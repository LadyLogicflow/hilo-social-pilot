#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image Producer - Generiert Premium-Bild MIT deutscher Überschrift für ShareNext-Pipeline.

Übersetzt Art Direction Board in gpt-image-2 Prompt und generiert das Bild.

WICHTIG:
- Text NUR auf DEUTSCH (NIEMALS Englisch!)
- Überschrift natürlich ins Bild integriert
- EURO (€) verwenden, NIEMALS Dollar ($)
- Zielgruppe: Deutsche Steuerzahler

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

    # System-Prompt: ShareNext Image Prompt Director (Catrin's Spezifikation)
    # System-Prompt: Einfacher Prompt Director (Stand 12:10, gute Bilder!)
    system_prompt = """Du bist ein Prompt Director für gpt-image-2 Bildgenerierung.
Deine Aufgabe: Übersetze ein Art Direction Board in einen präzisen Bildgenerierungs-Prompt.

KRITISCH WICHTIG - TEXT-REGELN:
- **ÜBERSCHRIFT MUSS SICHTBAR SEIN** - Die vorgegebene deutsche Überschrift MUSS groß, lesbar und prominent im Bild erscheinen!
- **Text NUR auf DEUTSCH** - Absolutely NO English!
- **Text natürlich integrieren** - auf Schildern, Wänden, Tafeln, Anzeigen, Plakaten (nicht schwebend!)
- **GROß UND LESBAR** - Die Überschrift muss auf Mobilgeräten gut lesbar sein!
- **EXAKT die vorgegebene Überschrift verwenden** - Keine Änderungen, keine Übersetzung!
- **EURO (€) verwenden** - NEVER Dollar ($) or USD!
- **Zielgruppe: Deutsche Steuerzahler** - alles auf Deutsch!

Bildgenerierungs-Prompt Struktur:

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

Text-Regeln (SEHR WICHTIG!):
- **ÜBERSCHRIFT IST PFLICHT** - Wenn eine Überschrift vorgegeben ist, MUSS sie prominent im Bild erscheinen!
- **GROß, DEUTLICH, LESBAR** - Die Überschrift muss das wichtigste Text-Element im Bild sein!
- **NUR DEUTSCHE SPRACHE** - Absolutely NO English words!
- **EURO (€) verwenden** - NEVER use Dollar ($) or other currencies
- **Natürliche Integration** - Text auf Schildern, Wänden, Tafeln, Plakaten, Anzeigen (nicht schwebend!)
- **EXAKT übernehmen** - Die vorgegebene Überschrift Wort für Wort verwenden, keine Änderungen!
- Keine zusätzlichen Labels, Captions oder Wasserzeichen

Negatives (vermeiden):
- "English text", "Dollar sign $", "USD"
- "generic stock photo"
- "cluttered"
- "watermark" (außer HILO Logo)

HILO Brand:
- Farben: Navy (#1f428d), Grün (#60a33c), Weiß - Akzente gerne in diesen Markenfarben
- Stil: Professionell aber warm, nicht steril
- Authentisch, nicht Stock-Klischee
- Zielgruppe: Deutsche Steuerzahler
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

Art Direction Board:
- Hauptmotiv: {art_board.focal_point}
- Umgebung: {art_board.bildaufbau}
- Komposition: {art_board.komposition_prinzip}
- Kameraperspektive: {art_board.kamera_perspektive}
- Licht: {art_board.licht_qualitaet}, {art_board.licht_richtung}, {art_board.licht_stimmung}
- Farbführung: {', '.join(art_board.dominante_farben)}, {art_board.farbtemperatur}, {art_board.farbkontrast}
- Materialität: (aus Beschreibung ableitbar)
- Atmosphäre: {art_board.atmosphaere}
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
            response_format=ImageProductionBrief,
            temperature=0.5  # Balance: Kreativ aber präzise
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
        tuple: (PIL.Image, ImageProductionBrief)

    Example:
        >>> image, prod_brief = produce_image(brief, route, art_board, headline="Sparen bei Steuern")
        >>> image.show()
        >>> print(prod_brief.image_prompt)
    """
    # Schritt 1: Production Brief erstellen (mit headline!)
    production_brief = create_production_brief(brief, route, art_board, headline=headline)

    # Schritt 2: Bild generieren
    image = generate_image(production_brief, size, quality, output_path)

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
