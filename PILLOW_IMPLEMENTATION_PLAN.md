# PILLOW Text-Rendering Implementation Plan

**Datum:** 2026-07-29  
**Status:** Ready for Implementation  
**Aufwand:** ~2-4 Stunden  
**Ziel:** Deutsche Texte 100% zuverlässig in Social-Media-Bilder einbauen

---

## 🎯 HINTERGRUND

### Problem
GPT Image 2 via `images.generate()` rendert deutschen Text **nicht zuverlässig**:
- ❌ Versuch 1: Text fehlt komplett
- ❌ Versuch 2: Text fehlt komplett  
- ❌ Versuch 3: Text fehlt komplett
- QA meldet: "Im Bild sind weder Headline noch Infopunkte noch CTA vorhanden"
- Das Motiv ist GUT, aber KEIN Text wurde erzeugt
- **ALLE** Retry-Versuche scheitern am gleichen Problem

### Ursache (Chatty's Analyse)
GPT Image 2 erhält einen sehr langen Prompt und interpretiert ihn als:
> "Erstelle eine hochwertige Social-Media-Anzeige."

NICHT als:
> "Rendere exakt diese vier deutschen Textblöcke."

Das Model ignoriert die Typografie-Anweisungen praktisch komplett, auch wenn sie als "MANDATORY" markiert sind.

### Warum Prompt-Optimierung nicht hilft
- Der Workflow ist technisch sauber ✅
- GPT-5.6 Terra erstellt perfekte Kampagnenpläne ✅
- GPT Image 2 ignoriert trotzdem die Text-Anweisungen ❌
- Das ist eine **Model-Limitation**, kein Prompt-Problem ❌

---

## 💡 CHATTY'S LÖSUNG

### Ansatz
**Trennung von Motiv und Typografie:**

1. **GPT 5.6 Terra:** Kampagnenstrategie + Bildidee + Texte + **Layout-Plan**
2. **GPT Image 2:** **NUR** das Hero-Motiv (mit **Freifläche für Text!**)
3. **Pillow (Python):** Headline + Bullets + CTA **exakt platzieren**
4. **GPT 5.6 Vision:** Design + Lesbarkeit prüfen (NICHT ob Text existiert!)

### Warum das besser ist
- ✅ **100% zuverlässig** (deterministisch, kein Retry nötig!)
- ✅ **Deutsche Texte** kein Problem
- ✅ **Volle Kontrolle** über Position, Schrift, Farbe, Kontrast
- ✅ **Kreativ variabel** (GPT entscheidet Layout!)
- ✅ **QA einfacher** (Text existiert IMMER!)
- ✅ **Schneller** (3x weniger API-Calls wegen fehlendem Retry)
- ✅ **Billiger** (weniger Token durch fehlgeschlagene Versuche)

### Qualitätsanspruch
Unsere QA verlangt:
- 100% richtige deutsche Rechtschreibung
- 100% vollständige Wörter
- 100% vollständige Bulletpoints
- 100% vollständiger CTA
- Smartphone-lesbar (6 Zoll)

→ Das ist ein **Publishing-Ziel**, nicht ein Kreativ-Ziel!  
→ **Deterministische Text-Engine** ist dafür besser geeignet als generative Bild-KI!

---

## 🏗️ ARCHITEKTUR

### Layout-System

#### TextBox Model
```python
class TextBox(BaseModel):
    """Position und Ausrichtung eines Textblocks."""
    x: float = Field(ge=0.0, le=1.0, description="X-Position (0.0 = links, 1.0 = rechts)")
    y: float = Field(ge=0.0, le=1.0, description="Y-Position (0.0 = oben, 1.0 = unten)")
    width: float = Field(ge=0.0, le=1.0, description="Breite (0.0-1.0)")
    height: float = Field(ge=0.0, le=1.0, description="Höhe (0.0-1.0)")
    align: Literal["left", "center", "right"] = Field(description="Horizontale Ausrichtung")
    vertical_align: Literal["top", "center", "bottom"] = Field(description="Vertikale Ausrichtung")
```

