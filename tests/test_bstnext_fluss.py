# -*- coding: utf-8 -*-
"""BSt Next: kompletter Ablauf direkt auf /bstnext (Freigeben, Jetzt veroeffentlichen, Einplanen),
ohne HILO-Vorschau pro Beratungsstelle. Veroeffentlichung nur mit Attrappen."""
import datetime
import json
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
def env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext4-")
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


def _neu(c):
    c.post("/bstnext/neu", data={"weiss": "Wir fangen mit", "lime": "Ihren Belegen\nan.", "format": "quadrat",
                                  "datum": "", "caption": "Text", "alt": "", "bildtyp": "kachel", "motiv": "belege"},
           follow_redirects=True)


def _status(eid=1):
    with db.get_conn() as conn:
        return conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid,)).fetchone()[0]


def _seite_setzen(c, pid=SEITE):
    c.post("/bstnext/seite", data={"seiten": pid}, follow_redirects=True)


def test_freigeben_und_knoepfe_je_status(env):
    c, _ = env
    _seite_setzen(c)
    _neu(c)
    html = c.get("/bstnext").get_data(as_text=True)
    assert "Freigeben" in html and "Jetzt veröffentlichen" not in html
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    assert _status() == "freigegeben"
    html = c.get("/bstnext").get_data(as_text=True)
    assert "Jetzt veröffentlichen" in html and "Einplanen" in html and 'value="%s"' % SEITE in html


def test_jetzt_veroeffentlichen(env):
    c, calls = env
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "beide"}, follow_redirects=True)
    assert "Facebook: OK" in r.get_data(as_text=True) and "Instagram: OK" in r.get_data(as_text=True)
    assert calls["fb"][0][0] == SEITE and calls["fb"][0][1].endswith("bstnext_1.png")
    assert calls["ig"][0][0] == SEITE
    assert _status() == "veroeffentlicht"
    assert "ansehen" in c.get("/bstnext").get_data(as_text=True)


def test_nur_facebook(env):
    c, calls = env
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "facebook"}, follow_redirects=True)
    assert len(calls["fb"]) == 1 and calls["ig"] == []


def test_ohne_freigabe_nichts(env):
    c, calls = env
    _seite_setzen(c)
    _neu(c)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "beide"}, follow_redirects=True)
    assert "zuerst freigegeben" in r.get_data(as_text=True)
    assert calls["fb"] == [] and _status() == "entwurf"


def test_falsche_seite_und_kanal_abgelehnt(env):
    c, calls = env
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": "999", "kanal": "beide"}, follow_redirects=True)
    assert "nur an die hinterlegte BSt-Next-Facebook-Seite" in r.get_data(as_text=True)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "whatsapp_kanal"}, follow_redirects=True)
    assert "Unbekannter Kanal" in r.get_data(as_text=True)
    assert calls["fb"] == [] and _status() == "freigegeben"


def test_hilo_entwurf_ueber_bstnext_route_404(env):
    c, _ = env
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (9,'{\"ueberschrift\":\"HILO\"}','freigegeben')")
    assert c.post("/bstnext/veroeffentlichen/9", data={"page_id": SEITE, "kanal": "beide"}).status_code == 404
    assert c.post("/bstnext/freigeben/9").status_code == 404
    assert c.post("/bstnext/einplanen/9", data={"datum": "2099-01-01", "zeit": "10:00", "page_id": SEITE}).status_code == 404


def test_fehler_wird_angezeigt_status_bleibt(env, monkeypatch):
    c, _ = env
    monkeypatch.setattr(publish, "publish_facebook", lambda *a, **k: (False, "HTTP 190: Token abgelaufen"))
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "facebook"}, follow_redirects=True)
    assert "Token abgelaufen" in r.get_data(as_text=True)
    assert _status() == "freigegeben"


def test_einplanen(env):
    c, calls = env
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    morgen = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r = c.post("/bstnext/einplanen/1", data={"datum": morgen, "zeit": "10:30", "page_id": SEITE, "kanal": "beide"},
               follow_redirects=True)
    assert "eingeplant" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        gp = conn.execute("SELECT * FROM geplante_posts").fetchall()
    assert len(gp) == 1 and gp[0]["page_id"] == SEITE and gp[0]["stelle_id"] is None
    assert gp[0]["geplant_am"] == morgen + "T10:30:00" and gp[0]["status"] == "geplant" and gp[0]["kanal"] == "beide"
    assert calls["fb"] == []                       # eingeplant, noch nicht gepostet
    # der Zeitplan-Dienst postet es zur Zeit (hier: Zeitpunkt auf jetzt gesetzt)
    with db.get_conn() as conn:
        conn.execute("UPDATE geplante_posts SET geplant_am=?", (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),))
        conn.commit()
    web._publiziere_geplant(gp[0]["id"])
    assert len(calls["fb"]) == 1 and calls["fb"][0][0] == SEITE


def test_einplanen_abgelehnt(env):
    c, _ = env
    _seite_setzen(c)
    _neu(c)
    r = c.post("/bstnext/einplanen/1", data={"datum": "2099-01-01", "zeit": "10:00", "page_id": SEITE},
               follow_redirects=True)
    assert "zuerst freigegeben" in r.get_data(as_text=True)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    assert "Vergangenheit" in c.post("/bstnext/einplanen/1", data={"datum": "2020-01-01", "zeit": "10:00",
                                                                  "page_id": SEITE}, follow_redirects=True).get_data(as_text=True)
    assert "Datum und Uhrzeit" in c.post("/bstnext/einplanen/1", data={"datum": "", "zeit": "", "page_id": SEITE},
                                         follow_redirects=True).get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM geplante_posts").fetchone()[0] == 0


def test_freigeben_nur_mit_fertigem_bild(env):
    c, _ = env
    _neu(c)
    with db.get_conn() as conn:
        conn.execute("UPDATE entwuerfe SET bild_pfad='/nix' WHERE id=1")
        conn.commit()
    r = c.post("/bstnext/freigeben/1", follow_redirects=True)
    assert "noch nicht fertig" in r.get_data(as_text=True) and _status() == "entwurf"
