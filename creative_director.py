#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Creative Director - 5 kreative Routen für ShareNext-Pipeline.

Entwickelt aus einem Message Brief 5 unterschiedliche kreative Routen:
1. Emotionale Szene - Menschen in Situationen
2. Visuelle Metapher - Abstraktes bildlich dargestellt
3. Objektmotiv - Fokus auf ein zentrales Objekt
4. Kontrast/Störmoment - Unerwartetes Element
5. Unkonventionell - passt bewusst in keine der 4 Kategorien (seit 2026-08-11, gegen
   Nivellierung durch feste Schemata, siehe PROMPT_CHANGELOG.md)

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
        "Kontrast/Störmoment",
        "Unkonventionell"
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

    scroll_stop_device: str = Field(
        description="Was GENAU stoppt den Daumen beim Scrollen? Ein konkretes visuelles Element/"
                    "Detail, kein allgemeines Stilwort. Schlecht: 'ungewöhnliches Stillleben mit "
                    "Kuchen'. Gut: 'Ein Kuchen in Euro-Form, aus dem exakt ein Fünftel "
                    "herausgeschnitten wurde - man fragt sich sofort, warum genau dieses Stück.'"
    )

    headline_dependency: Literal["low", "medium", "high"] = Field(
        description="Wie sehr braucht diese Route die Überschrift, um verstanden zu werden? "
                    "'low' = die visuelle Idee funktioniert bereits für sich allein, ganz ohne Text "
                    "(z.B. ein Objekt, das unerwartet seine Form/Funktion ändert). 'medium' = das Motiv "
                    "ist interessant, aber der volle Sinn erschließt sich erst mit der Überschrift. "
                    "'high' = ohne Überschrift ist das Motiv nur ein austauschbares Alltagsobjekt (z.B. "
                    "ein Briefumschlag, ein Koffer) - das ist ein Warnsignal für eine schwache visuelle "
                    "Idee, nicht nur eine neutrale Eigenschaft."
    )


