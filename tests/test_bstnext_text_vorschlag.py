# -*- coding: utf-8 -*-
"""BSt Next: KI-Entwurf des Begleittextes (Knopf 'Text vorschlagen'). Die KI ist durchgehend gemockt."""
import os
import shutil
import tempfile
from types import SimpleNamespace

import pytest

import db
import web
from bstnext import begleittext, brand, routes as bs_routes

GUTER_TEXT = (
    "Ihre Mitglieder bringen Belege in allen Formaten, und Sie sortieren sie von Hand.\n\n"
    "Mit SortNext ändert sich das. SortNext analysiert und sortiert die Belege der Mitglieder und liefert "
    "das Ergebnis als PDF- und Excel-Datei.\n\n"
    "Wir fangen mit Ihren Belegen an.")


class FakeClient:
    """Liefert nacheinander die vorbereiteten Antworten und merkt sich die Prompts."""
    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.prompts = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        text = self.antworten.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


# ---------- Modul ----------

def test_guter_text_bekommt_link_und_hashtags_fest_angehaengt():
    text = begleittext.erzeuge(["Gut Ding will", "SortNext haben"], client=FakeClient(GUTER_TEXT))
    assert text.startswith(GUTER_TEXT)
    assert "Mehr über BSt Next: http://www.bst-next.de" in text
    assert text.rstrip().endswith(brand.HASHTAGS)


def test_prompt_enthaelt_spruch_produktfakten_und_schlusszeilen_aber_nicht_smartnext_oder_preise():
    c = FakeClient(GUTER_TEXT)
    begleittext.erzeuge(["Gut Ding will", "SortNext haben"], client=c)
    p = c.prompts[0]
    assert "Gut Ding will" in p and "SortNext haben" in p
    for name in ("SortNext", "BookNext", "CallNext", "ShareNext", "HelpNext", "CoachNext"):
        assert name in p
    assert "Wir fangen mit Ihren Belegen an." in p and "Wir fangen mit Ihren Prozessen an." in p
    assert "wird es besser" in p and "Der Beleg fällt nicht weit vom Stapel." in p      # Vorgaben von Casty
    assert "höchstens fünf Sätze" in p and "Schmerzpunkt" in p and "Kurze und lange Sätze abwechseln" in p
    assert "SmartNext" not in p.split("Regeln:")[0] and "CheckNext" not in p.split("Regeln:")[0]
    produkte_teil = p.split("Übersicht statt Chaos):")[1].split("3. Schlusszeile")[0]
    assert "€" not in produkte_teil and not any(ch.isdigit() for ch in produkte_teil)


@pytest.mark.parametrize("schlecht", [
    GUTER_TEXT.replace("Ihre Mitglieder", "Ihre 40 Mitglieder"),                        # Ziffern
    GUTER_TEXT + "\n\n#BStNext",                                                          # Hashtag
    GUTER_TEXT.replace("analysiert", "analysiert vollautomatisch"),                       # unbelegtes Versprechen
    GUTER_TEXT.replace("Mit SortNext", "Mit SmartNext"),                                  # ausgeblendetes Produkt
    GUTER_TEXT.replace("Sie sortieren", "du sortierst"),                                  # Du-Ansprache
    GUTER_TEXT.replace("ändert sich das.", "ändert sich das.\n\n**Fett**"),               # Markdown
    GUTER_TEXT.replace("Wir fangen mit Ihren Belegen an.", "Wir legen los."),             # Schlusszeile weicht ab
])
def test_unbrauchbarer_text_wird_abgelehnt_und_einmal_neu_angefragt(schlecht):
    c = FakeClient(schlecht, GUTER_TEXT)
    text = begleittext.erzeuge(["Gut Ding will"], client=c)
    assert len(c.prompts) == 2 and "abgelehnt" in c.prompts[1]
    assert text.startswith(GUTER_TEXT)


def test_zu_kurzer_text_bekommt_beim_zweiten_versuch_klaren_hinweis_und_log_mit_anfang(caplog):
    c = FakeClient("Gerne, hier ein Vorschlag.", GUTER_TEXT)
    with caplog.at_level("INFO", logger="hilo.bstnext"):
        text = begleittext.erzeuge(["Möge der Scanner mit Dir sein!"], client=c)
    assert text.startswith(GUTER_TEXT)
    assert "alle drei Absätze vollständig aus" in c.prompts[1]
    assert "alle drei Absätze vollständig aus" not in c.prompts[0]
    meldung = " ".join(r.getMessage() for r in caplog.records)
    assert "zu kurz" in meldung and "Gerne, hier ein Vorschlag." in meldung and "Länge=26" in meldung


