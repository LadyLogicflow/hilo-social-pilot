# ShareNext Migration - ✅ ABGESCHLOSSEN

**Analyse:** 2026-08-06 (Argus - Code-Reviewer Agent)  
**Durchführung:** 2026-08-06 (Docky - Worker-Seer Agent)  
**Status:** ✅ 100% ABGESCHLOSSEN

## Zusammenfassung

Die HILO Codebase wurde vollständig von mehreren Bildgenerierungs-Systemen (kampagne.py, Standard-Bilder) auf **ausschließlich ShareNext** migriert. Alle Komponenten nutzen jetzt die ShareNext Pipeline (6-stufige Premium-Bildgenerierung).

## ✅ Erledigte Aufgaben

### 1. fristen.py ✅ ABGESCHLOSSEN
- ShareNext Pipeline integriert für Fristen-Countdown
- Alt-text Support hinzugefügt
- Docstring aktualisiert (kampagne.py → ShareNext)

### 2. textgen.py ✅ ABGESCHLOSSEN
- `generate_with_campaign()` Funktion komplett gelöscht (86 Zeilen)
- `_create_drafts()`: use_campaign if/else entfernt
- Alle Aufrufer nutzen jetzt `generate()` (ShareNext)

### 3. web.py ✅ ABGESCHLOSSEN (3 kampagne-Stellen entfernt)
- `/beitrag-neu` Route: Beide Modi auf ShareNext umgestellt
- `_kampagne_pillow_rerender()` komplett gelöscht (31 Zeilen)
- `caption_erstellen`: Inline OpenAI statt kampagne.py
- JSON-Felder bereinigt (kampagne_motiv_pfad, kampagne_layout_template)

### 4. Weitere Dateien ✅
- **anlass.py:** generate_with_campaign() → generate()
- **wissen.py:** generate_with_campaign() → generate()

### 5. kampagne.py ✅ GELÖSCHT
- Komplette Datei gelöscht (1260+ Zeilen)
- 0 verbleibende Imports oder Aufrufe
- Nur Legacy-Kommentare verbleiben (harmlos)

## Migrations-Scripts (gelöscht ✅)

Diese Scripts wurden gelöscht da sie nur für die Migration gebraucht wurden:
- ✅ check_old_images.py
- ✅ fix_sharenext_fields.py
- ✅ sync_bild_pfad_to_json.py
- ✅ alle_auf_standard.py
- ✅ fix_stil.py
- ⚠️ regenerate_images.py (behalten für Bulk-Regenerierung)

## Cleanup nach Migration

Nach Entfernung von kampagne.py müssen auch entfernt werden:
- JSON-Felder: `kampagne_motiv_pfad`, `kampagne_layout_template`
- Alte Kommentare in textgen.py, text_renderer.py
- wartung.py: `aufraeumen_kampagne()` umbenennen

## Migration-Plan

### Phase 1: fristen.py umstellen
```python
# ALT:
import kampagne
image_path, review, motiv_path, layout_template, highlight_words = kampagne.generate_image_for_fixed_text(...)

# NEU:
from sharenext_pipeline import run_sharenext_pipeline
result = run_sharenext_pipeline(
    stream="fristen",
    thema=titel,
    text=beschreibung,
    kanal="Facebook",
    headline=titel,
    size="1024x1024"
)
bild_pfad = os.path.join(DATA_DIR, f"frist_{frist_id}.png")
```

### Phase 2: textgen.py bereinigen
- `generate_with_campaign()` entfernen
- Alle Aufrufer auf `generate()` umstellen

### Phase 3: web.py bereinigen
- `_kampagne_pillow_rerender()` entfernen
- `/beitrag-neu` auf `textgen.generate()` umstellen
- `caption_erstellen` neue Funktion bauen

### Phase 4: kampagne.py löschen
- Datei komplett entfernen
- Alle Referenzen geprüft
- JSON-Felder aufräumen

## ShareNext Pipeline (Production-ready ✅)

**Dateien:**
- sharenext_pipeline.py
- message_brief.py
- creative_director.py
- concept_jury.py
- art_director.py
- image_producer.py
- visual_qa.py

