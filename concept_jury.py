#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Concept Jury - Bewertung und Auswahl der besten kreativen Route.

Bewertet die 5 kreativen Routen nach gewichteten Kriterien und wählt den Gewinner.

Bewertungskriterien (Gewichte, Summe = 100%):
- Botschaftsklarheit (20%)
- Scroll-Stop-Potenzial (25%)
- Markenpassung (15%)
- Originalität (15%)
- Umsetzbarkeit (5%)
- Emotionale Wirkung (15%)
- Zielgruppenrelevanz (5%)

Mindestwert: 7.0/10 für finale Auswahl (sonst Qualitätswarnung)

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

    # ─────────────────────────────────────────────────────────────────────────
    # SEMANTIC BRIDGE TEST (PRUEFMODUS) - ZUERST ausfuellen, DANN bewerten.
    # Zwingt aus dem Pitch-Modus in den Pruefmodus: erst pruefen, ob die Idee wirklich
    # ankommt, dann Punkte vergeben. Nicht die Marketing-Vorteile aufzaehlen.
    # ─────────────────────────────────────────────────────────────────────────
    read_500ms: str = Field(
        description="500-ms-Read: Was sieht ein Betrachter beim ganz schnellen Blick ZUERST? "
                    "Nur das offensichtlich Sichtbare beschreiben, noch keine Deutung."
    )
    spontane_bedeutung: str = Field(
        description="Was bedeutet dieses Motiv OHNE jede Erklärung und OHNE die Headline - die erste, "
                    "naheliegendste Assoziation eines normalen Betrachters? Ehrlich, nicht die "
                    "gewünschte Wunsch-Deutung."
    )
    kernbotschaft_bruecke: Literal["direkt", "teilweise", "nein"] = Field(
        description="Führt die spontane_bedeutung DIREKT zur Kernaussage des Posts? 'direkt' = ohne "
                    "gedanklichen Umweg. 'teilweise' = die Verbindung ist da, aber man muss einen "
                    "Schritt selbst ergänzen. 'nein' = es braucht eine konstruierte Erklärung, die ein "
                    "normaler Betrachter nie hätte. Eine erst nachträglich erklärbare Metapher ist "
                    "NICHT 'direkt'."
    )
    fehlinterpretations_risiko: Literal["niedrig", "mittel", "hoch"] = Field(
        description="Wie hoch ist das Risiko, dass das Motiv spontan ETWAS ANDERES bedeutet als die "
                    "Kernaussage? 'hoch', wenn eine andere naheliegende Deutung mindestens ebenso "
                    "plausibel ist wie die gewünschte - INSBESONDERE, wenn die Bildwelt eine starke, "
                    "allgemein bekannte oder fachlich naheliegende Bedeutung aktiviert, die nicht zur "
                    "Kernaussage gehört (z.B. ein Umfeld, das im Steuer-/Finanzkontext sofort ein "
                    "ANDERES Thema auslöst). Nicht als 'gering' schönreden, egal wie clever die "
                    "geplante Metapher klingt."
    )

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
    """Verdict der Concept Jury - Bewertung aller 5 Routen + Gewinner."""

    # Bewertungen aller 5 Routen
    evaluation_1: RouteEvaluation = Field(description="Bewertung Route 1 (Emotionale Szene)")
    evaluation_2: RouteEvaluation = Field(description="Bewertung Route 2 (Metapher)")
    evaluation_3: RouteEvaluation = Field(description="Bewertung Route 3 (Objekt)")
    evaluation_4: RouteEvaluation = Field(description="Bewertung Route 4 (Kontrast)")
    evaluation_5: RouteEvaluation = Field(description="Bewertung Route 5 (Unkonventionell)")

    # Gewinner
    winning_route: Literal[1, 2, 3, 4, 5] = Field(
        description="Nummer der gewinnenden Route (1-5)"
    )
    winning_score: float = Field(
        ge=1.0, le=10.0,
        description="Score der gewinnenden Route"
    )
    winning_titel: str = Field(description="Titel der gewinnenden Route")

    # Begründung für Auswahl
    begruendung: str = Field(
        description="Warum diese Route gewonnen hat, in 2-3 Sätzen - FAKTISCH über den Semantic "
                    "Bridge Test, NICHT im Marketing-Ton: Was sieht man zuerst, was bedeutet es "
                    "spontan, wie führt das zur Kernbotschaft, und warum ist das "
                    "Fehlinterpretationsrisiko vertretbar. KEINE Pitch-Floskeln wie 'starke "
                    "Markenpassung', 'emotionale Wirkung', 'ideal für Awareness', 'kanalfähiges Paket'."
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
# Angepasst 2026-08-11: scroll_stop_potenzial + originalitaet hoeher gewichtet,
# umsetzbarkeit + zielgruppenrelevanz reduziert - diese beiden Kriterien werteten mutige/
# originelle Konzepte am haeufigsten ab (siehe PROMPT_CHANGELOG.md).
# Angepasst 2026-08-25: emotionale_wirkung 0.10 -> 0.15, originalitaet 0.20 -> 0.15. Die alte
# Gewichtung (Scroll-Stop 25% + Originalitaet 20% = 45%) hat abstrakte Transformationen/Symbole
# systematisch ueber warme, echte, menschliche Szenen gestellt - genau die Drift, die weg von den
# starken fruehen Motiven (warme Familienszene, echtes Objekt) fuehrte. Emotionale Wirkung hebt
# warm-echt-konkrete Routen; Originalitaet bleibt wichtig, dominiert aber nicht mehr.
_GEWICHTE = {
    "botschaftsklarheit": 0.20,
    "scroll_stop_potenzial": 0.25,
    "markenpassung": 0.15,
    "originalitaet": 0.15,
    "umsetzbarkeit": 0.05,
    "emotionale_wirkung": 0.15,
    "zielgruppenrelevanz": 0.05,
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


def _botschaftsklarheit_cap(evaluation: "RouteEvaluation") -> float:
    """Harter Deckel fuer die Botschaftsklarheit, abgeleitet aus den strukturierten Pruef-Feldern
    (Semantik-Check). Verhindert, dass ein starker Hook fehlende Bildsemantik ueberdeckt:
    - Bruecke 'nein'  ODER Risiko 'hoch'   -> max 4
    - Bruecke 'teilweise' ODER Risiko 'mittel' -> max 6
    - Bruecke 'direkt' UND Risiko 'niedrig'    -> 10 (kein Deckel)
    """
    bruecke = getattr(evaluation, "kernbotschaft_bruecke", "direkt")
    risiko = getattr(evaluation, "fehlinterpretations_risiko", "niedrig")
    if bruecke == "nein" or risiko == "hoch":
        return 4.0
    if bruecke == "teilweise" or risiko == "mittel":
        return 6.0
    return 10.0


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
        5: verdict.evaluation_5,
    }

    # HARTES SEMANTIK-GATE: Botschaftsklarheit code-seitig deckeln, damit die Jury ihre eigene
    # Bruecken-/Risiko-Einschaetzung NICHT durch einen hohen Message-Score ueberstimmen kann.
    for evaluation in evaluations.values():
        cap = _botschaftsklarheit_cap(evaluation)
        if evaluation.botschaftsklarheit > cap:
            evaluation.botschaftsklarheit = cap

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

    # Fallback: Beste Route auch wenn < MINDEST_SCORE (besser als Fehler!)
    if verdict.quality_warning:
        log.warning(
            "Gewinner-Route hat Score %.2f < MINDEST_SCORE %.1f - beste verfügbare Route wird trotzdem verwendet. "
            "Qualitätskontrolle empfohlen!", gewinner.gesamtscore, MINDEST_SCORE
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EVALUATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def evaluate_routes(
    brief: MessageBrief,
    territories: CreativeTerritories,
    model: str = "gpt-5-nano",
    recent_heroes: "list[str] | None" = None,
    recent_environments: "list[str] | None" = None
) -> ConceptJuryVerdict:
    """Bewertet 5 kreative Routen und wählt die beste aus.

    Die Concept Jury bewertet jede Route nach 7 gewichteten Kriterien:
    - Botschaftsklarheit (20%)
    - Scroll-Stop-Potenzial (25%)
    - Markenpassung (15%)
    - Originalität (15%)
    - Umsetzbarkeit (5%)
    - Emotionale Wirkung (15%)
    - Zielgruppenrelevanz (5%)

    Mindestwert für Gewinner: 7.0/10

    Args:
        brief: Message Brief (Kontext für Bewertung)
        territories: 5 kreative Routen vom Creative Director
        model: OpenAI-Modell (default: gpt-5-nano - günstiges Modell für Bewertungsaufgabe)

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
        ("Route 5: Unkonventionell", territories.route_5_unkonventionell),
    ]

    # System-Prompt: Concept Jury Rolle
    system_prompt = """Du bist eine Concept Jury für Social-Media-Marketing.
Deine Aufgabe: Bewerte 5 kreative Routen objektiv und wähle die beste aus.

Kontext:
- HILO ist eine Hilfsorganisation für Lohnsteuerhilfe
- Marke: Vertrauenswürdig, professionell, aber NICHT langweilig
- Zielgruppe: siehe Message Brief im User-Prompt - die dort genannte KONKRETE Zielgruppe ist
  maßgeblich für das Kriterium "Zielgruppenrelevanz", nicht eine pauschale Annahme
- Ziel: Scroll-Stop-Potenzial + Markenpassung

SEMANTIK-CHECK - ZUERST je Route ausfüllen (Prüfmodus, NICHT Pitch - keine Marketing-Vorteile
aufzählen, sondern ehrlich prüfen, ob die Bedeutung wirklich ankommt):
1. read_500ms: Was sieht ein UNVORBEREITETER Betrachter zuerst? Nur Sichtbares, keine Interpretation.
2. spontane_bedeutung: Was ist OHNE Headline und OHNE Konzeptbeschreibung die wahrscheinlichste ERSTE
   Bedeutung des Motivs? Die naheliegendste, nicht die gewünschte.
3. kernbotschaft_bruecke: Führt diese spontane Bedeutung DIREKT zur Kernaussage? -> direkt / teilweise
   / nein. Eine erst nachträglich erklärbare Metapher gilt NICHT als "direkt".
4. fehlinterpretations_risiko: niedrig / mittel / hoch. "hoch", wenn eine andere naheliegende Deutung
   mindestens ebenso plausibel ist wie die gewünschte - insbesondere wenn die Bildwelt eine starke,
   allgemein bekannte oder fachlich naheliegende Bedeutung aktiviert, die nicht zur Kernaussage gehört.
5. Serienähnlichkeit: Prüfe Hero-Kategorie UND übergeordnete Bedeutungswelt. Technisch verschiedene
   Motive aus derselben visuellen oder semantischen Familie sind KEINE echte Vielfalt.

Grundregeln dabei: Du kennst Thema, Route und Absicht - der Facebook-Nutzer kennt NUR das Bild.
Bewerte, was das Motiv TATSÄCHLICH kommuniziert, nicht was der Creative Director sagen wollte. Nutze
Routenname, Begründung oder geplante Metapher NIEMALS als Beweis, dass eine Bedeutung sichtbar ist.
Erfinde keine nicht sichtbaren Elemente oder Beziehungen. Wenn du die Bedeutung erst ausführlich
erklären musst, ist sie nicht intuitiv. VISUAL ≠ MESSAGE: ein spektakulärer Hook (Scroll-Stop) darf
fehlende Botschaftsklarheit NICHT kompensieren - beide sind unabhängig.

SCORE-KOPPLUNG (Botschaftsklarheit) - das System deckelt dies zusätzlich HART code-seitig:
- direkte Brücke + niedriges Risiko  -> 7-10 möglich
- teilweise Brücke ODER mittleres Risiko -> max. 6
- Brücke "nein" ODER hohes Risiko -> max. 4

Bewertungskriterien (Skala 1-10):

1. **Botschaftsklarheit (20%)**: Ist die BEABSICHTIGTE Bedeutung sofort erkennbar?
   Dieser Score folgt direkt aus dem SEMANTIK-CHECK oben (kernbotschaft_bruecke + fehlinterpretations_
   risiko) - siehe SCORE-KOPPLUNG; das System deckelt ihn zusätzlich hart. Ein Mehrzweck-Symbol, das
   genauso gut für ein anderes Thema stehen könnte, ist NICHT klar - auch wenn es selbst eindeutig
   aussieht. Die Headline soll die visuelle Idee präzisieren, nicht erst erklären müssen.
   - 9-10: Kristallklar, unmissverständlich - kaum plausible Alternativ-Deutungen zum
     konkreten Thema.
   - 7-8: Klar erkennbar, aber ein bis zwei naheliegende Alternativ-Deutungen denkbar.
   - 5-6: Etwas unklar, muss nachdenken - mehrere ähnlich plausible Deutungen möglich.
   - 1-4: Verwirrend, unklar - das Motiv könnte für fast jedes Thema derselben Kategorie stehen.

2. **Scroll-Stop-Potenzial (25%)**: Fällt das Bild im Feed auf?
   Bewerte NICHT einfach, ob das Bild bunt, groß, kontrastreich oder attraktiv wäre - bewerte die
   STÄRKE DER ZUGRUNDE LIEGENDEN VISUELLEN IDEE (siehe VISUELLE ÜBERSETZUNG/ONE-IDEA-TEST im
   Creative-Director-Prompt). Ein riesiges rotes Element oder eine aggressive Signalfarbe
   erhalten NICHT automatisch einen hohen Score - frage: Ist die IDEE auffällig, oder
   hauptsächlich Farbe/Größe?
   - 9-10: Das Motiv funktioniert bereits als kleines Thumbnail OHNE Text UND ohne aggressive
     Signalfarbe. Ein dominanter visueller Gedanke erzeugt innerhalb von <1 Sekunde Neugier,
     Überraschung oder Spannung - headline_dependency ist dabei meist 'low'. GENAUSO stark ist ein
     warmer, echter menschlicher Moment oder ein real fotografiertes Objekt in kräftigem Licht, das
     sofort Nähe und Interesse erzeugt - Scroll-Stop entsteht nicht nur durch abstrakte Überraschung,
     sondern ebenso durch echte emotionale Sogwirkung. Beides verdient hier 9-10.
   - 7-8: Klarer visueller Hook, aber für vollständiges Verständnis wird die Headline teilweise
     benötigt (headline_dependency 'medium').
   - 5-6: Professionell und attraktiv, aber überwiegend thematische Illustration oder bekanntes
     Symbol - im Feed erwartbar, nichts das man zweimal ansieht.
   - 3-4: Typisches Stock-/Corporate-/Steuer-Motiv, austauschbares Alltagsobjekt
     (headline_dependency 'high' ist hier ein starkes Warnsignal).
   - 1-2: Visuell austauschbar oder ohne dominanten Focal Point.
   - ACHTUNG Requisiten-Häufung: Mehrere kleine, gleichrangige Objekte (+ Mini-Beschriftungen
     darauf) in einer Szene wirken im Thumbnail unruhig statt eines klaren Eyecatchers - werte
     das ab, auch wenn jedes Einzelteil für sich passend ist. Ein einzelnes, mutig
     inszeniertes Element schlägt eine Ansammlung von Requisiten.

3. **Markenpassung (15%)**: Passt es zur HILO-Marke?
   - 9-10: Perfekt: vertrauenswürdig UND interessant
   - 7-8: Gut, passt
   - 5-6: Etwas off-brand
   - 1-4: Passt nicht zur Marke
   - WICHTIG: "Vertrauenswürdig" heißt NICHT "brav". Auffällige, kontraststarke oder
     ungewöhnliche Konzepte NICHT abwerten, nur weil sie mutig sind - werte nur ab, wenn es
     reißerisch wird oder die Seriosität eines Lohnsteuerhilfevereins beschädigt.
   - Warme, echte Fotografie - ein ehrlicher menschlicher Moment oder ein greifbares Objekt in
     echtem, warmem Licht - ist besonders markentypisch für HILO (nahbar, seriös, menschlich) und
     soll hier hoch bewertet werden. Ein flaches, kühl-grafisches Symbol auf einfarbiger Fläche ist
     dagegen weniger markentypisch.

4. **Originalität (15%)**: Hebt sich das Konzept ab?
   - 9-10: Echte Transformation, überraschende Kombination oder visuelle Analogie trägt die
     Aussage (siehe VISUELLE ÜBERSETZUNG im Creative-Director-Prompt) - völlig neu, unerwartet.
   - 7-8: Eigenständige Interpretation des Themas, vermeidet Klischees.
   - 5-6: Passendes Symbol, aber wenig Transformation - der Gegenstand aus dem Thema wird
     erkennbar, aber kaum verändert/neu kombiniert.
   - 1-4: Ein Gegenstand aus dem Thema wird lediglich abgebildet (Stock-Klischee) - keine
     eigenständige visuelle Idee, nur Illustration eines Begriffs.
   - HINWEIS: Originalität heißt NICHT zwingend abstrakte Transformation. Auch ein frischer, echter
     menschlicher Moment oder eine ungewöhnlich ehrliche, warme Alltagsszene, wie man sie im
     Steuer-Umfeld selten sieht, ist eine eigenständige Idee und verdient 7-8+. Werte eine warme,
     echte Szene NICHT automatisch als "wenig Transformation" ab - Klischee meint die gestellte
     Stockfoto-Pose, nicht einen authentisch eingefangenen Moment.

5. **Umsetzbarkeit (5%)**: Kann man das realistisch umsetzen?
   - 9-10: Einfach umsetzbar
   - 7-8: Machbar mit Standard-Tools
   - 5-6: Herausfordernd
   - 1-4: Unrealistisch

6. **Emotionale Wirkung (15%)**: Erzeugt es die gewünschte Emotion?
   - 9-10: Starke emotionale Resonanz
   - 7-8: Emotion erkennbar
   - 5-6: Etwas flach
   - 1-4: Keine emotionale Wirkung

7. **Zielgruppenrelevanz (5%)**: Spricht es die Zielgruppe an?
   - 9-10: Perfekt auf Zielgruppe zugeschnitten
   - 7-8: Passt zur Zielgruppe
   - 5-6: Etwas daneben
   - 1-4: Verfehlt Zielgruppe

**Gesamtscore Berechnung:**
Der gewichtete Gesamtscore und die Auswahl des Gewinners werden VOM SYSTEM berechnet
(Gewichte: Botschaftsklarheit 20%, Scroll-Stop 25%, Markenpassung 15%, Originalität 15%,
Umsetzbarkeit 5%, Emotionale Wirkung 15%, Zielgruppenrelevanz 5%).
Du musst NICHT rechnen - konzentriere dich auf präzise Einzelbewertungen (1-10) und gute
Begründungen. Deine Angaben zu gesamtscore/winning_route werden überschrieben.

**Mindestwert für Gewinner: 7.0/10**

Wichtig:
- Sei kritisch aber fair
- Begründe deine Bewertungen
- Der beste ist nicht immer der "sicherste" - Originalität zählt!
- Aber: Markenpassung ist wichtig (keine wilden Experimente)
- SIGNALFARBEN (Rot, Orange, Neon o.ä.): erlaubt, wenn semantisch begründet (z.B. Warnung/
  Risiko-Thema), aber KEIN Ersatz für eine starke visuelle Idee - eine Route, deren Scroll-Stop
  hauptsächlich aus einer auffälligen Farbe statt aus der Idee selbst kommt, gehört unter
  Scroll-Stop-Potenzial UND Originalität abgewertet, nicht nur toleriert.
"""

    # User-Prompt: Routes + Message Brief
    routes_text = "\n\n".join([
        f"**{name}**\n"
        f"Titel: {route.titel}\n"
        f"Typ: {route.typ}\n"
        f"Beschreibung: {route.beschreibung}\n"
        f"Visuelle Signatur: {route.visuelle_signatur}\n"
        f"Emotion: {route.emotionale_richtung}\n"
        f"Beispiel: {route.beispiel_szene}\n"
        f"Scroll-Stop-Device: {route.scroll_stop_device}\n"
        f"Hero-Kategorie: {route.hero_kurz}\n"
        f"Bedeutungswelt: {route.semantic_environment}\n"
        f"Headline-Abhängigkeit: {route.headline_dependency}"
        for name, route in routes
    ])

    # Serien-Vielfalt: zuletzt genutzte Hero-Kategorien (aus der Creative Memory) - dienen
    # ausschliesslich der Novelty-Abwertung in der Jury, werden NICHT dem Creative Director gezeigt.
    recent_heroes = [h for h in (recent_heroes or []) if h and h.strip()]
    recent_environments = [e for e in (recent_environments or []) if e and e.strip()]
    if recent_heroes or recent_environments:
        teile = ["\n\n**SERIEN-VIELFALT (Novelty-Prüfung):**"]
        if recent_heroes:
            teile.append("Zuletzt verwendete Hero-Kategorien (neueste zuletzt):\n- "
                         + "\n- ".join(recent_heroes))
        if recent_environments:
            teile.append("Zuletzt verwendete Bedeutungswelten/Umfelder (neueste zuletzt):\n- "
                         + "\n- ".join(recent_environments))
        teile.append(
            "Werte eine Route bei Originalität UND Scroll-Stop-Potenzial DEUTLICH ab (etwa 2-3 Punkte), "
            "wenn ihre Hero-Kategorie ODER ihre Bedeutungswelt einer der obigen entspricht oder sehr "
            "ähnlich ist. WICHTIG: Die Bedeutungswelt zählt besonders - mehrere technisch verschiedene "
            "Motive aus DERSELBEN Welt (z.B. Fahrrad, Bahnhof, Auto, Straße = alles 'Pendeln/Mobilität') "
            "sind KEINE echte Abwechslung, sondern Wiederholung. Ziel ist Vielfalt auch auf Bedeutungs"
            "ebene. Eine inhaltlich klar bessere Route darf trotzdem gewinnen; die Abwertung greift bei "
            "annähernd gleichwertigen."
        )
        novelty_block = "\n".join(teile)
    else:
        novelty_block = ""

    user_prompt = f"""Bewerte diese 5 kreativen Routen und wähle die beste aus.

**Message Brief (Kontext):**
- Kernaussage: {brief.kernaussage}
- Nutzen: {brief.nutzen}
- Zielgruppe: {brief.zielgruppe}
- Reaktion: {brief.reaktion}
- Funnel-Stufe: {brief.funnel_stufe}
- Kanal: {brief.kanal}

**5 Kreative Routen:**

{routes_text}
{novelty_block}

Bewerte jede Route nach den 7 Kriterien (1-10).
Begründe Stärken und Schwächen je Route.
Der gewichtete Gesamtscore und der Gewinner werden vom System berechnet - du musst nicht rechnen.
"""

    log.info(f"Concept Jury bewertet 5 Routen für: {brief.kernaussage}")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=ConceptJuryVerdict
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
        print("Schritt 1: Creative Director generiert 5 Routen...")
        territories = generate_creative_routes(brief)

        print("✓ 5 Routen generiert:")
        print(f"  1. {territories.route_1_emotionale_szene.titel}")
        print(f"  2. {territories.route_2_metapher.titel}")
        print(f"  3. {territories.route_3_objekt.titel}")
        print(f"  4. {territories.route_4_kontrast.titel}")
        print(f"  5. {territories.route_5_unkonventionell.titel}\n")

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
