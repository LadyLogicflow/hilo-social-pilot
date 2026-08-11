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
        description="Wen spricht dieser Post KONKRET an? Keine pauschale Kategorie wie "
                     "'Arbeitnehmer' oder 'Steuerzahler', sondern die spezifische Gruppe, die "
                     "wirklich vom Thema betroffen ist - inkl. Altersbereich oder Lebenssituation, "
                     "wo das den Personenkreis eingrenzt. Beispiele: 'Berufstätige ab 40 mit "
                     "pflegebedürftigen Angehörigen' (bei Pflegethemen), 'Eltern von Kindern im "
                     "Kita-/Grundschulalter' (bei Kinderbetreuungskosten), 'Berufstätige "
                     "Pendler:innen, keine Rentner' (bei Fahrtkosten/Werbungskosten), "
                     "'Rentner:innen ohne bisherige Steuererklärung' (bei Rentenbesteuerung), "
                     "'Auszubildende, meist unter 25' (bei Ausbildungskosten/erstem Steuerjahr), "
                     "'Alleinstehende ohne Kinder' (bei Themen, die sich von Familien-/"
                     "Paar-Konstellationen unterscheiden, z.B. Grundfreibetrag, Steuerklasse 1)."
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
    model: str = "gpt-5.6-terra"
) -> MessageBrief:
    """Generiert automatisch ein Message Brief aus Post-Daten via KI.

    Args:
        stream: Content-Stream ('radar', 'fristen', 'anlass', 'wissen')
        thema: Thema/Überschrift des Posts
        text: Post-Text/Beschreibung
        kanal: Social-Media-Kanal ('Facebook', 'Instagram', 'LinkedIn', 'Google Business')
        model: OpenAI-Modell (default: gpt-5.6-terra - das Brief ist die Grundlage für alle
            nachfolgenden Pipeline-Stufen, insbesondere die Zielgruppen-Ableitung; ein schwaches
            Modell hier pflanzt sich durch die gesamte Pipeline fort)

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
- Content-Streams:
  * 'radar': Aktuelle News/Gesetzesänderungen → meist Awareness
  * 'fristen': Wichtige Termine/Deadlines → meist Decision
  * 'anlass': Saisonale Themen (Jahresende, Steuererklärung) → meist Awareness
  * 'wissen': Erklärungen/Tutorials → meist Consideration

Wichtig:
- Kernaussage: Klar und prägnant (1-2 Sätze)
- Nutzen: Konkret, nicht generisch ("Verspätungszuschlag vermeiden" statt "gut informiert sein")
- Reaktion: Realistisch (meist "Termin buchen", "Frist merken", "Artikel lesen")
- Funnel-Stufe: Logisch aus Stream ableiten, aber flexibel

KERNAUSSAGE NICHT AUF "GELD SPAREN" PLATTDRÜCKEN (WICHTIG!):

Sehr viele HILO-Themen haben irgendwo einen Geld-/Steuervorteil - das macht "Geld sparen" oder
"Steuervorteil nutzen" zur bequemsten, aber am wenigsten hilfreichen Kernaussage. Sie liefert der
Bildregie keinen Ansatzpunkt außer generischen Geld-/Euro-Symbolen, die sich über fast jedes
Thema stülpen lassen und dadurch austauschbar wirken. Suche stattdessen den SPEZIFISCHSTEN,
überraschendsten Aufhänger im Text - meist eine konkrete Unterscheidung, Bedingung oder ein
Detail, das die eigentliche Story ist:
- "Unterhaltspflicht bei eigenen Eltern ja, bei Schwiegereltern rechtlich NICHT" ist die Story,
  nicht "man kann Geld absetzen" - die rechtliche Unterscheidung ist der Aufhänger.
- "Erholungsbeihilfe gilt auch für Ehegatte und Kinder, nicht nur den Arbeitnehmer selbst" ist
  die Story, nicht "es gibt einen Steuervorteil beim Gehalt".
Die Geld-Ebene ist fast immer der Hintergrund, nicht die eigentliche Nachricht - die Kernaussage
sollte den konkreten Twist/die konkrete Bedingung benennen, nicht nur "spart Steuern".
ZIELGRUPPE - PRÄZISE ABLEITEN (WICHTIG!):

"Arbeitnehmer und Rentner" oder "Steuerzahler" ist KEINE brauchbare Zielgruppe - das trifft auf
fast jeden Post zu und hilft der Bildregie nicht. Leite stattdessen die tatsächlich betroffene
Gruppe aus dem konkreten Thema ab, so eng wie das Thema es hergibt. Prüfe dabei:
- Lebenssituation/Alter: Wer hat dieses Problem typischerweise? (z.B. Pflege → Menschen ab
  etwa 40, oft mit alternden Eltern; Kinderbetreuungskosten → Eltern mit Kindern im
  Betreuungs-/Grundschulalter, nicht Eltern erwachsener Kinder)
- Erwerbsstatus: Betrifft es nur Erwerbstätige (z.B. Fahrtkosten/Werbungskosten,
  Homeoffice-Pauschale - hier sind Rentner explizit AUSGESCHLOSSEN) oder nur Rentner
  (z.B. Rentenbesteuerung) oder beide?
- Familiensituation: Singles, Familien, Alleinerziehende - wenn das Thema danach unterscheidet

Beispiele guter Zielgruppen-Ableitung:
- "Pflegegrad als Steuerabzug" → "Berufstätige ab ca. 40 mit pflegebedürftigen Angehörigen"
- "Kinderbetreuungskosten absetzen" → "Eltern von Kindern im Kita-/Grundschulalter"
- "Fahrtkosten als Werbungskosten" → "Berufstätige Pendler:innen (nicht Rentner)"
- "Rentenbesteuerung 2026" → "Rentner:innen, insbesondere Neurentner:innen"
- "Homeoffice-Pauschale" → "Angestellte im Homeoffice, aktuell erwerbstätig"
- "Erste Steuererklärung als Azubi" → "Auszubildende, meist unter 25"
- "Grundfreibetrag/Steuerklasse 1" → "Alleinstehende ohne Kinder"

Wenn das Thema wirklich alle gleichermaßen betrifft (z.B. allgemeine Fristerinnerung ohne
inhaltliche Einschränkung), ist eine breitere Zielgruppe in Ordnung - aber das ist die Ausnahme,
nicht der Standardfall.
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
- zielgruppe: Wen spricht das KONKRET an? (Alter/Lebenssituation/Erwerbsstatus, wenn das Thema
  danach unterscheidet - keine pauschale Kategorie wie "Steuerzahler" oder "Arbeitnehmer")
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
            response_format=MessageBrief
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
# HEADLINE-FALLBACK (wenn kein Copywriter-Text vorliegt)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GeneratedHeadline(BaseModel):
    """Selbst generierte Bild-Überschrift (Fallback, wenn keine freigegebene vorliegt)."""

    headline: str = Field(
        max_length=55,
        description="Prägnante deutsche Überschrift für das Bild (max. 55 Zeichen). Kurz genug, "
                     "um im Bild groß und auf dem Smartphone lesbar dargestellt zu werden."
    )


def generate_headline(brief: MessageBrief, text: str = "", model: str = "gpt-5.6-terra") -> str:
    """Erzeugt eine Bild-Überschrift, wenn keine freigegebene Überschrift vorliegt.

    #Headline-Fallback: Ohne Überschrift laeuft der Image Producer im Modus 'no_text' und
    erzeugt ein Bild komplett ohne Text - fuer einen Social-Media-Post meist unbrauchbar.

    WICHTIG - rechtliche Sorgfalt: Die Überschrift darf ausschliesslich Aussagen enthalten, die
    durch Kernaussage/Quelltext gedeckt sind. Betraege, Fristen, Prozentsaetze und Rechtsfolgen
    duerfen NICHT erfunden oder gerundet werden. Liegt eine vom Copywriter freigegebene
    Überschrift vor, ist diese IMMER vorzuziehen.

    Args:
        brief: Message Brief (Kernaussage, Nutzen, Zielgruppe)
        text: Optionaler Original-Posttext als Faktenbasis
        model: OpenAI-Modell (default: gpt-5.6-terra)

    Returns:
        str: Überschrift (max. 55 Zeichen)

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern
    """
    client = _get_client()

    system_prompt = """Du bist Werbetexter für HILO, einen deutschen Lohnsteuerhilfeverein.