def test_werbliche_nutzenaussage_ohne_zusicherung_ist_erlaubt():
    werbend = GUTER_TEXT.replace("liefert", "liefert Ihnen Übersicht statt Chaos. Sie sparen Zeit und Fehlerquellen und bekommt")
    assert begleittext.pruefe(werbend) is None
    assert begleittext.pruefe(GUTER_TEXT) is None


def test_prompt_hat_keine_beispieltexte_aber_werbliche_nutzenaussage_und_aufhaenger():
    p = begleittext.baue_prompt(["Gut Ding will"])
    assert "Werbliche Nutzenformulierungen" in p and "Der Beleg fällt nicht weit vom Stapel." in p
    assert "Beispieltexte" not in p and "Papier im falschen Format" in p      # nur als Vergleich in den Stilregeln
    assert "Stunden Handarbeit" not in p and "schon verwendet" not in p


def test_frueher_verwendete_anfaenge_kommen_in_den_prompt_und_die_ki_bekommt_sie():
    c = FakeClient(GUTER_TEXT)
    begleittext.erzeuge(["Gut Ding will"], client=c, vermeiden=["Belege sind wie Post.", "Eine Datei macht nichts."])
    assert "schon verwendet" in c.prompts[0]
    assert "- Belege sind wie Post." in c.prompts[0] and "- Eine Datei macht nichts." in c.prompts[0]


def test_zweimal_unbrauchbar_gibt_klare_meldung():
    c = FakeClient(GUTER_TEXT + " 3 Stunden", GUTER_TEXT + " 3 Stunden")
    with pytest.raises(begleittext.BegleittextFehler) as ex:
        begleittext.erzeuge(["Gut Ding will"], client=c)
    assert "keinen brauchbaren Text" in str(ex.value)


def test_ki_fehler_gibt_meldung_ohne_interna():
    class Kaputt:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("geheimer Fehler 401")))
    with pytest.raises(begleittext.BegleittextFehler) as ex:
        begleittext.erzeuge(["Gut Ding will"], client=Kaputt())
    assert "geheimer" not in str(ex.value) and "gerade nicht möglich" in str(ex.value)


def test_ohne_spruch_keine_ki():
    c = FakeClient(GUTER_TEXT)
    with pytest.raises(begleittext.BegleittextFehler):
        begleittext.erzeuge(["  ", ""], client=c)
    assert c.prompts == []


# ---------- Route / Formular ----------

@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="hilo-test-bstnext-text-")
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tmp, "test.db")
    db.init_db()
    monkeypatch.setitem(bs_routes._cfg, "data_dir", tmp)
    monkeypatch.setitem(bs_routes._cfg, "pages_fn", lambda: ([], None))
    monkeypatch.setitem(bs_routes._cfg, "text_sperre_s", 0)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "test-admin"
        s["rolle"] = "admin"
    yield c
    db.DB_PATH = original
    shutil.rmtree(tmp, ignore_errors=True)


def _anzahl():
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM entwuerfe").fetchone()[0]


def test_route_liefert_text_speichert_aber_nichts(client, monkeypatch):
    gesehen = {}
    def fake(zeilen, **kw):
        gesehen["zeilen"] = zeilen
        return "VORSCHLAG"
    monkeypatch.setitem(bs_routes._cfg, "text_fn", fake)
    r = client.post("/bstnext/text-vorschlag", data={"weiss": "Gut Ding will", "lime": "SortNext haben",
                                                    "weiss_nach": "Nur SortNext in time.", "bildtyp": "kachel"})
    assert r.status_code == 200 and r.get_json() == {"text": "VORSCHLAG"}
    assert gesehen["zeilen"] == ["Gut Ding will", "SortNext haben", "Nur SortNext in time."]
    assert _anzahl() == 0


def test_route_nimmt_beim_karussell_alle_slides_sonst_nicht(client, monkeypatch):
    gesehen = []
    monkeypatch.setitem(bs_routes._cfg, "text_fn", lambda z, **kw: gesehen.append(z) or "X")
    daten = {"weiss": "Eins", "weiss2": "Zwei", "lime3": "Drei"}
    client.post("/bstnext/text-vorschlag", data=dict(daten, bildtyp="karussell"))
    client.post("/bstnext/text-vorschlag", data=dict(daten, bildtyp="kachel"))
    assert gesehen[0] == ["Eins", "Zwei", "Drei"] and gesehen[1] == ["Eins"]


