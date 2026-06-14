# -*- coding: utf-8 -*-
"""Personalisierung eines Beitrags je Beratungsstelle: gleiches Bild, aber der CTA-Text
im Bild nennt die Stelle, und der Begleittext bekommt einen lokalen Bezug + Buchungslink.
Deterministisch (kein KI-Token)."""
import os


def fuer_stelle(fields, stelle):
    """Gibt eine personalisierte Kopie der Beitrags-Felder fuer eine Beratungsstelle zurueck.
    Deterministisch: nutzt ausschliesslich echte Stammdaten (Ort, Leitung, Buchungslink) und
    erfindet nichts. Der Begleittext bekommt einen persoenlichen, lokalen Bezug."""
    f = dict(fields)
    ort = (stelle["ort"] or "").strip() if _has(stelle, "ort") else ""
    leitung = (stelle["leitung"] or "").strip() if _has(stelle, "leitung") else ""
    buchung = (stelle["buchungs_url"] or "").strip() if _has(stelle, "buchungs_url") else ""
    if ort:
        f["cta"] = "Jetzt Termin bei Ihrer HILO-Beratungsstelle %s vereinbaren" % ort
        # Persoenlicher Begleittext: nennt die Leitung, falls hinterlegt, sonst die Stelle.
        if leitung:
            satz = ("%s von Ihrer HILO-Beratungsstelle in %s bespricht Ihre steuerliche "
                    "Situation gerne persönlich mit Ihnen." % (leitung, ort))
        else:
            satz = "Ihre HILO-Beratungsstelle in %s berät Sie gerne persönlich." % ort
        if buchung:
            # ohne abschliessenden Punkt, damit der Link nicht bricht
            satz += " Termin vereinbaren: %s" % buchung
        f["caption"] = ((fields.get("caption") or "").strip() + " " + satz).strip()
    return f


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
    photo = bildmotiv.ensure_photo(f.get("bild_motiv"))
    slogan = bildgen.pick_slogan(f.get("slogan"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bildgen.render(f, photo, slogan, out_path, portrait=_portrait(stelle))
    return f, out_path


def render_slides_fuer_stelle(fields, stelle, out_dir, prefix):
    """Rendert ein Karussell mit personalisiertem CTA (gleiches Foto/Design je Stelle).
    Liefert (felder, [pfade]). Kreisportraet der Stelle ersetzt ggf. den blauen Slogan-Punkt."""
    import bildgen, bildmotiv
    f = fuer_stelle(fields, stelle)
    photo = bildmotiv.ensure_photo(f.get("bild_motiv"))
    slogan = bildgen.pick_slogan(f.get("slogan"))
    paths = bildgen.render_slides(f, photo, slogan, out_dir, prefix, portrait=_portrait(stelle))
    return f, paths


def _has(row, key):
    try:
        return key in row.keys()
    except Exception:
        return key in row
