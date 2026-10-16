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
    VisionProviderError,
    _normalize,
    _png_bytes,
)


class UnpooledVision(VisionProvider):
    """The provider exactly as it was before its autorelease pool (2026-10-16).

    Kept so the pooled provider can be measured against its predecessor
    back to back, under identical conditions, without switching checkouts.
    """

    def recognize(self, image: Any) -> tuple[Any, ...]:
        request_class, handler_class = self._load()
        try:
            payload = self._payload(image)
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
        results.sort(key=lambda result: (result.quad.p1.y, result.quad.p1.x))
        return tuple(results)


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

    def _payload(self, image: Any) -> Any:
        return _scaled_rgb(image, self._config.input_scale)

    def _run(self, request_class: Any, handler_class: Any, payload: Any) -> Sequence[Any]:
        import Quartz

        width, height, rgb = payload
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
    "unpooled": UnpooledVision,
    "request_reuse": RequestReuseVision,
    "raw_image": RawImageVision,
}

__all__ = ["VARIANTS", "RawImageVision", "RequestReuseVision", "UnpooledVision", "_png_bytes"]
