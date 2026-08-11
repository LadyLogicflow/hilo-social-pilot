# -*- coding: utf-8 -*-
"""Tests fuer Issue #138 - Anti-generisch: Foto-Prompt Richtung authentische/
dokumentarische Optik (weg vom Hochglanz-Stockfoto-Look).

Deckt ab (beide Prompts: _prompt + _tafel_prompt):
  A) Anti-generisch-Anweisung vorhanden:
     - dokumentarisch/Reportage + authentisch
     - charaktervoll/gelebte Gesichter + natuerliche Hautstruktur
     - echte/gelebte Umgebung mit Alltags-Details
     - Verneinung von Stockfoto / Model / steriler Werbe-/Corporate-Optik
  B) Bestehende Anweisungen (#135/#136) weiterhin vorhanden:
     - Schild in der Szene integriert (Tisch/Staffelei/angelehnt), NICHT gehalten, candid
     - themenpassende Stimmung (Zuversicht/Erleichterung) + Normalfarben (neutrales Tageslicht)
     - Tafel-Text-Block unveraendert: HILO-Dunkelblau, serifenlos, helles Schild,
       sign_text in Anfuehrungszeichen, 'EINZIGE Schrift', echte Umlaute
  C) Rahmen-Regression: Payload background='opaque'/size '1024x1024', Cache-Praefixe
     (szene:/tafel:) unveraendert; beide Modi rendern 1080x1080 mit Dummy-Foto.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/manual_anti_generisch.py
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


SCENE = "ruhige Buero-Szene mit einer beratenen Familie"
SIGN = "Frist verpasst? Wir helfen sofort!"


# Pro Aspekt eine Menge alternativer Formulierungen (mindestens eine reicht), damit der
# Test die fachliche ABSICHT prueft, nicht eine exakte Wortwahl.
_DOKUMENTARISCH = ["dokumentarisch", "redaktionell", "reportage"]
_AUTHENTISCH = ["authentisch"]
_CHARAKTERVOLL = ["charaktervoll", "gelebten gesichtern", "natuerlicher hautstruktur",
                  "natürlicher hautstruktur", "individuelle"]
_ECHTE_UMGEBUNG = ["gelebte, leicht unperfekte", "alltags-details", "kein steriles studio"]
# Verneinungen (weg vom Stock-Look)
_NO_STOCKFOTO = ["hochglanz-stockfoto", "stockfoto"]
_NO_MODEL = ["austauschbaren models", "model-gesichter", "models"]
_NO_STERIL = ["sterile werbe", "corporate-optik", "steril"]


def _has_any(prompt, options):
    low = prompt.lower()
    return any(o.lower() in low for o in options)


def _assert_anti_generisch(prompt, label):
    if not _has_any(prompt, _DOKUMENTARISCH):
        _fail("%s: dokumentarisch/redaktionell/Reportage-Anweisung fehlt" % label)
    if not _has_any(prompt, _AUTHENTISCH):
        _fail("%s: 'authentisch'-Anweisung fehlt" % label)
    if not _has_any(prompt, _CHARAKTERVOLL):
        _fail("%s: charaktervolle/gelebte Gesichter / Hautstruktur fehlt" % label)
    if not _has_any(prompt, _ECHTE_UMGEBUNG):
        _fail("%s: echte/gelebte Umgebung mit Alltags-Details fehlt" % label)
    if not _has_any(prompt, _NO_STOCKFOTO):
        _fail("%s: Verneinung 'Stockfoto' fehlt" % label)
    if not _has_any(prompt, _NO_MODEL):
        _fail("%s: Verneinung 'Model'/austauschbare Models fehlt" % label)
    if not _has_any(prompt, _NO_STERIL):
        _fail("%s: Verneinung steriler Werbe-/Corporate-Optik fehlt" % label)


# Bestehende Anweisungen (#135/#136), die NICHT verloren gehen duerfen.
_SCHILD_IN_SZENE = ["in die Szene integriert", "natuerlich in die szene"]
_SCHILD_TRAEGER = ["auf einem Tisch", "Staffelei", "angelehnt", "lehnt an"]
_NICHT_GEHALTEN = ["GEHALTEN"]
_CANDID = ["candid", "ungestellt", "Schnappschuss"]
_MOOD_THEMA = ["Zuversicht", "Erleichterung", "Souveraenitaet"]
_NORMALFARBEN = ["neutralem Tageslicht"]


def _assert_bestehend(prompt, label):
    if not _has_any(prompt, _SCHILD_IN_SZENE):
        _fail("%s: Schild-in-Szene-Anweisung verloren gegangen" % label)
    if not _has_any(prompt, _SCHILD_TRAEGER):
        _fail("%s: Schild-Traeger (Tisch/Staffelei/angelehnt) verloren gegangen" % label)
    if not _has_any(prompt, _NICHT_GEHALTEN):
        _fail("%s: 'nicht gehalten'-Anweisung verloren gegangen" % label)
    if not _has_any(prompt, _CANDID):
        _fail("%s: candid/ungestellt verloren gegangen" % label)
    if not _has_any(prompt, _MOOD_THEMA):
        _fail("%s: themenpassende Stimmung (Zuversicht/Erleichterung) verloren gegangen" % label)
    if not _has_any(prompt, _NORMALFARBEN):
        _fail("%s: Normalfarben (neutrales Tageslicht) verloren gegangen" % label)


def test_anti_generisch_beide_prompts():
    print("== A) Anti-generisch-Anweisung in beiden Prompts ==")
    sp = bildmotiv._prompt(SCENE)
    tp = bildmotiv._tafel_prompt(SCENE, SIGN)
    _assert_anti_generisch(sp, "Szene-Prompt")
    _assert_anti_generisch(tp, "Tafel-Prompt")
    print("  A1) Beide Prompts: dokumentarisch/authentisch/charaktervoll/echte Umgebung "
          "+ Verneinung Stockfoto/Model/steril OK")


def test_bestehende_anweisungen_erhalten():
    print("== B) Bestehende Anweisungen (#135/#136) erhalten ==")
    sp = bildmotiv._prompt(SCENE)
    tp = bildmotiv._tafel_prompt(SCENE, SIGN)
    _assert_bestehend(sp, "Szene-Prompt")
    _assert_bestehend(tp, "Tafel-Prompt")
    # Szene-Prompt: 'KEIN Text'-Anweisung bleibt
    if "KEIN Text, keine Schrift" not in sp:
        _fail("Szene-Prompt: 'KEIN Text'-Anweisung verloren gegangen")
    # Tafel-Text-Block unveraendert: HILO-Dunkelblau, serifenlos, helles Schild, EINZIGE,
    # sign_text in Anfuehrungszeichen
    if "HILO-Dunkelblau" not in tp:
        _fail("Tafel-Prompt: 'HILO-Dunkelblau' fehlt")
    if "SERIFENLOSEN" not in tp or "Arial-aehnlich" not in tp:
        _fail("Tafel-Prompt: serifenlose Schriftangabe fehlt")
    if "helles Schild" not in tp:
        _fail("Tafel-Prompt: 'helles Schild' fehlt")
    if "EINZIGE" not in tp:
        _fail("Tafel-Prompt: 'EINZIGE Schrift'-Anweisung fehlt")
    if ("'%s'" % SIGN) not in tp:
        _fail("Tafel-Prompt: sign_text nicht mehr in Anfuehrungszeichen")
    for ch in ("ä", "ö", "ü", "ß"):
        if ch not in tp:
            _fail("Tafel-Prompt: echter Umlaut %r fehlt" % ch)
    print("  B1) Beide Prompts: Schild-in-Szene/candid + Stimmung + Normalfarben + "
          "Tafel-Text-Block (HILO-Blau/serifenlos/EINZIGE/Anfuehrungszeichen/Umlaute) OK")


def test_rahmen_unveraendert():
    print("== C) Rahmen-Regression: Payload + Cache-Praefixe unveraendert ==")
    pl_t = bildmotiv.tafel_payload(SCENE, SIGN)
    if pl_t.get("background") != "opaque":
        _fail("Tafel-Payload background != 'opaque'")
    if pl_t.get("size") != "1024x1024":
        _fail("Tafel-Payload size != '1024x1024'")
    pl_s = bildmotiv.openai_payload(bildmotiv._prompt(SCENE))
    if pl_s.get("background") != "opaque" or pl_s.get("size") != "1024x1024":
        _fail("Szene-Payload background/size veraendert")
    if not bildmotiv.tafel_cache_key(SCENE, SIGN).startswith("tafel:"):
        _fail("Cache-Praefix 'tafel:' veraendert")
    sp = bildmotiv._szene_pfad(SCENE)
    if not (sp and os.path.basename(sp).endswith(".png")):
        _fail("Szene-Pfad (Praefix 'szene:') kaputt")
    print("  C1) background='opaque', size='1024x1024', Cache-Praefixe szene:/tafel: unveraendert OK")


def _dummy_photo(path):
    Image.new("RGB", (1024, 1024), (150, 150, 150)).save(path)
    return path


def test_render_beide_modi():
    print("== C) Render beide Modi mit Dummy-Foto (1080x1080) ==")
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "antigen_dummy.png"))
    fields = {"ueberschrift": SIGN, "cta": "Jetzt Beratungsstelle finden", "szene_motiv": SCENE}
    for stil in ("standard", "ki_tafel"):
        db.set_einstellung("bild_stil", stil)
        out = os.path.join(data, "antigen_%s.png" % stil)
        p = b.render(fields, photo, "Wir sind HILO", out, portrait=None)
        if not (p and os.path.exists(p)):
            _fail("render() (%s) hat kein Bild erzeugt" % stil)
        if Image.open(p).size != (1080, 1080):
            _fail("%s-Bild hat falsche Groesse" % stil)
    db.set_einstellung("bild_stil", "standard")
    print("  C2) Render standard + ki_tafel: 1080x1080 OK")


if __name__ == "__main__":
    db.init_db()
    test_anti_generisch_beide_prompts()
    test_bestehende_anweisungen_erhalten()
    test_rahmen_unveraendert()
    test_render_beide_modi()
    print("BESTANDEN: Anti-generisch (#138) - alle Pruefungen gruen.")
