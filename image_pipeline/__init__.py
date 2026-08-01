"""
Multi-Stage Image Generation Pipeline

Basiert auf ShareNext 2.0 Art Direction System,
vereinfacht für HILO-Bedürfnisse.

Workflow:
    Content → Creative Brief → Production Brief → Asset

Nutzung:
    from image_pipeline import ImagePipeline, ContentInput

    pipeline = ImagePipeline()
    content = ContentInput(
        text="Ihre Steuererklärung...",
        theme="Steuererstattung",
        content_type="radar"
    )

    result = pipeline.run(content)
    prompt = result['prompt']
"""

from .models import ContentInput, CreativeBrief, ProductionBrief, ImageAsset
from .creative_brief import CreativeBriefGenerator
from .production_brief import ProductionBriefGenerator
from .pipeline import ImagePipeline, generate_prompt_for_content

__all__ = [
    'ContentInput',
    'CreativeBrief',
    'ProductionBrief',
    'ImageAsset',
    'CreativeBriefGenerator',
    'ProductionBriefGenerator',
    'ImagePipeline',
    'generate_prompt_for_content',
]
