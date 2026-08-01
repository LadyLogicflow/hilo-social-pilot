"""
Prompt-Builder-System für HILO-Social-Pilot

Basiert auf ShareNext 2.0 Prompt-Builder-Architektur,
vereinfacht für HILO-Bedürfnisse.

Kernfunktion:
- Template-basierte Prompt-Generierung
- Parameter-Extraktion aus Content
- Konsistente Bild-Qualität durch wiederverwendbare Templates
"""

from typing import Dict, Optional
from pathlib import Path


class PromptTemplate:
    """Ein wiederverwendbares Prompt-Template"""

    def __init__(self, name: str, template: str, description: str = ""):
        self.name = name
        self.template = template
        self.description = description

    def render(self, **params: str) -> str:
        """Rendert das Template mit den gegebenen Parametern"""
        try:
            return self.template.format(**params)
        except KeyError as e:
            raise ValueError(f"Missing parameter {e} for template '{self.name}'")


class PromptBuilder:
    """Haupt-Builder für Bild-Prompts"""

    def __init__(self):
        self.templates: Dict[str, PromptTemplate] = {}
        self._load_default_templates()

    def _load_default_templates(self):
        """Lädt die Standard-Templates"""

        # HILO Masterprompt v3 als Template
        self.register_template(
            name="hilo_masterprompt_v3",
            template="""Du bist gleichzeitig Creative Director, Art Director und Editorial Photographer für HILO.

Deine Aufgabe: Entwickle aus dem Newslettertext ein Bild, das wie ein Titelbild eines hochwertigen Wirtschafts- oder Verbrauchermagazins wirkt.

SCHRITT 1: BILDSTRATEGIE WÄHLEN

Analysiere den Text und wähle ZUERST die Bildstrategie:
{bildstrategie}

SCHRITT 2: BILDART NACH THEMA WÄHLEN

Thema: {thema}
Empfohlene Bildart: {bildart}

WICHTIG: Infografiken dürfen AUSSCHLIESSLICH verwendet werden, wenn Informationen oder Prozesse besser verständlich werden als durch ein fotografisches oder illustratives Motiv.

SCHRITT 3: PRIORITÄTEN

Bildarten nach Priorität (höchste zuerst):
1. Editorial Photography
2. Konzeptfotografie
3. Symbolbild
4. Stillleben
5. Objektfotografie
6. Illustration
7. Comic (Ligne-Claire)
8. Papiercollage
9. **Infografik** (LETZTE WAHL)

FARBEN

Nutze die HILO-CI ausschließlich als dezente Akzente:
- #1a3a6b (Navy)
- #4a8c5c (Grün)
- #b8c8e8 (Lavendel)
- Weiß

BILDSPRACHE

modern, hochwertig, vertrauenswürdig, authentisch, professionell, emotional passend, ruhige Komposition, klare Blickführung

MENSCHEN

Verwende Menschen nur, wenn sie die Aussage verbessern.
Keine gestellten Businessposen, keine Daumen-hoch-Gesten, keine übertriebenen Emotionen.

VERMEIDE

Stockfoto-Look, Geldregen, riesige Eurozeichen, überladene Szenen, Logos, QR-Codes, Wasserzeichen, Text im Bild

FORMAT

Quadratisch. 1:1. Ultra High Quality.

TEXT

{newsletter_text}""",
            description="HILO Masterprompt v3 - Bildstrategie-basierter Ansatz"
        )

        # Vereinfachtes Template für schnelle Generierung
        self.register_template(
            name="hilo_simple",
            template="""Create a premium editorial photograph for a social media post.

THEME: {theme}
VISUAL STRATEGY: {visual_strategy}
MOOD: {mood}

STYLE:
- Modern, professional, trustworthy
- Editorial photography quality
- Clean composition

COLORS:
Use HILO brand colors as subtle accents:
- Navy (#1a3a6b)
- Green (#4a8c5c)
- Lavender (#b8c8e8)

AVOID:
- Stock photo look
- Text in image
- Logos, QR codes
- Overloaded scenes

FORMAT: Square 1:1, ultra high quality

CONTENT:
{content}""",
            description="Vereinfachtes Template für schnelle Generierung"
        )

        # Template für Fristen-Countdown
        self.register_template(
            name="deadline_countdown",
            template="""Create a premium editorial photograph showing a deadline or time-sensitive situation.

DEADLINE: {deadline_date}
TOPIC: {topic}

VISUAL APPROACH:
- Object photography or editorial photography
- Convey urgency without being alarmist
- Professional and trustworthy tone

SUGGESTED OBJECTS:
- Calendar, clock, or time-related objects
- Clean, minimalist composition
- Natural lighting

COLORS:
- Navy (#1a3a6b) and Green (#4a8c5c) as accents
- Professional color palette

AVOID:
- Red warning colors (use navy/green instead)
- Stress-inducing imagery
- Text in image

FORMAT: Square 1:1, ultra high quality

CONTEXT:
{context}""",
            description="Template für Fristen-Countdown-Posts"
        )

        # Template für Wissens-Serie
        self.register_template(
            name="knowledge_series",
            template="""Create a premium editorial photograph for an educational finance topic.

TOPIC: {topic}
KNOWLEDGE LEVEL: {knowledge_level}

VISUAL APPROACH:
- Editorial photography or illustration
- Convey expertise and trust
- Clear, approachable style

MOOD:
- Professional but friendly
- Encouraging learning
- Building confidence

COLORS:
- Navy (#1a3a6b), Green (#4a8c5c), Lavender (#b8c8e8)
- High contrast for clarity

COMPOSITION:
- Clean, focused
- Single clear subject
- Negative space for text overlay later

AVOID:
- Overly complex scenes
- Confusing metaphors
- Text in image

FORMAT: Square 1:1, ultra high quality

CONTENT:
{content}""",
            description="Template für Wissens-Serie-Posts"
        )

    def register_template(self, name: str, template: str, description: str = ""):
        """Registriert ein neues Template"""
        self.templates[name] = PromptTemplate(name, template, description)

    def build(self, template_name: str, **params) -> str:
        """Baut einen Prompt aus einem Template"""
        if template_name not in self.templates:
            raise ValueError(f"Template '{template_name}' not found")

        template = self.templates[template_name]
        return template.render(**params)

    def list_templates(self) -> Dict[str, str]:
        """Listet alle verfügbaren Templates"""
        return {
            name: template.description
            for name, template in self.templates.items()
        }

    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """Holt ein spezifisches Template"""
        return self.templates.get(name)


# Singleton-Instanz für einfache Nutzung
_builder = PromptBuilder()


def build_prompt(template_name: str, **params) -> str:
    """Convenience-Funktion zum Prompt-Building"""
    return _builder.build(template_name, **params)


def list_templates() -> Dict[str, str]:
    """Convenience-Funktion zum Template-Listing"""
    return _builder.list_templates()


# Beispiel-Nutzung
if __name__ == "__main__":
    # Liste alle Templates
    print("Verfügbare Templates:")
    for name, desc in list_templates().items():
        print(f"  - {name}: {desc}")

    # Beispiel: Fristen-Countdown
    prompt = build_prompt(
        "deadline_countdown",
        deadline_date="31. Dezember 2026",
        topic="Steuererklärung",
        context="Frist für die Abgabe der Steuererklärung 2025 naht"
    )
    print("\n" + "="*80)
    print("Beispiel-Prompt (Deadline):")
    print("="*80)
    print(prompt)
