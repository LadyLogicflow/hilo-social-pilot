# -*- coding: utf-8 -*-
"""BSt-Next-Karussell: 3 Slides (1+2 nur Text, 3 Text + Logo mit Claim), Facebook- und Instagram-
Karussell. Veroeffentlichung nur mit Attrappen; Einplanen mit Karussell ist gesperrt."""
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


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-karussell-")
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
    calls = {"fb": [], "fb_karussell": [], "ig": [], "story": []}
    monkeypatch.setattr(publish, "publish_facebook",
                        lambda page, bild, cap, place=None, alt_text=None: calls["fb"].append((page, bild)) or (True, "p1"))
    monkeypatch.setattr(publish, "publish_facebook_carousel",
                        lambda page, bilder, cap, place=None, alt_texts=None:
                        calls["fb_karussell"].append((page, list(bilder), cap)) or (True, "fbk1"))
    monkeypatch.setattr(publish, "publish_facebook_story",
                        lambda page, bild, alt_text=None: calls["story"].append((page, bild)) or (True, "s1"))
    monkeypatch.setattr(web, "_publish_instagram",
                        lambda pub_, page, bilder, cap, fmt, eid, sid, location_id=None, alt_text=None:
                        calls["ig"].append((page, list(bilder), fmt)) or (True, "ig1"))
    yield c, calls, tmp
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


FORM = {"weiss": "Slide eins", "lime": "kurz.", "format": "quadrat", "datum": "", "caption": "Text",
        "alt": "", "bildtyp": "karussell", "motiv": "belege",
        "weiss2": "Slide zwei", "lime2": "", "weiss3": "Slide drei", "lime3": "Mit Logo."}


def _neu(c, **ueber):
    daten = dict(FORM)
    daten.update(ueber)
    return c.post("/bstnext/neu", data=daten, follow_redirects=True)


def _seite_setzen(c):
    c.post("/bstnext/seite", data={"seiten": SEITE}, follow_redirects=True)


def _fields(eid=1):
    with db.get_conn() as conn:
        row = conn.execute("SELECT text, bild_pfad, status FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    return json.loads(row["text"]), row["bild_pfad"], row["status"]


def test_karussell_erzeugt_drei_slides(client):
    c, _, _ = client
    _neu(c)
    f, bild_pfad, status = _fields()
    bs = f["bstnext"]
    assert bs["typ"] == "karussell" and len(bs["bilder"]) == 3 and status == "entwurf"
    assert bild_pfad == bs["bilder"][0]
    assert [s["logo"] for s in bs["slides"]] == [False, False, True]
    for pfad in bs["bilder"]:
        assert Image.open(pfad).size == (1080, 1080)


def test_logo_nur_auf_slide_drei(client):
    c, _, _ = client
    _neu(c)
    bilder = _fields()[0]["bstnext"]["bilder"]
    navy = (0, 25, 66)
    # unten links (dort sitzt auf Slide 3 das Logo mit Claim) ist auf Slide 1 und 2 reine Navy-Flaeche
    for pfad in bilder[:2]:
        im = Image.open(pfad).convert("RGB")
        region = im.crop((90, 800, 540, 985))
        assert set(region.getdata()) == {navy}
    im3 = Image.open(bilder[2]).convert("RGB")
    assert len(set(im3.crop((90, 800, 540, 985)).getdata())) > 1


def test_text_slides_duerfen_mehr_zeilen_haben_als_slide_mit_logo(tmp_path):
    zeilen = ["Zeile %d" % i for i in range(1, 8)]
    kachel.render(zeilen, [], str(tmp_path / "a.png"), "quadrat", mit_logo=False)
    with pytest.raises(kachel.KachelFehler):
        kachel.render(zeilen, [], str(tmp_path / "b.png"), "quadrat", mit_logo=True)


def test_fehlender_slide_text_legt_nichts_an(client):
    c, _, tmp = client
    r = _neu(c, weiss2="")
    assert "jeder der 3 Slides" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0] == 0
    bilder = os.path.join(tmp, "bilder")
    assert not os.path.isdir(bilder) or [n for n in os.listdir(bilder) if n.endswith(".png")] == []


