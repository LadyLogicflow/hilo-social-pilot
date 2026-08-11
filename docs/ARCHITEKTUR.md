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
| `textgen.py` | Text/Bild-Orchestrierung (aktiver Pfad): `generate_drafts`/`generate_for_ids` → `_create_drafts`; erzeugt den **Text** je Beitrag via `generate()` (Anthropic **Claude**) und ruft fürs **Bild** die ShareNext-Pipeline (`run_sharenext_pipeline`); `extract_topics` extrahiert Themen aus PDFs/Links (Claude) |
| `sharenext_pipeline.py` | **Aktive Bild-Pipeline** (`run_sharenext_pipeline`): 6-stufiger Workflow (Message Brief → Creative Director → Concept Jury → Art Director → Image Producer → Visual QA), siehe [Bild-Design](#bild-design) |
| `message_brief.py` | ShareNext-Stufe 1: Kernaussage/Zielgruppe + Headline-Fallback (`gpt-5.6-terra`) |
| `creative_director.py` | ShareNext-Stufe 2: vier kreative Bild-Routen (Szene/Metapher/Objekt/Kontrast) (`gpt-5.6-terra`) |
| `concept_jury.py` | ShareNext-Stufe 3: bewertet die Routen, wählt die Gewinner-Route (`gpt-5-nano`) |
| `art_director.py` | ShareNext-Stufe 4: Art-Direction-Board (Focal Point, Licht, dominante Farben) (`gpt-5.6-terra`) |
| `image_producer.py` | ShareNext-Stufe 5: baut den Produktions-Prompt (`gpt-5.6-terra`), erzeugt das Bild (`gpt-image-2`) inkl. Headline im Bild + Alt-Text (`gpt-4o-mini`) |
| `visual_qa.py` | ShareNext-Stufe 6: prüft das Rohbild (Score/Freigabe, Vision-`gpt-5.6-terra`) |
| `sharenext_integration.py`, `prompt_builder.py`, `image_pipeline/` | Separates, template-basiertes Prompt-Builder-System – im aktuellen Produktionspfad **nicht** aktiv (experimentell/Legacy) |
| `text_renderer.py` | Pillow-Text-Rendering der alten Pipeline – **im Normalpfad ungenutzt** (ShareNext schreibt den Text per `gpt-image-2` direkt ins Bild) |
| `bildgen.py` | **Nur noch CI-Kreise + ShareNext-Aufruf** (Stand 2026-08-11): `add_logo_circles` setzt Logo-/Portrait-Kreis auf JEDES Bild; `render_drafts()` ruft für neue Entwürfe direkt `run_sharenext_pipeline` auf. Die alte Karten-Pipeline (`render()` mit Pille/Bullets/CTA per Pillow, drei Stile Standard/KI-Tafel/Kreativ) ist vollständig entfernt – auch aus allen `web.py`-Routen (Text überarbeiten, Anderes Bild, Bild-Aktion, Bildtyp, Veröffentlichungs-Fallback). `render_slides()` (Multi-Slide) existiert nur noch für die **Story-Frames**-Funktion, nicht mehr für ein Karussell-Postformat. |
| `bildmotiv.py` | Alte Foto-Erzeugung (inkl. Comic-Stile) – wird von KEINER Route/keinem Button mehr aufgerufen (Stand 2026-08-11); bleibt nur als totes Modul im Repo, falls Einzelfunktionen später wiederverwendet werden sollen |
| `stilwahl.py` | Bild-Stil-Zufallslogik der alten Pipeline – wird von keiner Route mehr aufgerufen (Stand 2026-08-11), totes Modul |
| `schauplatz.py` | Schauplätze der alten Pipeline (nur noch für Altfälle) |
| `traeger.py` | Botschafts-Träger der alten Pipeline (nur noch für Altfälle) |
| `wartung.py` | Cache-Aufräumung: `aufraeumen_motive` (KI-Foto-Cache `DATA_DIR/motive/` der alten Pipeline) und die Legacy-Funktion `aufraeumen_legacy_kampagne` (`DATA_DIR/kampagne/`, nur noch für alte Vor-ShareNext-Entwürfe mit `kampagne_motiv_pfad`) |
| `countdown_motive.py` | Gezeichnete Icons (Kalender, Wecker, Sanduhr) |
| `fristen.py` | Fristen-Countdown (gestaffelte Erinnerungen) |
| `anlass.py` | Anlass-Tage (besondere Tage mit Steuer-Aufhänger) |
| `wissen.py` | Wissens-Serie (zeitlose Themen, füllt leere Tage) |
| `personalisierung.py` | Beitrag je Beratungsstelle anpassen (CTA + Begleittext) |
| `pool.py` | Zufalls-Pool: Kanäle, „nie doppelt"-Logik je Stelle/Kanal, tägliche Ziehung, Restbestand/Warnung |
| `publish.py` | Meta-Graph-API: Veröffentlichung auf **Facebook** (Feed-Einzelbild + Story) und **Instagram** (Feed-Einzelbild + Story) sowie Reichweiten-Insights und Token-Handling – siehe [VEROEFFENTLICHUNG.md](VEROEFFENTLICHUNG.md). Die Carousel-Funktionen (`publish_facebook_carousel`/`publish_instagram_carousel`) bleiben im Code, werden aber seit Entfernung des Karussell-Postformats (2026-08-11) nicht mehr aufgerufen. |
| `uploader.py` | Lädt ein Bild per SFTP auf den Webspace (IONOS) und liefert die **öffentliche URL** – nötig, weil Instagram Bilder nur über öffentliche URLs zieht |
| `logging_setup.py` | Logging nach `logs/hilo.log` |

## Die vier Content-Streams

Alle Streams münden in dieselbe Freigabe und denselben Kalender. Der **Text** kommt bei allen
vier Strömen von **Claude** (`textgen.generate`), das **Bild** aus der **ShareNext-Pipeline**
(`sharenext_pipeline.run_sharenext_pipeline`, OpenAI) – **außer** beim Fristen-Countdown, wo der
Text bewusst hart vorformuliert bleibt (rechtlich relevante Fristen/Beträge) und nur das Bild von
der KI kommt (die feste Überschrift wird der Pipeline als `headline` übergeben, siehe unten):

1. **Aktuelles (News)** – `radar.py` wertet täglich die Quellen aus. Relevante externe
   News (Haufe, BFH) gehen in **Stufe 1** (Themenauswahl). HILO-eigene Steuertipps und
   BVL überspringen Stufe 1 und gehen direkt in die Entwurfserstellung
   (`textgen.generate_drafts`/`generate_for_ids` → `_create_drafts`).
2. **Fristen-Countdown** – `fristen.py` erzeugt gestaffelte Erinnerungen vor den
   Abgabefristen (ab 3 Monaten 1×/Woche, letzte 4 Wochen 2×/Woche, letzte Woche täglich).
   Text fest vorformuliert (kein KI-Token für den Text), Bild via
   `sharenext_pipeline.run_sharenext_pipeline` mit fest übergebener `headline` (die feste
   Überschrift wird ins Bild geschrieben, siehe `fristen.py`).
3. **Anlass-Tage** – `anlass.py` (`erzeuge_anlass_posts`) erzeugt zu besonderen Tagen
   (Tabelle `anlasstage`) einen Beitrag mit Steuer-Bezug: Text via `textgen.generate` (Claude),
   Bild via ShareNext-Pipeline; Wochenend-Tage erscheinen am Freitag davor.
4. **Wissens-Serie** – `wissen.py` (`auffuellen`) füllt leere Kalendertage mit zeitlosen Themen
   (Tabelle `wissensthemen`, ebenfalls Text via `textgen.generate` + ShareNext-Bild), sobald der
   Vorrat offener Beiträge unter eine Schwelle fällt.

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
  *Hinweis (Stand 2026-08-11):* `bild_tool` und die `bild_stil_*`-Schalter wirken auf **gar
  nichts** mehr – die alte `bildmotiv.py`-Pipeline wird von keiner Route mehr aufgerufen; der
  ShareNext-Weg nutzt immer `gpt-image-2` und ignoriert diese Einstellungen vollständig.
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
  `last_cache_cleanup.txt`), räumt `wartung.aufraeumen_motive` (`DATA_DIR/motive/`, KI-Foto-Cache
  der alten Pipeline) UND die Legacy-Funktion `wartung.aufraeumen_legacy_kampagne`
  (`DATA_DIR/kampagne/`, nur noch für alte Vor-ShareNext-Entwürfe mit `kampagne_motiv_pfad`).
  Beide orphan-basiert, 14-Tage-Schonfrist; was ein aktiver Beitrag noch braucht, wird NIE
  gelöscht. Verwaltung zeigt Cache-Größe beider Ordner + freien Speicher + Knopf.

