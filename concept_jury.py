#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Concept Jury - Bewertung und Auswahl der besten kreativen Route.

Bewertet die 4 kreativen Routen nach gewichteten Kriterien und wählt den Gewinner.

Bewertungskriterien:
- Botschaftsklarheit (20%)
- Scroll-Stop-Potenzial (20%)
- Markenpassung (15%)
- Originalität (15%)
- Umsetzbarkeit (10%)
- Emotionale Wirkung (10%)
- Zielgruppenrelevanz (10%)

Mindestwerte: 7-8/10 für finale Auswahl

Teil von Issue #3: ShareNext MVP
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from message_brief import MessageBrief
from creative_director import CreativeTerritories, CreativeRoute
from secrets_store import get_secret

log = logging.getLogger("hilo.concept_jury")


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


class RouteEvaluation(BaseModel):
    """Bewertung einer einzelnen kreativen Route."""

    route_name: str = Field(description="Name/Typ der Route (z.B. 'Emotionale Szene')")
    route_titel: str = Field(description="Titel der Route")

    # Bewertungen (Skala 1-10)
    botschaftsklarheit: float = Field(
        ge=1.0, le=10.0,
        description="Ist die Kernaussage klar erkennbar? (1-10)"
    )
    scroll_stop_potenzial: float = Field(
        ge=1.0, le=10.0,
        description="Fällt das Bild auf? Stoppt es den Scroll? (1-10)"
    )
    markenpassung: float = Field(
        ge=1.0, le=10.0,
        description="Passt es zur HILO-Marke? (vertrauenswürdig, professionell) (1-10)"
    )
    originalitaet: float = Field(
        ge=1.0, le=10.0,
        description="Hebt sich das Konzept ab? Vermeidet Stock-Klischees? (1-10)"
    )
    umsetzbarkeit: float = Field(
        ge=1.0, le=10.0,
        description="Ist es technisch/praktisch realisierbar? (1-10)"
    )
    emotionale_wirkung: float = Field(
        ge=1.0, le=10.0,
        description="Erzeugt es die gewünschte emotionale Reaktion? (1-10)"
    )
    zielgruppenrelevanz: float = Field(
        ge=1.0, le=10.0,
        description="Spricht es die Zielgruppe an? (1-10)"
    )

    # Gewichtete Gesamtbewertung (berechnet)
    gesamtscore: float = Field(
        ge=1.0, le=10.0,
        description="Gewichteter Durchschnitt aller Kriterien (1-10)"
    )

    # Begründung
    staerken: str = Field(description="Was macht diese Route stark?")
    schwaechen: str = Field(description="Was könnte besser sein?")
    empfehlung: Literal["Stark empfohlen", "Empfohlen", "Bedingt empfohlen", "Nicht empfohlen"] = Field(
        description="Gesamtempfehlung basierend auf Score"
    )