#### CampaignPlan erweitern
```python
class CampaignPlan(BaseModel):
    # Bestehende Felder...
    headline: str
    supporting_points: list[str]
    cta: str
    caption: str
    
    # NEU: Layout-Informationen
    layout_template: Literal[
        "text_left_hero_right",
        "text_right_hero_left",
        "text_top_hero_bottom",
        "hero_top_text_bottom",
        "centered_headline_bottom_panel",
        "editorial_split"
    ]
    
    headline_box: TextBox
    supporting_box: TextBox
    cta_box: TextBox
    
    # Für GPT Image 2:
    motiv_prompt: str = Field(description="Englischer Prompt NUR für das Motiv (OHNE Text!)")
```

### 6 Layout-Vorlagen

```python
LAYOUT_TEMPLATES = {
    "text_left_hero_right": {
        "headline_box": TextBox(x=0.07, y=0.08, width=0.48, height=0.24, align="left", vertical_align="top"),
        "supporting_box": TextBox(x=0.07, y=0.38, width=0.42, height=0.28, align="left", vertical_align="top"),
        "cta_box": TextBox(x=0.07, y=0.76, width=0.46, height=0.11, align="center", vertical_align="center"),
        "motiv_area": "right 50%",
        "motiv_instruction": "Keep the left 45% visually calm. Place the hero subject on the right side."
    },
    
    "text_right_hero_left": {
        "headline_box": TextBox(x=0.55, y=0.08, width=0.38, height=0.24, align="right", vertical_align="top"),
        "supporting_box": TextBox(x=0.55, y=0.38, width=0.38, height=0.28, align="right", vertical_align="top"),
        "cta_box": TextBox(x=0.55, y=0.76, width=0.38, height=0.11, align="center", vertical_align="center"),
        "motiv_area": "left 50%",
        "motiv_instruction": "Keep the right 40% visually calm. Place the hero subject on the left side."
    },
    
    "text_top_hero_bottom": {
        "headline_box": TextBox(x=0.07, y=0.06, width=0.86, height=0.18, align="center", vertical_align="top"),
        "supporting_box": TextBox(x=0.07, y=0.28, width=0.86, height=0.14, align="center", vertical_align="top"),
        "cta_box": TextBox(x=0.25, y=0.47, width=0.50, height=0.09, align="center", vertical_align="center"),
        "motiv_area": "bottom 45%",
        "motiv_instruction": "Keep the top 55% visually calm. Place the hero subject in the lower half."
    },
    
    "hero_top_text_bottom": {
        "headline_box": TextBox(x=0.07, y=0.58, width=0.86, height=0.16, align="center", vertical_align="top"),
        "supporting_box": TextBox(x=0.07, y=0.76, width=0.86, height=0.12, align="center", vertical_align="top"),
        "cta_box": TextBox(x=0.25, y=0.90, width=0.50, height=0.08, align="center", vertical_align="center"),
        "motiv_area": "top 55%",
        "motiv_instruction": "Keep the bottom 40% visually calm. Place the hero subject in the upper half."
    },
    
    "centered_headline_bottom_panel": {
        "headline_box": TextBox(x=0.10, y=0.35, width=0.80, height=0.22, align="center", vertical_align="center"),
        "supporting_box": TextBox(x=0.10, y=0.72, width=0.80, height=0.14, align="center", vertical_align="top"),
        "cta_box": TextBox(x=0.25, y=0.88, width=0.50, height=0.09, align="center", vertical_align="center"),
        "motiv_area": "background",
        "motiv_instruction": "Create a full-frame background. Leave vertical center and bottom 25% calm."
    },
    
    "editorial_split": {
        "headline_box": TextBox(x=0.05, y=0.12, width=0.42, height=0.20, align="left", vertical_align="top"),
        "supporting_box": TextBox(x=0.05, y=0.38, width=0.42, height=0.24, align="left", vertical_align="top"),
        "cta_box": TextBox(x=0.05, y=0.68, width=0.42, height=0.10, align="left", vertical_align="center"),
        "motiv_area": "right 48%",
        "motiv_instruction": "Create an editorial split layout. Hero subject fills the right half completely."
    }
}
```

