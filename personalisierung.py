# -*- coding: utf-8 -*-
"""Personalisierung eines Beitrags je Beratungsstelle: gleiches Bild, aber der CTA-Text
im Bild nennt die Stelle, und der Begleittext bekommt einen lokalen Bezug + Buchungslink.
Deterministisch (kein KI-Token)."""
import os


def fuer_stelle(fields, stelle):
    """Gibt eine personalisierte Kopie der Beitrags-Felder fuer eine Beratungsstelle zurueck."""
    f = dict(fields)
    ort = (stelle["ort"] or "").strip() if _has(stelle, "ort") else ""
    buchung = (stelle["buchungs_url"] or "").strip() if _has(stelle, "buchungs_url") else ""
    if ort:
        f["cta"] = "Jetzt Termin bei Ihrer HILO-Beratungsstelle %s vereinbaren" % ort
        if buchung:
            # ohne abschliessenden Punkt, damit der Link nicht bricht
            zusatz = " Vereinbaren Sie Ihren Termin bei Ihrer HILO-Beratungsstelle in %s: %s" % (ort, buchung)
        else:
            zusatz = " Vereinbaren Sie Ihren Termin bei Ihrer HILO-Beratungsstelle in %s." % ort
        f["caption"] = ((fields.get("caption") or "").strip() + zusatz).strip()
    return f


def render_fuer_stelle(fields, stelle, out_path):
    """Rendert das Bild mit personalisiertem CTA (gleiches Foto/Design). Liefert (felder, pfad)."""
    import bildgen, bildmotiv
    f = fuer_stelle(fields, stelle)
    photo = bildmotiv.ensure_photo(f.get("bild_motiv"))
    slogan = bildgen.pick_slogan(f.get("slogan"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bildgen.render(f, photo, slogan, out_path)
    return f, out_path


def render_slides_fuer_stelle(fields, stelle, out_dir, prefix):
    """Rendert ein Karussell mit personalisiertem CTA (gleiches Foto/Design je Stelle).
    Liefert (felder, [pfade])."""
    import bildgen, bildmotiv
    f = fuer_stelle(fields, stelle)
    photo = bildmotiv.ensure_photo(f.get("bild_motiv"))
    slogan = bildgen.pick_slogan(f.get("slogan"))
    paths = bildgen.render_slides(f, photo, slogan, out_dir, prefix)
    return f, paths


def _has(row, key):
    try:
        return key in row.keys()
    except Exception:
        return key in row
