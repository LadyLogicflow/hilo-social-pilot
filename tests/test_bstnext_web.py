# -*- coding: utf-8 -*-
"""BSt Next als eigener Mandant in ShareNext (Stufe 1b): Seite /bstnext, Kachel-Entwurf, Weichen
(guard) gegen Vermischung mit HILO, Sperre der HILO-Bildfunktionen, Freigabe + Veroeffentlichung
(mit Mock, nichts wird wirklich veroeffentlicht)."""
import json
import os
import shutil
import tempfile

import pytest
from PIL import Image

import db
import web
import publish
from bstnext import brand, guard, routes as bs_routes

SEITE = "123456789012345"


@pytest.fixture
def env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-")
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tmp, "test.db")
    db.init_db()
    monkeypatch.setitem(bs_routes._cfg, "data_dir", tmp)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "test-admin"
        s["rolle"] = "admin"
    yield c, tmp
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _neu(c, **kw):
    daten = {"weiss": "Wir fangen mit", "lime": "Ihren Belegen\nan.", "format": "quadrat",
             "datum": "", "caption": "Ein Text.", "alt": ""}
    daten.update(kw)
    return c.post("/bstnext/neu", data=daten, follow_redirects=True)


def _entwurf(eid=1):
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()


def test_seite_laedt(env):
    c, _ = env
    r = c.get("/bstnext")
    assert r.status_code == 200 and "BSt Next" in r.get_data(as_text=True)


def test_neu_legt_entwurf_mit_kachel_an(env):
    c, tmp = env
    r = _neu(c)
    assert r.status_code == 200 and "BSt-Next-Entwurf 1 erstellt" in r.get_data(as_text=True)
    e = _entwurf()
    f = json.loads(e["text"])
    assert f["marke"] == "bstnext" and f["bstnext"]["weiss"] == ["Wir fangen mit"]
    assert f["ueberschrift"] == "Wir fangen mit Ihren Belegen an."
    # Hashtags werden angehaengt
    assert "#BStNext" in f["captions"]["facebook"] and f["captions"]["facebook"].startswith("Ein Text.")
    assert e["status"] == "entwurf" and e["kanal"] == "facebook"
    im = Image.open(e["bild_pfad"]).convert("RGB")
    assert im.size == (1080, 1080) and im.getpixel((5, 5)) == brand.NAVY
    assert e["bild_pfad"].startswith(tmp)
    # Thema darf vom HILO-Generator nicht erneut aufgegriffen werden
    with db.get_conn() as conn:
        assert conn.execute("SELECT status FROM themen WHERE id=?", (e["thema_id"],)).fetchone()[0] == "erledigt"


def test_hochformat(env):
    c, _ = env
    _neu(c, format="hochformat")
    assert Image.open(_entwurf()["bild_pfad"]).size == (1080, 1350)


def test_zu_breite_zeile_legt_nichts_an(env):
    c, _ = env
    r = _neu(c, weiss="Donaudampfschifffahrtsgesellschaft")
    assert "Kachel nicht erzeugbar" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0] == 0


def test_pflichtfelder_und_datum(env):
    c, _ = env
    assert "weiße Zeile" in _neu(c, weiss="").get_data(as_text=True)
    assert "Begleittext" in _neu(c, caption="").get_data(as_text=True)
    assert "Vergangenheit" in _neu(c, datum="2020-01-01").get_data(as_text=True)
    assert "zu lang" in _neu(c, caption="x" * 2100).get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0] == 0


def test_seite_speichern_nur_ziffern_und_nur_admin(env):
    c, _ = env
    r = c.post("/bstnext/seite", data={"seiten": "abc"}, follow_redirects=True)
    assert "nur aus Ziffern" in r.get_data(as_text=True)
    c.post("/bstnext/seite", data={"seiten": SEITE + ", 999"}, follow_redirects=True)
    assert guard.seiten_ids(db.get_einstellung(guard.EINSTELLUNG_SEITEN)) == {SEITE, "999"}
    with c.session_transaction() as s:
        s["rolle"] = "freigeber"
    assert c.post("/bstnext/seite", data={"seiten": "1"}).status_code == 403


