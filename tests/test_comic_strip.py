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
    /workspace/.hvenv/bin/python tests/test_comic_strip.py
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


def main():
    db.init_db()
    test_1_stilwahl()
    test_2_panels_refs_prompts()
    test_3_fallback_ohne_berater()
    test_4_render_slides_fuer_stelle()
    test_5_picker_und_whitelist()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
