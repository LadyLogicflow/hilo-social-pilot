# -*- coding: utf-8 -*-
"""BSt-Next-Beitraege erscheinen NICHT in den HILO-Listen (Einplanung, Entwuerfe, Startseiten-Zaehler):
dort gaebe es Beratungsstellen-Auswahl und Pool-Knopf. Sie bleiben unter /bstnext bearbeitbar."""
import json
import os
import shutil
import tempfile

import pytest

import db
import web
from bstnext import routes as bs_routes

HILO_TITEL = "HILO-Beitrag-Sichtbar-4711"
BST_TITEL = "BSTNEXT-Beitrag-Versteckt-4712"


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-listen-")
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tmp, "test.db")
    db.init_db()
    monkeypatch.setitem(bs_routes._cfg, "data_dir", tmp)
    monkeypatch.setitem(bs_routes._cfg, "pages_fn", lambda: ([], None))
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "test-admin"
        s["rolle"] = "admin"
    yield c
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _entwurf(titel, status, bst=False):
    f = {"ueberschrift": titel}
    if bst:
        f["marke"] = "bstnext"
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(text,status) VALUES (?,?)", (json.dumps(f), status))
        conn.commit()


def test_einplanung_zeigt_keine_bstnext_beitraege(client):
    _entwurf(HILO_TITEL, "freigegeben")
    _entwurf(BST_TITEL, "freigegeben", bst=True)
    html = client.get("/einplanung").get_data(as_text=True)
    assert HILO_TITEL in html and BST_TITEL not in html


def test_entwuerfe_liste_zeigt_keine_bstnext_beitraege(client):
    _entwurf(HILO_TITEL, "entwurf")
    _entwurf(BST_TITEL, "entwurf", bst=True)
    html = client.get("/entwuerfe").get_data(as_text=True)
    assert HILO_TITEL in html and BST_TITEL not in html


def test_startseite_zaehlt_bstnext_nicht_mit(client):
    _entwurf(HILO_TITEL, "freigegeben")
    _entwurf(BST_TITEL, "freigegeben", bst=True)
    _entwurf(BST_TITEL + "-2", "entwurf", bst=True)
    seen = {}
    orig = web.render_template_string

    def spy(tpl, **kw):
        if "freigegeben_offen" in kw:
            seen.update(freigegeben_offen=kw["freigegeben_offen"], entwuerfe_offen=kw["entwuerfe_offen"])
        return orig(tpl, **kw)

    web.render_template_string = spy
    try:
        assert client.get("/").status_code == 200
    finally:
        web.render_template_string = orig
    assert seen == {"freigegeben_offen": 1, "entwuerfe_offen": 0}


def test_bstnext_seite_zeigt_den_beitrag_weiter(client):
    _entwurf(BST_TITEL, "entwurf", bst=True)
    r = client.get("/bstnext")
    assert r.status_code == 200


def test_filtermuster_passt_zur_schreibweise_der_bstnext_routen():
    # bstnext.routes erkennt BSt-Next-Entwuerfe am Teilstring '"marke": "bstnext"' im Text.
    assert web._BSTNEXT_LIKE == '%"marke": "bstnext"%'
    assert '"marke": "bstnext"' in json.dumps({"marke": "bstnext"})
