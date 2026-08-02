#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit-Tests für Message Brief Generator.

Tests ohne echte API-Calls (Mock).
"""

import pytest
from unittest.mock import Mock, patch
from message_brief import MessageBrief, generate_message_brief


def test_message_brief_model():
    """Teste MessageBrief Pydantic Model."""
    brief = MessageBrief(
        kernaussage="Steuerfrist endet 31.12.",
        nutzen="Verspätungszuschlag vermeiden",
        zielgruppe="Arbeitnehmer",
        reaktion="Termin buchen",
        funnel_stufe="Decision",
        kanal="Facebook"
    )

    assert brief.kernaussage == "Steuerfrist endet 31.12."
    assert brief.zielgruppe == "Arbeitnehmer"
    assert brief.funnel_stufe == "Decision"


def test_message_brief_invalid_funnel():
    """Teste dass ungültige Funnel-Stufe abgelehnt wird."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        MessageBrief(
            kernaussage="Test",
            nutzen="Test",
            zielgruppe="Test",
            reaktion="Test",
            funnel_stufe="Invalid",  # Ungültig!
            kanal="Facebook"
        )


@patch('message_brief._get_client')
def test_generate_message_brief_mock(mock_get_client):
    """Teste generate_message_brief mit gemocktem OpenAI Client."""

    # Mock OpenAI Response
    mock_client = Mock()
    mock_completion = Mock()
    mock_choice = Mock()
    mock_message = Mock()

    # Simuliere strukturierten Output
    mock_message.parsed = MessageBrief(
        kernaussage="Wichtige Steuerfrist endet am 31. Dezember",
        nutzen="Rechtzeitig einreichen, Verspätungszuschlag vermeiden",
        zielgruppe="Arbeitnehmer",
        reaktion="Termin buchen",
        funnel_stufe="Decision",
        kanal="Facebook"
    )

    mock_choice.message = mock_message
    mock_completion.choices = [mock_choice]
    mock_client.beta.chat.completions.parse.return_value = mock_completion
    mock_get_client.return_value = mock_client

    # Test
    brief = generate_message_brief(
        stream="fristen",
        thema="Steuerfrist 31.12.",
        text="Jetzt Termin sichern!",
        kanal="Facebook"
    )

    assert brief.kernaussage == "Wichtige Steuerfrist endet am 31. Dezember"
    assert brief.zielgruppe == "Arbeitnehmer"
    assert brief.funnel_stufe == "Decision"
    assert brief.kanal == "Facebook"

    # Prüfe dass OpenAI aufgerufen wurde
    mock_client.beta.chat.completions.parse.assert_called_once()
    call_args = mock_client.beta.chat.completions.parse.call_args
    assert call_args.kwargs["model"] == "gpt-4o-mini"
    assert call_args.kwargs["response_format"] == MessageBrief


@patch('message_brief._get_client')
def test_generate_message_brief_kindergeld(mock_get_client):
    """Teste dass Kindergeld → Eltern erkannt wird."""

    mock_client = Mock()
    mock_completion = Mock()
    mock_choice = Mock()
    mock_message = Mock()

    # KI sollte "Eltern mit Kindern" erkennen
    mock_message.parsed = MessageBrief(
        kernaussage="Kindergeld beantragen - So geht's",
        nutzen="Finanzielle Unterstützung für Familien sichern",
        zielgruppe="Eltern mit Kindern",  # Automatisch erkannt!
        reaktion="Termin buchen",
        funnel_stufe="Consideration",
        kanal="Instagram"
    )

    mock_choice.message = mock_message
    mock_completion.choices = [mock_choice]
    mock_client.beta.chat.completions.parse.return_value = mock_completion
    mock_get_client.return_value = mock_client

    # Test
    brief = generate_message_brief(
        stream="wissen",
        thema="Kindergeld: So funktioniert die Beantragung",
        text="Wir erklären Schritt für Schritt...",
        kanal="Instagram"
    )

    assert brief.zielgruppe == "Eltern mit Kindern"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
