# HILO Kampagnen-Workflow - Code für Chatty

## 1. DATENMODELLE (Pydantic BaseModel)

```python
from pydantic import BaseModel, Field

class CampaignPlan(BaseModel):
    """Kampagnenplan von GPT-5.6 Terra (Stufe 1)."""
    core_message: str = Field(description="Kernaussage des Steuertexts in einem Satz")
    target_emotion: str = Field(description="Ziel-Emotion")
    
    headline: str = Field(max_length=55, description="Prägnante Überschrift (max. 55 Zeichen)")
    supporting_points: list[str] = Field(
        min_length=2,
        max_length=3,
        description="2-3 kurze Infopunkte (je max. 45 Zeichen)"
    )
    cta: str = Field(max_length=35, description="Call-to-Action (max. 35 Zeichen)")
    caption: str = Field(description="Begleittext für Social Media (150-200 Wörter)")
    
    visual_strategy: str = Field(description="Gewählte Bildstrategie")
    visual_concept: str = Field(description="Beschreibung des visuellen Konzepts")
    hero_element: str = Field(description="Dominantes Hauptelement im Bild")
    layout: str = Field(description="Layout-Beschreibung")
    background: str = Field(description="Hintergrund-Beschreibung")
    text_contrast: str = Field(description="Farbkontrast für Text")
    accent_usage: str = Field(description="Verwendung der Akzentfarben")
    
    image_prompt: str = Field(description="Vollständiger englischer Prompt für GPT Image 2")


class QualityReview(BaseModel):
    """Qualitätsprüfung von GPT-5.6 Terra (Stufe 3)."""
    approved: bool = Field(description="True = Bild freigegeben, False = Neu generieren")
    
    text_is_exact: bool = Field(description="Alle Texte exakt wie vorgegeben?")
    spelling_is_correct: bool = Field(description="Deutsche Rechtschreibung korrekt?")
    all_text_is_readable: bool = Field(description="Alle Texte gut lesbar?")
    message_matches_article: bool = Field(description="Aussage entspricht dem Steuertext?")
    layout_is_professional: bool = Field(description="Layout professionell?")
    
    problems: list[str] = Field(description="Liste gefundener Probleme")
    correction_instruction: str = Field(description="Anweisung zur Korrektur (falls approved=False)")
```

## 2. STUFE 1: KAMPAGNENPLANUNG

```python
def create_campaign_plan(
    article: str,
    cta: str = "Jetzt Termin vereinbaren",
    channel: str = "Instagram und Facebook",
    format_size: str = "1080x1080",
) -> CampaignPlan:
    """Stufe 1: Kampagnenplanung mit GPT-5.6 Terra.
    
    Args:
        article: Vollständiger Steuertext oder Newslettertext
        cta: Gewünschter Call-to-Action
        channel: Ziel-Kanal (für Kontext)
        format_size: Bildformat
    
    Returns:
        CampaignPlan mit allen Kampagnen-Details inkl. image_prompt
    """
    if not article or not article.strip():
        raise ValueError("Artikel darf nicht leer sein!")
    
    client = OpenAI(api_key="***REMOVED***")
    
    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",
        messages=[
            {
                "role": "system",
                "content": CREATIVE_DIRECTOR_PROMPT,  # Siehe unten
            },
            {
                "role": "user",
                "content": (
                    f"STEUERTEXT:\n{article}\n\n"
                    f"GEWÜNSCHTER CTA:\n{cta}\n\n"
                    f"FORMAT: {format_size}, quadratisch\n"
                    f"KANAL: {channel}"
                ),
            },
        ],
        response_format=CampaignPlan,
    )
    
    plan = response.choices[0].message.parsed
    
    if plan is None:
        raise RuntimeError("Es wurde kein Kampagnenplan erzeugt.")
    
    return plan
```

## 3. STUFE 2: BILDGENERIERUNG

```python
def generate_advertisement(
    image_prompt: str,
    output_path: Optional[str] = None,
    size: Literal["1024x1024", "2048x2048"] = "1024x1024",
    quality: Literal["low", "medium", "high", "auto"] = "high",
) -> Path:
    """Stufe 2: Grafik-Generierung mit GPT Image 2.
    
    Args:
        image_prompt: Vollständiger Prompt von create_campaign_plan()
        output_path: Optional: Ziel-Pfad (Standard: auto-generiert)
        size: Bildgröße
        quality: Qualitätsstufe
    
    Returns:
        Path zum gespeicherten PNG
    """
    client = OpenAI(api_key="***REMOVED***")
    
    # HIER IST DER WICHTIGE TEIL!
    result = client.images.generate(
        model="gpt-image-2",
        prompt=image_prompt,
        size=size,
        quality=quality,
        output_format="png",
    )
    
    image_base64 = result.data[0].b64_json
    
    if not image_base64:
        raise RuntimeError("Das Bildmodell lieferte keine Bilddaten.")
    
    # Bild speichern
    if not output_path:
        import time
        timestamp = int(time.time())
        output_path = f"data/kampagne/campaign_{timestamp}.png"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    path = Path(output_path)
    path.write_bytes(base64.b64decode(image_base64))
    
    return path
```