## Bild-Design

Das Beitragsbild (quadratisch, Pipeline-Größe `1024×1024`) entsteht in der **ShareNext-Pipeline**
(`sharenext_pipeline.run_sharenext_pipeline`) – einem 6-stufigen Workflow über OpenAI-Modelle:

1. **Message Brief** (`message_brief.py`, `gpt-5.6-terra`) – leitet aus Thema/Text die
   Kernaussage und Zielgruppe ab (Grundlage der Bildidee); liefert bei Bedarf einen
   Headline-Fallback.
2. **Creative Director** (`creative_director.py`, `gpt-5.6-terra`) – entwickelt vier kreative
   Bild-Routen (emotionale Szene, Metapher, Objekt, Kontrast).
3. **Concept Jury** (`concept_jury.py`, `gpt-5-nano`) – bewertet die vier Routen und wählt die
   stärkste aus (bewusst günstiges Bewertungsmodell).
4. **Art Director Board** (`art_director.py`, `gpt-5.6-terra`) – legt die visuelle Regie fest:
   Focal Point, Lichtstimmung, dominante Farben.
5. **Image Producer** (`image_producer.py`) – baut aus dem Board den Produktions-Prompt
   (`gpt-5.6-terra`) und erzeugt das reale Bild mit **`gpt-image-2`** (Qualität `medium`). Die
   **Headline wird direkt ins Bild geschrieben** (kein nachträgliches Text-Overlay); zusätzlich
   entsteht ein Alt-Text für die Barrierefreiheit (`gpt-4o-mini`).
