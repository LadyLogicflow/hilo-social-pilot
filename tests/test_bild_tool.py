# -*- coding: utf-8 -*-
"""Tests fuer Issue #137 - umschaltbares Bild-TOOL (OpenAI | Ideogram), orthogonal zum Bild-STIL,
plus OpenAI-Modell-Bump auf gpt-image-2 (per HILO_OPENAI_IMAGE_MODEL ueberschreibbar).

Deckt ab (alles OHNE echten Netz-/API-Call - Anbieter werden gemockt):
  A) db.get/set_einstellung('bild_tool'): Default-Fallback 'openai' + Persistenz.
  B) erzeuge_bild routet je bild_tool zum richtigen Anbieter (openai vs ideogram).
  C) OpenAI-Payload nutzt das Modell aus HILO_OPENAI_IMAGE_MODEL (Default 'gpt-image-2',
     per env ueberschreibbar); background='opaque', size '1024x1024'.
  D) Ideogram-Request: korrekte URL (.../v1/ideogram-v4/generate), 'Api-Key'-Header,
     'Content-Type: application/json', Body text_prompt == unser Prompt, quadratisches Format;
     Antwort data[0].url wird heruntergeladen -> bytes.
  E) Ohne ideogram_api_key + tool=ideogram -> None (kein Crash, KEIN Fallback auf OpenAI).
  F) Cache-Key enthaelt das Tool: openai vs ideogram -> VERSCHIEDENE Dateinamen fuer gleiches Motiv
     (Szene UND Tafel). Der openai-Dateiname bleibt UNVERAENDERT (Praefix-frei).
  G) cache_dateien_fuer_fields nimmt BEIDE Tool-Varianten auf (Retention-Schutz #134/#137).
  H) Secrets werden NIE im Klartext geloggt/ausgegeben.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_bild_tool.py
"""
import os, sys, types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import bildmotiv
import secrets_store


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Fake 'requests' - faengt POST/GET ab, ohne Netz. Wird in sys.modules injiziert,
# da bildmotiv 'import requests' erst INNERHALB der Funktionen macht.
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data or {}
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _FakeRequests:
    def __init__(self):
        self.calls = []          # ('post'|'get', url, kwargs)
        self.post_resp = None
        self.get_resp = None

    def post(self, url, **kw):
        self.calls.append(("post", url, kw))
        return self.post_resp

    def get(self, url, **kw):
        self.calls.append(("get", url, kw))
        return self.get_resp


def _install_fake_requests(fake):
    sys.modules["requests"] = fake


# Secrets deterministisch ueber Monkeypatch steuern (kein echtes secrets.json noetig).
_KEYS = {}


def _fake_get_secret(name, required=False):
    return _KEYS.get(name)


bildmotiv.get_secret = _fake_get_secret
secrets_store.get_secret = _fake_get_secret


# ---------------------------------------------------------------------------
# A) Einstellung bild_tool get/set
# ---------------------------------------------------------------------------
def test_einstellung():
    db.init_db()
    if db.get_einstellung("bild_tool", "openai") != "openai":
        _fail("Default-Fallback fuer fehlendes 'bild_tool' muss 'openai' sein")
    db.set_einstellung("bild_tool", "ideogram")
    if db.get_einstellung("bild_tool", "openai") != "ideogram":
        _fail("set/get_einstellung('bild_tool') persistiert nicht")
    if bildmotiv.aktives_bild_tool() != "ideogram":
        _fail("aktives_bild_tool() liest die Einstellung nicht")
    # unbekannter Wert -> Fallback 'openai'
    db.set_einstellung("bild_tool", "quatsch")
    if bildmotiv.aktives_bild_tool() != "openai":
        _fail("unbekanntes bild_tool muss auf 'openai' zurueckfallen")
    db.set_einstellung("bild_tool", "openai")
    print("  A) get/set_einstellung('bild_tool') + aktives_bild_tool: OK")


# ---------------------------------------------------------------------------
# B/C) erzeuge_bild Routing + OpenAI-Payload-Modell
# ---------------------------------------------------------------------------
PROMPT = "Ein warmer Herbstmoment am Kuechentisch - Test-Prompt"