## 4. STUFE 3: QUALITÄTSKONTROLLE

```python
def quality_check(
    image_path: Path,
    plan: CampaignPlan,
    article: str,
) -> QualityReview:
    """Stufe 3: Qualitätskontrolle mit GPT-5.6 Terra (multimodal).
    
    Args:
        image_path: Pfad zum generierten Bild
        plan: Kampagnenplan mit erwarteten Texten
        article: Original-Steuertext
    
    Returns:
        QualityReview mit Prüfergebnis
    """
    client = OpenAI(api_key="***REMOVED***")
    
    # Bild als Base64 laden
    image_data = image_path.read_bytes()
    image_base64 = base64.b64encode(image_data).decode("utf-8")
    
    # Erwartete Texte zusammenstellen
    expected_texts = f"""ERWARTETE TEXTE:

Headline: {plan.headline}

Infopunkte:
{chr(10).join("• " + p for p in plan.supporting_points)}

CTA: {plan.cta}

ORIGINALTEXT:
{article[:500]}"""
    
    # HIER IST DIE QA MIT VISION!
    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",  # Terra für multimodales QA
        messages=[
            {
                "role": "system",
                "content": QA_PROMPT,  # Siehe unten
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": expected_texts},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        },
                    },
                ],
            },
        ],
        response_format=QualityReview,
    )
    
    review = response.choices[0].message.parsed
    
    if review is None:
        raise RuntimeError("Es wurde keine Qualitätsprüfung erzeugt.")
    
    return review
```

## 5. RETRY-SCHLEIFE

```python
def run_campaign(
    article: str,
    cta: str = "Jetzt Termin vereinbaren",
    output_path: Optional[str] = None,
    max_retries: int = 3,
    test_mode: bool = False,
) -> tuple[CampaignPlan, Path, QualityReview]:
    """Kompletter 3-Stufen-Workflow mit automatischer Retry-Logik.
    
    Args:
        article: Vollständiger Steuertext
        cta: Call-to-Action
        output_path: Optional: Ziel-Pfad für finale Grafik
        max_retries: Maximale Anzahl Neugenerierungen bei QA-Fehlern
        test_mode: True = low quality für Tests
    
    Returns:
        (CampaignPlan, finale_image_path, QualityReview)
    """
    # Stufe 1: Kampagnenplanung (nur einmal!)
    plan = create_campaign_plan(article, cta=cta)
    
    # Stufe 2 + 3: Grafik + QA (mit Retry)
    size = "1024x1024"
    quality = "low" if test_mode else "high"
    
    kampagne_dir = "data/kampagne"
    os.makedirs(kampagne_dir, exist_ok=True)
    
    for attempt in range(1, max_retries + 1):
        try:
            # Stufe 2: Grafik generieren
            temp_path = f"{kampagne_dir}/attempt_{attempt}.png" if not output_path else output_path
            
            image_path = generate_advertisement(
                plan.image_prompt,
                output_path=temp_path,
                size=size,
                quality=quality,
            )
            
            # Stufe 3: QA
            review = quality_check(image_path, plan, article)
            
            if review.approved:
                # ✅ ERFOLG!
                return plan, image_path, review
            
            if attempt < max_retries:
                # ⚠️ Abgelehnt, neuer Versuch...
                continue
            else:
                # ❌ Alle Versuche fehlgeschlagen
                return plan, image_path, review
        
        except Exception as e:
            if attempt < max_retries:
                continue
            else:
                raise RuntimeError(f"Alle {max_retries} Versuche fehlgeschlagen!") from e
    
    raise RuntimeError("Workflow-Logik-Fehler")
```

## 6. QA-PROMPT

