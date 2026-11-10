# -*- coding: utf-8 -*-
"""Stufe 2 (Typ C, Foto-Look): Szenen-Ablauf mit Fake-Modellen, Foto-Kachel, Web-Ablauf (Job, Sperren)."""
import json
import os
import shutil
import tempfile
from types import SimpleNamespace

import pytest
from PIL import Image

import db
import web
import publish
from bstnext import brand, kachel, guard, szene, routes as bs_routes


# --- Fake-Modelle ------------------------------------------------------------------------------
def _route(t, k="Ordner-Regal"):
    return SimpleNamespace(titel=t, szene="A calm shelf with binders, no text. " + t, kategorie=k)


class FakeLLM:
    def __init__(self, qa_ergebnisse=(True,), gewinner=1):
        self.qa = list(qa_ergebnisse)
        self.gewinner = gewinner
        self.aufrufe = []

    def __call__(self, system, user, schema, bild=None):
        name = schema.__name__
        self.aufrufe.append(name)
        if name == "Routen":
            return SimpleNamespace(routen=[_route("R0"), _route("R1"), _route("R2")])
        if name == "Wahl":
            return SimpleNamespace(gewinner=self.gewinner, begruendung="passt am besten")
        if name == "QA":
            ok = self.qa.pop(0) if self.qa else True
            return SimpleNamespace(bestanden=ok, probleme=[] if ok else ["lesbare Buchstaben im Bild"])
        raise AssertionError(name)


def _foto(prompt, groesse):
    b, h = map(int, groesse.split("x"))
    _foto.prompts.append(prompt)
    return Image.new("RGB", (b, h), (90, 140, 190))
_foto.prompts = []


def test_szene_pipeline_waehlt_route_und_setzt_headline(tmp_path):
    _foto.prompts.clear()
    llm = FakeLLM(gewinner=1)
    prot = szene.erzeuge_szene("Belege", ["Wir fangen mit"], ["Ihren Belegen", "an."], "quadrat", "belege",
                               str(tmp_path / "s.png"), llm=llm, bild_fn=_foto)
    assert llm.aufrufe == ["Routen", "Wahl", "QA"]
    assert prot["route"] == "R1" and prot["versuche"] == 1 and "R1" in _foto.prompts[0]
    # fester Stil-/Tabu-Zusatz ist im Prompt
    assert "no text, no letters" in _foto.prompts[0] and "#001942" in _foto.prompts[0]
    im = Image.open(prot["pfad"]).convert("RGB")
    assert im.size == (1080, 1080)
    farben = {c for _, c in im.getcolors(maxcolors=1 << 22)}
    assert brand.WHITE in farben and brand.LIME in farben


def test_szene_qa_fehlschlag_zweiter_versuch_mit_anderer_route(tmp_path):
    _foto.prompts.clear()
    llm = FakeLLM(qa_ergebnisse=(False, True), gewinner=0)
    prot = szene.erzeuge_szene("Belege", ["Beleg."], [], "hochformat", "belege", str(tmp_path / "s.png"),
                               llm=llm, bild_fn=_foto)
    assert prot["versuche"] == 2 and prot["route"] == "R1"
    assert prot["qa"][0]["bestanden"] is False and "lesbare" in prot["qa"][0]["probleme"][0]
    assert Image.open(prot["pfad"]).size == (1080, 1350)


def test_szene_qa_dauerhaft_nicht_bestanden(tmp_path):
    llm = FakeLLM(qa_ergebnisse=(False, False))
    with pytest.raises(RuntimeError, match="nicht bestanden"):
        szene.erzeuge_szene("Belege", ["Beleg."], [], "quadrat", "belege", str(tmp_path / "s.png"),
                            llm=llm, bild_fn=_foto)
    assert not (tmp_path / "s.png").exists()


def test_szene_prueft_zeilen_vor_kosten(tmp_path):
    llm = FakeLLM()
    with pytest.raises(kachel.KachelFehler):
        szene.erzeuge_szene("x", ["Das ist eine viel zu lange Headline Zeile"], [], "quadrat", "belege",
                            str(tmp_path / "s.png"), llm=llm, bild_fn=_foto)
    assert llm.aufrufe == []          # kein einziger Modellaufruf, keine Kosten


def test_szene_format_story_nicht_fuer_foto(tmp_path):
    with pytest.raises(ValueError):
        szene.erzeuge_szene("x", ["Beleg."], [], "story", "belege", str(tmp_path / "s.png"),
                            llm=FakeLLM(), bild_fn=_foto)


def test_motiv_text_und_prompt_tabus():
    assert "Ordner" in szene.motiv_text("belege") and szene.motiv_text("frei: Waage") == "frei: Waage"
    assert "no children" in szene.STIL_ZUSATZ and "fictional people only" in szene.STIL_ZUSATZ


def test_render_foto_zuschnitt_und_navy_verlauf(tmp_path):
    foto = Image.new("RGB", (1536, 1024), (255, 255, 255))      # Querformat -> wird zugeschnitten
    p = kachel.render_foto(foto, ["Beleg."], [], str(tmp_path / "f.png"), "quadrat")
    im = Image.open(p).convert("RGB")
    assert im.size == (1080, 1080)
    oben = im.getpixel((1070, 5))
    mitte = im.getpixel((1070, 600))
    assert oben[2] < 255 and oben[0] < 80            # oben stark navy
    assert mitte == (255, 255, 255)                  # Bildmitte unberuehrt (Verlauf endet davor)


