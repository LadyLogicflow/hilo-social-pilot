# -*- coding: utf-8 -*-
"""Tests fuer Comic-Strip v2 (#155): zwei Story-Archetypen (vorteil/warnung), gesteuert ueber die
Bild-2-Auswahlliste, mit KI-Vorauswahl. Alles GEMOCKT - keine echten KI-/Netz-/Bild-Calls.

Beweist:
  1. Archetyp 'warnung': Feld-1-Prompt = Allein-am-Handy-Szene; Feld-2-Prompt = schadenfroh +
     'ABGELEHNT' + gewaehlte warnung-Variante; Feld-3-Text = "Komm zu HILO ...".
  2. Archetyp 'vorteil': Feld-1-Prompt = Beratungsszene; Feld-2-Prompt = trauriger Aermelschoner +
     vorteil-Variante; Feld-3-Text = "HILO - wir machen es einfach!".
  3. comic_strip_vorauswahl: gemockter Claude bestimmt Archetyp + variant_index; robuster Fallback
     ohne Key (kein Crash, sinnvoller Default aus comic_brief / vorteil).
  4. /bild-generieren: "Automatisch" -> Vorauswahl setzt archetyp + strip_zeile2 (persistiert);
     konkrete Variante -> deren Archetyp abgeleitet + persistiert; Bild-1-Override wirkt weiter.
  5. Bild-2-Dropdown (name=strip_zeile2 + "Automatisch") in allen drei Pickern.

Ausfuehrung:
  HILO_DATA_DIR=/tmp/v2-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_comic_strip_v2.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import textgen

_PASS = []


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    _PASS.append(msg)
    print("  OK:", msg)


def _dummy_png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (32, 32), (180, 200, 160)).save(path)
    return path


def _run_ensure(fields, berater):
    """Ruft ensure_comic_strip_bilder mit gemockten Bild-Funktionen; liefert Liste der Panel-Prompts
    (Feld 1..3) und die refs je Panel."""
    captured = []

    def _fake_ref(prompt, refs):
        captured.append((prompt, list(refs)))
        return b"PANELPNG"

    def _fake_gen(prompt, tool=None):
        captured.append((prompt, []))
        return b"GENPNG"

    orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    try:
        panels = bildmotiv.ensure_comic_strip_bilder(fields, berater)
    finally:
        bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen
    return panels, captured


# --- 1) Archetyp 'warnung' ---------------------------------------------------------------------
def test_1_archetyp_warnung():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "v2_warnung.png"))
    db.set_einstellung("finanzamt_bibel_bild", None)
    variante = bildmotiv.COMIC_STRIP_VARIANTEN["warnung"][1]   # eine konkrete warnung-Variante
    us = "WARNUNG-FELD1-155-A"
    fields = {"bild_stil": "comic_strip", "ueberschrift": us,
              "strip_archetyp": "warnung", "strip_zeile2": variante}
    panels, cap = _run_ensure(fields, berater)
    if len(cap) != 3:
        _fail("warnung: nicht 3 Panels: %d" % len(cap))
    p1, p2, p3 = cap[0][0], cap[1][0], cap[2][0]
    # Feld 1: Allein-am-Handy-Szene (Kernwoerter aus dem warnung-Delta)
    if ("ALLEIN" not in p1) or ("Handy" not in p1):
        _fail("warnung Feld-1-Prompt ist nicht die Allein-am-Handy-Szene: %r" % p1[:200])
    if us not in p1:
        _fail("warnung: Bild-1-Text (Ueberschrift) fehlt im Feld-1-Prompt")
    # Feld 2: schadenfroh + ABGELEHNT + gewaehlte Variante
    if "ABGELEHNT" not in p2 or "schadenfroh" not in p2:
        _fail("warnung Feld-2-Prompt nicht schadenfroh/ABGELEHNT: %r" % p2[:200])
    if variante not in p2:
        _fail("warnung: gewaehlte Bild-2-Variante fehlt im Feld-2-Prompt")
    # Feld 3: Pointe "Komm zu HILO ..."
    if bildmotiv.COMIC_STRIP_POINTE_ARCHETYP["warnung"] not in p3:
        _fail("warnung Feld-3-Text != 'Komm zu HILO ...': %r" % p3[:200])
    if bildmotiv.COMIC_STRIP_POINTE_ARCHETYP["warnung"] != "Komm zu HILO - wir machen es einfach!":
        _fail("warnung-Pointe weicht vom #155-Wortlaut ab")
    # refs unveraendert: Feld 1+3 = Berater, Feld 2 = Finanzamt
    fa = bildmotiv._finanzamt_ref_pfad()
    if cap[0][1] != [berater] or cap[2][1] != [berater] or cap[1][1] != [fa]:
        _fail("warnung: refs falsch (1/3=Berater, 2=Finanzamt erwartet): %r" %
              [cap[0][1], cap[1][1], cap[2][1]])
    _ok("Archetyp warnung: Allein-am-Handy / schadenfroh+ABGELEHNT+Variante / 'Komm zu HILO ...'; refs unveraendert")


# --- 2) Archetyp 'vorteil' ---------------------------------------------------------------------
def test_2_archetyp_vorteil():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "v2_vorteil.png"))
    db.set_einstellung("finanzamt_bibel_bild", None)
    variante = bildmotiv.COMIC_STRIP_VARIANTEN["vorteil"][2]
    us = "VORTEIL-FELD1-155-B"
    fields = {"bild_stil": "comic_strip", "ueberschrift": us,
              "strip_archetyp": "vorteil", "strip_zeile2": variante}
    panels, cap = _run_ensure(fields, berater)
    p1, p2, p3 = cap[0][0], cap[1][0], cap[2][0]
    # Feld 1: Beratungsszene (Berater + Mitglied)
    if "Beratungsraum" not in p1 and "Mitglied" not in p1:
        _fail("vorteil Feld-1-Prompt ist nicht die Beratungsszene: %r" % p1[:200])
    if "ALLEIN" in p1 or "Handy" in p1:
        _fail("vorteil Feld-1-Prompt enthaelt faelschlich die warnung-Szene")
    if us not in p1:
        _fail("vorteil: Bild-1-Text (Ueberschrift) fehlt im Feld-1-Prompt")
    # Feld 2: trauriger Aermelschoner + vorteil-Variante, NICHT ABGELEHNT
    if "deprimiert" not in p2 and "geknickt" not in p2:
        _fail("vorteil Feld-2-Prompt nicht traurig/geknickt: %r" % p2[:200])
    if "ABGELEHNT" in p2:
        _fail("vorteil Feld-2-Prompt enthaelt faelschlich 'ABGELEHNT'")
    if variante not in p2:
        _fail("vorteil: gewaehlte Bild-2-Variante fehlt im Feld-2-Prompt")
    # Feld 3: "HILO - wir machen es einfach!"
    if bildmotiv.COMIC_STRIP_POINTE_ARCHETYP["vorteil"] not in p3:
        _fail("vorteil Feld-3-Text != 'HILO - wir machen es einfach!': %r" % p3[:200])
    if bildmotiv.COMIC_STRIP_POINTE_ARCHETYP["vorteil"] != "HILO - wir machen es einfach!":
        _fail("vorteil-Pointe weicht vom #155-Wortlaut ab")
    _ok("Archetyp vorteil: Beratungsszene / trauriger Aermelschoner+Variante / 'HILO - wir machen es einfach!'")


# --- 3) Default-Bild-2-Text ohne strip_zeile2 (Rueckwaertskompatibilitaet) ---------------------
def test_3_default_bild2():
    # vorteil ohne strip_zeile2 -> v1-Default COMIC_STRIP_JAMMER
    if bildmotiv._comic_strip_zeile({}, "jammer", "vorteil") != bildmotiv.COMIC_STRIP_JAMMER:
        _fail("vorteil-Default (ohne strip_zeile2) != COMIC_STRIP_JAMMER")
    # warnung ohne strip_zeile2 -> erste warnung-Variante
    if bildmotiv._comic_strip_zeile({}, "jammer", "warnung") != bildmotiv.COMIC_STRIP_VARIANTEN["warnung"][0]:
        _fail("warnung-Default (ohne strip_zeile2) != erste warnung-Variante")
    # gesetztes strip_zeile2 hat Vorrang
    if bildmotiv._comic_strip_zeile({"strip_zeile2": "MEINE-ZEILE"}, "jammer", "warnung") != "MEINE-ZEILE":
        _fail("gesetztes strip_zeile2 wird nicht bevorzugt")
    # 2-arg-Signatur (v1) bleibt gueltig -> Default vorteil
    if bildmotiv._comic_strip_zeile({}, "pointe") != bildmotiv.COMIC_STRIP_POINTE:
        _fail("2-arg _comic_strip_zeile(pointe) != COMIC_STRIP_POINTE (v1-kompatibel)")
    _ok("Default-Bild-2: vorteil=JAMMER, warnung=erste Variante; strip_zeile2 hat Vorrang; 2-arg-Signatur bleibt")


# --- 4) _comic_strip_variante_archetyp (Zuordnung Variante -> Archetyp) ------------------------
def test_4_variante_zuordnung():
    for arche in ("vorteil", "warnung"):
        for v in bildmotiv.COMIC_STRIP_VARIANTEN[arche]:
            if bildmotiv._comic_strip_variante_archetyp(v) != arche:
                _fail("Variante %r nicht als %s erkannt" % (v, arche))
    if bildmotiv._comic_strip_variante_archetyp("unbekannter Text") is not None:
        _fail("unbekannte Variante muss None liefern")
    if bildmotiv._comic_strip_variante_archetyp("") is not None:
        _fail("leerer Text muss None liefern")
    _ok("_comic_strip_variante_archetyp ordnet jede Variante ihrem Archetyp zu; unbekannt -> None")


# --- 5) comic_strip_vorauswahl: gemockter Claude bestimmt Archetyp/Index -----------------------
def test_5_vorauswahl_gemockt():
    class _Blob:
        def __init__(self, t): self.text = t

    class _Msg:
        def __init__(self, t): self.content = [_Blob(t)]

    class _FakeClient:
        def __init__(self, payload): self._p = payload
        class _M:
            pass
        @property
        def messages(self):
            outer = self
            class _MM:
                def create(self, **kw): return _Msg(outer._p)
            return _MM()

    vor = textgen.comic_strip_vorauswahl(
        {"ueberschrift": "X", "caption": "Y"},
        client=_FakeClient('{"archetyp": "warnung", "variant_index": 2}'))
    if vor.get("archetyp") != "warnung" or vor.get("variant_index") != 2:
        _fail("gemockte Vorauswahl falsch ausgewertet: %r" % vor)

    # Ungueltiger Index -> auf 0 geklemmt; ungueltiger Archetyp -> Fallback
    vor2 = textgen.comic_strip_vorauswahl(
        {"ueberschrift": "X"},
        client=_FakeClient('{"archetyp": "warnung", "variant_index": 99}'))
    if vor2.get("archetyp") != "warnung" or vor2.get("variant_index") != 0:
        _fail("Index-Klemmung fehlgeschlagen: %r" % vor2)
    _ok("comic_strip_vorauswahl (gemockter Claude): Archetyp+Index korrekt; Index-Klemmung wirkt")


# --- 6) Fallback ohne Key -> kein Crash, sinnvoller Default ------------------------------------
def test_6_vorauswahl_fallback():
    # Ohne Key (kein anthropic_api_key im Test) -> Fallback. finanzamt_figur + nicht-positiv -> warnung.
    vor_w = textgen.comic_strip_vorauswahl(
        {"ueberschrift": "Frist verpasst",
         "comic_brief": {"stimmung": "humor", "finanzamt_figur": True}})
    if vor_w.get("archetyp") != "warnung":
        _fail("Fallback: finanzamt+humor sollte 'warnung' liefern: %r" % vor_w)
    # positive Stimmung -> vorteil
    vor_v = textgen.comic_strip_vorauswahl(
        {"comic_brief": {"stimmung": "positiv", "finanzamt_figur": True}})
    if vor_v.get("archetyp") != "vorteil":
        _fail("Fallback: positive Stimmung sollte 'vorteil' liefern: %r" % vor_v)
    # gar keine Info -> Default vorteil, Index 0, kein Crash
    vor_d = textgen.comic_strip_vorauswahl({})
    if vor_d != {"archetyp": "vorteil", "variant_index": 0}:
        _fail("Fallback-Default (leere fields) falsch: %r" % vor_d)
    _ok("Fallback ohne Key: kein Crash; warnung/vorteil aus comic_brief abgeleitet; Default vorteil/0")


# --- 7) _comic_strip_archetyp: Vorrang strip_archetyp, sonst Vorauswahl/Fallback ---------------
def test_7_archetyp_aufloesung():
    if bildmotiv._comic_strip_archetyp({"strip_archetyp": "warnung"}) != "warnung":
        _fail("_comic_strip_archetyp ignoriert explizites strip_archetyp")
    if bildmotiv._comic_strip_archetyp({"strip_archetyp": "quatsch"}) != "vorteil":
        _fail("ungueltiges strip_archetyp -> muss auf Vorauswahl/Default 'vorteil' fallen")
    # ohne strip_archetyp + ohne Key -> Fallback aus comic_brief
    a = bildmotiv._comic_strip_archetyp(
        {"comic_brief": {"stimmung": "sachlich", "finanzamt_figur": True}})
    if a != "warnung":
        _fail("_comic_strip_archetyp Fallback (finanzamt+sachlich) sollte 'warnung' sein: %r" % a)
    if bildmotiv._comic_strip_archetyp({}) != "vorteil":
        _fail("_comic_strip_archetyp leere fields -> Default 'vorteil'")
    _ok("_comic_strip_archetyp: strip_archetyp hat Vorrang; sonst KI-Vorauswahl/Fallback; Default vorteil")


# --- 8) Bild-2-Dropdown in allen drei Pickern -------------------------------------------------
def test_8_dropdown_in_pickern():
    import web
    for name, tpl in (("ENTWUERFE", web.ENTWUERFE), ("EINPLANUNG", web.EINPLANUNG),
                      ("POOL", web.POOL)):
        if "name=strip_zeile2" not in tpl:
            _fail("Picker %s enthaelt das Bild-2-Dropdown (name=strip_zeile2) nicht" % name)
        if "Automatisch" not in tpl:
            _fail("Picker %s enthaelt die Option 'Automatisch' nicht" % name)
        if "strip_varianten.get('vorteil'" not in tpl or "strip_varianten.get('warnung'" not in tpl:
            _fail("Picker %s rendert die Varianten-Optgroups nicht" % name)
        if "e.f.strip_zeile2" not in tpl:
            _fail("Picker %s belegt das Dropdown nicht mit dem gespeicherten Wert vor" % name)
    _ok("Bild-2-Dropdown (strip_zeile2, Automatisch, Varianten-Optgroups, vorbelegt) in allen drei Pickern")


# --- 9) /bild-generieren: Automatisch vs. konkrete Variante -> Persistenz + Durchreichung ------
def test_9_route_persistenz():
    import json as _json
    import web
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"

    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "v2_stelle.png"))
    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(name, ort, aktiv, berater_comic) "
                     "VALUES (?,?,1,?)", ("Teststelle 155", "Musterstadt", berater))
        cur = conn.execute("INSERT INTO entwuerfe(text, status) VALUES (?, 'entwurf')",
                           (_json.dumps({"ueberschrift": "URSPRUNG-155"}),))
        conn.commit()
        eid = cur.lastrowid

    gesehen = {}
    dummy_panel = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "bilder", "panel_155.png"))

    def _fake_ensure(fields, berater_ref):
        gesehen["strip_archetyp"] = (fields or {}).get("strip_archetyp")
        gesehen["strip_zeile2"] = (fields or {}).get("strip_zeile2")
        gesehen["strip_zeile1"] = (fields or {}).get("strip_zeile1")
        return [dummy_panel, dummy_panel, dummy_panel]

    orig_ensure = bildmotiv.ensure_comic_strip_bilder
    bildmotiv.ensure_comic_strip_bilder = _fake_ensure
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = "admin"
    try:
        # (a) Konkrete warnung-Variante gewaehlt -> Archetyp abgeleitet + persistiert.
        variante = bildmotiv.COMIC_STRIP_VARIANTEN["warnung"][0]
        c.post("/bild-generieren/%d" % eid,
               data={"bild_stil": "comic_strip", "zurueck": "entwuerfe",
                     "strip_zeile1": "  OVERRIDE-155  ", "strip_zeile2": variante})
        if gesehen.get("strip_archetyp") != "warnung":
            _fail("konkrete warnung-Variante -> Archetyp kam nicht als 'warnung' an: %r" % gesehen)
        if gesehen.get("strip_zeile2") != variante:
            _fail("konkrete Variante wurde nicht durchgereicht: %r" % gesehen.get("strip_zeile2"))
        if gesehen.get("strip_zeile1") != "OVERRIDE-155":
            _fail("Bild-1-Override (#156) wirkt nicht mehr: %r" % gesehen.get("strip_zeile1"))
        with db.get_conn() as conn:
            data = _json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])
        if data.get("strip_archetyp") != "warnung" or data.get("strip_zeile2") != variante:
            _fail("Archetyp/Variante nicht im Entwurf-JSON persistiert: %r" % data)

        # (b) "Automatisch" (leer) -> Vorauswahl setzt Archetyp + eine konkrete Variante, persistiert.
        c.post("/bild-generieren/%d" % eid,
               data={"bild_stil": "comic_strip", "zurueck": "entwuerfe",
                     "strip_zeile1": "", "strip_zeile2": ""})
        arche = gesehen.get("strip_archetyp")
        if arche not in ("vorteil", "warnung"):
            _fail("Automatisch: kein gueltiger Archetyp gesetzt: %r" % arche)
        z2 = gesehen.get("strip_zeile2")
        if z2 not in bildmotiv.COMIC_STRIP_VARIANTEN.get(arche, []):
            _fail("Automatisch: gesetzte Variante gehoert nicht zum Archetyp: %r/%r" % (arche, z2))
        with db.get_conn() as conn:
            data2 = _json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])
        if data2.get("strip_archetyp") != arche or data2.get("strip_zeile2") != z2:
            _fail("Automatisch: Archetyp/Variante nicht persistiert: %r" % data2)
    finally:
        bildmotiv.ensure_comic_strip_bilder = orig_ensure
    _ok("/bild-generieren: konkrete Variante -> Archetyp abgeleitet; Automatisch -> Vorauswahl; beides persistiert; #156-Override wirkt")


def main():
    db.init_db()
    test_1_archetyp_warnung()
    test_2_archetyp_vorteil()
    test_3_default_bild2()
    test_4_variante_zuordnung()
    test_5_vorauswahl_gemockt()
    test_6_vorauswahl_fallback()
    test_7_archetyp_aufloesung()
    test_8_dropdown_in_pickern()
    test_9_route_persistenz()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
