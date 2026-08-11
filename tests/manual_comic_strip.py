# -*- coding: utf-8 -*-
"""Tests fuer den Post-Typ "Comic-Strip" (comic_strip, #154) - 3-Felder-Karussell mit Sprechblasen.

Beweist die VERDRAHTUNG (KEINE echten externen KI-/Bild-APIs - alles gemockt):

  1. stilwahl: STILE/_FLAG_KEY kennen 'comic_strip'; aktiver_stil erkennt ihn; er ist per Default
     NICHT im Zufalls-Topf (aktive_stile) - so kann er keinem Beitrag zufaellig zugelost werden.
  2. ensure_comic_strip_bilder: erzeuge_comic_bild_ref/erzeuge_bild gepatcht ->
     (a) genau 3 Panels;
     (b) Feld 1+3 refs == [Berater-Ref], Feld 2 refs == [Finanzamt-Ref];
     (c) die drei Zeilen (ueberschrift / COMIC_STRIP_JAMMER / COMIC_STRIP_POINTE) stehen jeweils
         im richtigen Panel-Prompt (und jeder Panel-Prompt basiert auf HILO_COMIC_MASTER);
     (e) Fallback ohne Berater-Ref -> KEIN Crash, weiterhin 3 Panels (via generations-Weg).
  3. render_slides_fuer_stelle liefert bei comic_strip eine 3er-Slide-Liste (mit und ohne
     Berater-Referenz der Stelle).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/cs-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/manual_comic_strip.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import stilwahl
import personalisierung

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


def _fields(ueberschrift):
    return {"bild_stil": "comic_strip", "ueberschrift": ueberschrift}


# --- 1) stilwahl kennt comic_strip, aber NICHT im Zufalls-Topf --------------------------------
def test_1_stilwahl():
    if "comic_strip" not in stilwahl.STILE:
        _fail("stilwahl.STILE enthaelt 'comic_strip' nicht: %r" % (stilwahl.STILE,))
    if stilwahl._FLAG_KEY.get("comic_strip") != "bild_stil_comic_strip":
        _fail("_FLAG_KEY['comic_strip'] falsch: %r" % stilwahl._FLAG_KEY.get("comic_strip"))
    if stilwahl.aktiver_stil({"bild_stil": "comic_strip"}) != "comic_strip":
        _fail("aktiver_stil erkennt comic_strip nicht")
    # Default aller Flags zuruecksetzen -> comic_strip darf NICHT im Zufalls-Topf sein (Flag-Default 0),
    # alle uebrigen Stile aber schon (Zufallswahl bleibt unveraendert).
    for k in ("bild_stil_standard", "bild_stil_ki_tafel", "bild_stil_kreativ", "bild_stil_comic",
              "bild_stil_comic_beratung", "bild_stil_comic_strip"):
        db.set_einstellung(k, None)
    aktiv = stilwahl.aktive_stile()
    if "comic_strip" in aktiv:
        _fail("comic_strip ist faelschlich im Zufalls-Topf (aktive_stile): %r" % aktiv)
    if set(aktiv) != {"standard", "ki_tafel", "kreativ", "comic", "comic_beratung"}:
        _fail("Zufalls-Topf ohne comic_strip weicht ab: %r" % aktiv)
    # waehle_stil darf comic_strip NIE liefern (Default-Flags)
    for _ in range(200):
        if stilwahl.waehle_stil(None, {}) == "comic_strip":
            _fail("waehle_stil lieferte comic_strip (darf nicht im Zufalls-Topf sein)")
    _ok("stilwahl: comic_strip registriert + erkannt; NICHT im Zufalls-Topf (Default-Flag 0)")


# --- 2) ensure_comic_strip_bilder: 3 Panels, refs, Prompts -----------------------------------
def test_2_panels_refs_prompts():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_154.png"))
    db.set_einstellung("finanzamt_bibel_bild", None)   # -> _finanzamt_ref_pfad = FINANZAMT_REF_PATH
    fa_ref = bildmotiv._finanzamt_ref_pfad()
    if not os.path.exists(fa_ref):
        _fail("Finanzamt-Referenz nicht vorhanden (Asset fehlt?): %r" % fa_ref)

    ueberschrift = "STRIP-UEBERSCHRIFT-EINDEUTIG-154-A"
    captured = []          # je Panel: (prompt, refs)
    gen_called = {"n": 0}

    def _fake_ref(prompt, refs):
        captured.append((prompt, list(refs)))
        return b"PANELPNG"

    def _fake_gen(prompt, tool=None):
        gen_called["n"] += 1
        return b"GENPNG"

    orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    try:
        panels = bildmotiv.ensure_comic_strip_bilder(_fields(ueberschrift), berater)
    finally:
        bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen

    # (a) genau 3 Panels, alle existieren
    if len(panels) != 3:
        _fail("ensure_comic_strip_bilder lieferte nicht genau 3 Panels: %r" % panels)
    if any((not p) or (not os.path.exists(p)) for p in panels):
        _fail("nicht alle Panel-Pfade existieren: %r" % panels)
    if len(captured) != 3:
        _fail("erzeuge_comic_bild_ref wurde nicht genau 3x aufgerufen: %d" % len(captured))
    if gen_called["n"] != 0:
        _fail("erzeuge_bild (generations) wurde faelschlich aufgerufen (alle refs lagen vor)")

    # (b) refs: Feld 1+3 = Berater, Feld 2 = Finanzamt
    if captured[0][1] != [berater]:
        _fail("Feld 1 refs != [berater]: %r" % captured[0][1])
    if captured[1][1] != [fa_ref]:
        _fail("Feld 2 refs != [finanzamt_ref]: %r" % captured[1][1])
    if captured[2][1] != [berater]:
        _fail("Feld 3 refs != [berater]: %r" % captured[2][1])

    # (c) Zeilen im richtigen Panel-Prompt + jeder Prompt basiert auf HILO_COMIC_MASTER
    for i, (prompt, _refs) in enumerate(captured):
        if bildmotiv.HILO_COMIC_MASTER not in prompt:
            _fail("Panel %d-Prompt basiert nicht auf HILO_COMIC_MASTER" % (i + 1))
    if ueberschrift not in captured[0][0]:
        _fail("Ueberschrift steht nicht im Feld-1-Prompt")
    if bildmotiv.COMIC_STRIP_JAMMER not in captured[1][0]:
        _fail("COMIC_STRIP_JAMMER steht nicht im Feld-2-Prompt")
    if bildmotiv.COMIC_STRIP_POINTE not in captured[2][0]:
        _fail("COMIC_STRIP_POINTE steht nicht im Feld-3-Prompt")
    # Die feste Pointe muss exakt der Auftrags-Wortlaut sein.
    if bildmotiv.COMIC_STRIP_POINTE != "HILO - wir machen es einfach!":
        _fail("COMIC_STRIP_POINTE weicht vom Auftrags-Wortlaut ab: %r" % bildmotiv.COMIC_STRIP_POINTE)
    # Sprechblasen-Anweisung (Variante A): exakter Text + Markenname HILO.
    if 'Sprech-/Gedankenblase mit exakt diesem deutschen Text' not in captured[0][0]:
        _fail("Sprechblasen-Anweisung fehlt im Panel-Prompt")
    _ok("ensure_comic_strip_bilder: 3 Panels; refs [berater/finanzamt/berater]; Zeilen je Panel-Prompt")


# --- 2e) Fallback ohne Berater-Ref -> kein Crash, weiterhin 3 Panels --------------------------
def test_3_fallback_ohne_berater():
    ueberschrift = "STRIP-UEBERSCHRIFT-EINDEUTIG-154-B"
    db.set_einstellung("finanzamt_bibel_bild", None)
    ref_calls = {"n": 0}
    gen_calls = {"n": 0}

    def _fake_ref(prompt, refs):
        ref_calls["n"] += 1
        return b"PANELPNG"

    def _fake_gen(prompt, tool=None):
        gen_calls["n"] += 1
        return b"GENPNG"

    orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    try:
        panels = bildmotiv.ensure_comic_strip_bilder(_fields(ueberschrift), "")
    finally:
        bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen

    if len(panels) != 3:
        _fail("Fallback ohne Berater: nicht 3 Panels: %r" % panels)
    if any(not os.path.exists(p) for p in panels):
        _fail("Fallback: nicht alle Panel-Pfade existieren: %r" % panels)
    # Feld 2 hat weiterhin die Finanzamt-Referenz -> 1x Referenz-Call; Feld 1+3 ohne Berater ->
    # 2x generations-Weg (kein Crash).
    if ref_calls["n"] != 1:
        _fail("Fallback: erwartete genau 1 Referenz-Call (Finanzamt), war %d" % ref_calls["n"])
    if gen_calls["n"] != 2:
        _fail("Fallback: erwartete 2 generations-Calls (Feld 1+3), war %d" % gen_calls["n"])
    _ok("Fallback ohne Berater-Ref: 3 Panels, kein Crash (Feld1/3 via generations, Feld2 via Finanzamt-Ref)")


# --- 3) render_slides_fuer_stelle liefert bei comic_strip 3 Pfade ----------------------------
def test_4_render_slides_fuer_stelle():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_2154.png"))

    def _fake_ref(prompt, refs):
        return b"PANELPNG"

    def _fake_gen(prompt, tool=None):
        return b"GENPNG"

    orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    out_dir = os.path.join(bildmotiv.DATA_DIR, "bilder", "cs_test")
    try:
        # a) Stelle MIT Berater-Comic -> 3 Panels
        st = {"berater_comic": berater, "bibel_bild": None, "portrait_pfad": None}
        f = _fields("STRIP-UEBERSCHRIFT-EINDEUTIG-154-C")
        _felder, paths = personalisierung.render_slides_fuer_stelle(f, st, out_dir, "slide")
        if len(paths) != 3:
            _fail("render_slides_fuer_stelle (mit Berater) lieferte nicht 3 Pfade: %r" % paths)
        if any(not os.path.exists(p) for p in paths):
            _fail("render_slides_fuer_stelle: Pfade existieren nicht: %r" % paths)

        # b) Stelle OHNE Berater-Comic -> degradiert, aber weiterhin 3 Panels, kein Crash
        st_ohne = {"berater_comic": None, "bibel_bild": None, "portrait_pfad": None}
        f2 = _fields("STRIP-UEBERSCHRIFT-EINDEUTIG-154-D")
        _felder2, paths2 = personalisierung.render_slides_fuer_stelle(f2, st_ohne, out_dir, "slide")
        if len(paths2) != 3:
            _fail("render_slides_fuer_stelle (ohne Berater) lieferte nicht 3 Pfade: %r" % paths2)
    finally:
        bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen
    _ok("render_slides_fuer_stelle: comic_strip -> 3 Panel-Pfade (mit und ohne Berater der Stelle)")


# --- 4) Picker + /bild-generieren-Whitelist --------------------------------------------------
def test_5_picker_und_whitelist():
    import web
    for name, tpl in (("ENTWUERFE", web.ENTWUERFE), ("EINPLANUNG", web.EINPLANUNG),
                      ("POOL", web.POOL)):
        if 'value="comic_strip"' not in tpl or "Comic-Strip" not in tpl:
            _fail("Picker %s enthaelt die Option 'Comic-Strip' nicht" % name)
    _ok("Picker /entwuerfe, /pool, /einplanung enthalten die Option 'Comic-Strip'")

    # Whitelist: comic_strip kommt an der Stil-Pruefung vorbei (kein "Bitte einen Stil wählen."),
    # ohne aktive Stelle mit Berater -> Hinweis-Flash + KEIN Bild.
    import json as _json
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(text, status) VALUES (?, 'entwurf')",
                           (_json.dumps({"ueberschrift": "X"}),))
        conn.commit()
        eid = cur.lastrowid

    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = "admin"

    c.post("/bild-generieren/%d" % eid, data={"bild_stil": "comic_strip", "zurueck": "entwuerfe"})
    with c.session_transaction() as sess:
        flashes = [m for _, m in sess.get("_flashes", [])]
    if any("Bitte einen Stil" in m for m in flashes):
        _fail("comic_strip wurde faelschlich als ungueltiger Stil abgewiesen: %r" % flashes)
    if not any("Comic-Berater in der Beratungsstellen-Verwaltung" in m for m in flashes):
        _fail("comic_strip ohne Berater: erwarteter Hinweis-Flash fehlt: %r" % flashes)
    with db.get_conn() as conn:
        row = conn.execute("SELECT bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if row["bild_pfad"]:
        _fail("comic_strip-Vorschau ohne Berater hat faelschlich ein Bild erzeugt")
    _ok("Whitelist akzeptiert comic_strip; Vorschau ohne Berater -> Hinweis + kein Bild")


# --- 6) #156: optionales Override fuer Feld 1 (strip_zeile1) ---------------------------------
def test_6_override_feld1():
    # 6a) _comic_strip_zeile direkt: nicht-leeres Override -> Vorrang vor der Ueberschrift;
    #     leeres/fehlendes Override -> weiter die Ueberschrift. Feld 2/3 IMMER unveraendert.
    ueberschrift = "URSPRUNG-UEBERSCHRIFT-156"
    override = "EIGENER-FELD1-SATZ-156"
    mit = {"ueberschrift": ueberschrift, "strip_zeile1": override}
    ohne = {"ueberschrift": ueberschrift, "strip_zeile1": ""}
    fehlt = {"ueberschrift": ueberschrift}
    if bildmotiv._comic_strip_zeile(mit, "ueberschrift") != override:
        _fail("Override wird bei 'ueberschrift' nicht bevorzugt")
    if bildmotiv._comic_strip_zeile(ohne, "ueberschrift") != ueberschrift:
        _fail("leeres Override -> es muss weiter die Ueberschrift gelten")
    if bildmotiv._comic_strip_zeile(fehlt, "ueberschrift") != ueberschrift:
        _fail("fehlendes Override -> es muss weiter die Ueberschrift gelten")
    # Whitespace-only Override zaehlt als leer
    if bildmotiv._comic_strip_zeile({"ueberschrift": ueberschrift, "strip_zeile1": "   "},
                                    "ueberschrift") != ueberschrift:
        _fail("Whitespace-only Override muss als leer gelten (weiter Ueberschrift)")
    # Feld 2/3 duerfen sich durch das Override NICHT aendern
    if bildmotiv._comic_strip_zeile(mit, "jammer") != bildmotiv.COMIC_STRIP_JAMMER:
        _fail("Override hat faelschlich Feld 2 (Jammer) veraendert")
    if bildmotiv._comic_strip_zeile(mit, "pointe") != bildmotiv.COMIC_STRIP_POINTE:
        _fail("Override hat faelschlich Feld 3 (Pointe) veraendert")

    # 6b) ensure_comic_strip_bilder: gesetztes Override landet im Panel-1-Prompt STATT der
    #     Ueberschrift; Feld 2 = Jammer, Feld 3 = Pointe unveraendert.
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_156.png"))
    db.set_einstellung("finanzamt_bibel_bild", None)

    def _run(fields):
        captured = []

        def _fake_ref(prompt, refs):
            captured.append(prompt)
            return b"PANELPNG"

        def _fake_gen(prompt, tool=None):
            captured.append(prompt)
            return b"GENPNG"

        orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
        bildmotiv.erzeuge_comic_bild_ref = _fake_ref
        bildmotiv.erzeuge_bild = _fake_gen
        try:
            bildmotiv.ensure_comic_strip_bilder(fields, berater)
        finally:
            bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen
        return captured

    us_a = "PANEL1-UEBERSCHRIFT-156-A"
    ov_a = "PANEL1-OVERRIDE-156-A"
    cap = _run({"bild_stil": "comic_strip", "ueberschrift": us_a, "strip_zeile1": ov_a})
    if len(cap) != 3:
        _fail("Override-Lauf: nicht genau 3 Panel-Prompts: %r" % len(cap))
    if ov_a not in cap[0]:
        _fail("Override steht NICHT im Panel-1-Prompt")
    if us_a in cap[0]:
        _fail("Ueberschrift steht faelschlich weiter im Panel-1-Prompt (Override sollte ersetzen)")
    if bildmotiv.COMIC_STRIP_JAMMER not in cap[1]:
        _fail("Feld 2 (Jammer) im Override-Lauf veraendert")
    if bildmotiv.COMIC_STRIP_POINTE not in cap[2]:
        _fail("Feld 3 (Pointe) im Override-Lauf veraendert")
    if ov_a in cap[1] or ov_a in cap[2]:
        _fail("Override ist faelschlich in Feld 2/3 gelandet")

    # 6c) leeres Override -> Panel-1 enthaelt weiter die Ueberschrift (neue Ueberschrift -> neuer Cache)
    us_b = "PANEL1-UEBERSCHRIFT-156-B"
    cap2 = _run({"bild_stil": "comic_strip", "ueberschrift": us_b, "strip_zeile1": ""})
    if us_b not in cap2[0]:
        _fail("leeres Override: Ueberschrift fehlt im Panel-1-Prompt")
    _ok("#156 Override Feld 1: strip_zeile1 ersetzt die Ueberschrift in Panel 1; leer -> Ueberschrift; Feld 2/3 unveraendert")


# --- 7) #156: optionales Textfeld in ALLEN DREI Pickern (Entwuerfe/Pool/Einplanung) -----------
def test_7_override_input_in_pickern():
    import web
    for name, tpl in (("ENTWUERFE", web.ENTWUERFE), ("EINPLANUNG", web.EINPLANUNG),
                      ("POOL", web.POOL)):
        if "name=strip_zeile1" not in tpl:
            _fail("Picker %s enthaelt das Override-Feld (name=strip_zeile1) nicht" % name)
        if "e.f.strip_zeile1" not in tpl:
            _fail("Picker %s befuellt das Override-Feld nicht mit dem gespeicherten Wert" % name)
    _ok("#156 Override-Textfeld ist in allen drei Pickern (Entwuerfe/Pool/Einplanung) vorhanden + vorbefuellt")


# --- 8) #156: Override wird ueber /bild-generieren persistiert + bis ensure_... durchgereicht --
def test_8_route_persistiert_override():
    import json as _json
    import web
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"

    # Aktive Stelle MIT Berater-Referenz, damit der comic_strip-Zweig nicht vorzeitig abbricht.
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_stelle_156.png"))
    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(name, ort, aktiv, berater_comic) "
                     "VALUES (?,?,1,?)", ("Teststelle 156", "Musterstadt", berater))
        cur = conn.execute("INSERT INTO entwuerfe(text, status) VALUES (?, 'entwurf')",
                           (_json.dumps({"ueberschrift": "URSPRUNG-156"}),))
        conn.commit()
        eid = cur.lastrowid

    # ensure_comic_strip_bilder mocken (keine echte Bild-KI) + die uebergebenen fields mitschneiden.
    gesehen = {}
    dummy_panel = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "bilder", "panel_156.png"))

    def _fake_ensure(fields, berater_ref):
        gesehen["strip_zeile1"] = (fields or {}).get("strip_zeile1")
        return [dummy_panel, dummy_panel, dummy_panel]

    orig = bildmotiv.ensure_comic_strip_bilder
    bildmotiv.ensure_comic_strip_bilder = _fake_ensure
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = "admin"
    try:
        # (a) Override gesetzt -> muss bei ensure_... ankommen UND im Entwurf-JSON persistiert werden.
        c.post("/bild-generieren/%d" % eid,
               data={"bild_stil": "comic_strip", "zurueck": "entwuerfe",
                     "strip_zeile1": "  ROUTE-OVERRIDE-156  "})
        if gesehen.get("strip_zeile1") != "ROUTE-OVERRIDE-156":
            _fail("Override kam nicht (getrimmt) in ensure_comic_strip_bilder an: %r" % gesehen.get("strip_zeile1"))
        with db.get_conn() as conn:
            data = _json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])
        if data.get("strip_zeile1") != "ROUTE-OVERRIDE-156":
            _fail("Override wurde nicht im Entwurf-JSON persistiert: %r" % data.get("strip_zeile1"))

        # (b) leeres Override -> wird auf '' zurueckgesetzt (wieder Ueberschrift).
        c.post("/bild-generieren/%d" % eid,
               data={"bild_stil": "comic_strip", "zurueck": "entwuerfe", "strip_zeile1": ""})
        with db.get_conn() as conn:
            data2 = _json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])
        if data2.get("strip_zeile1") != "":
            _fail("leeres Override wurde nicht als '' persistiert (Reset): %r" % data2.get("strip_zeile1"))
    finally:
        bildmotiv.ensure_comic_strip_bilder = orig
    _ok("#156 /bild-generieren reicht strip_zeile1 bis ensure_comic_strip_bilder durch + persistiert es (Reset bei leer)")


def test_9_ref_signatur_invalidiert_cache():
    """#158: Wird die Berater- ODER Finanzamt-Referenz durch ein neues Bild MIT GLEICHEM DATEINAMEN
    (neue mtime) ersetzt, MUSS sich der Panel-Cache-Pfad aendern. Panel 1/3 haengen an der Berater-
    Referenz, Panel 2 (Finanzamt) an _finanzamt_ref_pfad. Ohne Aenderung bleibt der Pfad gleich."""
    prompt = "PANEL-PROMPT-REFSIG-158"
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_refsig.png"))

    # (a) Berater-Panel (idx 0): unveraendert -> gleicher Pfad, ersetzt (neue mtime) -> neuer Pfad.
    p0 = bildmotiv._comic_strip_pfad(0, prompt, berater, tool="openai")
    if bildmotiv._comic_strip_pfad(0, prompt, berater, tool="openai") != p0:
        _fail("#158: unveraenderte Berater-Referenz aendert den Panel-Pfad (nicht mehr effizient)")
    t = os.path.getmtime(berater)
    os.utime(berater, (t + 10, t + 10))
    if bildmotiv._comic_strip_pfad(0, prompt, berater, tool="openai") == p0:
        _fail("#158: ersetzte Berater-Referenz (neue mtime) erzeugt KEINEN neuen Panel-Pfad")

    # (b) Finanzamt-Panel (idx 1): ein ersetztes Finanzamt-Bible-Bild muss Panel 2 erneuern,
    # obwohl Berater/Prompt unveraendert bleiben.
    fa = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "bibeln", "finanzamt.png"))
    db.set_einstellung("finanzamt_bibel_bild", fa)  # -> _finanzamt_ref_pfad = fa
    try:
        if bildmotiv._finanzamt_ref_pfad() != fa:
            _fail("#158: _finanzamt_ref_pfad liefert nicht das gesetzte Bible-Bild")
        p1 = bildmotiv._comic_strip_pfad(1, prompt, berater, tool="openai")
        if bildmotiv._comic_strip_pfad(1, prompt, berater, tool="openai") != p1:
            _fail("#158: unveraendertes Finanzamt-Bild aendert den Panel-2-Pfad")
        tf = os.path.getmtime(fa)
        os.utime(fa, (tf + 10, tf + 10))
        if bildmotiv._comic_strip_pfad(1, prompt, berater, tool="openai") == p1:
            _fail("#158: ersetztes Finanzamt-Bild (neue mtime) erneuert Panel 2 NICHT")
    finally:
        db.set_einstellung("finanzamt_bibel_bild", None)
    _ok("#158: ersetzte Berater-/Finanzamt-Referenz (neue mtime) -> neuer Panel-Pfad; unveraendert -> gleich")


def main():
    db.init_db()
    test_1_stilwahl()
    test_2_panels_refs_prompts()
    test_3_fallback_ohne_berater()
    test_4_render_slides_fuer_stelle()
    test_5_picker_und_whitelist()
    test_6_override_feld1()
    test_7_override_input_in_pickern()
    test_8_route_persistiert_override()
    test_9_ref_signatur_invalidiert_cache()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
