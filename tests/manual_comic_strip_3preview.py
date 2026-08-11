# -*- coding: utf-8 -*-
"""Tests fuer #157: alle DREI Comic-Strip-Panels in der Beitrags-Vorschau (Erzeugung/Pool/
Einplanung) statt nur einem. Beweist die Verdrahtung (KEINE echten externen KI-/Bild-APIs):

  1. /bild-generieren (comic_strip) persistiert die 3 Panel-Pfade als data['strip_panels']
     im Entwurf-JSON (ensure_comic_strip_bilder gemockt -> 3 Pfade). bild_pfad bleibt Panel 1.
  2. Nur tatsaechlich vorhandene Pfade landen in strip_panels (nicht-existente werden gefiltert).
  3. Ein ANDERER Stil (ki_tafel) entfernt vorhandene strip_panels wieder (Vorschau zeigt dann
     das Einzelbild, nicht den alten Strip).
  4. Serve-Route /strip-panel/<eid>/<idx>: liefert vorhandene Panels aus (login noetig), bei
     ungueltigem Index/fehlender Datei -> 404; ohne Login -> kein 200 (gleiche Schutzstufe /bild).
  5. Flask-Render der drei Vorschau-Bloecke (Entwuerfe/Pool/Einplanung): mit strip_panels
     erscheinen 3 /strip-panel-Verweise, ohne bleibt es beim Einzelbild /bild.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/p3-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/manual_comic_strip_3preview.py
"""
import os
import sys
import json as _json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
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
    Image.new("RGB", (32, 32), (180, 200, 160)).save(path)
    return path


def _client():
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = "admin"
    return c


def _neuer_entwurf(text_dict, status="entwurf"):
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(text, status) VALUES (?, ?)",
                           (_json.dumps(text_dict), status))
        conn.commit()
        return cur.lastrowid


def _panels3():
    return [_dummy_png(os.path.join(bildmotiv.DATA_DIR, "bilder", "p3_panel_%d.png" % i))
            for i in range(3)]


# --- 1) /bild-generieren comic_strip persistiert 3 Panels in strip_panels ---------------------
def test_1_persistiert_strip_panels():
    # aktive Stelle MIT Berater-Referenz, damit der comic_strip-Zweig nicht vorzeitig abbricht
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_stelle_157.png"))
    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(name, ort, aktiv, berater_comic) VALUES (?,?,1,?)",
                     ("Teststelle 157", "Musterstadt", berater))
        conn.commit()
    eid = _neuer_entwurf({"ueberschrift": "URSPRUNG-157"})
    panels = _panels3()

    def _fake_ensure(fields, berater_ref):
        return list(panels)

    orig = bildmotiv.ensure_comic_strip_bilder
    bildmotiv.ensure_comic_strip_bilder = _fake_ensure
    c = _client()
    try:
        c.post("/bild-generieren/%d" % eid,
               data={"bild_stil": "comic_strip", "zurueck": "entwuerfe"})
    finally:
        bildmotiv.ensure_comic_strip_bilder = orig

    with db.get_conn() as conn:
        row = conn.execute("SELECT text, bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    data = _json.loads(row["text"])
    if data.get("strip_panels") != panels:
        _fail("strip_panels wurde nicht als 3er-Liste persistiert: %r" % (data.get("strip_panels"),))
    if len(data.get("strip_panels") or []) != 3:
        _fail("strip_panels ist keine 3er-Liste: %r" % (data.get("strip_panels"),))
    # bild_pfad bleibt Panel 1 (Einzel-Fallback)
    if row["bild_pfad"] != panels[0]:
        _fail("bild_pfad ist nicht Panel 1: %r" % row["bild_pfad"])
    _ok("#157 /bild-generieren(comic_strip): data['strip_panels'] = 3 Pfade; bild_pfad = Panel 1")
    return eid


# --- 2) nur existierende Pfade landen in strip_panels ----------------------------------------
def test_2_nur_vorhandene_pfade():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_stelle_157b.png"))
    with db.get_conn() as conn:
        # Stelle existiert aus Test 1 bereits; egal - Hauptsache eine aktive mit Berater vorhanden
        conn.execute("INSERT OR IGNORE INTO beratungsstellen(name, ort, aktiv, berater_comic) "
                     "VALUES (?,?,1,?)", ("Teststelle 157b", "Musterstadt", berater))
        conn.commit()
    eid = _neuer_entwurf({"ueberschrift": "URSPRUNG-157B"})
    gute = _panels3()
    fehlend = os.path.join(bildmotiv.DATA_DIR, "bilder", "p3_nicht_da.png")
    if os.path.exists(fehlend):
        os.remove(fehlend)

    def _fake_ensure(fields, berater_ref):
        # Panel 1 real, Panel 2 fehlend, Panel 3 real -> nur die zwei realen duerfen bleiben
        return [gute[0], fehlend, gute[2]]

    orig = bildmotiv.ensure_comic_strip_bilder
    bildmotiv.ensure_comic_strip_bilder = _fake_ensure
    c = _client()
    try:
        c.post("/bild-generieren/%d" % eid, data={"bild_stil": "comic_strip", "zurueck": "entwuerfe"})
    finally:
        bildmotiv.ensure_comic_strip_bilder = orig

    with db.get_conn() as conn:
        data = _json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])
    if data.get("strip_panels") != [gute[0], gute[2]]:
        _fail("nicht-existente Panel-Pfade wurden nicht gefiltert: %r" % (data.get("strip_panels"),))
    _ok("#157 strip_panels enthaelt nur tatsaechlich vorhandene Panel-Pfade")


