#!/bin/bash
# ─────────────────────────────────────────────────────────────
# install.sh  –  Setup Solar E-Ink Dashboard
# Raspberry Pi 3B+ + Waveshare 7.5" e-Paper Driver HAT
# ─────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EPAPER_LIB="$HOME/e-Paper"

echo "========================================"
echo "  Solar Dashboard – Installazione"
echo "========================================"
echo ""

# ── 1. Aggiorna pacchetti ─────────────────────────────────────
echo "[1/6] Aggiorno pacchetti sistema..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-pip \
    python3-pil \
    python3-requests \
    python3-rpi.gpio \
    fonts-dejavu-core \
    git \
    libopenjp2-7 \
    libatlas-base-dev

# ── 2. Abilita SPI ────────────────────────────────────────────
echo ""
echo "[2/6] Verifico SPI..."
if ! lsmod | grep -q spi_bcm2835; then
    echo "  SPI non attivo. Abilito in /boot/config.txt..."
    if ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null && \
       ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
        # Supporto sia Bullseye che Bookworm
        BOOT_CFG="/boot/config.txt"
        [ -f "/boot/firmware/config.txt" ] && BOOT_CFG="/boot/firmware/config.txt"
        echo "dtparam=spi=on" | sudo tee -a "$BOOT_CFG"
        echo "  ATTENZIONE: SPI abilitato. Riavvio necessario al termine."
        REBOOT_NEEDED=1
    fi
else
    echo "  SPI già attivo."
fi

# ── 3. Libreria Python Waveshare ──────────────────────────────
echo ""
echo "[3/6] Installo libreria Waveshare e-Paper..."
if [ ! -d "$EPAPER_LIB" ]; then
    echo "  Clono repo Waveshare..."
    git clone --depth=1 https://github.com/waveshare/e-Paper.git "$EPAPER_LIB"
else
    echo "  Repo già presente in $EPAPER_LIB. Aggiorno..."
    cd "$EPAPER_LIB" && git pull --ff-only 2>/dev/null || true
    cd "$SCRIPT_DIR"
fi

# Installa il pacchetto Python Waveshare
cd "$EPAPER_LIB/RaspberryPi_JetsonNano/python"
pip3 install . --break-system-packages 2>/dev/null \
    || pip3 install . \
    || echo "  (installazione pip opzionale fallita, uso percorso diretto)"
cd "$SCRIPT_DIR"

# ── 4. Dipendenze Python extra ────────────────────────────────
echo ""
echo "[4/6] Installo dipendenze Python..."
pip3 install requests pillow --break-system-packages 2>/dev/null \
    || pip3 install requests pillow

# ── 5. Configura il progetto ──────────────────────────────────
echo ""
echo "[5/6] Configurazione..."
if [ ! -f "$SCRIPT_DIR/config.json" ]; then
    echo "  ERRORE: config.json non trovato in $SCRIPT_DIR"
    echo "  Copia config.json nella stessa cartella di questo script."
    exit 1
fi

# Verifica che il token non sia quello di default
if grep -q "IL_TUO_TOKEN_LONG_LIVED" "$SCRIPT_DIR/config.json"; then
    echo ""
    echo "  ⚠️  IMPORTANTE: modifica config.json con il tuo token HA!"
    echo "  In HA: Profilo → Token accesso a lungo termine → Crea token"
    echo ""
fi

chmod +x "$SCRIPT_DIR/solar_dashboard.py"

# ── 6. Test preview (senza display fisico) ────────────────────
echo "[6/6] Eseguo test preview..."
python3 "$SCRIPT_DIR/solar_dashboard.py" --preview 2>&1 | tail -5
if [ -f "$SCRIPT_DIR/preview.png" ]; then
    echo "  ✓ preview.png generata correttamente."
else
    echo "  ⚠  Preview non generata (controlla i log)."
fi

# ── Riepilogo ─────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Installazione completata!"
echo "========================================"
echo ""
echo "Prossimi passi:"
echo ""
echo "  1. Modifica config.json con:"
echo "     - ha_url  (es. http://192.168.1.x:8123)"
echo "     - ha_token (token HA long-lived)"
echo ""
echo "  2. Test manuale:"
echo "     python3 $SCRIPT_DIR/solar_dashboard.py --preview"
echo "     # apri preview.png per verificare il layout"
echo ""
echo "  3. Primo avvio sul display reale:"
echo "     python3 $SCRIPT_DIR/solar_dashboard.py --once"
echo ""
echo "  4. Installa come servizio automatico:"
echo "     sudo cp $SCRIPT_DIR/solar-dashboard.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now solar-dashboard"
echo ""

if [ "${REBOOT_NEEDED}" = "1" ]; then
    echo "  ⚠️  RIAVVIA il Raspberry Pi per attivare SPI:"
    echo "     sudo reboot"
    echo ""
fi
