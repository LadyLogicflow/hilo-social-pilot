# -*- coding: utf-8 -*-
"""Tests fuer #163: /vorschau rendert comic_strip als Karussell (3 gecachte Panels je Stelle)
statt eines falschen, teuren Einzelbildes. Beweist die Verdrahtung ohne echte KI-/Bild-APIs:

  1. comic_strip-Entwurf + Stelle mit Berater-Ref: /vorschau nutzt render_slides_fuer_stelle
     (NICHT render_fuer_stelle - per Spy geprueft); das item traegt 3 Panel-URLs.
  2. Serve-Route /preview-strip/<eid>/<sid>/<idx>: liefert die Panels mit Rolle freigeber (200),
     404 bei fehlender Datei, und ist ohne Login / mit zu niedriger Rolle gesperrt (kein 200).
  3. Anderer Stil (standard): /vorschau nutzt weiter render_fuer_stelle, ein Bild (unveraendert).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/vp-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_vorschau_comic_strip.py
"""
import os
import sys
import json as _json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import personalisierung
import web

_PASS = []


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    _PASS.append(msg)
    print("  OK:", msg)


def _dummy_png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (32, 32), (160, 200, 180)).save(path)
    return path


def _client(rolle="freigeber"):
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = rolle
    return c


def _neuer_entwurf(text_dict, status="freigegeben"):
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(text, status) VALUES (?, ?)",
                           (_json.dumps(text_dict), status))
        conn.commit()
        return cur.lastrowid


def _stelle(name, berater=True):
    ref = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_%s.png" % name)) if berater else None
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO beratungsstellen(name, ort, aktiv, fb_seite, berater_comic) VALUES (?,?,1,?,?)",
            (name, "Musterstadt", "fbpage_%s" % name, ref))
        conn.commit()
        return cur.lastrowid


def _panels3(tag):
    return [_dummy_png(os.path.join(bildmotiv.DATA_DIR, "bilder", "vp_%s_%d.png" % (tag, i)))
            for i in range(3)]


# --- 1) comic_strip -> render_slides_fuer_stelle, 3 Panel-URLs, NICHT render_fuer_stelle ------
def test_1_comic_strip_karussell():
    sid = _stelle("Strip163")
    eid = _neuer_entwurf({"ueberschrift": "STRIP-163", "bild_stil": "comic_strip"})
    panels = _panels3("s163")

    aufrufe = {"slides": 0, "single": 0}

    def _fake_slides(fields, stelle, out_dir, prefix):
        aufrufe["slides"] += 1
        return fields, list(panels)

    def _spy_single(fields, stelle, out_path):
        aufrufe["single"] += 1
        _dummy_png(out_path)
        return fields, out_path

    orig_slides = personalisierung.render_slides_fuer_stelle
    orig_single = personalisierung.render_fuer_stelle
    personalisierung.render_slides_fuer_stelle = _fake_slides
    personalisierung.render_fuer_stelle = _spy_single
    c = _client()
    try:
        r = c.post("/vorschau/%d" % eid, data={"stelle_id": str(sid)})
    finally:
        personalisierung.render_slides_fuer_stelle = orig_slides
        personalisierung.render_fuer_stelle = orig_single

    if r.status_code != 200:
        _fail("/vorschau (comic_strip) rendert nicht (Status %s)" % r.status_code)
    if aufrufe["slides"] != 1:
        _fail("render_slides_fuer_stelle wurde nicht genau einmal genutzt: %r" % aufrufe)
    if aufrufe["single"] != 0:
        _fail("render_fuer_stelle (Einzelbild-Weg) wurde faelschlich aufgerufen: %r" % aufrufe)
    html = r.get_data(as_text=True)
    for idx in range(3):
        if ("/preview-strip/%d/%d/%d" % (eid, sid, idx)) not in html:
            _fail("Vorschau zeigt Panel-URL %d nicht" % idx)
    if ("/preview-bild/%d/%d" % (eid, sid)) in html:
        _fail("Comic-Strip-Vorschau zeigt faelschlich das Einzel-Vorschaubild /preview-bild")
    _ok("#163 /vorschau(comic_strip): nutzt render_slides_fuer_stelle (nicht render_fuer_stelle); 3 Panel-URLs")
    return eid, sid, panels


