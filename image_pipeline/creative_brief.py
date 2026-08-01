"""
Creative Brief Generator

Analysiert Content und erstellt einen strategischen Creative Brief.
"""

import logging
from .models import ContentInput, CreativeBrief

logger = logging.getLogger(__name__)


class CreativeBriefGenerator:
    """Generiert Creative Briefs aus Content"""

    # Mapping von Content-Typen zu Bildstrategien
    CONTENT_TYPE_STRATEGIES = {
        'radar': 'Neuigkeit visualisieren',
        'deadline': 'Warnen (ohne Alarm)',
        'knowledge': 'Erklärung visualisieren',
        'anlass': 'Emotion erzeugen',
    }

    # Mapping von Themen zu visuellen Strategien
    THEME_VISUAL_STRATEGIES = {
        'Steuererstattung': ('Editorial Photography', 'hoffnungsvoll, erleichtert'),
        'Steuerfalle': ('Symbolbild', 'warnend, professionell'),
        'Frist': ('Objektfotografie', 'klar, dringlich'),
        'Finanzwissen': ('Illustration', 'freundlich, vertrauenswürdig'),
        'Beratung': ('Editorial Photography', 'empathisch, kompetent'),
    }

    def generate(self, content: ContentInput) -> CreativeBrief:
        """
        Generiert einen Creative Brief aus Content

        Args:
            content: Input-Content

        Returns:
            CreativeBrief mit strategischen Vorgaben
        """
        logger.info(f"Generating creative brief for content type: {content.content_type}")

        # Bildstrategie basierend auf Content-Typ
        bildstrategie = self.CONTENT_TYPE_STRATEGIES.get(
            content.content_type,
            'Emotion erzeugen'
        )

        # Visuelle Strategie und Mood basierend auf Thema
        visual_strategy, mood = self._determine_visual_strategy(content.theme)

        # Key Message extrahieren (vereinfacht)
        key_message = self._extract_key_message(content.text)

        # Stil-Vorschlag
        suggested_style = self._suggest_style(content.content_type, content.theme)

        brief = CreativeBrief(
            visual_strategy=visual_strategy,
            mood=mood,
            key_message=key_message,
            bildstrategie=bildstrategie,
            suggested_style=suggested_style,
            metadata={
                'content_type': content.content_type,
                'theme': content.theme,
            }
        )

        logger.debug(f"Generated brief: strategy={visual_strategy}, mood={mood}")
        return brief

    def _determine_visual_strategy(self, theme: str) -> tuple[str, str]:
        """Bestimmt visuelle Strategie und Mood basierend auf Thema"""
        # Exakte Matches zuerst
        if theme in self.THEME_VISUAL_STRATEGIES:
            return self.THEME_VISUAL_STRATEGIES[theme]

        # Keyword-basierte Fallbacks
        theme_lower = theme.lower()

        if any(kw in theme_lower for kw in ['erstattung', 'rückzahlung', 'geld zurück']):
            return ('Editorial Photography', 'hoffnungsvoll, erleichtert')

        if any(kw in theme_lower for kw in ['falle', 'achtung', 'fehler']):
            return ('Symbolbild', 'warnend, professionell')

        if any(kw in theme_lower for kw in ['frist', 'termin', 'deadline']):
            return ('Objektfotografie', 'klar, dringlich')

        if any(kw in theme_lower for kw in ['wissen', 'ratgeber', 'tipp']):
            return ('Illustration', 'freundlich, vertrauenswürdig')

        # Default
        return ('Editorial Photography', 'professional, trustworthy')

    def _extract_key_message(self, text: str) -> str:
        """Extrahiert die Kernbotschaft aus dem Text (vereinfacht)"""
        text = text.strip()

        # Versuche ersten Satz zu extrahieren
        import re
        sentence_match = re.search(r'^[^.]+\.(?:\s|$)', text)

        if sentence_match:
            sentence = sentence_match.group(0).strip()
            # Verwende ersten Satz wenn er sinnvoll lang ist (10-150 Zeichen)
            if 10 <= len(sentence) <= 150:
                return sentence

        # Text ist kurz genug -> verwende komplett
        if len(text) <= 100:
            return text

        # Fallback: Erste 100 Zeichen
        return text[:100].strip() + '...'

    def _suggest_style(self, content_type: str, theme: str) -> str:
        """Schlägt einen Stil vor basierend auf Content-Typ und Thema"""
        # Priorisierung wie im Masterprompt v3
        if content_type == 'radar':
            return 'Editorial Photography'
        elif content_type == 'deadline':
            return 'Objektfotografie'
        elif content_type == 'knowledge':
            return 'Illustration oder Editorial Photography'
        elif content_type == 'anlass':
            return 'Editorial Photography'
        else:
            return 'Editorial Photography'
