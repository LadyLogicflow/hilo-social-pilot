# -*- coding: utf-8 -*-
"""Eingeplante BSt-Next-Beitraege zeigen auf /bstnext ihren Termin und keine Veroeffentlichen-/
Einplanen-Knoepfe mehr; serverseitig sind Doppel-Veroeffentlichung und Doppel-Einplanung gesperrt."""
import datetime
import os
import shutil
import tempfile

import pytest

import db
import web
import publish
from bstnext import routes as bs_routes

SEITE = "222333444"


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-eingeplant-")
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
    calls = {"fb": [], "ig": []}
    monkeypatch.setattr(publish, "publish_facebook",
                        lambda page, bild, cap, place=None, alt_text=None: calls["fb"].append((page, bild)) or (True, "p1"))
    monkeypatch.setattr(web, "_publish_instagram",
                        lambda pub_, page, bilder, cap, fmt, eid, sid, location_id=None, alt_text=None:
                        calls["ig"].append((page, bilder)) or (True, "ig1"))
    yield c, calls
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _vorbereiten(c):
    c.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)
    c.post("/bstnext/neu", data={"weiss": "Wir fangen mit", "lime": "Ihren Belegen\nan.", "format": "quadrat",
                                  "datum": "", "caption": "Text", "alt": "", "bildtyp": "kachel", "motiv": "belege"},
           follow_redirects=True)
    c.post("/bstnext/freigeben/1", follow_redirects=True)


def _einplanen(c, tage=1, zeit="10:30"):
    datum = (datetime.date.today() + datetime.timedelta(days=tage)).isoformat()
    r = c.post("/bstnext/einplanen/1", data={"datum": datum, "zeit": zeit, "page_id": SEITE, "kanal": "beide"},
               follow_redirects=True)
    return datum, r


def _anzahl_geplant():
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM geplante_posts").fetchone()[0]


def test_ohne_einplanung_bleiben_die_knoepfe(client):
    c, _ = client
    _vorbereiten(c)
    html = c.get("/bstnext").get_data(as_text=True)
    assert "/bstnext/veroeffentlichen/1" in html and "/bstnext/einplanen/1" in html
    assert "eingeplant für" not in html


def test_eingeplanter_beitrag_zeigt_termin_ohne_knoepfe(client):
    c, _ = client
    _vorbereiten(c)
    datum, _r = _einplanen(c)
    d = datetime.date.fromisoformat(datum)
    html = c.get("/bstnext").get_data(as_text=True)
    assert "eingeplant für %s um 10:30 Uhr" % d.strftime("%d.%m.%Y") in html
    assert "/bstnext/veroeffentlichen/1" not in html and "/bstnext/einplanen/1" not in html
    assert "/geplant" in html                      # Hinweis, wo man ändert und löscht


def test_doppelt_veroeffentlichen_ist_gesperrt(client):
    c, calls = client
    _vorbereiten(c)
    _einplanen(c)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "beide"}, follow_redirects=True)
    assert "schon eingeplant" in r.get_data(as_text=True)
    assert calls["fb"] == [] and calls["ig"] == []


def test_doppelt_einplanen_ist_gesperrt(client):
    c, _ = client
    _vorbereiten(c)
    _einplanen(c)
    _datum, r = _einplanen(c, tage=2, zeit="12:00")
    assert "schon eingeplant" in r.get_data(as_text=True)
    assert _anzahl_geplant() == 1


def test_nach_loeschen_der_einplanung_sind_die_knoepfe_wieder_da(client):
    c, _ = client
    _vorbereiten(c)
    _einplanen(c)
    with db.get_conn() as conn:
        gpid = conn.execute("SELECT id FROM geplante_posts").fetchone()[0]
    c.post("/geplant-loeschen/%d" % gpid, follow_redirects=True)
    html = c.get("/bstnext").get_data(as_text=True)
    assert "eingeplant für" not in html and "/bstnext/veroeffentlichen/1" in html


def test_gepostete_einplanung_blockiert_nicht_mehr(client):
    c, _ = client
    _vorbereiten(c)
    _einplanen(c)
    with db.get_conn() as conn:
        conn.execute("UPDATE geplante_posts SET status='gepostet'")
        conn.commit()
    html = c.get("/bstnext").get_data(as_text=True)
    assert "eingeplant für" not in html
