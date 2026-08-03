#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Creative Director - 4 kreative Routen für ShareNext-Pipeline.

Entwickelt aus einem Message Brief 4 unterschiedliche kreative Routen:
1. Emotionale Szene - Menschen in Situationen
2. Visuelle Metapher - Abstraktes bildlich dargestellt
3. Objektmotiv - Fokus auf ein zentrales Objekt
4. Kontrast/Störmoment - Unerwartetes Element

Teil von Issue #2: ShareNext MVP
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from message_brief import MessageBrief
from secrets_store import get_secret

log = logging.getLogger("hilo.creative_director")


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
# STRUCTURED OUTPUT MODELS (Pydantic)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreativeRoute(BaseModel):
    """Eine kreative Route - ein visuelles Konzept für das Bild.

    Jede Route repräsentiert eine andere Art, die Kernaussage visuell darzustellen.
    """

    typ: Literal[
        "Emotionale Szene",
        "Visuelle Metapher",
        "Objektmotiv",
        "Kontrast/Störmoment"
    ] = Field(description="Art der kreativen Route")

    titel: str = Field(
        max_length=60,
        description="Kurzer prägnanter Titel der Route (z.B. 'Erleichterter Unternehmer')"
    )

    beschreibung: str = Field(
        description="Detaillierte Beschreibung der visuellen Idee (2-3 Sätze)"
    )

    visuelle_signatur: str = Field(
        description="Was macht diese Route visuell erkennbar? (z.B. 'Warme Lichtstimmung, Nahaufnahme Gesicht')"
    )

    emotionale_richtung: str = Field(
        description="Welche Emotion soll transportiert werden? (z.B. 'Erleichterung', 'Dringlichkeit', 'Vertrauen')"
    )

    beispiel_szene: str = Field(
        description="Konkretes Beispiel wie das Bild aussehen könnte (1-2 Sätze)"
    )


