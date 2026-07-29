#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-Stufen-Workflow für automatisierte Kampagnen-Generierung mit Qualitätskontrolle.

Workflow:
1. GPT-5.6 Terra: Kampagnenplanung (Structured Output)
2. GPT Image 2: Grafik-Generierung (2048x2048, high quality)
3. GPT-5.6 Terra: Qualitätskontrolle (automatische Retry bei Fehlern)

Basiert auf ChatGPT-Feedback vom 2026-07-29.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from config import DATA_DIR
from secrets_store import get_secret

log = logging.getLogger("hilo.kampagne")


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
# STRUCTURED OUTPUT MODELS (Pydantic)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CampaignPlan(BaseModel):
    """Kampagnenplan von GPT-5.6 Terra (Stufe 1).

    Structured Output mit allen notwendigen Informationen für die Grafik-Generierung.
    """
    core_message: str = Field(description="Kernaussage des Steuertexts in einem Satz")
    target_emotion: str = Field(description="Ziel-Emotion (z.B. Optimismus, Vertrauen, Erleichterung)")

    headline: str = Field(max_length=55, description="Prägnante Überschrift (max. 55 Zeichen)")
    supporting_points: list[str] = Field(
        min_length=2,
        max_length=3,
        description="2-3 kurze Infopunkte (je max. 45 Zeichen)"
    )
    cta: str = Field(max_length=35, description="Call-to-Action (max. 35 Zeichen)")
    caption: str = Field(description="Begleittext für Social Media (150-200 Wörter, mit Hook und Interaktionsfrage)")

    visual_strategy: str = Field(description="Gewählte Bildstrategie (z.B. Editorial Photography, Still Life)")
    visual_concept: str = Field(description="Beschreibung des visuellen Konzepts")
    hero_element: str = Field(description="Dominantes Hauptelement im Bild")
    layout: str = Field(description="Layout-Beschreibung (z.B. 'Text links, Motiv rechts')")
    background: str = Field(description="Hintergrund-Beschreibung")
    text_contrast: str = Field(description="Farbkontrast für Text (z.B. 'Navy auf hell')")
    accent_usage: str = Field(description="Verwendung der Akzentfarben")

    image_prompt: str = Field(description="Vollständiger englischer Prompt für GPT Image 2")


