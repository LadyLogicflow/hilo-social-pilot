# -*- coding: utf-8 -*-
"""Tests fuer #161 - Figur-Steckbrief je Charakter (Reihenfolge Stil -> Figur -> Szene) +
Modell-Umschalter gpt-image-1 / gpt-image-2. KEINE echten Netz-/KI-Calls (alles gemockt).

Beweist:

  TEIL A - Figur-Steckbrief
    1. comic_strip Feld 2 (Aermelschoner): FINANZAMT_FIGUR steht im Panel-Prompt an der RICHTIGEN
       Position (nach HILO_COMIC_MASTER, vor der Szene/dem Panel-Delta).
    2. comic_strip Feld 1/3 (Berater): der Berater-Steckbrief (fields['bibel_text']) steht im
       Panel-Prompt, WENN gesetzt; NICHT, wenn leer. FINANZAMT_FIGUR NUR in Feld 2.
    3. normaler comic mit finanzamt_figur: FINANZAMT_FIGUR steht nach dem Stil (STIL_A_BLOCK) und
       vor der Szene; ohne finanzamt_figur NICHT.
    4. personalisierung.render_slides_fuer_stelle reicht bibel_text der Stelle in die comic_strip-
       Panels durch (Feld 1/3).

  TEIL B - Modell-Umschalter
    5. openai_image_model() nutzt die Einstellung 'bild_modell' (validiert); openai_payload +
       erzeuge_comic_bild_ref uebernehmen das Modell.
    6. Cache-Pfad unterscheidet gpt-image-1 vs gpt-image-2 (comic / comic_beratung / comic_strip).
    7. Fallback-Retry: schlaegt der Bild-Call mit gpt-image-2 fehl, wird EINMAL mit gpt-image-1
       nachgezogen (generations + edits).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/s161-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/manual_comic_figur_modell.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
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


def _capture_strip(fields, berater):
    """Ruft ensure_comic_strip_bilder mit gemockter Bild-KI auf und liefert die 3 Panel-Prompts."""
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


# --- TEIL A / 1 + 2) comic_strip: FINANZAMT_FIGUR (Feld 2) + bibel_text (Feld 1/3) ---------------
def test_1_strip_figur_steckbrief():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_161a.png"))
    db.set_einstellung("finanzamt_bibel_bild", None)
    db.set_einstellung("bild_modell", None)

    bibel = "BERATER-STECKBRIEF-161-EINDEUTIG: freundliche Person, kurze Haare, blaues Sakko."
    fields = {"bild_stil": "comic_strip", "ueberschrift": "STRIP-161-A", "bibel_text": bibel}
    caps = _capture_strip(fields, berater)
    if len(caps) != 3:
        _fail("nicht genau 3 Panel-Prompts: %d" % len(caps))

    master = bildmotiv.HILO_COMIC_MASTER
    figur = bildmotiv.FINANZAMT_FIGUR

    # Feld 2 (idx 1): FINANZAMT_FIGUR muss NACH dem Master und VOR der Szene/dem Delta stehen.
    p2 = caps[1]
    if figur not in p2:
        _fail("FINANZAMT_FIGUR fehlt im Feld-2-Prompt")
    if master not in p2:
        _fail("HILO_COMIC_MASTER fehlt im Feld-2-Prompt")
    # Delta von Feld 2 beginnt mit 'Szene (Feld 2 von 3)'. Der Steckbrief muss davor stehen.
    if not (p2.index(master) < p2.index(figur) < p2.index("Szene (Feld 2 von 3)")):
        _fail("FINANZAMT_FIGUR steht nicht zwischen Master und Szene (Feld 2)")

    # Feld 1/3: der Berater-Steckbrief (bibel_text) muss im Prompt stehen, NICHT FINANZAMT_FIGUR.
    for idx in (0, 2):
        p = caps[idx]
        if bibel not in p:
            _fail("Berater-Steckbrief (bibel_text) fehlt im Feld-%d-Prompt" % (idx + 1))
        if figur in p:
            _fail("FINANZAMT_FIGUR steht faelschlich im Berater-Feld %d" % (idx + 1))
        # Position: nach Master, vor dem Panel-Delta ('Szene (Feld ...)').
        if not (p.index(master) < p.index(bibel) < p.index("Szene (Feld")):
            _fail("Berater-Steckbrief steht nicht zwischen Master und Szene (Feld %d)" % (idx + 1))
    # Umgekehrt: FINANZAMT_FIGUR NUR in Feld 2.
    if figur in caps[0] or figur in caps[2]:
        _fail("FINANZAMT_FIGUR darf nur in Feld 2 stehen")
    _ok("comic_strip: FINANZAMT_FIGUR in Feld 2, Berater-Steckbrief in Feld 1/3 - je nach Master/vor Szene")


def test_2_strip_ohne_bibel_text():
    """Ohne bibel_text bleibt in Feld 1/3 KEIN Berater-Steckbrief (nur Master + Delta)."""
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_161b.png"))
    db.set_einstellung("finanzamt_bibel_bild", None)
    fields = {"bild_stil": "comic_strip", "ueberschrift": "STRIP-161-B"}  # KEIN bibel_text
    caps = _capture_strip(fields, berater)
    # Feld 2 hat weiterhin FINANZAMT_FIGUR (konstant), Feld 1/3 KEINEN zusaetzlichen Steckbrief:
    if bildmotiv.FINANZAMT_FIGUR not in caps[1]:
        _fail("FINANZAMT_FIGUR fehlt in Feld 2 (ohne bibel_text)")
    # Feld 1: direkt nach dem Master folgt das Panel-Delta ('Szene (Feld 1 von 3)') - kein Steckbrief
    # dazwischen. Wir pruefen, dass zwischen Master-Ende und 'Szene (Feld' nur der Trenner steht.
    p1 = caps[0]
    master_end = p1.index(bildmotiv.HILO_COMIC_MASTER) + len(bildmotiv.HILO_COMIC_MASTER)
    zwischen = p1[master_end:p1.index("Szene (Feld")]
    if zwischen.strip():
        _fail("ohne bibel_text steht faelschlich Text zwischen Master und Szene (Feld 1): %r" % zwischen)
    _ok("comic_strip ohne bibel_text: kein Berater-Steckbrief in Feld 1/3 (nur Master + Delta)")


# --- TEIL A / 3) normaler comic mit finanzamt_figur --------------------------------------------
def test_3_comic_finanzamt_figur():
    db.set_einstellung("bild_modell", None)
    figur = bildmotiv.FINANZAMT_FIGUR
    stil = bildmotiv.STIL_A_BLOCK

    mit = {"comic_brief": {"szene": "eine Alltagsszene", "finanzamt_figur": True}}
    p = bildmotiv._comic_prompt(mit)
    if figur not in p:
        _fail("FINANZAMT_FIGUR fehlt im comic-Prompt (finanzamt_figur=True)")
    # Position: nach dem Stil (STIL_A_BLOCK), vor der Szene ('Szene: ...').
    if not (p.index(stil) < p.index(figur) < p.index("\n\nSzene: ")):
        _fail("FINANZAMT_FIGUR steht nicht zwischen Stil und Szene im comic-Prompt")
    # FINANZAMT_BLOCK bleibt ergaenzend vorhanden.
    if bildmotiv.FINANZAMT_BLOCK not in p:
        _fail("FINANZAMT_BLOCK darf durch die Figur NICHT ersetzt werden")

    ohne = {"comic_brief": {"szene": "eine Alltagsszene", "finanzamt_figur": False}}
    p0 = bildmotiv._comic_prompt(ohne)
    if figur in p0:
        _fail("FINANZAMT_FIGUR steht faelschlich im comic-Prompt ohne finanzamt_figur")
    _ok("comic normal: FINANZAMT_FIGUR nach Stil/vor Szene bei finanzamt_figur; nicht ohne; FINANZAMT_BLOCK bleibt")


# --- TEIL A / 4) personalisierung reicht bibel_text in die Strip-Panels durch -------------------
def test_4_personalisierung_reicht_bibel_text():
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_161st.png"))
    bibel = "STELLE-BIBEL-161: ruhige Person mit Brille, graues Sakko."
    gesehen = {}

    def _fake_ensure(fields, berater_ref):
        gesehen["bibel_text"] = (fields or {}).get("bibel_text")
        return ["x", "y", "z"]

    orig = bildmotiv.ensure_comic_strip_bilder
    bildmotiv.ensure_comic_strip_bilder = _fake_ensure
    out_dir = os.path.join(bildmotiv.DATA_DIR, "bilder", "cs161")
    try:
        st = {"berater_comic": berater, "bibel_bild": None, "bibel_text": bibel, "portrait_pfad": None}
        f = {"bild_stil": "comic_strip", "ueberschrift": "STRIP-161-ST"}
        personalisierung.render_slides_fuer_stelle(f, st, out_dir, "slide")
    finally:
        bildmotiv.ensure_comic_strip_bilder = orig
    if gesehen.get("bibel_text") != bibel:
        _fail("bibel_text der Stelle kam NICHT in den comic_strip-Panels an: %r" % gesehen.get("bibel_text"))
    _ok("personalisierung: bibel_text der Stelle wird in die comic_strip-Panels (Feld 1/3) durchgereicht")


# --- TEIL B / 5) Modell aus Einstellung -------------------------------------------------------
def test_5_modell_aus_einstellung():
    os.environ.pop("HILO_OPENAI_IMAGE_MODEL", None)
    db.set_einstellung("bild_modell", None)
    if bildmotiv.openai_image_model() != "gpt-image-1":
        _fail("Default-Modell (ohne Einstellung) muss gpt-image-1 sein, war %r" % bildmotiv.openai_image_model())
    db.set_einstellung("bild_modell", "gpt-image-2")
    if bildmotiv.openai_image_model() != "gpt-image-2":
        _fail("Einstellung 'bild_modell'=gpt-image-2 wird nicht genutzt")
    if bildmotiv.openai_payload("P")["model"] != "gpt-image-2":
        _fail("openai_payload nutzt das Einstellungs-Modell nicht")
    # Unbekannter Wert -> Default (gpt-image-1)
    db.set_einstellung("bild_modell", "gpt-image-99")
    if bildmotiv.openai_image_model() != "gpt-image-1":
        _fail("unbekanntes Modell muss auf gpt-image-1 zurueckfallen")
    db.set_einstellung("bild_modell", None)
    _ok("openai_image_model/openai_payload nutzen 'bild_modell' (validiert; unbekannt -> Default gpt-image-1)")


# --- TEIL B / 6) Cache-Pfad unterscheidet die Modelle -----------------------------------------
def test_6_cache_key_pro_modell():
    db.set_einstellung("finanzamt_bibel_bild", None)
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_161cache.png"))
    fields = {"bild_stil": "comic", "comic_brief": {"szene": "Szene 161", "finanzamt_figur": False}}

    db.set_einstellung("bild_modell", "gpt-image-1")
    c1 = bildmotiv._comic_pfad(fields, tool="openai")
    b1 = bildmotiv._comic_beratung_pfad(fields, berater, tool="openai")
    s1 = bildmotiv._comic_strip_pfad(0, "PROMPT-161", berater, tool="openai")

    db.set_einstellung("bild_modell", "gpt-image-2")
    c2 = bildmotiv._comic_pfad(fields, tool="openai")
    b2 = bildmotiv._comic_beratung_pfad(fields, berater, tool="openai")
    s2 = bildmotiv._comic_strip_pfad(0, "PROMPT-161", berater, tool="openai")

    if c1 == c2:
        _fail("_comic_pfad unterscheidet gpt-image-1/gpt-image-2 NICHT: %r" % c1)
    if b1 == b2:
        _fail("_comic_beratung_pfad unterscheidet die Modelle NICHT")
    if s1 == s2:
        _fail("_comic_strip_pfad unterscheidet die Modelle NICHT")
    # gpt-image-1 = Default -> KEIN Modell-Praefix (bestehende Cache-Dateien bleiben gueltig).
    if "g2_" in os.path.basename(c1):
        _fail("gpt-image-1 darf keinen Modell-Praefix tragen (Rueckwaerts-Kompatibilitaet): %r" % c1)
    if "comic_g2_" not in os.path.basename(c2) and "g2_comic_" not in os.path.basename(c2):
        _fail("gpt-image-2 traegt keinen Modell-Praefix: %r" % os.path.basename(c2))
    # Ideogram bleibt modell-unabhaengig (kein g2_-Praefix beim Modellwechsel).
    si = bildmotiv._comic_strip_pfad(0, "PROMPT-161", berater, tool="ideogram")
    if "g2_" in os.path.basename(si):
        _fail("Ideogram-Comic-Pfad darf beim Modellwechsel keinen g2_-Praefix bekommen: %r" % si)
    db.set_einstellung("bild_modell", None)
    _ok("Cache-Pfad: gpt-image-1 (kein Praefix) vs gpt-image-2 (g2_) getrennt; Ideogram modell-unabhaengig")


# --- TEIL B / 7) Fallback-Retry bei Modell-Fehler ---------------------------------------------
def test_7_fallback_retry():
    import requests

    # a) generations-Weg (erzeuge_bild_openai): gpt-image-2 wirft, gpt-image-1 gelingt.
    db.set_einstellung("bild_modell", "gpt-image-2")
    orig_secret = bildmotiv.get_secret
    bildmotiv.get_secret = lambda name, required=False: "sk-TESTKEY-should-not-leak"
    versuche = {"modelle": []}

    class _Resp:
        def __init__(self, ok):
            self._ok = ok

        def raise_for_status(self):
            if not self._ok:
                raise RuntimeError("model not available")

        def json(self):
            import base64
            return {"data": [{"b64_json": base64.b64encode(b"OKPNG").decode()}]}

    def _fake_post(url, headers=None, json=None, data=None, files=None, timeout=None, **kw):
        modell = (json or {}).get("model") if json else (data or {}).get("model")
        versuche["modelle"].append(modell)
        return _Resp(modell == "gpt-image-1")   # nur gpt-image-1 gelingt

    orig_post = requests.post
    requests.post = _fake_post
    try:
        daten = bildmotiv.erzeuge_bild_openai("PROMPT")
    finally:
        requests.post = orig_post
        bildmotiv.get_secret = orig_secret
    if daten != b"OKPNG":
        _fail("Fallback-Retry (generations) liefert kein Bild: %r" % daten)
    if versuche["modelle"] != ["gpt-image-2", "gpt-image-1"]:
        _fail("Fallback-Retry-Reihenfolge (generations) falsch: %r" % versuche["modelle"])

    # b) edits-Weg (erzeuge_comic_bild_ref): gpt-image-2 wirft, gpt-image-1 gelingt.
    # #162: HIER wird der reine MODELL-Fallback (#161) geprueft, deshalb input_fidelity=low pinnen -
    # so faellt der zusaetzliche 'ohne input_fidelity'-Versuch (#162) weg und die Modell-Reihenfolge
    # bleibt gpt-image-2 -> gpt-image-1. Der Fidelity-Fallback (mit->ohne) ist in
    # test_comic_input_fidelity.py separat abgedeckt.
    ref = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_161retry.png"))
    bildmotiv.get_secret = lambda name, required=False: "sk-TESTKEY-should-not-leak"
    versuche2 = {"modelle": []}

    def _fake_post2(url, headers=None, json=None, data=None, files=None, timeout=None, **kw):
        modell = (data or {}).get("model")
        versuche2["modelle"].append(modell)
        return _Resp(modell == "gpt-image-1")

    requests.post = _fake_post2
    os.environ["HILO_INPUT_FIDELITY"] = "low"
    try:
        daten2 = bildmotiv.erzeuge_comic_bild_ref("PROMPT", [ref])
    finally:
        requests.post = orig_post
        bildmotiv.get_secret = orig_secret
        os.environ.pop("HILO_INPUT_FIDELITY", None)
    if daten2 != b"OKPNG":
        _fail("Fallback-Retry (edits) liefert kein Bild: %r" % daten2)
    if versuche2["modelle"] != ["gpt-image-2", "gpt-image-1"]:
        _fail("Fallback-Retry-Reihenfolge (edits) falsch: %r" % versuche2["modelle"])
    db.set_einstellung("bild_modell", None)
    _ok("Fallback-Retry: gpt-image-2 fehlgeschlagen -> EINMAL mit gpt-image-1 (generations + edits)")


# --- TEIL B / 8) UI: Dropdown + POST-Handler --------------------------------------------------
def test_8_ui_dropdown_und_save():
    import web
    if 'name=bild_modell' not in web.VERWALTUNG:
        _fail("Bild-Modell-Dropdown (name=bild_modell) fehlt im Verwaltungs-Template")
    if 'value="gpt-image-1"' not in web.VERWALTUNG or 'value="gpt-image-2"' not in web.VERWALTUNG:
        _fail("Bild-Modell-Dropdown enthaelt nicht beide Optionen")
    if "bildmodell_save" not in web.VERWALTUNG:
        _fail("Bild-Modell-Formular (bildmodell_save) fehlt im Template")

    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"; sess["rolle"] = "admin"
    # gueltiges Modell speichern
    c.post("/verwaltung", data={"formular": "bildmodell_save", "bild_modell": "gpt-image-2"})
    if db.get_einstellung("bild_modell") != "gpt-image-2":
        _fail("POST bildmodell_save persistiert gpt-image-2 nicht")
    # unbekanntes Modell -> Default gpt-image-1
    c.post("/verwaltung", data={"formular": "bildmodell_save", "bild_modell": "gpt-image-99"})
    if db.get_einstellung("bild_modell") != "gpt-image-1":
        _fail("POST bildmodell_save: unbekanntes Modell faellt nicht auf gpt-image-1 zurueck")
    db.set_einstellung("bild_modell", None)
    _ok("UI: Bild-Modell-Dropdown vorhanden; POST speichert (validiert, unbekannt -> gpt-image-1)")


def main():
    db.init_db()
    test_1_strip_figur_steckbrief()
    test_2_strip_ohne_bibel_text()
    test_3_comic_finanzamt_figur()
    test_4_personalisierung_reicht_bibel_text()
    test_5_modell_aus_einstellung()
    test_6_cache_key_pro_modell()
    test_7_fallback_retry()
    test_8_ui_dropdown_und_save()
    print("\nALLE TESTS BESTANDEN (#161 - Figur-Steckbrief + Modell-Umschalter, %d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
