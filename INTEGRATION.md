# 3-Stufen-Workflow Integration

## Übersicht

Der 3-Stufen-Workflow (GPT-5.6 Terra + GPT Image 2 + QA) ist jetzt **vollständig integriert** in die Post-Erstellung!

**Vorteil:** Qualitätsgeprüfte Bilder mit eingebettetem Text + automatische Fehlerkorrektur!

---

## Verwendung

### Standard-Workflow (bisheriger Weg)

```python
from textgen import generate_drafts

# Anthropic Claude (wie bisher)
erzeugt = generate_drafts(limit=3, kanal="google")
```

### 3-Stufen-Workflow (NEU!)

```python
from textgen import generate_drafts

# 3-Stufen-Workflow mit GPT-5.6 Terra + GPT Image 2 + QA
erzeugt = generate_drafts(
    limit=3,
    kanal="google",
    use_campaign=True,    # 🔑 3-Stufen-Workflow aktivieren
    test_mode=False       # False = high quality (2048x2048)
)
```

### Test-Modus (günstiger)

```python
# Für Tests: low quality (1024x1024)
erzeugt = generate_drafts(
    limit=3,
    kanal="google",
    use_campaign=True,
    test_mode=True        # 🔑 Spart Kosten!
)
```

---

## CLI-Verwendung

### Bisheriger Weg (Anthropic Claude)

```bash
python3 main.py --generate 3
```

### 3-Stufen-Workflow (TODO: CLI-Parameter fehlt noch)

Derzeit nur über Python-API verfügbar!

**TODO:** `--use-campaign` Flag zu main.py hinzufügen!

---

## Unterschiede

### Bisheriger Workflow (generate)

1. **Anthropic Claude** erstellt Text (headline, bullets, cta)
2. Bild wird **SPÄTER** erstellt (beim Rendering)
3. **KEINE** Qualitätskontrolle
4. Text wird **über** das Bild gelegt

### 3-Stufen-Workflow (generate_with_campaign)

1. **GPT-5.6 Terra** plant Kampagne (headline, bullets, cta, visual_concept)
2. **GPT Image 2** erstellt Bild **SOFORT** (mit Text im Bild!)
3. **GPT-5.6 Terra** prüft Qualität (Tippfehler, Lesbarkeit, Layout)
4. Bei Problemen: **Automatisch neu generieren** (max. 3x)
5. Bild ist **FERTIG** und wird in DB gespeichert!

---

## Was wird in der DB gespeichert?

### Bisheriger Workflow

```json
{
  "ueberschrift": "...",
  "bullets": ["...", "..."],
  "cta": "...",
  "bild_stil": "standard",
  "bild_motiv": "..."
}
```

(Bild-Pfad wird SPÄTER beim Rendering hinzugefügt)

### 3-Stufen-Workflow

```json
{
  "ueberschrift": "...",
  "subline": "...",           ← NEU: Kernaussage
  "bullets": ["...", "..."],
  "cta": "...",
  "bild_stil": "standard",
  "bild_motiv": "...",
  "bild_pfad": "/data/bilder/campaign_1234567890.png",  ← NEU: Bild BEREITS erstellt!
  "qa_approved": true,        ← NEU: QA-Status
  "qa_problems": []           ← NEU: Liste von Problemen (leer wenn OK)
}
```

---

## Kosten

### Pro Durchlauf (ohne Retry)

- **Test-Modus:** ~0.20 EUR (low quality, 1024x1024)
- **Produktion:** ~0.35 EUR (high quality, 2048x2048)

### Bei 3 Retries (Worst Case)

- **Test-Modus:** ~0.60 EUR
- **Produktion:** ~1.00 EUR

**Empfehlung:** Immer erst mit `test_mode=True` testen!

---

## Beispiel: Batch-Verarbeitung

```python
from textgen import generate_drafts

# 10 Posts mit 3-Stufen-Workflow erstellen
print("Erstelle 10 Posts mit 3-Stufen-Workflow...")

# SCHRITT 1: Test-Modus (günstig, schnell)
erzeugt = generate_drafts(
    limit=10,
    kanal="google",
    use_campaign=True,
    test_mode=True
)

print(f"{erzeugt} Posts erstellt (Test-Modus)")

# SCHRITT 2: Manuelle Prüfung im Dashboard

# SCHRITT 3: Bei Freigabe -> nochmal mit high quality
# (TODO: Funktion für "upgrade to high quality" erstellen)
```

---

## Fehlerbehandlung

### Retry-Logik

Der 3-Stufen-Workflow versucht **automatisch** bis zu 3x neu zu generieren wenn:
- Tippfehler erkannt werden
- Text unleserlich ist
- Layout unprofessionell ist
- Text nicht exakt übereinstimmt

### Was passiert nach 3 Fehlversuchen?

Der Post wird trotzdem erstellt, ABER:
- `qa_approved` ist `False`
- `qa_problems` enthält Liste von Problemen

**TODO:** Im Dashboard QA-Status anzeigen + Filter für "nicht freigegebene" Posts!

---

## Integration Status

### ✅ Erledigt

- [x] `generate_with_campaign()` Funktion erstellt
- [x] `_create_drafts()` aktualisiert (use_campaign Parameter)
- [x] `generate_drafts()` aktualisiert (use_campaign Parameter)
- [x] `generate_for_ids()` aktualisiert (use_campaign Parameter)
- [x] Bild-Speicherung in `/data/bilder/campaign_*.png`
- [x] QA-Status in DB gespeichert

### ⏳ TODO

- [ ] CLI-Parameter `--use-campaign` zu main.py hinzufügen
- [ ] Dashboard: QA-Status anzeigen (✅/❌ Badge)
- [ ] Dashboard: Filter für "nicht freigegebene" Posts
- [ ] Funktion für "upgrade to high quality" (Test → Produktion)
- [ ] Statistik: Erfolgsrate der QA (wie viele Retries im Durchschnitt?)

---

## Migration

### Bestehende Posts

Bestehende Posts verwenden weiterhin den **bisherigen Workflow**!

Der 3-Stufen-Workflow gilt NUR für **neue** Posts (ab Integration)!

### Umstellung

Um ALLE neuen Posts mit 3-Stufen-Workflow zu erstellen:

**Option 1:** Default-Parameter ändern (textgen.py)

```python
def generate_drafts(limit=3, kanal="google", use_campaign=True, test_mode=False):
#                                              ^^^^^^^^^^^^^ Default auf True!
```

**Option 2:** Immer explizit angeben

```python
generate_drafts(limit=3, kanal="google", use_campaign=True)
```

---

## Autoren

- **Entwicklung:** Docky (Pandora Agent)
- **Konzept:** ChatGPT + Catrin
- **Datum:** 2026-07-29