---

## 📝 UMSETZUNGSPLAN

### Phase 1: Datenmodelle erweitern

**Datei:** `kampagne.py`

1. TextBox Model hinzufügen
2. CampaignPlan erweitern:
   - `layout_template: Literal[...]`
   - `headline_box: TextBox`
   - `supporting_box: TextBox`
   - `cta_box: TextBox`
   - `motiv_prompt: str` (statt `image_prompt`)
3. LAYOUT_TEMPLATES Dict definieren

### Phase 2: CREATIVE_DIRECTOR_PROMPT anpassen

**Datei:** `kampagne.py`

**WICHTIG:** Prompt MASSIV ändern!

**ALT:**
```
Formuliere einen englischen Produktionsprompt für GPT Image 2
mit MANDATORY TEXT RENDERING...
```

**NEU:**
```
LAYOUT-PLANUNG

Wähle eine passende Layout-Vorlage aus:
- text_left_hero_right (Text links, Motiv rechts)
- text_right_hero_left (Text rechts, Motiv links)
- text_top_hero_bottom (Text oben, Motiv unten)
- hero_top_text_bottom (Motiv oben, Text unten)
- centered_headline_bottom_panel (Zentrale Headline, unteres Panel)
- editorial_split (Editorial Split-Layout)

MOTIV-PROMPT (NUR FÜR DAS BILD, OHNE TEXT!)

Formuliere einen englischen Produktionsprompt für GPT Image 2.

WICHTIG:
- Dieser Prompt beschreibt NUR das visuelle Motiv
- KEIN Text, KEINE Typografie, KEINE Buchstaben!
- Das Motiv muss eine ruhige Fläche für Text lassen
- Verwende die Layout-spezifische Anweisung

Beispiel für "text_left_hero_right":
"A professional tax consultation scene with warm natural lighting.
Keep the left 45% of the image visually calm and free of important objects.
Place the hero subject (tax consultant, documents, calculator) on the right side.
Clean, modern aesthetic. High-quality photography.
DO NOT RENDER ANY TEXT, LETTERS, NUMBERS OR TYPOGRAPHY."

Der finale motiv_prompt muss vollständig in Englisch sein.
```

### Phase 3: Pillow Text-Rendering

