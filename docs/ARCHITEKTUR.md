# Architektur

HISOME ist eine **Python/Flask**-Anwendung mit einer **SQLite**-Datenbank. Alles läuft in
einem Prozess auf dem Raspberry Pi; lange Aufgaben (Generierung, Tageslauf) werden in
**Subprozesse** ausgelagert, damit der Webserver nie blockiert.

## Datenfluss (Überblick)

```
Quellen ──Radar──┐
PDF/Link ────────┤→ themen ──Stufe 1──→ ausgewählt ──Claude/Bild──→ entwürfe ──Stufe 2──→ freigegeben ──→ Kalender ──→ veröffentlicht
Fristen ─────────┤                                   (Countdown/Anlass direkt als Entwurf, auf den Tag geplant)
Anlass-Tage ─────┤
Wissens-Serie ───┘
```

## Module

| Datei | Aufgabe |
|-------|---------|
| `main.py` | Kommandozeile (CLI): `--serve`, `--daily`, `--radar`, `--generate`, `--render`, `--set-secret`, `--add-user`, `--list-pages`, `--publish` … |
| `web.py` | Flask-Dashboard: Kachel-Startseite, Stufe 1/2, Einplanung, **Content-Kalender**, Verwaltung, Login, 7-Uhr-Scheduler, Generierung-Subprozess |
| `config.py` | Nicht-geheime Konfiguration, Quellen-URLs (`SOURCES`, `SCRAPE_SOURCES`) |
| `db.py` | SQLite-Schema, Migrationen, Seed (Anlass-Tage, Wissens-Themen) |
| `secrets_store.py` | Sichere Geheimnisse: Umgebungsvariable oder geschützte `secrets.json` |
| `radar.py` | Themen-Radar (RSS + Scraper), Relevanzfilter, **HILO/BVL-Abgleich** |
| `scraper.py` | HTML-Scraper für Quellen ohne RSS (BVL) |
| `relevance.py` | Schlagwort-Klassifizierung (relevant / verworfen / neutral) |
| `sources.py` | Aktive Quellen aus der Konfiguration |
| `ingest.py` | Eigene Quellen: PDF/Link → Text → **Mehr-Themen-Extraktion** |
| `textgen.py` | Texterstellung via Claude (`generate`, `regenerate`, `extract_topics`) |
| `bildgen.py` | Bild im HILO-Referenzdesign (v10), rauschfrei gerendert |
| `bildmotiv.py` | Foto-Motiv via OpenAI **oder** gezeichnetes Icon (`icon:…`) |
| `countdown_motive.py` | Gezeichnete Icons (Kalender, Wecker, Sanduhr) |
| `fristen.py` | Fristen-Countdown (gestaffelte Erinnerungen) |
| `anlass.py` | Anlass-Tage (besondere Tage mit Steuer-Aufhänger) |
| `wissen.py` | Wissens-Serie (zeitlose Themen, füllt leere Tage) |
| `personalisierung.py` | Beitrag je Beratungsstelle anpassen (CTA + Begleittext) |
| `publish.py` | Veröffentlichung auf Facebook (Foto-Upload) + Instagram (vorbereitet) |
| `logging_setup.py` | Logging nach `logs/hilo.log` |

## Die vier Content-Streams

Alle Streams münden in dieselbe Freigabe und denselben Kalender:

1. **Aktuelles (News)** – `radar.py` wertet täglich die Quellen aus. Relevante externe
   News (Haufe, BFH) gehen in **Stufe 1** (Themenauswahl). HILO-eigene Steuertipps und
   BVL überspringen Stufe 1 und gehen direkt in die Texterstellung.
2. **Fristen-Countdown** – `fristen.py` erzeugt gestaffelte Erinnerungen vor den
   Abgabefristen (ab 3 Monaten 1×/Woche, letzte 4 Wochen 2×/Woche, letzte Woche täglich).
3. **Anlass-Tage** – `anlass.py` erzeugt zu besonderen Tagen (Tabelle `anlasstage`) einen
   Beitrag mit Steuer-Bezug; Wochenend-Tage erscheinen am Freitag davor.
4. **Wissens-Serie** – `wissen.py` füllt leere Kalendertage mit zeitlosen Themen
   (Tabelle `wissensthemen`), sobald der Vorrat offener Beiträge unter eine Schwelle fällt.

## Datenbank (Tabellen)

- `themen` – erkannte/aufgenommene Themen (Quelle, Titel, Status, Volltext, hash).
  Status: `vorgeschlagen` (Stufe 1) · `ausgewaehlt` (zur Texterstellung) · `verworfen` ·
  `dublette` / `erledigt` (HILO/BVL-Abgleich).
- `entwuerfe` – erzeugte Beiträge (Text als JSON, Bildpfad, Status, **geplant_fuer**).
  Status: `entwurf` (Stufe 2) · `freigegeben` (eingeplant) · `veroeffentlicht` · `verworfen`.
- `posts` – Veröffentlichungs-Protokoll (Kanal, Plattform-Post-ID, Fehler).
- `benutzer` – Dashboard-Konten (Rolle: admin / freigeber / redakteur).
- `audit` – Audit-Log aller relevanten Aktionen.
- `beratungsstellen` – Stellen mit Ort, Leitung, **fb_seite**, Buchungslink.
- `anlasstage` – kuratierte besondere Tage (MM-TT, Anlass, Steuer-Aufhänger).
- `wissensthemen` – zeitlose Themen (Titel, Aufhänger, zuletzt genutzt).

## Hintergrund-Abläufe

- **7-Uhr-Scheduler** (`web.py._daily_scheduler`): Thread im Webserver, startet einmal
  täglich ab 7:00 Uhr `main.py --daily` als Subprozess (datums-getaktet via `last_radar.txt`).
- **Generierung** (`web.py._start_generation`): „Texte & Bilder erzeugen" startet
  `main.py --generate N --render` als Subprozess – der Webserver bleibt frei.

## Bild-Design

Das Beitragsbild (1080×1080, `bildgen.py`) folgt dem **HILO-Referenzdesign v10**:
zwei Verlaufsbänder (Blau→Grün), weiße Überschrift oben, Text links, optionales
freigestelltes Foto bzw. gezeichnetes Motiv-Icon rechts, CTA im unteren Band, zwei
schwebende Kreise (Logo links, rotierender Slogan rechts). Alles programmatisch und
rauschfrei – Fotos optional via OpenAI, Icons komplett ohne Token.
