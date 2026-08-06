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
| `textgen.py` | Text/Bild-Orchestrierung: `generate_with_campaign` (aktiver Pfad, ruft `kampagne.run_campaign`) sowie `generate`/`extract_topics` (Claude, nur noch für Themen-Extraktion aus PDFs/Links genutzt) |
| `kampagne.py` | **Aktive Bild-Pipeline**: 3-Stufen-Workflow (GPT-5.6 Terra Planung → GPT Image 2 Motiv → GPT-5.6 Terra/nano QA), `run_campaign` (textet + gestaltet selbst) und `generate_image_for_fixed_text`/`create_visual_plan` (Art-Director-only, Text bleibt fest vorgegeben - genutzt vom Fristen-Countdown) |
| `text_renderer.py` | Pillow-Text-Rendering: zeichnet Headline/Bullets/CTA deterministisch aufs KI-Motiv (kein Hintergrund-Rechteck - Textfarbe wird automatisch aus der gemessenen Bildhelligkeit gewählt) |
| `bildgen.py` | **Nur noch Fallback + CI-Kreise**: `add_logo_circles` (Logo/Portrait-Kreis, wird von allen Streams genutzt) läuft weiter aktiv; `render_drafts`/die 3 alten Stile (Standard/KI-Tafel/Kreativ) sind nur Absicherung für Altfälle, im Normalbetrieb ungenutzt |
| `bildmotiv.py` | Alte Foto-Erzeugung (inkl. Comic-Stile) - bleibt im Repo für spätere Wiederverwendung, wird aktuell von keinem der vier Content-Ströme mehr automatisch aufgerufen |
| `stilwahl.py` | Bild-Stil-Zufallslogik der alten Pipeline - nur noch relevant für Altfälle ohne `kampagne_motiv_pfad` |
| `schauplatz.py` | Schauplätze der alten Pipeline (nur noch für Altfälle) |
| `traeger.py` | Botschafts-Träger der alten Pipeline (nur noch für Altfälle) |
| `wartung.py` | Cache-Aufräumung für **beide** Bild-Pipelines: `aufraeumen_motive` (alt, `DATA_DIR/motive/`) und `aufraeumen_kampagne` (3-Stufen-Workflow, `DATA_DIR/kampagne/` - schützt insbesondere das rohe Motiv für die Personalisierung je Stelle) |
| `countdown_motive.py` | Gezeichnete Icons (Kalender, Wecker, Sanduhr) |
| `fristen.py` | Fristen-Countdown (gestaffelte Erinnerungen) |
| `anlass.py` | Anlass-Tage (besondere Tage mit Steuer-Aufhänger) |
| `wissen.py` | Wissens-Serie (zeitlose Themen, füllt leere Tage) |
| `personalisierung.py` | Beitrag je Beratungsstelle anpassen (CTA + Begleittext) |
| `pool.py` | Zufalls-Pool: Kanäle, „nie doppelt"-Logik je Stelle/Kanal, tägliche Ziehung, Restbestand/Warnung |
| `publish.py` | Meta-Graph-API: Veröffentlichung auf **Facebook** (Feed-Einzelbild/Karussell + Story) und **Instagram** (Feed-Einzelbild/Karussell + Story) sowie Reichweiten-Insights und Token-Handling – siehe [VEROEFFENTLICHUNG.md](VEROEFFENTLICHUNG.md) |
| `uploader.py` | Lädt ein Bild per SFTP auf den Webspace (IONOS) und liefert die **öffentliche URL** – nötig, weil Instagram Bilder nur über öffentliche URLs zieht |
| `logging_setup.py` | Logging nach `logs/hilo.log` |

## Die vier Content-Streams

Alle Streams münden in dieselbe Freigabe und denselben Kalender. Text UND Bild kommen bei
allen vier Strömen aus dem **3-Stufen-Workflow** (`kampagne.py`, GPT-5.6 Terra + GPT Image 2) -
**außer** beim Fristen-Countdown, wo der Text bewusst hart vorformuliert bleibt (rechtlich
relevante Fristen/Beträge) und nur das Bild von der KI kommt (Art-Director-only, siehe unten):

1. **Aktuelles (News)** – `radar.py` wertet täglich die Quellen aus. Relevante externe
   News (Haufe, BFH) gehen in **Stufe 1** (Themenauswahl). HILO-eigene Steuertipps und
   BVL überspringen Stufe 1 und gehen direkt in die Texterstellung
   (`textgen.generate_with_campaign`).
2. **Fristen-Countdown** – `fristen.py` erzeugt gestaffelte Erinnerungen vor den
   Abgabefristen (ab 3 Monaten 1×/Woche, letzte 4 Wochen 2×/Woche, letzte Woche täglich).
   Text fest vorformuliert (kein KI-Token für den Text), Bild via
   `kampagne.generate_image_for_fixed_text` (nur Motiv/Layout von der KI).
