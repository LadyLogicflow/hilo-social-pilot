"""
Multi-Stage Image Generation Pipeline

Orchestriert den Workflow: Content → Creative Brief → Production Brief → Asset
"""

import logging
from typing import Optional
from .models import ContentInput, CreativeBrief, ProductionBrief, ImageAsset
from .creative_brief import CreativeBriefGenerator
from .production_brief import ProductionBriefGenerator

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception für Pipeline-Fehler"""
    pass


class CreativeBriefError(PipelineError):
    """Fehler beim Creative Brief Generation"""
    pass


class ProductionBriefError(PipelineError):
    """Fehler beim Production Brief Generation"""
    pass


class AssetGenerationError(PipelineError):
    """Fehler bei Asset-Generierung"""
    pass


class ImagePipeline:
    """
    Multi-Stage Pipeline für Bild-Generierung

    Workflow:
    1. Content → Creative Brief (Strategie)
    2. Creative Brief → Production Brief (Technische Specs)
    3. Production Brief → Image Asset (Finale Generierung)
    """

    def __init__(self):
        self.creative_generator = CreativeBriefGenerator()
        self.production_generator = ProductionBriefGenerator()

    def run(self, content: ContentInput, generate_image: bool = False) -> dict:
        """
        Führt die vollständige Pipeline aus

        Args:
            content: Input-Content
            generate_image: Wenn True, generiert tatsächlich ein Bild (erfordert API-Integration)

        Returns:
            dict mit allen Pipeline-Stufen

        Raises:
            CreativeBriefError: Fehler bei Creative Brief Generation
            ProductionBriefError: Fehler bei Production Brief Generation
            AssetGenerationError: Fehler bei Asset-Generierung
        """
        logger.info(f"Starting pipeline for content type: {content.content_type}")

        # Stage 1: Creative Brief
        try:
            creative_brief = self.creative_generator.generate(content)
            logger.info(f"Stage 1 complete: Creative Brief → {creative_brief.visual_strategy}")
        except Exception as e:
            logger.error(f"Stage 1 failed: {e}", exc_info=True)
            raise CreativeBriefError(f"Creative brief generation failed: {e}") from e

        # Stage 2: Production Brief
        try:
            production_brief = self.production_generator.generate(creative_brief, content.text)
            logger.info(f"Stage 2 complete: Production Brief → {len(production_brief.prompt)} chars")
        except Exception as e:
            logger.error(f"Stage 2 failed: {e}", exc_info=True)
            raise ProductionBriefError(f"Production brief generation failed: {e}") from e

        # Stage 3: Asset Generation (optional)
        asset = None
        if generate_image:
            try:
                # Hier würde die tatsächliche Bild-Generierung stattfinden
                # Integration mit bildmotiv.py oder OpenAI/Ideogram direkt
                logger.warning("Image generation not implemented yet (requires API integration)")
                asset = None
            except Exception as e:
                logger.error(f"Stage 3 failed: {e}", exc_info=True)
                raise AssetGenerationError(f"Asset generation failed: {e}") from e
        else:
            logger.info("Stage 3 skipped: generate_image=False")

        # Pipeline-Ergebnis
        result = {
            'content': content,
            'creative_brief': creative_brief,
            'production_brief': production_brief,
            'asset': asset,
            'prompt': production_brief.prompt,
            'metadata': {
                'stages_completed': 2 if not generate_image else 3,
                'content_type': content.content_type.value if hasattr(content.content_type, 'value') else content.content_type,
                'visual_strategy': creative_brief.visual_strategy,
            }
        }

        logger.info("Pipeline complete")
        return result

    def run_creative_brief(self, content: ContentInput) -> CreativeBrief:
        """Führt nur Stage 1 aus: Content → Creative Brief"""
        return self.creative_generator.generate(content)

    def run_production_brief(self, creative_brief: CreativeBrief, content_text: str = "") -> ProductionBrief:
        """Führt nur Stage 2 aus: Creative Brief → Production Brief"""
        return self.production_generator.generate(creative_brief, content_text)


# Convenience-Funktion
def generate_prompt_for_content(text: str, theme: str, content_type: str = 'radar') -> str:
    """
    Convenience-Funktion: Generiert einen optimierten Prompt für Content

    Args:
        text: Content-Text
        theme: Thema
        content_type: 'radar', 'deadline', 'knowledge', 'anlass'

    Returns:
        Optimierter Prompt-String
    """
    pipeline = ImagePipeline()

    content = ContentInput(
        text=text,
        theme=theme,
        content_type=content_type
    )

    result = pipeline.run(content, generate_image=False)
    return result['prompt']
