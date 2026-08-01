"""
Tests für die Multi-Stage Image Pipeline
"""

import pytest
from image_pipeline import (
    ImagePipeline,
    ContentInput,
    CreativeBrief,
    ProductionBrief,
    CreativeBriefGenerator,
    ProductionBriefGenerator,
    generate_prompt_for_content,
)


class TestContentInput:
    """Tests für ContentInput Model"""

    def test_content_input_creation(self):
        """ContentInput kann erstellt werden"""
        content = ContentInput(
            text="Steuererklärung bis 31.12.",
            theme="Frist",
            content_type="deadline"
        )
        assert content.text == "Steuererklärung bis 31.12."
        assert content.theme == "Frist"
        assert content.content_type == "deadline"
        assert content.metadata == {}

    def test_content_input_with_metadata(self):
        """ContentInput mit Metadata"""
        content = ContentInput(
            text="Test text with sufficient length",
            theme="Test",
            content_type="radar",
            metadata={"foo": "bar"}
        )
        assert content.metadata == {"foo": "bar"}


class TestCreativeBriefGenerator:
    """Tests für Creative Brief Generator"""

    def test_generate_brief_for_deadline(self):
        """Creative Brief für Deadline-Content"""
        generator = CreativeBriefGenerator()
        content = ContentInput(
            text="Steuererklärung bis 31. Dezember einreichen!",
            theme="Frist",
            content_type="deadline"
        )

        brief = generator.generate(content)

        assert isinstance(brief, CreativeBrief)
        assert brief.bildstrategie == "Warnen (ohne Alarm)"
        assert "Objektfotografie" in brief.visual_strategy
        assert brief.key_message != ""

    def test_generate_brief_for_knowledge(self):
        """Creative Brief für Wissens-Content"""
        generator = CreativeBriefGenerator()
        content = ContentInput(
            text="Was sind Abschreibungen?",
            theme="Finanzwissen",
            content_type="knowledge"
        )

        brief = generator.generate(content)

        assert brief.bildstrategie == "Erklärung visualisieren"
        assert "Illustration" in brief.visual_strategy or "Editorial" in brief.visual_strategy

    def test_visual_strategy_by_theme(self):
        """Visuelle Strategie wird korrekt nach Thema gewählt"""
        generator = CreativeBriefGenerator()

        # Steuererstattung → Editorial, hoffnungsvoll
        strategy, mood = generator._determine_visual_strategy("Steuererstattung")
        assert strategy == "Editorial Photography"
        assert "hoffnungsvoll" in mood

        # Steuerfalle → Symbolbild, warnend
        strategy, mood = generator._determine_visual_strategy("Steuerfalle")
        assert strategy == "Symbolbild"
        assert "warnend" in mood

    def test_key_message_extraction(self):
        """Key Message wird korrekt extrahiert"""
        generator = CreativeBriefGenerator()

        # Kurzer Text
        short_text = "Kurze Nachricht"
        assert generator._extract_key_message(short_text) == "Kurze Nachricht"

        # Langer Text → Erster Satz
        long_text = "Erster Satz. Zweiter Satz. Dritter Satz."
        message = generator._extract_key_message(long_text)
        assert message == "Erster Satz."

        # Sehr langer Text → Gekürzt
        very_long = "x" * 200
        message = generator._extract_key_message(very_long)
        assert len(message) <= 103  # 100 + "..."


