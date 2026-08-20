"""Hanly engine package."""

from .contracts import (
    BoundingBox,
    DictionaryEntry,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ResourceMetadata,
    ResourceStatus,
    ROIImage,
    TokenAnalysis,
)
from .errors import HanlyError, ProviderError
from .providers import DictionaryProvider, MorphologyProvider, OCRProvider

__all__ = [
    "BoundingBox",
    "DictionaryEntry",
    "DictionaryProvider",
    "HanlyError",
    "LookupContext",
    "LookupResult",
    "LookupStatus",
    "MorphologyProvider",
    "OCRProvider",
    "OCRResult",
    "PixelFormat",
    "Point",
    "ProviderError",
    "Quad",
    "ROIImage",
    "ResourceMetadata",
    "ResourceStatus",
    "TokenAnalysis",
]
