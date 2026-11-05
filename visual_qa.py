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
- Concept Fidelity (ist die geplante Idee im Bild sichtbar umgesetzt?)

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
        description="Sind die Logo-Schutzzonen (unten links, unten rechts) frei von wichtigen Bildinhalten?"
    )
    scroll_stop_wirkung: float = Field(
        ge=1.0, le=10.0, default=5.0,
        description="Wuerde DIESES tatsaechlich generierte Bild im Feed auffallen - unabhaengig von "
                    "der Headline? Prueft, ob das bei der Jury bewertete Scroll-Stop-Potenzial (das "
                    "auf der TEXT-Beschreibung der Route beruhte, bevor das Bild existierte) im "
                    "fertigen Bild wirklich ankommt. WICHTIG: Grosse Schrift, aggressive Farbe oder "
                    "hoher Kontrast allein rechtfertigen KEINEN hohen Score - bewerte die Staerke der "
                    "visuellen IDEE, nicht ob das Bild bunt/grell ist."
    )
    composition_integrity: float = Field(
        ge=1.0, le=10.0, default=5.0,
        description="Bilden Hero-Element, Schrift und Gesamtkomposition eine gemeinsame, durchdachte "
                    "Gestaltung? Hoher Score: die Schrift steht klar und gut lesbar DIREKT auf einem "
                    "ruhigen Bildbereich, harmonisch in die Komposition eingebettet (Platzierung, "
                    "Farb-/Kontrastbezug zur Szene) - OHNE aufgesetzte farbige Textplatte/Kasten. "
                    "Niedriger Score: eine aufgesetzte farbige Platte/ein Kasten hinter der Schrift "
                    "(wirkt wie ein Werbe-Template ueber ein beliebiges Foto gelegt) ODER Schrift "
                    "unruhig/schlecht lesbar ohne Bezug zum Motiv."
    )
    concept_fidelity: float = Field(
        ge=1.0, le=10.0, default=5.0,
        description="Hat das TATSAECHLICH erzeugte Bild die zentrale Mechanik der geplanten Idee "
                    "(die 'Erwartungen' im User-Prompt: Route, Focal Point, Scroll-Stop-Device) "
                    "SICHTBAR umgesetzt? Bewerte NUR, was im Bild wirklich zu sehen ist - nicht, was "
                    "Art Direction oder Prompt beabsichtigt haben. Fehlt die zentrale Transformation/"
                    "Handlung/semantische Mechanik oder ist sie nur schwach angedeutet, ist dieser "
                    "Score niedrig (1-5), auch wenn das Bild handwerklich schoen ist."
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

    # ─────────────────────────────────────────────────────────────────────────
    # RECHTLICHES AUSSCHLUSSKRITERIUM (unabhaengig von Ueberschrift/Score)
    # ─────────────────────────────────────────────────────────────────────────

    enthaelt_fremdes_kennzeichen: bool = Field(
        default=False,
        description="Zeigt das Bild ein echtes oder eindeutig erkennbares staatliches Hoheitszeichen "
                     "(Bundesadler, Bundeswehr-/Polizei-/Zoll-/Behörden-Abzeichen, Wappen, Dienstsiegel) "
                     "ODER ein echtes Institutions-/Marken-Logo (z.B. 'Agentur für Arbeit', Banken, "
                     "Versicherungen, andere Firmen/Organisationen außer HILO)? Auch stilisierte/"
                     "angedeutete Nachbildungen zählen. HARTES AUSSCHLUSSKRITERIUM - True führt IMMER "
                     "zur Ablehnung, unabhängig vom Score."
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
    "scroll_stop_wirkung",
    "composition_integrity",
    "concept_fidelity",
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

    # Hartes Ausschlusskriterium: Hoheitszeichen oder fremdes Logo im Bild (rechtliches Risiko)
    if verdict.enthaelt_fremdes_kennzeichen:
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
    model: str = "gpt-5.6-terra",
    kampagne: str = "steuer"
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
   - GLEICHZEITIG gilt: Der bevorzugte HILO-Look ist warme, helle, echte Fotografie (ein ehrlicher
     menschlicher Moment oder ein greifbares Objekt in warmem Tageslicht). Ein warmes, ruhiges,
     echt wirkendes Foto ist genauso markentypisch wie ein kontraststarkes und darf NICHT
     abgewertet werden, nur weil es nicht dramatisch/dunkel ist. Warme, echte, konkrete Motive
     (Mensch/Objekt) und abstrakte grafische Ideen sind gleichwertig - ein flaches, kühl-grafisches
     Symbol auf einfarbiger Fläche ist eher weniger markentypisch. HILO-Grün wirkt als gezielter
     Akzent, nicht als große grafische Fläche.
   - SIGNALFARBEN (Rot, Orange, Neon o.ä.): bei Warnungs-/Risiko-Themen erlaubt, aber die
     HILO-Farbdramaturgie (Navy/Grün) muss weiterhin spürbar bleiben - eine Signalfarbe, die
     Navy/Grün komplett verdrängt, drückt diesen Score.
   - Vermeiden: reißerisch, unseriös, steril

5. **Technische Qualität? (1-10)**
   - Bildqualität okay?
   - Keine Artefakte, strange Proportionen?
   - Bei Personen: anatomisch korrekt? (Hände, Finger, Gliedmaßen)
   - enthaelt_fremdes_kennzeichen: Zeigt das Bild ein echtes oder eindeutig erkennbares
     staatliches Hoheitszeichen (Bundesadler, Bundeswehr-/Polizei-/Zoll-/Behörden-Abzeichen,
     Wappen, Dienstsiegel) ODER ein echtes Institutions-/Marken-Logo (z.B. "Agentur für
     Arbeit", Banken, Versicherungen, andere Firmen/Organisationen außer HILO)? Auch
     stilisierte/angedeutete Nachbildungen zählen als True. HARTES AUSSCHLUSSKRITERIUM -
     unabhängig vom Score, führt IMMER zur Ablehnung. Prüfe das besonders bei Uniform-/
     Behörden-/Bank-Motiven genau (Schulterklappen, Briefköpfe, Umschlag-Absender, Kragenspiegel).

6. **Schutzzonen frei? (1-10)**
   - Die Logo-Kreise werden später unten links und unten rechts platziert
   - Sind diese Ecken (je ca. 22% Bildbreite × 28% Bildhöhe) frei von wichtigen Bildinhalten?
   - Ragt kein Gesicht, keine Hand, kein zentrales Objekt hinein?

7. **Scroll-Stop-Wirkung? (1-10)**
   - Würde DIESES tatsächlich generierte Bild im Feed auffallen - unabhängig von der Headline?
   - Die Jury hat das Scroll-Stop-Potenzial bereits anhand der TEXT-Beschreibung der Route
     bewertet, BEVOR das Bild existierte. Hier wird geprüft, ob es im fertigen Bild ankommt.
   - THUMBNAIL-TEST: Wäre die Leitidee auch bei ca. 180×180 Pixel (kleine Feed-Vorschau)
     sofort verständlich und visuell dominant? Braucht es feine Details oder kleine Requisiten,
     um die Idee zu verstehen? Dann ist der Score niedriger.
   - WICHTIG: Große Schrift, aggressive Farbe oder hoher Kontrast allein rechtfertigen KEINEN
     hohen Score - frage, ob die zugrunde liegende visuelle IDEE auffällig ist, nicht nur ihre
     Farbe/Größe. Ein großes rotes Element ist nicht automatisch ein starker Scroll-Stop.
   - 9-10: Funktioniert bereits als Thumbnail ohne Text, erzeugt sofort Neugier/Überraschung -
     durch die IDEE, nicht nur durch Farbe/Größe.
   - 5-6: Professionell, aber im Feed erwartbar.
   - 1-4: Visuell austauschbar, kein dominanter Reiz.

8. **Composition Integrity? (1-10)**
   - Bilden Hero-Element, Schrift und Gesamtkomposition eine gemeinsame, durchdachte
     Gestaltung - oder wirkt das Ergebnis wie ein aufgesetztes Werbe-Template?
   - 9-10: Die Schrift steht klar und gut lesbar DIREKT auf einem ruhigen Bildbereich und ist
     harmonisch in die Komposition eingebettet (Platzierung, Farb-/Kontrastbezug zur Szene, Text
     folgt der Bildkomposition) - OHNE aufgesetzte farbige Textplatte/Kasten dahinter.
   - 5-6: Ordentlich, aber nicht besonders verzahnt - Text und Foto koexistieren neutral.
   - 1-4: Eine aufgesetzte farbige Textplatte/ein Kasten hinter der Schrift (wirkt wie ein
     Werbe-Template über ein beliebiges Foto gelegt) ODER gar keine erkennbare Verzahnung
     zwischen Schrift und Motiv.

9. **Concept Fidelity? (1-10) - prüft Umsetzung gegen Absicht**
   - Hat das TATSÄCHLICH erzeugte Bild die zentrale Mechanik der geplanten Idee (siehe
     "Erwartungen" im User-Prompt: Route, Focal Point, Scroll-Stop-Device) SICHTBAR umgesetzt?
   - Bewerte NUR das Sichtbare, nicht die Absicht. Beispiel: Wenn geplant war "Papier rollt sich
     zurück / Zeit läuft rückwärts", im Bild aber nur "eine Rolle mit aufgedruckten Zahlen" zu
     sehen ist (ohne erkennbare Rückwärts-/Rückspul-Mechanik), dann ist die zentrale Idee NICHT
     umgesetzt.
   - 9-10: die entscheidende Transformation/Handlung/Mechanik ist klar und eindeutig sichtbar.
   - 5-6: angedeutet, aber nicht überzeugend umgesetzt.
   - 1-4: die zentrale Mechanik fehlt; das Bild zeigt etwas Vageres/anderes als geplant.
   - REGEL: "Leitidee erkennbar" (1) und "Scroll-Stop-Wirkung" (7) dürfen NICHT höher sein als die
     Concept Fidelity - alle drei bewerten das SICHTBARE Ergebnis, nicht die geplante Idee. Eine
     gute Idee, die das Bild nicht sichtbar umsetzt, ist IM BILD keine gute Idee. Begründe die
     Creative-Qualität also nie mit der Absicht der Art Direction, sondern nur mit dem, was da ist.

10. **Überschrift (nur wenn im User-Prompt eine Überschrift vorgegeben ist!)**
   - headline_vorhanden (1-10): Ist die Überschrift im Bild sichtbar und prominent?
   - headline_lesbar (1-10): Auf dem Smartphone gut lesbar? Groß genug, genug Kontrast,
     nicht vom Motiv überlagert oder angeschnitten? Die Schrift soll DIREKT auf dem Bild stehen -
     Navy (#1f428d) auf hellem Grund, Weiß auf dunklem/kräftigem Grund, je nach Lesbarkeit. Ein
     dezenter Schatten/Halo für Kontrast ist in Ordnung. Eine aufgesetzte farbige Platte/Tafel/
     ein Banner hinter dem Text ist NICHT erwünscht und drückt den Score (die klare, plattenfreie
     Schrift direkt auf einem ruhigen Bildbereich ist der Soll-Zustand).
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
- Erkennbares staatliches Hoheitszeichen oder fremdes Institutions-/Marken-Logo → IMMER abgelehnt

Sei kritisch aber fair!
Wichtig: Bewerte NUR die Einzelkriterien (1-10). Gesamtscore und Freigabe werden vom System
berechnet - du musst nicht rechnen.
"""

    # Headline-Block nur einfügen, wenn eine Überschrift ins Bild gerendert werden sollte
    mit_headline = bool(headline and headline.strip())
    if mit_headline:
        headline_block = (
            "9. ÜBERSCHRIFT - die folgende Überschrift sollte im Bild stehen:\n"
            f'   >>> {headline.strip()} <<<\n'
            "   - headline_vorhanden: sichtbar und prominent?\n"
            "   - headline_lesbar: auf dem Smartphone gut lesbar?\n"
            "   - gefundener_text: tippe den im Bild lesbaren Text EXAKT ab (Fehler NICHT korrigieren!)\n"
            "   - headline_text_exakt: stimmt er zeichengenau mit der Vorgabe überein? "
            "(Umlaute, Buchstabendreher, Zusatzwörter - im Zweifel false)"
        )
    else:
        headline_block = (
            "9. ÜBERSCHRIFT: Es wurde KEINE Überschrift vorgegeben - die Headline-Felder sind "
            "nicht relevant (Standardwerte belassen). Im Bild sollte dann auch kein Text stehen."
        )

    # User-Prompt
    user_prompt = f"""Prüfe dieses Rohmotiv (Gate A):

**Kontext:**
- Kernaussage: {brief.kernaussage}
- Route: {route.typ} - {route.titel}
- Gewünschte Emotion: {art_board.emotionaler_moment}

**Erwartungen (die GEPLANTE Idee - fuer die Concept-Fidelity-Pruefung):**
- Geplante Leitidee/Mechanik: {route.beschreibung}
- Geplantes Scroll-Stop-Device: {route.scroll_stop_device}
- Focal Point: {art_board.focal_point} ({art_board.focal_point_position})
- Negativraum: {art_board.negativraum_text}
- Atmosphäre: {art_board.atmosphaere}

Bewerte (1-10):
1. Leitidee erkennbar?
2. Focal Point vollständig?
3. Textzonen nutzbar?
4. Markenpassung (HILO: warm, professionell, persönlich - auffällig/kontraststark ist ERWÜNSCHT)?
5. Technische Qualität (inkl. Anatomie bei Personen, KEINE Hoheitszeichen/fremden Logos)?
6. Schutzzonen unten links + unten rechts frei (je ca. 22% × 28%)?
7. Scroll-Stop-Wirkung (Thumbnail-Test: sofort verständlich/dominant auch bei ca. 180×180px; Farbe/Größe allein zählt nicht, die IDEE muss auffallen)?
8. Composition Integrity (wirkt Text+Motiv wie EINE Gestaltung, oder wie 'Foto + Textkasten + Logo'?)
9. Concept Fidelity (ist die zentrale MECHANIK der geplanten Idee oben im Bild WIRKLICH sichtbar umgesetzt? Nur das Sichtbare zählt, nicht die Absicht; Leitidee und Scroll-Stop nicht höher als dieser Wert)

{headline_block}

Gib nur die Einzelbewertungen an - Gesamtscore und Freigabe berechnet das System.
"""

    import campaigns
    _cmp = campaigns.get(kampagne)
    if _cmp:
        system_prompt = system_prompt + getattr(_cmp, "QA_HINT", "")

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