# --- 2) Serve-Route /preview-strip: Schutzstufe + 200 + 404 ----------------------------------
def test_2_serve_route(eid, sid, panels):
    c = _client("freigeber")
    for idx in range(3):
        r = c.get("/preview-strip/%d/%d/%d" % (eid, sid, idx))
        if r.status_code != 200:
            _fail("Panel %d wurde nicht ausgeliefert (Status %s)" % (idx, r.status_code))
        if r.mimetype != "image/png":
            _fail("Panel %d falscher mimetype: %r" % (idx, r.mimetype))
    # fehlende Datei / Index -> 404
    if c.get("/preview-strip/%d/%d/9" % (eid, sid)).status_code != 404:
        _fail("nicht vorhandenes Panel lieferte nicht 404")
    # ohne Login -> kein 200 (Redirect zur Anmeldung)
    anon = web.app.test_client()
    if anon.get("/preview-strip/%d/%d/0" % (eid, sid)).status_code == 200:
        _fail("Serve-Route ist ohne Login oeffentlich zugaenglich (200)")
    # zu niedrige Rolle (redakteur) -> kein 200 (403)
    low = _client("redakteur")
    if low.get("/preview-strip/%d/%d/0" % (eid, sid)).status_code == 200:
        _fail("Serve-Route ist mit zu niedriger Rolle (redakteur) zugaenglich (200)")
    _ok("#163 /preview-strip: 200 mit Rolle freigeber; 404 bei fehlender Datei; gesperrt ohne Login / redakteur")


# --- 3) anderer Stil (standard): weiter render_fuer_stelle, ein Bild --------------------------
def test_3_standard_unveraendert():
    sid = _stelle("Std163")
    eid = _neuer_entwurf({"ueberschrift": "STD-163", "bild_stil": "standard"})

    aufrufe = {"slides": 0, "single": 0}

    def _spy_slides(fields, stelle, out_dir, prefix):
        aufrufe["slides"] += 1
        return fields, []

    def _fake_single(fields, stelle, out_path):
        aufrufe["single"] += 1
        _dummy_png(out_path)
        return fields, out_path

    orig_slides = personalisierung.render_slides_fuer_stelle
    orig_single = personalisierung.render_fuer_stelle
    personalisierung.render_slides_fuer_stelle = _spy_slides
    personalisierung.render_fuer_stelle = _fake_single
    c = _client()
    try:
        r = c.post("/vorschau/%d" % eid, data={"stelle_id": str(sid)})
    finally:
        personalisierung.render_slides_fuer_stelle = orig_slides
        personalisierung.render_fuer_stelle = orig_single

    if r.status_code != 200:
        _fail("/vorschau (standard) rendert nicht (Status %s)" % r.status_code)
    if aufrufe["single"] != 1:
        _fail("render_fuer_stelle wurde nicht genau einmal genutzt (standard): %r" % aufrufe)
    if aufrufe["slides"] != 0:
        _fail("render_slides_fuer_stelle wurde faelschlich aufgerufen (standard): %r" % aufrufe)
    html = r.get_data(as_text=True)
    if ("/preview-bild/%d/%d" % (eid, sid)) not in html:
        _fail("Standard-Vorschau zeigt das Einzel-Vorschaubild /preview-bild nicht")
    if ("/preview-strip/%d/" % eid) in html:
        _fail("Standard-Vorschau zeigt faelschlich Panel-URLs")
    _ok("#163 /vorschau(standard): weiter render_fuer_stelle, ein Bild (unveraendert)")


def main():
    db.init_db()
    eid, sid, panels = test_1_comic_strip_karussell()
    test_2_serve_route(eid, sid, panels)
    test_3_standard_unveraendert()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
