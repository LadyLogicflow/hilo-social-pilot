"""Diagnose-Log, wenn die Text-KI kein JSON liefert (Recruiting-Abbruch 05.11.2026)."""
import logging
import sys
import types

import pytest

import textgen


class _Block:
    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block(text)]
        self.stop_reason = stop_reason
        self.model = "claude-test"


def _fake_anthropic(monkeypatch, text, stop_reason="end_turn"):
    mod = types.ModuleType("anthropic")

    class _Messages:
        def create(self, **kw):
            return _Msg(text, stop_reason)

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    mod.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setattr(textgen, "get_secret", lambda *a, **k: "dummy")


def test_nicht_lesbare_antwort_wird_mit_grund_geloggt(monkeypatch, caplog):
    _fake_anthropic(monkeypatch, "Dazu kann ich leider nichts schreiben.", "end_turn")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(Exception):
            textgen.generate({}, kampagne="recruiting", variation_index=0)
    meldung = " ".join(r.getMessage() for r in caplog.records)
    assert "nicht als JSON lesbar" in meldung
    assert "recruiting" in meldung
    assert "end_turn" in meldung
    assert "Dazu kann ich leider nichts" in meldung


def test_leere_antwort_wird_mit_laenge_null_geloggt(monkeypatch, caplog):
    _fake_anthropic(monkeypatch, "", "refusal")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(Exception):
            textgen.generate({}, kampagne="recruiting", variation_index=0)
    meldung = " ".join(r.getMessage() for r in caplog.records)
    assert "refusal" in meldung and "0 Zeichen" in meldung
