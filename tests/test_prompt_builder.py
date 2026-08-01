"""
Tests für das Prompt-Builder-System
"""

import pytest
from prompt_builder import PromptBuilder, PromptTemplate, build_prompt, list_templates


class TestPromptTemplate:
    """Tests für die PromptTemplate-Klasse"""

    def test_template_creation(self):
        """Template kann erstellt werden"""
        template = PromptTemplate(
            name="test",
            template="Hello {name}!",
            description="Test template"
        )
        assert template.name == "test"
        assert template.template == "Hello {name}!"
        assert template.description == "Test template"

    def test_template_render(self):
        """Template kann gerendert werden"""
        template = PromptTemplate(
            name="test",
            template="Hello {name}, you are {age} years old!",
        )
        result = template.render(name="Alice", age="25")
        assert result == "Hello Alice, you are 25 years old!"

    def test_template_render_missing_param(self):
        """Template wirft Fehler bei fehlendem Parameter"""
        template = PromptTemplate(
            name="test",
            template="Hello {name}!",
        )
        with pytest.raises(ValueError, match="Missing parameter"):
            template.render()


class TestPromptBuilder:
    """Tests für die PromptBuilder-Klasse"""

    def test_builder_initialization(self):
        """Builder wird mit Standard-Templates initialisiert"""
        builder = PromptBuilder()
        templates = builder.list_templates()

        # Prüfe dass Standard-Templates existieren
        assert "hilo_masterprompt_v3" in templates
        assert "hilo_simple" in templates
        assert "deadline_countdown" in templates
        assert "knowledge_series" in templates

    def test_register_template(self):
        """Neue Templates können registriert werden"""
        builder = PromptBuilder()
        builder.register_template(
            name="custom",
            template="Custom {text}",
            description="Custom template"
        )
        assert "custom" in builder.list_templates()

    def test_build_prompt(self):
        """Prompts können gebaut werden"""
        builder = PromptBuilder()
        prompt = builder.build(
            "hilo_simple",
            theme="Steuertipp",
            visual_strategy="Editorial Photography",
            mood="professional, trustworthy",
            content="Wichtiger Steuertipp für Unternehmer"
        )
        assert "Steuertipp" in prompt
        assert "Editorial Photography" in prompt
        assert "professional, trustworthy" in prompt
        assert "Wichtiger Steuertipp für Unternehmer" in prompt

    def test_build_prompt_missing_template(self):
        """Build wirft Fehler bei fehlendem Template"""
        builder = PromptBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.build("nonexistent", foo="bar")

    def test_get_template(self):
        """Templates können abgerufen werden"""
        builder = PromptBuilder()
        template = builder.get_template("hilo_simple")
        assert template is not None
        assert template.name == "hilo_simple"

    def test_get_nonexistent_template(self):
        """Nicht-existierende Templates liefern None"""
        builder = PromptBuilder()
        template = builder.get_template("nonexistent")
        assert template is None


class TestConvenienceFunctions:
    """Tests für die Convenience-Funktionen"""

    def test_build_prompt_function(self):
        """build_prompt() Funktion funktioniert"""
        prompt = build_prompt(
            "deadline_countdown",
            deadline_date="31. Dezember 2026",
            topic="Steuererklärung",
            context="Frist naht"
        )
        assert "31. Dezember 2026" in prompt
        assert "Steuererklärung" in prompt
        assert "Frist naht" in prompt

    def test_list_templates_function(self):
        """list_templates() Funktion funktioniert"""
        templates = list_templates()
        assert isinstance(templates, dict)
        assert len(templates) > 0
        assert "hilo_masterprompt_v3" in templates


class TestHILOMasterpromptV3:
    """Tests für den HILO Masterprompt v3"""

    def test_masterprompt_structure(self):
        """Masterprompt enthält alle wichtigen Elemente"""
        prompt = build_prompt(
            "hilo_masterprompt_v3",
            bildstrategie="Emotion erzeugen",
            thema="Steuererstattung",
            bildart="Editorial Photography",
            newsletter_text="Sie bekommen Geld zurück!"
        )

        # Prüfe Struktur
        assert "Creative Director" in prompt
        assert "SCHRITT 1: BILDSTRATEGIE" in prompt
        assert "SCHRITT 2: BILDART" in prompt
        assert "SCHRITT 3: PRIORITÄTEN" in prompt
        assert "FARBEN" in prompt
        assert "BILDSPRACHE" in prompt
        assert "MENSCHEN" in prompt
        assert "VERMEIDE" in prompt
        assert "FORMAT" in prompt

        # Prüfe Parameter
        assert "Emotion erzeugen" in prompt
        assert "Steuererstattung" in prompt
        assert "Editorial Photography" in prompt
        assert "Sie bekommen Geld zurück!" in prompt

        # Prüfe CI-Farben
        assert "#1a3a6b" in prompt  # Navy
        assert "#4a8c5c" in prompt  # Grün
        assert "#b8c8e8" in prompt  # Lavendel


class TestDeadlineCountdownTemplate:
    """Tests für das Fristen-Countdown-Template"""

    def test_deadline_template(self):
        """Fristen-Template funktioniert"""
        prompt = build_prompt(
            "deadline_countdown",
            deadline_date="31. Mai 2026",
            topic="Umsatzsteuervoranmeldung",
            context="Monatliche Frist"
        )

        assert "31. Mai 2026" in prompt
        assert "Umsatzsteuervoranmeldung" in prompt
        assert "Monatliche Frist" in prompt
        assert "deadline" in prompt.lower() or "frist" in prompt.lower()
        assert "#1a3a6b" in prompt  # Navy
        assert "#4a8c5c" in prompt  # Grün


class TestKnowledgeSeriesTemplate:
    """Tests für das Wissens-Serie-Template"""

    def test_knowledge_template(self):
        """Wissens-Template funktioniert"""
        prompt = build_prompt(
            "knowledge_series",
            topic="Abschreibungen",
            knowledge_level="Einsteiger",
            content="Was sind Abschreibungen und wie funktionieren sie?"
        )

        assert "Abschreibungen" in prompt
        assert "Einsteiger" in prompt
        assert "Was sind Abschreibungen" in prompt
        assert "educational" in prompt.lower() or "wissen" in prompt.lower()


class TestSimpleTemplate:
    """Tests für das Simple-Template"""

    def test_simple_template(self):
        """Simple-Template für schnelle Generierung"""
        prompt = build_prompt(
            "hilo_simple",
            theme="Steuertipp des Tages",
            visual_strategy="Symbolbild",
            mood="freundlich, einladend",
            content="Belege sammeln lohnt sich!"
        )

        assert "Steuertipp des Tages" in prompt
        assert "Symbolbild" in prompt
        assert "freundlich, einladend" in prompt
        assert "Belege sammeln lohnt sich!" in prompt
        assert "HILO" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
