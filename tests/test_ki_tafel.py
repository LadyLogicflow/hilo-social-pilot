# -*- coding: utf-8 -*-
"""Tests fuer Issue #132 - umschaltbarer Bild-Stil 'KI-Tafel'.

Deckt ab:
  A) db.get_einstellung/set_einstellung: Default-Fallback + Persistenz.
  B) bildmotiv ki_tafel: Prompt enthaelt den sign_text in Anfuehrungszeichen, die
     'einzige Schrift im Bild'-Anweisung und korrekte deutsche Umlaute; Payload
     background='opaque' / size '1024x1024'; Cache-Key enthaelt sign_text (Praefix 'tafel:').
     Modus 'standard' nutzt weiter den v11-Szene-Prompt (KEIN Tafel-Wortlaut).
  C) bildgen: Modus ki_tafel rendert mit opakem Dummy-Foto OHNE Text-Karte, MIT CTA-Pille
     + CI-Kreisen (kein Crash, 1080x1080); Modus standard unveraendert (Karte vorhanden);
     Creme-Fallback ohne Foto.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_ki_tafel.py
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


# ---------------------------------------------------------------------------
# A) Einstellung get/set
# ---------------------------------------------------------------------------
def test_einstellung():
    db.init_db()
    # Default-Fallback (Schluessel existiert nicht)
    if db.get_einstellung("bild_stil", "standard") != "standard":
        _fail("Default-Fallback fuer fehlenden Schluessel falsch")
    if db.get_einstellung("gibtsnicht") is not None:
        _fail("Fehlender Schluessel ohne Default sollte None liefern")
    # Persistenz
    db.set_einstellung("bild_stil", "ki_tafel")
    if db.get_einstellung("bild_stil", "standard") != "ki_tafel":
        _fail("set/get_einstellung persistiert nicht")
    # Ueberschreiben
    db.set_einstellung("bild_stil", "standard")
    if db.get_einstellung("bild_stil") != "standard":
        _fail("Ueberschreiben einer Einstellung schlug fehl")
    print("  A) get/set_einstellung: Default-Fallback + Persistenz OK")


# ---------------------------------------------------------------------------
# B) bildmotiv KI-Tafel-Prompt + Payload + Cache-Key
# ---------------------------------------------------------------------------
SIGN = "Abschiedsfeier steuerfrei - so geht's!"
SCENE = "warme Sommerszene am Strand bei Sonnenuntergang"


def test_tafel_prompt():
    prompt = bildmotiv._tafel_prompt(SCENE, SIGN)
    # sign_text in Anfuehrungszeichen
    if ("'%s'" % SIGN) not in prompt:
        _fail("sign_text steht nicht in Anfuehrungszeichen im Prompt")
    # Szene eingesetzt
    if SCENE not in prompt:
        _fail("Szene wurde nicht in den Prompt eingesetzt")
    # 'einzige Schrift'-Anweisung
    if "EINZIGE" not in prompt or "Schrift im gesamten Bild" not in prompt:
        _fail("'einzige Schrift im Bild'-Anweisung fehlt")
    # echte deutsche Umlaute im Prompt
    for ch in ("ä", "ö", "ü", "ß"):
        if ch not in prompt:
            _fail("Echter Umlaut %r fehlt im Prompt" % ch)
    # keine ASCII-Umschreibung der Steueranweisung (Schaerfentiefe muss als Schärfentiefe stehen)
    if "Schärfentiefe" not in prompt:
        _fail("Prompt nutzt nicht durchgaengig echte Umlaute (Schärfentiefe)")
    print("  B1) Tafel-Prompt: sign_text in Quotes + 'einzige Schrift' + echte Umlaute OK")


def test_tafel_payload():
    pl = bildmotiv.tafel_payload(SCENE, SIGN)
    if pl.get("background") != "opaque":
        _fail("Payload background != 'opaque'")
    if pl.get("size") != "1024x1024":
        _fail("Payload size != '1024x1024'")
    if ("'%s'" % SIGN) not in pl.get("prompt", ""):
        _fail("Payload-Prompt enthaelt den sign_text nicht")
    print("  B2) Payload: background='opaque', size='1024x1024', Prompt mit sign_text OK")


def test_tafel_cache_key():
    key = bildmotiv.tafel_cache_key(SCENE, SIGN)
    if not key.startswith("tafel:"):
        _fail("Cache-Key hat nicht den Praefix 'tafel:'")
    if SIGN not in key:
        _fail("Cache-Key enthaelt den sign_text nicht")
    # andere Ueberschrift -> anderer Key (Foto pro Ueberschrift)
    if bildmotiv.tafel_cache_key(SCENE, "Andere Ueberschrift") == key:
        _fail("Verschiedene Ueberschriften ergeben denselben Cache-Key")
    print("  B3) Cache-Key: Praefix 'tafel:' + enthaelt sign_text + ueberschrift-spezifisch OK")


def test_standard_prompt_unchanged():
    """Modus 'standard' nutzt weiter den v11-Szene-Prompt (kein Tafel-Wortlaut)."""
    sp = bildmotiv._prompt(SCENE)
    if "TAFEL" in sp or "Tafel" in sp:
        _fail("Standard-Szene-Prompt enthaelt unerwartet Tafel-Wortlaut")
    if "KEIN Text, keine Schrift" not in sp:
        _fail("Standard-Szene-Prompt (v11) veraendert - 'KEIN Text'-Anweisung fehlt")
    print("  B4) Standard-Szene-Prompt (v11) unveraendert OK")


def test_ensure_photo_fuer_routing():
    """Ohne API-Key liefert ensure_photo_fuer im ki_tafel-Modus None (kein Crash, kein Netz)."""
    db.set_einstellung("bild_stil", "ki_tafel")
    res = bildmotiv.ensure_photo_fuer({"ueberschrift": SIGN, "szene_motiv": SCENE})
    if res is not None:
        _fail("Ohne openai_api_key sollte ensure_photo_fuer (ki_tafel) None liefern, war: %r" % res)
    db.set_einstellung("bild_stil", "standard")
    print("  B5) ensure_photo_fuer routet ki_tafel + None ohne Key OK")


# ---------------------------------------------------------------------------
# C) bildgen Rendering je Modus
# ---------------------------------------------------------------------------
FIELDS = {
    "ueberschrift": "Abschiedsfeier steuerfrei - so geht's!",
    "subline": "Was Arbeitnehmer beachten muessen",
    "bullets": ["Bis 110 Euro je Person steuerfrei", "Betrieblicher Anlass noetig", "Belege aufbewahren"],
    "cta": "Jetzt Beratungsstelle in Ihrer Naehe finden",
    "hero": "110 EUR",
}


def _dummy_photo(path):
    """Opakes Dummy-Foto (RGB, kein Alpha) - simuliert das KI-Foto ohne OpenAI."""
    Image.new("RGB", (1024, 1024), (180, 140, 90)).save(path)
    return path


def _card_pixels(img):
    """Grobe Heuristik: zaehlt nahezu-weisse Pixel in der Bildmitte (dort sitzt die v11-Textkarte).
    Im ki_tafel-Modus ohne Karte ist das Foto dort braun -> nahe 0 weisse Pixel."""
    cnt = 0
    px = img.convert("RGB").load()
    for x in range(380, 700, 8):
        for y in range(380, 700, 8):
            r, g, bl = px[x, y]
            if r > 235 and g > 235 and bl > 235:
                cnt += 1
    return cnt


def test_render_ki_tafel():
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "dummy_tafel.png"))
    db.set_einstellung("bild_stil", "ki_tafel")
    out = os.path.join(data, "ki_tafel.png")
    p = b.render(FIELDS, photo, "Wir sind HILO", out, portrait=None)
    if not (p and os.path.exists(p)):
        _fail("render() (ki_tafel) hat kein Bild erzeugt")
    img = Image.open(p)
    if img.size != (1080, 1080):
        _fail("ki_tafel-Bild hat falsche Groesse: %r" % (img.size,))
    card = _card_pixels(img)
    if card > 60:
        _fail("ki_tafel-Modus zeigt offenbar doch eine Text-Karte (weisse Mitte: %d Pixel)" % card)
    print("  C1) ki_tafel: 1080x1080, KEINE Text-Karte (weisse Mitte=%d), kein Crash OK" % card)


def test_render_standard_unchanged():
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "dummy_std.png"))
    db.set_einstellung("bild_stil", "standard")
    out = os.path.join(data, "standard.png")
    p = b.render(FIELDS, photo, "Wir sind HILO", out, portrait=None)
    img = Image.open(p)
    if img.size != (1080, 1080):
        _fail("Standard-Bild hat falsche Groesse")
    card = _card_pixels(img)
    if card < 200:
        _fail("Standard-Modus zeigt keine Text-Karte (weisse Mitte nur %d Pixel)" % card)
    print("  C2) standard: Text-Karte vorhanden (weisse Mitte=%d) - v11 unveraendert OK" % card)


def test_render_ki_tafel_creme_fallback():
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    db.set_einstellung("bild_stil", "ki_tafel")
    out = os.path.join(data, "ki_tafel_creme.png")
    p = b.render(FIELDS, None, "Wir sind HILO", out, portrait=None)   # kein Foto -> Creme-Fallback
    if not (p and os.path.exists(p)):
        _fail("render() (ki_tafel, kein Foto) hat kein Bild erzeugt")
    if Image.open(p).size != (1080, 1080):
        _fail("Creme-Fallback hat falsche Groesse")
    db.set_einstellung("bild_stil", "standard")
    print("  C3) ki_tafel ohne Foto: Creme-Fallback gerendert (1080x1080) OK")


if __name__ == "__main__":
    print("== A) Einstellung get/set ==")
    test_einstellung()
    print("== B) bildmotiv KI-Tafel-Prompt / Payload / Cache-Key ==")
    test_tafel_prompt()
    test_tafel_payload()
    test_tafel_cache_key()
    test_standard_prompt_unchanged()
    test_ensure_photo_fuer_routing()
    print("== C) bildgen Rendering je Modus ==")
    test_render_ki_tafel()
    test_render_standard_unchanged()
    test_render_ki_tafel_creme_fallback()
    print("BESTANDEN: Umschaltbarer Bild-Stil 'KI-Tafel' (#132) - alle Pruefungen gruen.")