def test_hilo_bildfunktionen_fuer_bstnext_gesperrt(env, monkeypatch):
    c, _ = env
    _neu(c)
    def boom(*a, **k):
        raise AssertionError("HILO-Pipeline darf nicht laufen")
    monkeypatch.setattr(web, "_sharenext_bild_synchron", boom)
    vorher = _entwurf()["bild_pfad"]
    for url in ("/bild-neu/1", "/umsetzung-neu/1", "/text-neu/1", "/bild-generieren/1", "/anderes-bild/1",
                "/pool-aufnehmen/1", "/beitrag-neu/1"):
        r = c.post(url, data={}, follow_redirects=True)
        assert "gehört zu BSt Next" in r.get_data(as_text=True), url
    r = c.post("/aktion/1", data={"aktion": "ueberarbeiten", "feedback": "x"}, follow_redirects=True)
    assert "gehört zu BSt Next" in r.get_data(as_text=True)
    r = c.post("/aktion/1", data={"aktion": "caption_erstellen"}, follow_redirects=True)
    assert "gehört zu BSt Next" in r.get_data(as_text=True)
    assert _entwurf()["bild_pfad"] == vorher


def test_hilo_entwurf_nicht_gesperrt(env, monkeypatch):
    c, _ = env
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (7,'{\"ueberschrift\":\"HILO\"}','entwurf')")
    aufgerufen = []
    monkeypatch.setattr(web, "_sharenext_bild_synchron", lambda f, e: aufgerufen.append(e) or "/nix")
    r = c.post("/bild-neu/7", data={}, follow_redirects=False)
    assert "gehört zu BSt Next" not in (r.get_data(as_text=True) or "")
    assert r.headers.get("Location", "") != "/bstnext"


def test_seiten_rendern_mit_bstnext_entwurf(env):
    c, _ = env
    _neu(c)
    assert c.get("/entwuerfe").status_code == 200
    assert c.get("/beitrag/1").status_code == 200
    assert c.get("/einplanung").status_code == 200
    assert c.get("/").status_code == 200
    assert b"/bild/1" in c.get("/bstnext").data


def test_freigabe_wie_bisher(env):
    c, _ = env
    _neu(c)
    c.post("/aktion/1", data={"aktion": "freigeben"}, follow_redirects=True)
    assert _entwurf()["status"] == "freigegeben"


# --- Veroeffentlichung (Mock) ------------------------------------------------------------------
@pytest.fixture
def pub(monkeypatch):
    calls = {"fb": [], "ig": []}
    monkeypatch.setattr(publish, "publish_facebook",
                        lambda page, bild, cap, place=None, alt_text=None: calls["fb"].append((page, bild, cap, alt_text)) or (True, "p1"))
    monkeypatch.setattr(web, "_publish_instagram",
                        lambda pub_, page, bilder, cap, fmt, eid, sid, location_id=None, alt_text=None:
                        calls["ig"].append((page, bilder, cap)) or (True, "ig1"))
    return calls


def _frei(c, seiten=SEITE):
    _neu(c)
    c.post("/bstnext/seite", data={"seiten": seiten}, follow_redirects=True)
    c.post("/aktion/1", data={"aktion": "freigeben"}, follow_redirects=True)
    c.get("/bstnext")   # evtl. wartende Hinweise abholen


def test_bstnext_geht_an_bstnext_seite(env, pub):
    c, _ = env
    _frei(c)
    c.post("/veroeffentlichen/1", data={"page_id": SEITE, "kanal_p" + SEITE: "beide"}, follow_redirects=True)
    assert len(pub["fb"]) == 1 and pub["fb"][0][0] == SEITE
    assert pub["fb"][0][1].endswith("bstnext_1.png") and "#BStNext" in pub["fb"][0][2]
    assert len(pub["ig"]) == 1 and pub["ig"][0][0] == SEITE
    assert _entwurf()["status"] == "veroeffentlicht"


