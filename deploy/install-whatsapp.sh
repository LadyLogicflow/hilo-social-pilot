#!/usr/bin/env bash
# Richtet den HISOME WhatsApp-Dienst (Node/Baileys) auf dem Pi ein.
# Auf dem Pi im Projektordner ausfuehren:  bash deploy/install-whatsapp.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
WA_DIR="$DIR/whatsapp"
USER_NAME="$(whoami)"
PORT="${HILO_WHATSAPP_PORT:-8769}"
UNIT="/etc/systemd/system/hilo-whatsapp.service"

# 1) Node.js pruefen (>= 18 noetig)
if ! command -v node >/dev/null 2>&1; then
  echo "FEHLER: Node.js ist nicht installiert." >&2
  echo "Bitte einmalig installieren (Raspberry Pi OS, aktuelle LTS):" >&2
  echo "  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -" >&2
  echo "  sudo apt-get install -y nodejs" >&2
  echo "Danach dieses Skript erneut ausfuehren." >&2
  exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "FEHLER: Node.js $(node -v) ist zu alt (>= 18 noetig)." >&2
  echo "Bitte aktualisieren (siehe https://deb.nodesource.com)." >&2
  exit 1
fi
NODE_BIN="$(command -v node)"

echo "Projekt:  $DIR"
echo "Benutzer: $USER_NAME"
echo "Node:     $NODE_BIN ($(node -v))"
echo "Port:     $PORT (nur localhost)"

# 2) Abhaengigkeiten installieren
echo "Installiere Node-Abhaengigkeiten ..."
( cd "$WA_DIR" && npm install --omit=dev --no-audit --no-fund )

# 3) systemd-Unit schreiben
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=HISOME WhatsApp-Dienst (Baileys)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$WA_DIR
ExecStart=$NODE_BIN $WA_DIR/server.mjs
Environment=HILO_WHATSAPP_PORT=$PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now hilo-whatsapp.service

echo
echo "FERTIG. Der WhatsApp-Dienst laeuft jetzt im Hintergrund (127.0.0.1:$PORT)."
echo "  Status:   sudo systemctl status hilo-whatsapp.service"
echo "  Logs:     journalctl -u hilo-whatsapp.service -f"
echo "  Neustart: sudo systemctl restart hilo-whatsapp.service"
echo
echo "Jetzt im Dashboard oben auf 'WhatsApp' klicken und den QR-Code mit der"
echo "Beratungsstellen-Nummer scannen (WhatsApp > Verknuepfte Geraete > Geraet verknuepfen)."
