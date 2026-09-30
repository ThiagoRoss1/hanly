"""Adapt local macOS Vision OCR without model downloads or cross-platform imports.

Load pyobjc lazily on Darwin. Convert normalized bottom-left coordinates into
top-left pixels and keep Objective-C objects behind the provider seam.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from .contracts import OCRResult, PixelFormat, Point, Quad, ROIImage
from .errors import ProviderError

_VISION_FRAMEWORK = "/System/Library/Frameworks/Vision.framework"

#: Vision's ``VNRequestTextRecognitionLevel``. Korean exists only at the
#: accurate level; the fast level supports six Latin-script languages.
_LEVEL_ACCURATE = 0

#: How much larger the image handed to Vision is than the ROI captured. At the
#: UI text sizes Hanly hovers over, Vision silently returns nothing for whole
#: lines at 1x; doubling recovers them. See :func:`_png_bytes`.
DEFAULT_INPUT_SCALE = 2

#: Ceiling on that enlargement. Scale grows the decoded image quadratically, so
#: an unbounded value turns a configuration slip into an allocation the machine
#: cannot satisfy. Nothing above this has ever measured better than 2x.
MAX_INPUT_SCALE = 8

_PIXEL_MODES = {
    PixelFormat.GRAYSCALE_8: "L",
    PixelFormat.RGB_888: "RGB",
    PixelFormat.BGR_888: "BGR",
    PixelFormat.RGBA_8888: "RGBA",
}


class VisionProviderError(ProviderError):
    """Raised when Vision is unavailable or returns something unusable."""


@dataclass(frozen=True)
class VisionConfig:
    """Configure Vision's text correction and presentation-only input scaling.

    Language correction may alter damaged or real words, a measurable dictionary
    tradeoff. ``input_scale`` enlarges the PNG, not captured/result geometry.
    """

    languages: tuple[str, ...] = ("ko-KR",)
    language_correction: bool = False
    minimum_text_height: float = 0.0
    input_scale: int = DEFAULT_INPUT_SCALE

    def __post_init__(self) -> None:
        if isinstance(self.input_scale, bool) or not isinstance(self.input_scale, int):
            raise ValueError("input_scale must be an integer")
        if not 1 <= self.input_scale <= MAX_INPUT_SCALE:
            raise ValueError(
                f"input_scale must be between 1 and {MAX_INPUT_SCALE}"
            )


class VisionProvider:
    """Adapt Apple's Vision text recognizer to :class:`OCRProvider`."""

    def __init__(self, config: VisionConfig | None = None) -> None:
        self._config = config or VisionConfig()
        self._classes: tuple[Any, Any] | None = None

    @staticmethod
    def is_available() -> bool:
        """Whether this machine can run Vision at all."""

        if sys.platform != "darwin":
            return False
        try:
            VisionProvider()._load()
        except ProviderError:
            return False
        return True

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        """Run Vision for one ROI and return normalized results in reading order."""

        if not isinstance(image, ROIImage):
            raise TypeError("image must be an ROIImage")

        request_class, handler_class = self._load()
        try:
            payload = _png_bytes(image, self._config.input_scale)
        except Exception as exc:
            raise VisionProviderError(f"Vision input conversion failed: {exc}") from exc

        try:
            observations = self._run(request_class, handler_class, payload)
        except VisionProviderError:
            raise
        except Exception as exc:
            raise VisionProviderError(f"Vision recognition failed: {exc}") from exc

        results = [
            normalized
            for observation in observations
            if (normalized := _normalize(observation, image)) is not None
        ]
        # Vision returns observations in confidence order; the seam promises
        # reading order, which for one small ROI is top-to-bottom then left.
        results.sort(key=lambda result: (result.quad.p1.y, result.quad.p1.x))
        return tuple(results)

    def prewarm(self) -> None:
        """Load the framework before the first real lookup pays for it."""

        self._load()

    def _run(
        self, request_class: Any, handler_class: Any, payload: bytes
    ) -> Sequence[Any]:
        from Foundation import NSData

        request = request_class.alloc().init()
        request.setRecognitionLevel_(_LEVEL_ACCURATE)
        request.setRecognitionLanguages_(list(self._config.languages))
        request.setUsesLanguageCorrection_(self._config.language_correction)
        if self._config.minimum_text_height > 0:
            request.setMinimumTextHeight_(self._config.minimum_text_height)

        data = NSData.dataWithBytes_length_(payload, len(payload))
        handler = handler_class.alloc().initWithData_options_(data, {})
        handler.performRequests_error_([request], None)
        return request.results() or ()

    def _load(self) -> tuple[Any, Any]:
        """Resolve the two Vision classes once, or say why it cannot."""

        if self._classes is not None:
            return self._classes

        if sys.platform != "darwin":
            raise VisionProviderError("Vision text recognition requires macOS")
        try:
            import objc
            from Foundation import NSBundle
        except Exception as exc:
            raise VisionProviderError("pyobjc is unavailable") from exc

        bundle = NSBundle.bundleWithPath_(_VISION_FRAMEWORK)
        if bundle is None or not bundle.load():
            raise VisionProviderError("Vision.framework could not be loaded")
        try:
            classes = (
                objc.lookUpClass("VNRecognizeTextRequest"),
                objc.lookUpClass("VNImageRequestHandler"),
            )
        except Exception as exc:
            raise VisionProviderError("Vision text recognition is unavailable") from exc

        self._classes = classes
        return classes


def _png_bytes(image: ROIImage, scale: int = 1) -> bytes:
    """Encode a presentation-only enlargement without changing ROI geometry.

    Nearest-neighbor replication prevents Vision from dropping small Korean/Latin
    lines without inventing subpixel detail. Only the payload grows; results are
    mapped back to the original ROI.
    """

    from PIL import Image

    mode = _PIXEL_MODES[image.pixel_format]
    if mode == "BGR":
        frame = Image.frombytes("RGB", (image.width, image.height), image.data)
        frame = Image.merge("RGB", frame.split()[::-1])
    else:
        frame = Image.frombytes(mode, (image.width, image.height), image.data)

    frame = frame.convert("RGB")
    if scale > 1:
        frame = frame.resize(
            (image.width * scale, image.height * scale), Image.Resampling.NEAREST
        )

    buffer = BytesIO()
    frame.save(buffer, format="PNG")
    return buffer.getvalue()


def _normalize(observation: Any, image: ROIImage) -> OCRResult | None:
    """Convert one Vision observation into a normalized result, or drop it."""

    candidates = observation.topCandidates_(1)
    if not candidates:
        return None
    text = candidates[0].string()
    if not isinstance(text, str) or not text.strip():
        return None

    box = observation.boundingBox()
    left = box.origin.x * image.width
    right = (box.origin.x + box.size.width) * image.width
    # Vision's origin is bottom-left; the contract's is top-left.
    top = (1.0 - box.origin.y - box.size.height) * image.height
    bottom = (1.0 - box.origin.y) * image.height
    if right - left <= 0 or bottom - top <= 0:
        return None

    return OCRResult(
        text=text,
        confidence=float(candidates[0].confidence()),
        quad=Quad(
            Point(left, top), Point(right, top), Point(right, bottom), Point(left, bottom)
        ),
    )


__all__ = [
    "DEFAULT_INPUT_SCALE",
    "MAX_INPUT_SCALE",
    "VisionConfig",
    "VisionProvider",
    "VisionProviderError",
]
