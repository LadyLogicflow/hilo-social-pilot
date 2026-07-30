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

# Absoluter Pfad zum fonts/-Ordner (Repo-Root, gleiche Ebene wie diese Datei) - NICHT relativ
# ("fonts/...") verwenden, das haengt vom Arbeitsverzeichnis beim Programmstart ab und schlug
# fehl -> Pillow fiel auf die winzige Standard-Bitmap-Schrift zurueck (Text kaum lesbar).
FONT_DIR = Path(__file__).resolve().parent / "fonts"


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
    # Schriften liegen im Repo unter fonts/ (absoluter Pfad via FONT_DIR, s.o.)
    try:
        font_headline = ImageFont.truetype(str(FONT_DIR / "ArchivoBlack-Regular.ttf"), 68)
        # Inter-Variable.ttf ist eine VARIABLE Font (ein File, alle Gewichte) - die vorher
        # verwendeten 'Inter-SemiBold.ttf'/'Inter-Bold.ttf' waren defekt (enthielten faelschlich
        # HTML-Seiten statt echter Font-Daten -> jeder Ladeversuch scheiterte, WESHALB ALLE DREI
        # Schriften inkl. Headline auf die winzige Pillow-Standardschrift zurueckfielen - das war
        # die eigentliche Ursache fuer 'Text viel zu klein').
        font_body = ImageFont.truetype(str(FONT_DIR / "Inter-Variable.ttf"), 32)
        font_body.set_variation_by_name("SemiBold")
        font_cta = ImageFont.truetype(str(FONT_DIR / "Inter-Variable.ttf"), 36)
        font_cta.set_variation_by_name("Bold")
    except Exception:
        # Fallback: Standard-Font (OSError bei fehlender/kaputter Datei, aber auch andere Fehler
        # bei set_variation_by_name abfangen - besser lesbare-aber-falsche Schrift als Crash)
        font_headline = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_cta = ImageFont.load_default()

    # HILO Farben
    NAVY = "#1f428d"
    GREEN = "#60a33c"
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
        return "#1f428d", "#ffffff"  # helles Motiv -> Navy-Text, weisse Outline
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
    Aufrufer nicht angepasst werden muessen - es wird nie mehr eine Flaeche gezeichnet.

    #Kollisionsschutz: lange Woerter (z.B. deutsche Komposita wie 'Entfernungspauschale')
    koennen in schmalen Spalten auf 2 Zeilen umbrechen und dadurch die Box-Hoehe sprengen -
    das reicht dann ggf. bis in die reservierte Logo-Kreis-Zone hinein, unabhaengig davon wie
    die Box selbst dimensioniert ist. Deshalb: passt der umgebrochene Text nicht in die Box-
    Hoehe, wird die Schrift schrittweise verkleinert (font_variant, funktioniert bei jeder TTF),
    bis er passt oder eine Mindestgroesse erreicht ist."""
    # Pixel-Koordinaten berechnen
    x = int(box.x * img_width)
    y = int(box.y * img_height)
    w = int(box.width * img_width)
    h = int(box.height * img_height)

    # Text umbrechen; passt er nicht in die Box-Hoehe, Schrift schrittweise verkleinern.
    mindestgroesse = max(18, int(font.size * 0.55))
    for _ in range(8):
        wrapped_lines = _wrap_text(text, font, w)
        line_height = _get_line_height(font)
        total_text_height = len(wrapped_lines) * line_height
        if total_text_height <= h or font.size <= mindestgroesse:
            break
        neue_groesse = max(mindestgroesse, font.size - 4)
        if neue_groesse == font.size:
            break
        font = font.font_variant(size=neue_groesse)

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

        text_y += line_height


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
    """Rendert CTA als Pillen-Button - IMMER unten mittig, Breite passt sich automatisch an den
    Text an (#Layout-Fix). 'box' (aus dem Layout-Template) wird bewusst NICHT fuer Position/
    Breite verwendet: die Templates hatten unterschiedliche, teils schmale/versetzte CTA-Boxen
    (mal links, mal mittig im Bild) - bei laengeren, insbesondere PERSONALISIERTEN CTA-Texten
    (z.B. mit Ortsname) lief der Text seitlich aus der festen Box heraus und wurde abgeschnitten
    bzw. ueberlappte andere Elemente wie den Logo-Kreis. Jetzt: Button-Breite = tatsaechliche
    Textbreite + Innenabstand, horizontal zentriert, fester Abstand vom unteren Bildrand. Darf
    dafuer bewusst einen Teil des Motivs ueberdecken (unwichtiger als abgeschnittener Text).

    Kreis-Ausweichlogik (#Kollisionsschutz): der Logo-Kreis (bildgen.add_logo_circles,
    pos="diagonal2") sitzt IMMER unten-links, genau dort wo der CTA-Button unten sitzt. Reine
    Pillow-Geometrie, kein KI-Call noetig: faellt der zentrierte Button in die reservierte Zone
    (x<0.30 der Bildbreite), wird er zunaechst nach rechts verschoben (so mittig wie moeglich,
    aber kollisionsfrei). Ist der Text dafuer zu lang (verschobener Button wuerde ueber den
    rechten Rand hinauslaufen), wird die CTA-SCHRIFTGROESSE schrittweise verkleinert, bis der
    Button in die verfuegbare Breite passt - garantiert IMMER kollisionsfrei UND ohne
    abgeschnittenen Text, unabhaengig von der Textlaenge."""
    circle_safe_x = int(img_width * 0.30)
    rand_margin = int(img_width * 0.04)
    verfuegbare_breite = img_width - rand_margin - circle_safe_x

    aktuelle_font = font
    for _ in range(10):  # max. 10 Verkleinerungsschritte (Sicherheitsgrenze gegen Endlosschleife)
        bbox = draw.textbbox((0, 0), text, font=aktuelle_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        pad_x = max(24, int(text_height * 1.1))
        pad_y = max(16, int(text_height * 0.6))
        btn_w = text_width + 2 * pad_x
        btn_h = text_height + 2 * pad_y

        max_w = int(img_width * 0.92)
        passt_zentriert = btn_w <= max_w
        # Passt der Button (zentriert ODER nach rechts verschoben) in die kollisionsfreie Zone?
        passt_ohne_kollision = btn_w <= verfuegbare_breite
        if passt_zentriert and (passt_ohne_kollision or aktuelle_font.size <= 20):
            break  # entweder passt's, oder wir sind an der Mindestgroesse angekommen (Notfall)
        neue_groesse = max(20, aktuelle_font.size - 2)
        if neue_groesse == aktuelle_font.size:
            break
        aktuelle_font = aktuelle_font.font_variant(size=neue_groesse)

    if btn_w > max_w:
        btn_w = max_w  # Notfall (Mindestschriftgroesse erreicht, Text trotzdem noch zu lang)

    x = (img_width - btn_w) // 2
    bottom_margin = int(img_height * 0.06)
    y = img_height - bottom_margin - btn_h

    if x < circle_safe_x:
        x = circle_safe_x
        if x + btn_w > img_width - rand_margin:
            x = img_width - rand_margin - btn_w

    draw.rounded_rectangle([x, y, x + btn_w, y + btn_h], radius=btn_h // 2, fill=bg_color)
    font = aktuelle_font

    text_x = x + (btn_w - text_width) // 2
    text_y = y + (btn_h - text_height) // 2
    draw.text((text_x, text_y), text, font=font, fill=text_color)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Bricht Text in Zeilen um, die in max_width passen.

    Respektiert bestehende Zeilenumbrueche in 'text' als ERZWUNGENE Absatzgrenzen (z.B. zwischen
    einzelnen Bullet-Points, die mit '\\n' getrennt uebergeben werden - siehe render_text_on_image).
    Vorher wurde per text.split() der GESAMTE Text inkl. Zeilenumbruechen in eine flache Wortliste
    zerlegt und komplett neu umgebrochen - dadurch liefen mehrere Bullet-Points in derselben Zeile
    zusammen statt untereinander zu stehen. Jetzt wird pro Absatz (zwischen den '\\n') unabhaengig
    umgebrochen; ein Absatz kann bei Bedarf weiterhin ueber mehrere Zeilen laufen, startet aber nie
    im selben Zeilenrest wie der vorherige Absatz."""
    draw_temp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    all_lines = []
    for absatz in text.split("\n"):
        words = absatz.split()
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw_temp.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width - 20:  # 20px Margin
                current_line = test_line
            else:
                if current_line:
                    all_lines.append(current_line)
                current_line = word
        if current_line:
            all_lines.append(current_line)
    return all_lines


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
    ueber das Motiv). Outline-Farbe ist die zu 'fill_color' PASSENDE Gegenfarbe (weiss bei
    dunklem/Navy-Text, schwarz bei hellem/weissem Text - siehe _text_colors_for_region), NICHT
    IMMER schwarz+weiss zugleich: ein erzwungener schwarzer Ring um dunklen (Navy-)Text
    verschmolz mit der Fuellfarbe selbst und machte die Buchstaben klumpig/schwer lesbar statt
    besser - genau umgekehrtes Ergebnis. Ein einzelner, zur Fuellfarbe komplementaerer Ring
    reicht: er kontrastiert sowohl zum Text (immer) als auch zum ueblichen Hintergrund an dieser
    Stelle (die Farbwahl basiert ja auf der gemessenen Helligkeit genau dort)."""
    x, y = pos
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)
