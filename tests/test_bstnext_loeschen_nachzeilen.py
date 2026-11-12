# -*- coding: utf-8 -*-
"""BSt Next: (1) Beitraege loeschen (nicht veroeffentlichte, nicht eingeplante), (2) optionale weisse Zeilen
NACH dem Lime-Teil bei Spruchkachel und Karussell (nicht beim Foto-Look)."""
import datetime
import json
import os
import shutil
import tempfile

import pytest
from PIL import Image

import db
import web
import publish
from bstnext import kachel, routes as bs_routes

SEITE = "222333444"
KACHEL = {"weiss": "Gut Ding will", "lime": "SortNext haben", "weiss_nach": "Nur SortNext in time.",
          "format": "quadrat", "datum": "", "caption": "Text", "alt": "", "bildtyp": "kachel", "motiv": "belege"}


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-loeschen-")
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
    monkeypatch.setattr(publish, "publish_facebook_carousel", lambda *a, **k: (True, "k1"))
    monkeypatch.setattr(web, "_publish_instagram", lambda *a, **k: (True, "ig1"))
    yield c
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _neu(c, **ueber):
    d = dict(KACHEL)
    d.update(ueber)
    return c.post("/bstnext/neu", data=d, follow_redirects=True)


def _zeile(eid=1):
    with db.get_conn() as conn:
        return conn.execute("SELECT text, bild_pfad, status FROM entwuerfe WHERE id=?", (eid,)).fetchone()


def _anzahl():
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0]


# ---------- weisse Zeilen nach dem Lime-Teil ----------

def test_nach_zeilen_werden_gespeichert_und_gerendert(client):
    _neu(client)
    z = _zeile()
    f = json.loads(z["text"])
    assert f["bstnext"]["weiss_nach"] == ["Nur SortNext in", "time."] or f["bstnext"]["weiss_nach"] == ["Nur SortNext in time."]
    im = Image.open(z["bild_pfad"]).convert("RGB")
    # vierte Textzeile (nach 1 weiss + 1 lime): weisse Pixel im Textbereich dort, wo ohne den Zusatz Navy waere
    y0 = 164 + 2 * 118
    region = im.crop((90, y0, 990, y0 + 90))
    assert (255, 255, 255) in set(region.getdata())


def test_nach_zeilen_kommen_nach_lime_nicht_davor(tmp_path):
    kachel.render(["Eins"], ["Zwei"], str(tmp_path / "a.png"), "quadrat", weisse_nach=["Drei"])
    im = Image.open(tmp_path / "a.png").convert("RGB")
    lime, weiss = (163, 230, 53), (255, 255, 255)
    def farben(zeilenindex):
        y0 = 164 + zeilenindex * 118
        return set(im.crop((90, y0, 990, y0 + 90)).getdata())
    assert weiss in farben(0) and lime in farben(1) and weiss in farben(2) and lime not in farben(2)


def test_zu_viele_zeilen_mit_nach_wird_abgelehnt(client):
    r = _neu(client, weiss="a\nb\nc", lime="d\ne", weiss_nach="f\ng\nh")
    assert "Zu viele Zeilen" in r.get_data(as_text=True)
    assert _anzahl() == 0


def test_nach_zeilen_im_foto_look_werden_abgelehnt(client):
    r = _neu(client, bildtyp="foto")
    assert "nur bei Spruchkachel und Karussell" in r.get_data(as_text=True)
    assert _anzahl() == 0


def test_nach_zeilen_pro_karussell_slide(client):
    _neu(client, bildtyp="karussell", weiss2="Slide zwei", lime2="", weiss3="Slide drei", lime3="Mit Logo.",
         weiss_nach="", weiss_nach2="Fuer Slide zwei", weiss_nach3="")
    f = json.loads(_zeile()["text"])
    slides = f["bstnext"]["slides"]
    assert slides[0]["weiss_nach"] == [] and slides[1]["weiss_nach"] == ["Fuer Slide zwei"]


def test_ohne_nach_zeilen_unveraendert(client):
    _neu(client, weiss_nach="")
    f = json.loads(_zeile()["text"])
    assert f["bstnext"]["weiss_nach"] == []


# ---------- Loeschen ----------

def test_entwurf_loeschen_entfernt_beitrag_und_bild(client):
    _neu(client)
    bild = _zeile()["bild_pfad"]
    assert os.path.exists(bild)
    r = client.post("/bstnext/loeschen/1", follow_redirects=True)
    assert "gelöscht" in r.get_data(as_text=True)
    assert _anzahl() == 0 and not os.path.exists(bild)


def test_karussell_loeschen_entfernt_alle_drei_bilder(client):
    _neu(client, bildtyp="karussell", weiss2="Slide zwei", lime2="", weiss3="Slide drei", lime3="Mit Logo.",
         weiss_nach="")
    pfade = json.loads(_zeile()["text"])["bstnext"]["bilder"]
    assert len(pfade) == 3 and all(os.path.exists(p) for p in pfade)
    client.post("/bstnext/loeschen/1", follow_redirects=True)
    assert _anzahl() == 0 and not any(os.path.exists(p) for p in pfade)


def test_freigegebenen_beitrag_loeschen(client):
    client.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)
    _neu(client)
    client.post("/bstnext/freigeben/1", follow_redirects=True)
    client.post("/bstnext/loeschen/1", follow_redirects=True)
    assert _anzahl() == 0


def test_veroeffentlichten_beitrag_nicht_loeschen(client):
    client.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)
    _neu(client)
    client.post("/bstnext/freigeben/1", follow_redirects=True)
    client.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "facebook"}, follow_redirects=True)
    assert _zeile()["status"] == "veroeffentlicht"
    r = client.post("/bstnext/loeschen/1", follow_redirects=True)
    assert "als Nachweis erhalten" in r.get_data(as_text=True)
    assert _anzahl() == 1


def test_eingeplanten_beitrag_nicht_loeschen(client):
    client.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)
    _neu(client)
    client.post("/bstnext/freigeben/1", follow_redirects=True)
    datum = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    client.post("/bstnext/einplanen/1", data={"datum": datum, "zeit": "10:30", "page_id": SEITE, "kanal": "beide"},
                follow_redirects=True)
    r = client.post("/bstnext/loeschen/1", follow_redirects=True)
    assert "Einplanung" in r.get_data(as_text=True)
    assert _anzahl() == 1
    html = client.get("/bstnext").get_data(as_text=True)
    assert "/bstnext/loeschen/1" not in html          # kein Loeschen-Knopf bei eingeplantem Beitrag


def test_loeschen_knopf_nur_bei_loeschbaren_beitraegen(client):
    _neu(client)
    html = client.get("/bstnext").get_data(as_text=True)
    assert "/bstnext/loeschen/1" in html


def test_hilo_beitrag_ueber_bstnext_route_404(client):
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(id,text,status) VALUES (9,'{\"ueberschrift\":\"HILO\"}','entwurf')")
        conn.commit()
    assert client.post("/bstnext/loeschen/9").status_code == 404
    assert _anzahl() == 1
