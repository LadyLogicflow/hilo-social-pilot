# -*- coding: utf-8 -*-
"""Tests fuer Issue #135 - Bild-Feinschliff: Normalfarben, frohe Stimmung,
Arial-Schrift, CTA in HILO-Gruen, Tafel-Text in HILO-Blau.

Deckt ab:
  A) bildmotiv Foto-Prompt (ki_tafel UND szene):
     - Normalfarben statt warm: 'natuerliche'/'ausgewogene' Farben + 'neutralem Tageslicht',
       und NICHT mehr 'warm'/'golden'/'amber'.
     - Stimmung froh & geloest: 'froh'/'geloest'/'positiv' + keine traurigen/depressiven Gesichter.
     - ki_tafel zusaetzlich: Tafel-Text in HILO-Dunkelblau, serifenlos/Arial-aehnlich, helles Schild.
     - Payload unveraendert (background='opaque', size '1024x1024'); Cache-Praefixe unveraendert.
  B) bildgen:
     - Font-Lookup _BOLD/_REG enthalten Arial-Pfade VOR Liberation.
     - CTA-Pillenfarbe ACCENT = HILO-Gruen (96,163,60), nicht mehr Gold/Orange (243,146,0).
     - Render mit opakem Dummy-Foto in beiden Modi (standard + ki_tafel): 1080x1080, kein Crash.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_bild_feinschliff.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import bildgen as b


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


SIGN = "Frist verpasst? Wir helfen sofort!"
SCENE = "ruhige Buero-Szene mit einer beratenen Familie"

# Farb-/Stimmungs-Begriffe, die in BEIDEN Prompts (szene + ki_tafel) vorkommen muessen.
_NORMAL_COLORS = ("natuerliche", "ausgewogene", "neutralem Tageslicht")
_NO_WARM = ("warm", "golden", "amber")          # duerfen NUR noch als Negation auftauchen
_MOOD_POSITIVE = ("froh", "geloest", "positiv")
_MOOD_NEGATIVE_PHRASE = "KEINE traurigen"        # Verneinung trauriger/depressiver Gesichter


def _assert_normalfarben(prompt, label):
    low = prompt.lower()
    for w in _NORMAL_COLORS:
        if w.lower() not in low:
            _fail("%s: Normalfarben-Begriff %r fehlt" % (label, w))
    # 'warm'/'golden'/'amber' duerfen nicht mehr als POSITIVE Farbangabe vorkommen.
    # Wir erlauben sie nur im Verneinungs-Satz 'NICHT uebertrieben warm, golden oder amber'.
    if "harmonische warme farben" in low or "warme, weiches" in low or "warmes, weiches" in low:
        _fail("%s: alte warme Farb-/Lichtangabe noch vorhanden" % label)
    if "NICHT uebertrieben warm" not in prompt:
        _fail("%s: Verneinung 'NICHT uebertrieben warm, golden oder amber' fehlt" % label)


def _assert_stimmung(prompt, label):
    for w in _MOOD_POSITIVE:
        if w not in prompt:
            _fail("%s: positiver Stimmungs-Begriff %r fehlt" % (label, w))
    if _MOOD_NEGATIVE_PHRASE not in prompt:
        _fail("%s: Verneinung trauriger Gesichter ('KEINE traurigen') fehlt" % label)
    if "depressiv" not in prompt:
        _fail("%s: 'depressiv'-Vermeidung fehlt" % label)


def test_szene_prompt_feinschliff():
    sp = bildmotiv._prompt(SCENE)
    _assert_normalfarben(sp, "Szene-Prompt")
    _assert_stimmung(sp, "Szene-Prompt")
    # Komposition/Negativraum-Anweisung bleibt erhalten (Rueckwaertskompatibilitaet)
    if "KEIN Text, keine Schrift" not in sp:
        _fail("Szene-Prompt: 'KEIN Text'-Anweisung verloren gegangen")
    print("  A1) Szene-Prompt: Normalfarben + frohe Stimmung + kein Text OK")


def test_tafel_prompt_feinschliff():
    tp = bildmotiv._tafel_prompt(SCENE, SIGN)
    _assert_normalfarben(tp, "Tafel-Prompt")
    _assert_stimmung(tp, "Tafel-Prompt")
    # ki_tafel-spezifisch: HILO-Dunkelblau + serifenlos/Arial-aehnlich + helles Schild
    if "HILO-Dunkelblau" not in tp:
        _fail("Tafel-Prompt: 'HILO-Dunkelblau' (Textfarbe) fehlt")
    if "SERIFENLOSEN" not in tp or "Arial-aehnlich" not in tp:
        _fail("Tafel-Prompt: serifenlose/Arial-aehnliche Schriftangabe fehlt")
    if "HELLES" not in tp or "helles Schild" not in tp:
        _fail("Tafel-Prompt: 'helles Schild' fehlt")
    # sign_text weiter in Anfuehrungszeichen + EINZIGE-Schrift-Anweisung erhalten
    if ("'%s'" % SIGN) not in tp:
        _fail("Tafel-Prompt: sign_text nicht mehr in Anfuehrungszeichen")
    if "EINZIGE" not in tp:
        _fail("Tafel-Prompt: 'EINZIGE Schrift'-Anweisung verloren gegangen")
    # echte deutsche Umlaute
    for ch in ("ä", "ö", "ü", "ß"):
        if ch not in tp:
            _fail("Tafel-Prompt: echter Umlaut %r fehlt" % ch)
    print("  A2) Tafel-Prompt: Normalfarben + frohe Stimmung + HILO-Blau/serifenlos/helles Schild OK")


def test_payload_unchanged():
    pl = bildmotiv.tafel_payload(SCENE, SIGN)
    if pl.get("background") != "opaque":
        _fail("Payload background != 'opaque'")
    if pl.get("size") != "1024x1024":
        _fail("Payload size != '1024x1024'")
    print("  A3) Payload unveraendert: background='opaque', size='1024x1024' OK")


def test_cache_praefixe_unchanged():
    k = bildmotiv.tafel_cache_key(SCENE, SIGN)
    if not k.startswith("tafel:"):
        _fail("Tafel-Cache-Praefix veraendert (erwartet 'tafel:')")
    sp = bildmotiv._szene_pfad(SCENE)
    if sp is None or not os.path.basename(sp).endswith(".png"):
        _fail("Szene-Pfad-Berechnung veraendert")
    print("  A4) Cache-Praefixe unveraendert ('tafel:' / 'szene:') OK")


# ---------------------------------------------------------------------------
# B) bildgen: Fonts + CTA-Farbe + Render
# ---------------------------------------------------------------------------
def _arial_before_liberation(paths, label):
    arial_idx = next((i for i, p in enumerate(paths) if "Arial" in p or "arial" in p), None)
    lib_idx = next((i for i, p in enumerate(paths) if "liberation" in p.lower()), None)
    if arial_idx is None:
        _fail("%s: kein Arial-Pfad in der Font-Liste" % label)
    if lib_idx is None:
        _fail("%s: Liberation-Fallback aus der Font-Liste entfernt" % label)
    if arial_idx >= lib_idx:
        _fail("%s: Arial-Pfad steht NICHT vor Liberation" % label)


def test_font_lookup_arial_first():
    _arial_before_liberation(b._BOLD, "_BOLD")
    _arial_before_liberation(b._REG, "_REG")
    print("  B1) Font-Lookup _BOLD/_REG: Arial zuerst, Liberation als Fallback erhalten OK")


def test_cta_farbe_gruen():
    if b.ACCENT == (243, 146, 0):
        _fail("CTA-Pillenfarbe ist noch Gold/Orange (243,146,0)")
    if b.ACCENT != (96, 163, 60):
        _fail("CTA-Pillenfarbe ist nicht HILO-Gruen (96,163,60), war: %r" % (b.ACCENT,))
    print("  B2) CTA-Pillenfarbe ACCENT = HILO-Gruen (96,163,60) OK")


FIELDS = {
    "ueberschrift": SIGN,
    "subline": "Wir kuemmern uns - Sie sind entlastet",
    "bullets": ["Schnelle Hilfe", "Persoenliche Beratung", "Loesung statt Sorge"],
    "cta": "Jetzt Beratungsstelle finden",
    "hero": "24h",
}


def _dummy_photo(path):
    Image.new("RGB", (1024, 1024), (140, 150, 160)).save(path)
    return path


def test_render_beide_modi():
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "dummy_135.png"))
    for stil in ("standard", "ki_tafel"):
        db.set_einstellung("bild_stil", stil)
        out = os.path.join(data, "feinschliff_%s.png" % stil)
        p = b.render(FIELDS, photo, "Wir sind HILO", out, portrait=None)
        if not (p and os.path.exists(p)):
            _fail("render() (%s) hat kein Bild erzeugt" % stil)
        if Image.open(p).size != (1080, 1080):
            _fail("%s-Bild hat falsche Groesse" % stil)
    db.set_einstellung("bild_stil", "standard")
    print("  B3) Render mit Dummy-Foto in beiden Modi (standard + ki_tafel): 1080x1080 OK")


if __name__ == "__main__":
    db.init_db()
    print("== A) bildmotiv Foto-Prompt-Feinschliff (szene + ki_tafel) ==")
    test_szene_prompt_feinschliff()
    test_tafel_prompt_feinschliff()
    test_payload_unchanged()
    test_cache_praefixe_unchanged()
    print("== B) bildgen Fonts + CTA-Farbe + Render ==")
    test_font_lookup_arial_first()
    test_cta_farbe_gruen()
    test_render_beide_modi()
    print("BESTANDEN: Bild-Feinschliff (#135) - alle Pruefungen gruen.")
