#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Art Director Board - Visuelle Regie für ShareNext-Pipeline.

Übersetzt die gewinnende kreative Route in präzise visuelle Entscheidungen:
- Focal Point: Visueller Schwerpunkt
- Komposition: Bildaufbau (Rule of Thirds, Symmetrie, etc.)
- Licht: Richtung, Qualität, Stimmung
- Farbdramaturgie: Dominante Farben, Kontraste, Temperatur
- Emotion: Emotionaler Moment, Ausdruck

Teil von Issue #4: ShareNext MVP
"""

from __future__ import annotations

import json
import logging
import os
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from config import DATA_DIR
from message_brief import MessageBrief
from creative_director import CreativeRoute
from secrets_store import get_secret

log = logging.getLogger("hilo.art_director")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VARIANZ-MECHANISMUS (gegen LLM-Bias bei Kameraperspektive/Komposition)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# #Varianz-Fix: Bei Literal-Feldern ohne
# starkes inhaltliches Unterscheidungsmerkmal (hier: Kameraperspektive, Kompositionsprinzip)
# neigt das LLM zu denselben 1-2 Optionen. Anders als beim Layout (dort codeseitig zufaellig
# VORGEGEBEN) bleibt die Wahl hier bewusst beim LLM, weil sie inhaltlich von der Route abhaengt -
# es wird nur informiert, was zuletzt genutzt wurde, und um Abwechslung GEBETEN (kein Zwang),
# damit die Kreativitaet nicht leidet, falls die letzte Wahl objektiv die beste bleibt.

_VARIANZ_FELDER = ("kamera_perspektive", "komposition_prinzip", "hintergrund_typ")
_VARIANZ_HISTORY_LEN = 3  # wie viele letzte Werte je Feld gemerkt werden


def _variance_history_path() -> str:
    return os.path.join(DATA_DIR, "art_director_variance.json")


def _load_variance_history() -> dict[str, list[str]]:
    try:
        with open(_variance_history_path(), encoding="utf-8") as f:
            data = json.load(f)
        return {feld: data.get(feld, []) for feld in _VARIANZ_FELDER}
    except Exception:
        return {feld: [] for feld in _VARIANZ_FELDER}


def _save_variance_choice(history: dict[str, list[str]], board: "ArtDirectionBoard") -> None:
    for feld in _VARIANZ_FELDER:
        wert = getattr(board, feld)
        werte = history.get(feld, [])
        werte = [w for w in werte if w != wert] + [wert]
        history[feld] = werte[-_VARIANZ_HISTORY_LEN:]
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_variance_history_path(), "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
    except Exception:
        pass


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


class ArtDirectionBoard(BaseModel):
    """Art Direction Board - präzise visuelle Anweisungen für Image Producer.

    Das Board übersetzt eine kreative Route in konkrete visuelle Entscheidungen
    entlang von 5 Kern-Achsen.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # FOCAL POINT
    # ─────────────────────────────────────────────────────────────────────────

    focal_point: str = Field(
        description="Wo liegt der visuelle Schwerpunkt? Was zieht den Blick zuerst an? "
                    "(z.B. 'Sanduhr im Vordergrund', 'Gesicht der Person', 'Rote Zahl')"
    )

    focal_point_position: Literal[
        "Zentrum",
        "Links-Oben",
        "Rechts-Oben",
        "Links-Unten",
        "Rechts-Unten",
        "Linke Hälfte",
        "Rechte Hälfte"
    ] = Field(description="Position des Focal Points im Bild")

    # ─────────────────────────────────────────────────────────────────────────
    # KOMPOSITION
    # ─────────────────────────────────────────────────────────────────────────

    komposition_prinzip: Literal[
        "Rule of Thirds",
        "Goldener Schnitt",
        "Symmetrie",
        "Diagonale",
        "Rahmen im Rahmen",
        "Leading Lines",
        "Negative Space",
        "Bildfüllende Großaufnahme",
        "Bewusst asymmetrisch/ungeordnet"
    ] = Field(description="Welches Kompositionsprinzip wird angewendet?")

    bildaufbau: str = Field(
        description="Beschreibung des Bildaufbaus (2-3 Sätze). Wo sind die Elemente platziert?"
    )

    hintergrund_typ: Literal[
        "Echte fotografische Umgebung (Tiefe/Textur/Licht)",
        "Freigestellt vor einfarbiger Fläche",
        "Nahaufnahme/Textur-Detail (Hintergrund kaum sichtbar)",
        "Illustrativ/grafisch (bewusst kein Foto-Look)"
    ] = Field(
        description="Welche Art Hintergrund/Umgebung traegt das Motiv? WICHTIG: 'Freigestellt vor "
                    "einfarbiger Flaeche' ist NUR eine von vier gleichwertigen Optionen, nicht der "
                    "Standardfall - ein durchgehend einfarbiger Studio-/Render-Hintergrund wirkt bei "
                    "wiederholter Nutzung schnell langweilig und generisch, selbst wenn das Motiv "
                    "selbst gut ist. Bevorzuge wo passend eine echte fotografische Umgebung mit "
                    "Tiefe (z.B. ein Tisch mit Geschirr im Bokeh-Hintergrund, ein Raum mit Fenster-"
                    "licht) - 'ein dominantes Element' bedeutet NICHT 'kein Umfeld'."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # LICHT
    # ─────────────────────────────────────────────────────────────────────────

    licht_qualitaet: Literal["Soft", "Hart", "Dramatisch", "Diffus"] = Field(
        description="Qualität des Lichts"
    )

    licht_richtung: Literal[
        "Von vorne (Frontal)",
        "Von links",
        "Von rechts",
        "Von oben",
        "Von hinten (Backlight)",
        "Seitlich-schräg"
    ] = Field(description="Hauptrichtung des Lichts")

    licht_stimmung: str = Field(
        description="Lichtstimmung / Tageszeit (z.B. 'Warmes Morgenlicht', 'Kühles Bürolicht', "
                    "'Dramatisches Abendlicht', 'Neutrales Studio-Licht')"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # FARBDRAMATURGIE
    # ─────────────────────────────────────────────────────────────────────────

    dominante_farben: list[str] = Field(
        min_length=2,
        max_length=4,
        description="2-4 dominante Farben im Bild (z.B. ['Blau', 'Weiß', 'Rot-Akzent'])"
    )

    farbtemperatur: Literal["Warm", "Kalt", "Neutral", "Warm-Kalt-Kontrast"] = Field(
        description="Gesamte Farbtemperatur des Bildes"
    )

    farbkontrast: str = Field(
        description="Art des Farbkontrasts (z.B. 'Komplementärkontrast Blau-Orange', "
                    "'Hell-Dunkel-Kontrast', 'Monochromatisch mit Akzent')"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # EMOTION & ATMOSPHERE
    # ─────────────────────────────────────────────────────────────────────────

    emotionaler_moment: str = Field(
        description="Welcher emotionale Moment wird eingefangen? "
                    "(z.B. 'Moment der Erleichterung', 'Dringende Eile', 'Ruhige Konzentration')"
    )

    atmosphaere: str = Field(
        description="Gesamtatmosphäre des Bildes (z.B. 'Professionell und beruhigend', "
                    "'Dringlich aber nicht panisch', 'Warm und einladend')"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # BRAND SIGNATURE (seit 2026-08-11)
    # ─────────────────────────────────────────────────────────────────────────

    brand_signature: str = Field(
        description="Wie wird HILO in DIESEM Motiv visuell spürbar - unabhängig von Logo/"
                    "Slogan-Kreis (die kommen ohnehin deterministisch dazu)? Konkret benennen, "
                    "z.B. 'Navy als große ruhige Hintergrundfläche, sattes Grün als einzelner "
                    "Farbakzent am Focal Point, klarer Hell-Dunkel-Kontrast' - NICHT 'irgendwo "
                    "Grün verwenden'. Ziel: Auch ohne die beiden Kreise sollte das Bild erkennbar "
                    "aus derselben Bildwelt stammen wie andere HILO-Posts."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # TECHNISCHE DETAILS
    # ─────────────────────────────────────────────────────────────────────────

    kamera_perspektive: Literal[
        "Eye-Level (Augenhöhe)",
        "High Angle (von oben)",
        "Low Angle (von unten)",
        "Bird's Eye (Vogelperspektive)",
        "Dutch Angle (schräg)"
    ] = Field(description="Kameraperspektive")

    schaerfe_tiefe: Literal[
        "Alles scharf (große Schärfentiefe)",
        "Fokus vorne, Hintergrund unscharf",
        "Fokus hinten, Vordergrund unscharf",
        "Selektive Schärfe (nur Focal Point)"
    ] = Field(description="Schärfentiefe / Bokeh")

    # ─────────────────────────────────────────────────────────────────────────
    # TEXT-ZONEN (wichtig für deterministisches Text-Rendering)
    # ─────────────────────────────────────────────────────────────────────────

    negativraum_text: str = Field(
        description="Wo ist Platz für Text? Welche Bereiche bleiben ruhig/leer? "
                    "(z.B. 'Obere linke Ecke ruhig', 'Rechte Hälfte hat Raum', "
                    "'Unten Mitte für CTA')"
    )

    text_kontrast_empfehlung: str = Field(
        description="Empfehlung für Text-Kontrast (z.B. 'Navy-Text auf heller Zone links', "
                    "'Weißer Text auf dunklem Hintergrund rechts')"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GENERATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_art_direction_board(
    brief: MessageBrief,
    winning_route: CreativeRoute,
    model: str = "gpt-5.6-terra"
) -> ArtDirectionBoard:
    """Erstellt Art Direction Board aus gewinnender Route.

    Übersetzt die kreative Route in präzise visuelle Anweisungen für den
    Image Producer. Deckt alle 5 Kern-Achsen ab:
    - Focal Point (Schwerpunkt)
    - Komposition (Bildaufbau)
    - Licht (Qualität, Richtung, Stimmung)
    - Farbdramaturgie (Farben, Temperatur, Kontrast)
    - Emotion (Moment, Atmosphäre)

    Plus technische Details (Kamera, Schärfe) und Text-Zonen.

    Args:
        brief: Message Brief (Kontext)
        winning_route: Gewinnende kreative Route aus Concept Jury
        model: OpenAI-Modell (default: gpt-5.6-terra)

    Returns:
        ArtDirectionBoard: Detaillierte visuelle Anweisungen

    Raises:
        ValueError: Wenn OpenAI API-Key fehlt
        Exception: Bei OpenAI API-Fehlern

    Example:
        >>> board = create_art_direction_board(brief, winning_route)
        >>> print(board.focal_point)
        'Sanduhr im Vordergrund'
        >>> print(board.licht_stimmung)
        'Dramatisches Abendlicht'
        >>> print(board.dominante_farben)
        ['Rot', 'Schwarz', 'Gold']
    """
    client = _get_client()

    # Varianz-Historie laden (letzte genutzte Kameraperspektiven/Kompositionsprinzipien)
    variance_history = _load_variance_history()

    # System-Prompt: Art Director Rolle
    system_prompt = """Du bist ein erfahrener Art Director für Social-Media-Marketing.
Deine Aufgabe: Übersetze eine kreative Route in präzise visuelle Anweisungen.

Kontext:
- HILO ist eine Hilfsorganisation für Lohnsteuerhilfe
- Marke: Vertrauenswürdig, professionell, warm
- Ziel: Professionelle Bilder die auffallen aber nicht laut/aufdringlich sind

Die 7 Kern-Achsen:

1. **Focal Point**
   - Was zieht den Blick zuerst an?
   - Wo liegt es im Bild? (Zentrum, Rule of Thirds, etc.)
   - Muss klar und dominant sein
   - EIN Element trägt das Bild - alle weiteren Objekte sind klar untergeordnet (kleiner,
     unscharf, im Hintergrund) oder fehlen ganz. Eine Ansammlung mehrerer gleich wichtiger
     Requisiten (z.B. mehrere Gegenstände nebeneinander mit eigenen Beschriftungen) verwässert
     den Focal Point und wirkt im Feed unruhig statt eines einzelnen, mutigen Bildeindrucks.

2. **Komposition**
   - Welches Prinzip? (Rule of Thirds, Symmetrie, etc.)
   - Wo sind die Elemente platziert?
   - Führt der Bildaufbau das Auge?

3. **Licht**
   - Qualität: Soft/Hart/Dramatisch?
   - Richtung: Von wo kommt das Licht?
   - Stimmung: Welche Tageszeit/Atmosphäre?

4. **Farbdramaturgie**
   - 2-4 dominante Farben
   - Warm/Kalt/Neutral?
   - Welcher Kontrast? (Komplementär, Hell-Dunkel, etc.)

5. **Emotion**
   - Welcher emotionale Moment?
   - Gesamtatmosphäre?

6. **Brand Signature (HILO Visual Signature)**
   - Wie wird HILO in DIESEM Motiv spürbar - unabhängig von Logo-/Slogan-Kreis?
   - Bevorzugte visuelle Grammatik (KEIN starres Template - nicht jedes Bild muss alle Punkte
     erfüllen, das sind Bausteine zur Auswahl, nicht eine Checkliste):
     * tiefes Navy als starke Bühne oder strukturierende Fläche
     * sattes HILO-Grün als bewusster, prägnanter Akzent (nicht als erzwungene Requisite)
     * Weiß/helle Materialien für starken Kontrast
     * ein dominantes Hero-Element statt vieler Requisiten
     * hochwertige Editorial-/Werbefotografie oder bewusst gestaltete grafische Intervention
     * eine überraschende Transformation eines vertrauten Gegenstands ist besonders geeignet
     * klare Formen und starke Silhouetten, die auch im Thumbnail funktionieren
     * großzügiger Negative Space ist erwünscht, solange das Hero-Element dominant bleibt
   - Diese Merkmale sind eine visuelle Grammatik, kein Rezept - wenn jedes Bild denselben
     Navy-Hintergrund mit derselben Papierkante bekommt, ist das genauso eine Monotonie wie ein
     generisches Stockfoto. Wähle pro Motiv aus, was zur konkreten Idee passt.
   - Gedankenexperiment: Würde man das Bild OHNE Logo/Slogan/Überschrift noch als HILO
     erkennen? Wenn nein, ist die Brand Signature zu schwach.

7. **Hintergrund/Umgebung**
   - Trägt eine ECHTE fotografische Umgebung das Motiv (Tiefe, Textur, Licht, evtl. leichtes
     Bokeh) oder steht das Element freigestellt vor einer einfarbigen Fläche?
   - **VORSICHT PRODUKTSHOT-REFLEX:** Ein durchgehend einfarbiger Studio-/Render-Hintergrund
     ist NUR eine von mehreren gültigen Optionen - wird sie bei jedem Bild gewählt, wirkt die
     ganze Bildserie schnell langweilig und generisch wie 3D-Renderings, egal wie gut das
     einzelne Motiv ist. "Ein dominantes Element" (siehe Focal Point oben) bedeutet NICHT
     "kein Umfeld" - ein Hero-Objekt auf einem echten Tisch mit Geschirr im unscharfen
     Hintergrund ist genauso fokussiert wie ein freigestelltes Objekt, wirkt aber warm und
     fotografisch statt steril.
   - Bevorzuge wo es zur Route passt eine echte Umgebung mit Tiefe.

THUMBNAIL-TEST (wichtig für Feed-Wirkung):
Instagram/Facebook zeigen das Bild zuerst klein - ca. 180×180 Pixel zwischen vielen anderen
Posts, nicht als 1080×1080-Kunstwerk. Der Focal Point muss auch in dieser Miniaturgröße sofort
verständlich und dominant bleiben. Feine Details, kleine Requisiten oder subtile visuelle Gags
dürfen NICHT nötig sein, um die Leitidee zu verstehen - das passt zur "ein dominantes Element"-
Regel oben.

SCROLL-STOP HOOK (wichtig für Feed-Wirkung):
Der Focal Point entscheidet, ob jemand im Feed innehält oder weiterscrollt - das passiert in
Bruchteilen einer Sekunde, bevor überhaupt gelesen wird. "Schön" reicht dafür nicht. Wähle einen
Focal Point, der einen kleinen Widerspruch, eine Überraschung oder eine unmittelbare Frage im
Kopf auslöst (z.B. eine ungewöhnliche Nahaufnahme statt Totale, ein unerwartetes Detail im
Vordergrund, ein Moment mitten in einer Handlung statt einer ruhigen Pose). Das muss NICHT
reißerisch oder dramatisch sein - bei HILO passt eher ein stiller, aber ungewöhnlicher Moment
als Effekthascherei. Aber: ein rein dekoratives, erwartbares Motiv (Person lächelt in Kamera,
Dokument liegt ordentlich auf dem Tisch) ist selten ein Hook.

Plus:
- **Kamera**: Perspektive (Eye-Level, High Angle, etc.)
- **Schärfe**: Schärfentiefe (alles scharf vs. Bokeh)
- **Text-Zonen**: Wo ist Platz für Text? (wichtig!)

Wichtig:
- Sei KONKRET (nicht "schönes Licht", sondern "weiches Licht von links")
- Denk an Text-Zonen (Text muss später drauf passen!)
- HILO-CI beachten: Navy (#1f428d), Grün (#60a33c), Weiß - Akzente gerne in diesen Markenfarben
- SIGNALFARBEN (Rot, Orange, Neon o.ä.) sind erlaubt, wenn sie semantisch begründet sind (z.B.
  bei einem Warnungs-/Risiko-Thema) - aber sie dürfen die HILO-Farbdramaturgie (Navy/Grün) nicht
  vollständig verdrängen. Navy oder Grün müssen im Bild weiterhin spürbar bleiben, auch wenn eine
  Signalfarbe den Akzent setzt.
- Professionell aber nicht steril
"""

    # User-Prompt: Route + Brief
    user_prompt = f"""Erstelle ein Art Direction Board für diese kreative Route:

**Message Brief (Kontext):**
- Kernaussage: {brief.kernaussage}
- Zielgruppe: {brief.zielgruppe}
- Gewünschte Emotion: (leite aus Funnel-Stufe ab: {brief.funnel_stufe})
- Kanal: {brief.kanal}

**Gewinnende Route:**
- Typ: {winning_route.typ}
- Titel: {winning_route.titel}
- Beschreibung: {winning_route.beschreibung}
- Visuelle Signatur: {winning_route.visuelle_signatur}
- Emotionale Richtung: {winning_route.emotionale_richtung}
- Beispiel-Szene: {winning_route.beispiel_szene}
- Scroll-Stop-Device: {winning_route.scroll_stop_device}

Erstelle präzise visuelle Anweisungen:
- Focal Point (was + wo?)
- Komposition (Prinzip + Aufbau)
- Licht (Qualität + Richtung + Stimmung)
- Farben (2-4 dominante + Temperatur + Kontrast)
- Emotion (Moment + Atmosphäre)
- Brand Signature (wie ist HILO im Motiv spürbar, auch ohne Logo/Slogan-Kreis?)
- Hintergrund/Umgebung (echte fotografische Umgebung mit Tiefe, oder freigestellt vor
  einfarbiger Fläche? Nicht standardmäßig freigestellt wählen - siehe VORSICHT
  PRODUKTSHOT-REFLEX oben)
- Kamera + Schärfe
- Text-Zonen (wo ist Platz?)

Denk an:
- HILO-CI: Navy (#1f428d), Grün (#60a33c), Weiß - Akzente in diesen Markenfarben
- Text muss später drauf passen!
- Professionell, warm, vertrauenswürdig

VARIANZ (Hinweis, kein Zwang):
- Zuletzt genutzte Kameraperspektiven: {', '.join(variance_history['kamera_perspektive']) or 'keine'}
- Zuletzt genutzte Kompositionsprinzipien: {', '.join(variance_history['komposition_prinzip']) or 'keine'}
- Zuletzt genutzte Hintergrund-Typen: {', '.join(variance_history['hintergrund_typ']) or 'keine'}
Wähle bevorzugt eine andere Option als zuletzt, WENN sie zur Route genauso gut oder besser passt.
Wenn die zuletzt genutzte Option für dieses Motiv klar die stärkste Wahl ist, nimm sie trotzdem -
die inhaltliche Passung zur Route hat immer Vorrang vor reiner Abwechslung.
"""

    log.info(f"Art Director erstellt Board für: {winning_route.titel}")

    try:
        # OpenAI API-Call mit Structured Output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=ArtDirectionBoard
        )

        board = completion.choices[0].message.parsed

        if not board:
            raise Exception("OpenAI API gab kein valides Art Direction Board zurück")

        log.info(
            f"✓ Art Direction Board erstellt:\n"
            f"   Focal Point: {board.focal_point}\n"
            f"   Kamera: {board.kamera_perspektive} | Komposition: {board.komposition_prinzip}\n"
            f"   Licht: {board.licht_stimmung}\n"
            f"   Farben: {', '.join(board.dominante_farben)}\n"
            f"   Emotion: {board.emotionaler_moment}"
        )

        # Varianz-Historie aktualisieren (fuer den naechsten Aufruf)
        _save_variance_choice(variance_history, board)

        return board

    except Exception as e:
        log.error(f"Fehler beim Erstellen des Art Direction Boards: {e}")
        raise


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    # Test mit Mock-Daten
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from message_brief import MessageBrief
    from creative_director import CreativeRoute

    print("="*80)
    print("ART DIRECTOR BOARD TEST")
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

    # Simuliere gewinnende Route (Sanduhr-Metapher)
    winning_route = CreativeRoute(
        typ="Visuelle Metapher",
        titel="Sanduhr mit rotem Sand",
        beschreibung="Dramatische Sanduhr im Fokus, roter Sand rinnt durch, "
                     "symbolisiert ablaufende Zeit. Dunkler Hintergrund.",
        visuelle_signatur="Dramatisches Licht von links, Rot-Kontrast",
        emotionale_richtung="Dringlichkeit (aber nicht Panik)",
        beispiel_szene="Sanduhr groß im Vordergrund, fast leer, roter Sand"
    )

    print(f"\nMessage Brief: {brief.kernaussage}")
    print(f"Gewinnende Route: {winning_route.titel} ({winning_route.typ})\n")

    try:
        board = create_art_direction_board(brief, winning_route)

        print("🎨 ART DIRECTION BOARD:\n")
        print("─" * 80)
        print("FOCAL POINT")
        print(f"  Element: {board.focal_point}")
        print(f"  Position: {board.focal_point_position}")

        print("\n" + "─" * 80)
        print("KOMPOSITION")
        print(f"  Prinzip: {board.komposition_prinzip}")
        print(f"  Aufbau: {board.bildaufbau}")

        print("\n" + "─" * 80)
        print("LICHT")
        print(f"  Qualität: {board.licht_qualitaet}")
        print(f"  Richtung: {board.licht_richtung}")
        print(f"  Stimmung: {board.licht_stimmung}")

        print("\n" + "─" * 80)
        print("FARBDRAMATURGIE")
        print(f"  Dominante Farben: {', '.join(board.dominante_farben)}")
        print(f"  Temperatur: {board.farbtemperatur}")
        print(f"  Kontrast: {board.farbkontrast}")

        print("\n" + "─" * 80)
        print("EMOTION & ATMOSPHÄRE")
        print(f"  Emotionaler Moment: {board.emotionaler_moment}")
        print(f"  Atmosphäre: {board.atmosphaere}")

        print("\n" + "─" * 80)
        print("TECHNISCH")
        print(f"  Kamera: {board.kamera_perspektive}")
        print(f"  Schärfe: {board.schaerfe_tiefe}")

        print("\n" + "─" * 80)
        print("TEXT-ZONEN")
        print(f"  Negativraum: {board.negativraum_text}")
        print(f"  Text-Kontrast: {board.text_kontrast_empfehlung}")

        print("\n" + "="*80)

    except Exception as e:
        print(f"\n❌ Fehler: {e}")
        print("\nHinweis: Dieser Test braucht einen OpenAI API-Key.")
