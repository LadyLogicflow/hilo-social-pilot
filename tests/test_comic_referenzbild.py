# -*- coding: utf-8 -*-
"""Tests fuer den Comic-Referenzbild-Pfad (OpenAI images/edits mit Stil-/Charakter-Referenz).

Beweist die VERDRAHTUNG (KEINE echten externen KI-/Bild-APIs - alles gemockt):

  1. erzeuge_comic_bild_ref: requests.post wird gepatcht -> URL endet auf '/images/edits',
     data['model']==gpt-image-1, files enthaelt die Referenzen als 'image[]', der Prompt wird
     uebergeben, KEIN 'background'-Feld; der API-Key taucht NICHT im Rueckgabewert auf.
  2. ensure_comic_bild mit finanzamt_figur True -> refs = [stil_ref, finanzamt_ref];
     False -> nur [stil_ref] (erzeuge_comic_bild_ref gepatcht, refs geprueft; erzeuge_bild
     gepatcht, damit KEIN generations-Call laeuft).
  3. Fallback: erzeuge_comic_bild_ref -> None => erzeuge_bild (generations) wird aufgerufen.
  4. HILO_COMIC_REFERENCE=0 => erzeuge_comic_bild_ref wird NICHT aufgerufen, erzeuge_bild schon.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/comic-ref-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_comic_referenzbild.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import bildmotiv


_PASS = []


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    _PASS.append(msg)
    print("  OK:", msg)


class _FakeResp:
    """Minimaler requests.Response-Ersatz fuer den images/edits-Mock."""

    def __init__(self, b64):
        self._b64 = b64

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"b64_json": self._b64}]}


def test_1_erzeuge_comic_bild_ref_request():
    """erzeuge_comic_bild_ref baut den images/edits-Request korrekt und der Key leakt nicht."""
    import base64
    import requests

    # PNG-Nutzlast, die die (gemockte) API zurueckliefert.
    payload = b"REF-PNG-BYTES"
    b64 = base64.b64encode(payload).decode("ascii")

    captured = {}

    def _fake_post(url, headers=None, data=None, files=None, timeout=None, **kw):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["data"] = data or {}
        captured["files"] = files or []
        captured["timeout"] = timeout
        captured["kw"] = kw
        return _FakeResp(b64)

    orig_post = requests.post
    orig_get_secret = bildmotiv.get_secret
    # Test-Key NUR im Mock; nie echt genutzt.
    bildmotiv.get_secret = lambda name, required=False: "sk-TESTKEY-should-not-leak"
    requests.post = _fake_post
    try:
        refs = [bildmotiv.STIL_REF_PATH, bildmotiv.FINANZAMT_REF_PATH]
        prompt = "REF-INSTRUCTION-UND-COMIC-PROMPT"
        result = bildmotiv.erzeuge_comic_bild_ref(prompt, refs)
    finally:
        requests.post = orig_post
        bildmotiv.get_secret = orig_get_secret

    # a) Rueckgabe = dekodierte Bytes
    if result != payload:
        _fail("erzeuge_comic_bild_ref lieferte nicht die dekodierten PNG-Bytes: %r" % result)
    # b) URL endet auf /images/edits
    if not captured.get("url", "").endswith("/images/edits"):
        _fail("URL endet nicht auf /images/edits: %r" % captured.get("url"))
    # c) data: Modell + Pflichtfelder, KEIN background
    data = captured["data"]
    if data.get("model") != "gpt-image-1":
        _fail("data['model'] != gpt-image-1: %r" % data.get("model"))
    if data.get("prompt") != prompt:
        _fail("data['prompt'] wurde nicht durchgereicht: %r" % data.get("prompt"))
    if data.get("size") != "1024x1024" or str(data.get("n")) != "1":
        _fail("size/n falsch: %r" % data)
    if "background" in data:
        _fail("edits-Call darf KEIN background-Feld tragen: %r" % data)
    # d) files: beide Referenzen als 'image[]', mit Basenamen
    files = captured["files"]
    feldnamen = [f[0] for f in files]
    if feldnamen != ["image[]", "image[]"]:
        _fail("files-Feldnamen falsch (erwartet 2x image[]): %r" % feldnamen)
    basenamen = [f[1][0] for f in files]
    if basenamen != [os.path.basename(bildmotiv.STIL_REF_PATH),
                     os.path.basename(bildmotiv.FINANZAMT_REF_PATH)]:
        _fail("files-Basenamen stimmen nicht mit den refs ueberein: %r" % basenamen)
    if any(f[1][2] != "image/png" for f in files):
        _fail("files-MIME-Typ ist nicht image/png: %r" % files)
    # e) Content-Type NICHT manuell gesetzt (multipart-Boundary setzt requests selbst)
    if "Content-Type" in captured["headers"]:
        _fail("Content-Type wurde manuell gesetzt (bricht multipart-Boundary): %r"
              % captured["headers"])
    # f) Key leakt NICHT in den Rueckgabewert
    if b"TESTKEY" in (result or b""):
        _fail("API-Key leakt in den Rueckgabewert")
    _ok("erzeuge_comic_bild_ref: images/edits-Request korrekt (model/prompt/files), Key leakt nicht")


def test_2_ensure_comic_bild_ref_auswahl():
    """ensure_comic_bild waehlt die Referenzen: finanzamt_figur True -> [stil, finanzamt], sonst [stil]."""
    captured = {"refs": None, "prompt": None, "gen_called": False}

    def _fake_ref(prompt, refs):
        captured["refs"] = list(refs)
        captured["prompt"] = prompt
        return b"REFPNG"

    def _fake_gen(prompt, tool=None):
        captured["gen_called"] = True
        return b"GENPNG"

    orig_ref = bildmotiv.erzeuge_comic_bild_ref
    orig_gen = bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    os.environ.pop("HILO_COMIC_REFERENCE", None)  # Default (aktiv)
    try:
        # a) MIT Finanzamt-Figur -> beide Referenzen
        fields_fa = {"ueberschrift": "Bescheid abgelehnt",
                     "comic_brief": {"stimmung": "humor", "szene": "Buerger staunt ueber Post",
                                     "hook": "Aha!", "finanzamt_figur": True}}
        path = bildmotiv.ensure_comic_bild(fields_fa)
        if captured["refs"] != [bildmotiv.STIL_REF_PATH, bildmotiv.FINANZAMT_REF_PATH]:
            _fail("finanzamt_figur True: refs != [stil_ref, finanzamt_ref]: %r" % captured["refs"])
        if not captured["prompt"].startswith(bildmotiv.REF_INSTRUCTION):
            _fail("Referenz-Prompt beginnt nicht mit REF_INSTRUCTION")
        if bildmotiv.STIL_A_BLOCK not in captured["prompt"]:
            _fail("Referenz-Prompt enthaelt STIL_A_BLOCK nicht")
        if captured["gen_called"]:
            _fail("erzeuge_bild (generations) wurde faelschlich aufgerufen (Referenz lieferte Bytes)")
        if not path or not os.path.exists(path):
            _fail("ensure_comic_bild (Finanzamt) lieferte keinen gueltigen Cache-Pfad")

        # b) OHNE Finanzamt-Figur -> nur Stil-Referenz
        captured["refs"] = None
        captured["gen_called"] = False
        fields_ohne = {"ueberschrift": "Pauschale nutzen",
                       "comic_brief": {"stimmung": "positiv", "szene": "Paar freut sich",
                                       "hook": "", "finanzamt_figur": False}}
        bildmotiv.ensure_comic_bild(fields_ohne)
        if captured["refs"] != [bildmotiv.STIL_REF_PATH]:
            _fail("finanzamt_figur False: refs != [stil_ref]: %r" % captured["refs"])
        if captured["gen_called"]:
            _fail("erzeuge_bild (generations) wurde faelschlich aufgerufen (kein Fallback erwartet)")
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig_ref
        bildmotiv.erzeuge_bild = orig_gen
    _ok("ensure_comic_bild: Referenz-Auswahl finanzamt=[stil,finanzamt] / sonst [stil], kein generations-Call")


def test_3_fallback_auf_generations():
    """erzeuge_comic_bild_ref -> None => Fallback auf erzeuge_bild (generations) mit reinem Comic-Prompt."""
    captured = {"gen_prompt": None, "gen_called": False}

    def _fake_ref(prompt, refs):
        return None  # kein Key / Fehler

    def _fake_gen(prompt, tool=None):
        captured["gen_called"] = True
        captured["gen_prompt"] = prompt
        return b"GENPNG"

    orig_ref = bildmotiv.erzeuge_comic_bild_ref
    orig_gen = bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    os.environ.pop("HILO_COMIC_REFERENCE", None)  # Default (aktiv)
    try:
        fields = {"ueberschrift": "Fallback-Fall",
                  "comic_brief": {"stimmung": "sachlich", "szene": "ruhige Szene",
                                  "hook": "", "finanzamt_figur": False}}
        path = bildmotiv.ensure_comic_bild(fields)
        if not captured["gen_called"]:
            _fail("Fallback: erzeuge_bild (generations) wurde NICHT aufgerufen")
        if bildmotiv.REF_INSTRUCTION in (captured["gen_prompt"] or ""):
            _fail("Fallback-Prompt enthaelt faelschlich die REF_INSTRUCTION")
        if bildmotiv.STIL_A_BLOCK not in (captured["gen_prompt"] or ""):
            _fail("Fallback-Prompt enthaelt STIL_A_BLOCK nicht")
        if not path or not os.path.exists(path):
            _fail("Fallback: ensure_comic_bild lieferte keinen gueltigen Cache-Pfad")
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig_ref
        bildmotiv.erzeuge_bild = orig_gen
    _ok("Fallback: Referenz None => erzeuge_bild (generations) mit reinem Comic-Prompt")


def test_4_referenz_deaktiviert():
    """HILO_COMIC_REFERENCE=0 => erzeuge_comic_bild_ref wird NICHT aufgerufen, erzeuge_bild schon."""
    captured = {"ref_called": False, "gen_called": False}

    def _fake_ref(prompt, refs):
        captured["ref_called"] = True
        return b"REFPNG"

    def _fake_gen(prompt, tool=None):
        captured["gen_called"] = True
        return b"GENPNG"

    orig_ref = bildmotiv.erzeuge_comic_bild_ref
    orig_gen = bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    os.environ["HILO_COMIC_REFERENCE"] = "0"
    try:
        fields = {"ueberschrift": "Deaktiviert",
                  "comic_brief": {"stimmung": "sachlich", "szene": "andere Szene",
                                  "hook": "", "finanzamt_figur": True}}
        path = bildmotiv.ensure_comic_bild(fields)
        if captured["ref_called"]:
            _fail("HILO_COMIC_REFERENCE=0: erzeuge_comic_bild_ref wurde faelschlich aufgerufen")
        if not captured["gen_called"]:
            _fail("HILO_COMIC_REFERENCE=0: erzeuge_bild (generations) wurde NICHT aufgerufen")
        if not path or not os.path.exists(path):
            _fail("HILO_COMIC_REFERENCE=0: ensure_comic_bild lieferte keinen gueltigen Pfad")
    finally:
        bildmotiv.erzeuge_comic_bild_ref = orig_ref
        bildmotiv.erzeuge_bild = orig_gen
        os.environ.pop("HILO_COMIC_REFERENCE", None)
    _ok("HILO_COMIC_REFERENCE=0: kein Referenz-Call, nur generations")


def test_5_cache_key_ref_vs_nichtref_getrennt():
    """Der Cache-Pfad unterscheidet Referenz- von Nicht-Referenz-Modus (kein Kollidieren)."""
    fields = {"ueberschrift": "Kollisionstest",
              "comic_brief": {"stimmung": "sachlich", "szene": "identische Szene",
                              "hook": "", "finanzamt_figur": False}}
    os.environ.pop("HILO_COMIC_REFERENCE", None)  # aktiv
    p_ref = bildmotiv._comic_pfad(fields, tool="openai")
    os.environ["HILO_COMIC_REFERENCE"] = "0"
    try:
        p_noref = bildmotiv._comic_pfad(fields, tool="openai")
    finally:
        os.environ.pop("HILO_COMIC_REFERENCE", None)
    if p_ref == p_noref:
        _fail("Cache-Pfad Referenz vs. Nicht-Referenz ist identisch (Kollision): %r" % p_ref)
    # Und cache_dateien_fuer_fields nutzt denselben Bau (via _comic_pfad) -> enthaelt den aktiven Pfad.
    pfade = bildmotiv.cache_dateien_fuer_fields(fields)  # Default = aktiv
    if p_ref not in pfade:
        _fail("cache_dateien_fuer_fields enthaelt den aktiven (Referenz-)Comic-Pfad nicht")
    _ok("Cache-Key: Referenz- und Nicht-Referenz-Bilder bekommen getrennte Dateien; Aufraeumschutz konsistent")


def main():
    db.init_db()
    test_1_erzeuge_comic_bild_ref_request()
    test_2_ensure_comic_bild_ref_auswahl()
    test_3_fallback_auf_generations()
    test_4_referenz_deaktiviert()
    test_5_cache_key_ref_vs_nichtref_getrennt()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
