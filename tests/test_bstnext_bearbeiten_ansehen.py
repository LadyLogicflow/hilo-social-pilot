# -*- coding: utf-8 -*-
"""BSt Next: Beitraege bearbeiten (nicht veroeffentlicht, nicht eingeplant) und gross ansehen."""
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
KACHEL = {"weiss": "Gut Ding will", "lime": "SortNext haben", "weiss_nach": "", "format": "quadrat",
          "datum": "", "caption": "Text", "alt": "", "bildtyp": "kachel", "motiv": "belege"}


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-bearb-")
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
    monkeypatch.setattr(publish, "publish_facebook", lambda *a, **k: (True, "p1"))
    monkeypatch.setattr(web, "_publish_instagram", lambda *a, **k: (True, "ig1"))
    yield c
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _neu(c, **ueber):
    d = dict(KACHEL)
    d.update(ueber)
    return c.post("/bstnext/neu", data=d, follow_redirects=True)


def _bearb(c, eid=1, **ueber):
    d = dict(KACHEL)
    d.update(ueber)
    return c.post("/bstnext/bearbeiten/%d" % eid, data=d, follow_redirects=True)


def _zeile(eid=1):
    with db.get_conn() as conn:
        return conn.execute("SELECT text, bild_pfad, status, geplant_fuer FROM entwuerfe WHERE id=?", (eid,)).fetchone()


def _freigeben(c):
    c.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)
    c.post("/bstnext/freigeben/1", follow_redirects=True)


# ---------- Bearbeiten ----------

def test_formular_ist_vorausgefuellt(client):
    _neu(client, weiss_nach="Nur SortNext in time.", alt="Mein Alt")
    html = client.get("/bstnext/bearbeiten/1").get_data(as_text=True)
    assert "Beitrag 1 bearbeiten" in html
    assert "Gut Ding will" in html and "SortNext haben" in html and "Nur SortNext in time." in html
    assert "Mein Alt" in html
    assert 'action="/bstnext/bearbeiten/1"' in html


def test_bearbeiten_aendert_text_und_bild_gleiche_nummer(client):
    _neu(client)
    alt_bild = _zeile()["bild_pfad"]
    with open(alt_bild, "rb") as fh:
        vorher = fh.read()
    _bearbeiten = _bearb(client, weiss="Neuer Satz", lime="Neu hier", caption="Neuer Text")
    assert "gespeichert" in _bearbeiten.get_data(as_text=True)
    z = _zeile()
    f = json.loads(z["text"])
    assert f["bstnext"]["weiss"] == ["Neuer Satz"] and "Neuer Text" in f["caption"]
    with open(z["bild_pfad"], "rb") as fh:
        assert fh.read() != vorher
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0] == 1


def test_bearbeiten_setzt_freigegeben_auf_entwurf_zurueck(client):
    _neu(client)
    _freigeben(client)
    assert _zeile()["status"] == "freigegeben"
    _bearb(client, weiss="Anders")
    assert _zeile()["status"] == "entwurf"


def test_veroeffentlichten_beitrag_nicht_bearbeiten(client):
    _neu(client)
    _freigeben(client)
    client.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "facebook"}, follow_redirects=True)
    assert _zeile()["status"] == "veroeffentlicht"
    r = client.post("/bstnext/bearbeiten/1", data=dict(KACHEL, weiss="Anders"), follow_redirects=True)
    assert "als Nachweis erhalten" in r.get_data(as_text=True)
    assert json.loads(_zeile()["text"])["bstnext"]["weiss"] == ["Gut Ding will"]


def test_eingeplanten_beitrag_nicht_bearbeiten(client):
    _neu(client)
    _freigeben(client)
    datum = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    client.post("/bstnext/einplanen/1", data={"datum": datum, "zeit": "10:30", "page_id": SEITE, "kanal": "beide"},
                follow_redirects=True)
    r = client.get("/bstnext/bearbeiten/1", follow_redirects=True)
    assert "Einplanung" in r.get_data(as_text=True)
    html = client.get("/bstnext").get_data(as_text=True)
    assert "/bstnext/bearbeiten/1" not in html


