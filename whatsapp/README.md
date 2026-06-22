# HISOME WhatsApp-Dienst (Baileys)

Kleiner Node-Prozess, der **neben** dem Python-Dashboard auf dem Pi läuft und
WhatsApp **Status** und **Kanal**-Beiträge posten kann. Er stellt eine schlanke
HTTP-API bereit (nur `127.0.0.1`), die das Dashboard aufruft.

> **Wichtig:** WhatsApp-Status hat keine offizielle API. Dieser Dienst nutzt das
> **Linked-Device-Modell** (QR-Scan, wie WhatsApp Web). Pro Nummer wird die
> Sitzung einmal per QR verknüpft und liegt danach persistent in `auth/`.
> Es bleibt ein (geringes) Restrisiko, dass die Nummer von WhatsApp gesperrt wird –
> deshalb eigene Beratungsstellen-Nummern verwenden, keine privaten.

## Einrichtung auf dem Pi (einmalig)

1. **Node.js installieren** (falls noch nicht vorhanden, aktuelle LTS):
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
   sudo apt-get install -y nodejs
   ```
2. **Dienst einrichten** (installiert Abhängigkeiten + systemd-Service):
   ```bash
   bash deploy/install-whatsapp.sh
   ```
3. Im Dashboard oben auf **„WhatsApp"** klicken, den **QR-Code** mit der
   Beratungsstellen-Nummer scannen (WhatsApp → *Verknüpfte Geräte* →
   *Gerät verknüpfen*). Fertig – die Verbindung bleibt bestehen.

## Bedienung / Wartung

```bash
sudo systemctl status  hilo-whatsapp.service   # Status
journalctl -u hilo-whatsapp.service -f         # Logs
sudo systemctl restart hilo-whatsapp.service   # Neustart
```

## HTTP-API (intern, nur localhost)

| Methode | Pfad            | Zweck                                            |
|---------|-----------------|--------------------------------------------------|
| GET     | `/status`       | `{ state, qr, me, error }`                       |
| GET     | `/channels`     | Bekannte Kanäle (best effort)                    |
| POST    | `/post-status`  | `{ imagePath?, caption, statusJidList? }`        |
| POST    | `/post-channel` | `{ jid` oder `invite, imagePath?, caption }`     |
| POST    | `/logout`       | Sitzung trennen, Auth löschen, neuer QR          |

`state`: `init` → `qr` → `connected` (oder `closed`/`logged_out`).

## Konfiguration (Umgebungsvariablen)

| Variable                | Default                | Bedeutung                          |
|-------------------------|------------------------|------------------------------------|
| `HILO_WHATSAPP_PORT`    | `8769`                 | Port der lokalen HTTP-API          |
| `HILO_WHATSAPP_AUTH`    | `whatsapp/auth`        | Ordner für die Sitzungs-Daten      |
| `HILO_WHATSAPP_LOGLEVEL`| `warn`                 | `debug`/`info`/`warn`/`error`      |

Das Dashboard erreicht den Dienst über `HILO_WHATSAPP_URL`
(Default `http://127.0.0.1:8769`, in `config.py`).
