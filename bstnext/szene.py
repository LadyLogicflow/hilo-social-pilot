# -*- coding: utf-8 -*-
"""Typ C (Stufe 2): Foto-Look-Szene mit KI in der BSt-Next-CI.

Schlanke Kopie des ShareNext-Gedankens (Creative Director -> Jury -> Bildprompt -> Bild -> QA),
aber NUR mit dem BSt-Next-Bildbrief (Fassung 2, von catrin freigegeben 09.11.2026). Der HILO-Code
bleibt unberuehrt; alle Modellaufrufe sind injizierbar (Tests laufen ohne Netz).

Ablauf erzeuge_szene():
1. Director: 3 Routen aus Thema/Headline (nur Motive aus dem Bildbrief, ohne Schrift im Bild),
2. Jury: waehlt die Route (CI-Passung, Klarheit, Tabus),
3. Bildprompt: deterministisch aus der Route + Stil-Zusatz (Navy-Stich, kein Text/Logo),
4. Bild (gpt-image-2), 5. QA gegen die Vermeidungsliste (Vision), bei Fehlschlag EIN neuer Versuch,
6. Headline + Logo setzt kachel.render_foto (Pillow), nie die KI."""
import base64
import io
import logging
import os

from . import brand, kachel

log = logging.getLogger("hilo.bstnext.szene")

MODELL = "gpt-5.6-terra"          # wie die HILO-Pipeline (creative_director/visual_qa)
# 1024x1024 ist die in ShareNext erprobte Groesse; das Hochformat entsteht per Cover-Zuschnitt (render_foto).
BILD_GROESSEN = {"quadrat": "1024x1024", "hochformat": "1024x1024"}

# --- Bildbrief Fassung 2 (Casty, von catrin freigegeben) ---------------------------------------
MOTIVE = {
    "belege": "Schreibtisch mit Belegstapel, Ordner im Regal, Haende beim Sortieren (Papier ohne lesbaren Text)",
    "termine": "Kalender, Beratungsgespraech am Tisch, ruhige Buero-Atmosphaere",
    "telefon": "Anruf am Arbeitsplatz, Headset, Notizblock (ohne lesbaren Text)",
    "werbung": "Aushang, Schaufenster einer Beratungsstelle, Megafon als Symbol (ohne lesbare Schrift)",
    "challenge": "Stoppuhr, Kalender Januar, Starter-Paket als Symbol (keine Rangliste, kein Podest)",
}
STIL_ZUSATZ = ("Vertical-friendly composition, photorealistic, calm natural light, shallow depth of field, "
               "navy blue color grade (#001942), lime green (#A3E635) only as a very small accent, "
               "clean uncluttered scene with generous empty space in the upper third for a headline, "
               "no text, no letters, no numbers, no logos, no watermarks, no readable writing or documents, "
               "no brand names, fictional people only (fully AI-generated, never resembling real or famous persons), "
               "no children, no real-looking company or office-brand logos, no promise or result shown.")
TABUS = ("Keine erkennbaren realen Personen (auch keine Promis oder Mitarbeitende), keine Kinder, "
         "keine lesbare Schrift/Zahlen/Prozente/Preise/Zeitersparnisse, keine lesbaren Dokumente mit Personendaten, "
         "keine Kundenlogos, Testimonials oder Fremdmarken, keine HILO-Farben oder -Zeichen, "
         "keine Rangliste/Podest, keine fiktive Person als Kunde oder Mitarbeiter, kein Erfolgs- oder Ergebnisversprechen, "
         "keine echt wirkenden Beratungsstellen-Raeume mit Schild oder Logo.")


# --- Datenmodelle (Pydantic nur, wenn die Standard-Funktionen genutzt werden) -------------------
def _modelle():
    from pydantic import BaseModel, Field

    class Route(BaseModel):
        titel: str = Field(description="Kurztitel der Route, deutsch")
        szene: str = Field(description="Englische Bildbeschreibung der Szene (ohne Text im Bild), 2-4 Saetze")
        kategorie: str = Field(description="Kurz-Kategorie des Motivs, deutsch, z. B. 'Ordner-Regal'")

    class Routen(BaseModel):
        routen: list[Route]

    class Wahl(BaseModel):
        gewinner: int = Field(description="Index (0-basiert) der besten Route")
        begruendung: str

    class QA(BaseModel):
        bestanden: bool
        probleme: list[str]

    return Route, Routen, Wahl, QA


def _client():
    from creative_director import _get_client
    return _get_client()


def _llm_parse(system, user, schema, bild=None):
    """Standard-Modellaufruf (OpenAI Structured Output). Tests ersetzen diese Funktion."""
    client = _client()
    content = [{"type": "text", "text": user}]
    if bild is not None:
        buf = io.BytesIO()
        bild.convert("RGB").save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}})
    comp = client.beta.chat.completions.parse(
        model=MODELL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": content if bild is not None else user}],
        response_format=schema)
    out = comp.choices[0].message.parsed
    if out is None:
        raise RuntimeError("Modell lieferte keine gueltige Antwort")
    return out


def _bild_erzeugen(prompt, groesse):
    """Standard-Bildaufruf (gpt-image-2). Tests ersetzen diese Funktion."""
    from image_producer import ImageProductionBrief
    import image_producer
    brief = ImageProductionBrief.model_construct(image_prompt=prompt)
    return image_producer.generate_image(brief, size=groesse, quality="medium")