3. **Anlass-Tage** – `anlass.py` erzeugt zu besonderen Tagen (Tabelle `anlasstage`) einen
   Beitrag mit Steuer-Bezug (`generate_with_campaign`); Wochenend-Tage erscheinen am
   Freitag davor.
4. **Wissens-Serie** – `wissen.py` füllt leere Kalendertage mit zeitlosen Themen
   (Tabelle `wissensthemen`, `generate_with_campaign`), sobald der Vorrat offener Beiträge
   unter eine Schwelle fällt.

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
- **Cache-Aufräumung** (`web.py._cache_cleanup_scheduler`): Thread, einmal täglich (Marker
  `last_cache_cleanup.txt`), räumt BEIDE Bild-Pipelines auf - `wartung.aufraeumen_motive`
  (`DATA_DIR/motive/`, alte Pipeline) UND `wartung.aufraeumen_kampagne` (`DATA_DIR/kampagne/`,
  3-Stufen-Workflow: rohe Motive + Text-Zwischenbilder). Beide orphan-basiert, 14-Tage-Schonfrist;
  was ein aktiver Beitrag noch braucht (inkl. `kampagne_motiv_pfad` für die Personalisierung je
  Stelle) wird NIE gelöscht. Verwaltung zeigt Cache-Größe beider Ordner + freien Speicher + Knopf.

## Bild-Design

Das Beitragsbild (1080×1080) entsteht im **3-Stufen-Workflow** (`kampagne.py`):

1. **Planung** (GPT-5.6 Terra) – entwickelt aus dem Steuertext Headline, Infopunkte, CTA,
   Begleittext, ein visuelles Konzept, ein Layout (6 Vorlagen: Text links/rechts/oben/unten
   vom Motiv, zentrale Headline, editorial split) und einen englischen Motiv-Prompt (NUR
   Bildbeschreibung, kein Text). Beim Fristen-Countdown steht der Text bereits fest (rechtlich
   relevante Fristen/Beträge) - hier plant GPT-5.6 Terra NUR das visuelle Konzept
   (`create_visual_plan`/`generate_image_for_fixed_text`), der Text bleibt unverändert.
2. **Motiv** (GPT Image 2, Qualität `medium` - kaum Unterschied zu `high`, ~75% günstiger) –
   erzeugt ein Foto/Illustration OHNE Text, mit bewusst freigehaltener, kontrastreicher Fläche
   für den späteren Text.
3. **QA** (`gpt-5-nano`, günstigstes Vision-Modell) – prüft Lesbarkeit/Kontrast, Themenbezug,
   Layout. Kein Auto-Retry bei Ablehnung (#Kostenschutz): das Bild geht bei Problemen zur
   manuellen Prüfung statt automatisch (kostenpflichtig) neu erzeugt zu werden.

Der Text (Headline, Bullets, CTA) wird per **Pillow** (`text_renderer.py`) direkt aufs Motiv
gerendert - OHNE Hintergrundfläche, layert also harmonisch über das Bild. Die Textfarbe
(Navy oder Weiß) wird automatisch aus der gemessenen Helligkeit des Bildbereichs hinter der
jeweiligen Textbox gewählt, nicht fest vorgegeben. CTA bleibt bewusst ein solider grüner Button.

- **CI-Kreise** (Markenzeichen): weißer Logo-Kreis + blauer Slogan-Kreis, per Code-Overlay
  (`bildgen.add_logo_circles`) nach dem Pillow-Text-Rendering aufgesetzt - läuft unabhängig vom
  Bild-Workflow und wird von allen vier Content-Strömen genutzt. Ein Stellen-Porträt (`portrait`)
  ersetzt optional einen Kreis.
- **Personalisierung je Beratungsstelle** (`personalisierung.render_fuer_stelle`): das rohe
  KI-Motiv (`kampagne_motiv_pfad`, vor dem Text-Overlay) wird wiederverwendet - nur der
  personalisierte CTA-Text (nennt den Ort) wird per Pillow neu draufgerendert + der
  Stellen-Portrait-Kreis gesetzt. KEIN neuer GPT-Image-Call nötig.
- **Alte Pipeline** (`bildgen.py`/`bildmotiv.py`/`stilwahl.py`, drei Stile Standard/KI-Tafel/
  Kreativ + Comic-Varianten): bleibt im Repo, wird aber von keinem der vier Content-Ströme mehr
  automatisch aufgerufen - nur noch Fallback für Alt-Entwürfe ohne `kampagne_motiv_pfad`. Die
  Comic-Stile (inkl. personalisiertem Berater-Comic je Stelle) sind für einen späteren,
  gezielten Einsatz vorgesehen, aktuell aber nicht aktiv.

Das bisherige Banderdesign v10 ist über den Git-Tag `design-backup-2026-06-23` wiederherstellbar.
