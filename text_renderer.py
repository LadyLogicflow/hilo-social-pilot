#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pillow-basiertes Text-Rendering für HILO Social-Media-Posts.

Rendert Headline, Bullets und CTA deterministisch auf Basis
von Layout-Vorlagen und TextBox-Koordinaten.
"""

from pathlib import Path
from typing import Literal

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

    # Textfarbe automatisch je nach Bildhelligkeit hinter der jeweiligen Box waehlen
    # (kein Hintergrund-Rechteck mehr -> muss zur tatsaechlichen Motiv-Helligkeit passen,
    # nicht nur zur geplanten 'text_contrast'-Beschreibung, die nicht immer zutrifft).
    headline_color, headline_outline = _text_colors_for_region(img, headline_box, W, H)
    supporting_color, supporting_outline = _text_colors_for_region(img, supporting_box, W, H)

    # 1. Headline rendern
    _render_text_block(
        draw, headline,
        headline_box, W, H,
        font_headline, headline_color, headline_outline,
        background_overlay
    )

    # 2. Supporting Points rendern
    bullets_text = "\n".join(f"• {p}" for p in supporting_points)
    _render_text_block(
        draw, bullets_text,
        supporting_box, W, H,
        font_body, supporting_color, supporting_outline,
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


def _text_colors_for_region(
    img: Image.Image, box: TextBox, img_width: int, img_height: int
) -> tuple[str, str]:
    """Misst die durchschnittliche Helligkeit des Bildbereichs unter 'box' und liefert
    (textfarbe, outline_farbe) - hell dahinter -> dunkler Navy-Text mit weisser Outline,
    dunkel dahinter -> weisser Text mit schwarzer Outline. Ersetzt die frueher feste
    Hintergrundflaeche: da der Text jetzt direkt ueber dem Motiv liegt, muss die Farbe zur
    TATSAECHLICHEN Bildhelligkeit passen, nicht nur zur geplanten Beschreibung."""
    x = int(box.x * img_width)
    y = int(box.y * img_height)
    w = max(1, int(box.width * img_width))
    h = max(1, int(box.height * img_height))
    region = img.crop((x, y, x + w, y + h)).convert("L")
    # Kleines Sample reicht (Performance) - grobe Durchschnittshelligkeit genuegt.
    region = region.resize((16, 16))
    avg = sum(region.getdata()) / (16 * 16)
    if avg > 150:
        return "#1a3a6b", "#ffffff"  # helles Motiv -> Navy-Text, weisse Outline
    return "#ffffff", "#000000"  # dunkles Motiv -> weisser Text, schwarze Outline


def _render_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: TextBox,
    img_width: int,
    img_height: int,
    font: ImageFont.FreeTypeFont,
    text_color: str,
    outline_color: str,
    add_background: bool,
):
    """Rendert einen Textblock OHNE Farbflaeche dahinter - der Text layert harmonisch
    ueber das Motiv (sonst sieht man vom Bild nichts mehr). Lesbarkeit kommt stattdessen
    von einer kraeftigeren Outline/Schlagschatten (_draw_text_with_outline), deren Farbe
    hier durchgereicht wird (per Helligkeitsmessung gewaehlt, siehe _text_colors_for_region).
    'add_background' bleibt als Parameter erhalten (Kompatibilitaet, ungenutzt), damit
    Aufrufer nicht angepasst werden muessen - es wird nie mehr eine Flaeche gezeichnet."""
    # Pixel-Koordinaten berechnen
    x = int(box.x * img_width)
    y = int(box.y * img_height)
    w = int(box.width * img_width)
    h = int(box.height * img_height)

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

        # Zeile zeichnen (mit Outline für bessere Lesbarkeit, Farbe je nach Bildhelligkeit)
        _draw_text_with_outline(draw, (text_x, text_y), line, font, text_color,
                                 outline_color=outline_color)

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
    outline_width: int = 3,
):
    """Zeichnet Text mit Outline fuer Lesbarkeit OHNE Hintergrundflaeche (Text layert direkt
    ueber das Motiv). outline_width 3 statt 2 (#Layout-Update) - kompensiert den Wegfall der
    Farbflaeche, die vorher automatisch Kontrast garantiert hat; ohne sie haengt die
    Lesbarkeit staerker von einer kraeftigen Outline ab."""
    x, y = pos
    # Outline (4 Richtungen)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Vordergrund
    draw.text((x, y), text, font=font, fill=fill_color)
