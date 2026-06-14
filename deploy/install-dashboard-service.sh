#!/usr/bin/env bash
# Richtet das HILO-Freigabe-Dashboard als systemd-Dienst ein (laeuft im Hintergrund,
# startet beim Booten automatisch, startet nach Absturz neu).
# Aufruf im Projektordner:  bash deploy/install-dashboard-service.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"
PORT="${HILO_DASHBOARD_PORT:-8530}"
PY="$DIR/.venv/bin/python"
UNIT="/etc/systemd/system/hilo-dashboard.service"

if [ ! -x "$PY" ]; then
  echo "FEHLER: $PY nicht gefunden. Bitte zuerst 'bash deploy/install.sh' ausfuehren." >&2
  exit 1
fi

echo "Projekt:  $DIR"
echo "Benutzer: $USER_NAME"
echo "Port:     $PORT"

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=HILO Social-Media-Pilot - Freigabe-Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$PY $DIR/main.py --serve
Environment=HILO_DASHBOARD_PORT=$PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now hilo-dashboard.service
echo
echo "FERTIG. Das Dashboard laeuft jetzt im Hintergrund (Port $PORT)."
echo "  Status:   sudo systemctl status hilo-dashboard.service"
echo "  Logs:     journalctl -u hilo-dashboard.service -f"
echo "  Neustart: sudo systemctl restart hilo-dashboard.service"
echo "  Stoppen:  sudo systemctl stop hilo-dashboard.service"
