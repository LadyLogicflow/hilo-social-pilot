# ShareNext Migration - Status & TODO

**Datum:** 2026-08-06  
**Analysiert von:** Argus (Code-Reviewer Agent)  
**Status:** 80% abgeschlossen

## Zusammenfassung

Die HILO Codebase wurde von mehreren Bildgenerierungs-Systemen (kampagne.py, Standard-Bilder) auf **ausschließlich ShareNext** migriert. Die Migration ist zu 80% abgeschlossen - **kampagne.py wird noch an 3 kritischen Stellen verwendet**.

## KRITISCH - Muss noch gefixt werden

### 1. fristen.py (Zeile 118-131)
- **Problem:** Nutzt noch `kampagne.generate_image_for_fixed_text()`
- **Impact:** Fristen-Countdowns verwenden altes System
- **Lösung:** Auf ShareNext Pipeline umstellen (analog zu textgen.generate())

### 2. textgen.py (Zeile 594-659)
- **Problem:** `generate_with_campaign()` nutzt kampagne.py parallel zu `generate()` (ShareNext)
- **Impact:** Inkonsistenz - manche Entwürfe alt, andere neu
- **Lösung:** Komplett auf ShareNext umstellen ODER als DEPRECATED markieren

### 3. web.py (3 Stellen)
- **Problem 3a:** `_kampagne_pillow_rerender()` (Zeile 1951-1980) - Legacy-Funktion
- **Problem 3b:** `/beitrag-neu` Route (Zeile 1999-2011) - ruft `generate_with_campaign()`
- **Problem 3c:** `caption_erstellen` (Zeile 3117-3121) - ruft `kampagne.generate_caption_only()`
- **Lösung:** Alle auf ShareNext-Logik umstellen

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

## Nächste Schritte

1. ✅ Migrations-Scripts gelöscht
2. ⏳ fristen.py auf ShareNext umstellen
3. ⏳ textgen.py bereinigen
4. ⏳ web.py bereinigen
5. ⏳ kampagne.py löschen
6. ⏳ JSON-Felder aufräumen
7. ⏳ Tests durchführen
