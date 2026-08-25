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
                    "Detail, kein allgemeines Stilwort. Schlecht: ein vages Stilwort ('ungewöhnliches "
                    "Stillleben'). Gut: ein präzise beschriebenes, überraschendes Detail, das sofort "
                    "eine konkrete Frage im Kopf auslöst."
    )

    hero_kurz: str = Field(
        max_length=40,
        description="Kurz-KATEGORIE des Hero-Motivs in 2-4 Wörtern, für die Serien-Vielfalt-Prüfung "
                    "(NICHT der Titel, sondern die Grundart des Motivs + Material). Beschreibe die "
                    "TYPE, nicht die konkrete Idee: z.B. 'Papierdokument-Objekt', 'Mensch in "
                    "Alltagsszene', 'Kalender/Datum-Objekt', 'typografische Form', 'Haushalts-"
                    "gegenstand', 'Lebensmittel-Motiv'. So kann das System erkennen, wenn dieselbe "
                    "Grundart in der Serie zu oft vorkommt."
    )

    semantic_environment: str = Field(
        max_length=40,
        description="Die uebergeordnete BEDEUTUNGSWELT/das Umfeld des Motivs in 1-3 Woertern, fuer die "
                    "Serien-Vielfalt auf Bedeutungsebene. Abstrakter als hero_kurz: z.B. 'Pendeln/"
                    "Mobilitaet' (Fahrrad, Auto, Strasse, Bahnhof, Bahnsteig zaehlen ALLE hierzu), "
                    "'Dokument/Formular', 'Zeit', 'Geld/Erstattung', 'Zuhause/Familie', 'Buero'. So "
                    "erkennt das System, wenn die Serie zwar unterschiedliche Motive, aber staendig "
                    "dieselbe Bedeutungswelt zeigt (z.B. immer wieder Verkehr/Pendeln)."
    )

    message_angle: str = Field(
        max_length=40,
        description="Welchen KERNNUTZEN / welche Teilbotschaft des Themas visualisiert diese Route? "
                    "In 1-3 Woertern - fuer die Serien-Vielfalt auf ARGUMENT-Ebene. Ein Thema hat oft "
                    "mehrere Nutzen (z.B. 'freiwillig/keine Pflicht', 'rueckwirkend/Jahre zurueck', "
                    "'Erstattung/Geld zurueck', 'ruecknehmbar/flexibel'). So erkennt das System, wenn "
                    "die Serie optisch variiert, aber staendig DIESELBE Teilbotschaft zeigt (z.B. immer "
                    "'rueckwirkend/zurueck')."
    )

    headline_dependency: Literal["low", "medium", "high"] = Field(
        description="Wie sehr braucht diese Route die Überschrift, um verstanden zu werden? "
                    "'low' = die visuelle Idee funktioniert bereits für sich allein, ganz ohne Text "
                    "(z.B. ein Objekt, das unerwartet seine Form/Funktion ändert). 'medium' = das Motiv "
                    "ist interessant, aber der volle Sinn erschließt sich erst mit der Überschrift. "
                    "'high' = ohne Überschrift ist das Motiv nur ein austauschbares Alltagsobjekt - das "
                    "ist ein Warnsignal für eine schwache visuelle Idee, nicht nur eine neutrale "
                    "Eigenschaft."
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
        description="Route 2: Visuelle Metapher - Abstraktes Konzept bildlich dargestellt - "
                     "EIN Bildelement, keine Requisiten-Ansammlung"
    )

    route_3_objekt: CreativeRoute = Field(
        description="Route 3: Objektmotiv - Fokus auf ein zentrales, greifbares Objekt"
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
        '<prägnanter Titel der Metapher-Route>'
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
- **Transformation**: Ein bekanntes Objekt verändert unerwartet Form, Material oder Funktion.
- **Visueller Widerspruch**: Zwei normalerweise nicht zusammengehörende Dinge bilden EIN Motiv.
- **Editorial Intervention**: Eine starke grafische Intervention verändert die Wahrnehmung einer
  realistischen Szene.
- **Narrative Situation**: Ein einzelner ungewöhnlicher Moment erzeugt eine Frage im Kopf.
- **Bedeutungsvolle Größenrelation**: Ein Element wird ungewöhnlich groß/klein, wenn das die
  Aussage trägt.

Schwächer sind Motive, die lediglich einen Begriff aus dem Thema als naheliegenden Gegenstand
abbilden. Das sind austauschbare Symbole, keine eigenständigen Bildideen. Aus einem Gegenstand aus
dem Thema muss eine NEUE visuelle Idee entstehen, nicht nur seine Abbildung.

ONE-IDEA-TEST: Die visuelle Leitidee muss in einem kurzen Satz mit möglichst nur EINEM
Hauptmotiv beschreibbar sein. Je kürzer und bildlicher dieser Satz, desto stärker die Route.
- Stark: ein Satz mit einem einzigen, klaren Hauptmotiv.
- Schwach: ein Satz voller "und", der mehrere gleichrangige Requisiten aufzählt.
Dieser Test zwingt dazu, Idee von bloßer Ausstattung zu unterscheiden - wenn die Route nur mit
einem Nebensatz voller "und" beschreibbar ist, ist sie noch keine Idee, sondern eine Szene.

SEMANTISCHE PRÄZISION: Eine ungewöhnliche Transformation ist nur dann stark, wenn ihre Bedeutung
möglichst eng mit der Kernaussage verbunden ist - nicht nur überraschend, sondern auch treffend.
Frage bei jeder Route: "Welche anderen Bedeutungen könnte ein Betrachter diesem Motiv OHNE
Headline geben?" Je mehr naheliegende Alternativ-Deutungen bestehen, desto schwächer die Route -
die Headline soll die visuelle Idee PRÄZISIEREN, nicht erst ERKLÄREN müssen.
Die Bedeutung des visuellen Hooks muss aus allgemein verständlicher visueller Logik entstehen und
OHNE konstruierte Erklärung zur Kernbotschaft führen. Eine Metapher ist NICHT deshalb intuitiv, weil
ihre Bedeutung im Konzepttext erklärt werden kann - sie muss beim schnellen Betrachten von selbst
entstehen, sonst trägt sie nicht.
BESONDERS kritisch sind Fehldeutungen im GLEICHEN Themenfeld: Wenn ein Motiv genauso gut ein
ANDERES Steuer-/Finanzthema meinen könnte (eine fachlich naheliegende Verwechslung), ist die Route
zu unpräzise - dann trägt selbst ein technisch schönes Bild die gewünschte Aussage nicht. Die
gewünschte Bedeutung muss die mit Abstand naheliegendste sein, auch ohne Headline.
- Stark: ein transformiertes Motiv, dessen symbolische Bedeutung kulturell eindeutig und eng mit
  der KONKRETEN Kernaussage verknüpft ist.
- Schwächer: ein Mehrzweck-Symbol, das nur ganz allgemein für einen Oberbegriff steht und genauso
  gut für viele andere Themen passen würde - die Verbindung zum konkreten Thema bleibt vage.
WICHTIG - keine Verwechslung mit "möglichst wörtlich": Das Ziel ist NICHT, Mehrdeutigkeit durch
pure Abbildung zu vermeiden (ein Foto vom Gegenstand aus dem Thema hat kaum Fehldeutungen, ist
aber wieder reine Illustration, siehe oben). Das Ziel ist ein TRANSFORMIERTES Motiv, dessen
symbolische Bedeutung kulturell eindeutig ist, statt eines Mehrzweck-Symbols mit vielen möglichen
Lesarten. Beide Prinzipien - Transformation UND semantische Präzision - gelten gemeinsam, keins
ersetzt das andere.

WÄRME & ECHTHEIT (gleichrangiges Leitprinzip - genauso wichtig wie die visuelle Übersetzung oben):
Die stärksten HILO-Bilder wirken wie echte, warme Fotografie: ein ehrlicher menschlicher Moment
oder ein greifbares, real fotografiertes Objekt in warmem Tageslicht - mit Tiefe, Textur und
Atmosphäre. Diese Wärme ist eine Kernqualität der Marke; eine emotional wahre, real wirkende Szene
ist ein Spitzen-Ergebnis und ein vollwertiger Gewinner, kein Rückfall auf "nur ein Foto". Eine gute
visuelle Übersetzung entsteht genauso über einen warmen echten Moment wie über eine abstrakte
Transformation - beide Wege sind erstklassig und gleichwertig. Bevorzuge echte fotografische Tiefe,
echtes Licht und echtes Material gegenüber einer flachen, rein grafischen Bildfläche. Auch hier
gilt die visuelle Übersetzung: ein echter Moment trägt eine klare Emotion oder Handlung (nicht eine
sterile Abbildung des Themen-Gegenstands). Das HILO-Grün wirkt am stärksten als gezielter, kräftiger
Akzent innerhalb eines warmen, echten Bildes - eine kleine leuchtende Fläche, ein Lichtreflex, ein
markanter Farbtupfer -, nicht als großflächiger grafischer Block über das ganze Bild.
Faustregel für die Serie: Menschen und echte Szenen dürfen ruhig häufiger vorkommen als abstrakte
Symbol-Grafiken - ein warmer, konkreter Alltagsmoment ist im Feed sympathischer und markentypischer
als ein weiteres schwebendes Icon.

ORIGINALITÄT & KEINE WIEDERHOLUNG (verbindlich):
Entwickle für JEDES Thema eine eigenständige visuelle Leitidee aus dessen KONKRETER Kernaussage.
Wiederhole keine bekannte Motivlösung, Transformation, Metapher oder Kompositionsmuster nur deshalb,
weil sie bei einem anderen Thema funktioniert hat. Wenn dir eine Idee sofort und "naheliegend"
einfällt, ist sie oft schon eine Formel - prüfe dann, ob eine frischere, stärker themenspezifische
Idee besser trägt. Ziel ist echte Vielfalt über die Bildserie hinweg, nicht die immer gleiche Lösung.

MARKENINTEGRATION (organisch, nicht erzwungen):
Mindestens eine zentrale Eigenschaft des Hero-Motivs oder seiner unmittelbaren Inszenierung soll die
HILO-Farbwelt organisch tragen - Navy, Grün und Weiß sollen Teil der visuellen Idee selbst sein, nicht
nur über Headline, Logo oder Slogan entstehen. ABER: Markenfarben niemals sachlich unbegründet
erzwingen - eine hochwertige, natürliche Bildidee hat Vorrang vor künstlicher Einfärbung.
Insbesondere KEIN künstlicher Neon-/Leucht-Glow an einem Objekt, nur um Grün unterzubringen - ein
natürlicher grüner Akzent an einer sinnvollen, glaubwürdigen Stelle ist besser als ein aufgesetztes
Leuchten. Lieber gar kein Grün im Motiv als ein erzwungenes.

Die 4 Routen-Typen:

1. **Emotionale Szene**
   - Menschen in realistischen Situationen
   - Emotionen: Erleichterung, Stress, Freude, Zufriedenheit
   - NICHT: Stock-Foto-Klischees vermeiden! KEINE Steuerberater-/Beratungsszene, niemand der
     über Unterlagen oder am Schreibtisch sitzt, keine gestellte Pose - die Person muss ETWAS TUN.
   - BRAUCHT EINE KONKRETE HANDLUNG ODER BEZIEHUNG, nicht nur eine Person mit einem Gegenstand.
     Eine Person, die nur ein Objekt hält und aus dem Bild schaut, ist keine Szene, sondern eine
     Pose - dieselbe Schwäche wie eine reine Objekt-Illustration, nur mit Person statt Gegenstand.
     Stark ist eine sichtbare Handlung ZWISCHEN Menschen oder ein Moment mit klarem Vorher/Nachher.
     Die Szene muss auch ohne Headline erkennbar "etwas passiert hier gerade" vermitteln.

2. **Visuelle Metapher**
   - Abstraktes Konzept bildlich dargestellt
   - Muss zur Kernaussage passen
   - Darf nicht zu abstrakt sein (Zielgruppe muss es verstehen)
   - EIN Bildelement trägt die Metapher – NICHT mehrere Requisiten zu einem Arrangement
     kombinieren. Eine Metapher, die man in einem Wort erklären kann, nicht in einem Satz.

3. **Objektmotiv**
   - Fokus auf EIN zentrales, greifbares Objekt
   - Echte Still-Life-Fotografie (Materialtextur, Umgebungslicht, leichte Schärfentiefe) -
     KEIN flacher Studio-/Render-Look mit dem Objekt freigestellt vor einfarbiger Fläche.
     Ein Objekt auf einem echten Tisch/in einer echten Umgebung mit unscharfem Hintergrund
     wirkt hochwertiger und wärmer als ein steriles Produktfoto.
   - Objekt muss klar erkennbar und relevant sein

4. **Kontrast/Störmoment**
   - Unerwartetes Element das Aufmerksamkeit erzeugt
   - Pattern-Interrupt - bricht Erwartungen
   - NICHT willkürlich - muss zur Botschaft passen

5. **Unkonventionell**
   - Passt bewusst in KEINE der 4 Kategorien oben - Freiraum für eine Idee, die sich nicht in
     ein Schema pressen lässt (z.B. eine grafisch/typografische oder collagenhafte Lösung statt
     eines klassischen Fotos)
   - Muss trotzdem zur Kernaussage passen und umsetzbar sein - "unkonventionell" heißt nicht
     "beliebig"
   - Diese Route existiert explizit, damit gute Ideen nicht in eine unpassende Schublade
     gezwungen werden, nur weil die anderen 4 Kategorien vorgeben, wie ein HILO-Bild auszusehen hat

Wichtig:
- Jede Route muss ANDERS sein (nicht nur leichte Variationen)
- Visuell erkennbare Signaturen (Licht, Farbe, Komposition)
- Alle 4 müssen zur Kernaussage passen
- Scroll-Stop-Potenzial beachten
- **Mindestens EINE der Routen MUSS eine klare Transformation oder einen sichtbaren Widerspruch
  als Scroll-Stop tragen** - kein bloßes Abbilden des Themen-Objekts (Illustration eines Begriffs
  ist die schwächste Lösung).
- **EIN dominantes Bildelement pro Route, keine Requisiten-Ansammlung.** Mehrere kleine Objekte
  (+ Labels/Beschriftungen darauf) konkurrieren um Aufmerksamkeit und werden im Feed-Thumbnail
  unlesbar. Lieber ein einzelnes, klares Element mutig/großformatig inszenieren als eine
  Szene aus vielen kleinen Requisiten zusammenzustellen - das gilt besonders für "Visuelle
  Metapher" und "Kontrast/Störmoment".
- **HILO-Farben nicht als erzwungene Requisiten.** Navy/Grün sollen über Licht, Flächen,
  Hintergrund, Material oder Farbkontrast entstehen - nicht durch sachlich unnötige grüne/blaue
  Gegenstände. Das erzeugt sonst genau die austauschbaren Wiederholungsmuster, die eine
  eigenständige Bildsprache verhindern.
- **KEINE echten Hoheitszeichen, Institutions- oder Marken-Logos** (Bundesadler, Bundeswehr-/
  Polizei-/Behörden-Abzeichen, Wappen, aber auch Logos echter Behörden wie "Agentur für Arbeit",
  Banken, Versicherungen, anderer Firmen) vorschlagen - auch nicht bei Themen mit Uniform-/
  Behörden-/Bank-Bezug (z.B. Wehrdienst, Beamtenstatus, Behördenbrief). Das Objekt (Umschlag,
  Uniform, Formular) ja, ein echtes fremdes Kennzeichen darauf nein. Rechtliches Risiko, hat
  Vorrang vor Scroll-Stop-Überlegungen.
- **KEINE ERKLÄR-LABELS.** Beschrifte Gegenstände nicht mit Begriffen, nur damit eine Metapher
  verständlich wird. Wenn ein Gegenstand ein Label braucht, um seine Bedeutung zu erklären, ist
  das ein Signal, dass die visuelle Idee selbst noch nicht trägt - überarbeite dann bevorzugt die
  Idee, statt sie mit Text zu erklären. Ausnahme: Schrift, die ein natürlicher, fachlich
  notwendiger Bestandteil des Motivs selbst ist (ein echter Aufdruck, der ohnehin dort stünde).
- **SIGNALFARBEN kontrolliert einsetzen.** Rot, Orange, Neon oder andere markenfremde
  Signalfarben sind erlaubt, wenn sie semantisch begründet sind (z.B. eine Warnung/ein Risiko-
  Thema). Sie dürfen aber NICHT der alleinige Grund für Scroll-Stop-Wirkung sein und die
  HILO-Farbdramaturgie (Navy/Grün) nicht vollständig verdrängen - Navy oder Grün müssen weiterhin
  spürbar bleiben, auch wenn eine Signalfarbe den Akzent setzt.

ABGENUTZTE BILDSPRACHE (eher vermeiden, kein starres Verbot):
- generische Businessperson-/Stockfoto-Klischees und sichtlich gestellte Posen
- übertriebenes/unnatürliches Lächeln, grundlos breit in die Kamera grinsen
- Steuerberater-/Beratungsszene: Person(en) sitzen über Unterlagen/am Schreibtisch, klassische
  Beratungsgespräch-Situation - ausdrücklich unerwünscht (Owner-Vorgabe)
- wörtliche Klischee-Symbole für "Geld"
- dieselbe Objekt-Transformation immer wieder als Standardlösung für jedes Thema - wenn eine
  Bildidee bei mehreren unterschiedlichen Themen wiederholt auftaucht, droht sie zur Formel zu
  werden; prüfe dann, ob eine andere, zur KONKRETEN Kernaussage passende Idee stärker ist.
Das sind abgenutzte Muster, keine verbotenen Themen. Echte Emotionen, ungewöhnliche
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
- Hero-Kurz (2-4 Wörter Kategorie des Hero-Motivs, für die Serien-Vielfalt - Grundart + Material,
  nicht die konkrete Idee)
- Semantic-Environment (1-3 Wörter übergeordnete Bedeutungswelt, z.B. Pendeln/Mobilität,
  Dokument/Formular, Zeit, Geld/Erstattung)
- Message-Angle (1-3 Wörter: welcher Kernnutzen wird visualisiert? z.B. freiwillig/keine Pflicht,
  rückwirkend/Jahre zurück, Erstattung/Geld zurück, rücknehmbar/flexibel)
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