**Namens-Schema:** `entwurf_{id}.png` (konsistent)

**Genutzt in:**
- textgen.py (`generate()` Funktion)
- web.py (neue Entwürfe)
- regenerate_images.py (Bulk-Regenerierung)

## Migration-Statistik

- **6 Dateien geändert**
- **101 Zeilen hinzugefügt** (ShareNext Integration + Alt-text)
- **1446 Zeilen gelöscht** (komplette kampagne.py + Legacy-Code)
- **0 kampagne-Imports verbleibend**

## Abgeschlossene Schritte

1. ✅ Migrations-Scripts gelöscht (Option A)
2. ✅ fristen.py auf ShareNext umgestellt
3. ✅ textgen.py bereinigt (generate_with_campaign gelöscht)
4. ✅ web.py bereinigt (3 kampagne-Stellen entfernt)
5. ✅ anlass.py + wissen.py umgestellt
6. ✅ kampagne.py gelöscht
7. ✅ JSON-Felder aufgeräumt (kampagne_motiv_pfad, kampagne_layout_template)

## Optional (nicht kritisch)

- Legacy-Kommentare aufräumen (bildgen.py, text_renderer.py)
- wartung.py: `aufraeumen_kampagne()` umbenennen in `aufraeumen_legacy_kampagne()`
- Syntax-Tests durchführen (bereits lokal geprüft ✅)

---

## Phase 2 – Alte Standard-/Stil-Pipeline + Karussell entfernt (2026-08-11)

**Anlass:** Trotz "100% abgeschlossen" (Phase 1 oben) lief in der Praxis noch die alte
Pillow-Karten-Pipeline (Pille „HILO Steuertipp" + Headline + Bullets + CTA-Button per Pillow
gerendert) – sie war nur aus dem *neuen* Beitrags-Fluss entfernt, hing aber noch an ~9
Bild-Buttons in `web.py` sowie an der zentralen Batch-Funktion `bildgen.render_drafts()`.
Erkannt anhand eines Bild-Vergleichs (siehe Chat-Protokoll): ein per Button erzeugtes Bild
zeigte noch die alte Karten-Optik statt der ShareNext-Optik (GPT schreibt die Headline direkt
ins Foto, Pillow ergänzt nur die beiden CI-Kreise).

### Entfernt: alte Stil-Pipeline (Standard/KI-Tafel/Kreativ/Comic/Comic-Beratung/Comic-Strip)

- **`web.py`:** neue zentrale Funktion `_sharenext_bild_synchron(data, eid)` – bündelt
  ShareNext-Pipeline-Aufruf + Speichern + Logo-Kreise. Ersetzt die alte
  `bildmotiv.ensure_photo_fuer()` + `bildgen.render()`-Kombination in:
  - `/text-neu` (`text_neu`)
  - `/anderes-bild` (`anderes_bild`) – Stil-Zufallslogik (`stilwahl.anderen_stil_waehlen`) entfernt
  - `/bild-aktion` → `layout_neu` und `stil_wechseln`
  - `/bild-generieren` (`bild_generieren`) – komplette Comic/KI-Tafel/Kreativ-Auswahl inkl.
    Comic-Strip-Panel-Logik entfernt, Formularfeld `bild_stil` wird ignoriert
  - `/bild-typ` (`bild_typ`) – Person-/Themenbild-Unterscheidung entfernt (existiert in
    ShareNext nicht)
  - `_ensure_bild_pfad()` – Veröffentlichungs-Fallback (Bild fehlt noch → on-demand erzeugen)
  - `_premium_foto_hintergrund()` – nutzt jetzt ebenfalls die gemeinsame Helper-Funktion
    (Code-Dopplung entfernt)
- **`bildgen.py`:** `render_drafts()` (Batch-Job für alle neuen Entwürfe ohne Bild – Kern von
  Dashboard-Stufe 2 "Texte & Bilder erzeugen") ruft jetzt direkt `run_sharenext_pipeline` +
  `add_logo_circles` statt der alten `render()`-Funktion. **Das war vermutlich die
  Hauptquelle der falschen Bilder**, da dieser Job für jeden neuen Beitrag ohne `bild_pfad` lief.
