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

# Named constants für Konsistenz
MAX_CONTENT_LENGTH_SIMPLE = 200  # Für hilo_simple Template
MAX_CONTEXT_LENGTH_TEMPLATES = 300  # Für spezifische Templates


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
        ValueError: Bei ungültigen Inputs (text zu kurz, theme leer, ungültiger content_type)
    """
    # Validate inputs at integration boundary
    if not text or len(text.strip()) < 10:
        raise ValueError("text must be at least 10 characters")

    if not theme or len(theme.strip()) == 0:
        raise ValueError("theme cannot be empty")

    # Validate content_type
    try:
        ContentType(content_type)
    except ValueError:
        valid_types = [t.value for t in ContentType]
        raise ValueError(
            f"Invalid content_type '{content_type}'. "
            f"Must be one of: {valid_types}"
        )

    logger.info(
        f"Generating optimized prompt: theme='{theme}', type='{content_type}', "
        f"use_pipeline={use_pipeline}, text_length={len(text)}"
    )

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
    # Validate content_type explicitly (defensive)
    valid_types = {'deadline', 'knowledge', 'anlass', 'radar'}
    if content_type not in valid_types:
        raise ValueError(f"Invalid content_type: {content_type}")

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
    else:  # radar (only valid option left after validation)
        visual_strategy = 'Editorial Photography'
        mood = 'professional, trustworthy'

    # Nutze hilo_simple Template
    prompt = build_prompt(
        "hilo_simple",
        theme=theme,
        visual_strategy=visual_strategy,
        mood=mood,
        content=text[:MAX_CONTENT_LENGTH_SIMPLE]
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
            context=text[:MAX_CONTEXT_LENGTH_TEMPLATES]
        )
    except KeyError as e:
        # Template parameter fehlt - legitimer Fallback
        logger.warning(f"deadline_countdown template parameter missing, using pipeline: {e}")
        return generate_optimized_image_prompt(
            text=f"{topic}: {deadline_date}. {text}",
            theme=topic,
            content_type='deadline'
        )
    except ValueError as e:
        # Ungültige Parameter - Fehler durchreichen
        logger.error(f"Invalid deadline_prompt parameters: {e}")
        raise ValueError(f"Invalid deadline_prompt parameters: {e}") from e


def generate_knowledge_prompt(text: str, topic: str, knowledge_level: str = 'Einsteiger') -> str:
    """Generiert Prompt für Wissens-Serie-Posts"""
    try:
        # Versuche knowledge_series Template
        return build_prompt(
            "knowledge_series",
            topic=topic,
            knowledge_level=knowledge_level,
            content=text[:MAX_CONTEXT_LENGTH_TEMPLATES]
        )
    except KeyError as e:
        # Template parameter fehlt - legitimer Fallback
        logger.warning(f"knowledge_series template parameter missing, using pipeline: {e}")
        return generate_optimized_image_prompt(
            text=text,
            theme=topic,
            content_type='knowledge'
        )
    except ValueError as e:
        # Ungültige Parameter - Fehler durchreichen
        logger.error(f"Invalid knowledge_prompt parameters: {e}")
        raise ValueError(f"Invalid knowledge_prompt parameters: {e}") from e


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
