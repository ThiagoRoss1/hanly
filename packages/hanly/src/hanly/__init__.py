"""Hanly engine package."""

from .contracts import (
    BoundingBox,
    DictionaryEntry,
    DictionarySense,
    LexicalCandidate,
    LexicalComponent,
    LookupContext,
    LookupResult,
    LookupStatus,
    MorphologyAnalysis,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ResourceMetadata,
    ResourceStatus,
    ROIImage,
    TargetResolution,
    TextSelection,
    TokenAnalysis,
)
from .errors import HanlyError, ProviderError
from .language_pipeline import LanguagePipeline
from .lookup_pipeline import LookupPipeline
from .providers import DictionaryProvider, MorphologyProvider, OCRProvider

__all__ = [
    "BoundingBox",
    "DictionaryEntry",
    "DictionarySense",
    "DictionaryProvider",
    "HanlyError",
    "LanguagePipeline",
    "LexicalCandidate",
    "LexicalComponent",
    "MorphologyAnalysis",
    "TargetResolution",
    "LookupContext",
    "LookupPipeline",
    "LookupResult",
    "LookupStatus",
    "MorphologyAnalysis",
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
    "TargetResolution",
    "TextSelection",
    "TokenAnalysis",
]
