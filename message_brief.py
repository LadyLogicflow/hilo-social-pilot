#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Message Brief Generator für ShareNext-Pipeline.

Generiert automatisch ein strukturiertes Message Brief aus Post-Daten
(Stream, Thema, Text, Kanal) via KI.

Teil von Issue #1: ShareNext MVP
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from secrets_store import get_secret

log = logging.getLogger("hilo.message_brief")


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
# STRUCTURED OUTPUT MODEL (Pydantic)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MessageBrief(BaseModel):
    """Message Brief - strukturierte Zusammenfassung eines Social-Media-Posts.

    Wird automatisch aus Post-Daten (Stream, Thema, Text, Kanal) generiert
    und dient als Input für die ShareNext-Pipeline (Creative Director, etc.).
    """

    kernaussage: str = Field(
        description="Kernaussage des Posts in 1-2 Sätzen. Was ist die Hauptbotschaft?"
    )
    nutzen: str = Field(
        description="Was hat die Zielgruppe davon? Welches Problem wird gelöst oder welcher Vorteil geboten?"
    )
    zielgruppe: str = Field(
        description="Wen spricht dieser Post an? (z.B. 'Arbeitnehmer', 'Rentner', 'Eltern mit Kindern', 'Selbständige')"
    )
    reaktion: str = Field(
        description="Was soll die Zielgruppe tun? (z.B. 'Termin buchen', 'Artikel lesen', 'Frist merken')"
    )
    funnel_stufe: Literal["Awareness", "Consideration", "Decision"] = Field(
        description="Funnel-Stufe: Awareness (Aufmerksamkeit), Consideration (Interesse), Decision (Handlung)"
    )
    kanal: str = Field(
        description="Social-Media-Kanal (Facebook, Instagram, LinkedIn, Google Business)"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_message_brief(
    stream: str,
    thema: str,
    text: str,
    kanal: str,
    model: str = "gpt-4o-mini"
) -> MessageBrief:
    """Generiert automatisch ein Message Brief aus Post-Daten via KI.

    Args:
        stream: Content-Stream ('radar', 'fristen', 'anlass', 'wissen')
        thema: Thema/Überschrift des Posts
        text: Post-Text/Beschreibung
        kanal: Social-Media-Kanal ('Facebook', 'Instagram', 'LinkedIn', 'Google Business')
        model: OpenAI-Modell (default: gpt-4o-mini für schnelle, günstige Generierung)

    Returns:
        MessageBrief: Strukturiertes Message Brief mit allen Feldern

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern

    Example:
        >>> brief = generate_message_brief(
        ...     stream="fristen",
        ...     thema="Steuerfrist 31.12.",
        ...     text="Jetzt Termin sichern!",
        ...     kanal="Facebook"
        ... )
        >>> print(brief.kernaussage)
        'Wichtige Steuerfrist endet am 31. Dezember'
        >>> print(brief.zielgruppe)
        'Arbeitnehmer'
    """
    client = _get_client()

    # System-Prompt: Erklärt die Aufgabe und Kontext
    system_prompt = """Du bist ein Marketing-Experte für Steuerberatung.
Deine Aufgabe: Analysiere Social-Media-Posts und erstelle ein strukturiertes Message Brief.

Kontext:
- HILO ist eine Hilfsorganisation für Lohnsteuerhilfe
- Zielgruppe: Primär Arbeitnehmer und Rentner (aber leite die spezifische Zielgruppe aus dem Thema ab!)
- Content-Streams:
  * 'radar': Aktuelle News/Gesetzesänderungen → meist Awareness
  * 'fristen': Wichtige Termine/Deadlines → meist Decision
  * 'anlass': Saisonale Themen (Jahresende, Steuererklärung) → meist Awareness
  * 'wissen': Erklärungen/Tutorials → meist Consideration

Wichtig:
- Kernaussage: Klar und prägnant (1-2 Sätze)
- Nutzen: Konkret, nicht generisch ("Versp­ätungszuschlag vermeiden" statt "gut informiert sein")
- Zielgruppe: Intelligent aus Thema ableiten (Kindergeld → Eltern, Rente → Rentner, etc.)
- Reaktion: Realistisch (meist "Termin buchen", "Frist merken", "Artikel lesen")
- Funnel-Stufe: Logisch aus Stream ableiten, aber flexibel
"""

    # User-Prompt: Konkrete Post-Daten
    user_prompt = f"""Analysiere diesen Post und erstelle ein Message Brief:

Stream: {stream}
Thema: {thema}
Text: {text}
Kanal: {kanal}

Erstelle ein strukturiertes Message Brief mit:
- kernaussage: Was ist die Hauptbotschaft?
- nutzen: Was hat die Zielgruppe davon?
- zielgruppe: Wen spricht das an? (leite aus Thema ab!)
- reaktion: Was soll passieren?
- funnel_stufe: Awareness, Consideration oder Decision?
- kanal: {kanal}
"""

    log.info(f"Generiere Message Brief für: {thema} ({stream}/{kanal})")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=MessageBrief,
            temperature=0.7  # Etwas Kreativität, aber konsistent
        )

        brief = completion.choices[0].message.parsed

        if not brief:
            raise Exception("OpenAI API gab kein valides Message Brief zurück")

        log.info(f"✓ Message Brief generiert: Zielgruppe='{brief.zielgruppe}', Funnel='{brief.funnel_stufe}'")
        return brief

    except Exception as e:
        log.error(f"Fehler beim Generieren des Message Briefs: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    # Test-Beispiele
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_cases = [
        {
            "stream": "fristen",
            "thema": "Steuerfrist 31.12. - Jetzt Termin sichern!",
            "text": "Die Abgabefrist für Ihre Steuererklärung endet am 31. Dezember. Vereinbaren Sie jetzt einen Termin!",
            "kanal": "Facebook"
        },
        {
            "stream": "wissen",
            "thema": "Kindergeld: So funktioniert die Beantragung",
            "text": "Wir erklären Schritt für Schritt wie Sie Kindergeld beantragen und was Sie beachten müssen.",
            "kanal": "Instagram"
        },
        {
            "stream": "radar",
            "thema": "Homeoffice-Pauschale: Neue Regelung ab 2026",
            "text": "Ab Januar 2026 gilt eine neue Pauschale für Homeoffice-Tage. Jetzt informieren!",
            "kanal": "LinkedIn"
        }
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"TEST {i}: {test['thema']}")
        print(f"{'='*60}")

        try:
            brief = generate_message_brief(
                stream=test["stream"],
                thema=test["thema"],
                text=test["text"],
                kanal=test["kanal"]
            )

            print(f"\n📋 Message Brief:")
            print(f"   Kernaussage: {brief.kernaussage}")
            print(f"   Nutzen: {brief.nutzen}")
            print(f"   Zielgruppe: {brief.zielgruppe}")
            print(f"   Reaktion: {brief.reaktion}")
            print(f"   Funnel-Stufe: {brief.funnel_stufe}")
            print(f"   Kanal: {brief.kanal}")

        except Exception as e:
            print(f"\n❌ Fehler: {e}")
