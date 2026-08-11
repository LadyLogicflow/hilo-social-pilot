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
    schutzzonen_frei: float = Field(
        ge=1.0, le=10.0, default=10.0,
        description="Sind die Logo-Schutzzonen (unten links, oben rechts) frei von wichtigen Bildinhalten?"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ÜBERSCHRIFT (nur relevant, wenn eine Überschrift ins Bild gerendert wurde)
    # ─────────────────────────────────────────────────────────────────────────

    headline_vorhanden: float = Field(
        ge=1.0, le=10.0, default=10.0,
        description="Ist die vorgegebene Überschrift im Bild sichtbar und prominent?"
    )
    headline_lesbar: float = Field(
        ge=1.0, le=10.0, default=10.0,
        description="Ist die Überschrift auf einem Smartphone gut lesbar (Größe, Kontrast, keine Überlappung)?"
    )
    headline_text_exakt: bool = Field(
        default=True,
        description="Stimmt der Text im Bild ZEICHENGENAU mit der Vorgabe überein (inkl. Umlaute, "
                     "keine Buchstabendreher, keine erfundenen Zusatzwörter)? HARTES AUSSCHLUSSKRITERIUM."
    )
    gefundener_text: str = Field(
        default="",
        description="Der im Bild tatsächlich lesbare Überschriften-Text (exakt abgetippt, für Diagnose)"
    )

    # Gesamtscore (wird CODE-seitig berechnet, nicht vom LLM - siehe _compute_score())
    gesamtscore: float = Field(ge=1.0, le=10.0, description="Durchschnitt aller Bewertungen")

    # Verdict (wird CODE-seitig gesetzt, nicht vom LLM)
    freigegeben: bool = Field(description="True = freigegeben (Score >= 8.0), False = abgelehnt")

    # Feedback
    staerken: str = Field(description="Was ist gut?")
    schwaechen: str = Field(description="Was könnte besser sein?")
    empfehlung: str = Field(description="Freigeben oder neu generieren?")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCORE-BERECHNUNG (code-seitig, nicht vom LLM)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FREIGABE_SCHWELLE = 8.0

_QA_KRITERIEN = (
    "leitidee_erkennbar",
    "focal_point_vollstaendig",
    "textzonen_nutzbar",
    "markenpassung",
    "technische_qualitaet",
    "schutzzonen_frei",
)

# Zusaetzliche Kriterien, die nur zaehlen, wenn eine Überschrift ins Bild gerendert wurde
_QA_KRITERIEN_HEADLINE = (
    "headline_vorhanden",
    "headline_lesbar",
)


def _compute_qa_score(verdict: "VisualQAVerdict", mit_headline: bool = False) -> None:
    """Berechnet Gesamtscore + Freigabe CODE-seitig und ueberschreibt die LLM-Werte.

    #Rechen-Fix: Vorher hat das LLM den Durchschnitt selbst gebildet und 'freigegeben' selbst
    gesetzt - LLMs rechnen unzuverlaessig, und die Freigabe ist eine Gate-Entscheidung, die
    deterministisch sein muss. Das LLM liefert jetzt nur noch die Einzelbewertungen.

    #Headline-Gate: Wurde eine Überschrift ins Bild gerendert, zaehlen Sichtbarkeit und
    Lesbarkeit in den Score - und ein zeichengenau falscher Text (Buchstabendreher, fehlende
    Umlaute) fuehrt IMMER zur Ablehnung, unabhaengig vom Score. Bildmodelle verschreiben sich
    bei Text; ohne dieses Gate wuerde das erst im veroeffentlichten Post auffallen.
    """
    kriterien = _QA_KRITERIEN + (_QA_KRITERIEN_HEADLINE if mit_headline else ())
    werte = [getattr(verdict, k) for k in kriterien]
    verdict.gesamtscore = round(sum(werte) / len(werte), 2)
    verdict.freigegeben = verdict.gesamtscore >= FREIGABE_SCHWELLE

    # Hartes Ausschlusskriterium: falsch geschriebene Überschrift
    if mit_headline and not verdict.headline_text_exakt:
        verdict.freigegeben = False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# QA DIRECTOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def check_raw_image(
    image: Image.Image,
    brief: MessageBrief,
    route: CreativeRoute,
    art_board: ArtDirectionBoard,
    headline: str = "",
    model: str = "gpt-5.6-terra"
) -> VisualQAVerdict:
    """Gate A: Prüft das generierte Motiv (inkl. eingebrannter Überschrift).

    Args:
        image: PIL.Image - Das generierte Motiv
        brief: Message Brief (Kontext)
        route: Gewinnende Route
        art_board: Art Direction Board
        headline: Die Überschrift, die ins Bild gerendert werden sollte. Wird sie übergeben,
            prüft die QA zusätzlich Sichtbarkeit, Lesbarkeit und ZEICHENGENAUE Schreibweise -
            ein falsch geschriebener Text führt immer zur Ablehnung.
        model: OpenAI-Modell mit Vision (default: gpt-5.6-terra)

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
   - WICHTIG: "Vertrauenswürdig" heißt NICHT "brav" oder "gedämpft". Kräftiger Kontrast, satte
     Farbakzente, ungewöhnliche Perspektiven und ein deutlicher Scroll-Stop-Moment sind
     ERWÜNSCHT und dürfen NICHT abgewertet werden - sie sind bewusste Vorgabe der Art Direction.
     Werte nur ab, wenn das Bild reißerisch/effekthascherisch wirkt oder die Seriosität eines
     Lohnsteuerhilfevereins beschädigt - nicht, weil es auffällig ist.
   - Vermeiden: reißerisch, unseriös, steril

5. **Technische Qualität? (1-10)**
   - Bildqualität okay?
   - Keine Artefakte, strange Proportionen?
   - Bei Personen: anatomisch korrekt? (Hände, Finger, Gliedmaßen)

6. **Schutzzonen frei? (1-10)**
   - Die Logo-Kreise werden später unten links und oben rechts platziert
   - Sind diese Ecken (je ca. 22% Bildbreite × 28% Bildhöhe) frei von wichtigen Bildinhalten?
   - Ragt kein Gesicht, keine Hand, kein zentrales Objekt hinein?

7. **Überschrift (nur wenn im User-Prompt eine Überschrift vorgegeben ist!)**
   - headline_vorhanden (1-10): Ist die Überschrift im Bild sichtbar und prominent?
   - headline_lesbar (1-10): Auf dem Smartphone gut lesbar? Groß genug, genug Kontrast,
     nicht vom Motiv überlagert oder angeschnitten? Falls eine eigene Fläche/Tafel/Banner hinter
     dem Text liegt: ist diese Fläche in HILO-Farben (Navy #1f428d oder Grün #60a33c, mit weißer
     Schrift) oder Weiß mit Navy-Schrift? Eine willkürliche neutrale Farbe (Creme/Beige/Grau/
     Pastell) für diese Fläche ist ein Lesbarkeits-Trick ohne Markenwirkung und drückt den Score.
   - gefundener_text: Tippe den im Bild lesbaren Überschriften-Text EXAKT ab, so wie er
     dasteht - inklusive eventueller Fehler. Nicht korrigieren, nicht glätten!
   - headline_text_exakt (true/false): Stimmt der abgetippte Text ZEICHENGENAU mit der Vorgabe
     überein? Prüfe besonders: Umlaute (ä/ö/ü/ß), Buchstabendreher, fehlende oder doppelte
     Buchstaben, erfundene Zusatzwörter, englische Wörter. Im Zweifel false.
     ACHTUNG: Bildmodelle verschreiben sich bei Text häufig - das ist der wichtigste Check.

**Freigabe-Regel:**
- Gesamtscore >= 8.0 → Freigegeben
- Gesamtscore < 8.0 → Abgelehnt (neu generieren)
- Falsch geschriebene Überschrift → IMMER abgelehnt

Sei kritisch aber fair!
Wichtig: Bewerte NUR die Einzelkriterien (1-10). Gesamtscore und Freigabe werden vom System
berechnet - du musst nicht rechnen.
"""

    # Headline-Block nur einfügen, wenn eine Überschrift ins Bild gerendert werden sollte
    mit_headline = bool(headline and headline.strip())
    if mit_headline:
        headline_block = (
            "7. ÜBERSCHRIFT - die folgende Überschrift sollte im Bild stehen:\n"
            f'   >>> {headline.strip()} <<<\n'
            "   - headline_vorhanden: sichtbar und prominent?\n"
            "   - headline_lesbar: auf dem Smartphone gut lesbar?\n"
            "   - gefundener_text: tippe den im Bild lesbaren Text EXAKT ab (Fehler NICHT korrigieren!)\n"
            "   - headline_text_exakt: stimmt er zeichengenau mit der Vorgabe überein? "
            "(Umlaute, Buchstabendreher, Zusatzwörter - im Zweifel false)"
        )
    else:
        headline_block = (
            "7. ÜBERSCHRIFT: Es wurde KEINE Überschrift vorgegeben - die Headline-Felder sind "
            "nicht relevant (Standardwerte belassen). Im Bild sollte dann auch kein Text stehen."
        )

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
4. Markenpassung (HILO: warm, professionell, persönlich - auffällig/kontraststark ist ERWÜNSCHT)?
5. Technische Qualität (inkl. Anatomie bei Personen)?
6. Schutzzonen unten links + oben rechts frei (je ca. 22% × 28%)?

{headline_block}

Gib nur die Einzelbewertungen an - Gesamtscore und Freigabe berechnet das System.
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
            response_format=VisualQAVerdict
        )

        verdict = completion.choices[0].message.parsed

        if not verdict:
            raise Exception("OpenAI API gab kein valides QA Verdict zurück")

        # Gesamtscore + Freigabe code-seitig berechnen (LLM-Werte werden überschrieben)
        _compute_qa_score(verdict, mit_headline=mit_headline)

        if mit_headline and not verdict.headline_text_exakt:
            log.warning(
                "⚠️ Überschrift im Bild weicht ab! Soll: '%s' | Gelesen: '%s' -> ABGELEHNT",
                headline.strip(), verdict.gefundener_text
            )

        log.info(
            f"✓ Visual QA Verdict:\n"
            f"   Gesamtscore: {verdict.gesamtscore:.1f}/10 (berechnet)\n"
            f"   Überschrift exakt: {'Ja' if not mit_headline or verdict.headline_text_exakt else 'NEIN'}\n"
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