class CreativeTerritories(BaseModel):
    """5 kreative Routen vom Creative Director.

    Der Creative Director entwickelt 5 unterschiedliche Ansätze um die
    Kernaussage visuell darzustellen. Jede Route folgt einem anderen Prinzip.
    """

    route_1_emotionale_szene: CreativeRoute = Field(
        description="Route 1: Emotionale Szene - Menschen in einer Situation (Erleichterung, Stress, Freude)"
    )

    route_2_metapher: CreativeRoute = Field(
        description="Route 2: Visuelle Metapher - Abstraktes Konzept bildlich (Wegweiser, Puzzle, Sanduhr) - "
                     "EIN Bildelement, keine Requisiten-Ansammlung"
    )

    route_3_objekt: CreativeRoute = Field(
        description="Route 3: Objektmotiv - Fokus auf ein zentrales Objekt (Dokument, Ordner, Stempel, Kalender)"
    )

    route_4_kontrast: CreativeRoute = Field(
        description="Route 4: Kontrast/Störmoment - Unerwartetes Element das Aufmerksamkeit erzeugt"
    )

    route_5_unkonventionell: CreativeRoute = Field(
        description="Route 5: Unkonventionell - passt bewusst in KEINE der 4 Kategorien oben (z.B. grafisch/"
                     "typografisch, Doppelbelichtung, Collage, surreale Verfremdung eines Alltagsobjekts). "
                     "Freiraum für eine Idee, die sich nicht in ein Schema pressen lässt."
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_creative_routes(
    brief: MessageBrief,
    model: str = "gpt-5.6-terra"
) -> CreativeTerritories:
    """Generiert 5 kreative Routen aus einem Message Brief.

    Der Creative Director entwickelt 5 unterschiedliche visuelle Ansätze:
    1. Emotionale Szene (Menschen in Situationen)
    2. Visuelle Metapher (Abstraktes bildlich)
    3. Objektmotiv (Fokus auf Objekt)
    4. Kontrast/Störmoment (Unerwartetes)
    5. Unkonventionell (passt bewusst in keine der 4 Kategorien)

    Args:
        brief: Message Brief mit Kernaussage, Nutzen, Zielgruppe, etc.
        model: OpenAI-Modell (default: gpt-5.6-terra für kreative Aufgaben)

    Returns:
        CreativeTerritories: 5 kreative Routen

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
Deine Aufgabe: Entwickle 5 unterschiedliche kreative Routen für ein Social-Media-Bild.

Kontext:
- HILO ist eine Hilfsorganisation für Lohnsteuerhilfe
- Zielgruppe: siehe Message Brief im User-Prompt - die dort genannte KONKRETE Zielgruppe
  (Alter, Lebenssituation, Erwerbsstatus) ist maßgeblich, nicht eine pauschale Annahme.
  Die Personen/Situationen in deinen Routen müssen zu dieser Zielgruppe passen.
- Stil: Professionell, vertrauenswürdig, aber NICHT langweilig
- Ziel: Scroll-Stop-Potenzial - das Bild soll auffallen!

VISUELLE ÜBERSETZUNG STATT ILLUSTRATION (WICHTIGSTES PRINZIP - vor allen Routen-Details unten!):

Zeige nicht einfach einen Gegenstand, der im Thema vorkommt. Übersetze die Kernaussage in einen
EIGENSTÄNDIGEN visuellen Gedanken. Ein Gegenstand, der nur benennt worum es geht, ist eine
Illustration - keine Idee. Bevorzuge:
- **Transformation**: Ein bekanntes Objekt verändert unerwartet Form, Material oder Funktion
  (Beispiel: ein Steuerformular wird zum Papierflugzeug).
- **Visueller Widerspruch**: Zwei normalerweise nicht zusammengehörende Dinge bilden EIN Motiv.
- **Editorial Intervention**: Eine starke grafische Intervention verändert die Wahrnehmung einer
  realistischen Szene (Beispiel: ein riesiges "AUSNAHME?" durchschneidet das Motiv).
- **Narrative Situation**: Ein einzelner ungewöhnlicher Moment erzeugt eine Frage im Kopf.
- **Bedeutungsvolle Größenrelation**: Ein Element wird ungewöhnlich groß/klein, wenn das die
  Aussage trägt.

Schwächer sind Motive, die lediglich einen Begriff aus dem Thema abbilden - "Erholungsbeihilfe"
→ ein Koffer, "Arbeitsuchend" → ein Brief, "Schenkung" → ein Haustürschlüssel, "Steuer" → ein
Ordner. Das sind austauschbare Symbole, keine eigenständigen Bildideen. Aus einem Gegenstand aus
dem Thema muss eine NEUE visuelle Idee entstehen, nicht nur seine Abbildung.

ONE-IDEA-TEST: Die visuelle Leitidee muss in einem kurzen Satz mit möglichst nur EINEM
Hauptmotiv beschreibbar sein. Je kürzer und bildlicher dieser Satz, desto stärker die Route.
- Stark: "Ein Steuerformular wird zum Papierflugzeug." / "Ein riesiges AUSNAHME? durchschneidet
  das Motiv."
- Schwach: "Eine Waage zeigt links Schlüssel mit Unterstützungsschild, rechts einen
  Steuerordner und in der Mitte ein Gewicht." / "Auf einem Tisch liegen ein Brief und eine
  Karte zum Thema."
Dieser Test zwingt dazu, Idee von bloßer Ausstattung zu unterscheiden - wenn die Route nur mit
einem Nebensatz voller "und" beschreibbar ist, ist sie noch keine Idee, sondern eine Szene.

Die 4 Routen-Typen:

1. **Emotionale Szene**
   - Menschen in realistischen Situationen
   - Emotionen: Erleichterung, Stress, Freude, Zufriedenheit
   - Beispiele: Erleichterter Unternehmer am Schreibtisch, Familie beim Ausfüllen von Formularen
   - NICHT: Stock-Foto-Klischees vermeiden!

2. **Visuelle Metapher**
   - Abstraktes Konzept bildlich dargestellt
   - Beispiele: Sanduhr (Zeit läuft ab), Wegweiser (Orientierung), Puzzle (Komplexität),
     ein verformtes/umgestaltetes Alltagsobjekt (z.B. ein Kuchen in Symbolform)
   - Muss zur Kernaussage passen
   - Darf nicht zu abstrakt sein (Zielgruppe muss es verstehen)
   - EIN Bildelement trägt die Metapher – NICHT mehrere Requisiten zu einem Arrangement
     kombinieren (z.B. keine Waage-Szene mit zusätzlichen Objekten auf beiden Schalen plus
     Beschriftungen). Eine Metapher, die man in einem Wort erklären kann, nicht in einem Satz.

3. **Objektmotiv**
   - Fokus auf EIN zentrales Objekt
   - Beispiele: Dokument mit Stempel, Kalender mit markiertem Datum, Ordner, Sparschwein
   - Echte Still-Life-Fotografie (Materialtextur, Umgebungslicht, leichte Schärfentiefe) -
     KEIN flacher Studio-/Render-Look mit dem Objekt freigestellt vor einfarbiger Fläche.
     Ein Objekt auf einem echten Tisch/in einer echten Umgebung mit unscharfem Hintergrund
     wirkt hochwertiger und wärmer als ein steriles Produktfoto.
   - Objekt muss klar erkennbar und relevant sein

4. **Kontrast/Störmoment**
   - Unerwartetes Element das Aufmerksamkeit erzeugt
   - Beispiele: Große rote "31" in ruhigem Büro, leerer Schreibtisch mit EINEM auffälligen Element
   - Pattern-Interrupt - bricht Erwartungen
   - NICHT willkürlich - muss zur Botschaft passen

5. **Unkonventionell**
   - Passt bewusst in KEINE der 4 Kategorien oben - Freiraum für eine Idee, die sich nicht in
     ein Schema pressen lässt
   - Beispiele: grafisch/typografische Lösung statt Foto, Doppelbelichtung, Collage-Ästhetik,
     surreale Verfremdung eines Alltagsobjekts, ungewöhnliches Bildformat/Cropping als Konzept
   - Muss trotzdem zur Kernaussage passen und umsetzbar sein - "unkonventionell" heißt nicht
     "beliebig"
   - Diese Route existiert explizit, damit gute Ideen nicht in eine unpassende Schublade
     gezwungen werden, nur weil die anderen 4 Kategorien vorgeben, wie ein HILO-Bild auszusehen hat

Wichtig:
- Jede Route muss ANDERS sein (nicht nur leichte Variationen)
- Visuell erkennbare Signaturen (Licht, Farbe, Komposition)
- Alle 4 müssen zur Kernaussage passen
- Scroll-Stop-Potenzial beachten
- **EIN dominantes Bildelement pro Route, keine Requisiten-Ansammlung.** Mehrere kleine Objekte
  (+ Labels/Beschriftungen darauf) konkurrieren um Aufmerksamkeit und werden im Feed-Thumbnail
  unlesbar. Lieber ein einzelnes, klares Element mutig/großformatig inszenieren als eine
  Szene aus vielen kleinen Requisiten zusammenzustellen - das gilt besonders für "Visuelle
  Metapher" und "Kontrast/Störmoment".
- **HILO-Farben nicht als erzwungene Requisiten.** Navy/Grün sollen über Licht, Flächen,
  Hintergrund, Material oder Farbkontrast entstehen - nicht durch sachlich unnötige grüne/blaue
  Gegenstände (grüner Ordner, blauer Stift, grüne Tasse ...). Das erzeugt sonst genau die
  austauschbaren Wiederholungsmuster, die eine eigenständige Bildsprache verhindern.
- **KEINE echten Hoheitszeichen, Institutions- oder Marken-Logos** (Bundesadler, Bundeswehr-/
  Polizei-/Behörden-Abzeichen, Wappen, aber auch Logos echter Behörden wie "Agentur für Arbeit",
  Banken, Versicherungen, anderer Firmen) vorschlagen - auch nicht bei Themen mit Uniform-/
  Behörden-/Bank-Bezug (z.B. Wehrdienst, Beamtenstatus, Behördenbrief). Das Objekt (Umschlag,
  Uniform, Formular) ja, ein echtes fremdes Kennzeichen darauf nein. Rechtliches Risiko, hat
  Vorrang vor Scroll-Stop-Überlegungen.
- **KEINE ERKLÄR-LABELS.** Beschrifte Gegenstände nicht mit Begriffen, nur damit eine Metapher
  verständlich wird (z.B. ein Etikett "Unterstützung" an einem Schlüssel, ein Schild
  "gesetzliche Unterhaltspflicht" an einem Gewicht, ein Label "Erholungszeit" an einem Handtuch).
  Wenn ein Gegenstand ein Label braucht, um seine Bedeutung zu erklären, ist das ein Signal, dass
  die visuelle Idee selbst noch nicht trägt - überarbeite dann bevorzugt die Idee, statt sie mit
  Text zu erklären. Ausnahme: Schrift ist ein natürlicher, fachlich notwendiger Bestandteil des
  Motivs selbst (z.B. echter Aufdruck auf einem Dokument, eine Headline-Fläche).
- **SIGNALFARBEN kontrolliert einsetzen.** Rot, Orange, Neon oder andere markenfremde
  Signalfarben sind erlaubt, wenn sie semantisch begründet sind (z.B. eine Warnung/ein Risiko-
  Thema). Sie dürfen aber NICHT der alleinige Grund für Scroll-Stop-Wirkung sein und die
  HILO-Farbdramaturgie (Navy/Grün) nicht vollständig verdrängen - Navy oder Grün müssen weiterhin
  spürbar bleiben, auch wenn eine Signalfarbe den Akzent setzt.

ABGENUTZTE BILDSPRACHE (eher vermeiden, kein starres Verbot):
- generische Businessperson-Klischees (Person zeigt lächelnd auf Laptop-Bildschirm,
  Händeschütteln vor Glaswand, Daumen hoch im Anzug)
- sichtlich gestellte Stockfoto-Posen, grundlos breit in die Kamera grinsend
- übertriebenes/unnatürliches Lächeln
- wörtlicher Geldregen (fallende Scheine/Münzen als Klischee-Symbol für "Geld")
- **ein Steuerformular/Dokument, das zu einem anderen Objekt gefaltet/verformt wird** (Papierflieger,
  Brücke, Boot o.ä.) als Standardlösung für "Visuelle Metapher" - war ursprünglich eine starke,
  frische Idee, ist inzwischen bei mehreren unterschiedlichen Themen wiederholt aufgetaucht und
  droht zur neuen Formel zu werden. Eine Formular-Transformation ist nicht per se abgenutzt, aber
  sollte nicht die naheliegende Standardantwort auf jedes Thema sein - prüfe, ob eine andere
  Transformation (siehe VISUELLE ÜBERSETZUNG oben) besser zur KONKRETEN Kernaussage passt.
Das sind abgenutzte Muster, keine verbotenen Themen. Ein einzelnes, mutig inszeniertes
Euro-Symbol oder ein in Euro-Form verformtes Alltagsobjekt (z.B. ein Kuchen, ein Gegenstand)
ist AUSDRÜCKLICH KEIN Klischee, sondern ein starkes Kontrast/Störmoment-Motiv - das ist
etwas anderes als Geldregen und soll nicht vermieden werden. Echte Emotionen, ungewöhnliche
Perspektiven und starke Farbkontraste sind ausdrücklich erwünscht - wenn eine Idee wirklich
trägt, hat sie Vorrang vor dieser Liste.
"""

    # User-Prompt: Message Brief Daten
    user_prompt = f"""Entwickle 5 kreative Routen für diesen Social-Media-Post:

**Message Brief:**
- Kernaussage: {brief.kernaussage}
- Nutzen: {brief.nutzen}
- Zielgruppe: {brief.zielgruppe}
- Reaktion: {brief.reaktion}
- Funnel-Stufe: {brief.funnel_stufe}
- Kanal: {brief.kanal}

Erstelle 5 unterschiedliche kreative Routen:
1. Emotionale Szene (Menschen)
2. Visuelle Metapher (Abstraktes)
3. Objektmotiv (Objekt-Fokus)
4. Kontrast/Störmoment (Unerwartetes)
5. Unkonventionell (passt bewusst in keine der 4 Kategorien oben)

Jede Route braucht:
- Titel (kurz, prägnant)
- Beschreibung (2-3 Sätze)
- Visuelle Signatur (was macht sie erkennbar?)
- Emotionale Richtung (welche Emotion?)
- Beispiel-Szene (konkretes Bild-Beispiel)
- Scroll-Stop-Device (was GENAU stoppt den Daumen? Ein konkretes Detail, kein Stilwort)
- Headline-Abhängigkeit (low/medium/high - funktioniert die Idee auch ganz ohne Überschrift?)
"""

    log.info(f"Generiere 5 kreative Routen für: {brief.kernaussage}")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=CreativeTerritories
        )

        territories = completion.choices[0].message.parsed

        if not territories:
            raise Exception("OpenAI API gab keine validen Creative Territories zurück")

        log.info(
            f"✓ 5 kreative Routen generiert:\n"
            f"   1. {territories.route_1_emotionale_szene.titel}\n"
            f"   2. {territories.route_2_metapher.titel}\n"
            f"   3. {territories.route_3_objekt.titel}\n"
            f"   4. {territories.route_4_kontrast.titel}\n"
            f"   5. {territories.route_5_unkonventionell.titel}"
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
