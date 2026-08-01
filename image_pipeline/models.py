"""
Data Models für die Multi-Stage Image Pipeline

Basiert auf ShareNext 2.0 Art Direction Models,
vereinfacht für HILO.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


class ContentType(str, Enum):
    """Gültige Content-Typen"""
    RADAR = 'radar'
    DEADLINE = 'deadline'
    KNOWLEDGE = 'knowledge'
    ANLASS = 'anlass'


# Konstanten für Validierung
MIN_TEXT_LENGTH = 10
MAX_TEXT_LENGTH = 10000
MIN_DIMENSION = 256
MAX_DIMENSION = 2048
VALID_ASPECT_RATIOS = {"1:1", "16:9", "4:3", "3:2", "9:16"}


@dataclass
class ContentInput:
    """Input für die Pipeline: Newsletter-Content"""
    text: str
    theme: str
    content_type: ContentType
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validiere text
        if not self.text or not self.text.strip():
            raise ValueError("text cannot be empty")
        if len(self.text) < MIN_TEXT_LENGTH:
            raise ValueError(f"text must be at least {MIN_TEXT_LENGTH} characters")
        if len(self.text) > MAX_TEXT_LENGTH:
            raise ValueError(f"text exceeds maximum length of {MAX_TEXT_LENGTH} characters")

        # Validiere theme
        if not self.theme or not self.theme.strip():
            raise ValueError("theme cannot be empty")
        if len(self.theme) > 200:
            raise ValueError("theme exceeds maximum length of 200 characters")

        # Konvertiere content_type zu Enum falls String
        if isinstance(self.content_type, str):
            try:
                self.content_type = ContentType(self.content_type)
            except ValueError:
                raise ValueError(f"Invalid content_type: {self.content_type}. Must be one of: {[t.value for t in ContentType]}")


@dataclass
class CreativeBrief:
    """Creative Brief: Strategische Bildidee"""
    visual_strategy: str  # z.B. "Editorial Photography", "Symbolbild"
    mood: str  # z.B. "professional, trustworthy"
    key_message: str
    bildstrategie: str  # "Emotion erzeugen", "Warnen", "Symbol verwenden", etc.
    suggested_style: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductionBrief:
    """Production Brief: Technische Spezifikation"""
    prompt: str
    negative_prompt: Optional[str] = None
    aspect_ratio: str = "1:1"
    width: int = 1024
    height: int = 1024
    style_parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validiere prompt
        if not self.prompt or not self.prompt.strip():
            raise ValueError("prompt cannot be empty")
        if len(self.prompt) > 50000:
            raise ValueError("prompt exceeds maximum length")

        # Validiere aspect_ratio
        if self.aspect_ratio not in VALID_ASPECT_RATIOS:
            raise ValueError(f"Invalid aspect_ratio: {self.aspect_ratio}. Must be one of: {VALID_ASPECT_RATIOS}")

        # Validiere dimensions
        if not (MIN_DIMENSION <= self.width <= MAX_DIMENSION):
            raise ValueError(f"width must be between {MIN_DIMENSION} and {MAX_DIMENSION}")
        if not (MIN_DIMENSION <= self.height <= MAX_DIMENSION):
            raise ValueError(f"height must be between {MIN_DIMENSION} and {MAX_DIMENSION}")


@dataclass
class ImageAsset:
    """Finales Bild-Asset"""
    image_path: str
    prompt_used: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    creative_brief: Optional[CreativeBrief] = None
    production_brief: Optional[ProductionBrief] = None