def test_openai_routing_und_modell():
    _KEYS.clear()
    _KEYS["openai_api_key"] = "sk-TESTKEY-openai"
    os.environ.pop("HILO_OPENAI_IMAGE_MODEL", None)

    fake = _FakeRequests()
    fake.post_resp = _Resp(json_data={"data": [{"b64_json": __import__("base64").b64encode(b"OPENAIPNG").decode()}]})
    _install_fake_requests(fake)

    daten = bildmotiv.erzeuge_bild(PROMPT, tool="openai")
    if daten != b"OPENAIPNG":
        _fail("OpenAI-Pfad liefert nicht die dekodierten Bild-Bytes: %r" % daten)
    if len(fake.calls) != 1 or fake.calls[0][0] != "post":
        _fail("OpenAI-Pfad: genau ein POST erwartet, war %r" % fake.calls)
    url, kw = fake.calls[0][1], fake.calls[0][2]
    if url != "https://api.openai.com/v1/images/generations":
        _fail("OpenAI-URL falsch: %r" % url)
    body = kw.get("json") or {}
    if body.get("model") != "gpt-image-2":
        _fail("OpenAI-Default-Modell muss 'gpt-image-2' sein, war %r" % body.get("model"))
    if body.get("background") != "opaque" or body.get("size") != "1024x1024":
        _fail("OpenAI-Payload background/size falsch: %r" % body)
    if body.get("prompt") != PROMPT:
        _fail("OpenAI-Payload muss unseren Prompt enthalten")
    if "Bearer sk-TESTKEY-openai" not in kw.get("headers", {}).get("Authorization", ""):
        _fail("OpenAI-Authorization-Header fehlt/falsch")

    # env-Ueberschreibung des Modells
    os.environ["HILO_OPENAI_IMAGE_MODEL"] = "gpt-image-5-experimental"
    if bildmotiv.openai_payload(PROMPT)["model"] != "gpt-image-5-experimental":
        _fail("HILO_OPENAI_IMAGE_MODEL ueberschreibt das Modell nicht")
    os.environ.pop("HILO_OPENAI_IMAGE_MODEL", None)
    print("  B/C) erzeuge_bild routet zu OpenAI; Modell-Default 'gpt-image-2' + env-ueberschreibbar: OK")


# ---------------------------------------------------------------------------
# D) Ideogram-Request-Struktur + URL-Download
# ---------------------------------------------------------------------------
def test_ideogram_routing():
    _KEYS.clear()
    _KEYS["ideogram_api_key"] = "ideo-TESTKEY"
    os.environ.pop("HILO_IDEOGRAM_RESOLUTION", None)

    fake = _FakeRequests()
    fake.post_resp = _Resp(json_data={"data": [{"url": "https://img.ideogram.ai/bild123.png"}]})
    fake.get_resp = _Resp(content=b"IDEOGRAMPNG")
    _install_fake_requests(fake)

    daten = bildmotiv.erzeuge_bild(PROMPT, tool="ideogram")
    if daten != b"IDEOGRAMPNG":
        _fail("Ideogram-Pfad liefert nicht die heruntergeladenen Bild-Bytes: %r" % daten)
    if len(fake.calls) != 2:
        _fail("Ideogram-Pfad: POST + GET erwartet, war %r" % fake.calls)
    (m1, url1, kw1), (m2, url2, kw2) = fake.calls
    if m1 != "post" or url1 != "https://api.ideogram.ai/v1/ideogram-v4/generate":
        _fail("Ideogram-URL falsch: %r" % url1)
    headers = kw1.get("headers", {})
    if headers.get("Api-Key") != "ideo-TESTKEY":
        _fail("Ideogram 'Api-Key'-Header fehlt/falsch")
    if headers.get("Content-Type") != "application/json":
        _fail("Ideogram Content-Type muss application/json sein")
    body = kw1.get("json") or {}
    if body.get("text_prompt") != PROMPT:
        _fail("Ideogram-Body 'text_prompt' muss unseren Prompt enthalten, war %r" % body.get("text_prompt"))
    # quadratisches Format (Default 1024x1024) muss enthalten sein
    if "1024x1024" not in (body.get("resolution") or ""):
        _fail("Ideogram-Body muss quadratisches Format (1024x1024) tragen, war %r" % body.get("resolution"))
    if m2 != "get" or url2 != "https://img.ideogram.ai/bild123.png":
        _fail("Ideogram: Bild-URL aus data[0].url muss per GET geladen werden, war %r" % (m2, url2))

    # env-Ueberschreibung der Aufloesung
    os.environ["HILO_IDEOGRAM_RESOLUTION"] = "RESOLUTION_2048_2048"
    if bildmotiv.ideogram_payload(PROMPT)["resolution"] != "RESOLUTION_2048_2048":
        _fail("HILO_IDEOGRAM_RESOLUTION ueberschreibt die Aufloesung nicht")
    os.environ.pop("HILO_IDEOGRAM_RESOLUTION", None)
    print("  D) Ideogram-Request (URL/Api-Key/JSON/text_prompt/quadratisch) + URL-Download: OK")


# ---------------------------------------------------------------------------
# E) Ohne ideogram_api_key + tool=ideogram -> None, KEIN Fallback auf OpenAI
# ---------------------------------------------------------------------------
def test_ideogram_ohne_key():
    _KEYS.clear()
    _KEYS["openai_api_key"] = "sk-vorhanden"   # darf NICHT benutzt werden
    fake = _FakeRequests()
    fake.post_resp = _Resp(json_data={"data": [{"b64_json": "X"}]})
    _install_fake_requests(fake)
    daten = bildmotiv.erzeuge_bild(PROMPT, tool="ideogram")
    if daten is not None:
        _fail("Ohne ideogram_api_key muss erzeuge_bild(tool=ideogram) None liefern")
    if fake.calls:
        _fail("Ohne ideogram_api_key darf KEIN Request (auch kein OpenAI-Fallback) erfolgen: %r" % fake.calls)
    print("  E) ohne ideogram_api_key + tool=ideogram -> None, kein OpenAI-Fallback: OK")