# --- Schritte ---------------------------------------------------------------------------------
def motiv_text(motiv):
    """Freitext oder Schluessel aus MOTIVE."""
    m = (motiv or "").strip()
    return MOTIVE.get(m.lower(), m or MOTIVE["belege"])


def routen_erzeugen(thema, headline, motiv, llm):
    Route, Routen, Wahl, QA = _modelle()
    system = ("Du bist Creative Director fuer BSt Next (digitale Werkzeuge fuer Lohnsteuerhilfevereine). "
              "Entwickle genau 3 unterschiedliche Foto-Look-Szenen fuer ein Social-Media-Bild. "
              "Stil: ruhig, natuerliches Licht, Navy-Stich, Lime nur als Mini-Akzent. Im Bild steht KEINE Schrift; "
              "die Headline wird spaeter separat gesetzt. Personen nur voellig fiktiv. TABUS: " + TABUS)
    user = ("Thema: %s\nHeadline (nicht ins Bild schreiben): %s\nMotivrichtung: %s\n"
            "Gib 3 Routen mit englischer Szenenbeschreibung." % (thema, headline, motiv_text(motiv)))
    out = llm(system, user, Routen)
    routen = list(out.routen)[:3]
    if not routen:
        raise RuntimeError("Keine Routen erzeugt")
    return routen


def route_waehlen(routen, thema, llm):
    Route, Routen, Wahl, QA = _modelle()
    if len(routen) == 1:
        return 0, "einzige Route"
    system = ("Du bist Jury fuer BSt-Next-Bilder. Waehle die Route, die am besten zur Marke passt: ruhig, klar, "
              "ein Hauptmotiv, Platz fuer die Headline, keine Schrift im Bild, keine Tabus. TABUS: " + TABUS)
    user = "Thema: %s\n" % thema + "\n".join("%d) %s | %s | %s" % (i, r.titel, r.kategorie, r.szene)
                                              for i, r in enumerate(routen))
    w = llm(system, user, Wahl)
    i = w.gewinner if 0 <= w.gewinner < len(routen) else 0
    return i, w.begruendung


def bildprompt(route):
    """Deterministischer Bildprompt: Szene der Route + fester Stil-/Tabu-Zusatz."""
    return "%s %s" % (route.szene.strip(), STIL_ZUSATZ)


def qa_pruefen(bild, llm):
    Route, Routen, Wahl, QA = _modelle()
    system = ("Du pruefst ein KI-Bild fuer BSt Next gegen die Vermeidungsliste. Antworte bestanden=false, wenn "
              "irgendetwas davon zu sehen ist (und nenne es unter probleme). Liste: " + TABUS +
              " Zusatz: lesbare Buchstaben/Zahlen im Bild, verzerrte Haende/Gesichter, Wasserzeichen. "
              "Sonst bestanden=true.")
    return llm(system, "Pruefe das Bild.", QA, bild=bild)


def erzeuge_szene(thema, weisse_zeilen, lime_zeilen, fmt, motiv, ziel_pfad, *, llm=None, bild_fn=None,
                  versuche=2):
    """Erzeugt den fertigen Beitrag (Foto + Headline + Logo) und gibt ein Protokoll zurueck:
    {'pfad', 'route', 'kategorie', 'prompt', 'jury', 'qa': [...], 'versuche'}.
    Wirft RuntimeError, wenn auch nach 'versuche' Bildern die QA nicht besteht."""
    if fmt not in BILD_GROESSEN:
        raise ValueError("Format fuer Foto-Look: quadrat oder hochformat")
    llm = llm or _llm_parse
    bild_fn = bild_fn or _bild_erzeugen
    headline = " ".join(list(weisse_zeilen) + list(lime_zeilen))
    kachel.pruefe_zeilen(weisse_zeilen, lime_zeilen, fmt)       # fruh fehlschlagen, bevor Kosten entstehen
    routen = routen_erzeugen(thema, headline, motiv, llm)
    idx, jury = route_waehlen(routen, thema, llm)
    reihenfolge = [idx] + [i for i in range(len(routen)) if i != idx]
    protokoll = {"jury": jury, "qa": [], "versuche": 0}
    for n, ri in enumerate(reihenfolge[:max(1, versuche)]):
        route = routen[ri]
        prompt = bildprompt(route)
        foto = bild_fn(prompt, BILD_GROESSEN[fmt])
        qa = qa_pruefen(foto, llm)
        protokoll["versuche"] = n + 1
        protokoll["qa"].append({"route": route.titel, "bestanden": bool(qa.bestanden),
                                "probleme": list(qa.probleme)})
        if qa.bestanden:
            os.makedirs(os.path.dirname(ziel_pfad) or ".", exist_ok=True)
            kachel.render_foto(foto, weisse_zeilen, lime_zeilen, ziel_pfad, fmt)
            protokoll.update({"pfad": ziel_pfad, "route": route.titel, "kategorie": route.kategorie,
                              "prompt": prompt})
            return protokoll
    raise RuntimeError("Bild-Pruefung nicht bestanden: %s" % "; ".join(
        "; ".join(q["probleme"]) or "ohne Angabe" for q in protokoll["qa"]))
