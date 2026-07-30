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
    highlight_words: list[str] | None = None,
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
        highlight_words: Optionale Liste von Wörtern/Zahlen (aus headline/supporting_points),
            die GRÜN statt in der Standardfarbe hervorgehoben werden (z.B. von GPT gewählt,
            siehe kampagne.CampaignPlan.highlight_words). Nur in Headline/Bullets wirksam,
            nicht im CTA (der hat bereits eine eigene, klare Signalfarbe als Button).

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
        font_body = ImageFont.truetype(str(FONT_DIR / "Inter-Variable.ttf"), 38)
        font_body.set_variation_by_name("Bold")
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

    # Hervorhebungs-Woerter normalisieren (einmalig, case-insensitive Vergleich beim Rendern)
    highlight_set = {w.strip().lower().rstrip(".,!?:;") for w in (highlight_words or []) if w.strip()}

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
        background_overlay, highlight_set
    )

    # 2. Supporting Points rendern
    bullets_text = "\n".join(f"• {p}" for p in supporting_points)
    _render_text_block(
        draw, bullets_text,
        supporting_box, W, H,
        font_body, supporting_color, supporting_outline,
        background_overlay, highlight_set
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
    highlight_words: set[str] | None = None,
):
    """Rendert einen Textblock OHNE Farbflaeche dahinter - der Text layert harmonisch
    ueber das Motiv (sonst sieht man vom Bild nichts mehr). Lesbarkeit kommt stattdessen
    von einer kraeftigeren Outline/Schlagschatten (_draw_text_with_outline), deren Farbe
    hier durchgereicht wird (per Helligkeitsmessung gewaehlt, siehe _text_colors_for_region).
    'add_background' bleibt als Parameter erhalten (Kompatibilitaet, ungenutzt), damit
    Aufrufer nicht angepasst werden muessen - es wird nie mehr eine Flaeche gezeichnet.

    'highlight_words' (normalisiert, kleingeschrieben, ohne Satzzeichen): einzelne Woerter aus
    diesem Textblock, die GRUEN statt in 'text_color' gezeichnet werden (#Hervorhebung, von GPT
    ausgewaehlt - siehe kampagne.CampaignPlan.highlight_words). Erfordert Wort-fuer-Wort-
    Rendering statt einem einzigen draw.text-Aufruf pro Zeile, da eine Zeile jetzt gemischte
    Farben enthalten kann.

    Fortsetzungszeilen (2. Zeile eines umgebrochenen Bullet-Points) werden eingerueckt, damit sie
    unter dem TEXT der 1. Zeile stehen statt unter dem Aufzaehlungszeichen - und zwischen den
    Bullet-Punkten selbst (nicht zwischen den umgebrochenen Zeilen DESSELBEN Punkts) gibt es
    zusaetzlichen Abstand, beides analog zum alten Bild-Design (#Layout-Fix).

    #Kollisionsschutz: lange Woerter (z.B. deutsche Komposita wie 'Entfernungspauschale')
    koennen in schmalen Spalten auf 2 Zeilen umbrechen und dadurch die Box-Hoehe sprengen -
    das reicht dann ggf. bis in die reservierte Logo-Kreis-Zone hinein, unabhaengig davon wie
    die Box selbst dimensioniert ist. Deshalb: passt der umgebrochene Text nicht in die Box-
    Hoehe, wird die Schrift schrittweise verkleinert (font_variant, funktioniert bei jeder TTF),
    bis er passt oder eine Mindestgroesse erreicht ist."""
    highlight_words = highlight_words or set()
    HIGHLIGHT_GRUEN = "#60a33c"

    # Pixel-Koordinaten berechnen
    x = int(box.x * img_width)
    y = int(box.y * img_height)
    w = int(box.width * img_width)
    h = int(box.height * img_height)

    # Einzug fuer Fortsetzungszeilen = Breite von "• " in der aktuellen Schrift (misst sich
    # selbst nach - passt automatisch, falls die Schrift unten schrumpft).
    def _einzug(f):
        return draw.textbbox((0, 0), "• ", font=f)[2]

    extra_bullet_abstand_faktor = 0.4  # zusaetzlicher Abstand zwischen Bullet-Punkten

    # Text umbrechen; passt er nicht in die Box-Hoehe, Schrift schrittweise verkleinern.
    mindestgroesse = max(18, int(font.size * 0.55))
    for _ in range(8):
        zeilen = _wrap_paragraphs(text, font, w - _einzug(font))
        line_height = _get_line_height(font)
        neue_absaetze = sum(1 for _, fortsetzung in zeilen if not fortsetzung)
        extra_abstand = int(line_height * extra_bullet_abstand_faktor)
        total_text_height = len(zeilen) * line_height + max(0, neue_absaetze - 1) * extra_abstand
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

    space_width = draw.textbbox((0, 0), " ", font=font)[2]
    einzug_px = _einzug(font)

    # Zeilen rendern - WORT FUER WORT (statt die ganze Zeile in einem Aufruf), damit einzelne
    # Woerter gruen hervorgehoben werden koennen.
    ist_erste_zeile_gesamt = True
    for line, ist_fortsetzung in zeilen:
        if not ist_fortsetzung and not ist_erste_zeile_gesamt:
            text_y += int(line_height * extra_bullet_abstand_faktor)  # Abstand vor neuem Bullet
        ist_erste_zeile_gesamt = False

        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        einzug_hier = einzug_px if (ist_fortsetzung and box.align == "left") else 0
        if box.align == "left":
            cursor_x = x + 10 + einzug_hier
        elif box.align == "center":
            cursor_x = x + (w - line_width) // 2
        else:  # right
            cursor_x = x + w - line_width - 10

        for word in line.split(" "):
            if not word:
                cursor_x += space_width
                continue
            normalisiert = word.strip().lower().rstrip(".,!?:;")
            farbe = HIGHLIGHT_GRUEN if normalisiert in highlight_words else text_color
            _draw_text_with_outline(draw, (cursor_x, text_y), word, font, farbe,
                                     outline_color=outline_color)
            wort_bbox = draw.textbbox((0, 0), word, font=font)
            cursor_x += (wort_bbox[2] - wort_bbox[0]) + space_width

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
    """Rendert CTA als Pillen-Button mit FESTER Breite - IMMER unten, zentriert in der
    kollisionsfreien Zone (#Layout-Fix, #Kollisionsschutz). 'box' (aus dem Layout-Template)
    wird bewusst NICHT fuer Position/Breite verwendet.

    Anders als eine an den Text angepasste Breite (frueherer Ansatz - Button wurde bei langem
    Text sehr breit und musste dann verschoben/verkleinert werden): die Button-BREITE ist jetzt
    IMMER GLEICH (ein fester Anteil der sicheren Zone zwischen den beiden Logo-Kreisen), egal
    wie lang der Text ist. Der Kreis (bildgen.add_logo_circles, pos="diagonal2", IMMER unten-
    links) kann den fest positionierten Button dadurch prinzipbedingt nie beruehren - keine
    Verschiebung noetig, der Button bleibt immer an der gleichen Stelle und gleich breit.

    Der TEXT passt sich stattdessen der festen Breite an: passt er auf eine Zeile, einzeilig;
    ist er zu lang, bricht er automatisch auf 2 Zeilen um (wie die Bullet-Punkte); nur wenn
    selbst 2 Zeilen bei minimaler Schriftgroesse nicht reichen (extrem lange Texte), wird die
    Schrift zusaetzlich schrittweise verkleinert - reiner Notfall-Fallback."""
    circle_safe_x = int(img_width * 0.30)
    rand_margin = int(img_width * 0.04)
    safe_left = circle_safe_x
    safe_right = img_width - rand_margin
    safe_width = safe_right - safe_left

    # Feste Button-Breite: 92% der sicheren Zone (etwas Luft an beiden Raendern), IMMER gleich -
    # unabhaengig vom Text. Zentriert INNERHALB der sicheren Zone (nicht des Gesamtbilds, da die
    # sichere Zone durch den Kreis unten-links asymmetrisch ist).
    btn_w = int(safe_width * 0.92)
    x = safe_left + (safe_width - btn_w) // 2

    pad_x = 32
    innenbreite = btn_w - 2 * pad_x

    aktuelle_font = font
    zeilen = [text]
    for _ in range(10):  # Sicherheitsgrenze gegen Endlosschleife
        bbox = draw.textbbox((0, 0), text, font=aktuelle_font)
        einzeilig_breite = bbox[2] - bbox[0]
        if einzeilig_breite <= innenbreite:
            zeilen = [text]
            break
        zeilen = _wrap_text(text, aktuelle_font, innenbreite + 20)  # +20: Marge von _wrap_text selbst
        breiten = [draw.textbbox((0, 0), z, font=aktuelle_font)[2] for z in zeilen]
        if len(zeilen) <= 2 and max(breiten) <= innenbreite:
            break
        neue_groesse = max(18, aktuelle_font.size - 2)
        if neue_groesse == aktuelle_font.size:
            break  # Mindestgroesse erreicht - Notfall, laesst 3+ Zeilen zu statt abzuschneiden
        aktuelle_font = aktuelle_font.font_variant(size=neue_groesse)
    font = aktuelle_font

    zeilen_hoehe = _get_line_height(font)
    text_gesamt_hoehe = len(zeilen) * zeilen_hoehe
    pad_y = max(16, int(zeilen_hoehe * 0.35))
    btn_h = text_gesamt_hoehe + 2 * pad_y

    bottom_margin = int(img_height * 0.06)
    y = img_height - bottom_margin - btn_h

    draw.rounded_rectangle([x, y, x + btn_w, y + btn_h], radius=btn_h // 2, fill=bg_color)

    text_y = y + pad_y
    for zeile in zeilen:
        bbox = draw.textbbox((0, 0), zeile, font=font)
        zeile_breite = bbox[2] - bbox[0]
        text_x = x + (btn_w - zeile_breite) // 2
        draw.text((text_x, text_y), zeile, font=font, fill=text_color)
        text_y += zeilen_hoehe



def _wrap_paragraphs(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[tuple[str, bool]]:
    """Wie _wrap_text, markiert aber zusaetzlich pro Zeile, ob sie eine FORTSETZUNGSZEILE ist
    (2. oder weitere Zeile desselben Absatzes/Bullet-Points) statt die erste Zeile eines neuen
    Absatzes. Wird fuer den Einzug von Fortsetzungszeilen bei Bullet-Points gebraucht (#Layout-
    Fix: die 2. Zeile eines umgebrochenen Bullets stand bisher unter dem Aufzaehlungszeichen
    statt eingerueckt unter dem Text der 1. Zeile) sowie fuer extra Abstand zwischen Bullets."""
    draw_temp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    result: list[tuple[str, bool]] = []
    for absatz in text.split("\n"):
        words = absatz.split()
        current_line = ""
        ist_erste_zeile = True
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw_temp.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width - 20:  # 20px Margin
                current_line = test_line
            else:
                if current_line:
                    result.append((current_line, not ist_erste_zeile))
                    ist_erste_zeile = False
                current_line = word
        if current_line:
            result.append((current_line, not ist_erste_zeile))
    return result


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Bricht Text in Zeilen um, die in max_width passen.

    Respektiert bestehende Zeilenumbrueche in 'text' als ERZWUNGENE Absatzgrenzen (z.B. zwischen
    einzelnen Bullet-Points, die mit '\\n' getrennt uebergeben werden - siehe render_text_on_image).
    Vorher wurde per text.split() der GESAMTE Text inkl. Zeilenumbruechen in eine flache Wortliste
    zerlegt und komplett neu umgebrochen - dadurch liefen mehrere Bullet-Points in derselben Zeile
    zusammen statt untereinander zu stehen. Jetzt wird pro Absatz (zwischen den '\\n') unabhaengig
    umgebrochen; ein Absatz kann bei Bedarf weiterhin ueber mehrere Zeilen laufen, startet aber nie
    im selben Zeilenrest wie der vorherige Absatz."""
    return [line for line, _ in _wrap_paragraphs(text, font, max_width)]


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
    """Zeichnet Text OHNE Rand/Outline - reine Fuellfarbe (#Layout-Fix: der weisse/schwarze Rand
    um die Buchstaben wirkte unschoen/klobig, auf Wunsch entfernt). 'outline_color' und
    'outline_width' bleiben als Parameter erhalten (Kompatibilitaet mit bestehenden Aufrufern),
    werden aber nicht mehr verwendet. Lesbarkeit kommt jetzt ausschliesslich aus der
    Helligkeits-basierten Farbwahl (_text_colors_for_region: Navy auf hellem, Weiss auf dunklem
    Bildbereich) und der fetten Schrift - kein Sicherheitsnetz mehr bei sehr unruhigen/gemischt
    hell-dunklen Bildstellen (dafuer gibt's die QA-Pruefung als Auffangnetz)."""
    x, y = pos
    draw.text((x, y), text, font=font, fill=fill_color)