# --- 3) anderer Stil entfernt strip_panels ---------------------------------------------------
def test_3_anderer_stil_loescht_strip_panels():
    panels = _panels3()
    eid = _neuer_entwurf({"ueberschrift": "URSPRUNG-157C", "strip_panels": panels})

    # ki_tafel-Zweig: ensure_photo_fuer + bildgen.render mocken (keine externe KI / kein Asset noetig)
    orig_photo = bildmotiv.ensure_photo_fuer
    orig_render = web.bildgen.render
    bildmotiv.ensure_photo_fuer = lambda data: None
    web.bildgen.render = lambda *a, **k: None
    c = _client()
    try:
        c.post("/bild-generieren/%d" % eid, data={"bild_stil": "ki_tafel", "zurueck": "entwuerfe"})
    finally:
        bildmotiv.ensure_photo_fuer = orig_photo
        web.bildgen.render = orig_render

    with db.get_conn() as conn:
        data = _json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])
    if "strip_panels" in data:
        _fail("strip_panels wurde beim Wechsel auf ki_tafel nicht entfernt: %r" % (data.get("strip_panels"),))
    _ok("#157 Wechsel auf anderen Stil (ki_tafel) entfernt strip_panels wieder")


# --- 4) Serve-Route /strip-panel/<eid>/<idx> -------------------------------------------------
def test_4_serve_route():
    panels = _panels3()
    eid = _neuer_entwurf({"ueberschrift": "SERVE-157", "strip_panels": panels})
    c = _client()
    for i in range(3):
        r = c.get("/strip-panel/%d/%d" % (eid, i))
        if r.status_code != 200:
            _fail("Panel %d wurde nicht ausgeliefert (Status %s)" % (i, r.status_code))
        if r.mimetype != "image/png":
            _fail("Panel %d falscher mimetype: %r" % (i, r.mimetype))
    # Index ausserhalb des Bereichs -> 404
    if c.get("/strip-panel/%d/3" % eid).status_code != 404:
        _fail("Index 3 (out of range) lieferte nicht 404")
    # Entwurf ohne strip_panels -> 404
    eid2 = _neuer_entwurf({"ueberschrift": "OHNE-STRIP-157"})
    if c.get("/strip-panel/%d/0" % eid2).status_code != 404:
        _fail("Entwurf ohne strip_panels lieferte nicht 404")
    # fehlende Datei -> 404
    weg = panels[1]
    os.remove(weg)
    if c.get("/strip-panel/%d/1" % eid).status_code != 404:
        _fail("fehlende Panel-Datei lieferte nicht 404")
    _dummy_png(weg)  # wiederherstellen fuer evtl. Folgechecks
    # ohne Login -> gleiche Schutzstufe wie /bild (kein 200)
    anon = web.app.test_client()
    if anon.get("/strip-panel/%d/0" % eid).status_code == 200:
        _fail("Serve-Route ist ohne Login oeffentlich zugaenglich (200)")
    _ok("#157 /strip-panel liefert vorhandene Panels (login); 404 bei Index/Datei fehlt; nicht oeffentlich")


