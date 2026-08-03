#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual QA - Qualitätsprüfung für ShareNext-Pipeline.

Gate A: Rohmotiv-Check (vor Text-Rendering)
Gate B: Final-Layout-Check (nach Text-Rendering) - später

Prüft:
- Leitidee erkennbar?
- Focal Point vollständig?
- Textzonen nutzbar?
- Markenpassung?
- Technische Qualität?

Teil von Issue #6: ShareNext MVP
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field

from message_brief import MessageBrief
from creative_director import CreativeRoute
from art_director import ArtDirectionBoard
from secrets_store import get_secret

log = logging.getLogger("hilo.visual_qa")


def _get_client() -> OpenAI:
    """Erstellt OpenAI-Client mit API-Key aus secrets.json oder Umgebung."""
    api_key = get_secret("openai_api_key")
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "Kein OpenAI API-Key verfügbar!"
        )

    return OpenAI(api_key=api_key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STRUCTURED OUTPUT MODEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class VisualQAVerdict(BaseModel):
    """Visual QA Verdict - Gate A: Rohmotiv-Check."""

    # Bewertungen (1-10)
    leitidee_erkennbar: float = Field(ge=1.0, le=10.0, description="Ist die Leitidee klar erkennbar?")
    focal_point_vollstaendig: float = Field(ge=1.0, le=10.0, description="Ist das Hauptelement vollständig sichtbar?")
    textzonen_nutzbar: float = Field(ge=1.0, le=10.0, description="Sind die Textzonen ruhig und nutzbar?")
    markenpassung: float = Field(ge=1.0, le=10.0, description="Passt es zur HILO-Marke?")
    technische_qualitaet: float = Field(ge=1.0, le=10.0, description="Technische Qualität okay?")

    # Gesamtscore
    gesamtscore: float = Field(ge=1.0, le=10.0, description="Durchschnitt aller Bewertungen")

    # Verdict
    freigegeben: bool = Field(description="True = freigegeben (Score >= 8.0), False = abgelehnt")

    # Feedback
    staerken: str = Field(description="Was ist gut?")
    schwaechen: str = Field(description="Was könnte besser sein?")
    empfehlung: str = Field(description="Freigeben oder neu generieren?")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# QA DIRECTOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def check_raw_image(
    image: Image.Image,
    brief: MessageBrief,
    route: CreativeRoute,
    art_board: ArtDirectionBoard,
    model: str = "gpt-4o"
) -> VisualQAVerdict:
    """Gate A: Prüft Rohmotiv (vor Text-Rendering).

    Args:
        image: PIL.Image - Das generierte Rohmotiv
        brief: Message Brief (Kontext)
        route: Gewinnende Route
        art_board: Art Direction Board
        model: OpenAI-Modell mit Vision (default: gpt-4o)

    Returns:
        VisualQAVerdict: Bewertung + Freigabe-Entscheidung

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern
    """
    client = _get_client()

    # Bild zu Base64
    import base64
    from io import BytesIO
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode()

    # System-Prompt: Visual QA Director Rolle
    system_prompt = """Du bist ein Visual QA Director für Social-Media-Marketing.
Deine Aufgabe: Prüfe das generierte Rohmotiv kritisch.

GATE A CHECKS (vor Text-Rendering):

1. **Leitidee erkennbar? (1-10)**
   - Ist die kreative Leitidee klar zu sehen?
   - Würde jemand ohne Kontext verstehen was gemeint ist?

2. **Focal Point vollständig? (1-10)**
   - Ist das Hauptelement vollständig im Bild?
   - Nichts abgeschnitten oder angeschnitten?

3. **Textzonen nutzbar? (1-10)**
   - Sind die Negativräume ruhig genug für Text?
   - Genug Kontrast für Lesbarkeit?

4. **Markenpassung? (1-10)**
   - Passt es zur HILO-Marke? (Vertrauenswürdig, Professionell, Persönlich, Unterstützend)
   - Stil: Freundlich warm und kompetent
   - Vermeiden: Zu laut, steril

5. **Technische Qualität? (1-10)**
   - Bildqualität okay?
   - Keine Artefakte, strange Proportionen?

**Freigabe-Regel:**
- Gesamtscore >= 8.0 → Freigegeben
- Gesamtscore < 8.0 → Abgelehnt (neu generieren)

Sei kritisch aber fair!
"""

    # User-Prompt
    user_prompt = f"""Prüfe dieses Rohmotiv (Gate A):

**Kontext:**
- Kernaussage: {brief.kernaussage}
- Route: {route.typ} - {route.titel}
- Gewünschte Emotion: {art_board.emotionaler_moment}

**Erwartungen:**
- Focal Point: {art_board.focal_point} ({art_board.focal_point_position})
- Negativraum: {art_board.negativraum_text}
- Atmosphäre: {art_board.atmosphaere}

Bewerte (1-10):
1. Leitidee erkennbar?
2. Focal Point vollständig?
3. Textzonen nutzbar?
4. Markenpassung (HILO: warm, professionell, persönlich)?
5. Technische Qualität?

Freigabe wenn Gesamtscore >= 8.0
"""

    log.info(f"Visual QA prüft Rohmotiv: {route.titel}")

    try:
        # OpenAI Vision API
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_b64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            response_format=VisualQAVerdict,
            temperature=0.3  # Objektiv
        )

        verdict = completion.choices[0].message.parsed

        if not verdict:
            raise Exception("OpenAI API gab kein valides QA Verdict zurück")

        log.info(
            f"✓ Visual QA Verdict:\n"
            f"   Gesamtscore: {verdict.gesamtscore:.1f}/10\n"
            f"   Freigegeben: {'Ja' if verdict.freigegeben else 'NEIN'}\n"
            f"   Empfehlung: {verdict.empfehlung}"
        )

        return verdict

    except Exception as e:
        log.error(f"Fehler bei Visual QA: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("="*80)
    print("VISUAL QA TEST")
    print("="*80)
    print("\nHinweis: Braucht ein generiertes Bild zum Testen.")
    print("Führe erst image_producer.py aus um ein Test-Bild zu generieren.")
    print("="*80)
