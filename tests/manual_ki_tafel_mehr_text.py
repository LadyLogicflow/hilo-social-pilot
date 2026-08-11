# -*- coding: utf-8 -*-
"""Tests fuer Issue #139 - KI-Tafel: mehr Text aufs Schild (Ueberschrift + Stichpunkte).

Deckt ab:
  A) bildmotiv.tafel_sign_text (sign_text-Bauer):
     - mit bullets -> Ueberschrift + alle Stichpunkte, mehrzeilig, je '- '-Prefix
     - ohne/leere bullets -> nur Ueberschrift (Fallback = #132-Verhalten)
     - fehlende/kaputte Felder -> kein Crash (immer String)
  B) _tafel_prompt enthaelt den VOLLSTAENDIGEN sign_text (inkl. Bullets),
     die Anweisung 'Ueberschrift gross, Stichpunkte darunter', 'EINZIGE Schrift',
     korrekte deutsche Umlaute; bestehende Anweisungen (Schild-in-Szene,
     anti-generisch/dokumentarisch, themenpassende Stimmung) weiter vorhanden.
  C) Cache-Key aendert sich mit laengerem sign_text (anderes Motiv -> andere Datei);
     Payload (background='opaque', size '1024x1024') + Praefixe (tafel:/ideogram_)
     unveraendert.
  D) ensure_photo_fuer (ki_tafel) routet ohne Key zu None (kein Crash, kein Netz),
     auch mit Bullets; render beide Modi mit Dummy-Foto ok.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/manual_ki_tafel_mehr_text.py
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


UEBERSCHRIFT = "Abschiedsfeier steuerfrei - so geht's!"
BULLETS = ["Bis 110 Euro je Person steuerfrei", "Betrieblicher Anlass noetig", "Belege aufbewahren"]
SCENE = "warme Sommerszene am Strand bei Sonnenuntergang"


# ---------------------------------------------------------------------------
# A) sign_text-Bauer
# ---------------------------------------------------------------------------
def test_sign_text_mit_bullets():
    st = bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT, "bullets": BULLETS})
    zeilen = st.split("\n")
    if zeilen[0] != UEBERSCHRIFT:
        _fail("Erste Zeile ist nicht die Ueberschrift: %r" % zeilen[0])
    # alle Bullets vorhanden, je eigene Zeile mit '- '-Prefix
    for bl in BULLETS:
        if ("- " + bl) not in zeilen:
            _fail("Bullet %r fehlt als eigene '- '-Zeile" % bl)
    if len(zeilen) != 1 + len(BULLETS):
        _fail("Zeilenanzahl falsch: erwartet %d, war %d (%r)" % (1 + len(BULLETS), len(zeilen), zeilen))
    print("  A1) sign_text mit Bullets: Ueberschrift + alle Stichpunkte mehrzeilig ('- ') OK")


def test_sign_text_ohne_bullets():
    # keine bullets / leere Liste / leere Strings -> nur Ueberschrift (Fallback)
    for fields in (
        {"ueberschrift": UEBERSCHRIFT},
        {"ueberschrift": UEBERSCHRIFT, "bullets": []},
        {"ueberschrift": UEBERSCHRIFT, "bullets": ["", "   "]},
        {"ueberschrift": UEBERSCHRIFT, "bullets": None},
    ):
        st = bildmotiv.tafel_sign_text(fields)
        if st != UEBERSCHRIFT:
            _fail("Fallback nur-Ueberschrift verletzt fuer %r -> %r" % (fields, st))
    print("  A2) sign_text ohne (leere) Bullets: nur Ueberschrift (Fallback = #132) OK")


def test_sign_text_robust():
    # fehlende/kaputte Felder duerfen NICHT crashen und liefern immer einen String
    cases = [
        {},
        {"bullets": BULLETS},                       # nur Bullets, keine Ueberschrift
        {"ueberschrift": None, "bullets": None},
        {"ueberschrift": "", "bullets": "kein-list"},   # bullets als String (kein list/tuple)
        {"ueberschrift": UEBERSCHRIFT, "bullets": [1, 2, None, "drei"]},  # gemischte Typen
        "nicht-dict",
    ]
    for c in cases:
        st = bildmotiv.tafel_sign_text(c)
        if not isinstance(st, str):
            _fail("tafel_sign_text liefert keinen String fuer %r -> %r" % (c, st))
    # nur Bullets ohne Ueberschrift -> Bullets als Zeilen (erste Zeile kein leerer Vorspann)
    st = bildmotiv.tafel_sign_text({"bullets": BULLETS})
    if st.split("\n")[0] != "- " + BULLETS[0]:
        _fail("Nur-Bullets-Fall: erste Zeile unerwartet %r" % st.split("\n")[0])
    # nicht-list bullets -> wie kein bullet -> nur Ueberschrift
    if bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT, "bullets": "kein-list"}) != UEBERSCHRIFT:
        _fail("bullets als String muss wie 'keine bullets' behandelt werden")
    print("  A3) sign_text robust gegen fehlende/kaputte/gemischte Felder (kein Crash) OK")


# ---------------------------------------------------------------------------
# B) _tafel_prompt enthaelt den vollstaendigen sign_text + neue + alte Anweisungen
# ---------------------------------------------------------------------------
def test_tafel_prompt_volltext_und_anweisungen():
    sign_text = bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT, "bullets": BULLETS})
    prompt = bildmotiv._tafel_prompt(SCENE, sign_text)
    # vollstaendiger sign_text (inkl. aller Bullets) im Prompt
    if sign_text not in prompt:
        _fail("Der vollstaendige mehrzeilige sign_text steht nicht im Prompt")
    if UEBERSCHRIFT not in prompt:
        _fail("Ueberschrift fehlt im Prompt")
    for bl in BULLETS:
        if bl not in prompt:
            _fail("Stichpunkt %r fehlt im Prompt" % bl)
    # NEU: 'Ueberschrift gross, Stichpunkte darunter'
    low = prompt.lower()
    if "überschrift" not in low and "ueberschrift" not in low:
        _fail("Anweisung zur Ueberschrift fehlt im Prompt")
    if "stichpunkte" not in low:
        _fail("Anweisung zu den Stichpunkten fehlt im Prompt")
    if "groß" not in low and "gross" not in low:
        _fail("'Ueberschrift gross' fehlt im Prompt")
    if "darunter" not in low:
        _fail("'Stichpunkte darunter' fehlt im Prompt")
    if "kleiner" not in low:
        _fail("'Stichpunkte kleiner aber lesbar' fehlt im Prompt")
    # 'EINZIGE Schrift'
    if "EINZIGE" not in prompt or "Schrift im gesamten Bild" not in prompt:
        _fail("'einzige Schrift im Bild'-Anweisung fehlt")
    # echte deutsche Umlaute
    for ch in ("ä", "ö", "ü", "ß"):
        if ch not in prompt:
            _fail("Echter Umlaut %r fehlt im Prompt" % ch)
    print("  B1) Tafel-Prompt: voller sign_text + 'Ueberschrift gross/Stichpunkte darunter' + EINZIGE + Umlaute OK")


def test_tafel_prompt_bestehende_anweisungen():
    sign_text = bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT, "bullets": BULLETS})
    prompt = bildmotiv._tafel_prompt(SCENE, sign_text)
    low = prompt.lower()
    # Schild in der Szene (nicht gehalten), candid
    if "in die szene integriert" not in low:
        _fail("Bestehend: 'Schild in die Szene integriert' fehlt")
    if "gehalten" not in low:
        _fail("Bestehend: 'nicht gehalten' fehlt")
    if "candid" not in low:
        _fail("Bestehend: candid/ungestellt fehlt")
    # anti-generisch / dokumentarisch
    if "dokumentarisch" not in low and "reportage" not in low:
        _fail("Bestehend: dokumentarische/Reportage-Optik fehlt")
    if "stockfoto" not in low:
        _fail("Bestehend: Abgrenzung gegen Hochglanz-Stockfoto fehlt")
    # themenpassende Stimmung
    for w in ("zuversicht", "erleichterung", "souveraenitaet"):
        if w not in low:
            _fail("Bestehend: themenpassende Stimmung (%s) fehlt" % w)
    # Szene eingesetzt + helles Schild + HILO-Dunkelblau + serifenlos
    if SCENE not in prompt:
        _fail("Bestehend: Szene wurde nicht eingesetzt")
    if "hilo-dunkelblau" not in low:
        _fail("Bestehend: HILO-Dunkelblau fehlt")
    if "serifenlos" not in low:
        _fail("Bestehend: serifenlose Schrift fehlt")
    print("  B2) Tafel-Prompt: bestehende Anweisungen (Szene/candid/anti-generisch/Stimmung) weiter da OK")


# ---------------------------------------------------------------------------
# C) Cache-Key aendert sich mit laengerem sign_text; Payload/Praefixe unveraendert
# ---------------------------------------------------------------------------
def test_cache_key_aendert_sich():
    nur_ueber = bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT})
    mit_bullets = bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT, "bullets": BULLETS})
    k1 = bildmotiv.tafel_cache_key(SCENE, nur_ueber)
    k2 = bildmotiv.tafel_cache_key(SCENE, mit_bullets)
    if k1 == k2:
        _fail("Cache-Key aendert sich NICHT mit laengerem sign_text")
    # daraus folgt ein anderer Dateipfad (anderes Motiv -> andere Datei)
    p1 = bildmotiv._tafel_pfad(SCENE, nur_ueber, tool="openai")
    p2 = bildmotiv._tafel_pfad(SCENE, mit_bullets, tool="openai")
    if p1 == p2:
        _fail("Tafel-Dateipfad aendert sich NICHT mit laengerem sign_text")
    # Praefix unveraendert
    if not k2.startswith("tafel:"):
        _fail("Cache-Praefix 'tafel:' veraendert")
    if "ideogram_" not in os.path.basename(bildmotiv._tafel_pfad(SCENE, mit_bullets, tool="ideogram")):
        _fail("Ideogram-Praefix 'ideogram_' veraendert")
    print("  C1) Cache-Key + Dateipfad aendern sich mit laengerem sign_text; Praefixe tafel:/ideogram_ ok OK")


def test_payload_unveraendert():
    sign_text = bildmotiv.tafel_sign_text({"ueberschrift": UEBERSCHRIFT, "bullets": BULLETS})
    pl = bildmotiv.tafel_payload(SCENE, sign_text)
    if pl.get("background") != "opaque":
        _fail("Payload background != 'opaque'")
    if pl.get("size") != "1024x1024":
        _fail("Payload size != '1024x1024'")
    if sign_text not in pl.get("prompt", ""):
        _fail("Payload-Prompt enthaelt den vollen sign_text nicht")
    print("  C2) Payload: background='opaque', size='1024x1024', Prompt mit vollem sign_text OK")


# ---------------------------------------------------------------------------
# D) ensure_photo_fuer Routing + Render beide Modi
# ---------------------------------------------------------------------------
FIELDS = {
    "ueberschrift": UEBERSCHRIFT,
    "subline": "Was Arbeitnehmer beachten muessen",
    "bullets": BULLETS,
    "cta": "Jetzt Beratungsstelle in Ihrer Naehe finden",
    "szene_motiv": SCENE,
}


def test_ensure_photo_fuer_mit_bullets():
    """Ohne API-Key liefert ensure_photo_fuer im ki_tafel-Modus None - auch mit Bullets (kein Crash, kein Netz)."""
    db.set_einstellung("bild_stil", "ki_tafel")
    res = bildmotiv.ensure_photo_fuer(FIELDS)
    if res is not None:
        _fail("Ohne openai_api_key sollte ensure_photo_fuer (ki_tafel, bullets) None liefern, war: %r" % res)
    db.set_einstellung("bild_stil", "standard")
    print("  D1) ensure_photo_fuer (ki_tafel, mit Bullets) -> None ohne Key, kein Crash OK")


def _dummy_photo(path):
    Image.new("RGB", (1024, 1024), (180, 140, 90)).save(path)
    return path


def test_render_beide_modi():
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "mt_dummy.png"))
    db.set_einstellung("bild_stil", "ki_tafel")
    out_t = os.path.join(data, "mt_ki_tafel.png")
    p = b.render(FIELDS, photo, "Wir sind HILO", out_t, portrait=None)
    if not (p and os.path.exists(p) and Image.open(p).size == (1080, 1080)):
        _fail("render() ki_tafel (mit Bullets) kaputt")
    db.set_einstellung("bild_stil", "standard")
    out_s = os.path.join(data, "mt_standard.png")
    p2 = b.render(FIELDS, photo, "Wir sind HILO", out_s, portrait=None)
    if not (p2 and os.path.exists(p2) and Image.open(p2).size == (1080, 1080)):
        _fail("render() standard kaputt")
    print("  D2) Render beide Modi (ki_tafel + standard) mit Dummy-Foto 1080x1080 OK")


if __name__ == "__main__":
    db.init_db()
    print("== A) sign_text-Bauer ==")
    test_sign_text_mit_bullets()
    test_sign_text_ohne_bullets()
    test_sign_text_robust()
    print("== B) Tafel-Prompt: voller sign_text + neue + alte Anweisungen ==")
    test_tafel_prompt_volltext_und_anweisungen()
    test_tafel_prompt_bestehende_anweisungen()
    print("== C) Cache-Key + Payload ==")
    test_cache_key_aendert_sich()
    test_payload_unveraendert()
    print("== D) ensure_photo_fuer + Render ==")
    test_ensure_photo_fuer_mit_bullets()
    test_render_beide_modi()
    print("BESTANDEN: KI-Tafel mehr Text (#139) - alle Pruefungen gruen.")