- Module `bildmotiv.py`, `stilwahl.py`, `text_renderer.py` sowie `bildgen.render()` (die
  Karten-Funktion selbst) werden dadurch von **keiner Route mehr aufgerufen** – bleiben als
  totes Repo-Gepäck stehen (nicht gelöscht, für den Fall künftiger Wiederverwendung).
- Einstellungen `bild_tool` und `bild_stil_standard`/`_ki_tafel`/`_kreativ` (Verwaltung) wirken
  sich seither auf **nichts mehr** aus.

### Entfernt: Karussell-Feed-Format

- `_format()` in `web.py` liefert nur noch `"einzelbild"`, unabhängig vom Formularwert.
- "Karussell"-Option aus beiden Format-Dropdowns (Facebook/Instagram) im Vorschau-Formular
  entfernt.
- Alle Default-Werte von `"karussell"` auf `"einzelbild"` umgestellt: `web.py` (mehrere
  `_format(..., "karussell")`-Aufrufe, Auto-Pool-Einplanung, `gp["format_ig"] or ... or
  "karussell"`), `db.py` (Tabellen-Default `format_ig` bei `CREATE TABLE` und bei der
  `ALTER TABLE ... ADD COLUMN`-Migration für Bestandsdatenbanken).
- `/beitrag`-Detailseite zeigt nur noch das Einzelbild (kein Slide-Loop mehr); Route
  `/beitrag-slide/<eid>/<idx>` (Einzel-Slide-Download) entfernt.
- Alle "Karussell ansehen"-Labels/Bedingungen (`e.format=='karussell'`, `fmt=='karussell'`)
  aus den Jinja-Templates in `web.py` entfernt.
- **Bewusst NICHT entfernt:** `bildgen.render_slides()` – wird weiterhin für die
  **Story-Frames-Funktion** gebraucht (mehrere 9:16-Frames beim Story-Posten,
  `_publish_story`/`personalisierung.render_slides_fuer_stelle`); das ist eine andere Funktion
  als das (jetzt abgeschaltete) Karussell-Feed-Format. Ebenso bleiben
  `publish_facebook_carousel`/`publish_instagram_carousel` in `publish.py` als toter Code stehen
  (werden nicht mehr aufgerufen).

### Geänderte Dateien

| Datei | Art der Änderung |
|---|---|
| `web.py` | Neue Helper-Funktion `_sharenext_bild_synchron`; 7 Routen umgestellt; Karussell-UI/-Routen entfernt; Format-Defaults umgestellt |
| `bildgen.py` | `render_drafts()` auf ShareNext umgestellt |
| `db.py` | Schema-Default + Migrations-Default `format_ig`: `karussell` → `einzelbild` |
| `docs/BEDIENUNG.md` | Bild-Stil-Hinweis aktualisiert (Einstellung wirkungslos) |
| `docs/ARCHITEKTUR.md` | Modul-Tabelle + Datenbank-/Bild-Design-Abschnitte aktualisiert (alte Pipeline tot, Karussell entfernt) |
| `docs/FUNKTIONSUMFANG.md` | Bild-/Veröffentlichungs-Abschnitte aktualisiert, Stand-Datum erneuert |
| `docs/VEROEFFENTLICHUNG.md` | Karussell-Abschnitte (3.2, 4.2) als abgeschaltet markiert, Story-Abschnitt klargestellt |

### Nicht geprüft / offene Punkte

- Kein Live-Test mit echtem OpenAI-Key in dieser Umgebung möglich – nur Syntax-Checks und
  bestehende Unit-Tests (`tests/test_prompt_builder.py`, `tests/test_image_pipeline.py`,
  `tests/test_sharenext_integration.py`) liefen grün.
- Bereits bestehende Alt-Beiträge mit `format='karussell'` in der Datenbank werden von der
  Detailseite jetzt wie Einzelbild behandelt (nur `bild_pfad`/Panel 1 sichtbar) – nicht rückwirkend
  migriert.
- `bildmotiv.py`, `stilwahl.py`, `text_renderer.py`, `schauplatz.py`, `traeger.py` wurden nicht
  gelöscht, nur entkoppelt (siehe oben) – Aufräumen als separater Schritt möglich.
