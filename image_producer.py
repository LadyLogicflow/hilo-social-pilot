#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image Producer - Generiert Premium-Bild MIT deutscher Überschrift für ShareNext-Pipeline.

Übersetzt Art Direction Board in gpt-image-2 Prompt und generiert das Bild.

WICHTIG:
- Text NUR auf DEUTSCH (NIEMALS Englisch!)
- Überschrift natürlich ins Bild integriert
- EURO (€) verwenden, NIEMALS Dollar ($)
- Zielgruppe: konkret aus Message Brief (nicht pauschal "Steuerzahler")

Teil von Issue #5: ShareNext MVP
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field

from message_brief import MessageBrief
from creative_director import CreativeRoute
from art_director import ArtDirectionBoard
from secrets_store import get_secret

log = logging.getLogger("hilo.image_producer")


def _get_client() -> OpenAI:
    """Erstellt OpenAI-Client mit API-Key aus secrets.json oder Umgebung."""
    api_key = get_secret("openai_api_key")
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "Kein OpenAI API-Key verfügbar! "
            "Bitte 'openai_api_key' in data/secrets.json hinterlegen "
            "oder OPENAI_API_KEY als Umgebungsvariable setzen."
        )

    return OpenAI(api_key=api_key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STRUCTURED OUTPUT MODEL (Pydantic)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class VisibleText(BaseModel):
    """Text-Modus und exakter Text."""
    mode: str = Field(description="'no_text' oder 'exact_headline'")
    exact_text: str = Field(default="", description="Exakter Text oder leer")


class CompositionCheck(BaseModel):
    """Kompositionsprüfung."""
    primary_focus: str = Field(description="Position des Hauptmotivs")
    text_zone: str = Field(description="Position der ruhigen Textfläche")
    bottom_left_safe: bool = Field(description="Untere linke Schutzzone frei?")
    top_right_safe: bool = Field(description="Obere rechte Schutzzone frei?")


class Preflight(BaseModel):
    """Preflight-Check vor Bildgenerierung."""
    status: str = Field(description="'PASS' oder 'REJECT'")
    issues: list[str] = Field(default_factory=list, description="Liste von Problemen bei REJECT")


class ImageProductionBrief(BaseModel):
    """Production Brief - ShareNext JSON-Output nach Catrins Spezifikation.

    Strukturiertes Output mit Preflight-Check und Kompositionsvalidierung.
    """

    image_prompt: str = Field(
        default="",
        max_length=4000,
        description="Der vollständige Produktionsprompt für gpt-image-2 (100-4000 Zeichen bei PASS, leer bei REJECT)"
    )

    style_keywords: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="3-8 Stil-Keywords (leer bei REJECT)"
    )

    negative_hints: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Liste zu vermeidender Merkmale für QA-Checkliste (leer bei REJECT)"
    )

    visible_text: VisibleText = Field(
        description="Text-Modus und exakter sichtbarer Text"
    )

    composition_check: CompositionCheck = Field(
        description="Kompositionsprüfung mit Schutzzonen"
    )

    preflight: Preflight = Field(
        description="Preflight-Status und ggf. Probleme"
    )

    alt_text: str = Field(
        default="",
        max_length=300,
        description="Barrierefreier Alt-Text für Instagram/Facebook, wird nach der Bildgenerierung "
                     "aus dem tatsächlichen Bild erzeugt (nicht Teil des GPT-Outputs, wird separat gesetzt)"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_production_brief(
    brief: MessageBrief,
    route: CreativeRoute,
    art_board: ArtDirectionBoard,
    headline: str = "",
    model: str = "gpt-5.6-terra"
) -> ImageProductionBrief:
    """Erstellt Production Brief nach ShareNext-Spezifikation (Catrin).

    Der Image Prompt Director übersetzt das Art Direction Board in einen präzisen
    Produktionsprompt für gpt-image-2 mit Preflight-Check.

    Args:
        brief: Message Brief (Kontext)
        route: Gewinnende kreative Route
        art_board: Art Direction Board
        headline: Freigegebene Überschrift vom Copywriter (Campaign Plan)
        model: OpenAI-Modell (default: gpt-5.6-terra)

    Returns:
        ImageProductionBrief: JSON-Output mit Preflight + Kompositionscheck

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt oder Preflight REJECT
        Exception: Bei OpenAI API-Fehlern
    """
    client = _get_client()

    # Schutzzonen-Definitionen (basierend auf HILO-Kreisen)
    SAFE_ZONE_WIDTH = "22%"
    SAFE_ZONE_HEIGHT = "28%"

    # System-Prompt: ShareNext Image Prompt Director (konsolidiert 2026-08-11 - vorher zwei fast
    # identische Text-Regel-Bloecke, jetzt hierarchisch nach Prioritaet A/B/C strukturiert, siehe
    # PROMPT_CHANGELOG.md)
    system_prompt = """Du bist ein Prompt Director für gpt-image-2 Bildgenerierung.
Deine Aufgabe: Übersetze ein Art Direction Board in einen präzisen Bildgenerierungs-Prompt.

Die Regeln unten sind nach Priorität sortiert. PRIORITÄT A ist nicht verhandelbar - ein Bild,
das dagegen verstößt, ist unbrauchbar, egal wie gut es sonst aussieht. PRIORITÄT B entscheidet,
ob das Bild im Feed auffällt. PRIORITÄT C sorgt für Markenwirkung, ohne die Kreativität
einzuschränken.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÄT A - UNVERHANDELBAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Setze das Creative Concept (Route + Art Direction Board) inhaltlich exakt um - keine eigene
  Interpretation, die vom Board abweicht.
- Ist eine Überschrift vorgegeben: MUSS sie EXAKT (wortgenau, keine Änderung/Übersetzung),
  GROß, LESBAR und PROMINENT im Bild erscheinen - das wichtigste Text-Element im Bild.
- Text natürlich integrieren (auf Schildern, Wänden, Tafeln, Anzeigen, Plakaten) - NICHT
  schwebend.
- Braucht die Überschrift eine eigene Fläche für Kontrast: bevorzugt Navy (#1f428d) oder Grün
  (#60a33c) mit weißer Schrift (oder umgekehrt). Eine neutrale Fläche ist nur erlaubt, wenn sie
  erkennbar besser zur Szene passt UND zusätzlich ein sichtbares HILO-Farbelement (Rand,
  Streifen, Akzent) in der Nähe liegt - nie eine Fläche komplett ohne Markenfarbbezug. Wo
  möglich lieber ganz ohne separate Fläche, direkt auf einer dunklen Bildfläche im Motiv mit
  Halo/Kontrast.
- NUR DEUTSCHE SPRACHE - absolut kein Englisch.
- EURO (€) - NIEMALS Dollar ($) oder USD.
- Zielgruppe strikt beachten - siehe konkrete Zielgruppe im User-Prompt, nicht pauschalisieren.
- Logo-Schutzzonen (unten links + oben rechts, Maße im User-Prompt) MÜSSEN frei von wichtigem
  Bildinhalt bleiben.
- Keine zusätzlichen Labels, Captions oder Wasserzeichen (außer HILO-Logo).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÄT B - VISUELLE WIRKUNG (Scroll-Stop)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- EIN dominantes Hero-Element trägt das Bild - alle anderen Objekte sind klar untergeordnet
  (kleiner, unscharf, im Hintergrund) oder fehlen ganz. Keine Ansammlung mehrerer
  gleichrangiger Requisiten.
- **Kein Produktshot-Reflex:** "ein dominantes Element" heißt NICHT "freigestellt vor
  einfarbiger Fläche". Setze das Art Direction Board's Hintergrund-Typ tatsächlich um - bei
  "Echte fotografische Umgebung" MUSS eine echte Szene mit Tiefe/Textur/Licht entstehen (z.B.
  ein Tisch mit Geschirr im unscharfen Hintergrund), nicht nur eine flache Farbfläche hinter
  dem Objekt. Ein durchgehend einfarbiger Studio-Hintergrund wirkt in Serie schnell wie
  austauschbares 3D-Rendering statt echter Fotografie.
- Übersetze das Scroll-Stop-Device der Route konkret und sichtbar - nicht nur andeuten.
- Kräftiger Hell-Dunkel-Kontrast am Focal Point + mindestens ein satter, klar erkennbarer
  Farbakzent. Vermeide flaue, blasse oder gleichförmig helle Bilder - "professionell und warm"
  heißt nicht zurückhaltend.
- THUMBNAIL-TEST: Die Leitidee muss auch bei einer kleinen Feed-Vorschau (ca. 180×180 Pixel)
  sofort verständlich und visuell dominant sein - ohne dass feine Details oder kleine
  Requisiten nötig sind, um sie zu verstehen.
- Platziere den Focal Point dominant, nicht beiläufig am Rand. Eine ungewöhnliche
  Kameraperspektive oder ein engerer Ausschnitt statt einer neutralen Totale wirkt stärker.
  Der erste Eindruck sollte eine kleine Frage im Kopf auslösen ("was ist da los?"), bevor der
  Text überhaupt gelesen wird.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÄT C - MARKE & STIL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Übersetze die Brand Signature aus dem Art Direction Board konkret (Navy als Fläche, Grün als
  Akzent, o.ä.) - HILO-Farben sollen über Licht/Flächen/Material/Kontrast entstehen, nicht
  durch sachlich unnötige grüne/blaue Requisiten (kein "grüner Ordner, blauer Stift").
- Professionell, warm, vertrauenswürdig - aber nicht steril oder langweilig.
- Authentisch statt Stock-Foto-Klischee. Eher vermeiden (kein starres Verbot, wenn eine Idee
  wirklich trägt hat sie Vorrang): generische Businessperson-Klischees (Person zeigt lächelnd
  auf Laptop-Bildschirm, Händeschütteln vor Glaswand, Daumen hoch im Anzug), sichtlich gestellte
  Stockfoto-Posen, übertriebenes/unnatürliches Lächeln, "cluttered", Wasserzeichen.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROMPT-STRUKTUR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **Stil & Medium** (z.B. "editorial photography", "still life", "digital art")
2. **Hauptmotiv** (Focal Point detailliert beschreiben)
3. **Komposition** (Bildaufbau, Platzierung)
4. **Licht** (Qualität, Richtung, Stimmung)
5. **Farben** (dominante Farben, Kontrast, Temperatur)
6. **Atmosphäre** (Gesamtstimmung)
7. **Technisch** (Kamera, Schärfe)
8. **Negativraum** (wo ist Platz für Text?)

Prompt-Tipps:
- Sei SEHR spezifisch (nicht "schönes Licht", sondern "soft directional light from left")
- Verwende Fotografie-Fachbegriffe (shallow depth of field, rule of thirds, etc.)
- Beschreibe was DU SIEHST, nicht was es BEDEUTET
- gpt-image-2 versteht komplexe Prompts - nutze das!
"""

    # Text-Modus: exact_headline wenn headline vorhanden, sonst no_text
    text_mode = "exact_headline" if headline else "no_text"

    # User-Prompt: Art Board Daten nach ShareNext-Spezifikation
    user_prompt = f"""VERBINDLICHE EINGABEN

Message Brief:
- Kernaussage: {brief.kernaussage}
- Zielgruppe: {brief.zielgruppe}
- Kanal: {brief.kanal}
- Seitenverhältnis: 1:1 (1080x1080)
- Kommunikationsziel: {brief.funnel_stufe}
- gewünschte Reaktion: {brief.reaktion}

Freigegebene Creative Direction:
- Creative Territory: {route.typ}
- Kreative Route: {route.typ}
- Leitidee: {route.titel}
- Bildbeschreibung: {route.beschreibung}
- Aufmerksamkeitsanker: {route.emotionale_richtung}
- Scroll-Stop-Device: {route.scroll_stop_device}

Art Direction Board:
- Hauptmotiv: {art_board.focal_point}
- Umgebung: {art_board.bildaufbau}
- Hintergrund-Typ: {art_board.hintergrund_typ}
- Komposition: {art_board.komposition_prinzip}
- Kameraperspektive: {art_board.kamera_perspektive}
- Licht: {art_board.licht_qualitaet}, {art_board.licht_richtung}, {art_board.licht_stimmung}
- Farbführung: {', '.join(art_board.dominante_farben)}, {art_board.farbtemperatur}, {art_board.farbkontrast}
- Materialität: (aus Beschreibung ableitbar)
- Atmosphäre: {art_board.atmosphaere}
- Brand Signature: {art_board.brand_signature}
- Schärfe und Optik: {art_board.schaerfe_tiefe}
- Textzone: {art_board.negativraum_text}

Layoutvorgaben:
- Überschrift: {headline if headline else "(keine - wird später gesetzt)"}
- Textmodus: {text_mode}
- Logo-Schutzzone unten links: {SAFE_ZONE_WIDTH} Bildbreite × {SAFE_ZONE_HEIGHT} Bildhöhe
- Logo-Schutzzone oben rechts: {SAFE_ZONE_WIDTH} Bildbreite × {SAFE_ZONE_HEIGHT} Bildhöhe

AUSGABEFORMAT

Gib ausschließlich ein gültiges JSON-Objekt zurück (wie im System-Prompt spezifiziert).

Stelle sicher dass:
- image_prompt vollständig und präzise ist
- style_keywords 3-8 Einträge haben
- negative_hints Liste von zu vermeidenden Merkmalen enthält (für QA-Checkliste!)
- visible_text.mode = "{text_mode}" und exact_text = "{headline if headline else ""}"
- composition_check alle Schutzzonen als true markiert
- preflight.status = "PASS" (oder "REJECT" mit konkreten issues)

WICHTIG:
- Bei text_mode = "exact_headline": Verwende EXAKT die Überschrift "{headline}"!
- Bei text_mode = "no_text": KEINE Schrift im Bild!
- Schutzzonen unten links + oben rechts MÜSSEN frei bleiben!
- NUR DEUTSCHE SPRACHE, NIEMALS Englisch!
- EURO (€) verwenden, NIEMALS Dollar ($)!
"""

    log.info(f"Prompt Director erstellt Bildgenerierungs-Prompt für: {route.titel}")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=ImageProductionBrief
        )

        production_brief = completion.choices[0].message.parsed

        if not production_brief:
            raise Exception("OpenAI API gab kein valides Production Brief zurück")

        # Preflight-Check: REJECT bedeutet Abbruch!
        if production_brief.preflight.status == "REJECT":
            issues_text = "\n".join(f"  - {issue}" for issue in production_brief.preflight.issues)
            raise ValueError(
                f"Preflight REJECTED! Probleme:\n{issues_text}\n\n"
                f"Das Bild kann nicht generiert werden. Bitte Art Direction Board korrigieren."
            )

        log.info(
            f"✓ Production Brief erstellt (Preflight: {production_brief.preflight.status}):\n"
            f"   Prompt-Länge: {len(production_brief.image_prompt)} Zeichen\n"
            f"   Keywords: {', '.join(production_brief.style_keywords[:3])}...\n"
            f"   Text-Modus: {production_brief.visible_text.mode}\n"
            f"   Schutzzonen: BL={production_brief.composition_check.bottom_left_safe}, "
            f"TR={production_brief.composition_check.top_right_safe}"
        )

        return production_brief

    except Exception as e:
        log.error(f"Fehler beim Erstellen des Production Briefs: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ALT-TEXT GENERATOR (Barrierefreiheit + Plattform-Signal)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_alt_text(
    image: Image.Image,
    headline: str = "",
    kernaussage: str = "",
    model: str = "gpt-4o-mini"
) -> str:
    """Erzeugt barrierefreien Alt-Text aus dem TATSÄCHLICH generierten Bild.

    Nutzt ein Vision-Modell auf dem fertigen Bild (nicht den Produktions-Prompt), da das
    generierte Bild vom Prompt abweichen kann (z.B. bei Textplatzierung). Alt-Text ist für
    Screenreader-Nutzer:innen UND ein Ranking-Signal bei Instagram/Facebook.

    Args:
        image: Das fertig generierte Bild
        headline: Überschrift, die bereits im Bild steht (wird NICHT wiederholt, da sie im
            Bild selbst schon lesbar/vorgelesen wird - Alt-Text beschreibt das Visuelle)
        kernaussage: Kernaussage aus dem Message Brief (Kontext für treffendere Beschreibung)
        model: Vision-fähiges OpenAI-Modell (default: gpt-4o-mini)

    Returns:
        str: Alt-Text auf Deutsch, prägnant (Ziel: unter 150 Zeichen), ohne "Bild von..."-Floskeln

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern
    """
    client = _get_client()

    # Bild als Base64 für Vision-API vorbereiten
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    system_prompt = """Du erstellst Alt-Texte für Social-Media-Bilder (Instagram/Facebook) für HILO,
einen deutschen Lohnsteuerhilfeverein.

REGELN:
- Beschreibe was WIRKLICH im Bild zu sehen ist (Motiv, Personen, Objekte, Stimmung) - konkret,
  nicht generisch
- Beginne NICHT mit "Bild von", "Foto zeigt", "Grafik mit" - Screenreader kündigen das Bild
  bereits als Bild an, das ist redundant
- Wiederhole NICHT die im Bild sichtbare Überschrift wortwörtlich - der Screenreader liest ggf.
  auch den Bildtext vor, doppelt beschreiben verwirrt. Beschreibe stattdessen das VISUELLE.
- Kurz und dicht: 1-2 Sätze, ca. 100-150 Zeichen. Kein Blumen-Deutsch, keine Adjektiv-Häufung.
- Keine Hashtags, keine Keyword-Anhäufung, kein SEO-Spam
- Deutsche Sprache, echte Umlaute (ä, ö, ü, ß)
- Wenn Personen im Bild sind: nur äußerlich erkennbare Fakten beschreiben (z.B. "ältere Frau am
  Küchentisch"), keine Vermutungen über Identität, Emotion, die nicht sichtbar ist
"""

    user_prompt = f"""Erstelle einen Alt-Text für dieses Bild.

Kontext (NICHT wortwörtlich übernehmen, nur zur Einordnung):
- Kernaussage des Posts: {kernaussage or "(nicht angegeben)"}
- Im Bild sichtbare Überschrift (NICHT wiederholen): {headline or "(kein Text im Bild)"}
"""

    log.info("Generiere Alt-Text aus fertigem Bild...")

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                        }
                    ]
                }
            ],
            max_tokens=150,
            temperature=0.3  # Faktentreue wichtiger als Kreativität
        )

        alt_text = completion.choices[0].message.content.strip()

        if not alt_text:
            raise Exception("OpenAI API gab keinen Alt-Text zurück")

        log.info(f"✓ Alt-Text generiert ({len(alt_text)} Zeichen): {alt_text[:80]}...")
        return alt_text

    except Exception as e:
        # Alt-Text ist ein Zusatznutzen, kein Blocker - Pipeline soll bei Fehler weiterlaufen
        log.warning(f"Alt-Text-Generierung fehlgeschlagen, wird leer gelassen: {e}")
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IMAGE GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_image(
    production_brief: ImageProductionBrief,
    size: str = "1024x1024",
    quality: str = "medium",
    output_path: Optional[Path] = None
) -> Image.Image:
    """Generiert Rohmotiv mit OpenAI Image Model.

    Args:
        production_brief: Production Brief mit Prompt
        size: Bildgröße ('1024x1024', '1024x1792', '1792x1024')
        quality: Qualität ('low', 'medium', 'high', 'auto') - default: 'medium'
        output_path: Optional - Pfad zum Speichern (None = nicht speichern)

    Returns:
        PIL.Image: Generiertes Bild

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei Image API-Fehlern
    """
    client = _get_client()

    log.info(f"Generiere Bild ({size}, quality={quality})...")
    log.debug(f"Prompt: {production_brief.image_prompt[:200]}...")

    try:
        # OpenAI Image API-Call
        # Model: gpt-image-2 (neueres Modell) oder gpt-image-1 (bewährt)
        response = client.images.generate(
            model="gpt-image-2",
            prompt=production_brief.image_prompt,
            size=size,
            quality=quality,
            n=1
        )

        # Bild extrahieren (URL oder b64_json)
        import requests
        import base64

        image_data = response.data[0]

        # Debug: Response-Struktur (nur bei log.debug() aktiv)
        log.debug(f"image_data.url = {image_data.url}")
        log.debug(f"image_data.b64_json exists = {hasattr(image_data, 'b64_json')}")
        log.debug(f"response.data[0] attributes = {dir(image_data)}")

        if image_data.url:
            # URL-basiert
            log.debug(f"Download von URL: {image_data.url[:50]}...")
            image_response = requests.get(image_data.url)
            image = Image.open(BytesIO(image_response.content))
        elif hasattr(image_data, 'b64_json') and image_data.b64_json:
            # Base64-basiert
            log.debug("Dekodiere Base64-Bild")
            image_bytes = base64.b64decode(image_data.b64_json)
            image = Image.open(BytesIO(image_bytes))
        else:
            raise ValueError(f"Response enthält weder URL noch b64_json! Response: {image_data}")

        log.info(f"✓ Bild generiert: {image.size[0]}x{image.size[1]} px")

        # Optional: Speichern
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "PNG")
            log.info(f"✓ Bild gespeichert: {output_path}")

        return image

    except Exception as e:
        log.error(f"Fehler bei Bild-Generierung: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIGH-LEVEL API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def produce_image(
    brief: MessageBrief,
    route: CreativeRoute,
    art_board: ArtDirectionBoard,
    headline: str = "",
    size: str = "1024x1024",
    quality: str = "medium",
    output_path: Optional[Path] = None
) -> tuple[Image.Image, ImageProductionBrief]:
    """High-Level API: Erstellt Production Brief + generiert Bild.

    Kombination aus create_production_brief() und generate_image().

    Args:
        brief: Message Brief
        route: Gewinnende kreative Route
        art_board: Art Direction Board
        headline: Freigegebene Überschrift vom Copywriter (wird INS Bild geschrieben!)
        size: Bildgröße (default: 1024x1024)
        quality: Qualität ('low', 'medium', 'high', 'auto') - default: 'medium'
        output_path: Optional Speicherpfad

    Returns:
        tuple: (PIL.Image, ImageProductionBrief) - production_brief.alt_text enthält den
            barrierefreien Alt-Text (leer bei Fehler, blockiert die Pipeline nicht)

    Example:
        >>> image, prod_brief = produce_image(brief, route, art_board, headline="Sparen bei Steuern")
        >>> image.show()
        >>> print(prod_brief.image_prompt)
        >>> print(prod_brief.alt_text)
    """
    # Schritt 1: Production Brief erstellen (mit headline!)
    production_brief = create_production_brief(brief, route, art_board, headline=headline)

    # Schritt 2: Bild generieren
    image = generate_image(production_brief, size, quality, output_path)

    # Schritt 3: Alt-Text aus dem fertigen Bild generieren (best effort, nicht blockierend)
    production_brief.alt_text = generate_alt_text(
        image, headline=headline, kernaussage=brief.kernaussage
    )

    return image, production_brief


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    # Test mit Mock-Daten
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from message_brief import MessageBrief
    from creative_director import CreativeRoute
    from art_director import ArtDirectionBoard

    print("="*80)
    print("IMAGE PRODUCER TEST")
    print("="*80)

    # Test Message Brief
    brief = MessageBrief(
        kernaussage="Wichtige Steuerfrist endet am 31. Dezember",
        nutzen="Rechtzeitig einreichen, Verspätungszuschlag vermeiden",
        zielgruppe="Arbeitnehmer",
        reaktion="Termin buchen",
        funnel_stufe="Decision",
        kanal="Facebook"
    )

    # Test Route
    route = CreativeRoute(
        typ="Visuelle Metapher",
        titel="Sanduhr mit rotem Sand",
        beschreibung="Dramatische Sanduhr im Fokus, roter Sand rinnt durch",
        visuelle_signatur="Dramatisches Licht von links, Rot-Kontrast",
        emotionale_richtung="Dringlichkeit",
        beispiel_szene="Sanduhr groß im Vordergrund, fast leer"
    )

    # Test Art Board
    art_board = ArtDirectionBoard(
        focal_point="Sanduhr im Vordergrund",
        focal_point_position="Rechte Hälfte",
        komposition_prinzip="Rule of Thirds",
        bildaufbau="Sanduhr rechts, Negativraum links für Text",
        licht_qualitaet="Dramatisch",
        licht_richtung="Von links",
        licht_stimmung="Spätes Nachmittagslicht, warm aber ernst",
        dominante_farben=["Rot", "Schwarz", "Gold", "Navy"],
        farbtemperatur="Warm-Kalt-Kontrast",
        farbkontrast="Komplementärkontrast Rot-Navy",
        emotionaler_moment="Moment der Dringlichkeit",
        atmosphaere="Professionell mahnend",
        kamera_perspektive="Eye-Level (Augenhöhe)",
        schaerfe_tiefe="Selektive Schärfe (nur Focal Point)",
        negativraum_text="Obere linke Hälfte ruhig",
        text_kontrast_empfehlung="Weißer Text auf dunklem Grund links"
    )

    print(f"\nMessage Brief: {brief.kernaussage}")
    print(f"Route: {route.titel}\n")

    try:
        # Schritt 1: Production Brief
        print("Schritt 1: Erstelle Production Brief...")
        prod_brief = create_production_brief(brief, route, art_board)

        print("\n📝 DALL-E PROMPT:")
        print("-" * 80)
        print(prod_brief.image_prompt)
        print("-" * 80)
        print(f"\nKeywords: {', '.join(prod_brief.style_keywords)}")
        print(f"Negative: {', '.join(prod_brief.negative_hints)}\n")

        # Schritt 2: Bild generieren
        print("Schritt 2: Generiere Bild mit gpt-image-2...")
        output_path = Path("/tmp/sharenext-test-image.png")
        image = generate_image(prod_brief, output_path=output_path)

        print(f"\n✅ Bild generiert: {image.size[0]}x{image.size[1]} px")
        print(f"   Gespeichert: {output_path}")
        print("\n" + "="*80)

    except Exception as e:
        print(f"\n❌ Fehler: {e}")
        print("\nHinweis: Dieser Test braucht einen OpenAI API-Key.")
