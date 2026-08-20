"""Provider protocols for normalized Hanly engine inputs and outputs."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .contracts import DictionaryEntry, OCRResult, ROIImage, TokenAnalysis


@runtime_checkable
class OCRProvider(Protocol):
    """Recognizes normalized text regions from a normalized ROI image."""

    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        """Return recognized regions in reading order.

        Implementations return results in the reading order their adapter can
        best determine, so callers may rely on sequence order rather than
        re-deriving it. Ordering is the adapter's responsibility; the engine
        performs no line grouping.
        """
        ...


@runtime_checkable
class MorphologyProvider(Protocol):
    """Analyzes Korean text into normalized token information."""

    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        ...


@runtime_checkable
class DictionaryProvider(Protocol):
    """Looks up a normalized lemma and returns dictionary entries."""

    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        ...
