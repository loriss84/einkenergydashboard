#!/usr/bin/env python3
"""
Solar PV E-Ink Dashboard  –  v3
Raspberry Pi 3B+ + Waveshare 7.5" V2 (800x480, B/W)
Fonte dati: Home Assistant REST API
"""

import json
import sys
import os
import time
import logging
import math
import requests
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

WAVESHARE_LIB = os.path.expanduser('~/e-Paper/RaspberryPi_JetsonNano/python/lib')
EPD_W, EPD_H  = 800, 480
BLACK, WHITE  = 0, 255
PANEL_SEP     = 530

# ── Font ─────────────────────────────────────────────────────────────────────────
FONT_DIRS = [
    '/usr/share/fonts/truetype/dejavu/',
    '/usr/share/fonts/dejavu/',
    '/usr/share/fonts/truetype/freefont/',
]

def _find_font(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None

def load_fonts():
    bold = _find_font('DejaVuSans-Bold.ttf') or _find_font('FreeSansBold.ttf')
    reg  = _find_font('DejaVuSans.ttf')      or _find_font('FreeSans.ttf')
    try:
        return {
            'title':    ImageFont.truetype(bold, 20) if bold else ImageFont.load_default(),
            'value':    ImageFont.truetype(bold, 24) if bold else ImageFont.load_default(),
            'label':    ImageFont.truetype(reg,  14) if reg  else ImageFont.load_default(),
            'small':    ImageFont.truetype(reg,  12) if reg  else ImageFont.load_default(),
            'soc':      ImageFont.truetype(bold, 16) if bold else ImageFont.load_default(),
            'dev_name': ImageFont.truetype(bold, 14) if bold else ImageFont.load_default(),
            'dev_val':  ImageFont.truetype(bold, 20) if bold else ImageFont.load_default(),
        }
    except Exception:
        f = ImageFont.load_default()
        return {k: f for k in ('title','value','label','small','soc','dev_name','dev_val')}

# ── Helpers testo ─────────────────────────────────────────────────────────────────
def text_w(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]

def text_h(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[3] - b[1]

def draw_centered(draw, text, font, cx, y, fill=BLACK):
    draw.text((cx - text_w(draw, text, font)//2, y), text, font=font, fill=fill)

def draw_centered_bg(draw, text, font, cx, y, pad=5):
    """Testo centrato con sfondo bianco (maschera la freccia)."""
    w = text_w(draw, text, font)
    h = text_h(draw, text, font)
    draw.rectangle([cx - w//2 - pad, y - 2, cx + w//2 + pad, y + h + 2], fill=WHITE)
    draw.text((cx - w//2, y), text, font=font, fill=BLACK)

# ── Formattazione ─────────────────────────────────────────────────────────────────
def fmt_w(val, signed=False):
    if val is None:
        return '---'
    sign = ('+' if val > 0 else '') if signed else ''
    a = abs(val)
    if a >= 1000:
        return f'{sign}{val/1000:.2f} kW' if signed else f'{a/1000:.2f} kW'
    return f'{sign}{val:.0f} W' if signed else f'{a:.0f} W'

def fmt_soc(val):
    return f'{val:.0f}%' if val is not None else '--'

def fmt_device(val):
    if val is None:    return 'N/D'
    if abs(val) < 8:   return 'Spenta'
    a = abs(val)
    return f'{a/1000:.2f} kW' if a >= 1000 else f'{a:.0f} W'

# ── Icone meteo ───────────────────────────────────────────────────────────────────
def _sun(draw, cx, cy, r=28):
    """Sole: cerchio + raggi."""
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=BLACK, width=3, fill=WHITE)
    for deg in range(0, 360, 45):
        rad = math.radians(deg)
        x1 = cx + (r+5)  * math.cos(rad)
        y1 = cy + (r+5)  * math.sin(rad)
        x2 = cx + (r+14) * math.cos(rad)
        y2 = cy + (r+14) * math.sin(rad)
        draw.line([x1, y1, x2, y2], fill=BLACK, width=3)
    draw.ellipse([cx-r+8, cy-r+8, cx+r-8, cy+r-8], fill=BLACK)

def _moon(draw, cx, cy, r=28):
    """Luna crescente."""
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=BLACK)
    draw.ellipse([cx-r+r//2, cy-r, cx+r+r//2, cy+r], fill=WHITE)

def _cloud(draw, cx, cy, s=28):
    """Cloud outline. Restituisce la y del bordo inferiore."""
    bw = int(s * 1.5)
    by = cy + s // 3
    # Bumps (archi superiori)
    draw.arc([cx - bw//2, cy - s,     cx - bw//2 + s,   cy],          180, 360, fill=BLACK, width=3)
    draw.arc([cx - s//2,  cy - int(s*1.3), cx + s//2,   cy - s//6],   180, 360, fill=BLACK, width=3)
    draw.arc([cx + bw//2 - s, cy - s, cx + bw//2,       cy],          180, 360, fill=BLACK, width=3)
    # Lati
    draw.line([cx - bw//2,  cy,  cx - bw//2,  by], fill=BLACK, width=3)
    draw.line([cx + bw//2,  cy,  cx + bw//2,  by], fill=BLACK, width=3)
    # Base
    draw.line([cx - bw//2, by, cx + bw//2, by], fill=BLACK, width=3)
    return by

def _rain_drops(draw, cx, base_y, s=28, rows=2):
    """Gocce di pioggia sotto la nuvola."""
    bw = int(s * 1.5)
    for yi in range(rows):
        for xi in range(-2, 3):
            rx = cx + xi * bw // 4
            ry = base_y + 6 + yi * 12
            draw.line([rx, ry, rx - 3, ry + 9], fill=BLACK, width=2)

def _snow_dots(draw, cx, base_y, s=28):
    """Fiocchi di neve."""
    bw = int(s * 1.5)
    for xi in range(-2, 3):
        rx = cx + xi * bw // 4
        ry = base_y + 10
        r2 = 4
        draw.ellipse([rx-r2, ry-r2, rx+r2, ry+r2], fill=BLACK)

def _bolt_small(draw, cx, base_y, s=20):
    """Fulmine sotto la nuvola."""
    pts = [
        (cx + 5,  base_y + 2),
        (cx - 4,  base_y + s * 0.55),
        (cx + 6,  base_y + s * 0.55),
        (cx - 5,  base_y + s * 1.1),
        (cx + 4,  base_y + s * 0.6),
        (cx - 5,  base_y + s * 0.6),
    ]
    draw.polygon(pts, fill=BLACK)

def draw_weather_icon(draw, cx, cy, state, r=28):
    """Disegna l'icona meteo in base allo stato HA weather."""
    s = (state or 'sunny').lower().replace('-', '_')

    if s in ('sunny', 'clear'):
        _sun(draw, cx, cy, r)

    elif s == 'clear_night':
        _moon(draw, cx, cy, r)

    elif s in ('partlycloudy', 'partly_cloudy'):
        # Sole piccolo in alto a destra + nuvola in basso a sinistra
        _sun(draw, cx + r // 2, cy - r // 2, int(r * 0.55))
        _cloud(draw, cx - r // 4, cy + r // 4, int(r * 0.75))

    elif s in ('cloudy', 'overcast'):
        _cloud(draw, cx, cy, r)

    elif s in ('rainy', 'pouring', 'showers', 'shower_rain'):
        bottom = _cloud(draw, cx, cy - r // 4, r)
        _rain_drops(draw, cx, bottom, r, rows=2 if s == 'pouring' else 1)

    elif s in ('snowy', 'snowy_rainy'):
        bottom = _cloud(draw, cx, cy - r // 4, r)
        _snow_dots(draw, cx, bottom, r)

    elif s in ('lightning', 'lightning_rainy', 'thunderstorm'):
        bottom = _cloud(draw, cx, cy - r // 4, r)
        _bolt_small(draw, cx, bottom, r)
        if 'rainy' in s:
            _rain_drops(draw, cx + r // 2, bottom, r // 2, rows=1)

    elif s in ('fog', 'hazy', 'mist', 'haze'):
        for i, dy in enumerate(range(-r // 2, r // 2 + 1, r // 2)):
            x0 = cx - r + (i % 2) * 6
            x1 = cx + r - (i % 2) * 6
            draw.line([x0, cy + dy, x1, cy + dy], fill=BLACK, width=3)

    elif s in ('windy', 'wind'):
        for dy in [-r // 3, 0, r // 3]:
            draw.arc([cx - r, cy + dy - r // 4,
                      cx + r, cy + dy + r // 4],
                     200, 340, fill=BLACK, width=3)

    else:
        _sun(draw, cx, cy, r)  # fallback

# ── Altre icone ───────────────────────────────────────────────────────────────────
def draw_house(draw, cx, cy, s=30):
    draw.polygon([(cx, cy-s), (cx-s, cy), (cx+s, cy)], outline=BLACK, fill=WHITE)
    draw.line([(cx, cy-s), (cx-s, cy)], fill=BLACK, width=3)
    draw.line([(cx, cy-s), (cx+s, cy)], fill=BLACK, width=3)
    bx0, by0 = cx - s*0.75, cy
    bx1, by1 = cx + s*0.75, cy + s*1.1
    draw.rectangle([bx0, by0, bx1, by1], outline=BLACK, width=3, fill=WHITE)
    pw = s * 0.35
    draw.rectangle([cx-pw, by1-s*0.55, cx+pw, by1], outline=BLACK, width=2, fill=WHITE)

def draw_bolt(draw, cx, cy, s=28):
    pts = [(cx+7, cy-s),(cx-5, cy-3),(cx+9, cy-3),
           (cx-7, cy+s),(cx+5, cy+3),(cx-9, cy+3)]
    draw.polygon(pts, fill=BLACK)

def draw_battery_icon(draw, cx, cy, soc=50, s=26):
    bw = int(s * 1.7)
    bh = s
    x0, y0 = cx - bw//2, cy - bh//2
    draw.rectangle([x0, y0, x0+bw, y0+bh], outline=BLACK, width=3, fill=WHITE)
    term_h = bh // 3
    draw.rectangle([x0+bw, cy-term_h//2, x0+bw+7, cy+term_h//2], fill=BLACK)
    if soc is not None and soc > 0:
        fill_w = max(2, int((bw-8) * soc / 100))
        draw.rectangle([x0+4, y0+4, x0+4+fill_w, y0+bh-4], fill=BLACK)

# ── Frecce ────────────────────────────────────────────────────────────────────────
def midpoint_arrow(draw, x1, y1, x2, y2, active, head=10):
    mx, my = (x1+x2)/2, (y1+y2)/2
    angle  = math.atan2(y2-y1, x2-x1)
    if not active:
        draw.line([x1, y1, x2, y2], fill=BLACK, width=1)
        return
    draw.line([x1, y1, x2, y2], fill=BLACK, width=3)
    for da in [math.radians(145), math.radians(-145)]:
        a = angle + da
        draw.line([mx, my, mx + head*math.cos(a), my + head*math.sin(a)],
                  fill=BLACK, width=3)

def draw_soc_bar(draw, cx, y, soc, width=80, height=10):
    x0 = cx - width//2
    draw.rectangle([x0, y, x0+width, y+height], outline=BLACK, width=1)
    if soc and soc > 0:
        fill_w = max(1, int((width-2) * soc / 100))
        draw.rectangle([x0+1, y+1, x0+1+fill_w, y+height-1], fill=BLACK)

def draw_device_power_bar(draw, x0, y, val, home, width=200, height=8):
    draw.rectangle([x0, y, x0+width, y+height], outline=BLACK, width=1)
    if val and home and home > 0 and val > 0:
        fill_w = max(1, int((width-2) * min(1.0, val/home)))
        draw.rectangle([x0+1, y+1, x0+1+fill_w, y+height-1], fill=BLACK)

# ── Render ────────────────────────────────────────────────────────────────────────
def render(data, config):
    img   = Image.new('L', (EPD_W, EPD_H), WHITE)
    draw  = ImageDraw.Draw(img)
    fonts = load_fonts()

    solar   = data.get('solar')         or 0.0
    grid    = data.get('grid')          or 0.0
    bat_p   = data.get('battery_power') or 0.0
    bat_soc = data.get('battery_soc')   or 0.0
    home    = data.get('home')          or 0.0
    weather = data.get('weather', 'sunny') or 'sunny'
    devices = data.get('devices', {})

    conv = config.get('sign_convention', {})
    if not conv.get('grid_positive_is_import', True):
        grid = -grid
    if not conv.get('battery_positive_is_charge', True):
        bat_p = -bat_p

    THR = 15

    solar_active  = solar  > THR
    grid_import   = grid   > THR
    grid_export   = grid   < -THR
    bat_charge    = bat_p  > THR
    bat_discharge = bat_p  < -THR

    # ── Posizioni nodi ─────────────────────────────────────────────────────────
    SX, SY = 265, 108   # Solare / Meteo — più in alto
    HX, HY = 265, 300   # Casa
    GX, GY = 80,  300   # Rete
    BX, BY = 450, 300   # Batteria
    ICON_R = 30

    # ── Intestazione ───────────────────────────────────────────────────────────
    title = config.get('display', {}).get('title', 'Dashboard Fotovoltaico')
    draw.text((12, 8), title, font=fonts['title'], fill=BLACK)
    now_str = datetime.now().strftime('%d/%m  %H:%M')
    nw = text_w(draw, now_str, fonts['label'])
    draw.text((PANEL_SEP - nw - 10, 10), now_str, font=fonts['label'], fill=BLACK)
    draw.line([0, 32, PANEL_SEP, 32], fill=BLACK, width=1)

    # ── Connessioni ────────────────────────────────────────────────────────────
    midpoint_arrow(draw,
                   SX, SY + ICON_R + 4, HX, HY - ICON_R - 4,
                   active=solar_active)
    if grid_import:
        midpoint_arrow(draw, GX+ICON_R+4, GY, HX-ICON_R-4, HY, active=True)
    elif grid_export:
        midpoint_arrow(draw, HX-ICON_R-4, HY, GX+ICON_R+4, GY, active=True)
    else:
        draw.line([GX+ICON_R+4, GY, HX-ICON_R-4, HY], fill=BLACK, width=1)

    if bat_charge:
        midpoint_arrow(draw, HX+ICON_R+4, HY, BX-ICON_R-4, BY, active=True)
    elif bat_discharge:
        midpoint_arrow(draw, BX-ICON_R-4, BY, HX+ICON_R+4, HY, active=True)
    else:
        draw.line([HX+ICON_R+4, HY, BX-ICON_R-4, BY], fill=BLACK, width=1)

    # ── Icone ──────────────────────────────────────────────────────────────────
    draw_weather_icon(draw, SX, SY, weather, r=ICON_R)
    draw_house(draw, HX, HY, s=26)
    draw_bolt(draw, GX, GY, s=26)
    draw_battery_icon(draw, BX, BY, soc=bat_soc, s=26)

    # ── Etichette ──────────────────────────────────────────────────────────────
    # SOLARE — sfondo bianco per mascherare la freccia
    base = SY + ICON_R + 12
    draw_centered_bg(draw, 'Solare',     fonts['label'], SX, base)
    draw_centered_bg(draw, fmt_w(solar), fonts['value'], SX, base + 18)

    # CASA
    base = HY + ICON_R + 10
    draw_centered(draw, 'Casa',      fonts['label'], HX, base)
    draw_centered(draw, fmt_w(home), fonts['value'], HX, base + 17)

    # RETE
    base = GY + ICON_R + 10
    draw_centered(draw, 'Rete',                   fonts['label'], GX, base)
    draw_centered(draw, fmt_w(grid, signed=True), fonts['value'], GX, base + 17)

    # BATTERIA
    base = BY + ICON_R + 10
    draw_centered(draw, 'Batteria',               fonts['label'], BX, base)
    draw_centered(draw, fmt_w(bat_p, signed=True),fonts['value'], BX, base + 17)
    draw_soc_bar(draw, BX, base + 44, bat_soc, width=72, height=10)
    draw_centered(draw, fmt_soc(bat_soc), fonts['soc'], BX, base + 57)

    # ── Barra inferiore sinistra ───────────────────────────────────────────────
    bar_y = EPD_H - 36
    draw.line([0, bar_y, PANEL_SEP, bar_y], fill=BLACK, width=1)
    stats = []
    if solar > THR and home > THR:
        stats.append(f'Autoconsumo: {min(100, home/solar*100):.0f}%')
    if solar - home > THR:
        stats.append(f'Surplus: {fmt_w(solar - home)}')
    stats.append('Batt: ↑ carica' if bat_charge else ('Batt: ↓ scarica' if bat_discharge else 'Batt: standby'))
    draw_centered(draw, '   |   '.join(stats), fonts['small'], PANEL_SEP // 2, bar_y + 10)

    # ── Separatore verticale ───────────────────────────────────────────────────
    draw.line([PANEL_SEP, 0, PANEL_SEP, EPD_H], fill=BLACK, width=2)

    # ── Pannello dispositivi ───────────────────────────────────────────────────
    PX  = PANEL_SEP + 10
    PW  = EPD_W - PANEL_SEP - 10
    PC  = PANEL_SEP + PW // 2

    draw.text((PX + 4, 8), 'Carichi', font=fonts['title'], fill=BLACK)
    draw.line([PANEL_SEP, 32, EPD_W, 32], fill=BLACK, width=1)

    dev_list = config.get('devices', [])
    n = max(len(dev_list), 1)
    ROW_H = min((bar_y - 38) // n, 100)

    for i, dev in enumerate(dev_list):
        val  = devices.get(dev['entity'])
        name = dev.get('name', dev['entity'])
        y0   = 38 + i * ROW_H

        if i > 0:
            draw.line([PX, y0, EPD_W - 4, y0], fill=BLACK, width=1)

        draw.text((PX + 4, y0 + 4), name, font=fonts['dev_name'], fill=BLACK)

        val_str = fmt_device(val)
        vw = text_w(draw, val_str, fonts['dev_val'])
        draw.text((EPD_W - vw - 8, y0 + 4), val_str, font=fonts['dev_val'], fill=BLACK)

        draw_device_power_bar(draw, PX + 4, y0 + 30, val, home, width=PW - 8, height=9)

        if val and abs(val) >= 8 and home and home > 0:
            pct = min(100.0, abs(val) / home * 100)
            draw.text((PX + 4, y0 + 42), f'{pct:.0f}%', font=fonts['small'], fill=BLACK)

    draw.line([PANEL_SEP, bar_y, EPD_W, bar_y], fill=BLACK, width=1)
    total_dev = sum(v for v in devices.values() if v and v > 8)
    if total_dev > 0:
        draw.text((PX + 4, bar_y + 10),
                  f'Tot: {fmt_w(total_dev)}', font=fonts['small'], fill=BLACK)

    return img

# ── Home Assistant ────────────────────────────────────────────────────────────────
def ha_get(url, token, entity_id):
    """Legge stato numerico."""
    try:
        r = requests.get(f'{url.rstrip("/")}/api/states/{entity_id}',
                         headers={'Authorization': f'Bearer {token}',
                                  'Content-Type': 'application/json'},
                         timeout=10)
        r.raise_for_status()
        state = r.json().get('state', 'unknown')
        if state in ('unknown', 'unavailable', ''):
            return None
        return float(state)
    except Exception as e:
        logging.warning(f'HA: impossibile leggere {entity_id}: {e}')
        return None

def ha_get_str(url, token, entity_id):
    """Legge stato come stringa (per entità weather)."""
    try:
        r = requests.get(f'{url.rstrip("/")}/api/states/{entity_id}',
                         headers={'Authorization': f'Bearer {token}',
                                  'Content-Type': 'application/json'},
                         timeout=10)
        r.raise_for_status()
        return r.json().get('state', 'sunny')
    except Exception as e:
        logging.warning(f'HA: impossibile leggere {entity_id}: {e}')
        return 'sunny'

def fetch_data(config):
    url   = config['ha_url']
    token = config['ha_token']
    ents  = config['entities']

    result = {
        'solar':         ha_get(url, token, ents['solar']),
        'grid':          ha_get(url, token, ents['grid']),
        'battery_power': ha_get(url, token, ents['battery_power']),
        'battery_soc':   ha_get(url, token, ents['battery_soc']),
        'home':          ha_get(url, token, ents['home']),
        'weather':       ha_get_str(url, token, config.get('weather_entity', 'weather.forecast_casa')),
        'devices': {},
    }
    for dev in config.get('devices', []):
        result['devices'][dev['entity']] = ha_get(url, token, dev['entity'])
    return result

# ── Display e-ink ─────────────────────────────────────────────────────────────────
def send_to_epd(img, epd_model):
    sys.path.insert(0, WAVESHARE_LIB)
    try:
        mod = __import__(
            f'waveshare_epd.{"epd7in5" if epd_model == "epd7in5" else "epd7in5_V2"}',
            fromlist=['EPD']
        )
    except ImportError as e:
        logging.error(f'Libreria Waveshare non trovata in {WAVESHARE_LIB}: {e}')
        raise
    epd = mod.EPD()
    logging.info('Inizializzo display...')
    epd.init()
    epd.display(epd.getbuffer(img.convert('1')))
    logging.info('Display aggiornato. Vado in sleep.')
    epd.sleep()

# ── Scheduling ────────────────────────────────────────────────────────────────────
def _get_interval(schedule):
    if not schedule:
        return 300
    now       = datetime.now().time()
    day_start = _parse_time(schedule.get('day_start',  '06:30'))
    day_end   = _parse_time(schedule.get('day_end',    '22:00'))
    if day_start <= now < day_end:
        return schedule.get('day_interval',   120)
    return schedule.get('night_interval', 300)

def _parse_time(t):
    h, m = map(int, t.split(':'))
    return datetime.min.replace(hour=h, minute=m).time()

# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                os.path.join(os.path.dirname(__file__), 'solar_dashboard.log'),
                encoding='utf-8'
            ),
        ]
    )

    preview_mode = '--preview' in sys.argv
    once_mode    = '--once' in sys.argv or preview_mode

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path) as f:
        config = json.load(f)

    epd_model = config.get('epd_model', 'epd7in5_V2')
    schedule  = config.get('schedule', {})

    logging.info('=== Solar Dashboard v3 avviato ===')

    while True:
        try:
            logging.info('Recupero dati da Home Assistant...')
            data = fetch_data(config)
            logging.info(f'Meteo: {data["weather"]} | Solar: {data["solar"]} | Home: {data["home"]}')

            img = render(data, config)

            if preview_mode:
                out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'preview.png')
                img.save(out)
                logging.info(f'Preview: {out}')
            else:
                send_to_epd(img, epd_model)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f'Errore: {e}', exc_info=True)

        if once_mode:
            break

        interval = _get_interval(schedule)
        logging.info(f'Prossimo aggiornamento tra {interval}s...')
        time.sleep(interval)


if __name__ == '__main__':
    main()