def test_fehler_beim_bearbeiten_aendert_nichts(client):
    _neu(client)
    r = _bearb(client, weiss="a\nb\nc\nd\ne\nf\ng\nh")
    assert "Zu viele Zeilen" in r.get_data(as_text=True) or "nicht erzeugbar" in r.get_data(as_text=True)
    assert json.loads(_zeile()["text"])["bstnext"]["weiss"] == ["Gut Ding will"]
    assert _zeile()["bild_pfad"] and os.path.exists(_zeile()["bild_pfad"])


def test_karussell_bearbeiten_ersetzt_alle_drei_bilder(client):
    _neu(client, bildtyp="karussell", weiss2="Slide zwei", lime2="", weiss3="Slide drei", lime3="Mit Logo.")
    pfade = json.loads(_zeile()["text"])["bstnext"]["bilder"]
    html = client.get("/bstnext/bearbeiten/1").get_data(as_text=True)
    assert "Slide zwei" in html and "Slide drei" in html
    _bearb(client, bildtyp="karussell", weiss="Neu eins", weiss2="Neu zwei", lime2="", weiss3="Neu drei", lime3="Logo.")
    neu_pfade = json.loads(_zeile()["text"])["bstnext"]["bilder"]
    assert len(neu_pfade) == 3 and all(os.path.exists(p) for p in neu_pfade)
    assert json.loads(_zeile()["text"])["bstnext"]["slides"][1]["weiss"] == ["Neu zwei"]


def test_typwechsel_karussell_zu_kachel_raeumt_alte_bilder_auf(client):
    _neu(client, bildtyp="karussell", weiss2="Slide zwei", lime2="", weiss3="Slide drei", lime3="Mit Logo.")
    pfade = json.loads(_zeile()["text"])["bstnext"]["bilder"]
    _bearb(client, bildtyp="kachel")
    z = _zeile()
    assert os.path.exists(z["bild_pfad"])
    assert not any(os.path.exists(p) for p in pfade)


def test_hilo_beitrag_ueber_bstnext_route_404(client):
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (9,'{\"ueberschrift\":\"HILO\"}','entwurf')")
        conn.commit()
    assert client.get("/bstnext/bearbeiten/9").status_code == 404
    assert client.post("/bstnext/bearbeiten/9", data=KACHEL).status_code == 404


# ---------- Ansehen ----------

def test_ansehen_zeigt_bild_text_und_status(client):
    _neu(client, caption="Mein ausfuehrlicher Begleittext")
    html = client.get("/bstnext/ansehen/1").get_data(as_text=True)
    assert "Mein ausfuehrlicher Begleittext" in html and "entwurf" in html
    assert 'src="/bstnext/bild/1/1"' in html
    r = client.get("/bstnext/bild/1/1")
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"


def test_ansehen_karussell_zeigt_drei_bilder(client):
    _neu(client, bildtyp="karussell", weiss2="Slide zwei", lime2="", weiss3="Slide drei", lime3="Mit Logo.")
    html = client.get("/bstnext/ansehen/1").get_data(as_text=True)
    assert all('/bstnext/bild/1/%d"' % n in html for n in (1, 2, 3))
    assert client.get("/bstnext/bild/1/3").status_code == 200
    assert client.get("/bstnext/bild/1/4").status_code == 404


def test_ansehen_veroeffentlicht_ohne_bearbeiten_knopf(client):
    _neu(client)
    _freigeben(client)
    client.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "facebook"}, follow_redirects=True)
    html = client.get("/bstnext/ansehen/1").get_data(as_text=True)
    assert "veroeffentlicht" in html and "/bstnext/bearbeiten/1" not in html


def test_listenknoepfe_ansehen_und_bearbeiten(client):
    _neu(client)
    html = client.get("/bstnext").get_data(as_text=True)
    assert "/bstnext/ansehen/1" in html and "/bstnext/bearbeiten/1" in html


def test_hilo_beitrag_ansehen_404(client):
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (9,'{\"ueberschrift\":\"HILO\"}','entwurf')")
        conn.commit()
    assert client.get("/bstnext/ansehen/9").status_code == 404
    assert client.get("/bstnext/bild/9/1").status_code == 404