class QualityReview(BaseModel):
    """Qualitätsprüfung von GPT-5.6 Terra (Stufe 3).

    Prüft das generierte Bild auf Korrektheit, Lesbarkeit und fachliche Übereinstimmung.
    """
    approved: bool = Field(description="True = Bild freigegeben, False = Neu generieren")

    text_is_exact: bool = Field(description="Alle Texte exakt wie vorgegeben?")
    spelling_is_correct: bool = Field(description="Deutsche Rechtschreibung korrekt?")
    all_text_is_readable: bool = Field(description="Alle Texte gut lesbar?")
    message_matches_article: bool = Field(description="Aussage entspricht dem Steuertext?")
    layout_is_professional: bool = Field(description="Layout professionell?")

    problems: list[str] = Field(description="Liste gefundener Probleme")
    correction_instruction: str = Field(description="Anweisung zur Korrektur (falls approved=False)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CREATIVE DIRECTOR SYSTEMPROMPT (Stufe 1)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CREATIVE_DIRECTOR_PROMPT = """Du bist Creative Director, Senior Art Director und Werbetexter für HILO,
einen deutschen Lohnsteuerhilfeverein.

Entwickle aus dem gelieferten Steuertext eine vollständige Social-Media-Kampagne,
die ohne manuelle Nachbearbeitung durch GPT Image 2 umgesetzt werden kann.

ANALYSE

Ermittle:
1. die wichtigste fachliche Aussage
2. den konkreten Nutzen für Arbeitnehmer oder Rentner
3. die geeignete emotionale Wirkung
4. eine innerhalb von drei Sekunden verständliche Bildidee

TEXTERSTELLUNG

Erstelle:
- eine prägnante deutsche Headline mit höchstens 55 Zeichen
- zwei oder drei kurze Infopunkte mit jeweils höchstens 45 Zeichen
- einen kurzen Call-to-Action

Alle Aussagen müssen fachlich vom Eingabetext gedeckt sein.
Erfinde keine Beträge, Fristen, Voraussetzungen oder Rechtsfolgen.
Nicht gendern.

CAPTION (BEGLEITTEXT)

Erstelle einen deutschen Begleittext für Social Media (150-200 Wörter):

AUFBAU:
- HOOK (erster Satz, max. 10 Wörter): überraschend, direkt, neugierig machend
- INHALT: Erkläre das Thema knapp, nutzenorientiert, ohne Fachchinesisch
- INTERAKTIONSFRAGE: Stelle VOR dem Handlungsaufruf eine kurze Frage
- HANDLUNGSAUFRUF: Weise auf HILO-Beratung hin

STIL:
- Durchgehend SIE-Form (gesiezt, nie geduzt)
- Klar, direkt, menschlich (nicht belehrend)
- Echte UTF-8 Umlaute (ä, ö, ü, ß)
- KEINE Abkürzungen (z.B. → zum Beispiel)
- Sparsam mit Emojis (max. 2)
- 4-5 thematisch passende Hashtags, #HILO als letzten

WICHTIG:
- Nutze WENN MÖGLICH einen konkreten Fakt, Frist oder Urteil aus dem Eingabetext
- Nenne Quellen als TEXT ("Laut Bundesfinanzhof..."), KEINE Links
- Erfinde KEINE Fakten, Urteile, Beträge oder Fristen
- KEINE URLs im Text (werden automatisch ergänzt)

KREATIVKONZEPT

Entwickle intern drei deutlich unterschiedliche Bildideen.
Wähle anschließend die stärkste Idee nach:
- sofortiger Verständlichkeit
- Originalität
- Kampagnenwirkung
- Umsetzbarkeit mit integrierter Typografie
- Eignung für HILO

Bevorzuge je nach Thema:
- Editorial Photography
- Concept Photography
- Still Life
- Flat Lay
- authentische Lifestyle-Fotografie
- Editorial Illustration
- Ligne-Claire-Comic
- moderne 3D-Illustration

Verwende eine Infografik nur, wenn ein Ablauf oder Vergleich im Mittelpunkt steht.

GESTALTUNG

Die Anzeige muss als vollständige quadratische Werbegrafik funktionieren.

Sie benötigt:
- ein dominantes Hero-Element
- eine klare Blickführung
- einen ruhigen und gut lesbaren Textbereich
- eine eindeutige Hierarchie aus Headline, Infopunkten und CTA
- hohe Lesbarkeit auf Smartphones
- großzügige Abstände
- eine hochwertige, moderne Werbeästhetik

HILO-Farben:
- Navy: #1a3a6b
- Grün: #4a8c5c
- Lavendelblau: #b8c8e8
- Weiß: #ffffff

Nutze die Farben kontrolliert und hochwertig.

VERMEIDEN

- generische Businesspersonen
- gestellte Stockfoto-Posen
- übertriebenes Lächeln
- Geldregen
- übergroße Eurozeichen
- das Wort "HILO" in der Typografie
- zusätzliche Logos
- QR-Codes
- Wasserzeichen
- erfundene Texte

BILDPROMPT

Formuliere abschließend einen vollständigen englischen Produktionsprompt
für das Bildmodell.

CONCEPT LOCK

Das zuvor ausgewählte Kreativkonzept ist verbindlich und darf im Bildprompt
nicht verändert, uminterpretiert oder durch eine offensichtlichere Bildidee
ersetzt werden.

Der Bildprompt muss:

- exakt das ausgewählte Hauptmotiv beschreiben
- alle im Kreativkonzept genannten Kernelemente ausdrücklich aufführen
- die festgelegte Bildart verbindlich nennen
- unerwünschte Alternativmotive ausdrücklich ausschließen
- deutlich zwischen dem visuellen Motiv und dem Inhalt des Anzeigentextes unterscheiden

Der Steuertext darf ausschließlich die Typografie und die fachliche Botschaft
bestimmen. Er darf nicht zu einer neuen oder abweichenden Bildidee führen.

Wenn beispielsweise ein Still-Life gewählt wurde:

- dürfen keine Personen dargestellt werden
- darf nicht zu Lifestyle-Fotografie gewechselt werden
- darf keine Feier- oder Beratungsszene entstehen
- muss das Still-Life das dominante und klar erkennbare Hauptmotiv bleiben

Der englische Bildprompt muss mit diesem Block beginnen:

"MANDATORY VISUAL CONCEPT — DO NOT REINTERPRET:
[präzise Beschreibung des ausgewählten Kreativkonzepts]

The following visual concept is locked. Do not replace it with a different
scene, a more literal interpretation of the copy, or a lifestyle photograph."

Danach muss der Bildprompt getrennte Abschnitte enthalten:

1. MANDATORY VISUAL CONCEPT
2. REQUIRED OBJECTS
3. FORBIDDEN VISUAL ALTERNATIVES
4. COMPOSITION
5. EXACT TEXT
6. TYPOGRAPHY
7. BRAND COLOURS
8. CORNER SAFE ZONES
9. FINAL VALIDATION

REQUIRED OBJECTS

Führe alle zwingend sichtbaren Gegenstände als eindeutige Liste auf.
Das Bild ist ungültig, wenn eines dieser Elemente fehlt.

FORBIDDEN VISUAL ALTERNATIVES

Nenne alle Motive, die nicht entstehen dürfen, insbesondere solche,
die sich aus einer zu wörtlichen Interpretation des Steuertextes ergeben.

EXACT TEXT

Alle gelieferten Texte müssen exakt, vollständig und nur einmal erscheinen.
Keine zusätzlichen Wörter.
Keine Umformulierungen.
Keine erfundenen Texte.
Deutsche Rechtschreibung muss exakt eingehalten werden.

CORNER SAFE ZONES

Halte alle vier Ecken vollständig frei.

Definiere in jeder Ecke eine leere Sicherheitszone von mindestens
12 % der Bildbreite und 12 % der Bildhöhe.

In diesen Sicherheitszonen dürfen keinerlei Texte, Personen, Gegenstände,
Dekorationen, Schatten, Muster oder andere wichtige Bildelemente erscheinen.

FINAL VALIDATION

Der Bildprompt muss das Bildmodell abschließend anweisen, vor der Ausgabe
intern zu kontrollieren:

- Entspricht das Bild exakt dem gesperrten Kreativkonzept?
- Sind alle erforderlichen Gegenstände sichtbar?
- Wurden sämtliche verbotenen Alternativmotive vermieden?
- Sind alle Texte exakt geschrieben?
- Sind alle vier Ecken vollständig frei?

Wenn eine Bedingung nicht erfüllt ist, muss die Komposition vor der Ausgabe
korrigiert werden.

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STUFE 1: KAMPAGNENPLANUNG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_campaign_plan(
    article: str,
    cta: str = "Jetzt Termin vereinbaren",
    channel: str = "Instagram und Facebook",
    format_size: str = "1080x1080",
) -> CampaignPlan:
    """Stufe 1: Kampagnenplanung mit GPT-5.6 Terra.

    Args:
        article: Vollständiger Steuertext oder Newslettertext
        cta: Gewünschter Call-to-Action
        channel: Ziel-Kanal (für Kontext)
        format_size: Bildformat

    Returns:
        CampaignPlan mit allen Kampagnen-Details inkl. image_prompt

    Raises:
        ValueError: Wenn Artikel leer ist
        RuntimeError: Wenn kein Plan erzeugt wurde
    """
    if not article or not article.strip():
        raise ValueError("Artikel darf nicht leer sein!")

    client = _get_client()
    log.info("Stufe 1: Kampagnenplanung wird erstellt...")

    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",  # Terra-Version wie von Catrin angewiesen!
        messages=[
            {
                "role": "system",
                "content": CREATIVE_DIRECTOR_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"STEUERTEXT:\n{article}\n\n"
                    f"GEWÜNSCHTER CTA:\n{cta}\n\n"
                    f"FORMAT: {format_size}, quadratisch\n"
                    f"KANAL: {channel}"
                ),
            },
        ],
        response_format=CampaignPlan,
    )

    plan = response.choices[0].message.parsed

    if plan is None:
        raise RuntimeError("Es wurde kein Kampagnenplan erzeugt.")

    log.info("Stufe 1: Kampagnenplan erstellt - Headline: %s", plan.headline)
    return plan


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STUFE 2: GRAFIK-GENERIERUNG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_advertisement(
    image_prompt: str,
    output_path: Optional[str] = None,
    size: Literal["1024x1024", "2048x2048"] = "2048x2048",
    quality: Literal["low", "medium", "high", "auto"] = "high",
) -> Path:
    """Stufe 2: Grafik-Generierung mit GPT Image 2.

    Args:
        image_prompt: Vollständiger Prompt von create_campaign_plan()
        output_path: Optional: Ziel-Pfad (Standard: auto-generiert)
        size: Bildgröße (1024x1024 für Tests, 2048x2048 für Produktion)
        quality: Qualitätsstufe (low für Tests, high für Produktion)

    Returns:
        Path zum gespeicherten PNG

    Raises:
        RuntimeError: Wenn keine Bilddaten zurückkamen
    """
    client = _get_client()
    log.info("Stufe 2: Grafik wird generiert (size=%s, quality=%s)...", size, quality)

    result = client.images.generate(
        model="gpt-image-2",
        prompt=image_prompt,
        size=size,
        quality=quality,
        output_format="png",
    )

    image_base64 = result.data[0].b64_json

    if not image_base64:
        raise RuntimeError("Das Bildmodell lieferte keine Bilddaten.")

    # Auto-generiere Pfad falls nicht angegeben
    if not output_path:
        import time
        timestamp = int(time.time())
        output_path = os.path.join(DATA_DIR, "kampagne", f"campaign_{timestamp}.png")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    path = Path(output_path)
    path.write_bytes(base64.b64decode(image_base64))

    log.info("Stufe 2: Grafik gespeichert unter %s", path)
    return path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STUFE 3: QUALITÄTSKONTROLLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


