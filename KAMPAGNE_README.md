# 3-Stufen-Workflow: Automatisierte Kampagnen-Generierung

> **Stand-Hinweis (2026-07-30):** Dieses Dokument beschreibt den ursprünglichen Entwurf des
> Workflows. Seitdem geändert, siehe [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) für den
> aktuellen Stand:
> - Kein Auto-Retry mehr bei QA-Ablehnung (#Kostenschutz) - Bild geht zur manuellen Prüfung
> - QA läuft auf `gpt-5-nano` statt `gpt-5.6-terra` (~50x günstiger), Bild vor dem QA-Call verkleinert
> - Bild-Qualität `medium` statt `high` (~75% günstiger, kaum sichtbarer Unterschied)
> - Text liegt ohne Hintergrundfläche direkt über dem Motiv (adaptive Textfarbe je nach Bildhelligkeit)
> - Ist jetzt die **aktive Bild-Pipeline für alle vier Content-Ströme** (Aktuelles/Fristen/
>   Anlass/Wissen), nicht mehr nur ein Einzel-Feature - siehe `textgen.generate_with_campaign`
>   und `kampagne.generate_image_for_fixed_text` (Fristen: Text bleibt fest, nur das Bild kommt
>   von der KI)
> - Personalisierung je Beratungsstelle nutzt das rohe Motiv wieder statt neu zu generieren
>   (`personalisierung.render_fuer_stelle`)

Vollautomatischer Workflow für die Erstellung von Social-Media-Werbeanzeigen mit integrierter Qualitätskontrolle.

---

## Überblick

```
Steuertext → GPT-5.6 Terra → GPT Image 2 → GPT-5.6 Terra → Fertige Grafik
             (Planung)      (Grafik)      (QA)
```

**Problem gelöst:** Tippfehler ("sic" statt "sich"), fehlende QA, "HILO"-Text im Bild

**Lösung:** 3-Stufen-Pipeline mit automatischer Fehlerkennung und Retry-Logik

---

## Workflow-Stufen

### Stufe 1: Kampagnenplanung (GPT-5.6 Terra)

**Input:**
- Steuertext (beliebig)
- CTA (z.B. "Jetzt Termin vereinbaren")

**Output:** `CampaignPlan` (Structured Output)
- Headline (max. 55 Zeichen)
- 2-3 Infopunkte (je max. 45 Zeichen)
- Visuelle Strategie
- Vollständiger Bild-Prompt für Stufe 2

**Modell:** `gpt-5.6-terra` (wie von Catrin angewiesen)

---

### Stufe 2: Grafik-Generierung (GPT Image 2)

**Input:** `image_prompt` von Stufe 1

**Output:** PNG (Base64 → Datei)

**Modell:** `gpt-image-2`

**Einstellungen:**
- **Produktion:** `size="2048x2048"`, `quality="high"`
- **Tests:** `size="1024x1024"`, `quality="low"`

---

### Stufe 3: Qualitätskontrolle (GPT-5.6 Terra)

**Input:** Generiertes Bild + Erwartete Texte

**Output:** `QualityReview` (Structured Output)

**Prüfkriterien:**
- ✅ Textgenauigkeit (exakt wie vorgegeben?)
- ✅ Rechtschreibung (keine Tippfehler?)
- ✅ Lesbarkeit (auf Smartphone gut lesbar?)
- ✅ Fachliche Übereinstimmung (mit Steuertext?)
- ✅ Layout (professionell?)

**Logik:**
- `approved == True` → Bild freigeben ✅
- `approved == False` → Automatisch neu generieren (max. 3x)
- Nach 3 Fehlversuchen → Manuelle Kontrolle nötig

---

## Verwendung

### Python API

```python
from kampagne import run_campaign

# Kompletter Workflow
plan, image_path, review = run_campaign(
    article="Steuertext hier...",
    cta="Jetzt Beratungsstelle finden",
    test_mode=False,  # True für low-quality Tests
    max_retries=3,
)

print(f"Headline: {plan.headline}")
print(f"Bild: {image_path}")
print(f"Status: {'✅' if review.approved else '❌'}")
```

### CLI Test

```bash
cd ~/hilo-social-pilot
python3 kampagne.py
```

Erzeugt Test-Kampagne für Umzugskosten-Artikel.

---

## Kostenkontrolle

### Empfohlener Workflow

1. **Test-Bild:** `test_mode=True` (low quality, 1024x1024)
2. **QA auf Test-Bild**
3. **Bei Freigabe:** Nochmal mit `test_mode=False` (high quality, 2048x2048)

### Kosten pro Durchlauf

- GPT-5.6 Terra (Stufe 1): ~0.10 EUR
- GPT Image 2 (low): ~0.05 EUR
- GPT Image 2 (high): ~0.20 EUR
- GPT-5.6 Terra (Stufe 3): ~0.05 EUR

**Gesamt:** ~0.20 EUR (Test) / ~0.35 EUR (Produktion)

Bei 3 Retries: max. ~1.00 EUR

---

## Structured Outputs (Pydantic)

### CampaignPlan

```python
class CampaignPlan(BaseModel):
    core_message: str
    target_emotion: str
    headline: str = Field(max_length=55)
    supporting_points: list[str] = Field(min_length=2, max_length=3)
    cta: str = Field(max_length=35)
    visual_strategy: str
    visual_concept: str
    hero_element: str
    layout: str
    background: str
    text_contrast: str
    accent_usage: str
    image_prompt: str
```

### QualityReview

```python
class QualityReview(BaseModel):
    approved: bool
    text_is_exact: bool
    spelling_is_correct: bool
    all_text_is_readable: bool
    message_matches_article: bool
    layout_is_professional: bool
    problems: list[str]
    correction_instruction: str
```

---

## Integration in Post-Erstellung

**TODO:** Integration in `textgen.py` oder neuer Workflow

```python
# Beispiel-Integration
from kampagne import run_campaign

def create_post_with_campaign(article, cta):
    # 1. Kampagne erstellen
    plan, image_path, review = run_campaign(article, cta)
    
    # 2. In DB speichern
    fields = {
        "ueberschrift": plan.headline,
        "bullets": plan.supporting_points,
        "cta": plan.cta,
        "bild_pfad": str(image_path),
        "bild_stil": "standard",  # v5.x aktiviert
    }
    
    # 3. Post in DB einfügen
    # ... (wie bisher)
```

---

## Debugging

### Logging aktivieren

```python
import logging
logging.basicConfig(level=logging.INFO)
```

### Log-Ausgabe

```
[INFO] Stufe 1: Kampagnenplanung wird erstellt...
[INFO] Stufe 1: Kampagnenplan erstellt - Headline: Umzug? So holen Sie sich Geld zurück!
[INFO] Stufe 2: Grafik wird generiert (size=2048x2048, quality=high)...
[INFO] Stufe 2: Grafik gespeichert unter /data/kampagne/campaign_1234567890.png
[INFO] Stufe 3: Qualitätskontrolle wird durchgeführt...
[INFO] Stufe 3: Bild FREIGEGEBEN ✅
```

---

## Bekannte Probleme & Lösungen

### Problem: "sic" statt "sich"

**Lösung:** Stufe 3 erkennt den Tippfehler automatisch und generiert neu!

### Problem: "HILO" Text im Bild

**Lösung:** Masterprompt v5.2 + Stufe 3 QA prüfen darauf!

### Problem: Zu viele Retries (Kosten)

**Lösung:** `max_retries=1` oder `test_mode=True` für Tests

---

## Technische Anforderungen

- **Python:** 3.11+
- **OpenAI SDK:** neueste Version
- **Pydantic:** für Structured Outputs
- **OPENAI_API_KEY:** in Environment

```bash
pip install openai pydantic
export OPENAI_API_KEY="sk-..."
```

---

## Changelog

### v1.0 (2026-07-29)

- ✅ Stufe 1: GPT-5.6 Terra Kampagnenplanung
- ✅ Stufe 2: GPT Image 2 Grafik-Generierung
- ✅ Stufe 3: GPT-5.6 Terra QA
- ✅ Automatische Retry-Logik (max. 3x)
- ✅ Test-Modus (low quality)
- ✅ CLI für Tests
- ✅ Vollständige Dokumentation

**Basiert auf:** ChatGPT-Feedback vom 2026-07-29

---

## Autoren

- **Entwicklung:** Docky (Pandora Agent)
- **Konzept:** ChatGPT + Catrin
- **Referenz:** Masterprompt v5.2
