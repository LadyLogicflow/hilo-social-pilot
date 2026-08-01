"""
Data Models für die Multi-Stage Image Pipeline

Basiert auf ShareNext 2.0 Art Direction Models,
vereinfacht für HILO.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class ContentInput:
    """Input für die Pipeline: Newsletter-Content"""
    text: str
    theme: str
    content_type: str  # 'radar', 'deadline', 'knowledge', 'anlass'
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class CreativeBrief:
    """Creative Brief: Strategische Bildidee"""
    visual_strategy: str  # z.B. "Editorial Photography", "Symbolbild"
    mood: str  # z.B. "professional, trustworthy"
    key_message: str
    bildstrategie: str  # "Emotion erzeugen", "Warnen", "Symbol verwenden", etc.
    suggested_style: str
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ProductionBrief:
    """Production Brief: Technische Spezifikation"""
    prompt: str
    negative_prompt: Optional[str] = None
    aspect_ratio: str = "1:1"
    width: int = 1024
    height: int = 1024
    style_parameters: Dict[str, Any] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.style_parameters is None:
            self.style_parameters = {}
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ImageAsset:
    """Finales Bild-Asset"""
    image_path: str
    prompt_used: str
    metadata: Dict[str, Any] = None
    creative_brief: Optional[CreativeBrief] = None
    production_brief: Optional[ProductionBrief] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
