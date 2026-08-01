"""
ShareNext-Features Integration für HILO-Social-Pilot

Integration von:
1. Prompt-Builder-System (Template-basierte Prompts)
2. Multi-Stage Pipeline (Content → Creative Brief → Production Brief → Asset)

Verwendung:
    from sharenext_integration import generate_optimized_image_prompt

    # Einfache Nutzung
    prompt = generate_optimized_image_prompt(
        text="Steuererklärung bis 31. Dezember!",
        theme="Frist",
        content_type="deadline"
    )

    # Erweiterte Nutzung mit Pipeline
    result = generate_with_pipeline(...)
"""

import logging
from typing import Dict, Any, Optional
from image_pipeline import ImagePipeline, ContentInput, ContentType
from prompt_builder import build_prompt

logger = logging.getLogger(__name__)


def generate_optimized_image_prompt(
    text: str,
    theme: str,
    content_type: str = 'radar',
    use_pipeline: bool = True
) -> str:
    """
    Generiert einen optimierten Prompt für Bild-Generierung

    Kombiniert Prompt-Builder-System mit Multi-Stage Pipeline
    für beste Qualität.

    Args:
        text: Content-Text (Newsletter-Text)
        theme: Thema des Posts
        content_type: 'radar', 'deadline', 'knowledge', 'anlass'
        use_pipeline: Wenn True, nutze Multi-Stage Pipeline (empfohlen)

    Returns:
        Optimierter Prompt-String

    Raises:
        ValueError: Bei ungültigen Inputs
    """
    logger.info(f"Generating optimized prompt for theme='{theme}', type='{content_type}'")

    if use_pipeline:
        # Nutze Multi-Stage Pipeline für strategische Optimierung
        return _generate_with_pipeline(text, theme, content_type)
    else:
        # Direkter Prompt-Builder (schneller, aber weniger strategisch)
        return _generate_with_prompt_builder(text, theme, content_type)


def _generate_with_pipeline(text: str, theme: str, content_type: str) -> str:
    """Generiert Prompt mit Multi-Stage Pipeline"""
    pipeline = ImagePipeline()

    # Erstelle Content-Input
    content = ContentInput(
        text=text,
        theme=theme,
        content_type=ContentType(content_type)
    )

    # Führe Pipeline aus
    result = pipeline.run(content, generate_image=False)

    logger.info(
        f"Pipeline complete: {result['metadata']['visual_strategy']} "
        f"({len(result['prompt'])} chars)"
    )

    return result['prompt']


def _generate_with_prompt_builder(text: str, theme: str, content_type: str) -> str:
    """Generiert Prompt direkt mit Prompt-Builder"""
    # Mappe content_type zu passenden Template-Parametern
    if content_type == 'deadline':
        visual_strategy = 'Objektfotografie'
        mood = 'klar, dringlich'
    elif content_type == 'knowledge':
        visual_strategy = 'Illustration oder Editorial Photography'
        mood = 'freundlich, vertrauenswürdig'
    elif content_type == 'anlass':
        visual_strategy = 'Editorial Photography'
        mood = 'emotional, ansprechend'
    else:  # radar
        visual_strategy = 'Editorial Photography'
        mood = 'professional, trustworthy'

    # Nutze hilo_simple Template
    prompt = build_prompt(
        "hilo_simple",
        theme=theme,
        visual_strategy=visual_strategy,
        mood=mood,
        content=text[:200]  # Erste 200 Zeichen
    )

    return prompt


def generate_with_pipeline(
    text: str,
    theme: str,
    content_type: str = 'radar'
) -> Dict[str, Any]:
    """
    Generiert vollständige Pipeline-Ergebnisse

    Returns:
        dict mit:
            - content: ContentInput
            - creative_brief: CreativeBrief
            - production_brief: ProductionBrief
            - prompt: Finaler Prompt
            - metadata: Pipeline-Metadata
    """
    pipeline = ImagePipeline()

    content = ContentInput(
        text=text,
        theme=theme,
        content_type=ContentType(content_type)
    )

    result = pipeline.run(content, generate_image=False)

    logger.info(f"Full pipeline result: {result['metadata']}")

    return result


# Convenience-Funktionen für spezifische Content-Typen

def generate_deadline_prompt(text: str, deadline_date: str, topic: str) -> str:
    """Generiert Prompt für Fristen-Countdown-Posts"""
    try:
        # Versuche deadline_countdown Template
        return build_prompt(
            "deadline_countdown",
            deadline_date=deadline_date,
            topic=topic,
            context=text[:300]
        )
    except Exception as e:
        logger.warning(f"deadline_countdown template failed, using pipeline: {e}")
        # Fallback auf Pipeline
        return generate_optimized_image_prompt(
            text=f"{topic}: {deadline_date}. {text}",
            theme=topic,
            content_type='deadline'
        )


def generate_knowledge_prompt(text: str, topic: str, knowledge_level: str = 'Einsteiger') -> str:
    """Generiert Prompt für Wissens-Serie-Posts"""
    try:
        # Versuche knowledge_series Template
        return build_prompt(
            "knowledge_series",
            topic=topic,
            knowledge_level=knowledge_level,
            content=text[:300]
        )
    except Exception as e:
        logger.warning(f"knowledge_series template failed, using pipeline: {e}")
        # Fallback auf Pipeline
        return generate_optimized_image_prompt(
            text=text,
            theme=topic,
            content_type='knowledge'
        )


# Beispiel-Nutzung
if __name__ == "__main__":
    # Einfaches Beispiel
    prompt = generate_optimized_image_prompt(
        text="Die Frist für Ihre Steuererklärung 2025 endet am 31. Dezember 2026. Jetzt handeln!",
        theme="Steuererklärung",
        content_type="deadline"
    )
    print("="*80)
    print("GENERIERTER PROMPT:")
    print("="*80)
    print(prompt)
    print("="*80)

    # Erweiterte Nutzung
    result = generate_with_pipeline(
        text="Was sind Abschreibungen und wie funktionieren sie?",
        theme="Finanzwissen",
        content_type="knowledge"
    )
    print("\nPIPELINE-ERGEBNIS:")
    print(f"Visual Strategy: {result['creative_brief'].visual_strategy}")
    print(f"Mood: {result['creative_brief'].mood}")
    print(f"Prompt Länge: {len(result['prompt'])} Zeichen")
