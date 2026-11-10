# -*- coding: utf-8 -*-
"""Automatischer Zeilenumbruch fuer BSt-Next-Kacheln (catrin gab ganze Saetze ein)."""
import json
import os
import shutil
import tempfile

import pytest

import db
import web
from bstnext import kachel, routes as bs_routes


def test_umbrechen_funktion():
    z = kachel.umbrechen(["Wir fangen nicht mit Ihrer Software an."])
    assert len(z) >= 3 and " ".join(z) == "Wir fangen nicht mit Ihrer Software an."
    assert kachel.umbrechen(["Beleg.", "", "  "]) == ["Beleg."]
    assert kachel.umbrechen(["Wir fangen mit", "Ihren Belegen an."])[0] == "Wir fangen mit"
    assert kachel.umbrechen(["Donaudampfschifffahrtsgesellschaft"]) == ["Donaudampfschifffahrtsgesellschaft"]
    with pytest.raises(kachel.KachelFehler):
        kachel.umbrechen(["x"], "kino")


@pytest.fixture
def env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext3-")
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tmp, "test.db")
    db.init_db()
    monkeypatch.setitem(bs_routes._cfg, "data_dir", tmp)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "test-admin"
        s["rolle"] = "admin"
    yield c
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _post(c, weiss, lime=""):
    return c.post("/bstnext/neu", data={"weiss": weiss, "lime": lime, "format": "quadrat", "datum": "",
                                         "caption": "Text", "alt": "", "bildtyp": "kachel", "motiv": "belege"},
                  follow_redirects=True)


def test_neu_bricht_lange_zeilen_um(env):
    r = _post(env, "Wir fangen nicht mit Ihrer Software an.", "Ihren Belegen")
    assert "BSt-Next-Entwurf 1 erstellt" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        f = json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=1").fetchone()[0])
    assert " ".join(f["bstnext"]["weiss"]) == "Wir fangen nicht mit Ihrer Software an."
    assert " ".join(f["bstnext"]["lime"]) == "Ihren Belegen"


def test_neu_zu_viele_zeilen_bleibt_fehler(env):
    r = _post(env, "Das ist ein sehr langer Satz der nach dem Umbruch viel zu viele Zeilen braucht und nicht passt")
    assert "Zu viele Zeilen" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0] == 0


def test_seite_waehlen_statt_id(env, monkeypatch):
    monkeypatch.setitem(bs_routes._cfg, "pages_fn", lambda: ([
        {"id": "111", "name": "HILO Neuss", "ig_id": "9", "ig_username": "hilo_neuss"},
        {"id": "222", "name": "BSt Next", "ig_id": None, "ig_username": None}], None))
    html = env.get("/bstnext").get_data(as_text=True)
    assert "BSt Next (222)" in html and "kein Instagram verknüpft" in html and "@hilo_neuss" in html
    env.post("/bstnext/seite", data={"seite_wahl": "222", "seiten": "999"}, follow_redirects=True)
    assert db.get_einstellung("bstnext_fb_seiten") == "222"          # Auswahl hat Vorrang
    assert 'value="222" selected' in env.get("/bstnext").get_data(as_text=True)
    env.post("/bstnext/seite", data={"seite_wahl": "", "seiten": ""}, follow_redirects=True)
    assert db.get_einstellung("bstnext_fb_seiten") == ""             # beides leer = entfernt


def test_seitenliste_fehler_sichtbar_und_manuell_moeglich(env, monkeypatch):
    monkeypatch.setitem(bs_routes._cfg, "pages_fn", lambda: ([], "Invalid OAuth access token"))
    html = env.get("/bstnext").get_data(as_text=True)
    assert "Invalid OAuth access token" in html and "name=seiten" in html
    env.post("/bstnext/seite", data={"seiten": "333"}, follow_redirects=True)
    assert db.get_einstellung("bstnext_fb_seiten") == "333"


def test_seitenliste_nur_fuer_admin(env, monkeypatch):
    monkeypatch.setitem(bs_routes._cfg, "pages_fn", lambda: ([{"id": "111", "name": "Geheim", "ig_id": None, "ig_username": None}], None))
    with env.session_transaction() as s:
        s["rolle"] = "freigeber"
    assert "Geheim" not in env.get("/bstnext").get_data(as_text=True)


def test_scheduler_blockt_bstnext_an_beratungsstelle_und_whatsapp(env, monkeypatch):
    import datetime
    import publish
    aufrufe = []
    monkeypatch.setattr(publish, "publish_facebook", lambda *a, **k: aufrufe.append(a) or (True, "x"))
    monkeypatch.setattr(web, "_veroeffentliche_whatsapp", lambda *a, **k: aufrufe.append("wa") or ("x", True, []))
    jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    f = json.dumps({"marke": "bstnext", "ueberschrift": "x", "caption": "c"})
    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(id,name,ort,aktiv,fb_seite) VALUES (1,'HILO X','X',1,'555')")
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (1,?,'freigegeben')", (f,))
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (2,?,'pool')", (f,))
        conn.execute("INSERT INTO geplante_posts(id,entwurf_id,stelle_id,kanal,format,geplant_am,status) "
                     "VALUES (1,1,1,'facebook','einzelbild',?, 'geplant')", (jetzt,))
        conn.execute("INSERT INTO geplante_posts(id,entwurf_id,stelle_id,kanal,format,geplant_am,status,pool) "
                     "VALUES (2,2,1,'whatsapp_kanal','einzelbild',?, 'geplant',1)", (jetzt,))
        conn.commit()
    web._publiziere_geplant(1)
    web._publiziere_geplant(2)
    assert aufrufe == []
    with db.get_conn() as conn:
        st = [r[0] for r in conn.execute("SELECT status FROM geplante_posts ORDER BY id")]
    assert st == ["fehler", "fehler"]