QA_PROMPT = """Du bist Qualitätskontrolleur für HILO Social-Media-Werbeanzeigen.

Prüfe das generierte Bild auf:

1. TEXTGENAUIGKEIT: Sind alle Texte (Headline, Infopunkte, CTA) EXAKT wie vorgegeben?
   Keine Tippfehler, keine fehlenden Buchstaben, keine zusätzlichen Wörter?

2. RECHTSCHREIBUNG: Ist die deutsche Rechtschreibung perfekt?

3. LESBARKEIT: Sind alle Texte auf einem Smartphone (6 Zoll) SCHARF und KLAR LESBAR?
   - Schriftgröße NIEMALS unter 28pt
   - ALLE Texte müssen DEUTLICH erkennbar sein
   - Bei unscharfen oder zu kleinen Texten: approved = False!

4. TEXT-KONTRAST: Ist der Text GEGEN DEN HINTERGRUND KLAR LESBAR?
   - Text muss SCHARFEN Kontrast haben (hell auf dunkel ODER dunkel auf hell)
   - KEINE grauen, blassen oder schlecht lesbaren Texte
   - KEINE Texte über komplexen Mustern ohne Hintergrund-Box
   - Bei schlechtem Kontrast: approved = False!

5. FACHLICHE ÜBEREINSTIMMUNG: Entspricht die Aussage dem Originaltext?

6. LAYOUT: Wirkt das Layout professionell und hochwertig?

Bei JEDEM Problem: approved = False!

Beispiele für Problems:
- "Im zweiten Infopunkt steht 'sic' statt 'sich'"
- "Das Wort 'HILO' erscheint im Bild (sollte nicht sein)"
- "CTA-Text ist nicht vollständig"
- "Headline hat einen Tippfehler"

Gib ausschließlich die verlangte strukturierte Ausgabe zurück."""