**Neue Datei:** `text_renderer.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pillow-basiertes Text-Rendering für HILO Social-Media-Posts.

Rendert Headline, Bullets und CTA deterministisch auf Basis
von Layout-Vorlagen und TextBox-Koordinaten.
"""

from pathlib import Path
from typing import Literal, Optional

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field


class TextBox(BaseModel):
    """Position und Ausrichtung eines Textblocks."""
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(ge=0.0, le=1.0)
    height: float = Field(ge=0.0, le=1.0)
    align: Literal["left", "center", "right"]
    vertical_align: Literal["top", "center", "bottom"]


def render_text_on_image(
    image_path: Path,
    headline: str,
    supporting_points: list[str],
    cta: str,
    headline_box: TextBox,
    supporting_box: TextBox,
    cta_box: TextBox,
    output_path: Path,
    background_overlay: bool = False,
) -> Path:
    """Rendert Texte auf ein Bild.
    
    Args:
        image_path: Pfad zum Basis-Bild (von GPT Image 2)
        headline: Deutsche Headline
        supporting_points: 2-3 deutsche Infopunkte
        cta: Deutscher Call-to-Action
        headline_box: Position für Headline
        supporting_box: Position für Bullets
        cta_box: Position für CTA
        output_path: Ausgabe-Pfad
        background_overlay: Falls True, halbtransparente Hintergründe hinter Text
    
    Returns:
        Path zum finalen Bild
    """
    # Bild laden
    img = Image.open(image_path).convert("RGB")
    W, H = img.size  # Sollte 1080x1080 sein
    
    draw = ImageDraw.Draw(img, "RGBA")
    
    # Schriften laden (HILO CI: Archivo Black für Headline, Inter für Body)
    # TODO: Schriftdateien müssen im Repo liegen!
    try:
        font_headline = ImageFont.truetype("fonts/ArchivoBlack-Regular.ttf", 68)
        font_body = ImageFont.truetype("fonts/Inter-SemiBold.ttf", 32)
        font_cta = ImageFont.truetype("fonts/Inter-Bold.ttf", 36)
    except OSError:
        # Fallback: Standard-Font
        font_headline = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_cta = ImageFont.load_default()
    
    # HILO Farben
    NAVY = "#1a3a6b"
    GREEN = "#4a8c5c"
    LAVENDER = "#b8c8e8"
    WHITE = "#ffffff"
    
    # 1. Headline rendern
    _render_text_block(
        draw, headline,
        headline_box, W, H,
        font_headline, WHITE, NAVY,
        background_overlay
    )
    
    # 2. Supporting Points rendern
    bullets_text = "\n".join(f"• {p}" for p in supporting_points)
    _render_text_block(
        draw, bullets_text,
        supporting_box, W, H,
        font_body, WHITE, NAVY,
        background_overlay
    )
    
    # 3. CTA rendern (auf grüner/navy Fläche)
    _render_cta_button(
        draw, cta,
        cta_box, W, H,
        font_cta, WHITE, GREEN
    )
    
    # Speichern
    img.save(output_path)
    return output_path


def _render_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: TextBox,
    img_width: int,
    img_height: int,
    font: ImageFont.FreeTypeFont,
    text_color: str,
    bg_color: str,
    add_background: bool,
):
    """Rendert einen Textblock mit optionalem Hintergrund."""
    # Pixel-Koordinaten berechnen
    x = int(box.x * img_width)
    y = int(box.y * img_height)
    w = int(box.width * img_width)
    h = int(box.height * img_height)
    
    # Optional: Halbtransparenter Hintergrund
    if add_background:
        # Navy mit 85% Deckkraft
        bg_rgba = (*_hex_to_rgb(bg_color), 217)  # 217/255 ≈ 85%
        draw.rectangle([x, y, x + w, y + h], fill=bg_rgba)
    
    # Text mehrzeilig umbrechen
    wrapped_lines = _wrap_text(text, font, w)
    
    # Vertikale Position berechnen
    total_text_height = len(wrapped_lines) * _get_line_height(font)
    
    if box.vertical_align == "top":
        text_y = y + 10
    elif box.vertical_align == "center":
        text_y = y + (h - total_text_height) // 2
    else:  # bottom
        text_y = y + h - total_text_height - 10
    
    # Zeilen rendern
    for line in wrapped_lines:
        # Horizontale Position
        if box.align == "left":
            text_x = x + 10
        elif box.align == "center":
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            text_x = x + (w - line_width) // 2
        else:  # right
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            text_x = x + w - line_width - 10
        
        # Zeile zeichnen (mit Outline für bessere Lesbarkeit)
        _draw_text_with_outline(draw, (text_x, text_y), line, font, text_color)
        
        text_y += _get_line_height(font)


def _render_cta_button(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: TextBox,
    img_width: int,
    img_height: int,
    font: ImageFont.FreeTypeFont,
    text_color: str,
    bg_color: str,
):
    """Rendert CTA als Button mit farbigem Hintergrund."""
    x = int(box.x * img_width)
    y = int(box.y * img_height)
    w = int(box.width * img_width)
    h = int(box.height * img_height)
    
    # Button-Rechteck (abgerundete Ecken)
    draw.rounded_rectangle(
        [x, y, x + w, y + h],
        radius=12,
        fill=bg_color
    )
    
    # Text zentriert
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    text_x = x + (w - text_width) // 2
    text_y = y + (h - text_height) // 2
    
    draw.text((text_x, text_y), text, font=font, fill=text_color)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Bricht Text in Zeilen um die in max_width passen."""
    lines = []
    words = text.split()
    current_line = ""
    
    draw_temp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw_temp.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width - 20:  # 20px Margin
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines


def _get_line_height(font: ImageFont.FreeTypeFont) -> int:
    """Berechnet Zeilenhöhe für Font."""
    draw_temp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = draw_temp.textbbox((0, 0), "Tg", font=font)
    return bbox[3] - bbox[1] + 8  # +8px Zeilenabstand


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Konvertiert Hex-Farbe zu RGB."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill_color: str,
    outline_color: str = "#000000",
    outline_width: int = 2,
):
    """Zeichnet Text mit Outline für bessere Lesbarkeit."""
    x, y = pos
    # Outline (4 Richtungen)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Vordergrund
    draw.text((x, y), text, font=font, fill=fill_color)
```

