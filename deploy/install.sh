#!/usr/bin/env bash
# Auf dem Raspberry Pi im Projektordner ausfuehren.
set -euo pipefail
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
mkdir -p data logs
if [ ! -f secrets.json ]; then
  cp secrets.example.json secrets.json
  chmod 600 secrets.json
  echo ">> secrets.json angelegt (chmod 600) - bitte echte Werte eintragen."
fi
./.venv/bin/python main.py --init-db
echo ">> Fertig. Testlauf:  ./.venv/bin/python main.py --once"
echo ">> Zeitsteuerung aktivieren:"
echo "   sudo cp deploy/hilo-pilot.service deploy/hilo-pilot.timer /etc/systemd/system/"
echo "   sudo systemctl daemon-reload && sudo systemctl enable --now hilo-pilot.timer"