# ---------------------------------------------------------------------------
# F) Cache-Key enthaelt das Tool (Szene + Tafel); openai-Name unveraendert
# ---------------------------------------------------------------------------
def test_cache_key_pro_tool():
    motiv = "Eine ruhige Szene am Fluss"
    p_openai = bildmotiv._szene_pfad(motiv, tool="openai")
    p_ideogram = bildmotiv._szene_pfad(motiv, tool="ideogram")
    if p_openai == p_ideogram:
        _fail("Szene-Cache-Pfad muss sich je Tool unterscheiden")
    if os.path.basename(p_ideogram) != "ideogram_" + os.path.basename(p_openai):
        _fail("Ideogram-Szene-Datei muss 'ideogram_'-Praefix vor dem OpenAI-Namen tragen: %r vs %r"
              % (os.path.basename(p_ideogram), os.path.basename(p_openai)))

    # Regression: openai-Pfad ohne tool-Arg (Default) == openai-Pfad explizit (Praefix-frei)
    db.set_einstellung("bild_tool", "openai")
    if bildmotiv._szene_pfad(motiv) != p_openai:
        _fail("Default-Tool (openai) muss den Praefix-freien Szene-Pfad liefern (Cache-Regression)")

    # Tafel ebenso
    t_openai = bildmotiv._tafel_pfad("Szene", "Ueberschrift", tool="openai")
    t_ideogram = bildmotiv._tafel_pfad("Szene", "Ueberschrift", tool="ideogram")
    if t_openai == t_ideogram:
        _fail("Tafel-Cache-Pfad muss sich je Tool unterscheiden")
    if not os.path.basename(t_openai).startswith("tafel_"):
        _fail("OpenAI-Tafel-Datei muss unveraendert mit 'tafel_' beginnen")
    if not os.path.basename(t_ideogram).startswith("ideogram_tafel_"):
        _fail("Ideogram-Tafel-Datei muss mit 'ideogram_tafel_' beginnen")
    print("  F) Cache-Key enthaelt das Tool (Szene+Tafel); OpenAI-Name unveraendert: OK")


# ---------------------------------------------------------------------------
# G) Retention-Schutz: cache_dateien_fuer_fields enthaelt BEIDE Tool-Varianten
# ---------------------------------------------------------------------------
def test_retention_beide_tools():
    fields = {"szene_motiv": "Herbst am Kuechentisch", "ueberschrift": "Steuer leicht gemacht"}
    pfade = bildmotiv.cache_dateien_fuer_fields(fields)
    erwartet = {
        bildmotiv._szene_pfad(fields["szene_motiv"], tool="openai"),
        bildmotiv._szene_pfad(fields["szene_motiv"], tool="ideogram"),
        bildmotiv._tafel_pfad(fields["szene_motiv"], fields["ueberschrift"], tool="openai"),
        bildmotiv._tafel_pfad(fields["szene_motiv"], fields["ueberschrift"], tool="ideogram"),
    }
    fehlend = erwartet - pfade
    if fehlend:
        _fail("cache_dateien_fuer_fields fehlen Tool-Varianten (Retention-Risiko): %r" % fehlend)
    print("  G) cache_dateien_fuer_fields schuetzt BEIDE Tool-Varianten (openai+ideogram): OK")


# ---------------------------------------------------------------------------
# H) Keine Secrets im Output (defensiv: Funktionen geben Bytes/None, nie Keys)
# ---------------------------------------------------------------------------
def test_keine_secret_leaks():
    _KEYS.clear()
    _KEYS["openai_api_key"] = "sk-GEHEIM-LEAK-TEST"
    fake = _FakeRequests()
    fake.post_resp = _Resp(json_data={"data": [{"b64_json": __import__("base64").b64encode(b"P").decode()}]})
    _install_fake_requests(fake)
    out = bildmotiv.erzeuge_bild(PROMPT, tool="openai")
    if out is not None and b"sk-GEHEIM" in (out if isinstance(out, bytes) else out.encode()):
        _fail("Bild-Bytes enthalten den API-Key (Leak!)")
    print("  H) keine Secret-Leaks in der Rueckgabe: OK")


if __name__ == "__main__":
    test_einstellung()
    test_openai_routing_und_modell()
    test_ideogram_routing()
    test_ideogram_ohne_key()
    test_cache_key_pro_tool()
    test_retention_beide_tools()
    test_keine_secret_leaks()
    print("ALLE TESTS GRUEN (#137 - umschaltbares Bild-Tool + gpt-image-2)")