Deine Aufgabe: Eine einzige, prägnante Überschrift für ein Social-Media-Bild.

REGELN:
- MAXIMAL 55 Zeichen (sie wird gross ins Bild gesetzt und muss auf dem Handy lesbar sein)
- Deutsch, echte Umlaute (ä, ö, ü, ß)
- SIE-Form, wenn eine Anrede vorkommt (nie duzen)
- Nicht gendern
- Konkret und nutzenorientiert, kein Fachchinesisch, keine Floskeln
- KEINE Hashtags, keine Emojis, keine Anführungszeichen, kein Punkt am Ende
- Zur Zielgruppe passend formulieren (siehe Message Brief)

RECHTLICH KRITISCH:
- Erfinde KEINE Beträge, Fristen, Prozentsätze, Voraussetzungen oder Rechtsfolgen
- Übernimm Zahlen/Daten NUR, wenn sie wörtlich in Kernaussage oder Quelltext stehen
- Im Zweifel: eine Überschrift ohne konkrete Zahl formulieren
"""

    user_prompt = f"""Formuliere die Bild-Überschrift.

- Kernaussage: {brief.kernaussage}
- Nutzen: {brief.nutzen}
- Zielgruppe: {brief.zielgruppe}
- Gewünschte Reaktion: {brief.reaktion}
- Quelltext (Faktenbasis, nichts hinzuerfinden): {text or "(nicht angegeben)"}
"""

    log.info("Keine Überschrift übergeben - generiere Fallback-Überschrift...")

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format=GeneratedHeadline
    )

    result = completion.choices[0].message.parsed
    if not result or not result.headline.strip():
        raise Exception("Es wurde keine Überschrift erzeugt.")

    headline = result.headline.strip()
    log.info(f"✓ Fallback-Überschrift ({len(headline)} Zeichen): {headline}")
    return headline


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