class ConceptJuryVerdict(BaseModel):
    """Verdict der Concept Jury - Bewertung aller 4 Routen + Gewinner."""

    # Bewertungen aller 4 Routen
    evaluation_1: RouteEvaluation = Field(description="Bewertung Route 1 (Emotionale Szene)")
    evaluation_2: RouteEvaluation = Field(description="Bewertung Route 2 (Metapher)")
    evaluation_3: RouteEvaluation = Field(description="Bewertung Route 3 (Objekt)")
    evaluation_4: RouteEvaluation = Field(description="Bewertung Route 4 (Kontrast)")

    # Gewinner
    winning_route: Literal[1, 2, 3, 4] = Field(
        description="Nummer der gewinnenden Route (1-4)"
    )
    winning_score: float = Field(
        ge=1.0, le=10.0,
        description="Score der gewinnenden Route"
    )
    winning_titel: str = Field(description="Titel der gewinnenden Route")

    # Begründung für Auswahl
    begruendung: str = Field(
        description="Warum diese Route gewonnen hat (2-3 Sätze)"
    )

    # Warnung falls Score zu niedrig
    quality_warning: bool = Field(
        default=False,
        description="True wenn Gewinner-Score < 7.0 (Qualitätswarnung)"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCORE-BERECHNUNG (code-seitig, nicht vom LLM)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MINDEST_SCORE = 7.0

# Kriterium -> Gewicht (Summe = 1.00)
_GEWICHTE = {
    "botschaftsklarheit": 0.20,
    "scroll_stop_potenzial": 0.20,
    "markenpassung": 0.15,
    "originalitaet": 0.15,
    "umsetzbarkeit": 0.10,
    "emotionale_wirkung": 0.10,
    "zielgruppenrelevanz": 0.10,
}


def _weighted_score(evaluation: "RouteEvaluation") -> float:
    """Berechnet den gewichteten Gesamtscore einer Route."""
    return round(sum(getattr(evaluation, k) * w for k, w in _GEWICHTE.items()), 2)


def _empfehlung_fuer(score: float) -> str:
    if score >= 8.5:
        return "Stark empfohlen"
    if score >= 7.0:
        return "Empfohlen"
    if score >= 5.0:
        return "Bedingt empfohlen"
    return "Nicht empfohlen"


def _recompute_verdict(verdict: "ConceptJuryVerdict") -> None:
    """Rechnet Scores nach und bestimmt den Gewinner CODE-seitig.

    #Rechen-Fix: Vorher hat das LLM sowohl den gewichteten Durchschnitt als auch die Auswahl
    des Gewinners selbst vorgenommen - ohne Pruefung, ob die gewaehlte Route wirklich den
    hoechsten Score hat. LLMs rechnen unzuverlaessig; die Auswahl ist eine Gate-Entscheidung.
    Das LLM liefert jetzt faktisch nur noch die Einzelbewertungen + Begruendungen.
    """
    evaluations = {
        1: verdict.evaluation_1,
        2: verdict.evaluation_2,
        3: verdict.evaluation_3,
        4: verdict.evaluation_4,
    }

    # Einzelscores + Empfehlungen neu berechnen
    for evaluation in evaluations.values():
        evaluation.gesamtscore = _weighted_score(evaluation)
        evaluation.empfehlung = _empfehlung_fuer(evaluation.gesamtscore)

    # Gewinner = hoechster Score (bei Gleichstand niedrigste Routennummer)
    gewinner_nr = max(evaluations, key=lambda nr: (evaluations[nr].gesamtscore, -nr))
    gewinner = evaluations[gewinner_nr]

    if verdict.winning_route != gewinner_nr:
        log.warning(
            "LLM waehlte Route %s, hoechster berechneter Score hat aber Route %s (%.2f) - "
            "korrigiert.", verdict.winning_route, gewinner_nr, gewinner.gesamtscore
        )

    verdict.winning_route = gewinner_nr
    verdict.winning_score = gewinner.gesamtscore
    verdict.winning_titel = gewinner.route_titel
    verdict.quality_warning = gewinner.gesamtscore < MINDEST_SCORE


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EVALUATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def evaluate_routes(
    brief: MessageBrief,
    territories: CreativeTerritories,
    model: str = "gpt-5.6-terra"
) -> ConceptJuryVerdict:
    """Bewertet 4 kreative Routen und wählt die beste aus.

    Die Concept Jury bewertet jede Route nach 7 gewichteten Kriterien:
    - Botschaftsklarheit (20%)
    - Scroll-Stop-Potenzial (20%)
    - Markenpassung (15%)
    - Originalität (15%)
    - Umsetzbarkeit (10%)
    - Emotionale Wirkung (10%)
    - Zielgruppenrelevanz (10%)

    Mindestwert für Gewinner: 7.0/10

    Args:
        brief: Message Brief (Kontext für Bewertung)
        territories: 4 kreative Routen vom Creative Director
        model: OpenAI-Modell (default: gpt-5.6-terra)

    Returns:
        ConceptJuryVerdict: Bewertungen aller Routen + Gewinner

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern

    Example:
        >>> verdict = evaluate_routes(brief, territories)
        >>> print(f"Gewinner: Route {verdict.winning_route} - {verdict.winning_titel}")
        >>> print(f"Score: {verdict.winning_score}/10")
        >>> print(verdict.begruendung)
    """
    client = _get_client()

    # Extrahiere Routen
    routes = [
        ("Route 1: Emotionale Szene", territories.route_1_emotionale_szene),
        ("Route 2: Visuelle Metapher", territories.route_2_metapher),
        ("Route 3: Objektmotiv", territories.route_3_objekt),
        ("Route 4: Kontrast/Störmoment", territories.route_4_kontrast),
    ]

    # System-Prompt: Concept Jury Rolle
    system_prompt = """Du bist eine Concept Jury für Social-Media-Marketing.
Deine Aufgabe: Bewerte 4 kreative Routen objektiv und wähle die beste aus.

Kontext:
- HILO ist eine Hilfsorganisation für Lohnsteuerhilfe
- Marke: Vertrauenswürdig, professionell, aber NICHT langweilig
- Zielgruppe: siehe Message Brief im User-Prompt - die dort genannte KONKRETE Zielgruppe ist
  maßgeblich für das Kriterium "Zielgruppenrelevanz", nicht eine pauschale Annahme
- Ziel: Scroll-Stop-Potenzial + Markenpassung

Bewertungskriterien (Skala 1-10):

1. **Botschaftsklarheit (20%)**: Ist die Kernaussage klar und sofort verständlich?
   - 9-10: Kristallklar, unmissverständlich
   - 7-8: Klar erkennbar
   - 5-6: Etwas unklar, muss nachdenken
   - 1-4: Verwirrend, unklar

2. **Scroll-Stop-Potenzial (20%)**: Fällt das Bild im Feed auf?
   - 9-10: Sofortiger Eye-Catcher, unmöglich zu ignorieren
   - 7-8: Fällt auf, hebt sich ab
   - 5-6: Okay, aber nichts Besonderes
   - 1-4: Langweilig, geht unter

3. **Markenpassung (15%)**: Passt es zur HILO-Marke?
   - 9-10: Perfekt: vertrauenswürdig UND interessant
   - 7-8: Gut, passt
   - 5-6: Etwas off-brand
   - 1-4: Passt nicht zur Marke
   - WICHTIG: "Vertrauenswürdig" heißt NICHT "brav". Auffällige, kontraststarke oder
     ungewöhnliche Konzepte NICHT abwerten, nur weil sie mutig sind - werte nur ab, wenn es
     reißerisch wird oder die Seriosität eines Lohnsteuerhilfevereins beschädigt.

4. **Originalität (15%)**: Hebt sich das Konzept ab?
   - 9-10: Völlig neu, unerwartet
   - 7-8: Frisch, vermeidet Klischees
   - 5-6: Etwas gesehen, aber okay
   - 1-4: Stock-Klischee

5. **Umsetzbarkeit (10%)**: Kann man das realistisch umsetzen?
   - 9-10: Einfach umsetzbar
   - 7-8: Machbar mit Standard-Tools
   - 5-6: Herausfordernd
   - 1-4: Unrealistisch

6. **Emotionale Wirkung (10%)**: Erzeugt es die gewünschte Emotion?
   - 9-10: Starke emotionale Resonanz
   - 7-8: Emotion erkennbar
   - 5-6: Etwas flach
   - 1-4: Keine emotionale Wirkung

7. **Zielgruppenrelevanz (10%)**: Spricht es die Zielgruppe an?
   - 9-10: Perfekt auf Zielgruppe zugeschnitten
   - 7-8: Passt zur Zielgruppe
   - 5-6: Etwas daneben
   - 1-4: Verfehlt Zielgruppe

**Gesamtscore Berechnung:**
Der gewichtete Gesamtscore und die Auswahl des Gewinners werden VOM SYSTEM berechnet
(Gewichte: Botschaftsklarheit 20%, Scroll-Stop 20%, Markenpassung 15%, Originalität 15%,
Umsetzbarkeit 10%, Emotionale Wirkung 10%, Zielgruppenrelevanz 10%).
Du musst NICHT rechnen - konzentriere dich auf präzise Einzelbewertungen (1-10) und gute
Begründungen. Deine Angaben zu gesamtscore/winning_route werden überschrieben.

**Mindestwert für Gewinner: 7.0/10**

Wichtig:
- Sei kritisch aber fair
- Begründe deine Bewertungen
- Der beste ist nicht immer der "sicherste" - Originalität zählt!
- Aber: Markenpassung ist wichtig (keine wilden Experimente)
"""

    # User-Prompt: Routes + Message Brief
    routes_text = "\n\n".join([
        f"**{name}**\n"
        f"Titel: {route.titel}\n"
        f"Typ: {route.typ}\n"
        f"Beschreibung: {route.beschreibung}\n"
        f"Visuelle Signatur: {route.visuelle_signatur}\n"
        f"Emotion: {route.emotionale_richtung}\n"
        f"Beispiel: {route.beispiel_szene}"
        for name, route in routes
    ])

    user_prompt = f"""Bewerte diese 4 kreativen Routen und wähle die beste aus.

**Message Brief (Kontext):**
- Kernaussage: {brief.kernaussage}
- Nutzen: {brief.nutzen}
- Zielgruppe: {brief.zielgruppe}
- Reaktion: {brief.reaktion}
- Funnel-Stufe: {brief.funnel_stufe}
- Kanal: {brief.kanal}

**4 Kreative Routen:**

{routes_text}

Bewerte jede Route nach den 7 Kriterien (1-10).
Begründe Stärken und Schwächen je Route.
Der gewichtete Gesamtscore und der Gewinner werden vom System berechnet - du musst nicht rechnen.
"""

    log.info(f"Concept Jury bewertet 4 Routen für: {brief.kernaussage}")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=ConceptJuryVerdict,
            temperature=0.3  # Objektive Bewertung, wenig Kreativität
        )

        verdict = completion.choices[0].message.parsed

        if not verdict:
            raise Exception("OpenAI API gab kein valides Concept Jury Verdict zurück")

        # Scores + Gewinner code-seitig neu berechnen (LLM-Werte werden überschrieben)
        _recompute_verdict(verdict)

        # Warnung falls Score zu niedrig
        if verdict.quality_warning:
            log.warning(
                f"⚠️ Gewinner-Score ({verdict.winning_score:.1f}) unter Mindestwert "
                f"{MINDEST_SCORE}! Qualitätswarnung aktiv."
            )

        log.info(
            f"✓ Concept Jury Verdict:\n"
            f"   Gewinner: Route {verdict.winning_route} - {verdict.winning_titel}\n"
            f"   Score: {verdict.winning_score:.1f}/10 (berechnet)\n"
            f"   Begründung: {verdict.begruendung}"
        )

        return verdict

    except Exception as e:
        log.error(f"Fehler bei Concept Jury Bewertung: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    # Test mit Mock-Daten
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from message_brief import MessageBrief
    from creative_director import generate_creative_routes

    print("="*80)
    print("CONCEPT JURY TEST")
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

    print(f"\nMessage Brief: {brief.kernaussage}")
    print(f"Zielgruppe: {brief.zielgruppe}\n")

    try:
        # Generiere Routen (braucht OpenAI API-Key)
        print("Schritt 1: Creative Director generiert 4 Routen...")
        territories = generate_creative_routes(brief)

        print("✓ 4 Routen generiert:")
        print(f"  1. {territories.route_1_emotionale_szene.titel}")
        print(f"  2. {territories.route_2_metapher.titel}")
        print(f"  3. {territories.route_3_objekt.titel}")
        print(f"  4. {territories.route_4_kontrast.titel}\n")

        # Bewerte Routen
        print("Schritt 2: Concept Jury bewertet Routen...\n")
        verdict = evaluate_routes(brief, territories)

        # Zeige alle Bewertungen
        print("📊 BEWERTUNGEN:\n")
        for i, eval_name in enumerate([
            "evaluation_1", "evaluation_2", "evaluation_3", "evaluation_4"
        ], 1):
            evaluation = getattr(verdict, eval_name)
            print(f"Route {i}: {evaluation.route_titel}")
            print(f"  Gesamtscore: {evaluation.gesamtscore:.1f}/10")
            print(f"  Botschaft: {evaluation.botschaftsklarheit:.1f} | "
                  f"Scroll-Stop: {evaluation.scroll_stop_potenzial:.1f} | "
                  f"Marke: {evaluation.markenpassung:.1f}")
            print(f"  Stärken: {evaluation.staerken}")
            print(f"  Schwächen: {evaluation.schwaechen}")
            print(f"  Empfehlung: {evaluation.empfehlung}\n")

        # Zeige Gewinner
        print("="*80)
        print(f"🏆 GEWINNER: Route {verdict.winning_route} - {verdict.winning_titel}")
        print(f"   Score: {verdict.winning_score:.1f}/10")
        print(f"   Begründung: {verdict.begruendung}")

        if verdict.quality_warning:
            print(f"\n⚠️  QUALITÄTSWARNUNG: Score unter 7.0!")

        print("="*80)

    except Exception as e:
        print(f"\n❌ Fehler: {e}")
        print("\nHinweis: Dieser Test braucht einen OpenAI API-Key.")
