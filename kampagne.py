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
import random
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
    highlight_words: list[str] = Field(
        default_factory=list, max_length=3,
        description="1-3 einzelne Wörter ODER kurze Zahlen-Ausdrücke WÖRTLICH aus headline/"
                     "supporting_points (z.B. eine Zahl, ein Betrag, ein Schlüsselbegriff wie "
                     "'kostenlos'), die im Bild grün statt in der Standardfarbe hervorgehoben "
                     "werden sollen. Sparsam einsetzen (Wirkung durch Kontrast, nicht durch Menge)."
    )

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


class VisualOnlyPlan(BaseModel):
    """Reiner Bild-/Layout-Plan von GPT-5.6 Terra (Art Director), OHNE eigenen Text - fuer
    Faelle mit vorgegebenem, fest formuliertem Text (#Fristen-Countdown: rechtlich relevante
    Betraege/Daten sollen NICHT von der KI umformuliert werden koennen)."""
    visual_concept: str = Field(description="Beschreibung des visuellen Konzepts")
    highlight_words: list[str] = Field(
        default_factory=list, max_length=3,
        description="1-3 einzelne Wörter ODER kurze Zahlen-Ausdrücke WÖRTLICH aus dem "
                     "vorgegebenen Text (z.B. das Datum, ein Betrag), die im Bild grün statt in "
                     "der Standardfarbe hervorgehoben werden sollen. NUR aus dem gegebenen Text "
                     "auswählen, NICHTS umformulieren. Sparsam einsetzen."
    )
    layout_template: Literal[
        "text_left_hero_right", "text_right_hero_left", "text_top_hero_bottom",
        "hero_top_text_bottom", "centered_headline_bottom_panel", "editorial_split"
    ] = Field(description="Gewählte Layout-Vorlage")
    motiv_prompt: str = Field(description="Englischer Prompt NUR für das Motiv (OHNE Text-Rendering!)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LAYOUT-VORLAGEN (für Pillow Text-Rendering)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LAYOUT_TEMPLATES = {
    # WICHTIG (#Kollisionsschutz): Die Logo-Kreise (bildgen.add_logo_circles, pos="diagonal2")
    # sitzen IMMER unten-links (Logo) und oben-rechts (Slogan/Portrait) inkl. weichem
    # Schlagschatten - grosszuegig bis x<0.30 UND (y<0.30 ODER y>0.68). Bei rein linksbuendigen
    # Textboxen (x-Bereich bleibt < 0.55) ist oben-links dagegen FREI nutzbar - nur Boxen, die
    # in die obere RECHTE Ecke hineinreichen (x>0.68 UND y<0.30) oder in die untere LINKE Ecke
    # (x<0.30 UND y>0.68), muessen ausweichen. Der CTA-Button ignoriert diese Box fuer seine
    # EIGENE Groesse/Position (siehe _render_cta_button - feste Breite, zentriert in der
    # sicheren Zone, weicht der unten-links-Zone automatisch aus).
    "text_left_hero_right": {
        # Oben-links ist bei diagonal2 (Logo unten-links, Slogan/Portrait oben-rechts) FREI -
        # Ueberschrift darf wieder nach oben, nur unten-links (Bullets/CTA) bleibt reserviert.
        "headline_box": TextBox(x=0.07, y=0.08, width=0.48, height=0.22, align="left", vertical_align="top"),
        "supporting_box": TextBox(x=0.07, y=0.34, width=0.42, height=0.30, align="left", vertical_align="top"),
        "cta_box": TextBox(x=0.07, y=0.76, width=0.46, height=0.11, align="center", vertical_align="center"),
        "motiv_area": "right 50%",
        "motiv_instruction": "Keep the left 45% visually calm. Place the hero subject on the right side."
    },

    "text_right_hero_left": {
        "headline_box": TextBox(x=0.55, y=0.33, width=0.38, height=0.20, align="right", vertical_align="top"),
        "supporting_box": TextBox(x=0.55, y=0.52, width=0.38, height=0.24, align="right", vertical_align="top"),
        "cta_box": TextBox(x=0.55, y=0.76, width=0.38, height=0.11, align="center", vertical_align="center"),
        "motiv_area": "left 50%",
        "motiv_instruction": "Keep the right 40% visually calm. Place the hero subject on the left side."
    },

    "text_top_hero_bottom": {
        # Wie text_left_hero_right (oben links, fett), aber BREITER weil mehr Platz (Motiv unten)
        # → Headline kann 1-2 Zeilen statt 3, Bullets haben mehr Raum
        "headline_box": TextBox(x=0.07, y=0.08, width=0.65, height=0.22, align="left", vertical_align="top"),
        "supporting_box": TextBox(x=0.07, y=0.34, width=0.60, height=0.30, align="left", vertical_align="top"),
        "cta_box": TextBox(x=0.07, y=0.76, width=0.50, height=0.11, align="center", vertical_align="center"),
        "motiv_area": "bottom 45%",
        "motiv_instruction": "Keep the top 55% and left 65% visually calm. Place the hero subject in the lower right area."
    },

    "hero_top_text_bottom": {
        # Volle Breite wuerde in die unten-links-Zone hineinragen (Textblock liegt hier tief im
        # Bild) - daher x eingerueckt (0.30 statt 0.07), schmaler als die anderen Vorlagen.
        # WICHTIG: Text unten war zu klein → Boxen größer gemacht + höher gerückt (2026-07-30)
        "headline_box": TextBox(x=0.30, y=0.54, width=0.63, height=0.18, align="center", vertical_align="top"),
        "supporting_box": TextBox(x=0.30, y=0.72, width=0.63, height=0.16, align="center", vertical_align="top"),
        "cta_box": TextBox(x=0.25, y=0.89, width=0.50, height=0.09, align="center", vertical_align="center"),
        "motiv_area": "top 55%",
        "motiv_instruction": "Keep the bottom 45% visually calm and high-contrast. Place the hero subject in the upper half."
    },

    "centered_headline_bottom_panel": {
        "headline_box": TextBox(x=0.10, y=0.35, width=0.80, height=0.22, align="center", vertical_align="center"),
        # Panel liegt tief (y=0.69) -> eingerueckt + größer gemacht für bessere Lesbarkeit (2026-07-30)
        "supporting_box": TextBox(x=0.30, y=0.69, width=0.63, height=0.16, align="center", vertical_align="top"),
        "cta_box": TextBox(x=0.25, y=0.87, width=0.50, height=0.10, align="center", vertical_align="center"),
        "motiv_area": "background",
        "motiv_instruction": "Create a full-frame background. Leave vertical center and bottom 30% calm and high-contrast."
    },

    "editorial_split": {
        # Oben-links ist bei diagonal2 frei - siehe text_left_hero_right.
        "headline_box": TextBox(x=0.05, y=0.08, width=0.42, height=0.20, align="left", vertical_align="top"),
        "supporting_box": TextBox(x=0.05, y=0.32, width=0.42, height=0.32, align="left", vertical_align="top"),
        "cta_box": TextBox(x=0.05, y=0.74, width=0.42, height=0.10, align="left", vertical_align="center"),
        "motiv_area": "right 48%",
        "motiv_instruction": "Create an editorial split layout. Hero subject fills the right half completely."
    }
}


