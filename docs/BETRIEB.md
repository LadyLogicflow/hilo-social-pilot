# Betrieb (Installation & Wartung)

HISOME läuft als Web-Dienst auf einem Raspberry Pi. Diese Anleitung beschreibt
Installation, Dienste, Geheimnisse und die Facebook-Anbindung.

## 1. Projekt holen

```bash
cd ~
git clone <repo-url> hilo-social-pilot
cd hilo-social-pilot
```

Aktualisieren später jeweils mit `git pull` (danach den Dashboard-Dienst neu starten).

## 2. Virtuelle Umgebung & Abhängigkeiten

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

> **Wichtig:** Immer die `.venv` benutzen (`.venv/bin/python …`). Das System-Python hat
> die benötigten Bibliotheken (z.B. `feedparser`) sonst nicht.

## 3. Datenbank & Admin-Konto

```bash
.venv/bin/python main.py --init-db
.venv/bin/python main.py --add-user catrin     # Passwort wird verdeckt abgefragt -> Admin
```

## 4. Geheimnisse hinterlegen

Geheime Zugänge kommen **nie** ins Repo, sondern in eine geschützte `secrets.json`
(chmod 600). Setzen jeweils verdeckt:

```bash
.venv/bin/python main.py --set-secret openai_api_key      # PFLICHT: Text + Bild (3-Stufen-Workflow)
.venv/bin/python main.py --set-secret anthropic_api_key   # optional: nur Themen-Extraktion aus PDFs/Links
.venv/bin/python main.py --set-secret meta_user_token     # Facebook-Veröffentlichung
```

> **Wichtig (Stand 2026-07-30):** `openai_api_key` ist jetzt der zentrale Schlüssel - alle
> vier Content-Ströme (Aktuelles/Fristen/Anlass/Wissen) erzeugen Text UND Bild über den
> 3-Stufen-Workflow (GPT-5.6 Terra + GPT Image 2), siehe
> [ARCHITEKTUR.md](ARCHITEKTUR.md#bild-design). Ohne `openai_api_key` werden **keine neuen
> Beiträge** erzeugt (Log: "uebersprungen: kein 'openai_api_key' hinterlegt"). `anthropic_api_key`
> wird nur noch für die Themen-Extraktion aus hochgeladenen PDFs/Links gebraucht
> (`textgen.extract_topics`) - ohne ihn funktioniert alles andere normal weiter.

Optional für ein Langzeit-Token (60 Tage): `meta_app_id` und `meta_app_secret` setzen –
HISOME tauscht das Token dann automatisch (`publish.ensure_long_lived`).

## 5. Dashboard als Dienst

Das Dashboard läuft dauerhaft (inkl. 7-Uhr-Automatik). Einrichtung über das mitgelieferte
Skript bzw. eine systemd-Unit auf Port 8530:

```bash
sudo systemctl restart hilo-dashboard   # nach jedem git pull
```

> Nach Code-Änderungen muss der Dienst **neu gestartet** werden – ein laufender Webserver
> lädt neuen Code nicht von selbst.

Die tägliche Themen-Automatik ist **im Dashboard eingebaut** (Scheduler-Thread): einmal
täglich ab 7:00 Uhr startet `main.py --daily` als Subprozess. Ein separater Cron/Timer
ist nicht nötig, solange der Dashboard-Dienst läuft.

## 6. Facebook-Anbindung (Kurzfassung)

1. Meta-App mit Anwendungsfall **„Instagram API mit Facebook-Login"**.
2. Berechtigungen: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
   `instagram_basic`, `instagram_content_publish`, `business_management`.
3. Im Graph API Explorer ein Nutzer-Token erzeugen (alle Seiten + IG-Konten freigeben),
   per `--set-secret meta_user_token` hinterlegen.
4. Prüfen: `.venv/bin/python main.py --list-pages` zeigt die verbundenen Seiten.
5. In der Verwaltung jede Beratungsstelle mit ihrer **Facebook-Seiten-ID** verknüpfen.

> Instagram-Veröffentlichung ist im Code vorbereitet (`publish.publish_instagram`), braucht
> aber eine öffentliche Bild-URL (der Pi ist privat) und ein Token mit IG-Freigabe.

## 7. Tagesablauf prüfen / manuell auslösen

```bash
.venv/bin/python main.py --daily      # Radar + Countdowns + Anlass + Wissen + Bilder
.venv/bin/python main.py --radar      # nur Themen holen
```

Logdateien: `logs/hilo.log` (App), `data/generieren.log` und `data/radar.log` (Subprozesse).

## 8. Sicherung

Wichtige, nicht im Repo liegende Dateien: `secrets.json` und `data/hilo.db`
(Datenbank mit Themen, Entwürfen, Verwaltung). Regelmäßig sichern.