# --- Web-Ablauf ------------------------------------------------------------------------------
@pytest.fixture
def env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext2-")
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tmp, "test.db")
    db.init_db()
    monkeypatch.setitem(bs_routes._cfg, "data_dir", tmp)
    monkeypatch.setitem(bs_routes._cfg, "sync", True)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "test-admin"; s["rolle"] = "admin"
    yield c, tmp
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _form(**kw):
    d = {"weiss": "Wir fangen mit", "lime": "Ihren Belegen\nan.", "format": "quadrat", "datum": "",
         "caption": "Text", "alt": "", "bildtyp": "foto", "motiv": "belege"}
    d.update(kw)
    return d


def _entwurf(eid=1):
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    return r, json.loads(r["text"])


def _fake_fn(erfolg=True):
    def fn(thema, weiss, lime, fmt, motiv, ziel):
        if not erfolg:
            raise RuntimeError("Bild-Pruefung nicht bestanden: lesbare Buchstaben im Bild")
        kachel.render_foto(Image.new("RGB", (1024, 1024), (90, 140, 190)), weiss, lime, ziel, fmt)
        return {"pfad": ziel, "route": "R1", "kategorie": "Ordner-Regal", "prompt": "p", "jury": "j",
                "qa": [{"route": "R1", "bestanden": True, "probleme": []}], "versuche": 1}
    return fn


def test_foto_ablauf_erfolg(env, monkeypatch):
    c, tmp = env
    monkeypatch.setitem(bs_routes._cfg, "szene_fn", _fake_fn(True))
    r = c.post("/bstnext/neu", data=_form(), follow_redirects=True)
    assert "angelegt" in r.get_data(as_text=True)
    e, f = _entwurf()
    assert f["bild_status"] == "fertig" and f["bstnext"]["typ"] == "foto"
    assert f["bstnext"]["protokoll"]["route"] == "R1" and e["bild_pfad"].endswith("bstnext_1.png")
    assert Image.open(e["bild_pfad"]).size == (1080, 1080)
    assert b"(Foto-Look)" in c.get("/bstnext").data


def test_foto_fehler_sichtbar_und_freigabe_veroeffentlichung_gesperrt(env, monkeypatch):
    c, tmp = env
    monkeypatch.setitem(bs_routes._cfg, "szene_fn", _fake_fn(False))
    c.post("/bstnext/neu", data=_form(), follow_redirects=True)
    e, f = _entwurf()
    assert f["bild_status"] == "fehler" and "lesbare Buchstaben" in f["bild_info"] and not e["bild_pfad"]
    seite = c.get("/bstnext").get_data(as_text=True)
    assert "Bild fehlgeschlagen" in seite and "Bild neu erzeugen" in seite
    r = c.post("/aktion/1", data={"aktion": "freigeben"}, follow_redirects=True)
    assert "noch nicht fertig" in r.get_data(as_text=True)
    assert _entwurf()[0]["status"] == "entwurf"
    # Retry mit funktionierender Erzeugung
    monkeypatch.setitem(bs_routes._cfg, "szene_fn", _fake_fn(True))
    c.post("/bstnext/foto-neu/1", follow_redirects=True)
    e, f = _entwurf()
    assert f["bild_status"] == "fertig" and os.path.exists(e["bild_pfad"])
    c.post("/aktion/1", data={"aktion": "freigeben"}, follow_redirects=True)
    assert _entwurf()[0]["status"] == "freigegeben"


def test_foto_nicht_fertig_wird_nie_veroeffentlicht(env, monkeypatch):
    c, tmp = env
    monkeypatch.setitem(bs_routes._cfg, "szene_fn", _fake_fn(False))
    c.post("/bstnext/neu", data=_form(), follow_redirects=True)
    c.post("/bstnext/seite", data={"seiten": "123"}, follow_redirects=True)
    with db.get_conn() as conn:
        conn.execute("UPDATE entwuerfe SET status='freigegeben' WHERE id=1")   # Freigabe umgangen
        conn.commit()
    aufrufe = []
    monkeypatch.setattr(publish, "publish_facebook", lambda *a, **k: aufrufe.append(a) or (True, "x"))
    monkeypatch.setattr(web, "_sharenext_bild_synchron",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("HILO-Pipeline darf nicht laufen")))
    r = c.post("/veroeffentlichen/1", data={"page_id": "123"}, follow_redirects=True)
    assert "noch nicht fertig" in r.get_data(as_text=True)
    assert aufrufe == []


def test_foto_formularfehler(env, monkeypatch):
    c, tmp = env
    monkeypatch.setitem(bs_routes._cfg, "szene_fn", _fake_fn(True))
    assert "Unbekannter Bildtyp" in c.post("/bstnext/neu", data=_form(motiv="x"), follow_redirects=True).get_data(as_text=True)
    assert "Format" in c.post("/bstnext/neu", data=_form(format="story"), follow_redirects=True).get_data(as_text=True)
    assert "Kachel nicht erzeugbar" in c.post("/bstnext/neu", data=_form(weiss="Donaudampfschifffahrtsgesellschaft"),
                                              follow_redirects=True).get_data(as_text=True)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0] == 0


def test_foto_neu_nur_fuer_fehlerhafte_foto_entwuerfe(env, monkeypatch):
    c, tmp = env
    monkeypatch.setitem(bs_routes._cfg, "szene_fn", _fake_fn(True))
    c.post("/bstnext/neu", data=_form(), follow_redirects=True)
    assert "schon fertig" in c.post("/bstnext/foto-neu/1", follow_redirects=True).get_data(as_text=True)
    assert c.post("/bstnext/foto-neu/99").status_code == 404
    c.post("/bstnext/neu", data=_form(bildtyp="kachel"), follow_redirects=True)
    assert c.post("/bstnext/foto-neu/2").status_code == 404