# --- 5) Flask-Render der drei Vorschau-Bloecke -----------------------------------------------
def test_5_render_entwuerfe():
    panels = _panels3()
    eid_strip = _neuer_entwurf({"ueberschrift": "RENDER-STRIP-157", "strip_panels": panels})
    eid_plain = _neuer_entwurf({"ueberschrift": "RENDER-PLAIN-157"})
    c = _client()
    r = c.get("/entwuerfe")
    if r.status_code != 200:
        _fail("/entwuerfe rendert nicht (Status %s)" % r.status_code)
    html = r.get_data(as_text=True)
    for i in range(3):
        if ("/strip-panel/%d/%d" % (eid_strip, i)) not in html:
            _fail("/entwuerfe zeigt Panel-Verweis %d fuer den Strip-Entwurf nicht" % i)
    # Der Strip-Entwurf darf NICHT sein Einzelbild /bild zeigen; der plain-Entwurf schon.
    if ("/bild/%d" % eid_strip) in html:
        _fail("Strip-Entwurf zeigt faelschlich das Einzel-Vorschaubild /bild")
    if ("/bild/%d" % eid_plain) not in html:
        _fail("plain-Entwurf zeigt das Einzel-Vorschaubild /bild nicht")
    if ("/strip-panel/%d/" % eid_plain) in html:
        _fail("plain-Entwurf zeigt faelschlich Panel-Verweise")
    _ok("/entwuerfe: Strip-Entwurf -> 3 /strip-panel-Verweise; plain-Entwurf -> Einzelbild /bild")


def test_6_render_einplanung():
    panels = _panels3()
    eid = _neuer_entwurf({"ueberschrift": "RENDER-EINPL-157", "strip_panels": panels},
                         status="freigegeben")
    with db.get_conn() as conn:
        conn.execute("UPDATE entwuerfe SET format='karussell' WHERE id=?", (eid,))
        conn.commit()
    c = _client()
    r = c.get("/einplanung")
    if r.status_code != 200:
        _fail("/einplanung rendert nicht (Status %s)" % r.status_code)
    html = r.get_data(as_text=True)
    for i in range(3):
        if ("/strip-panel/%d/%d" % (eid, i)) not in html:
            _fail("/einplanung zeigt Panel-Verweis %d nicht" % i)
    _ok("/einplanung: Strip-Beitrag -> 3 /strip-panel-Verweise")


def test_7_render_pool():
    panels = _panels3()
    eid = _neuer_entwurf({"ueberschrift": "RENDER-POOL-157", "strip_panels": panels},
                         status="freigegeben")
    with db.get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO pool(entwurf_id, aktiv, freigegeben_am) "
                     "VALUES (?, 1, datetime('now'))", (eid,))
        conn.commit()
    c = _client()
    r = c.get("/pool")
    if r.status_code != 200:
        _fail("/pool rendert nicht (Status %s)" % r.status_code)
    html = r.get_data(as_text=True)
    for i in range(3):
        if ("/strip-panel/%d/%d" % (eid, i)) not in html:
            _fail("/pool zeigt Panel-Verweis %d nicht" % i)
    _ok("/pool: Strip-Beitrag -> 3 /strip-panel-Verweise")


def main():
    db.init_db()
    test_1_persistiert_strip_panels()
    test_2_nur_vorhandene_pfade()
    test_3_anderer_stil_loescht_strip_panels()
    test_4_serve_route()
    test_5_render_entwuerfe()
    test_6_render_einplanung()
    test_7_render_pool()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