def test_zu_breite_zeile_nennt_den_slide_und_raeumt_auf(client):
    c, _, tmp = client
    r = _neu(c, weiss3="Unmoeglichlangeswortdasnichtpasst")
    assert "Slide 3" in r.get_data(as_text=True)
    bilder = os.path.join(tmp, "bilder")
    assert not os.path.isdir(bilder) or [n for n in os.listdir(bilder) if n.endswith(".png")] == []


def test_veroeffentlichen_facebook_und_instagram_karussell(client, monkeypatch):
    c, calls, _ = client
    # HILO-Karussell-Pipeline darf nie angefasst werden
    import bildgen
    monkeypatch.setattr(bildgen, "render_slides",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("HILO-Pipeline benutzt")))
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "beide", "story_fb": "1"},
               follow_redirects=True)
    text = r.get_data(as_text=True)
    assert "Facebook: OK" in text and "Instagram: OK" in text
    bilder = _fields()[0]["bstnext"]["bilder"]
    assert calls["fb"] == [] and len(calls["fb_karussell"]) == 1
    assert calls["fb_karussell"][0][0] == SEITE and calls["fb_karussell"][0][1] == bilder
    assert calls["ig"] == [(SEITE, bilder, "karussell")]
    assert calls["story"] == []                       # keine Story zum Karussell
    assert _fields()[2] == "veroeffentlicht"


def test_nur_instagram_nur_facebook(client):
    c, calls, _ = client
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "instagram"}, follow_redirects=True)
    assert calls["fb_karussell"] == [] and len(calls["ig"]) == 1


def test_karussell_nie_an_beratungsstellen(client):
    c, calls, _ = client
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": "999", "kanal": "beide"}, follow_redirects=True)
    assert "nur an die hinterlegte BSt-Next-Facebook-Seite" in r.get_data(as_text=True)
    assert calls["fb_karussell"] == [] and calls["ig"] == []


def test_fehlende_slide_datei_blockiert_veroeffentlichung(client):
    c, calls, _ = client
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    os.remove(_fields()[0]["bstnext"]["bilder"][1])
    r = c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "beide"}, follow_redirects=True)
    assert "nicht alle 3 Bilder" in r.get_data(as_text=True)
    assert calls["fb_karussell"] == [] and calls["ig"] == [] and _fields()[2] == "freigegeben"


def test_einplanen_mit_karussell_ist_gesperrt(client):
    c, _, _ = client
    _seite_setzen(c)
    _neu(c)
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    r = c.post("/bstnext/einplanen/1", data={"datum": "2099-01-01", "zeit": "10:00", "page_id": SEITE,
                                             "kanal": "beide"}, follow_redirects=True)
    assert "noch nicht einplanen" in r.get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM geplante_posts").fetchone()[0] == 0


def test_einzelkachel_bleibt_unveraendert(client):
    c, calls, _ = client
    _seite_setzen(c)
    c.post("/bstnext/neu", data={"weiss": "Wir fangen mit", "lime": "Ihren Belegen\nan.", "format": "quadrat",
                                  "datum": "", "caption": "Text", "alt": "", "bildtyp": "kachel", "motiv": "belege"},
           follow_redirects=True)
    f, bild_pfad, _ = _fields()
    assert f["bstnext"]["typ"] == "kachel" and "bilder" not in f["bstnext"] and bild_pfad.endswith("bstnext_1.png")
    c.post("/bstnext/freigeben/1", follow_redirects=True)
    c.post("/bstnext/veroeffentlichen/1", data={"page_id": SEITE, "kanal": "beide"}, follow_redirects=True)
    assert len(calls["fb"]) == 1 and calls["fb_karussell"] == [] and calls["ig"][0][2] == "einzelbild"