6. **Visual QA** (`visual_qa.py`, Vision-`gpt-5.6-terra`) – prüft das Rohbild (Lesbarkeit,
   Themenbezug) und vergibt einen Score. **Kein Auto-Retry** bei schwacher Bewertung
   (#Kostenschutz): das Bild geht bei Problemen zur manuellen Prüfung.

Beim **Fristen-Countdown** läuft dieselbe Pipeline, jedoch mit der bereits festen Überschrift als
`headline`-Parameter – so bleibt der rechtlich relevante Text unverändert und wird nur ins Bild
gesetzt.

Nach der Pipeline setzt der Code nur noch die **CI-Kreise** aufs fertige Bild
(`bildgen.add_logo_circles`) und speichert es als `entwurf_<id>.png`. Einen **Fallback gibt es
nicht mehr** – ShareNext ist der einzige aktive Weg; schlägt die Generierung fehl, bleibt der
Beitrag zunächst ohne Bild (er kann später manuell/erneut erzeugt werden).

- **Text im Bild:** Anders als in der alten Pipeline rendert der Code den Text **nicht** mehr per
  Pillow aufs Motiv – `gpt-image-2` schreibt die Headline selbst ins Bild. `text_renderer.py`
  gehört damit zur alten Pipeline und ist im Normalpfad ungenutzt.
- **CI-Kreise** (Markenzeichen): weißer Logo-Kreis + blauer Slogan-Kreis, per Code-Overlay
  (`bildgen.add_logo_circles`) nach der Bilderzeugung aufgesetzt – läuft unabhängig von der
  Bild-KI und wird von allen vier Content-Strömen genutzt. Ein Stellen-Porträt (`portrait`)
  ersetzt optional einen Kreis.
- **Personalisierung je Beratungsstelle** (`personalisierung.render_fuer_stelle`): das erzeugte
  ShareNext-Bild (`entwuerfe.bild_pfad` bzw. `fields['bild_pfad']`) wird wiederverwendet – nur der
  personalisierte CTA/Logo-Kreis + der Stellen-Porträt-Kreis werden neu aufgesetzt. **KEIN neuer
  GPT-Image-Call** nötig.
- **Alte Pipeline entfernt** (Stand 2026-08-11): `bildmotiv.py`/die alte `bildgen.render()`
  (Pille/Bullets/CTA per Pillow)/`stilwahl.py` – drei Stile Standard/KI-Tafel/Kreativ +
  Comic-Varianten, Bild-KI wählbar über `bild_tool` – werden von **keiner** Route/keinem Button
  mehr aufgerufen, auch nicht als Fallback. Alle Bild-Buttons (Neu erzeugen, Text überarbeiten,
  Anderes Bild, Layout neu, Stil wechseln, Bildtyp wechseln, Veröffentlichungs-Fallback) laufen
  über `run_sharenext_pipeline`. Die Module bleiben nur als totes Repo-Gepäck stehen.
- **Karussell-Postformat entfernt** (Stand 2026-08-11): Facebook/Instagram-Feed-Posts sind nur
  noch Einzelbild; die Formatauswahl (`format_fb`/`format_ig`) wurde aus der Vorschau entfernt
  und liefert serverseitig immer `einzelbild`. `render_slides()` existiert nur noch für die
  Story-Frames-Funktion (mehrere 9:16-Frames beim Story-Posten), nicht mehr für ein
  Karussell-Feed-Format.

Das bisherige Banderdesign v10 ist über den Git-Tag `design-backup-2026-06-23` wiederherstellbar.
