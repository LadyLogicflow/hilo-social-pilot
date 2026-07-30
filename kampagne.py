#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-Stufen-Workflow für automatisierte Kampagnen-Generierung mit Qualitätskontrolle.

Workflow:
1. GPT-5.6 Terra: Kampagnenplanung (Structured Output)
2. GPT Image 2: Grafik-Generierung (2048x2048, high quality)
3. GPT-5.6 Terra: Qualitätskontrolle (automatische Retry bei Fehlern)

Basiert auf ChatGPT-Feedback vom 2026-07-29.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from config import DATA_DIR
from secrets_store import get_secret
from text_renderer import render_text_on_image

log = logging.getLogger("hilo.kampagne")


def _get_client() -> OpenAI:
    """Erstellt OpenAI-Client mit API-Key aus secrets.json oder Umgebung.

    Versucht zuerst secrets.json, dann OPENAI_API_KEY aus env.

    Raises:
        ValueError: Wenn kein API-Key verfügbar ist
    """
    api_key = get_secret("openai_api_key")
    if not api_key:
        # Fallback: Umgebungsvariable (für Container)
        api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "Kein OpenAI API-Key verfügbar! "
            "Bitte 'openai_api_key' in data/secrets.json hinterlegen "
            "oder OPENAI_API_KEY als Umgebungsvariable setzen."
        )

    return OpenAI(api_key=api_key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STRUCTURED OUTPUT MODELS (Pydantic)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TextBox(BaseModel):
    """Position und Ausrichtung eines Textblocks (normalisierte Koordinaten 0.0-1.0)."""
    x: float = Field(ge=0.0, le=1.0, description="X-Position (0.0 = links, 1.0 = rechts)")
    y: float = Field(ge=0.0, le=1.0, description="Y-Position (0.0 = oben, 1.0 = unten)")
    width: float = Field(ge=0.0, le=1.0, description="Breite (0.0-1.0)")
    height: float = Field(ge=0.0, le=1.0, description="Höhe (0.0-1.0)")
    align: Literal["left", "center", "right"] = Field(description="Horizontale Ausrichtung")
    vertical_align: Literal["top", "center", "bottom"] = Field(description="Vertikale Ausrichtung")


class CampaignPlan(BaseModel):
    """Kampagnenplan von GPT-5.6 Terra (Stufe 1).

    Structured Output mit allen notwendigen Informationen für die Grafik-Generierung.
    """
    core_message: str = Field(description="Kernaussage des Steuertexts in einem Satz")
    target_emotion: str = Field(description="Ziel-Emotion (z.B. Optimismus, Vertrauen, Erleichterung)")

    headline: str = Field(max_length=55, description="Prägnante Überschrift (max. 55 Zeichen)")
    supporting_points: list[str] = Field(
        min_length=2,
        max_length=3,
        description="2-3 kurze Infopunkte (je max. 45 Zeichen)"
    )
    cta: str = Field(max_length=35, description="Call-to-Action (max. 35 Zeichen)")
    caption: str = Field(description="Begleittext für Social Media (150-200 Wörter, mit Hook und Interaktionsfrage)")

    visual_strategy: str = Field(description="Gewählte Bildstrategie (z.B. Editorial Photography, Still Life)")
    visual_concept: str = Field(description="Beschreibung des visuellen Konzepts")
    hero_element: str = Field(description="Dominantes Hauptelement im Bild")
    layout: str = Field(description="Layout-Beschreibung (z.B. 'Text links, Motiv rechts')")
    background: str = Field(description="Hintergrund-Beschreibung")
    text_contrast: str = Field(description="Farbkontrast für Text (z.B. 'Navy auf hell')")
    accent_usage: str = Field(description="Verwendung der Akzentfarben")

    # NEU: Layout-Informationen für Pillow-Text-Rendering
    layout_template: Literal[
        "text_left_hero_right",
        "text_right_hero_left",
        "text_top_hero_bottom",
        "hero_top_text_bottom",
        "centered_headline_bottom_panel",
        "editorial_split"
    ] = Field(description="Gewählte Layout-Vorlage")

    # TextBox-Felder werden automatisch aus LAYOUT_TEMPLATES gefüllt (nicht von GPT!)
    headline_box: Optional[TextBox] = Field(default=None, description="Position für Headline (wird automatisch gefüllt)")
    supporting_box: Optional[TextBox] = Field(default=None, description="Position für Bullets (wird automatisch gefüllt)")
    cta_box: Optional[TextBox] = Field(default=None, description="Position für CTA (wird automatisch gefüllt)")

    # Für GPT Image 2: NUR Motiv-Prompt (OHNE Text!)
    motiv_prompt: str = Field(description="Englischer Prompt NUR für das Motiv (OHNE Text-Rendering!)")


class CaptionOnly(BaseModel):
    """Nur Caption für Bestandsposts (ohne Bild-Generierung)."""
    caption: str = Field(description="Begleittext für Social Media (150-200 Wörter, mit Hook und Interaktionsfrage)")


class QualityReview(BaseModel):
    """Qualitätsprüfung von GPT-5.6 Terra (Stufe 3).

    Prüft das generierte Bild auf Lesbarkeit, Motiv-Qualität und Layout
    (Text-Korrektheit wird von Pillow garantiert!).
    """
    approved: bool = Field(description="True = Bild freigegeben, False = Neu generieren")

    # Text-Checks ENTFERNT (wird von Pillow garantiert!)
    # text_is_exact: bool  ❌ NICHT MEHR NÖTIG
    # spelling_is_correct: bool  ❌ NICHT MEHR NÖTIG

    all_text_is_readable: bool = Field(description="Alle Texte gut lesbar?")
    text_has_good_contrast: bool = Field(description="Text-Kontrast ausreichend?")
    text_not_overlapping: bool = Field(description="Text überlappt nicht mit Motiv?")
    message_matches_article: bool = Field(description="Aussage entspricht dem Steuertext?")
    layout_is_professional: bool = Field(description="Layout professionell?")
    motiv_is_high_quality: bool = Field(description="Motiv hochwertig und ansprechend?")

    problems: list[str] = Field(description="Liste gefundener Probleme")
    correction_instruction: str = Field(description="Anweisung zur Korrektur (falls approved=False)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LAYOUT-VORLAGEN (für Pillow Text-Rendering)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CREATIVE DIRECTOR SYSTEMPROMPT (Stufe 1)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CREATIVE_DIRECTOR_PROMPT = """Du bist Creative Director, Senior Art Director und Werbetexter für HILO,
einen deutschen Lohnsteuerhilfeverein.

Entwickle aus dem gelieferten Steuertext eine vollständige Social-Media-Kampagne,
die ohne manuelle Nachbearbeitung durch GPT Image 2 umgesetzt werden kann.

ANALYSE

Ermittle:
1. die wichtigste fachliche Aussage
2. den konkreten Nutzen für Arbeitnehmer oder Rentner
3. die geeignete emotionale Wirkung
4. eine innerhalb von drei Sekunden verständliche Bildidee

TEXTERSTELLUNG

Erstelle:
- eine prägnante deutsche Headline mit höchstens 55 Zeichen
- zwei oder drei kurze Infopunkte mit jeweils höchstens 45 Zeichen
- einen kurzen Call-to-Action

Alle Aussagen müssen fachlich vom Eingabetext gedeckt sein.
Erfinde keine Beträge, Fristen, Voraussetzungen oder Rechtsfolgen.
Nicht gendern.

CAPTION (BEGLEITTEXT)

Erstelle einen deutschen Begleittext für Social Media (150-200 Wörter):

AUFBAU:
- HOOK (erster Satz, max. 10 Wörter): überraschend, direkt, neugierig machend
- INHALT: Erkläre das Thema knapp, nutzenorientiert, ohne Fachchinesisch
- INTERAKTIONSFRAGE: Stelle VOR dem Handlungsaufruf eine kurze Frage
- HANDLUNGSAUFRUF: Weise auf HILO-Beratung hin

STIL:
- Durchgehend SIE-Form (gesiezt, nie geduzt)
- Klar, direkt, menschlich (nicht belehrend)
- Echte UTF-8 Umlaute (ä, ö, ü, ß)
- KEINE Abkürzungen (z.B. → zum Beispiel)
- Sparsam mit Emojis (max. 2)
- 4-5 thematisch passende Hashtags, #HILO als letzten

WICHTIG:
- Nutze WENN MÖGLICH einen konkreten Fakt, Frist oder Urteil aus dem Eingabetext
- Nenne Quellen als TEXT ("Laut Bundesfinanzhof..."), KEINE Links
- Erfinde KEINE Fakten, Urteile, Beträge oder Fristen
- KEINE URLs im Text (werden automatisch ergänzt)

KREATIVKONZEPT

Entwickle intern drei deutlich unterschiedliche Bildideen.
Wähle anschließend die stärkste Idee nach:
- sofortiger Verständlichkeit
- Originalität
- Kampagnenwirkung
- Umsetzbarkeit mit integrierter Typografie
- Eignung für HILO

Bevorzuge je nach Thema:
- Editorial Photography
- Concept Photography
- Still Life
- Flat Lay
- authentische Lifestyle-Fotografie
- Editorial Illustration
- Ligne-Claire-Comic
- moderne 3D-Illustration

Verwende eine Infografik nur, wenn ein Ablauf oder Vergleich im Mittelpunkt steht.

GESTALTUNG

Die Anzeige muss als vollständige quadratische Werbegrafik funktionieren.

Sie benötigt:
- ein dominantes Hero-Element
- eine klare Blickführung
- einen ruhigen und gut lesbaren Textbereich
- eine eindeutige Hierarchie aus Headline, Infopunkten und CTA
- hohe Lesbarkeit auf Smartphones
- großzügige Abstände
- eine hochwertige, moderne Werbeästhetik

HILO-Farben:
- Navy: #1a3a6b
- Grün: #4a8c5c
- Lavendelblau: #b8c8e8
- Weiß: #ffffff

Nutze die Farben kontrolliert und hochwertig.

VERMEIDEN

- generische Businesspersonen
- gestellte Stockfoto-Posen
- übertriebenes Lächeln
- Geldregen
- übergroße Eurozeichen
- das Wort "HILO" in der Typografie
- zusätzliche Logos
- QR-Codes
- Wasserzeichen
- erfundene Texte

LAYOUT-PLANUNG

Wähle eine passende Layout-Vorlage aus den folgenden Optionen:

- text_left_hero_right: Text links (45%), Motiv rechts (50%)
- text_right_hero_left: Text rechts (40%), Motiv links (50%)
- text_top_hero_bottom: Text oben (55%), Motiv unten (45%)
- hero_top_text_bottom: Motiv oben (55%), Text unten (40%)
- centered_headline_bottom_panel: Zentrale Headline, unteres Text-Panel
- editorial_split: Editorial Split-Layout (Text links, Motiv rechts halbseitig)

Wähle das Layout das am besten zum Thema, Motiv und zur Aussage passt.

(Die Text-Positionen werden automatisch aus der Vorlage übernommen.)

MOTIV-PROMPT (NUR FÜR DAS BILD, OHNE TEXT!)

Formuliere einen englischen Produktionsprompt für GPT Image 2.

WICHTIG - DIES IST ENTSCHEIDEND:
- Der Prompt beschreibt NUR das visuelle Motiv
- KEIN Text, KEINE Typografie, KEINE Buchstaben, KEINE Zahlen!
- Das Motiv muss eine ruhige, freie Fläche für späteren Text lassen
- Verwende die Layout-spezifische Anweisung aus der gewählten Vorlage

Beispiel für "text_left_hero_right":

────────────────────────────────────────────────────────────────

Generate a professional tax consultation scene with warm natural lighting.

COMPOSITION:
Keep the left 45% of the image visually calm and free of important objects.
Place the hero subject (tax consultant, documents, calculator) on the right side.

STYLE:
Clean, modern aesthetic. High-quality photography.
Warm, inviting atmosphere with professional credibility.

COLORS:
Use HILO brand colors as accents:
- Navy #1a3a6b (background or supporting elements)
- Green #4a8c5c (accent details)
- Lavender #b8c8e8 (subtle highlights)
- White #ffffff (clean surfaces)

CORNER SAFE ZONES:
Keep all four corners clear (12% width × 12% height per corner) for logo overlays.

CRITICAL:
DO NOT RENDER ANY TEXT, LETTERS, NUMBERS OR TYPOGRAPHY.
The image must have clean, uncluttered areas for text overlay.

────────────────────────────────────────────────────────────────

Passe dieses Muster an:
- Verwende die Layout-Anweisung aus der gewählten Vorlage
- Beschreibe das Hero-Element präzise
- Nutze HILO-Farben als Akzente
- Stelle sicher dass der Textbereich RUHIG und FREI bleibt
- Wiederhole am Ende: "DO NOT RENDER ANY TEXT"

Der finale motiv_prompt muss vollständig in Englisch sein.

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STUFE 1: KAMPAGNENPLANUNG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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

    Raises:
        ValueError: Wenn Artikel leer ist
        RuntimeError: Wenn kein Plan erzeugt wurde
    """
    if not article or not article.strip():
        raise ValueError("Artikel darf nicht leer sein!")

    client = _get_client()
    log.info("Stufe 1: Kampagnenplanung wird erstellt...")

    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",  # Terra-Version wie von Catrin angewiesen!
        messages=[
            {
                "role": "system",
                "content": CREATIVE_DIRECTOR_PROMPT,
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

    # TextBox-Felder aus LAYOUT_TEMPLATES übernehmen
    template = LAYOUT_TEMPLATES[plan.layout_template]
    plan.headline_box = template["headline_box"]
    plan.supporting_box = template["supporting_box"]
    plan.cta_box = template["cta_box"]

    log.info("Stufe 1: Kampagnenplan erstellt - Headline: %s, Layout: %s", plan.headline, plan.layout_template)
    return plan


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STUFE 2: GRAFIK-GENERIERUNG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_advertisement(
    motiv_prompt: str,
    output_path: Optional[str] = None,
    size: Literal["1024x1024", "2048x2048"] = "1024x1024",
    quality: Literal["low", "medium", "high", "auto"] = "high",
) -> Path:
    """Stufe 2a: Motiv-Generierung mit GPT Image 2 (OHNE Text!).

    Args:
        motiv_prompt: Englischer Prompt NUR für das Motiv (OHNE Text!)
        output_path: Optional: Ziel-Pfad (Standard: auto-generiert)
        size: Bildgröße (1024x1024 optimal für 1080x1080 Feed-Posts!)
        quality: Qualitätsstufe (low für Tests, high für Produktion)

    Returns:
        Path zum gespeicherten PNG (NUR Motiv, Text wird später mit Pillow eingefügt!)

    Raises:
        RuntimeError: Wenn keine Bilddaten zurückkamen
    """
    client = _get_client()
    log.info("Stufe 2a: Motiv wird generiert (OHNE Text, size=%s, quality=%s)...", size, quality)

    result = client.images.generate(
        model="gpt-image-2",
        prompt=motiv_prompt,
        size=size,
        quality=quality,
        output_format="png",
    )

    image_base64 = result.data[0].b64_json

    if not image_base64:
        raise RuntimeError("Das Bildmodell lieferte keine Bilddaten.")

    # Auto-generiere Pfad falls nicht angegeben
    if not output_path:
        import time
        timestamp = int(time.time())
        output_path = os.path.join(DATA_DIR, "kampagne", f"campaign_{timestamp}.png")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    path = Path(output_path)
    path.write_bytes(base64.b64decode(image_base64))

    log.info("Stufe 2: Grafik gespeichert unter %s", path)
    return path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STUFE 3: QUALITÄTSKONTROLLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


QA_PROMPT = """Du bist Qualitätskontrolleur für HILO Social-Media-Werbeanzeigen.

WICHTIG: Die Texte (Headline, Bullets, CTA) wurden bereits mit Pillow eingefügt
und sind garantiert vorhanden und korrekt geschrieben!

Prüfe das generierte Bild auf:

1. LESBARKEIT: Sind alle Texte auf einem Smartphone (6 Zoll) SCHARF und KLAR LESBAR?
   - Ausreichende Schriftgröße?
   - Guter Kontrast zum Hintergrund?
   - Keine Überlappung mit Motivelementen?
   - Bei schlechtem Kontrast oder Überlappung: approved = False!

2. FACHLICHE ÜBEREINSTIMMUNG: Entspricht die Aussage dem Originaltext?
   - Passt das Motiv zum Thema?
   - Keine irreführenden visuellen Elemente?

3. LAYOUT & KOMPOSITION: Wirkt das Layout professionell und hochwertig?
   - Harmonieren Text und Motiv?
   - Sind die Proportionen ausgewogen?
   - Ist die Bildsprache passend für HILO?

4. MOTIV-QUALITÄT: Ist das Motiv hochwertig und ansprechend?
   - Keine störenden Elemente im Textbereich?
   - Professionelle Bildqualität?
   - Ansprechende visuelle Umsetzung?

Bei JEDEM Problem: approved = False!

Beispiele für Problems:
- "Text hat schlechten Kontrast zum Hintergrund (schwer lesbar)"
- "Headline überlappt mit Motivelementen"
- "Das Motiv passt nicht zum Thema Steuern/Beratung"
- "Bildqualität wirkt unprofessionell oder verschwommen"
- "Layout wirkt unausgewogen (zu viel leer, zu voll, schlechte Komposition)"

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


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

    Raises:
        RuntimeError: Wenn keine Review erzeugt wurde
    """
    client = _get_client()
    log.info("Stufe 3: Qualitätskontrolle wird durchgeführt...")

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

    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",  # Terra für multimodales QA
        messages=[
            {
                "role": "system",
                "content": QA_PROMPT,
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

    if review.approved:
        log.info("Stufe 3: Bild FREIGEGEBEN ✅")
    else:
        log.warning("Stufe 3: Bild ABGELEHNT ❌ - Probleme: %s", ", ".join(review.problems))

    return review


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KOMPLETTER WORKFLOW MIT RETRY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_campaign(
    article: str,
    cta: str = "Jetzt Termin vereinbaren",
    output_path: Optional[str] = None,
    max_retries: int = 1,
    test_mode: bool = False,
) -> tuple[CampaignPlan, Path, QualityReview]:
    """Kompletter 3-Stufen-Workflow. Standardmaessig OHNE Neugenerierung bei QA-Ablehnung
    (max_retries=1, #Kostenschutz): das Motiv (teuerster Schritt, GPT Image 2) wird nur EINMAL
    erzeugt. Die QA laeuft trotzdem und markiert Probleme (review.approved=False,
    review.problems) - das Bild geht dann zur manuellen Pruefung raus statt automatisch neu
    (und erneut kostenpflichtig) generiert zu werden. Hoeheren Wert nur bewusst setzen, wenn
    die Mehrkosten pro Ablehnung in Kauf genommen werden.

    Args:
        article: Vollständiger Steuertext
        cta: Call-to-Action
        output_path: Optional: Ziel-Pfad für finale Grafik
        max_retries: Maximale Anzahl Neugenerierungen bei QA-Fehlern (Default 1 = kein Retry)
        test_mode: True = low quality für Tests, False = high quality für Produktion

    Returns:
        (CampaignPlan, finale_image_path, QualityReview)

    Raises:
        RuntimeError: Wenn nach max_retries immer noch Fehler
    """
    log.info("━━━━ 3-STUFEN-WORKFLOW GESTARTET ━━━━")

    # Stufe 1: Kampagnenplanung (nur einmal!)
    plan = create_campaign_plan(article, cta=cta)

    # Stufe 2 + 3: Grafik + QA (mit Retry)
    size = "1024x1024"  # Immer 1024x1024 - optimal für 1080x1080 Feed-Posts!
    quality = "low" if test_mode else "high"

    # Kampagne-Verzeichnis erstellen (falls noch nicht vorhanden)
    kampagne_dir = os.path.join(DATA_DIR, "kampagne")
    os.makedirs(kampagne_dir, exist_ok=True)

    for attempt in range(1, max_retries + 1):
        log.info("━━━━ VERSUCH %d/%d ━━━━", attempt, max_retries)

        try:
            # Stufe 2a: Motiv generieren (OHNE Text!)
            motiv_path = os.path.join(kampagne_dir, f"motiv_{attempt}.png")

            motiv_image_path = generate_advertisement(
                plan.motiv_prompt,
                output_path=motiv_path,
                size=size,
                quality=quality,
            )

            # Stufe 2b: Text mit Pillow hinzufügen
            final_path = os.path.join(
                kampagne_dir, f"final_{attempt}.png"
            ) if not output_path else output_path

            log.info("Stufe 2b: Text-Rendering mit Pillow (Layout: %s)...", plan.layout_template)
            image_path = render_text_on_image(
                motiv_image_path,
                plan.headline,
                plan.supporting_points,
                plan.cta,
                plan.headline_box,
                plan.supporting_box,
                plan.cta_box,
                Path(final_path),
                background_overlay=True,  # Halbtransparente Hintergründe hinter Text
            )
            log.info("Stufe 2b: Text gerendert und gespeichert unter %s", image_path)

            # Stufe 3: QA (mit finalem Bild inkl. Text!)
            review = quality_check(image_path, plan, article)

            if review.approved:
                log.info("━━━━ WORKFLOW ERFOLGREICH NACH %d VERSUCH(EN) ━━━━", attempt)
                return plan, image_path, review

            if attempt < max_retries:
                log.info("Versuch %d: Bild abgelehnt, neuer Versuch...", attempt)
            else:
                log.warning("Alle Versuche fehlgeschlagen! Probleme: %s", ", ".join(review.problems))
                # Bild trotzdem zurückgeben für manuelle Prüfung
                return plan, image_path, review

        except Exception as e:
            log.warning("Versuch %d fehlgeschlagen (Exception): %s", attempt, e)
            if attempt < max_retries:
                continue
            else:
                raise RuntimeError(
                    f"Alle {max_retries} Versuche fehlgeschlagen! Letzte Exception: {e}"
                ) from e

    # Sollte nie erreicht werden
    raise RuntimeError("Workflow-Logik-Fehler")


def regenerate_image_with_qa(
    image_prompt: str,
    headline: str,
    supporting_points: list[str],
    cta: str,
    article_excerpt: str = "",
    output_path: Optional[str] = None,
    max_retries: int = 1,
    test_mode: bool = False,
) -> tuple[Path, QualityReview]:
    """Nur Stufe 2 + 3: Bild neu generieren mit QA (OHNE Kampagnenplanung).

    Für "neues Foto würfeln" im Dashboard - verwendet bestehenden image_prompt
    statt neue Kampagnenplanung zu machen.

    Standardmaessig OHNE automatischen Retry bei QA-Ablehnung (max_retries=1,
    #Kostenschutz) - das Motiv wird nur einmal (kostenpflichtig) erzeugt; die QA
    markiert Probleme fuer die manuelle Pruefung statt automatisch neu zu generieren.

    Args:
        image_prompt: Bestehender englischer Prompt für GPT Image 2
        headline: Erwartete Headline (für QA)
        supporting_points: Erwartete Infopunkte (für QA)
        cta: Erwarteter CTA (für QA)
        article_excerpt: Optionaler Artikel-Auszug (für QA-Kontext)
        output_path: Optionaler Ausgabepfad für das Bild
        max_retries: Maximale Anzahl Versuche bei QA-Ablehnung
        test_mode: True = low quality für Tests

    Returns:
        Tuple von (image_path, review)

    Raises:
        RuntimeError: Wenn alle Versuche fehlschlagen
    """
    import time

    # Kampagne-Verzeichnis erstellen (falls noch nicht vorhanden)
    kampagne_dir = os.path.join(DATA_DIR, "kampagne")
    os.makedirs(kampagne_dir, exist_ok=True)

    # Bildgröße und Qualität
    size = "1024x1024"  # Immer 1024x1024 - optimal für 1080x1080 Feed-Posts!
    quality = "low" if test_mode else "high"

    # Mini-Plan für QA (ohne vollständige Kampagnenplanung)
    from types import SimpleNamespace
    mini_plan = SimpleNamespace(
        headline=headline,
        supporting_points=supporting_points,
        cta=cta,
        core_message="",  # Nicht verfügbar bei Regeneration
    )

    for attempt in range(1, max_retries + 1):
        log.info("━━━━ BILD-REGENERIERUNG: VERSUCH %d/%d ━━━━", attempt, max_retries)

        try:
            # Stufe 2: Grafik generieren
            temp_path = os.path.join(
                kampagne_dir, f"regen_{int(time.time())}_{attempt}.png"
            ) if not output_path else output_path

            image_path = generate_advertisement(
                image_prompt,
                output_path=temp_path,
                size=size,
                quality=quality,
            )

            # Stufe 3: QA
            review = quality_check(image_path, mini_plan, article_excerpt or headline)

            if review.approved:
                log.info("Bild-Regenerierung erfolgreich nach %d Versuch(en) ✅", attempt)
                return image_path, review
            else:
                log.info(
                    "Versuch %d: Bild abgelehnt - Probleme: %s",
                    attempt,
                    ", ".join(review.problems)
                )
                if attempt < max_retries:
                    continue
                else:
                    log.warning(
                        "Alle %d Versuche fehlgeschlagen! Letzte Probleme: %s",
                        max_retries,
                        ", ".join(review.problems)
                    )
                    # Gib das letzte Bild zurück, auch wenn nicht approved
                    return image_path, review

        except Exception as e:
            log.warning("Versuch %d fehlgeschlagen (Exception): %s", attempt, e)
            if attempt < max_retries:
                continue
            else:
                raise RuntimeError(f"Alle {max_retries} Versuche fehlgeschlagen!") from e

    # Sollte nie erreicht werden
    raise RuntimeError("Regenerierung-Logik-Fehler")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CAPTION-ONLY FÜR BESTANDSPOSTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


CAPTION_ONLY_PROMPT = """Du bist Social-Media-Texter für HILO, einen deutschen Lohnsteuerhilfeverein.

Erstelle einen deutschen Begleittext für Social Media (150-200 Wörter):

AUFBAU:
- HOOK (erster Satz, max. 10 Wörter): überraschend, direkt, neugierig machend
- INHALT: Erkläre das Thema knapp, nutzenorientiert, ohne Fachchinesisch
- INTERAKTIONSFRAGE: Stelle VOR dem Handlungsaufruf eine kurze Frage
- HANDLUNGSAUFRUF: Weise auf HILO-Beratung hin

STIL:
- Durchgehend SIE-Form (gesiezt, nie geduzt)
- Klar, direkt, menschlich (nicht belehrend)
- Echte UTF-8 Umlaute (ä, ö, ü, ß)
- KEINE Abkürzungen (z.B. → zum Beispiel)
- Sparsam mit Emojis (max. 2)
- 4-5 thematisch passende Hashtags, #HILO als letzten

WICHTIG:
- Nutze WENN MÖGLICH einen konkreten Fakt, Frist oder Urteil aus dem Eingabetext
- Nenne Quellen als TEXT ("Laut Bundesfinanzhof..."), KEINE Links
- Erfinde KEINE Fakten, Urteile, Beträge oder Fristen
- KEINE URLs im Text (werden automatisch ergänzt)

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


def generate_caption_only(article: str) -> str:
    """Generiert NUR Caption für Bestandsposts (ohne Bild).

    Args:
        article: Vollständiger Steuertext oder Newslettertext

    Returns:
        Caption als String

    Raises:
        ValueError: Wenn Artikel leer ist
        RuntimeError: Wenn keine Caption erzeugt wurde
    """
    if not article or not article.strip():
        raise ValueError("Artikel darf nicht leer sein!")

    client = _get_client()
    log.info("Caption-only wird generiert...")

    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",
        messages=[
            {
                "role": "system",
                "content": CAPTION_ONLY_PROMPT,
            },
            {
                "role": "user",
                "content": f"STEUERTEXT:\n{article}",
            },
        ],
        response_format=CaptionOnly,
    )

    result = response.choices[0].message.parsed

    if result is None or not result.caption:
        raise RuntimeError("Es wurde keine Caption erzeugt.")

    log.info("Caption-only generiert: %s...", result.caption[:50])
    return result.caption


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI FÜR TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Test-Artikel
    test_article = """
    Kosten für einen beruflich veranlassten Umzug können unter bestimmten
    Voraussetzungen als Werbungskosten berücksichtigt werden. Neben
    nachgewiesenen Einzelkosten kommen gegebenenfalls Umzugskostenpauschalen
    in Betracht. Belege sollten sorgfältig aufbewahrt werden.
    """

    print("\n" + "="*80)
    print("3-STUFEN-WORKFLOW TEST")
    print("="*80 + "\n")

    try:
        plan, image_path, review = run_campaign(
            test_article,
            cta="Jetzt Beratungsstelle finden",
            test_mode=True,  # Low-Quality für Tests
        )

        print("\n✅ KAMPAGNE ERSTELLT!\n")
        print(f"Headline: {plan.headline}")
        print(f"Infopunkte: {', '.join(plan.supporting_points)}")
        print(f"Bild: {image_path}")
        print(f"QA-Status: {'FREIGEGEBEN ✅' if review.approved else 'ABGELEHNT ❌'}")

        if not review.approved:
            print(f"Probleme: {', '.join(review.problems)}")

    except Exception as e:
        log.error("Workflow fehlgeschlagen: %s", e, exc_info=True)
        sys.exit(1)
