# -*- coding: utf-8 -*-
"""Tests fuer das Comic-Berater-Setup (Stil "Comic Beratung", Schritt 1).

Beweist die VERDRAHTUNG (KEINE echten externen KI-/Bild-APIs, kein Netz - alles gemockt):

  1. DB-Migration: die Spalte beratungsstellen.berater_comic existiert nach init_db.
  2. bildmotiv.erzeuge_berater_comic: erzeuge_comic_bild_ref gepatcht (Dummy-Bytes) ->
     refs == [foto_path, STIL_REF_PATH], Prompt == BERATER_PORTRAIT_PROMPT; Datei geschrieben,
     Pfad zurueck. Ohne Foto -> None.
  3. Route POST /berater-comic/<id>: erzeuge_berater_comic gemockt -> berater_comic gesetzt,
     Erfolgs-flash. Ohne Leitungs-Foto -> Hinweis-flash, berater_comic bleibt NULL.
  4. Serve-Route GET /berater-comic-bild/<id>: ohne Login -> nicht erlaubt (Redirect);
     mit Login -> 200 + Datei-Bytes.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/berater-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_berater_comic.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import web
import bildmotiv
from config import DATA_DIR


_PASS = []


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    _PASS.append(msg)
    print("  OK:", msg)


def _client(rolle="admin", login=True):
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    if login:
        with c.session_transaction() as sess:
            sess["user"] = "tester"
            sess["rolle"] = rolle
    return c


def _seed_stelle(name, portrait=None):
    """Legt eine Beratungsstelle an (optional mit portrait_pfad) und liefert die id."""
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO beratungsstellen(name, ort, aktiv, portrait_pfad) VALUES (?,?,1,?)",
            (name, "Teststadt", portrait))
        conn.commit()
        return cur.lastrowid


def _berater_comic(sid):
    with db.get_conn() as conn:
        return conn.execute("SELECT berater_comic FROM beratungsstellen WHERE id=?",
                            (sid,)).fetchone()["berater_comic"]


# ---------------------------------------------------------------------------
def test_1_db_spalte_vorhanden():
    """init_db legt die additive Spalte berater_comic in beratungsstellen an."""
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(beratungsstellen)")]
    if "berater_comic" not in cols:
        _fail("Spalte berater_comic fehlt nach der Migration: %r" % cols)
    _ok("DB-Migration: beratungsstellen.berater_comic vorhanden")


def test_2_erzeuge_berater_comic():
    """erzeuge_berater_comic: korrekte refs/prompt, Datei geschrieben, Pfad zurueck; ohne Foto None."""
    # Echtes (kleines) Quell-Foto anlegen, damit os.path.exists(foto) True ist.
    foto_dir = os.path.join(DATA_DIR, "portraits")
    os.makedirs(foto_dir, exist_ok=True)
    foto_path = os.path.join(foto_dir, "stelle_4242.png")
    with open(foto_path, "wb") as fh:
        fh.write(b"FAKE-FOTO-BYTES")

    captured = {"refs": None, "prompt": None}

    def _fake_ref(prompt, refs):
        captured["prompt"] = prompt
        captured["refs"] = list(refs)
        return b"COMIC-PNG-BYTES"

    orig = bildmotiv.erzeuge_comic_bild_ref
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    try:
        pfad = bildmotiv.erzeuge_berater_comic(foto_path)
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig

    if captured["refs"] != [foto_path, bildmotiv.STIL_REF_PATH]:
        _fail("refs != [foto_path, STIL_REF_PATH]: %r" % captured["refs"])
    if captured["prompt"] != bildmotiv.BERATER_PORTRAIT_PROMPT:
        _fail("Prompt != BERATER_PORTRAIT_PROMPT: %r" % captured["prompt"])
    if not pfad or not os.path.exists(pfad):
        _fail("erzeuge_berater_comic lieferte keinen existierenden Pfad: %r" % pfad)
    if os.path.realpath(os.path.dirname(pfad)) != os.path.realpath(os.path.join(DATA_DIR, "berater")):
        _fail("Comic-Datei liegt nicht unter DATA_DIR/berater: %r" % pfad)
    if os.path.basename(pfad) != "comic_4242.png":
        _fail("Comic-Datei heisst nicht comic_<id>.png: %r" % os.path.basename(pfad))
    with open(pfad, "rb") as fh:
        if fh.read() != b"COMIC-PNG-BYTES":
            _fail("Comic-Datei enthaelt nicht die gelieferten Bytes")

    # Ohne (existierendes) Foto -> None, ohne erzeuge_comic_bild_ref aufzurufen.
    called = {"x": False}

    def _fake_ref2(prompt, refs):
        called["x"] = True
        return b"X"

    bildmotiv.erzeuge_comic_bild_ref = _fake_ref2
    try:
        r = bildmotiv.erzeuge_berater_comic(os.path.join(foto_dir, "gibt_es_nicht.png"))
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig
    if r is not None:
        _fail("erzeuge_berater_comic ohne Foto lieferte nicht None: %r" % r)
    if called["x"]:
        _fail("erzeuge_berater_comic ohne Foto rief faelschlich erzeuge_comic_bild_ref auf")
    _ok("erzeuge_berater_comic: refs/prompt korrekt, Datei geschrieben (comic_<id>.png), ohne Foto None")


def test_3_route_erzeugen():
    """POST /berater-comic/<id>: mit Leitungs-Foto -> berater_comic gesetzt; ohne Foto -> Hinweis."""
    # a) MIT Foto: erzeuge_berater_comic gemockt -> berater_comic wird gesetzt.
    foto_dir = os.path.join(DATA_DIR, "portraits")
    os.makedirs(foto_dir, exist_ok=True)
    ber_dir = os.path.join(DATA_DIR, "berater")
    os.makedirs(ber_dir, exist_ok=True)

    sid = _seed_stelle("Stelle-mit-Foto")
    foto_path = os.path.join(foto_dir, "stelle_%d.png" % sid)
    with open(foto_path, "wb") as fh:
        fh.write(b"FOTO")
    with db.get_conn() as conn:
        conn.execute("UPDATE beratungsstellen SET portrait_pfad=? WHERE id=?", (foto_path, sid))
        conn.commit()

    comic_path = os.path.join(ber_dir, "comic_%d.png" % sid)
    with open(comic_path, "wb") as fh:
        fh.write(b"COMICPNG")

    captured = {"foto": None}

    def _fake_erz(foto):
        captured["foto"] = foto
        return comic_path

    # Die Route importiert bildmotiv lokal (dasselbe Modulobjekt) und ruft
    # bildmotiv.erzeuge_berater_comic -> hier am Modul patchen genuegt.
    import bildmotiv as _bm
    orig_fn = _bm.erzeuge_berater_comic
    _bm.erzeuge_berater_comic = _fake_erz
    try:
        c = _client(rolle="admin")
        resp = c.post("/berater-comic/%d" % sid, follow_redirects=True)
    finally:
        _bm.erzeuge_berater_comic = orig_fn

    if resp.status_code != 200:
        _fail("POST /berater-comic (mit Foto) Status %s" % resp.status_code)
    if captured["foto"] != foto_path:
        _fail("Route uebergab nicht das portrait_pfad-Foto: %r" % captured["foto"])
    if _berater_comic(sid) != comic_path:
        _fail("berater_comic wurde nicht gesetzt: %r" % _berater_comic(sid))
    body = resp.get_data(as_text=True)
    if "Comic-Berater erzeugt" not in body:
        _fail("Erfolgs-flash fehlt in der Antwort")

    # b) OHNE Foto: Hinweis-flash, berater_comic bleibt NULL.
    sid2 = _seed_stelle("Stelle-ohne-Foto")
    c = _client(rolle="admin")
    resp2 = c.post("/berater-comic/%d" % sid2, follow_redirects=True)
    if resp2.status_code != 200:
        _fail("POST /berater-comic (ohne Foto) Status %s" % resp2.status_code)
    if _berater_comic(sid2) is not None:
        _fail("berater_comic wurde ohne Foto gesetzt: %r" % _berater_comic(sid2))
    if "kein Leitungs-Foto" not in resp2.get_data(as_text=True):
        _fail("Hinweis-flash 'kein Leitungs-Foto' fehlt")
    _ok("POST /berater-comic: mit Foto berater_comic gesetzt+flash; ohne Foto Hinweis, kein Wert")


def test_4_serve_route_login_geschuetzt():
    """GET /berater-comic-bild/<id>: ohne Login nicht erlaubt; mit Login 200 + Bytes."""
    ber_dir = os.path.join(DATA_DIR, "berater")
    os.makedirs(ber_dir, exist_ok=True)
    sid = _seed_stelle("Stelle-serve")
    comic_path = os.path.join(ber_dir, "comic_%d.png" % sid)
    with open(comic_path, "wb") as fh:
        fh.write(b"SERVE-COMIC-BYTES")
    with db.get_conn() as conn:
        conn.execute("UPDATE beratungsstellen SET berater_comic=? WHERE id=?", (comic_path, sid))
        conn.commit()

    # a) OHNE Login -> nicht erlaubt (Redirect zum Login oder 401/403, jedenfalls kein 200).
    anon = _client(login=False)
    r_anon = anon.get("/berater-comic-bild/%d" % sid)
    if r_anon.status_code == 200:
        _fail("Serve-Route lieferte OHNE Login 200 (Gesicht oeffentlich!) - status %s" % r_anon.status_code)
    if r_anon.status_code not in (301, 302, 401, 403):
        _fail("Serve-Route ohne Login: unerwarteter Status %s" % r_anon.status_code)

    # b) MIT Login -> 200 + die Datei-Bytes.
    c = _client(rolle="redakteur")  # login_required, beliebige Rolle genuegt
    r = c.get("/berater-comic-bild/%d" % sid)
    if r.status_code != 200:
        _fail("Serve-Route mit Login lieferte nicht 200: %s" % r.status_code)
    if r.get_data() != b"SERVE-COMIC-BYTES":
        _fail("Serve-Route lieferte nicht die Comic-Bytes")

    # c) Stelle ohne berater_comic -> 404.
    sid2 = _seed_stelle("Stelle-serve-leer")
    r404 = c.get("/berater-comic-bild/%d" % sid2)
    if r404.status_code != 404:
        _fail("Serve-Route ohne berater_comic lieferte nicht 404: %s" % r404.status_code)
    _ok("Serve-Route: ohne Login gesperrt, mit Login 200+Bytes, ohne Datei 404")


def main():
    db.init_db()
    test_1_db_spalte_vorhanden()
    test_2_erzeuge_berater_comic()
    test_3_route_erzeugen()
    test_4_serve_route_login_geschuetzt()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