def test_route_ohne_spruch_400_ohne_ki_aufruf(client, monkeypatch):
    aufrufe = []
    monkeypatch.setitem(bs_routes._cfg, "text_fn", lambda z, **kw: aufrufe.append(z) or "X")
    r = client.post("/bstnext/text-vorschlag", data={"weiss": "  "})
    assert r.status_code == 400 and "Spruch" in r.get_json()["fehler"] and aufrufe == []


def test_route_fehler_der_ki_wird_als_meldung_durchgereicht(client, monkeypatch):
    def fake(zeilen, **kw):
        raise begleittext.BegleittextFehler("Meldung für catrin")
    monkeypatch.setitem(bs_routes._cfg, "text_fn", fake)
    r = client.post("/bstnext/text-vorschlag", data={"weiss": "Gut Ding will"})
    assert r.status_code == 502 and r.get_json() == {"fehler": "Meldung für catrin"}


def test_route_unerwarteter_fehler_zeigt_keine_interna(client, monkeypatch):
    def fake(zeilen, **kw):
        raise RuntimeError("Token abc123")
    monkeypatch.setitem(bs_routes._cfg, "text_fn", fake)
    r = client.post("/bstnext/text-vorschlag", data={"weiss": "Gut Ding will"})
    assert r.status_code == 502 and "abc123" not in r.get_data(as_text=True)


def test_route_kostenschutz_zweiter_klick_sofort_danach_wird_gebremst(client, monkeypatch):
    aufrufe = []
    bs_routes._cfg["text_zeit"].clear()
    monkeypatch.setitem(bs_routes._cfg, "text_sperre_s", 60)
    monkeypatch.setitem(bs_routes._cfg, "text_fn", lambda z, **kw: aufrufe.append(z) or "X")
    erster = client.post("/bstnext/text-vorschlag", data={"weiss": "Gut Ding will"})
    zweiter = client.post("/bstnext/text-vorschlag", data={"weiss": "Gut Ding will"})
    assert erster.status_code == 200 and zweiter.status_code == 429 and len(aufrufe) == 1


def test_route_braucht_anmeldung():
    web.app.config["TESTING"] = True
    r = web.app.test_client().post("/bstnext/text-vorschlag", data={"weiss": "Gut Ding will"})
    assert r.status_code in (302, 401, 403)


def test_formular_zeigt_knopf_in_neu_und_bearbeiten(client):
    html = client.get("/bstnext").get_data(as_text=True)
    assert 'id="bn-textvorschlag"' in html and "/bstnext/text-vorschlag" in html and 'id="bn-caption"' in html
    client.post("/bstnext/neu", data={"weiss": "Gut Ding will", "lime": "SortNext haben", "format": "quadrat",
                                      "caption": "Text", "bildtyp": "kachel", "motiv": "belege"})
    html = client.get("/bstnext/bearbeiten/1").get_data(as_text=True)
    assert 'id="bn-textvorschlag"' in html


def test_vorgeschlagener_text_laesst_sich_speichern_hashtags_nicht_doppelt(client):
    text = begleittext.erzeuge(["Gut Ding will"], client=FakeClient(GUTER_TEXT))
    client.post("/bstnext/neu", data={"weiss": "Gut Ding will", "lime": "SortNext haben", "format": "quadrat",
                                      "caption": text, "bildtyp": "kachel", "motiv": "belege"})
    import json
    with db.get_conn() as conn:
        f = json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=1").fetchone()["text"])
    assert f["caption"].count("#BStNext") == 1 and "http://www.bst-next.de" in f["caption"]


def test_route_gibt_fruehere_anfaenge_weiter_und_schliesst_den_bearbeiteten_beitrag_aus(client, monkeypatch):
    for weiss, cap in (("Eins", "Erster Anfang.\n\nRest eins."), ("Zwei", "Zweiter Anfang.\n\nRest zwei.")):
        client.post("/bstnext/neu", data={"weiss": weiss, "lime": "x", "format": "quadrat", "caption": cap,
                                          "bildtyp": "kachel", "motiv": "belege"})
    gesehen = []
    monkeypatch.setitem(bs_routes._cfg, "text_fn", lambda z, **kw: gesehen.append(kw["vermeiden"]) or "X")
    client.post("/bstnext/text-vorschlag", data={"weiss": "Neu"})
    client.post("/bstnext/text-vorschlag?eid=2", data={"weiss": "Neu"})
    assert gesehen[0][:2] == ["Zweiter Anfang.", "Erster Anfang."]
    assert "Zweiter Anfang." not in gesehen[1] and "Erster Anfang." in gesehen[1]