def test_bstnext_nicht_an_hilo_stelle_oder_fremde_seite(env, pub):
    c, _ = env
    _frei(c)
    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(id,name,ort,aktiv,fb_seite) VALUES (1,'HILO X','X',1,'555')")
    r = c.post("/veroeffentlichen/1", data={"stelle_id": "1"}, follow_redirects=True)
    assert "nicht an Beratungsstellen" in r.get_data(as_text=True)
    r = c.post("/veroeffentlichen/1", data={"page_id": "777"}, follow_redirects=True)
    assert "nur an die hinterlegte BSt-Next-Facebook-Seite" in r.get_data(as_text=True)
    assert pub["fb"] == [] and pub["ig"] == []
    assert _entwurf()["status"] == "freigegeben"


def test_bstnext_ohne_hinterlegte_seite(env, pub):
    c, _ = env
    _neu(c)
    c.post("/aktion/1", data={"aktion": "freigeben"}, follow_redirects=True)
    r = c.post("/veroeffentlichen/1", data={"page_id": SEITE}, follow_redirects=True)
    assert "noch nicht hinterlegt" in r.get_data(as_text=True)
    assert pub["fb"] == []


def test_hilo_beitrag_nicht_an_bstnext_seite(env, pub):
    c, _ = env
    c.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (5,'{\"ueberschrift\":\"HILO\"}','freigegeben')")
    r = c.post("/veroeffentlichen/5", data={"page_id": SEITE}, follow_redirects=True)
    assert "HILO-Beiträge gehen nicht an die BSt-Next-Facebook-Seite" in r.get_data(as_text=True)
    assert pub["fb"] == []


def test_einplanung_bstnext_pruefung_und_scheduler_guard(env, pub):
    c, _ = env
    _frei(c)
    r = c.post("/auto-einplanen/1", data={"page_id": "777"}, follow_redirects=True)
    assert "nur an die hinterlegte BSt-Next-Facebook-Seite" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM geplante_posts").fetchone()[0] == 0
    c.post("/auto-einplanen/1", data={"page_id": SEITE, "kanal_p" + SEITE: "facebook"}, follow_redirects=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM geplante_posts WHERE page_id=?", (SEITE,)).fetchone()[0] == 1
        # Scheduler-Pfad: Ziel wird umgeleitet (Einstellung geaendert) -> Veroeffentlichung wird abgelehnt
        conn.execute("UPDATE einstellungen SET wert='999' WHERE schluessel=?", (guard.EINSTELLUNG_SEITEN,))
        conn.commit()
        gp = conn.execute("SELECT id FROM geplante_posts").fetchone()[0]
    import datetime
    with db.get_conn() as conn:
        conn.execute("UPDATE geplante_posts SET geplant_am=? WHERE id=?",
                     (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), gp))
        conn.commit()
    web._publiziere_geplant(gp)
    assert pub["fb"] == []
    with db.get_conn() as conn:
        assert conn.execute("SELECT status FROM geplante_posts WHERE id=?", (gp,)).fetchone()[0] == "fehler"


# --- reine Funktionen --------------------------------------------------------------------------
def test_guard_funktionen():
    bs = {"marke": "bstnext"}
    assert guard.ziel_erlaubt(bs, None, SEITE, {SEITE}) == (True, "")
    assert not guard.ziel_erlaubt(bs, {"id": 1}, None, {SEITE})[0]
    assert not guard.ziel_erlaubt(bs, None, SEITE, set())[0]
    assert guard.ziel_erlaubt({}, None, "555", {SEITE})[0]
    assert not guard.ziel_erlaubt({}, None, SEITE, {SEITE})[0]
    assert guard.seiten_ids(" 1, 2;3\n4 ") == {"1", "2", "3", "4"} and guard.seiten_ids(None) == set()
    assert guard.endpoint_gesperrt("bild_neu") and guard.endpoint_gesperrt("aktion", "ueberarbeiten")
    assert not guard.endpoint_gesperrt("aktion", "freigeben") and not guard.endpoint_gesperrt("veroeffentlichen")