def _last_layout_path() -> str:
    return os.path.join(DATA_DIR, "last_layout_template.txt")


def pick_layout_template() -> str:
    """Waehlt ein Layout-Template zufaellig (Abwechslung je Beitrag) - vermeidet eine
    Wiederholung des zuletzt genutzten (analog zu bildgen.pick_circle_pos()).

    #Layout-Fix: Die Layout-Wahl wurde bisher GPT ueberlassen (freies Feld im CampaignPlan/
    VisualOnlyPlan) - in der Praxis wurde dabei fast immer dieselbe erste Option
    ('text_left_hero_right') gewaehlt, ein bekannter LLM-Bias bei einer Liste gleichwertiger
    Optionen ohne starkes inhaltliches Unterscheidungsmerkmal. Jetzt wird das Layout CODE-SEITIG
    zufaellig vorgegeben (echte Abwechslung garantiert) und GPT bekommt es als bereits
    feststehende Vorgabe mitgeteilt, entwickelt Motiv-Prompt/Text dann passend dazu."""
    last = ""
    try:
        last = open(_last_layout_path(), encoding="utf-8").read().strip()
    except Exception:
        pass
    opts = [name for name in LAYOUT_TEMPLATES if name != last] or list(LAYOUT_TEMPLATES)
    chosen = random.choice(opts)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        open(_last_layout_path(), "w", encoding="utf-8").write(chosen)
    except Exception:
        pass
    return chosen


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

