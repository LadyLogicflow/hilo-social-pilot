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
| `bildgen.py` | Bild-Layout: 3 Stile (Standard / KI-Tafel / Kreativ), Textkarte bzw. Tafel-/Träger-Device + CI-Kreise |
| `bildmotiv.py` | Foto-Erzeugung via OpenAI (gpt-image-2) **oder** Ideogram; Szene-/Tafel-/Kreativ-Prompts + Cache, `icon:`-Motive |
| `stilwahl.py` | Bild-Stil zufällig pro Beitrag aus den aktiven Stilen (`aktiver_stil`, „Anderes Bild") |
| `schauplatz.py` | Schauplätze: saisonale/themen-passende Umgebung je Beitrag (Rotation, nie doppelt) |
| `traeger.py` | Botschafts-Träger (Tafel/Rahmen/Holzschild …): Hybrid-Auswahl (Zufall + nie doppelt + Themen) |
| `wartung.py` | Cache-Aufräumung: löscht nur ungenutzte KI-Fotos (orphan-basiert, Pool/aktiv geschützt) |
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
- `einstellungen` – globale Schlüssel-Wert-Einstellungen (z.B. `bild_tool` = openai/ideogram,
  `bild_stil_standard`/`_ki_tafel`/`_kreativ` = welche Bild-Stile im Zufalls-Topf sind).
- `schauplaetze` – pflegbare Liste schöner Umgebungen (Beschreibung, Jahreszeit, aktiv, zuletzt_genutzt);
  je Beitrag wird einer gezogen (Rotation, nie doppelt im Zyklus).
- `traeger` – pflegbare Liste der Botschafts-Träger (Name, prompt_snippet, aktiv, zuletzt_genutzt).

Die `entwuerfe.text`-JSON trägt pro Beitrag u.a. `bild_stil`, `schauplatz`, `traeger`, `kreativ_motiv`,
`szene_motiv`, `hero` – einmal bei der Erzeugung gewürfelt/erzeugt und dann stabil (Cache + Re-Render).

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
- **Cache-Aufräumung** (`web.py._cache_cleanup_scheduler` → `wartung.aufraeumen_motive`): Thread,
  einmal täglich (Marker `last_cache_cleanup.txt`), löscht aus `DATA_DIR/motive/` nur KI-Fotos,
  die **kein aktiver Beitrag** mehr braucht (orphan-basiert, 14-Tage-Schonfrist; Pool-/aktive Fotos
  und `icon_*` werden NIE gelöscht). Verwaltung zeigt Cache-Größe + freien Speicher + Knopf.

## Bild-Design

Das Beitragsbild (1080×1080, `bildgen.py`) entsteht in **drei Stilen**, die **zufällig je Beitrag**
gemischt werden (`stilwahl.aktiver_stil`; in der Verwaltung je Stil an/aus, „Anderes Bild" in der
Freigabe würfelt neu):

1. **Standard** – Foto-Vollbild-Hintergrund (cover-Crop; Creme-Fallback `_creme_bg` ohne Foto) +
   integriertes weißes Textfeld (`_card`, Scrim, Rand an allen vier Seiten, wächst mit dem Text –
   kein Überlauf, #131) mit Saison-Pille, Überschrift, **optionaler Hero-Zahl** oder größerer
   Überschrift + Hook, Symbol-Bullets und **grüner CTA-Pille** (HILO-CI, #135).
2. **KI-Tafel** – die Bild-KI schreibt **Überschrift + Stichpunkte** selbst auf einen **Träger**
   (Tafel/Rahmen/Holzschild/… aus `traeger`), der in einer schönen **Umgebung** (`schauplaetze`,
   saisonal/themen-passend) steht; CTA + CI-Kreise kommen weiter per Code-Overlay (#132/#139/#140/#142).
3. **Kreativ** – ein **kinoreifes, fotorealistisches Foto OHNE Text** (Art-Director-Schritt:
   `textgen.art_director_motiv` lässt Claude die Szene aus dem Beitrag entwerfen), Botschaft + CI
   kommen wie im Standard-Stil per Code-Overlay (#143).

- **CI-Kreise** (Markenzeichen): weißer Logo-Kreis + blauer Slogan-Kreis, Position rotiert je
  Beitrag (`pick_circle_pos`); ein Stellen-Porträt (`portrait`) ersetzt optional einen Kreis.
- **Foto-Erzeugung** (`bildmotiv.py`): je nach `bild_tool` via **OpenAI** (`gpt-image-2`,
  env `HILO_OPENAI_IMAGE_MODEL`) **oder Ideogram** (`ideogram_api_key`, bessere Text-im-Bild-Genauigkeit);
  `background=opaque`, 1024×1024, je Stil/Tool getrennt gecacht. Stil-Prompts: authentische/
  dokumentarische Optik, natürliche Farben, themenpassende Stimmung (#135/#136/#138).
- **Faktentreue:** Auf KI-Tafeln kann die Bild-KI sich verschreiben → Tafel-Texte vor dem Posten
  in der Freigabe gegenlesen.

Das bisherige Banderdesign v10 ist über den Git-Tag `design-backup-2026-06-23` wiederherstellbar.
