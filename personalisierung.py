# -*- coding: utf-8 -*-
"""Personalisierung eines Beitrags je Beratungsstelle: gleiches Bild, aber der CTA-Text
im Bild nennt die Stelle, und der Begleittext bekommt einen lokalen Bezug + Buchungslink.
Deterministisch (kein KI-Token)."""
import os
import re


def buchungslink(stelle):
    """Buchungs-URL der Beratungsstelle (oder '')."""
    return (stelle["buchungs_url"] or "").strip() if _has(stelle, "buchungs_url") else ""


def _local_satz(stelle):
    """Persoenlicher, lokaler Satz (Leitung/Ort) fuer den Begleittext (oder '' ohne Ort) - OHNE Link.
    Den Link bzw. den kanalabhaengigen Termin-Hinweis ergaenzt personalisiere_caption."""
    ort = (stelle["ort"] or "").strip() if _has(stelle, "ort") else ""
    if not ort:
        return ""
    leitung = (stelle["leitung"] or "").strip() if _has(stelle, "leitung") else ""
    if leitung:
        return ("%s von Ihrer HILO-Beratungsstelle in %s bespricht Ihre steuerliche "
                "Situation gerne persönlich mit Ihnen." % (leitung, ort))
    return "Ihre HILO-Beratungsstelle in %s berät Sie gerne persönlich." % ort


def _split_hashtags(text):
    """Trennt einen abschliessenden Hashtag-Block (#... am Ende) vom Haupttext ab.
    Nur wenn der Block klar abgesetzt ist: durch einen Zeilenumbruch ODER mit mindestens zwei
    Hashtags. So wird ein einzelnes Hashtag mitten im Satz (z.B. '... unter dem Tag #steuern')
    NICHT zerrissen. Rueckgabe: (haupttext, hashtag_block) - hashtag_block '' wenn keiner."""
    text = (text or "").strip()
    m = re.search(r"(\s*)((?:#\S+\s*)+)$", text)
    if not m or m.start(2) == 0:
        return text, ""
    block = m.group(2).strip()
    abgesetzt = "\n" in m.group(1) or len(re.findall(r"#\S+", block)) >= 2
    if not abgesetzt:
        return text, ""
    return text[:m.start()].rstrip(), block


def personalisiere_caption(base, stelle, kanal=None):
    """Haengt den lokalen Satz (+ kanalabhaengigen Termin-Hinweis) an den Begleittext an - aber VOR
    einen evtl. vorhandenen Hashtag-Block. Der Termin-Hinweis wird NUR ergaenzt, wenn ein Buchungslink
    hinterlegt ist - so passt er immer zum tatsaechlich geposteten ersten Kommentar:
    Facebook -> 'Link im ersten Kommentar', Instagram -> 'in unserer Bio', sonst (WhatsApp/Default)
    der Buchungslink direkt im Text."""
    satz = _local_satz(stelle)
    if not satz:
        return (base or "").strip()
    link = buchungslink(stelle)
    if link:
        if kanal == "facebook":
            satz += " Den Link zum Termin findest du im ersten Kommentar."
        elif kanal == "instagram":
            satz += " Den Termin-Link findest du in unserer Bio."
        else:
            satz += " Termin vereinbaren: %s" % link
    haupt, tags = _split_hashtags(base)
    kombi = (haupt + " " + satz).strip() if haupt else satz
    return (kombi + "\n\n" + tags).strip() if tags else kombi


def caption_fuer_stelle(fields, stelle, kanal):
    """Kanalspezifischer, fuer die Beratungsstelle personalisierter Begleittext."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    base = caps.get(kanal) or fields.get("caption") or ""
    return personalisiere_caption(base, stelle, kanal)


def fuer_stelle(fields, stelle, kanal=None):
    """Gibt eine personalisierte Kopie der Beitrags-Felder fuer eine Beratungsstelle zurueck.
    Deterministisch: nutzt ausschliesslich echte Stammdaten (Ort, Leitung, Buchungslink) und
    erfindet nichts. Der CTA im Bild nennt den Ort; der Begleittext bekommt einen lokalen Bezug.
    Mit 'kanal' wird der passende kanalspezifische Begleittext gewaehlt (sonst der Default)."""
    f = dict(fields)
    ort = (stelle["ort"] or "").strip() if _has(stelle, "ort") else ""
    base = caption_fuer(fields, kanal)
    if ort:
        f["cta"] = "Jetzt Termin bei Ihrer HILO-Beratungsstelle %s vereinbaren" % ort
        f["ort"] = ort   # fuer den sichtbaren Ortsbezug im Bild
    f["caption"] = personalisiere_caption(base, stelle)
    return f


def caption_fuer(fields, kanal):
    """Liefert den kanalspezifischen Begleittext (Fallback: gemeinsame 'caption')."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    return (caps.get(kanal) or fields.get("caption") or "").strip()


def _portrait(stelle):
    """Pfad zum Kreisportraet der Stelle, falls hinterlegt und vorhanden - sonst None
    (dann zeigt das Bild den blauen Slogan-Punkt)."""
    p = (stelle["portrait_pfad"] or "").strip() if _has(stelle, "portrait_pfad") else ""
    return p if (p and os.path.exists(p)) else None


def render_fuer_stelle(fields, stelle, out_path):
    """Rendert das Bild mit personalisiertem CTA (gleiches Foto/Design). Liefert (felder, pfad).
    Hat die Stelle ein Kreisportraet hinterlegt, ersetzt es den blauen Slogan-Punkt."""
    import bildgen, bildmotiv
    f = fuer_stelle(fields, stelle)
    photo = bildmotiv.ensure_photo_fuer(f)
    slogan = bildgen.pick_slogan(f.get("slogan"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bildgen.render(f, photo, slogan, out_path, portrait=_portrait(stelle))
    return f, out_path


def render_slides_fuer_stelle(fields, stelle, out_dir, prefix):
    """Rendert ein Karussell mit personalisiertem CTA (gleiches Foto/Design je Stelle).
    Liefert (felder, [pfade]). Kreisportraet der Stelle ersetzt ggf. den blauen Slogan-Punkt."""
    import bildgen, bildmotiv
    f = fuer_stelle(fields, stelle)
    photo = bildmotiv.ensure_photo_fuer(f)
    slogan = bildgen.pick_slogan(f.get("slogan"))
    paths = bildgen.render_slides(f, photo, slogan, out_dir, prefix, portrait=_portrait(stelle))
    return f, paths


def _has(row, key):
    try:
        return key in row.keys()
    except Exception:
        return key in row