class TestProductionBriefGenerator:
    """Tests für Production Brief Generator"""

    def test_generate_production_brief(self):
        """Production Brief wird korrekt generiert"""
        generator = ProductionBriefGenerator()

        creative_brief = CreativeBrief(
            visual_strategy="Editorial Photography",
            mood="professional, trustworthy",
            key_message="Steuertipp des Tages",
            bildstrategie="Emotion erzeugen",
            suggested_style="Editorial Photography",
            metadata={"theme": "Steuertipp"}
        )

        production_brief = generator.generate(creative_brief, "Content-Text")

        assert isinstance(production_brief, ProductionBrief)
        assert production_brief.prompt != ""
        assert production_brief.aspect_ratio == "1:1"
        assert production_brief.width == 1024
        assert production_brief.height == 1024
        assert production_brief.negative_prompt is not None

    def test_prompt_contains_strategy(self):
        """Prompt enthält visuelle Strategie"""
        generator = ProductionBriefGenerator()

        creative_brief = CreativeBrief(
            visual_strategy="Objektfotografie",
            mood="klar, dringlich",
            key_message="Frist naht",
            bildstrategie="Warnen",
            suggested_style="Objektfotografie"
        )

        production_brief = generator.generate(creative_brief)

        assert "Objektfotografie" in production_brief.prompt
        assert "klar, dringlich" in production_brief.prompt

    def test_negative_prompt_contains_forbidden_elements(self):
        """Negative Prompt enthält verbotene Elemente"""
        generator = ProductionBriefGenerator()

        creative_brief = CreativeBrief(
            visual_strategy="Editorial",
            mood="professional",
            key_message="Test",
            bildstrategie="Test",
            suggested_style="Editorial"
        )

        production_brief = generator.generate(creative_brief)

        negative = production_brief.negative_prompt.lower()
        assert "text" in negative
        assert "logo" in negative
        assert "watermark" in negative


class TestImagePipeline:
    """Tests für die vollständige Pipeline"""

    def test_pipeline_runs_all_stages(self):
        """Pipeline führt alle Stufen aus"""
        pipeline = ImagePipeline()

        content = ContentInput(
            text="Steuererklärung bis 31. Dezember!",
            theme="Frist",
            content_type="deadline"
        )

        result = pipeline.run(content, generate_image=False)

        assert 'content' in result
        assert 'creative_brief' in result
        assert 'production_brief' in result
        assert 'prompt' in result
        assert 'metadata' in result

        # Prüfe dass Stufen verknüpft sind
        assert isinstance(result['creative_brief'], CreativeBrief)
        assert isinstance(result['production_brief'], ProductionBrief)
        assert result['metadata']['stages_completed'] == 2

    def test_pipeline_creative_brief_only(self):
        """Pipeline kann nur Creative Brief generieren"""
        pipeline = ImagePipeline()

        content = ContentInput(
            text="Test text with sufficient length for validation",
            theme="Test",
            content_type="radar"
        )

        brief = pipeline.run_creative_brief(content)

        assert isinstance(brief, CreativeBrief)
        assert brief.visual_strategy != ""

    def test_pipeline_production_brief_only(self):
        """Pipeline kann nur Production Brief generieren"""
        pipeline = ImagePipeline()

        creative_brief = CreativeBrief(
            visual_strategy="Editorial",
            mood="professional",
            key_message="Test",
            bildstrategie="Test",
            suggested_style="Editorial"
        )

        production_brief = pipeline.run_production_brief(creative_brief, "Content")

        assert isinstance(production_brief, ProductionBrief)
        assert production_brief.prompt != ""


class TestConvenienceFunction:
    """Tests für Convenience-Funktion"""

    def test_generate_prompt_for_content(self):
        """generate_prompt_for_content funktioniert"""
        prompt = generate_prompt_for_content(
            text="Steuertipp: Belege sammeln!",
            theme="Finanzwissen",
            content_type="knowledge"
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        # Prompt sollte HILO-Elemente enthalten
        assert "#1a3a6b" in prompt or "Navy" in prompt  # HILO-Farben


class TestPipelineIntegration:
    """Integrations-Tests"""

    def test_full_pipeline_for_different_content_types(self):
        """Pipeline funktioniert für alle Content-Typen"""
        pipeline = ImagePipeline()

        content_types = ['radar', 'deadline', 'knowledge', 'anlass']

        for content_type in content_types:
            content = ContentInput(
                text=f"Test-Text für {content_type}",
                theme="Test",
                content_type=content_type
            )

            result = pipeline.run(content, generate_image=False)

            assert result['prompt'] != ""
            assert result['metadata']['content_type'] == content_type

    def test_pipeline_output_consistency(self):
        """Pipeline liefert konsistente Ergebnisse für gleichen Input"""
        pipeline = ImagePipeline()

        content = ContentInput(
            text="Konsistenz-Test",
            theme="Test",
            content_type="radar"
        )

        result1 = pipeline.run(content, generate_image=False)
        result2 = pipeline.run(content, generate_image=False)

        # Gleicher Input → Gleicher Output
        assert result1['prompt'] == result2['prompt']
        assert result1['creative_brief'].visual_strategy == result2['creative_brief'].visual_strategy


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
