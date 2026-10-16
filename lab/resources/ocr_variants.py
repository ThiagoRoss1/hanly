"""Candidate Vision changes, each one change away from the product provider.

Developer-only. Each variant subclasses the shipped ``VisionProvider`` and
overrides exactly one step, so a resource comparison against ``product``
measures that step and nothing else. A variant is promoted into
``packages/`` only with comparable evidence; until then it lives here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from hanly.vision_provider import (
    _LEVEL_ACCURATE,
    _PIXEL_MODES,
    VisionConfig,
    VisionProvider,
    _png_bytes,
)


class RequestReuseVision(VisionProvider):
    """Build one ``VNRecognizeTextRequest`` and reuse it for every image."""

    def __init__(self, config: VisionConfig | None = None) -> None:
        super().__init__(config)
        self._request: Any | None = None

    def _run(self, request_class: Any, handler_class: Any, payload: bytes) -> Sequence[Any]:
        from Foundation import NSData

        if self._request is None:
            request = request_class.alloc().init()
            request.setRecognitionLevel_(_LEVEL_ACCURATE)
            request.setRecognitionLanguages_(list(self._config.languages))
            request.setUsesLanguageCorrection_(self._config.language_correction)
            if self._config.minimum_text_height > 0:
                request.setMinimumTextHeight_(self._config.minimum_text_height)
            self._request = request
        data = NSData.dataWithBytes_length_(payload, len(payload))
        handler = handler_class.alloc().initWithData_options_(data, {})
        handler.performRequests_error_([self._request], None)
        return tuple(self._request.results() or ())


class RawImageVision(VisionProvider):
    """Hand Vision a ``CGImage`` built from the scaled pixels, with no PNG.

    The same Pillow scaling and channel handling as ``_png_bytes`` produce
    the pixels, so only the encode/decode round trip is removed; geometry is
    normalized against the unscaled ROI exactly as before.
    """

    def recognize(self, image: Any) -> Any:
        self._raw_image = image
        return super().recognize(image)

    def _run(self, request_class: Any, handler_class: Any, payload: bytes) -> Sequence[Any]:
        import Quartz

        width, height, rgb = _scaled_rgb(self._raw_image, self._config.input_scale)
        provider = Quartz.CGDataProviderCreateWithData(None, rgb, len(rgb), None)
        cg_image = Quartz.CGImageCreate(
            width, height, 8, 24, width * 3,
            Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB),
            Quartz.kCGImageAlphaNone, provider, None, False,
            Quartz.kCGRenderingIntentDefault,
        )
        request = request_class.alloc().init()
        request.setRecognitionLevel_(_LEVEL_ACCURATE)
        request.setRecognitionLanguages_(list(self._config.languages))
        request.setUsesLanguageCorrection_(self._config.language_correction)
        if self._config.minimum_text_height > 0:
            request.setMinimumTextHeight_(self._config.minimum_text_height)
        handler = handler_class.alloc().initWithCGImage_options_(cg_image, {})
        handler.performRequests_error_([request], None)
        return tuple(request.results() or ())


def _scaled_rgb(image: Any, scale: int) -> tuple[int, int, bytes]:
    """Pixels exactly as ``_png_bytes`` prepares them, before PNG encoding."""

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
    return frame.width, frame.height, frame.tobytes()


#: Name in a plan → factory. ``product`` is the shipped provider itself.
VARIANTS: dict[str, Callable[[], Any]] = {
    "request_reuse": RequestReuseVision,
    "raw_image": RawImageVision,
}

__all__ = ["VARIANTS", "RawImageVision", "RequestReuseVision", "_png_bytes"]
