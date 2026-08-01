"""
Integration-Tests für ShareNext-Features in HILO

Testet die Integration von:
1. Prompt-Builder-System
2. Multi-Stage Pipeline
"""

import pytest
from sharenext_integration import (
    generate_optimized_image_prompt,
    generate_with_pipeline,
    generate_deadline_prompt,
    generate_knowledge_prompt,
)
from image_pipeline import ContentType, PipelineError


class TestBasicIntegration:
    """Tests für grundlegende Integration"""

    def test_generate_optimized_prompt_with_pipeline(self):
        """generate_optimized_image_prompt funktioniert mit Pipeline"""
        prompt = generate_optimized_image_prompt(
            text="Steuererklärung bis 31. Dezember einreichen!",
            theme="Steuerfrist",
            content_type="deadline",
            use_pipeline=True
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        # Prompt sollte HILO-Elemente enthalten
        assert any(color in prompt for color in ["#1a3a6b", "#4a8c5c", "#b8c8e8", "Navy", "Green", "Lavender"])

    def test_generate_optimized_prompt_without_pipeline(self):
        """generate_optimized_image_prompt funktioniert ohne Pipeline"""
        prompt = generate_optimized_image_prompt(
            text="Neuer Steuertipp für Unternehmer",
            theme="Steuertipp",
            content_type="radar",
            use_pipeline=False
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "HILO" in prompt or "#1a3a6b" in prompt

    def test_both_methods_produce_valid_prompts(self):
        """Beide Methoden (mit/ohne Pipeline) liefern gültige Prompts"""
        text = "Wichtige Information zur Steuererstattung"
        theme = "Steuererstattung"

        prompt_with_pipeline = generate_optimized_image_prompt(
            text, theme, "radar", use_pipeline=True
        )
        prompt_without_pipeline = generate_optimized_image_prompt(
            text, theme, "radar", use_pipeline=False
        )

        # Beide sollten valide sein
        assert len(prompt_with_pipeline) > 100
        assert len(prompt_without_pipeline) > 100

        # Pipeline-Prompt könnte strategischer sein (meist länger)
        # Aber das ist nicht garantiert, also nur Existenz prüfen
        assert prompt_with_pipeline != prompt_without_pipeline


class TestContentTypeIntegration:
    """Tests für verschiedene Content-Typen"""

    def test_all_content_types_work(self):
        """Alle Content-Typen funktionieren"""
        content_types = ['radar', 'deadline', 'knowledge', 'anlass']

        for content_type in content_types:
            prompt = generate_optimized_image_prompt(
                text=f"Test-Text für {content_type}",
                theme="Test",
                content_type=content_type
            )

            assert len(prompt) > 0, f"Prompt für {content_type} ist leer"

    def test_deadline_content_gets_appropriate_strategy(self):
        """Deadline-Content bekommt passende Strategie"""
        result = generate_with_pipeline(
            text="Frist: 31. Dezember",
            theme="Steuerfrist",
            content_type="deadline"
        )

        # Creative Brief sollte Deadline-Strategie haben
        assert "Objekt" in result['creative_brief'].visual_strategy or \
               "Editorial" in result['creative_brief'].visual_strategy

    def test_knowledge_content_gets_appropriate_strategy(self):
        """Knowledge-Content bekommt passende Strategie"""
        result = generate_with_pipeline(
            text="Was sind Abschreibungen?",
            theme="Finanzwissen",
            content_type="knowledge"
        )

        # Creative Brief sollte Wissens-Strategie haben
        assert "Illustration" in result['creative_brief'].visual_strategy or \
               "Editorial" in result['creative_brief'].visual_strategy


class TestPipelineIntegration:
    """Tests für Pipeline-Integration"""

    def test_generate_with_pipeline_returns_complete_result(self):
        """generate_with_pipeline liefert vollständiges Ergebnis"""
        result = generate_with_pipeline(
            text="Wichtiger Steuertipp",
            theme="Steuertipp",
            content_type="radar"
        )

        # Prüfe alle erwarteten Keys
        assert 'content' in result
        assert 'creative_brief' in result
        assert 'production_brief' in result
        assert 'prompt' in result
        assert 'metadata' in result

        # Prüfe Datentypen
        assert result['prompt'] != ""
        assert result['metadata']['content_type'] == 'radar'

    def test_pipeline_produces_consistent_results(self):
        """Pipeline liefert konsistente Ergebnisse"""
        text = "Konsistenz-Test"
        theme = "Test"

        result1 = generate_with_pipeline(text, theme, "radar")
        result2 = generate_with_pipeline(text, theme, "radar")

        # Gleicher Input → Gleicher Output
        assert result1['prompt'] == result2['prompt']


class TestConvenienceFunctions:
    """Tests für Convenience-Funktionen"""

    def test_generate_deadline_prompt(self):
        """Deadline-Prompt-Generator funktioniert"""
        prompt = generate_deadline_prompt(
            text="Wichtige Frist beachten",
            deadline_date="31. Dezember 2026",
            topic="Steuererklärung"
        )

        assert len(prompt) > 0
        assert "31. Dezember 2026" in prompt
        assert "Steuererklärung" in prompt

    def test_generate_knowledge_prompt(self):
        """Knowledge-Prompt-Generator funktioniert"""
        prompt = generate_knowledge_prompt(
            text="Erklärung von Abschreibungen",
            topic="Abschreibungen",
            knowledge_level="Einsteiger"
        )

        assert len(prompt) > 0
        assert "Abschreibungen" in prompt
        assert "Einsteiger" in prompt


class TestErrorHandling:
    """Tests für Fehlerbehandlung"""

    def test_invalid_content_type_raises_error(self):
        """Ungültiger Content-Type wirft Fehler"""
        with pytest.raises(ValueError):
            generate_optimized_image_prompt(
                text="Test",
                theme="Test",
                content_type="invalid_type"
            )

    def test_empty_text_raises_error(self):
        """Leerer Text wirft Fehler"""
        with pytest.raises(ValueError):
            generate_optimized_image_prompt(
                text="",
                theme="Test",
                content_type="radar"
            )

    def test_too_short_text_raises_error(self):
        """Zu kurzer Text wirft Fehler"""
        with pytest.raises(ValueError):
            generate_optimized_image_prompt(
                text="Short",  # Nur 5 Zeichen
                theme="Test",
                content_type="radar"
            )

    def test_empty_theme_raises_error(self):
        """Leeres Thema wirft Fehler"""
        with pytest.raises(ValueError):
            generate_optimized_image_prompt(
                text="Valid text with sufficient length",
                theme="",
                content_type="radar"
            )


class TestPromptQuality:
    """Tests für Prompt-Qualität"""

    def test_prompt_contains_hilo_branding(self):
        """Prompt enthält HILO-Branding-Elemente"""
        prompt = generate_optimized_image_prompt(
            text="Test-Text mit ausreichender Länge für Validierung",
            theme="Test",
            content_type="radar"
        )

        # Mindestens eines der HILO-Elemente sollte vorhanden sein
        hilo_elements = [
            "#1a3a6b", "#4a8c5c", "#b8c8e8",  # Farben
            "Navy", "Green", "Lavender",       # Farbnamen
            "HILO",                            # Markenname
            "editorial", "Editorial",          # Stil
        ]

        assert any(element in prompt for element in hilo_elements)

    def test_prompt_has_minimum_length(self):
        """Prompt hat Mindestlänge (sollte detailliert sein)"""
        prompt = generate_optimized_image_prompt(
            text="Ausführlicher Text über Steuererstattungen und wie man sie beantragt",
            theme="Steuererstattung",
            content_type="radar"
        )

        # Ein guter Prompt sollte mindestens 200 Zeichen haben
        assert len(prompt) >= 200

    def test_prompt_contains_visual_strategy(self):
        """Prompt enthält visuelle Strategie"""
        prompt = generate_optimized_image_prompt(
            text="Text über wichtige Steuerfrist",
            theme="Frist",
            content_type="deadline"
        )

        # Sollte irgendeine Art von visueller Strategie enthalten
        visual_keywords = [
            "photograph", "editorial", "object", "illustration",
            "Fotografie", "Editorial", "Objekt", "Illustration"
        ]

        assert any(keyword.lower() in prompt.lower() for keyword in visual_keywords)


class TestBackwardCompatibility:
    """Tests für Rückwärtskompatibilität"""

    def test_works_with_string_content_type(self):
        """Funktioniert mit String content_type (wird zu Enum konvertiert)"""
        # Sollte funktionieren auch wenn String statt Enum übergeben wird
        prompt = generate_optimized_image_prompt(
            text="Test mit String content_type",
            theme="Test",
            content_type="radar"  # String, nicht Enum
        )

        assert len(prompt) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