def quality_check(
    image_path: Path,
    plan: CampaignPlan,
    article: str,
) -> QualityReview:
    """Stufe 3: Qualitätskontrolle mit GPT-5.6 Terra (multimodal).

    Args:
        image_path: Pfad zum generierten Bild
        plan: Kampagnenplan mit erwarteten Texten
        article: Original-Steuertext

    Returns:
        QualityReview mit Prüfergebnis

    Raises:
        RuntimeError: Wenn keine Review erzeugt wurde
    """
    client = _get_client()
    log.info("Stufe 3: Qualitätskontrolle wird durchgeführt...")

    # Bild als Base64 laden
    image_data = image_path.read_bytes()
    image_base64 = base64.b64encode(image_data).decode("utf-8")

    # Erwartete Texte zusammenstellen
    expected_texts = f"""ERWARTETE TEXTE:

Headline: {plan.headline}

Infopunkte:
{chr(10).join("• " + p for p in plan.supporting_points)}

CTA: {plan.cta}

ORIGINALTEXT:
{article[:500]}"""

    response = client.beta.chat.completions.parse(
        model="gpt-5.6-terra",  # Terra für multimodales QA
        messages=[
            {
                "role": "system",
                "content": QA_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": expected_texts},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        },
                    },
                ],
            },
        ],
        response_format=QualityReview,
    )

    review = response.choices[0].message.parsed

    if review is None:
        raise RuntimeError("Es wurde keine Qualitätsprüfung erzeugt.")

    if review.approved:
        log.info("Stufe 3: Bild FREIGEGEBEN ✅")
    else:
        log.warning("Stufe 3: Bild ABGELEHNT ❌ - Probleme: %s", ", ".join(review.problems))

    return review


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KOMPLETTER WORKFLOW MIT RETRY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_campaign(
    article: str,
    cta: str = "Jetzt Termin vereinbaren",
    output_path: Optional[str] = None,
    max_retries: int = 3,
    test_mode: bool = False,
) -> tuple[CampaignPlan, Path, QualityReview]:
    """Kompletter 3-Stufen-Workflow mit automatischer Retry-Logik.

    Args:
        article: Vollständiger Steuertext
        cta: Call-to-Action
        output_path: Optional: Ziel-Pfad für finale Grafik
        max_retries: Maximale Anzahl Neugenerierungen bei QA-Fehlern
        test_mode: True = low quality für Tests, False = high quality für Produktion

    Returns:
        (CampaignPlan, finale_image_path, QualityReview)

    Raises:
        RuntimeError: Wenn nach max_retries immer noch Fehler
    """
    log.info("━━━━ 3-STUFEN-WORKFLOW GESTARTET ━━━━")

    # Stufe 1: Kampagnenplanung (nur einmal!)
    plan = create_campaign_plan(article, cta=cta)

    # Stufe 2 + 3: Grafik + QA (mit Retry)
    size = "1024x1024" if test_mode else "2048x2048"
    quality = "low" if test_mode else "high"

    # Kampagne-Verzeichnis erstellen (falls noch nicht vorhanden)
    kampagne_dir = os.path.join(DATA_DIR, "kampagne")
    os.makedirs(kampagne_dir, exist_ok=True)

    for attempt in range(1, max_retries + 1):
        log.info("━━━━ VERSUCH %d/%d ━━━━", attempt, max_retries)

        try:
            # Stufe 2: Grafik generieren
            temp_path = os.path.join(
                kampagne_dir, f"attempt_{attempt}.png"
            ) if not output_path else output_path

            image_path = generate_advertisement(
                plan.image_prompt,
                output_path=temp_path,
                size=size,
                quality=quality,
            )

            # Stufe 3: QA
            review = quality_check(image_path, plan, article)

            if review.approved:
                log.info("━━━━ WORKFLOW ERFOLGREICH NACH %d VERSUCH(EN) ━━━━", attempt)
                return plan, image_path, review

            if attempt < max_retries:
                log.info("Versuch %d: Bild abgelehnt, neuer Versuch...", attempt)
            else:
                log.warning("Alle Versuche fehlgeschlagen! Probleme: %s", ", ".join(review.problems))
                # Bild trotzdem zurückgeben für manuelle Prüfung
                return plan, image_path, review

        except Exception as e:
            log.warning("Versuch %d fehlgeschlagen (Exception): %s", attempt, e)
            if attempt < max_retries:
                continue
            else:
                raise RuntimeError(
                    f"Alle {max_retries} Versuche fehlgeschlagen! Letzte Exception: {e}"
                ) from e

    # Sollte nie erreicht werden
    raise RuntimeError("Workflow-Logik-Fehler")


