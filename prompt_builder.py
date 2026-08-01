"""
Prompt-Builder-System für HILO-Social-Pilot

Basiert auf ShareNext 2.0 Prompt-Builder-Architektur,
vereinfacht für HILO-Bedürfnisse.

Kernfunktion:
- Template-basierte Prompt-Generierung
- Parameter-Extraktion aus Content
- Konsistente Bild-Qualität durch wiederverwendbare Templates
"""

import re
import logging
import threading
from typing import Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptTemplate:
    """Ein wiederverwendbares Prompt-Template"""

    def __init__(self, name: str, template: str, description: str = ""):
        self.name = name
        self.template = template
        self.description = description

    def _sanitize_content(self, content: str, max_length: int = 10000) -> str:
        """Sanitisiert User-Input für AI-Prompts"""
        if not content:
            return ""

        # Längen-Limit
        content = content[:max_length]

        # Entferne potenzielle Prompt-Injection-Marker
        dangerous_patterns = [
            r'IGNORE\s+ALL\s+PREVIOUS\s+INSTRUCTIONS',
            r'SYSTEM\s*:',
            r'ASSISTANT\s*:',
            r'USER\s*:',
        ]

        for pattern in dangerous_patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)

        # Normalisiere Whitespace
        content = re.sub(r'\s+', ' ', content).strip()

        return content

    def render(self, **params: Any) -> str:
        """Rendert das Template mit den gegebenen Parametern (mit Security-Validierung)"""
        # Validate parameter values - keine special format strings erlaubt
        forbidden_pattern = re.compile(r'\{[_\w]+\}')
        sanitized_params = {}

        for key, value in params.items():
            if value is None:
                raise ValueError(f"Parameter '{key}' cannot be None")

            if isinstance(value, str):
                # Check for format string injection
                if forbidden_pattern.search(value):
                    raise ValueError(
                        f"Parameter '{key}' contains forbidden format string syntax"
                    )
                # Sanitize content
                sanitized_params[key] = self._sanitize_content(value)
            else:
                sanitized_params[key] = value

        try:
            return self.template.format(**sanitized_params)
        except KeyError as e:
            raise ValueError(f"Missing parameter {e} for template '{self.name}'")


class PromptBuilder:
    """Haupt-Builder für Bild-Prompts (thread-safe)"""

    def __init__(self):
        self.templates: Dict[str, PromptTemplate] = {}
        self._lock = threading.RLock()
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
        """Registriert ein neues Template (thread-safe)"""
        with self._lock:
            self.templates[name] = PromptTemplate(name, template, description)
            logger.debug(f"Registered template '{name}'")

    def build(self, template_name: str, **params) -> str:
        """Baut einen Prompt aus einem Template (thread-safe mit Validierung)"""
        logger.info(f"Building prompt with template '{template_name}'")
        logger.debug(f"Parameters: {list(params.keys())}")

        # Validate all parameters
        for key, value in params.items():
            if value is None:
                raise ValueError(f"Parameter '{key}' cannot be None")
            if isinstance(value, str):
                if not value.strip():
                    raise ValueError(f"Parameter '{key}' cannot be empty")
                if len(value) > 50000:
                    raise ValueError(f"Parameter '{key}' exceeds maximum length (50000 chars)")

        with self._lock:
            if template_name not in self.templates:
                raise ValueError(f"Template '{template_name}' not found")

            template = self.templates[template_name]

        # Render outside lock (doesn't modify state)
        prompt = template.render(**params)
        logger.debug(f"Generated prompt length: {len(prompt)} chars")
        return prompt

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
