# -*- coding: utf-8 -*-
"""Tests fuer input_fidelity=high im Comic-Referenz-/Edit-Pfad (#162).

Beweist die VERDRAHTUNG (KEINE echten externen KI-/Bild-APIs - alles gemockt):

  1. erzeuge_comic_bild_ref sendet input_fidelity='high' im /images/edits-Datenteil;
     der reine generations-Payload (openai_payload / erzeuge_bild_openai) enthaelt es NICHT.
  2. Sicherheitsnetz: schlaegt der erste Call (MIT input_fidelity) fehl, zieht ein zweiter
     Versuch OHNE input_fidelity nach - kein Crash, alle Dateihandles sauber geschlossen.
  3. Cache-Marker: _comic_pfad / _comic_beratung_pfad / _comic_strip_pfad tragen bei
     HILO_INPUT_FIDELITY='high' den Marker 'hf_' und ergeben ANDERE Pfade als bei 'low'
     (einmalige Regenerierung); Producer und Pfad-Bauer bleiben konsistent.
  4. HILO_INPUT_FIDELITY='low' => KEIN input_fidelity im Request, KEIN 'hf_'-Marker
     (rueckwaertskompatibel, kein doppelter Fallback-Call).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/fid-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_comic_input_fidelity.py
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


def test_1_edits_sendet_input_fidelity_high():
    """erzeuge_comic_bild_ref sendet input_fidelity='high'; generations-Payload enthaelt es NICHT."""
    import base64
    import requests

    payload = b"REF-PNG-BYTES"
    b64 = base64.b64encode(payload).decode("ascii")
    captured = {}

    def _fake_post(url, headers=None, data=None, files=None, timeout=None, **kw):
        captured["data"] = data or {}
        return _FakeResp(b64)

    orig_post = requests.post
    orig_secret = bildmotiv.get_secret
    bildmotiv.get_secret = lambda name, required=False: "sk-TESTKEY-should-not-leak"
    requests.post = _fake_post
    os.environ.pop("HILO_INPUT_FIDELITY", None)  # Default = high
    try:
        result = bildmotiv.erzeuge_comic_bild_ref(
            "PROMPT", [bildmotiv.STIL_REF_PATH, bildmotiv.FINANZAMT_REF_PATH])
    finally:
        requests.post = orig_post
        bildmotiv.get_secret = orig_secret

    if result != payload:
        _fail("erzeuge_comic_bild_ref lieferte nicht die dekodierten PNG-Bytes: %r" % result)
    if captured["data"].get("input_fidelity") != "high":
        _fail("data['input_fidelity'] != 'high': %r" % captured["data"].get("input_fidelity"))
    # generations-Payload (erzeuge_bild_openai) darf input_fidelity NICHT tragen.
    gen = bildmotiv.openai_payload("PROMPT")
    if "input_fidelity" in gen:
        _fail("generations-Payload enthaelt faelschlich input_fidelity: %r" % gen)
    _ok("edits sendet input_fidelity='high'; generations-Payload enthaelt es NICHT")


def test_2_fallback_ohne_fidelity_bei_fehler():
    """Erster Call (mit input_fidelity) schlaegt fehl -> zweiter Versuch OHNE, Handles geschlossen."""
    import base64
    import requests

    payload = b"OK-OHNE-FID"
    b64 = base64.b64encode(payload).decode("ascii")
    aufrufe = []
    handles = []

    def _fake_post(url, headers=None, data=None, files=None, timeout=None, **kw):
        aufrufe.append(dict(data or {}))
        for f in (files or []):
            handles.append(f[1][1])  # das echte Dateihandle
        if "input_fidelity" in (data or {}):
            raise RuntimeError("Unknown parameter: 'input_fidelity'")
        return _FakeResp(b64)

    orig_post = requests.post
    orig_secret = bildmotiv.get_secret
    bildmotiv.get_secret = lambda name, required=False: "sk-TESTKEY"
    requests.post = _fake_post
    os.environ.pop("HILO_INPUT_FIDELITY", None)  # Default = high
    try:
        result = bildmotiv.erzeuge_comic_bild_ref(
            "PROMPT", [bildmotiv.STIL_REF_PATH, bildmotiv.FINANZAMT_REF_PATH])
    finally:
        requests.post = orig_post
        bildmotiv.get_secret = orig_secret

    if result != payload:
        _fail("Fallback lieferte nicht die Bytes des zweiten Versuchs: %r" % result)
    if len(aufrufe) != 2:
        _fail("Erwartet genau 2 Versuche (mit/ohne fidelity), waren: %d" % len(aufrufe))
    if "input_fidelity" not in aufrufe[0]:
        _fail("Versuch 1 sollte input_fidelity tragen: %r" % aufrufe[0])
    if "input_fidelity" in aufrufe[1]:
        _fail("Versuch 2 darf KEIN input_fidelity tragen: %r" % aufrufe[1])
    # Alle geoeffneten Dateihandles sind geschlossen (finally je Versuch).
    offen = [h for h in handles if not getattr(h, "closed", True)]
    if offen:
        _fail("Nicht alle Dateihandles wurden geschlossen: %r" % offen)
    _ok("Fallback: Versuch1 mit->Fehler, Versuch2 ohne input_fidelity; kein Crash, Handles geschlossen")


def test_3_cache_marker_high_vs_low():
    """_comic_*_pfad tragen bei high den 'hf_'-Marker und ergeben andere Pfade als bei low."""
    fields = {"ueberschrift": "Fidelity-Cache",
              "comic_brief": {"stimmung": "sachlich", "szene": "identische Szene",
                              "hook": "", "finanzamt_figur": False}}
    berater = bildmotiv.FINANZAMT_REF_PATH  # existierende Datei als Berater-/Panel-Referenz-Stellvertreter

    os.environ["HILO_INPUT_FIDELITY"] = "high"
    try:
        p_comic_hi = bildmotiv._comic_pfad(fields, tool="openai")
        p_ber_hi = bildmotiv._comic_beratung_pfad(fields, berater, tool="openai")
        p_strip_hi = bildmotiv._comic_strip_pfad(0, "PANEL", berater, tool="openai")
    finally:
        os.environ.pop("HILO_INPUT_FIDELITY", None)
    os.environ["HILO_INPUT_FIDELITY"] = "low"
    try:
        p_comic_lo = bildmotiv._comic_pfad(fields, tool="openai")
        p_ber_lo = bildmotiv._comic_beratung_pfad(fields, berater, tool="openai")
        p_strip_lo = bildmotiv._comic_strip_pfad(0, "PANEL", berater, tool="openai")
    finally:
        os.environ.pop("HILO_INPUT_FIDELITY", None)

    for name, hi, lo in (("comic", p_comic_hi, p_comic_lo),
                         ("comic_beratung", p_ber_hi, p_ber_lo),
                         ("comic_strip", p_strip_hi, p_strip_lo)):
        if hi == lo:
            _fail("%s: high- und low-Pfad identisch (kein Marker): %r" % (name, hi))
        if "hf_" not in os.path.basename(hi):
            _fail("%s: high-Pfad traegt keinen 'hf_'-Marker: %r" % (name, os.path.basename(hi)))
        if "hf_" in os.path.basename(lo):
            _fail("%s: low-Pfad traegt faelschlich 'hf_'-Marker: %r" % (name, os.path.basename(lo)))
    # Konsistenz Producer<->Pfadbauer: cache_dateien_fuer_fields (nutzt _comic_pfad) enthaelt den
    # high-Comic-Pfad, wenn high aktiv ist.
    os.environ["HILO_INPUT_FIDELITY"] = "high"
    try:
        pfade = bildmotiv.cache_dateien_fuer_fields(fields)
        p_now = bildmotiv._comic_pfad(fields, tool="openai")
    finally:
        os.environ.pop("HILO_INPUT_FIDELITY", None)
    if p_now not in pfade:
        _fail("cache_dateien_fuer_fields enthaelt den high-Comic-Pfad nicht (Inkonsistenz)")
    _ok("Cache-Marker: high traegt 'hf_' -> andere Pfade als low; Producer/Aufraeumschutz konsistent")


def test_4_low_kein_fidelity_kein_marker():
    """HILO_INPUT_FIDELITY='low' => kein input_fidelity im Request, kein doppelter Call, kein Marker."""
    import base64
    import requests

    payload = b"LOW-PNG"
    b64 = base64.b64encode(payload).decode("ascii")
    aufrufe = []

    def _fake_post(url, headers=None, data=None, files=None, timeout=None, **kw):
        aufrufe.append(dict(data or {}))
        return _FakeResp(b64)

    orig_post = requests.post
    orig_secret = bildmotiv.get_secret
    bildmotiv.get_secret = lambda name, required=False: "sk-TESTKEY"
    requests.post = _fake_post
    os.environ["HILO_INPUT_FIDELITY"] = "low"
    try:
        result = bildmotiv.erzeuge_comic_bild_ref("PROMPT", [bildmotiv.STIL_REF_PATH])
        marker = bildmotiv._fidelity_marker()
    finally:
        requests.post = orig_post
        bildmotiv.get_secret = orig_secret
        os.environ.pop("HILO_INPUT_FIDELITY", None)

    if result != payload:
        _fail("low: erzeuge_comic_bild_ref lieferte nicht die Bytes: %r" % result)
    if len(aufrufe) != 1:
        _fail("low: erwartet genau 1 Call (kein Fallback), waren: %d" % len(aufrufe))
    if "input_fidelity" in aufrufe[0]:
        _fail("low: Request darf KEIN input_fidelity tragen: %r" % aufrufe[0])
    if marker != "":
        _fail("low: _fidelity_marker() sollte '' sein, war: %r" % marker)
    _ok("low: kein input_fidelity im Request, genau 1 Call, kein 'hf_'-Marker")


def main():
    db.init_db()
    test_1_edits_sendet_input_fidelity_high()
    test_2_fallback_ohne_fidelity_bei_fehler()
    test_3_cache_marker_high_vs_low()
    test_4_low_kein_fidelity_kein_marker()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