HERVORHEBUNG (highlight_words)

Wähle 1-3 einzelne Wörter oder kurze Zahlen-Ausdrücke WÖRTLICH aus der Headline oder den
Infopunkten (z.B. eine Zahl, ein Betrag, ein starkes Schlüsselwort wie "kostenlos" oder
"sofort") - diese werden im Bild grün statt in der Standardfarbe hervorgehoben. Sparsam
einsetzen: die Wirkung kommt vom Kontrast, nicht von der Menge. Auch leer lassen ist erlaubt,
wenn kein Wort eine echte Hervorhebung verdient.

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
- einen ruhigen UND kontrastreichen Textbereich (der Text liegt OHNE Farbfläche direkt
  über dem Motiv - Kontrast muss vom Motiv selbst kommen, nicht von einer Hintergrundfläche)
- eine eindeutige Hierarchie aus Headline, Infopunkten und CTA
- hohe Lesbarkeit auf Smartphones
- großzügige Abstände
- eine hochwertige, moderne Werbeästhetik

HILO-Farben:
- Navy: #1f428d
- Grün: #60a33c
- Lavendelblau: #b8c8e8
- Weiß: #ffffff

FARBGEBUNG (WICHTIG - STRIKT EINHALTEN!):

Das Foto selbst soll eine NATÜRLICHE, NEUTRALE Farbgebung haben:
- Natürliches Tageslicht (KEIN warmer Goldton, KEIN Sepia, KEIN warmer Filter!)
- Realistische, kühle bis neutrale Materialien (Holz in natürlichem Braun, Papier in Weiß/Grau)
- Echte Hauttöne (keine warmen/goldenen Übertöne)
- Wie ein echtes redaktionelles Magazin-Foto mit professioneller Beleuchtung

