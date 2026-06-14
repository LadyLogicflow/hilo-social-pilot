# HISOME – HILO Social Media Tool

HISOME erstellt für die Beratungsstellen des Lohnsteuerhilfevereins **HILO** automatisiert
Social-Media-Beiträge: Es sammelt steuerrelevante Themen, lässt **Claude** passende Texte
schreiben, rendert **programmatisch** ein Beitragsbild im HILO-Referenzdesign (rauschfrei,
ohne Bild-Token) und stellt alles in einem **Freigabe-Dashboard** zur Kontrolle bereit.
Veröffentlicht wird **erst nach menschlicher Freigabe** auf Facebook (Instagram folgt).

Das Tool läuft als Web-Anwendung auf einem **Raspberry Pi** – komplett über den Browser
bedienbar, kein Terminal nötig.

---

## Inhaltsverzeichnis der Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) | Aufbau, Module, Datenfluss, Datenbank, Content-Streams |
| [docs/BEDIENUNG.md](docs/BEDIENUNG.md) | Bedienung des Dashboards (Schritt für Schritt) |
| [docs/BETRIEB.md](docs/BETRIEB.md) | Installation, Dienste, Automatik, Secrets, Facebook-Anbindung |

---

## Was HISOME kann

- **Themen-Radar** – täglich um 7:00 Uhr werden Quellen automatisch ausgewertet
  (HILO-Steuertipps, BVL, Haufe, Bundesfinanzhof).
- **Zwei-Stufen-Freigabe** – erst Themen auswählen (Stufe 1), dann fertige Beiträge
  freigeben (Stufe 2). Spart Bild-Token, weil nur Ausgewähltes erzeugt wird.
- **Eigene Quellen** – PDFs oder Links einwerfen; HISOME zerlegt sie automatisch in
  einzelne Themen.
- **HILO/BVL-Abgleich** – behandeln HILO und BVL dasselbe Thema, gewinnt HILO; ein
  bereits veröffentlichtes Gegenstück macht das Duplikat zu „erledigt".
- **Content-Kalender** – freigegebene Beiträge werden auf die nächsten freien Werktage
  verteilt (max. 1/Tag, Sa+So frei), Termine verschiebbar.
- **Fristen-Countdown** – gestaffelte Erinnerungen vor den Abgabefristen, mit Motiv-Icons
  (Kalender, Wecker, Sanduhr).
- **Anlass-Tage** – besondere Tage mit Steuer-Aufhänger (z.B. Tag des Bieres → Biersteuer).
- **Wissens-Serie** – zeitlose Themen füllen leere Kalendertage, damit nie eine Lücke
  entsteht.
- **Personalisierung je Beratungsstelle** – gleiches Bild, aber der CTA nennt die Stelle
  und der Begleittext bekommt lokalen Bezug + Buchungslink.

## Schnellstart (Entwicklung)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py --init-db
.venv/bin/python main.py --add-user admin      # Dashboard-Admin anlegen
.venv/bin/python main.py --serve               # Dashboard auf Port 8530
```

Geheime Zugänge (Claude, OpenAI, Facebook) werden **nicht** im Repo gespeichert, sondern
über `python main.py --set-secret NAME` in eine geschützte `secrets.json` (chmod 600) gelegt.

## Wichtigste Kommandos

```bash
python main.py --serve            # Dashboard (Webserver) starten
python main.py --daily            # Tageslauf: Radar + Countdowns + Anlass + Wissen + Bilder
python main.py --radar            # nur Themen-Radar
python main.py --generate N       # N Textentwürfe für ausgewählte Themen erzeugen
python main.py --render           # fehlende Bilder rendern
python main.py --set-secret NAME  # Geheimnis sicher hinterlegen
python main.py --add-user NAME    # Dashboard-Benutzer (Admin) anlegen
python main.py --list-pages       # verbundene Facebook-Seiten anzeigen
```

## Sicherheit & Datenschutz

- Echte Zugänge gehören **nicht** ins Repo (`secrets.json`, chmod 600).
- In das Tool nur **öffentliche/unkritische** Inhalte – **niemals Mandanten- oder Steuerdaten**.
- Jede Veröffentlichung wird im Audit-Log protokolliert.
