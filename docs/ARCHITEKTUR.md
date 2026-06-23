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
| `bildgen.py` | Bild im HILO-Magazin-Design (v11): Foto-Hintergrund + Textkarte + CI-Kreise |
| `bildmotiv.py` | Emotionales Szene-Foto via OpenAI **oder** gezeichnetes Icon (`icon:…`) |
| `countdown_motive.py` | Gezeichnete Icons (Kalender, Wecker, Sanduhr) |
| `fristen.py` | Fristen-Countdown (gestaffelte Erinnerungen) |
| `anlass.py` | Anlass-Tage (besondere Tage mit Steuer-Aufhänger) |
| `wissen.py` | Wissens-Serie (zeitlose Themen, füllt leere Tage) |
| `personalisierung.py` | Beitrag je Beratungsstelle anpassen (CTA + Begleittext) |
| `pool.py` | Zufalls-Pool: Kanäle, „nie doppelt"-Logik je Stelle/Kanal, tägliche Ziehung, Restbestand/Warnung |
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
  Status: `entwurf` (Stufe 2) · `freigegeben` (eingeplant) · `veroeffentlicht` · `verworfen` ·
  `pool` (zeitloser Beitrag im Zufalls-Pool).
- `geplante_posts` – terminierte Veröffentlichungen (Stelle/Seite, Kanal, Zeit, Status).
  Spalte `pool=1` markiert Einträge aus der täglichen Pool-Ziehung (Beitrag bleibt wiederverwendbar).
- `pool` – Mitgliedschaft im Zufalls-Pool (`entwurf_id`, `aktiv`, freigegeben_am/_von).
- `pool_nutzung` – „nie doppelt"-Gedächtnis: `UNIQUE(entwurf_id, stelle_id, kanal)` – jeder Beitrag
  je Stelle genau einmal pro Kanal (zeitversetzt über Kanäle erlaubt).
- `posts` – Veröffentlichungs-Protokoll (Kanal, Plattform-Post-ID, Fehler).
- `benutzer` – Dashboard-Konten (Rolle: admin / freigeber / redakteur).
- `audit` – Audit-Log aller relevanten Aktionen.
- `beratungsstellen` – Stellen mit Ort, Leitung, **fb_seite**, Buchungslink,
  `wa_status_aktiv` (WhatsApp-Status für diese Stelle ziehen) und `wa_kanal_invite`
  (WhatsApp-Kanal-Einladungslink).
- `anlasstage` – kuratierte besondere Tage (MM-TT, Anlass, Steuer-Aufhänger).
- `wissensthemen` – zeitlose Themen (Titel, Aufhänger, zuletzt genutzt).

## Hintergrund-Abläufe

- **7-Uhr-Scheduler** (`web.py._daily_scheduler`): Thread im Webserver, startet einmal
  täglich ab 7:00 Uhr `main.py --daily` als Subprozess (datums-getaktet via `last_radar.txt`).
- **Generierung** (`web.py._start_generation`): „Texte & Bilder erzeugen" startet
  `main.py --generate N --render` als Subprozess – der Webserver bleibt frei.
- **Pool-Scheduler** (`web.py._pool_scheduler` → `_pool_tagesziehung`): Thread im Webserver,
  zieht einmal täglich ab 7:00 Uhr (datums-getaktet via `last_pool_ziehung.txt`) je aktiver
  Beratungsstelle und je **verfügbarem** Kanal einen offenen Pool-Beitrag, legt einen
  `geplante_posts`-Eintrag (`pool=1`) an und schreibt `pool_nutzung`. Idempotent (1×/Tag,
  keine Doppel-Einplanung je Stelle/Kanal/Tag).
  - **Kanal-Verfügbarkeit** (`_kanal_verfuegbarkeit`): Facebook bei `fb_seite`, Instagram nur bei
    `ig_id` (aus `_pages()`), WhatsApp-Status bei `wa_status_aktiv=1`, WhatsApp-Kanal bei gesetztem
    `wa_kanal_invite`. Nicht vorhandene Kanäle werden übersprungen.
  - **Frequenz/Wochenende:** `_kanal_heute_faellig` (Status täglich, Kanal an `HILO_WA_KANAL_TAGE`,
    Default Di+Fr) und `_pool_wochenend_eids` (am Wochenende nur `quelle='wissen'`,
    `HILO_POOL_WOCHENEND_FILTER`).
  - **WhatsApp-Veröffentlichung** (`_veroeffentliche_whatsapp` in `_publiziere_geplant`, **nur** für
    `pool=1 + whatsapp_*`): postet via `_wa_call` an `/post-status` bzw. `/post-channel` des
    WhatsApp-Dienstes (`whatsapp/server.mjs`, eine globale Baileys-Session) mit personalisiertem
    Text und – für Status – personalisiertem 9:16-Bild. Dienst-Fehler → `status='fehler'`, kein
    Status-Flip. Der FB/IG-Pfad (`_veroeffentliche_ziel`) bleibt unberührt.

## Bild-Design

Das Beitragsbild (1080×1080, `bildgen.py`) folgt dem **HILO-Magazin-Design v11** (emotionaler,
foto-getriebener Look, seit Issue #129):

- **Foto als Vollbild-Hintergrund** (cover-Crop). Fehlt ein Foto, greift ein warmer
  Creme-Verlauf-Fallback (`_creme_bg`) – das Bild sieht auch ohne KI-Foto gut aus.
- **Integriertes weißes Textfeld** (`_card`, abgerundet, weicher Schatten + Scrim für Kontrast)
  mit: grüner Saison-/Themen-Pille, Überschrift, **optionaler Hero-Zahl** (groß, grün) **oder** –
  ohne Zahl – größerer Überschrift + Hook-Subline, gezeichneten Symbol-Bullets und Gold-CTA-Pille.
- **CI-Kreise bleiben** (Markenzeichen): weißer Logo-Kreis + blauer Slogan-Kreis, Position rotiert
  je Beitrag (`pick_circle_pos`). Ein Stellen-Porträt (`portrait`) ersetzt optional einen Kreis.
- **Foto-Motiv** (`bildmotiv.py`): emotionale Magazin-/Editorial-Szene **mit Umgebung** (nicht mehr
  freigestellt) via OpenAI `gpt-image-1` (`background=opaque`, 1024×1024, gecacht); `icon:`-Motive
  ohne Token. Das Szene-Motiv (`szene_motiv`) liefert die Text-KI je Beitrag. Der Prompt komponiert
  die Szene als **Rahmen** um eine ruhige Bildmitte (Negativraum), damit das Textfeld nichts
  Bildwichtiges verdeckt; die Karte hält dazu Rand an allen vier Seiten, passt sich aber dem
  Textumfang an (kein Überlauf unter die Karte). (#131)

Das bisherige Banderdesign v10 ist über den Git-Tag `design-backup-2026-06-23` wiederherstellbar.