### Phase 4: Integration

**Datei:** `kampagne.py`

1. `generate_advertisement()` anpassen:
   - Parameter ändern: `motiv_prompt` statt `image_prompt`
   - Prompt-Anweisung für GPT Image 2: "DO NOT RENDER ANY TEXT"

2. `run_campaign()` anpassen:
   - Nach Stufe 2 (Bildgenerierung): Text-Rendering mit Pillow
   - Vor Stufe 3 (QA): Finales Bild mit Text übergeben

```python
from text_renderer import render_text_on_image, LAYOUT_TEMPLATES

def run_campaign(...):
    # Stufe 1: Kampagnenplanung
    plan = create_campaign_plan(article, cta=cta)
    
    # Layout-Vorlage holen
    template = LAYOUT_TEMPLATES[plan.layout_template]
    
    for attempt in range(1, max_retries + 1):
        # Stufe 2a: NUR Motiv generieren (OHNE Text!)
        motiv_path = generate_advertisement(
            plan.motiv_prompt,
            output_path=f"{kampagne_dir}/motiv_{attempt}.png",
            size=size,
            quality=quality,
        )
        
        # Stufe 2b: Text mit Pillow hinzufügen
        final_path = f"{kampagne_dir}/final_{attempt}.png"
        image_path = render_text_on_image(
            motiv_path,
            plan.headline,
            plan.supporting_points,
            plan.cta,
            plan.headline_box,
            plan.supporting_box,
            plan.cta_box,
            Path(final_path),
            background_overlay=True,  # Optional: Hintergrund hinter Text
        )
        
        # Stufe 3: QA (mit finalem Bild!)
        review = quality_check(image_path, plan, article)
        
        if review.approved:
            return plan, image_path, review
```

### Phase 5: QA anpassen

**Datei:** `kampagne.py`

**QA_PROMPT vereinfachen:**

```python
QA_PROMPT = """Du bist Qualitätskontrolleur für HILO Social-Media-Werbeanzeigen.

WICHTIG: Die Texte wurden bereits mit Pillow eingefügt und sind garantiert vorhanden.

Prüfe das generierte Bild auf:

1. LESBARKEIT: Sind alle Texte auf einem Smartphone (6 Zoll) SCHARF und KLAR LESBAR?
   - Ausreichende Schriftgröße?
   - Guter Kontrast zum Hintergrund?
   - Keine Überlappung mit Motivelementen?

2. FACHLICHE ÜBEREINSTIMMUNG: Entspricht die Aussage dem Originaltext?

3. LAYOUT: Wirkt das Layout professionell und hochwertig?
   - Harmoniert Text mit Motiv?
   - Sind die Proportionen ausgewogen?
   - Ist die Bildsprache passend?

4. MOTIV-QUALITÄT: Ist das Motiv hochwertig und ansprechend?
   - Keine störenden Elemente im Textbereich?
   - Professionelle Bildqualität?

Bei JEDEM Problem: approved = False!

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""
```

**QualityReview Model anpassen:**