def regenerate_image_with_qa(
    image_prompt: str,
    headline: str,
    supporting_points: list[str],
    cta: str,
    article_excerpt: str = "",
    output_path: Optional[str] = None,
    max_retries: int = 3,
    test_mode: bool = False,
) -> tuple[Path, QualityReview]:
    """Nur Stufe 2 + 3: Bild neu generieren mit QA (OHNE Kampagnenplanung).

    Für "neues Foto würfeln" im Dashboard - verwendet bestehenden image_prompt
    statt neue Kampagnenplanung zu machen.

    Args:
        image_prompt: Bestehender englischer Prompt für GPT Image 2
        headline: Erwartete Headline (für QA)
        supporting_points: Erwartete Infopunkte (für QA)
        cta: Erwarteter CTA (für QA)
        article_excerpt: Optionaler Artikel-Auszug (für QA-Kontext)
        output_path: Optionaler Ausgabepfad für das Bild
        max_retries: Maximale Anzahl Versuche bei QA-Ablehnung
        test_mode: True = low quality für Tests

    Returns:
        Tuple von (image_path, review)

    Raises:
        RuntimeError: Wenn alle Versuche fehlschlagen
    """
    import time

    # Kampagne-Verzeichnis erstellen (falls noch nicht vorhanden)
    kampagne_dir = os.path.join(DATA_DIR, "kampagne")
    os.makedirs(kampagne_dir, exist_ok=True)

    # Bildgröße und Qualität
    size = "1024x1024" if test_mode else "2048x2048"
    quality = "low" if test_mode else "high"

    # Mini-Plan für QA (ohne vollständige Kampagnenplanung)
    from types import SimpleNamespace
    mini_plan = SimpleNamespace(
        headline=headline,
        supporting_points=supporting_points,
        cta=cta,
        core_message="",  # Nicht verfügbar bei Regeneration
    )

    for attempt in range(1, max_retries + 1):
        log.info("━━━━ BILD-REGENERIERUNG: VERSUCH %d/%d ━━━━", attempt, max_retries)

        try:
            # Stufe 2: Grafik generieren
            temp_path = os.path.join(
                kampagne_dir, f"regen_{int(time.time())}_{attempt}.png"
            ) if not output_path else output_path

            image_path = generate_advertisement(
                image_prompt,
                output_path=temp_path,
                size=size,
                quality=quality,
            )

            # Stufe 3: QA
            review = quality_check(image_path, mini_plan, article_excerpt or headline)

            if review.approved:
                log.info("Bild-Regenerierung erfolgreich nach %d Versuch(en) ✅", attempt)
                return image_path, review
            else:
                log.info(
                    "Versuch %d: Bild abgelehnt - Probleme: %s",
                    attempt,
                    ", ".join(review.problems)
                )
                if attempt < max_retries:
                    continue
                else:
                    log.warning(
                        "Alle %d Versuche fehlgeschlagen! Letzte Probleme: %s",
                        max_retries,
                        ", ".join(review.problems)
                    )
                    # Gib das letzte Bild zurück, auch wenn nicht approved
                    return image_path, review

        except Exception as e:
            log.warning("Versuch %d fehlgeschlagen (Exception): %s", attempt, e)
            if attempt < max_retries:
                continue
            else:
                raise RuntimeError(f"Alle {max_retries} Versuche fehlgeschlagen!") from e

    # Sollte nie erreicht werden
    raise RuntimeError("Regenerierung-Logik-Fehler")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI FÜR TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Test-Artikel
    test_article = """
    Kosten für einen beruflich veranlassten Umzug können unter bestimmten
    Voraussetzungen als Werbungskosten berücksichtigt werden. Neben
    nachgewiesenen Einzelkosten kommen gegebenenfalls Umzugskostenpauschalen
    in Betracht. Belege sollten sorgfältig aufbewahrt werden.
    """

    print("\n" + "="*80)
    print("3-STUFEN-WORKFLOW TEST")
    print("="*80 + "\n")

    try:
        plan, image_path, review = run_campaign(
            test_article,
            cta="Jetzt Beratungsstelle finden",
            test_mode=True,  # Low-Quality für Tests
        )

        print("\n✅ KAMPAGNE ERSTELLT!\n")
        print(f"Headline: {plan.headline}")
        print(f"Infopunkte: {', '.join(plan.supporting_points)}")
        print(f"Bild: {image_path}")
        print(f"QA-Status: {'FREIGEGEBEN ✅' if review.approved else 'ABGELEHNT ❌'}")

        if not review.approved:
            print(f"Probleme: {', '.join(review.problems)}")

    except Exception as e:
        log.error("Workflow fehlgeschlagen: %s", e, exc_info=True)
        sys.exit(1)
