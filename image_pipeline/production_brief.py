"""
Production Brief Generator

Konvertiert Creative Brief in technische Produktionsspezifikation.
"""

import logging
import re
from .models import CreativeBrief, ProductionBrief

logger = logging.getLogger(__name__)

# Optional: Import prompt_builder if available (wird in Integration-Phase verbunden)
try:
    from prompt_builder import build_prompt
    HAS_PROMPT_BUILDER = True
except ImportError:
    HAS_PROMPT_BUILDER = False
    logger.info("prompt_builder not available, using fallback prompts")


class ProductionBriefGenerator:
    """Generiert Production Briefs aus Creative Briefs"""

    @staticmethod
    def _sanitize_for_prompt(text: str, max_length: int = 500) -> str:
        """
        Sanitisiert Text für sichere Verwendung in AI-Prompts

        Args:
            text: Zu sanitisierender Text
            max_length: Maximale Länge

        Returns:
            Sicherer Text ohne Injection-Risiken
        """
        if not text:
            return ""

        # Entferne Control-Characters
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)

        # Verhindere Prompt-Breaking durch doppelte Newlines
        text = text.replace('\n\n', ' ')

        # Entferne potenzielle Injection-Patterns
        injection_patterns = [
            r'IGNORE\s+(?:ALL\s+)?PREVIOUS\s+INSTRUCTIONS',
            r'SYSTEM\s*:',
            r'ASSISTANT\s*:',
            r'USER\s*:',
        ]
        for pattern in injection_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # Limitiere Länge
        text = text[:max_length]

        return text.strip()

    def generate(self, creative_brief: CreativeBrief, content_text: str = "") -> ProductionBrief:
        """
        Generiert einen Production Brief aus einem Creative Brief

        Args:
            creative_brief: Strategischer Creative Brief
            content_text: Original-Content-Text

        Returns:
            ProductionBrief mit technischen Spezifikationen
        """
        logger.info(f"Generating production brief with strategy: {creative_brief.visual_strategy}")

        # Baue Prompt mit dem Prompt-Builder-System
        prompt = self._build_prompt(creative_brief, content_text)

        # Negative Prompt (was vermieden werden soll)
        negative_prompt = self._build_negative_prompt()

        # Stil-Parameter
        style_parameters = {
            'visual_strategy': creative_brief.visual_strategy,
            'mood': creative_brief.mood,
            'bildstrategie': creative_brief.bildstrategie,
        }

        brief = ProductionBrief(
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect_ratio="1:1",
            width=1024,
            height=1024,
            style_parameters=style_parameters,
            metadata=creative_brief.metadata
        )

        logger.debug(f"Generated production brief, prompt length: {len(prompt)} chars")
        return brief

    def _build_prompt(self, brief: CreativeBrief, content_text: str) -> str:
        """Baut den finalen AI-Prompt"""
        # Nutze das Prompt-Builder-System für konsistente Prompts (wenn verfügbar)
        if HAS_PROMPT_BUILDER:
            try:
                # Verwende hilo_simple Template
                prompt = build_prompt(
                    "hilo_simple",
                    theme=brief.metadata.get('theme', 'Steuertipp'),
                    visual_strategy=brief.visual_strategy,
                    mood=brief.mood,
                    content=brief.key_message or content_text[:200]
                )
                return prompt

            except Exception as e:
                logger.warning(f"Prompt-Builder failed, using fallback: {e}")

        # Fallback: Manueller Prompt
        return self._fallback_prompt(brief, content_text)

    def _fallback_prompt(self, brief: CreativeBrief, content_text: str) -> str:
        """Fallback-Prompt wenn Prompt-Builder nicht funktioniert"""
        # Sanitize alle User-Inputs
        safe_strategy = self._sanitize_for_prompt(brief.visual_strategy, 100)
        safe_mood = self._sanitize_for_prompt(brief.mood, 100)
        safe_message = self._sanitize_for_prompt(brief.key_message, 200)

        return f"""Create a premium editorial photograph for a social media post.

VISUAL STRATEGY: {safe_strategy}
MOOD: {safe_mood}
KEY MESSAGE: {safe_message}

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

FORMAT: Square 1:1, ultra high quality"""

    def _build_negative_prompt(self) -> str:
        """Baut den Negative Prompt (was vermieden werden soll)"""
        return "stock photo, text in image, logos, watermarks, qr codes, overloaded scenes, cliches, calculators, folders, handshakes"