HILO-Farben (Navy #1f428d UND Grün #60a33c) müssen als OBJEKTE im Bild sichtbar sein:
- MINDESTENS EIN Objekt in Navy (z.B. Ordner, Mappe, Notizbuch, Stift, Möbelstück)
- MINDESTENS EIN Objekt in Grün (z.B. Pflanze, Notizbuch, Ordner, Dekoobjekt)
- Diese Objekte MÜSSEN klar erkennbar sein (nicht nur winzige Details!)
- Platziere sie bewusst im Bild (nicht nur am Rand)

VERMEIDEN:
- Warme Goldtöne / Sepia-Filter
- Dominante Braun/Beige/Creme-Stimmung im ganzen Bild
- Navy/Grün als Hintergrundfarbe oder Lichtstimmung (nur als konkrete Objekte!)
- Übertrieben warme/sonnige Lichtstimmung

Ziel: Professionelles, kühles/neutrales Foto MIT klar sichtbaren Navy- und Grün-Objekten.

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

Das Layout ist bereits vorgegeben (siehe Nutzernachricht, Feld "LAYOUT") - übernimm den Wert
unverändert in layout_template, wähle es NICHT selbst. Die Optionen zur Orientierung:

- text_left_hero_right: Text links (45%), Motiv rechts (50%)
- text_right_hero_left: Text rechts (40%), Motiv links (50%)
- text_top_hero_bottom: Text oben (55%), Motiv unten (45%)
- hero_top_text_bottom: Motiv oben (55%), Text unten (40%)
- centered_headline_bottom_panel: Zentrale Headline, unteres Text-Panel
- editorial_split: Editorial Split-Layout (Text links, Motiv rechts halbseitig)

Entwickle Text und Motiv-Prompt so, dass sie zum vorgegebenen Layout passen.

(Die Text-Positionen werden automatisch aus der Vorlage übernommen.)

MOTIV-PROMPT (NUR FÜR DAS BILD, OHNE TEXT!)

Formuliere einen englischen Produktionsprompt für GPT Image 2.

WICHTIG - DIES IST ENTSCHEIDEND:
- Der Prompt beschreibt NUR das visuelle Motiv
- KEIN Text IN DEN TEXT-OVERLAY-BEREICHEN (wo Pillow Headline/Bullets/CTA einfügt)!
- ABER: Dokumente/Formulare im Bild MÜSSEN beschriftet sein (z.B. "Steuererklärung",
  "Antrag", Formularfelder, handschriftliche Notizen) - niemals leere weiße Blätter!
- Das Motiv muss eine ruhige, kontrastreiche Fläche für späteren Text-Overlay lassen (der
  Text bekommt KEINE Hintergrundfläche - Kontrast muss vom Motiv selbst kommen)
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
Natural, neutral photography color grading (daylight, warm/neutral tones, realistic materials
and skin tones) - like authentic editorial photography, NOT color-washed or color-graded
toward navy or green. Use HILO brand colors ONLY as small, deliberate accent objects/details:
- Navy #1f428d (e.g. one folder, one small object - never the background or overall lighting)
- Green #60a33c (e.g. a plant, a small accent detail)
- Lavender #b8c8e8 (subtle highlight on one object)
- White #ffffff (clean surfaces)
The photo as a whole must NOT look navy-toned or green-toned - only 1-2 small accent
details should carry these colors.

CORNER SAFE ZONES:
Keep all four corners clear (12% width × 12% height per corner) for logo overlays.

CRITICAL - TEXT-OVERLAY AREAS MUST BE FREE:
DO NOT RENDER ANY TEXT IN THE TEXT-OVERLAY AREAS (where Pillow will add the headline/bullets/CTA).
HOWEVER: If documents, forms, or papers appear in the image, they MUST show relevant text/labels
(e.g. "Steuererklärung", "Antrag", form fields, handwritten notes) - never blank white sheets!

CRITICAL - KEEP TEXT AREAS VISUALLY CALM & EMPTY:
The text-overlay areas MUST be completely free of distracting objects, complex patterns, or busy details.
Follow the layout instruction STRICTLY (e.g. "Keep the top 55% visually calm" means NO objects reaching
into that area - not even hands, papers, or decorative elements). The text area must be SIMPLE, CLEAN,
and HIGH-CONTRAST for perfect readability.

CRITICAL - REALISTIC ANATOMY & PROPORTIONS:
If people or body parts (hands, arms) appear, they MUST be anatomically correct and realistic.
NO elongated limbs, NO strange proportions, NO distorted fingers. Keep it natural and believable.

────────────────────────────────────────────────────────────────

Passe dieses Muster an:
- Verwende die Layout-Anweisung aus der gewählten Vorlage
- Beschreibe das Hero-Element präzise
- Nutze HILO-Farben als Akzente
- Stelle sicher dass der Textbereich RUHIG und FREI bleibt
- Wiederhole am Ende: "DO NOT RENDER ANY TEXT"

Der finale motiv_prompt muss vollständig in Englisch sein.

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


ART_DIRECTOR_ONLY_PROMPT = """Du bist Senior Art Director für HILO, einen deutschen
Lohnsteuerhilfeverein.

Der Text (Headline, Infopunkte, CTA) steht bereits FEST und darf NICHT verändert oder neu
formuliert werden - er enthält rechtlich relevante Fristen/Beträge. Deine Aufgabe: ein
passendes VISUELLES Konzept für ein Werbebild entwickeln, das zum gegebenen Text passt, sowie
1-3 Wörter/Zahlen-Ausdrücke WÖRTLICH aus diesem Text für eine grüne Hervorhebung auswählen
(z.B. das Datum oder einen Betrag) - dabei NICHTS umformulieren, nur auswählen.

KREATIVKONZEPT (WICHTIG: MEHR PEP!)

Entwickle intern drei DEUTLICH UNTERSCHIEDLICHE Bildideen passend zum Text.
Wähle die stärkste nach: sofortiger Verständlichkeit, Originalität, VISUELLE IMPACT, Eignung für HILO.

SEI KREATIV & MUTIG:
- Interessante Perspektiven (nicht immer nur Draufsicht!)
- Unerwartete Kompositionen (asymmetrisch, dynamisch, spannend)
- Kontrastreiche Farbakzente (Navy + Grün bewusst einsetzen!)
- Lebendige Szenen (nicht langweilig statisch)
- Moderne, frische Bildsprache (nicht generisch!)

Bevorzuge je nach Thema: Editorial Photography, Concept Photography, Still Life, Flat Lay,
authentische Lifestyle-Fotografie, Editorial Illustration, moderne 3D-Illustration.

VERMEIDE: Langweilige Standardmotive, immer gleiche Draufsichten, generische Stockfotos.

GESTALTUNG

Die Anzeige muss als vollständige quadratische Werbegrafik funktionieren:
- ein dominantes Hero-Element, klare Blickführung
- ein ruhiger, gut lesbarer Textbereich (der Text liegt OHNE Farbfläche direkt über dem
  Motiv - der Bereich muss visuell ruhig UND kontrastreich genug für Text sein)
- hohe Lesbarkeit auf Smartphones, hochwertige moderne Werbeästhetik

FARBGEBUNG (WICHTIG - STRIKT EINHALTEN!):

Das Foto selbst soll eine NATÜRLICHE, NEUTRALE Farbgebung haben:
- Natürliches Tageslicht (KEIN warmer Goldton, KEIN Sepia, KEIN warmer Filter!)
- Realistische, kühle bis neutrale Materialien (Holz in natürlichem Braun, Papier in Weiß/Grau)
- Echte Hauttöne (keine warmen/goldenen Übertöne)
- Wie ein echtes redaktionelles Magazin-Foto mit professioneller Beleuchtung

HILO-Farben (Navy #1f428d UND Grün #60a33c) müssen als OBJEKTE im Bild sichtbar sein:
- MINDESTENS EIN Objekt in Navy (z.B. Ordner, Mappe, Notizbuch, Stift, Möbelstück)
- MINDESTENS EIN Objekt in Grün (z.B. Pflanze, Notizbuch, Ordner, Dekoobjekt)
- Diese Objekte MÜSSEN klar erkennbar sein (nicht nur winzige Details!)
- Platziere sie bewusst im Bild (nicht nur am Rand)

VERMEIDEN:
- Warme Goldtöne / Sepia-Filter
- Dominante Braun/Beige/Creme-Stimmung im ganzen Bild
- Navy/Grün als Hintergrundfarbe oder Lichtstimmung (nur als konkrete Objekte!)
- Übertrieben warme/sonnige Lichtstimmung

Ziel: Professionelles, kühles/neutrales Foto MIT klar sichtbaren Navy- und Grün-Objekten.

VERMEIDEN: generische Businesspersonen, gestellte Stockfoto-Posen, übertriebenes Lächeln,
Geldregen, übergroße Eurozeichen, das Wort "HILO" in der Typografie, zusätzliche Logos,
QR-Codes, Wasserzeichen.

LAYOUT-PLANUNG

Das Layout ist bereits vorgegeben (siehe Nutzernachricht, Feld "LAYOUT") - übernimm den Wert
unverändert in layout_template, wähle es NICHT selbst.

MOTIV-PROMPT (NUR FÜR DAS BILD, OHNE TEXT!)

Formuliere einen englischen Produktionsprompt für GPT Image 2.

WICHTIG - DIES IST ENTSCHEIDEND:

KEIN Text IN DEN TEXT-OVERLAY-BEREICHEN (wo Pillow Headline/Bullets/CTA einfügt)!
ABER: Dokumente/Formulare im Bild MÜSSEN beschriftet sein (z.B. "Steuererklärung",
"Antrag", Formularfelder, handschriftliche Notizen) - niemals leere weiße Blätter!

STRIKTE FREIFLÄCHE FÜR TEXT:
Die Text-Overlay-Bereiche MÜSSEN komplett FREI sein von störenden Objekten, Mustern oder Details.
Befolge die Layout-Anweisung STRIKT (z.B. "Keep the top 55% calm" = KEINE Objekte in diesem Bereich -
auch nicht Hände, Papiere oder Deko). Der Textbereich muss EINFACH, SAUBER und KONTRASTREICH sein.

REALISTISCHE ANATOMIE:
Wenn Personen oder Körperteile (Hände, Arme) erscheinen, MÜSSEN sie anatomisch korrekt sein.
KEINE verlängerten Gliedmaßen, KEINE seltsamen Proportionen, KEINE verzerrten Finger.

Verwende die Layout-spezifische Anweisung.
Ende mit: "DO NOT RENDER ANY TEXT IN THE TEXT-OVERLAY AREAS. However, documents/forms must show
relevant labels. KEEP TEXT AREAS COMPLETELY FREE AND VISUALLY CALM. Realistic anatomy only."

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


def create_visual_plan(
    headline: str,
    supporting_points: list[str],
    cta: str,
    context: str = "",
) -> VisualOnlyPlan:
    """Art-Director-Stufe OHNE Texterstellung: GPT-5.6 Terra bekommt den fertigen, fest
    vorgegebenen Text und entwickelt dazu NUR ein visuelles Konzept + Motiv-Prompt + Layout.
    Fuer Faelle wie den Fristen-Countdown, wo der Text bewusst nicht von der KI veraendert
    werden soll (rechtlich relevante Daten/Betraege), aber trotzdem ein passendes, individuelles
    KI-Bild statt eines statischen Icons gewuenscht ist."""
    client = _get_client()
    log.info("Art-Director-Stufe (nur Bild, Text fest vorgegeben)...")

    # Layout-Vorlage CODE-SEITIG vorgeben (#Layout-Fix, wie bei create_campaign_plan).
    layout_template = pick_layout_template()
    layout_hinweis = LAYOUT_TEMPLATES[layout_template]["motiv_instruction"]

    user_content = (
        f"VORGEGEBENER TEXT (nicht veraendern):\n"
        f"Headline: {headline}\n"
        f"Infopunkte: {', '.join(supporting_points)}\n"
        f"CTA: {cta}\n\n"
        f"KONTEXT: {context}\n\n"
        f"LAYOUT (bereits festgelegt, NICHT selbst wählen - trage diesen Wert unverändert in "
        f"layout_template ein und gestalte den Motiv-Prompt passend dazu): {layout_template}\n"
        f"Layout-Hinweis für das Motiv: {layout_hinweis}"
    )

    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",
        messages=[
            {"role": "system", "content": ART_DIRECTOR_ONLY_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=VisualOnlyPlan,
    )
    plan = response.choices[0].message.parsed
    if plan is None:
        raise RuntimeError("Es wurde kein Bildkonzept erzeugt.")
    plan.layout_template = layout_template  # code-seitig erzwingen, s.o.
    log.info("Art-Director-Stufe: Layout %s gewählt.", plan.layout_template)
    return plan


def generate_image_for_fixed_text(
    headline: str,
    supporting_points: list[str],
    cta: str,
    context: str = "",
    output_path: Optional[str] = None,
    test_mode: bool = False,
) -> tuple[Path, QualityReview, Path, str, list[str]]:
    """Kompletter Bild-Workflow bei FEST VORGEGEBENEM Text (#Fristen-Countdown): Art-Director
    plant NUR das visuelle Konzept (create_visual_plan), GPT Image 2 erzeugt das Motiv, Pillow
    rendert den vorgegebenen Text drueber, QA prueft (kein Auto-Retry, #Kostenschutz - siehe
    run_campaign). Der Text selbst bleibt in JEDEM Fall unveraendert.

    Returns:
        (finale_image_path, QualityReview, motiv_image_path, layout_template, highlight_words)
        motiv_image_path + layout_template werden fuer die Personalisierung je Beratungsstelle
        gebraucht (personalisierung.render_fuer_stelle), damit dort NICHT nochmal GPT Image 2
        aufgerufen werden muss. highlight_words ebenso, damit die gruene Hervorhebung bei der
        kostenlosen Wiederverwendung (Personalisierung/'Text im Bild neu') erhalten bleibt."""
    vplan = create_visual_plan(headline, supporting_points, cta, context=context)
    template = LAYOUT_TEMPLATES[vplan.layout_template]

    kampagne_dir = os.path.join(DATA_DIR, "kampagne")
    os.makedirs(kampagne_dir, exist_ok=True)
    quality = "low" if test_mode else "medium"

    import time, uuid
    lauf_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    motiv_path = os.path.join(kampagne_dir, f"frist_motiv_{lauf_id}.png")
    motiv_image_path = generate_advertisement(vplan.motiv_prompt, output_path=motiv_path,
                                               size="1024x1024", quality=quality)

    final_path = os.path.join(kampagne_dir, f"frist_final_{lauf_id}.png") \
        if not output_path else output_path
    image_path = render_text_on_image(
        motiv_image_path, headline, supporting_points, cta,
        template["headline_box"], template["supporting_box"], template["cta_box"],
        Path(final_path), background_overlay=True, highlight_words=vplan.highlight_words,
    )

    from types import SimpleNamespace
    mini_plan = SimpleNamespace(headline=headline, supporting_points=supporting_points,
                                 cta=cta, core_message="")
    review = quality_check(image_path, mini_plan, context or headline)
    if not review.approved:
        log.warning("Fristen-Bild: QA-Probleme (kein Auto-Retry): %s", ", ".join(review.problems))
    return image_path, review, motiv_image_path, vplan.layout_template, vplan.highlight_words





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

    # Layout-Vorlage CODE-SEITIG vorgeben (#Layout-Fix: garantierte Abwechslung statt GPT-Bias
    # auf die erste Option) - GPT bekommt es als feststehende Vorgabe mitgeteilt.
    layout_template = pick_layout_template()
    layout_hinweis = LAYOUT_TEMPLATES[layout_template]["motiv_instruction"]

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
                    f"KANAL: {channel}\n\n"
                    f"LAYOUT (bereits festgelegt, NICHT selbst wählen - trage diesen Wert "
                    f"unverändert in layout_template ein und gestalte Text/Motiv-Prompt passend "
                    f"dazu): {layout_template}\n"
                    f"Layout-Hinweis für das Motiv: {layout_hinweis}"
                ),
            },
        ],
        response_format=CampaignPlan,
    )

    plan = response.choices[0].message.parsed

    if plan is None:
        raise RuntimeError("Es wurde kein Kampagnenplan erzeugt.")

    # Layout-Template IMMER auf den code-seitig vorgegebenen Wert erzwingen (#Layout-Fix) -
    # unabhaengig davon, was GPT im Feld zurueckgegeben hat (Instruktion oben, aber zur
    # Sicherheit nicht auf GPTs Befolgung verlassen - garantiert echte Abwechslung).
    plan.layout_template = layout_template

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

WICHTIG: Der Text (Headline, Bullets, CTA) wurde bereits mit Pillow eingefügt und ist
garantiert korrekt geschrieben - prüfe NICHT die Rechtschreibung. Der Text liegt OHNE
Hintergrundfläche direkt über dem Motiv (bewusstes Design), daher ist Kontrast/Lesbarkeit
der wichtigste Check - hier hängt alles vom Motiv darunter ab.

1. LESBARKEIT (wichtigstes Kriterium): Auf Smartphone (6 Zoll) scharf lesbar?
   - Ausreichender Kontrast zum darunterliegenden Motiv an JEDER Textstelle?
   - Keine visuell unruhigen/hellen Motivbereiche direkt hinter dem Text?
   - approved=False bei JEDER Stelle mit schwachem Kontrast.

2. ÜBRIGE PUNKTE (kompakt prüfen): Motiv passt zum Thema, Layout wirkt professionell,
   Motiv-Qualität hochwertig. approved=False bei jedem klaren Mangel.

Gib ausschließlich die verlangte strukturierte Ausgabe zurück, problems knapp (Stichpunkte)."""


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

    # Bild verkleinert als Base64 laden (#Kostenschutz): 512x512 reicht fuer Layout-/Kontrast-
    # Check locker aus und spart Bild-Tokens beim Vision-Call gegenueber dem vollen 1024x1024-PNG.
    import io
    from PIL import Image
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.thumbnail((512, 512), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Erwartete Texte zusammenstellen
    expected_texts = f"""ERWARTETE TEXTE:

Headline: {plan.headline}

Infopunkte:
{chr(10).join("• " + p for p in plan.supporting_points)}

CTA: {plan.cta}

ORIGINALTEXT:
{article[:500]}"""

    response = client.beta.chat.completions.parse(
        model="gpt-5-nano",  # QA ist reine Klassifikation (Ja/Nein + kurze Problemliste) - dafuer
        # reicht das guenstigste Vision-Modell (~50x billiger als Terra). Kein Auto-Retry mehr
        # (siehe run_campaign/regenerate_image_with_qa), daher geringes Risiko bei ungenauerer QA -
        # das Bild geht ohnehin zur manuellen Pruefung. Bei Bedarf hochstufen auf 'gpt-5.6-luna'.
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
) -> tuple[CampaignPlan, Path, QualityReview, Path]:
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
        (CampaignPlan, finale_image_path, QualityReview, motiv_image_path)
        motiv_image_path ist das ROHE KI-Motiv OHNE Text - wird fuer die Personalisierung je
        Beratungsstelle gebraucht (personalisierung.render_fuer_stelle rendert damit den
        personalisierten CTA-Text neu drauf, OHNE nochmal GPT Image 2 aufzurufen).

    Raises:
        RuntimeError: Wenn nach max_retries immer noch Fehler
    """
    log.info("━━━━ 3-STUFEN-WORKFLOW GESTARTET ━━━━")

    # Stufe 1: Kampagnenplanung (nur einmal!)
    plan = create_campaign_plan(article, cta=cta)

    # Stufe 2 + 3: Grafik + QA (mit Retry)
    size = "1024x1024"  # Immer 1024x1024 - optimal für 1080x1080 Feed-Posts!
    # 'medium' statt 'high' (#Kostenschutz): ~75% guenstiger ($0.053 vs $0.211/Bild), Qualitaets-
    # unterschied laut unabhaengigem Benchmark minimal (4.108 vs 4.155 von 5). 'low' faellt
    # dagegen spuerbar ab (3.946) - deshalb bewusst NICHT low fuer Produktionsbilder.
    quality = "low" if test_mode else "medium"
    kampagne_dir = os.path.join(DATA_DIR, "kampagne")
    os.makedirs(kampagne_dir, exist_ok=True)
    # Eindeutiger Lauf-Praefix (#Kollisionsschutz): 'motiv_1.png'/'final_1.png' waeren bei jedem
    # Aufruf gleich benannt gewesen und haetten sich gegenseitig ueberschrieben - insbesondere
    # riskant jetzt, wo das rohe Motiv fuer spaetere Personalisierung dauerhaft erhalten bleiben muss.
    import time, uuid
    lauf_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"

    for attempt in range(1, max_retries + 1):
        log.info("━━━━ VERSUCH %d/%d ━━━━", attempt, max_retries)

        try:
            # Stufe 2a: Motiv generieren (OHNE Text!)
            motiv_path = os.path.join(kampagne_dir, f"motiv_{lauf_id}_{attempt}.png")

            motiv_image_path = generate_advertisement(
                plan.motiv_prompt,
                output_path=motiv_path,
                size=size,
                quality=quality,
            )

            # Stufe 2b: Text mit Pillow hinzufügen
            final_path = os.path.join(
                kampagne_dir, f"final_{lauf_id}_{attempt}.png"
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
                highlight_words=plan.highlight_words,
            )
            log.info("Stufe 2b: Text gerendert und gespeichert unter %s", image_path)

            # Stufe 3: QA (mit finalem Bild inkl. Text!)
            review = quality_check(image_path, plan, article)

            if review.approved:
                log.info("━━━━ WORKFLOW ERFOLGREICH NACH %d VERSUCH(EN) ━━━━", attempt)
                return plan, image_path, review, motiv_image_path

            if attempt < max_retries:
                log.info("Versuch %d: Bild abgelehnt, neuer Versuch...", attempt)
            else:
                log.warning("Alle Versuche fehlgeschlagen! Probleme: %s", ", ".join(review.problems))
                # Bild trotzdem zurückgeben für manuelle Prüfung
                return plan, image_path, review, motiv_image_path

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
    # 'medium' statt 'high' (#Kostenschutz, wie in run_campaign): ~75% guenstiger, minimaler
    # Qualitaetsunterschied laut Benchmark.
    quality = "low" if test_mode else "medium"

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
        plan, image_path, review, motiv_path = run_campaign(
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
