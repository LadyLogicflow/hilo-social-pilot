#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image Producer - Generiert Rohmotiv ohne Text für ShareNext-Pipeline.

Übersetzt Art Direction Board in DALL-E Prompt und generiert das Bild.

WICHTIG:
- KEIN TEXT im generierten Bild!
- Negativraum für Text muss vorhanden sein
- Text wird später deterministisch mit Pillow gesetzt

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


class ImageProductionBrief(BaseModel):
    """Production Brief - DALL-E Prompt aus Art Direction Board.

    Übersetzt visuelle Anweisungen in einen präzisen DALL-E Prompt.
    """

    dalle_prompt: str = Field(
        min_length=100,
        max_length=4000,
        description="Detaillierter DALL-E Prompt (100-4000 Zeichen). "
                    "WICHTIG: KEIN Text/Wörter/Zahlen im Bild! Nur visuelle Elemente."
    )

    style_keywords: list[str] = Field(
        min_length=3,
        max_length=8,
        description="3-8 Stil-Keywords (z.B. 'editorial photography', 'dramatic lighting', 'minimalist')"
    )

    negative_prompt_hints: str = Field(
        description="Was soll VERMIEDEN werden? (z.B. 'text, words, numbers, generic stock photo look')"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_production_brief(
    brief: MessageBrief,
    route: CreativeRoute,
    art_board: ArtDirectionBoard,
    model: str = "gpt-4o"
) -> ImageProductionBrief:
    """Erstellt Production Brief (DALL-E Prompt) aus Art Direction Board.

    Die Prompt Director Rolle übersetzt das Art Board in einen präzisen
    DALL-E Prompt der alle visuellen Elemente beschreibt.

    WICHTIG: KEIN TEXT im Bild! Text wird später deterministisch gesetzt.

    Args:
        brief: Message Brief (Kontext)
        route: Gewinnende kreative Route
        art_board: Art Direction Board mit visuellen Anweisungen
        model: OpenAI-Modell (default: gpt-4o)

    Returns:
        ImageProductionBrief: DALL-E Prompt + Keywords + Negative Hints

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern
    """
    client = _get_client()

    # System-Prompt: Prompt Director Rolle
    system_prompt = """Du bist ein Prompt Director für DALL-E Bildgenerierung.
Deine Aufgabe: Übersetze ein Art Direction Board in einen präzisen DALL-E Prompt.

KRITISCH WICHTIG:
- **KEIN TEXT** im Bild! Keine Wörter, Zahlen, Buchstaben!
- Text wird später deterministisch gesetzt (Pillow)
- Negativraum für Text MUSS vorhanden sein

DALL-E Prompt Struktur:

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
- DALL-E 3 versteht komplexe Prompts - nutze das!

Negatives (vermeiden):
- "text", "words", "numbers", "letters", "captions"
- "generic stock photo"
- "cluttered"
- "watermark", "logo" (außer explizit gewünscht)

HILO Brand:
- Farben: Navy (#1e3a5f), Blue (#4a7ba7), Green (#8fbc3f) - alle gleichwertig, Akzente gerne in einer dieser Farben
- Stil: Professionell aber warm, nicht steril
- Authentisch, nicht Stock-Klischee
"""

    # User-Prompt: Art Board Daten
    user_prompt = f"""Erstelle einen DALL-E Prompt aus diesem Art Direction Board:

**Message Brief (Kontext):**
- Kernaussage: {brief.kernaussage}
- Emotion: {brief.funnel_stufe} (leite gewünschte Stimmung ab)

**Kreative Route:**
- Typ: {route.typ}
- Titel: {route.titel}
- Beschreibung: {route.beschreibung}

**Art Direction Board:**

FOCAL POINT:
- Element: {art_board.focal_point}
- Position: {art_board.focal_point_position}

KOMPOSITION:
- Prinzip: {art_board.komposition_prinzip}
- Aufbau: {art_board.bildaufbau}

LICHT:
- Qualität: {art_board.licht_qualitaet}
- Richtung: {art_board.licht_richtung}
- Stimmung: {art_board.licht_stimmung}

FARBEN:
- Dominante: {', '.join(art_board.dominante_farben)}
- Temperatur: {art_board.farbtemperatur}
- Kontrast: {art_board.farbkontrast}

EMOTION:
- Moment: {art_board.emotionaler_moment}
- Atmosphäre: {art_board.atmosphaere}

TECHNISCH:
- Kamera: {art_board.kamera_perspektive}
- Schärfe: {art_board.schaerfe_tiefe}

TEXT-ZONEN:
- Negativraum: {art_board.negativraum_text}
- Text-Kontrast: {art_board.text_kontrast_empfehlung}

Erstelle:
1. Detaillierten DALL-E Prompt (100-4000 Zeichen)
2. 3-8 Stil-Keywords
3. Negative Prompt Hints (was vermeiden?)

WICHTIG: KEIN TEXT im Bild!
"""

    log.info(f"Prompt Director erstellt DALL-E Prompt für: {route.titel}")

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

        log.info(
            f"✓ Production Brief erstellt:\n"
            f"   Prompt-Länge: {len(production_brief.dalle_prompt)} Zeichen\n"
            f"   Keywords: {', '.join(production_brief.style_keywords[:3])}..."
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
    log.debug(f"Prompt: {production_brief.dalle_prompt[:200]}...")

    try:
        # OpenAI Image API-Call
        # Model: gpt-image-2 (neueres Modell) oder gpt-image-1 (bewährt)
        response = client.images.generate(
            model="gpt-image-2",
            prompt=production_brief.dalle_prompt,
            size=size,
            quality=quality,
            n=1
        )

        # Bild extrahieren (URL oder b64_json)
        import requests
        import base64

        image_data = response.data[0]

        if image_data.url:
            # URL-basiert
            log.debug(f"Download von URL: {image_data.url[:50]}...")
            image_response = requests.get(image_data.url)
            image = Image.open(BytesIO(image_response.content))
        elif image_data.b64_json:
            # Base64-basiert
            log.debug("Dekodiere Base64-Bild")
            image_bytes = base64.b64decode(image_data.b64_json)
            image = Image.open(BytesIO(image_bytes))
        else:
            raise ValueError("Response enthält weder URL noch b64_json!")

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
        size: Bildgröße (default: 1024x1024)
        quality: Qualität ('low', 'medium', 'high', 'auto') - default: 'medium'
        output_path: Optional Speicherpfad

    Returns:
        tuple: (PIL.Image, ImageProductionBrief)

    Example:
        >>> image, prod_brief = produce_image(brief, route, art_board)
        >>> image.show()
        >>> print(prod_brief.dalle_prompt)
    """
    # Schritt 1: Production Brief erstellen
    production_brief = create_production_brief(brief, route, art_board)

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
        print(prod_brief.dalle_prompt)
        print("-" * 80)
        print(f"\nKeywords: {', '.join(prod_brief.style_keywords)}")
        print(f"Negative: {prod_brief.negative_prompt_hints}\n")

        # Schritt 2: Bild generieren
        print("Schritt 2: Generiere Bild mit DALL-E 3...")
        output_path = Path("/tmp/sharenext-test-image.png")
        image = generate_image(prod_brief, output_path=output_path)

        print(f"\n✅ Bild generiert: {image.size[0]}x{image.size[1]} px")
        print(f"   Gespeichert: {output_path}")
        print("\n" + "="*80)

    except Exception as e:
        print(f"\n❌ Fehler: {e}")
        print("\nHinweis: Dieser Test braucht einen OpenAI API-Key.")