```python
QA_PROMPT = """Du bist Qualitätskontrolleur für HILO Social-Media-Werbeanzeigen.

Prüfe das generierte Bild auf:

1. TEXTGENAUIGKEIT: Sind alle Texte (Headline, Infopunkte, CTA) EXAKT wie vorgegeben?
   Keine Tippfehler, keine fehlenden Buchstaben, keine zusätzlichen Wörter?

2. RECHTSCHREIBUNG: Ist die deutsche Rechtschreibung perfekt?

3. LESBARKEIT: Sind alle Texte auf einem Smartphone (6 Zoll) SCHARF und KLAR LESBAR?
   - Schriftgröße NIEMALS unter 28pt
   - ALLE Texte müssen DEUTLICH erkennbar sein
   - Bei unscharfen oder zu kleinen Texten: approved = False!

4. TEXT-KONTRAST: Ist der Text GEGEN DEN HINTERGRUND KLAR LESBAR?
   - Text muss SCHARFEN Kontrast haben (hell auf dunkel ODER dunkel auf hell)
   - KEINE grauen, blassen oder schlecht lesbaren Texte
   - Bei schlechtem Kontrast: approved = False!

5. FACHLICHE ÜBEREINSTIMMUNG: Entspricht die Aussage dem Originaltext?

6. LAYOUT: Wirkt das Layout professionell und hochwertig?

Bei JEDEM Problem: approved = False!

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""
```

## 7. AKTUELLER BILDPROMPT (Auszug)

Der CREATIVE_DIRECTOR_PROMPT enthält u.a. diesen Abschnitt:

```
BILDPROMPT (GPT Image 2 Production Briefing)

Formuliere abschließend einen vollständigen englischen Produktionsprompt
für GPT Image 2 nach folgendem Muster:

────────────────────────────────────────────────────────────────

Generate a square social media advertisement (1080x1080) with MANDATORY TEXT RENDERING.

#1 PRIORITY: Text rendering is the PRIMARY success criterion.
An image without the complete required text is invalid.

REQUIRED TEXT (exact German, must appear verbatim):
Headline: [füge hier die entwickelte Headline ein]
• [Infopunkt 1]
• [Infopunkt 2]
• [Infopunkt 3, falls vorhanden]
Call-to-Action: [füge hier den CTA ein]

TYPOGRAPHY REQUIREMENTS:
- Headline: largest element, 20-30% of image area, 3 lines maximum, mobile-readable
- Bullets: clearly smaller than headline, fully legible
- CTA: recognizable button or panel
- High contrast (light on dark OR dark on light)
- All text sharp, readable at 6-inch screen size
- No decorative placement on frames/objects/documents

VISUAL CONCEPT:
[füge hier die präzise Beschreibung des gewählten Kreativkonzepts ein]

LAYOUT:
[füge hier die Layout-Beschreibung ein]
(Text block left/Motiv right OR Text top/Motiv bottom preferred)
Reserve ≥40% area for text on clean, high-contrast background

HILO BRAND COLORS:
Navy #1a3a6b, Green #4a8c5c, Lavender #b8c8e8, White #ffffff

CORNER SAFE ZONES:
Keep all four corners clear (12% width × 12% height per corner) for logo overlays

FINAL CHECK before output:
☑ Visual concept executed
☑ Headline complete, readable
☑ All bullets complete, readable
☑ CTA clear
☑ No invented text
☑ German spelling correct
☑ Corners free
☑ Advertisement, not photo

If ANY check fails, correct BEFORE output.

────────────────────────────────────────────────────────────────

Fülle die Platzhalter [in eckigen Klammern] mit den zuvor entwickelten Inhalten.
Übernimmt alle Texte exakt wie vorgegeben.
Der finale Prompt muss vollständig in Englisch sein.
```

## 8. PROBLEM

**BEOBACHTUNG:**
- ✅ Stufe 1 (GPT-5.6 Terra): Funktioniert perfekt, erzeugt gute Kampagnenpläne
- ❌ Stufe 2 (GPT Image 2): Ignoriert die REQUIRED TEXT Anweisungen komplett
- ✅ Stufe 3 (GPT-5.6 Terra Vision): Erkennt korrekt dass Text fehlt

**QA-MELDUNG (typisch):**
"Im Bild sind weder Headline noch Infopunkte noch CTA vorhanden. Das Bild wirkt als Foto hochwertig..."

**BEDEUTET:**
- Das Motiv ist GUT
- Es wurde KEIN Text erzeugt (nicht "falsch", sondern "fehlt")
- GPT Image 2 via `images.generate` rendert deutschen Text nicht zuverlässig

**RETRY-ERGEBNIS:**
- Versuch 1: Text fehlt
- Versuch 2: Text fehlt
- Versuch 3: Text fehlt
- ALLE Versuche scheitern am gleichen Problem!

## 9. FRAGEN AN CHATTY

1. Ist `client.images.generate()` der richtige Endpunkt für Typografie-reiche Bilder?
2. Sollten wir einen anderen API-Endpunkt verwenden?
3. Ist die Formulierung "MANDATORY TEXT RENDERING" falsch?
4. Sollten wir die Textblöcke reduzieren (von 5 auf 3)?
5. Ist Pillow die einzige zuverlässige Lösung für deutschen Text?