class CreativeTerritories(BaseModel):
    """4 kreative Routen vom Creative Director.

    Der Creative Director entwickelt 4 unterschiedliche Ansätze um die
    Kernaussage visuell darzustellen. Jede Route folgt einem anderen Prinzip.
    """

    route_1_emotionale_szene: CreativeRoute = Field(
        description="Route 1: Emotionale Szene - Menschen in einer Situation (Erleichterung, Stress, Freude)"
    )

    route_2_metapher: CreativeRoute = Field(
        description="Route 2: Visuelle Metapher - Abstraktes Konzept bildlich (Wegweiser, Waage, Puzzle, Sanduhr)"
    )

    route_3_objekt: CreativeRoute = Field(
        description="Route 3: Objektmotiv - Fokus auf ein zentrales Objekt (Dokument, Ordner, Stempel, Kalender)"
    )

    route_4_kontrast: CreativeRoute = Field(
        description="Route 4: Kontrast/Störmoment - Unerwartetes Element das Aufmerksamkeit erzeugt"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_creative_routes(
    brief: MessageBrief,
    model: str = "gpt-4o"
) -> CreativeTerritories:
    """Generiert 4 kreative Routen aus einem Message Brief.

    Der Creative Director entwickelt 4 unterschiedliche visuelle Ansätze:
    1. Emotionale Szene (Menschen in Situationen)
    2. Visuelle Metapher (Abstraktes bildlich)
    3. Objektmotiv (Fokus auf Objekt)
    4. Kontrast/Störmoment (Unerwartetes)

    Args:
        brief: Message Brief mit Kernaussage, Nutzen, Zielgruppe, etc.
        model: OpenAI-Modell (default: gpt-4o für kreative Aufgaben)

    Returns:
        CreativeTerritories: 4 kreative Routen

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern

    Example:
        >>> from message_brief import MessageBrief
        >>> brief = MessageBrief(
        ...     kernaussage="Wichtige Steuerfrist endet am 31. Dezember",
        ...     nutzen="Verspätungszuschlag vermeiden",
        ...     zielgruppe="Arbeitnehmer",
        ...     reaktion="Termin buchen",
        ...     funnel_stufe="Decision",
        ...     kanal="Facebook"
        ... )
        >>> routes = generate_creative_routes(brief)
        >>> print(routes.route_2_metapher.titel)
        'Sanduhr mit rotem Sand'
    """
    client = _get_client()

    # System-Prompt: Creative Director Rolle
    system_prompt = """Du bist ein erfahrener Creative Director für Social-Media-Marketing.
Deine Aufgabe: Entwickle 4 unterschiedliche kreative Routen für ein Social-Media-Bild.

Kontext:
- HILO ist eine Hilfsorganisation für Lohnsteuerhilfe
- Zielgruppe: Hauptsächlich Arbeitnehmer und Rentner
- Stil: Professionell, vertrauenswürdig, aber NICHT langweilig
- Ziel: Scroll-Stop-Potenzial - das Bild soll auffallen!

Die 4 Routen-Typen:

1. **Emotionale Szene**
   - Menschen in realistischen Situationen
   - Emotionen: Erleichterung, Stress, Freude, Zufriedenheit
   - Beispiele: Erleichterter Unternehmer am Schreibtisch, Familie beim Ausfüllen von Formularen
   - NICHT: Stock-Foto-Klischees vermeiden!

2. **Visuelle Metapher**
   - Abstraktes Konzept bildlich dargestellt
   - Beispiele: Sanduhr (Zeit läuft ab), Wegweiser (Orientierung), Waage (Ausgleich), Puzzle (Komplexität)
   - Muss zur Kernaussage passen
   - Darf nicht zu abstrakt sein (Zielgruppe muss es verstehen)

3. **Objektmotiv**
   - Fokus auf EIN zentrales Objekt
   - Beispiele: Dokument mit Stempel, Kalender mit markiertem Datum, Ordner, Sparschwein
   - Still-Life-Fotografie-Stil
   - Objekt muss klar erkennbar und relevant sein

4. **Kontrast/Störmoment**
   - Unerwartetes Element das Aufmerksamkeit erzeugt
   - Beispiele: Große rote "31" in ruhigem Büro, leerer Schreibtisch mit EINEM auffälligen Element
   - Pattern-Interrupt - bricht Erwartungen
   - NICHT willkürlich - muss zur Botschaft passen

Wichtig:
- Jede Route muss ANDERS sein (nicht nur leichte Variationen)
- Visuell erkennbare Signaturen (Licht, Farbe, Komposition)
- Alle 4 müssen zur Kernaussage passen
- Scroll-Stop-Potenzial beachten
- Keine generischen Stock-Foto-Klischees
"""

    # User-Prompt: Message Brief Daten
    user_prompt = f"""Entwickle 4 kreative Routen für diesen Social-Media-Post:

**Message Brief:**
- Kernaussage: {brief.kernaussage}
- Nutzen: {brief.nutzen}
- Zielgruppe: {brief.zielgruppe}
- Reaktion: {brief.reaktion}
- Funnel-Stufe: {brief.funnel_stufe}
- Kanal: {brief.kanal}

Erstelle 4 unterschiedliche kreative Routen:
1. Emotionale Szene (Menschen)
2. Visuelle Metapher (Abstraktes)
3. Objektmotiv (Objekt-Fokus)
4. Kontrast/Störmoment (Unerwartetes)

Jede Route braucht:
- Titel (kurz, prägnant)
- Beschreibung (2-3 Sätze)
- Visuelle Signatur (was macht sie erkennbar?)
- Emotionale Richtung (welche Emotion?)
- Beispiel-Szene (konkretes Bild-Beispiel)
"""

    log.info(f"Generiere 4 kreative Routen für: {brief.kernaussage}")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=CreativeTerritories,
            temperature=0.9  # Hohe Kreativität!
        )

        territories = completion.choices[0].message.parsed

        if not territories:
            raise Exception("OpenAI API gab keine validen Creative Territories zurück")

        log.info(
            f"✓ 4 kreative Routen generiert:\n"
            f"   1. {territories.route_1_emotionale_szene.titel}\n"
            f"   2. {territories.route_2_metapher.titel}\n"
            f"   3. {territories.route_3_objekt.titel}\n"
            f"   4. {territories.route_4_kontrast.titel}"
        )
        return territories

    except Exception as e:
        log.error(f"Fehler beim Generieren der kreativen Routen: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    # Test-Beispiele
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Test Message Briefs
    test_briefs = [
        MessageBrief(
            kernaussage="Wichtige Steuerfrist endet am 31. Dezember",
            nutzen="Rechtzeitig einreichen, Verspätungszuschlag vermeiden",
            zielgruppe="Arbeitnehmer",
            reaktion="Termin buchen",
            funnel_stufe="Decision",
            kanal="Facebook"
        ),
        MessageBrief(
            kernaussage="Kindergeld beantragen - So geht's Schritt für Schritt",
            nutzen="Finanzielle Unterstützung für Familien sichern",
            zielgruppe="Eltern mit Kindern",
            reaktion="Artikel lesen und Termin buchen",
            funnel_stufe="Consideration",
            kanal="Instagram"
        ),
    ]

    for i, brief in enumerate(test_briefs, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}: {brief.kernaussage}")
        print(f"{'='*80}")

        try:
            routes = generate_creative_routes(brief)

            print(f"\n🎨 4 Kreative Routen:\n")

            for j, route_name in enumerate([
                "route_1_emotionale_szene",
                "route_2_metapher",
                "route_3_objekt",
                "route_4_kontrast"
            ], 1):
                route = getattr(routes, route_name)
                print(f"{j}. {route.typ}: {route.titel}")
                print(f"   {route.beschreibung}")
                print(f"   Signatur: {route.visuelle_signatur}")
                print(f"   Emotion: {route.emotionale_richtung}")
                print(f"   Beispiel: {route.beispiel_szene}")
                print()

        except Exception as e:
            print(f"\n❌ Fehler: {e}")