```python
class QualityReview(BaseModel):
    approved: bool
    
    # Text-Checks ENTFERNEN (wird von Pillow garantiert!)
    # text_is_exact: bool  ❌ ENTFERNEN
    # spelling_is_correct: bool  ❌ ENTFERNEN
    
    all_text_is_readable: bool = Field(description="Alle Texte gut lesbar?")
    text_has_good_contrast: bool = Field(description="Text-Kontrast ausreichend?")
    text_not_overlapping: bool = Field(description="Text überlappt nicht mit Motiv?")
    message_matches_article: bool = Field(description="Aussage entspricht dem Steuertext?")
    layout_is_professional: bool = Field(description="Layout professionell?")
    motiv_is_high_quality: bool = Field(description="Motiv hochwertig?")
    
    problems: list[str]
    correction_instruction: str
```

### Phase 6: Schriften hinzufügen

**Neue Dateien:**
- `fonts/ArchivoBlack-Regular.ttf` (für Headline)
- `fonts/Inter-SemiBold.ttf` (für Bullets)
- `fonts/Inter-Bold.ttf` (für CTA)

**Quellen:**
- Archivo Black: Google Fonts (Open Font License)
- Inter: Google Fonts (Open Font License)

Download-Links einfügen und Lizenzen beachten!

---

## ✅ TEST-PLAN

### Test 1: Layout-Vorlagen
- Jede der 6 Vorlagen mit einem Beispiel-Post testen
- Prüfen: Text ist lesbar, nicht überlappend, gut positioniert

### Test 2: Lange Texte
- Headline mit 55 Zeichen (Maximum)
- 3 Bullets mit je 45 Zeichen
- Prüfen: Text bricht korrekt um, passt in Box

### Test 3: Verschiedene Motive
- Helles Motiv (Kontrast-Test)
- Dunkles Motiv (Kontrast-Test)
- Komplexes Motiv (Überlappungs-Test)

### Test 4: QA-Schleife
- Prüfen: QA akzeptiert Bilder (keine falschen Ablehnungen mehr!)
- Prüfen: Retry funktioniert wenn Motiv schlecht ist

### Test 5: Integration
- Kompletter Workflow: Neuer Post erstellen
- Kompletter Workflow: "Foto neu würfeln"
- Logo-Kreise kommen NACH Text-Rendering

---

## 📦 DELIVERABLES

1. ✅ `kampagne.py` - Erweitert mit TextBox, LAYOUT_TEMPLATES, angepasstem Prompt
2. ✅ `text_renderer.py` - Neues Modul für Pillow-Rendering
3. ✅ `fonts/` - Verzeichnis mit Schriftdateien
4. ✅ Angepasste QA (QA_PROMPT + QualityReview Model)
5. ✅ Integration in `run_campaign()` und `regenerate_image_with_qa()`
6. ✅ Tests durchgeführt und dokumentiert
7. ✅ Git commit + push zu beiden Remotes

---

## 🚀 NÄCHSTE SCHRITTE

1. **Neue Session starten** (diese Session ist 100k Tokens lang!)
2. **Docky Briefing:** "Lies PILLOW_IMPLEMENTATION_PLAN.md und setze Phase 1-6 um!"
3. **Schritt für Schritt umsetzen**
4. **Nach jeder Phase testen**
5. **Git commit nach jeder fertigen Phase**
6. **Am Ende: Kompletter Test mit echten Posts**
7. **Service neu starten auf dem Pi**
8. **Catrin testet im Dashboard**

---

## 📊 ERFOLGS-KRITERIEN

- ✅ ALLE generierten Posts haben Text (Headline + Bullets + CTA)
- ✅ Deutsche Rechtschreibung ist IMMER korrekt (Pillow schreibt ab!)
- ✅ Text ist IMMER lesbar (deterministische Schriftgröße!)
- ✅ KEIN Retry wegen fehlendem Text mehr nötig
- ✅ QA-Erfolgsrate > 80% (nur noch Motiv-Qualität wird geprüft!)
- ✅ Catrin ist happy! 🎉

---

**ENDE DES PLANS** 🚀
