# -*- coding: utf-8 -*-
"""Tests fuer den Bild-Stil "Comic Beratung" (comic_beratung) - personalisiert pro Beratungsstelle.

Beweist die VERDRAHTUNG (KEINE echten externen KI-/Bild-APIs - alles gemockt):

  1. stilwahl: STILE enthaelt 'comic_beratung'; aktiver_stil({'bild_stil':'comic_beratung'})
     erkennt ihn; er ist per Default aktiv (im Zufalls-Topf).
  2. Picker: /entwuerfe-, /pool-, /einplanung-Template enthalten die Option "Comic Beratung";
     die /bild-generieren-Whitelist akzeptiert comic_beratung (und lehnt Unbekanntes ab).
  3. ensure_comic_beratung_bild: erzeuge_comic_bild_ref gepatcht -> Prompt enthaelt STIL_A_BLOCK
     UND BERATUNG_BLOCK; refs == [berater_comic, FINANZAMT_REF_PATH].
  4. Per-Stelle: zwei Stellen mit verschiedenem berater_comic -> verschiedene refs UND
     verschiedene Cache-Pfade (jede Stelle ihr eigenes Bild).
  5. Fallback: ohne berater_comic faellt ensure_comic_beratung_bild auf den normalen Comic
     (ensure_comic_bild) zurueck; die stellenlose /bild-generieren-Vorschau ohne jede Stelle mit
     Berater-Comic zeigt den Hinweis-Flash und erzeugt KEIN Bild.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/comic-beratung-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_comic_beratung.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import stilwahl

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


def _fields(szene="Kindergeld beantragen"):
    return {"bild_stil": "comic_beratung", "ueberschrift": "Test",
            "comic_brief": {"stimmung": "positiv", "szene": szene, "hook": "",
                            "finanzamt_figur": True}}


# --- 1) stilwahl kennt comic_beratung --------------------------------------------------------
def test_1_stilwahl():
    if "comic_beratung" not in stilwahl.STILE:
        _fail("stilwahl.STILE enthaelt 'comic_beratung' nicht: %r" % (stilwahl.STILE,))
    if stilwahl._FLAG_KEY.get("comic_beratung") != "bild_stil_comic_beratung":
        _fail("_FLAG_KEY['comic_beratung'] falsch: %r" % stilwahl._FLAG_KEY.get("comic_beratung"))
    if stilwahl.aktiver_stil({"bild_stil": "comic_beratung"}) != "comic_beratung":
        _fail("aktiver_stil erkennt comic_beratung nicht")
    # Default aktiv (kein Flag gesetzt -> im Topf)
    for k in ("bild_stil_standard", "bild_stil_ki_tafel", "bild_stil_kreativ", "bild_stil_comic",
              "bild_stil_comic_beratung"):
        db.set_einstellung(k, None)
    if "comic_beratung" not in stilwahl.aktive_stile():
        _fail("comic_beratung ist per Default nicht aktiv (nicht im Topf)")
    _ok("stilwahl: STILE/_FLAG_KEY/aktiver_stil kennen comic_beratung; Default aktiv")


# --- 2) Picker + Whitelist -------------------------------------------------------------------
def test_2_picker_und_whitelist():
    import web
    for name, tpl in (("ENTWUERFE", web.ENTWUERFE), ("EINPLANUNG", web.EINPLANUNG),
                      ("POOL", web.POOL)):
        if 'value="comic_beratung"' not in tpl or "Comic Beratung" not in tpl:
            _fail("Picker %s enthaelt die Option 'Comic Beratung' nicht" % name)
    _ok("Picker /entwuerfe, /pool, /einplanung enthalten die Option 'Comic Beratung'")

    # Whitelist der Route /bild-generieren: comic_beratung wird akzeptiert (kommt an der Stil-Pruefung
    # vorbei), Unbekanntes wird mit "Bitte einen Stil wählen." abgewiesen.
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(text, status) VALUES (?, 'entwurf')",
                           (json.dumps({"ueberschrift": "X"}),))
        conn.commit()
        eid = cur.lastrowid

    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = "admin"

    # a) Unbekannter Stil -> "Bitte einen Stil wählen."
    c.post("/bild-generieren/%d" % eid, data={"bild_stil": "quatsch", "zurueck": "entwuerfe"})
    with c.session_transaction() as sess:
        flashes = [m for _, m in sess.get("_flashes", [])]
    if not any("Bitte einen Stil" in m for m in flashes):
        _fail("Unbekannter Stil wurde nicht mit 'Bitte einen Stil wählen.' abgewiesen: %r" % flashes)
    # Flash-Puffer leeren (ohne Template-Render bleiben Flashes sonst in der Session liegen).
    with c.session_transaction() as sess:
        sess.pop("_flashes", None)

    # b) comic_beratung akzeptiert (keine aktive Stelle mit Berater-Comic -> Hinweis-Flash, NICHT
    #    die Stil-Ablehnung). Das beweist zugleich Whitelist UND die Vorschau-Ohne-Stelle-Regel.
    c.post("/bild-generieren/%d" % eid, data={"bild_stil": "comic_beratung", "zurueck": "entwuerfe"})
    with c.session_transaction() as sess:
        flashes = [m for _, m in sess.get("_flashes", [])]
    if any("Bitte einen Stil" in m for m in flashes):
        _fail("comic_beratung wurde faelschlich als ungueltiger Stil abgewiesen")
    if not any("Comic-Berater in der Beratungsstellen-Verwaltung" in m for m in flashes):
        _fail("comic_beratung ohne Berater-Comic: erwarteter Hinweis-Flash fehlt: %r" % flashes)
    # Kein Bild erzeugt (bild_pfad bleibt leer)
    with db.get_conn() as conn:
        row = conn.execute("SELECT bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if row["bild_pfad"]:
        _fail("comic_beratung-Vorschau ohne Berater-Comic hat faelschlich ein Bild erzeugt")
    _ok("Whitelist akzeptiert comic_beratung; Vorschau ohne Berater-Comic -> Hinweis + kein Bild")


# --- 3) ensure_comic_beratung_bild: Prompt + refs --------------------------------------------
def test_3_prompt_und_refs():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_1.png"))
    captured = {"prompt": None, "refs": None, "gen_called": False}

    def _fake_ref(prompt, refs):
        captured["prompt"] = prompt
        captured["refs"] = list(refs)
        return b"COMICPNG"

    def _fake_gen(prompt, tool=None):
        captured["gen_called"] = True
        return b"GENPNG"

    orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    try:
        path = bildmotiv.ensure_comic_beratung_bild(_fields(), berater)
    finally:
        bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen

    if bildmotiv.HILO_COMIC_MASTER not in (captured["prompt"] or ""):
        _fail("Prompt enthaelt HILO_COMIC_MASTER nicht")
    if bildmotiv.BERATUNG_BLOCK not in (captured["prompt"] or ""):
        _fail("Prompt enthaelt BERATUNG_BLOCK nicht")
    if captured["refs"] != [berater, bildmotiv.FINANZAMT_REF_PATH]:
        _fail("refs != [berater_comic, FINANZAMT_REF_PATH]: %r" % captured["refs"])
    if captured["gen_called"]:
        _fail("erzeuge_bild (generations) wurde faelschlich aufgerufen (Referenz lieferte Bytes)")
    if not path or not os.path.exists(path):
        _fail("ensure_comic_beratung_bild lieferte keinen gueltigen Cache-Pfad")
    _ok("ensure_comic_beratung_bild: Prompt=STIL_A_BLOCK+BERATUNG_BLOCK, refs=[berater,finanzamt]")


# --- 4) Per-Stelle: verschiedene Berater -> verschiedene refs + Cache-Pfade -------------------
def test_4_pro_stelle():
    b1 = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_10.png"))
    b2 = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_20.png"))
    fields = _fields("gleiche Szene fuer beide")

    seen = []

    def _fake_ref(prompt, refs):
        seen.append(list(refs))
        return b"COMICPNG"

    orig_ref = bildmotiv.erzeuge_comic_bild_ref
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    try:
        p1 = bildmotiv.ensure_comic_beratung_bild(fields, b1)
        p2 = bildmotiv.ensure_comic_beratung_bild(fields, b2)
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig_ref

    if seen[0] == seen[1]:
        _fail("Zwei verschiedene Berater lieferten identische refs: %r" % seen)
    if seen[0][0] != b1 or seen[1][0] != b2:
        _fail("refs[0] ist nicht der jeweilige Berater-Comic: %r" % seen)
    if bildmotiv._comic_beratung_pfad(fields, b1) == bildmotiv._comic_beratung_pfad(fields, b2):
        _fail("Cache-Pfad kollidiert fuer verschiedene Berater (kein Basename im Hash)")
    if p1 == p2:
        _fail("ensure_comic_beratung_bild lieferte fuer verschiedene Berater denselben Pfad")

    # Und der per-Stelle-Render (personalisierung) setzt den Berater-Comic DER STELLE ein.
    import personalisierung
    st1 = {"berater_comic": b1, "portrait_pfad": None}
    f = personalisierung._setze_berater_comic({"bild_stil": "comic_beratung"}, st1)
    if f.get("berater_comic") != b1:
        _fail("personalisierung._setze_berater_comic hat berater_comic der Stelle nicht gesetzt")
    _ok("Per-Stelle: verschiedene Berater -> verschiedene refs + Cache-Pfade; _setze_berater_comic wirkt")


# --- 5) Fallback ohne Berater-Comic -> normaler Comic ----------------------------------------
def test_5_fallback_normaler_comic():
    captured = {"comic_called": False, "ref_called": False}

    def _fake_comic(fields):
        captured["comic_called"] = True
        return "/tmp/normaler_comic.png"

    def _fake_ref(prompt, refs):
        captured["ref_called"] = True
        return b"X"

    orig_comic, orig_ref = bildmotiv.ensure_comic_bild, bildmotiv.erzeuge_comic_bild_ref
    bildmotiv.ensure_comic_bild = _fake_comic
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    try:
        # a) leerer Pfad
        r1 = bildmotiv.ensure_comic_beratung_bild(_fields(), "")
        # b) nicht existierender Pfad
        r2 = bildmotiv.ensure_comic_beratung_bild(_fields(), "/does/not/exist.png")
    finally:
        bildmotiv.ensure_comic_bild = orig_comic
        bildmotiv.erzeuge_comic_bild_ref = orig_ref

    if not captured["comic_called"]:
        _fail("Fallback: ensure_comic_bild (normaler Comic) wurde NICHT aufgerufen")
    if captured["ref_called"]:
        _fail("Fallback: erzeuge_comic_bild_ref wurde faelschlich aufgerufen (kein Berater)")
    if r1 != "/tmp/normaler_comic.png" or r2 != "/tmp/normaler_comic.png":
        _fail("Fallback lieferte nicht das Ergebnis von ensure_comic_bild")
    _ok("Fallback ohne Berater-Comic -> normaler Comic (ensure_comic_bild), kein Referenz-Call")


# --- 6) Character-Bible (#151): bibel_bild als erste Ref, bibel_text im Prompt, Fallback ------
def test_6_character_bible():
    import personalisierung

    # a) personalisierung._setze_berater_comic: bibel_bild hat Vorrang vor berater_comic; bibel_text
    #    wird durchgereicht.
    bild = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "bibeln", "stelle_77.png"))
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_77.png"))
    stelle = {"berater_comic": berater, "bibel_bild": bild,
              "bibel_text": "Freundliche Beraterin, kurze braune Haare, grüner Blazer",
              "portrait_pfad": None}
    f = personalisierung._setze_berater_comic({"bild_stil": "comic_beratung"}, stelle)
    if f.get("berater_comic") != bild:
        _fail("bibel_bild hat keinen Vorrang vor berater_comic: %r" % f.get("berater_comic"))
    if f.get("bibel_text") != stelle["bibel_text"]:
        _fail("bibel_text wurde nicht durchgereicht: %r" % f.get("bibel_text"))

    # b) ohne bibel_bild -> Fallback auf berater_comic (unveraendertes Verhalten).
    stelle_ohne = {"berater_comic": berater, "bibel_bild": None, "bibel_text": None,
                   "portrait_pfad": None}
    f2 = personalisierung._setze_berater_comic({"bild_stil": "comic_beratung"}, stelle_ohne)
    if f2.get("berater_comic") != berater:
        _fail("Fallback auf berater_comic ohne bibel_bild fehlgeschlagen: %r" % f2.get("berater_comic"))
    if "bibel_text" in f2:
        _fail("bibel_text wurde ohne Wert faelschlich gesetzt: %r" % f2.get("bibel_text"))

    # c) bibel_text landet im comic_beratung-Prompt; ohne bibel_text bleibt der Prompt unveraendert.
    fields_mit = _fields()
    fields_mit["bibel_text"] = "TESTBESCHREIBUNG-EINDEUTIG-XYZ"
    captured = {"prompt": None}

    def _fake_ref(prompt, refs):
        captured["prompt"] = prompt
        return b"COMICPNG"

    orig_ref = bildmotiv.erzeuge_comic_bild_ref
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    try:
        bildmotiv.ensure_comic_beratung_bild(fields_mit, bild)
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig_ref
    if "TESTBESCHREIBUNG-EINDEUTIG-XYZ" not in (captured["prompt"] or ""):
        _fail("bibel_text landet nicht im comic_beratung-Prompt")

    # Ohne bibel_text: Prompt == HILO_COMIC_MASTER + BERATUNG_BLOCK (Fallback, unveraendert - solange
    # keine globale Finanzamt-Bible-Beschreibung gesetzt ist; Default nach db.init_db).
    basis = bildmotiv._comic_beratung_prompt(_fields())
    if basis != bildmotiv.HILO_COMIC_MASTER + "\n\n" + bildmotiv.BERATUNG_BLOCK:
        _fail("Ohne bibel_text/finanzamt_bibel_text weicht der Prompt vom bisherigen Verhalten ab")
    _ok("Character-Bible: bibel_bild-Vorrang, bibel_text im Prompt, Fallback unveraendert")


# --- 7) Finanzamt-Bible (#151): eigenes Referenzbild ersetzt die Default-Finanzamt-Referenz ----
def test_7_finanzamt_bible():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_88.png"))
    fa_bild = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "bibeln", "finanzamt.png"))

    # Default (keine Finanzamt-Bible): 2. Ref ist FINANZAMT_REF_PATH.
    db.set_einstellung("finanzamt_bibel_bild", None)
    db.set_einstellung("finanzamt_bibel_text", None)
    refs_default = bildmotiv._comic_beratung_refs(berater)
    if refs_default != [berater, bildmotiv.FINANZAMT_REF_PATH]:
        _fail("Default-Finanzamt-Referenz falsch: %r" % refs_default)

    # Mit Finanzamt-Bible: 2. Ref ist das hinterlegte Bild; finanzamt_bibel_text landet im Prompt.
    db.set_einstellung("finanzamt_bibel_bild", fa_bild)
    db.set_einstellung("finanzamt_bibel_text", "FINANZAMT-BESCHREIBUNG-EINDEUTIG-QRS")
    try:
        refs_bibel = bildmotiv._comic_beratung_refs(berater)
        if refs_bibel != [berater, fa_bild]:
            _fail("Finanzamt-Bible-Bild ersetzt die Default-Referenz nicht: %r" % refs_bibel)
        prompt = bildmotiv._comic_beratung_prompt(_fields())
        if "FINANZAMT-BESCHREIBUNG-EINDEUTIG-QRS" not in prompt:
            _fail("finanzamt_bibel_text landet nicht im Prompt")
    finally:
        db.set_einstellung("finanzamt_bibel_bild", None)
        db.set_einstellung("finanzamt_bibel_text", None)
    _ok("Finanzamt-Bible: eigenes Referenzbild + Beschreibung greifen; Default unveraendert")


def main():
    db.init_db()
    test_1_stilwahl()
    test_2_picker_und_whitelist()
    test_3_prompt_und_refs()
    test_4_pro_stelle()
    test_5_fallback_normaler_comic()
    test_6_character_bible()
    test_7_finanzamt_bible()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
