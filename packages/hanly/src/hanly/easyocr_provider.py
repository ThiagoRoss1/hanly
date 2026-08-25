"""EasyOCR adapter for the normalized Hanly OCR provider seam.

EasyOCR is imported lazily so the engine package stays importable for clients
that do not install the optional Torch/EasyOCR runtime, while a composition
root can construct this provider when EasyOCR is available. Only
:class:`~hanly.contracts.OCRResult` values leave this module; EasyOCR's
``(box, text, confidence)`` triples and NumPy arrays remain implementation
details here.
"""

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from math import floor
from pathlib import Path
from statistics import median
from typing import Any

from .contracts import OCRResult, PixelFormat, Point, Quad, ROIImage
from .errors import ProviderError

# Past four threads the measured latency gain is small while total CPU keeps
# rising, which is the wrong trade for a background desktop helper.
_MAX_DEFAULT_CPU_THREADS = 4

# CRAFT ignores a text box whose longest side is under ``min_size``, and needs
# roughly 22 px of glyph height before it reports anything at all. A single
# Hangul syllable standing alone at a normal UI size fails both tests, while
# the same syllable with a particle attached passes because the box is twice
# as wide. Upscaling and lowering the box floor together recover it; neither
# does so alone. The pair costs about 2.7x the latency, so it belongs on a
# retry rather than on every lookup.
_DEFAULT_SENSITIVE_OPTIONS: Mapping[str, Any] = {"mag_ratio": 2.0, "min_size": 4}


@dataclass(frozen=True)
class EasyOCRConfig:
    """Explicit EasyOCR construction options supplied by composition code.

    ``languages`` deliberately defaults to Korean alone. ``korean_g2`` already
    recognizes the Latin letters, digits, and punctuation that appear beside
    Korean text, so adding ``"en"`` would load a second character set without
    widening what Hanly can read. GPU is never requested: V1 targets CPU-only
    desktops, and a GPU option would make provider behavior depend on hardware
    the rest of the runtime does not model.
    """

    languages: tuple[str, ...] = ("ko",)
    model_storage_directory: str | Path | None = None
    user_network_directory: str | Path | None = None
    download_enabled: bool = True
    cpu_threads: int | None = None
    extra_options: Mapping[str, Any] = field(default_factory=dict)
    readtext_options: Mapping[str, Any] = field(default_factory=dict)
    sensitive_readtext_options: Mapping[str, Any] = field(
        default_factory=lambda: dict(_DEFAULT_SENSITIVE_OPTIONS)
    )

    def __post_init__(self) -> None:
        # Freeze both collection boundaries as far as a public value object
        # can; callers cannot mutate what a constructed config holds.
        object.__setattr__(self, "languages", tuple(self.languages))
        object.__setattr__(self, "extra_options", dict(self.extra_options))
        object.__setattr__(self, "readtext_options", dict(self.readtext_options))
        object.__setattr__(
            self, "sensitive_readtext_options", dict(self.sensitive_readtext_options)
        )

        if not self.languages:
            raise ValueError("at least one recognition language is required")
        if any(
            not isinstance(language, str) or not language.strip()
            for language in self.languages
        ):
            raise ValueError("recognition languages must be non-empty strings")
        if not isinstance(self.download_enabled, bool):
            raise ValueError("download_enabled must be a boolean")
        if self.cpu_threads is not None and (
            isinstance(self.cpu_threads, bool)
            or not isinstance(self.cpu_threads, int)
            or self.cpu_threads < 1
        ):
            raise ValueError("cpu_threads must be a positive integer")

    def to_reader_kwargs(self) -> dict[str, Any]:
        """Return only the explicit options accepted by ``easyocr.Reader``."""

        options: dict[str, Any] = {
            "lang_list": list(self.languages),
            "gpu": False,
            "download_enabled": self.download_enabled,
            "verbose": False,
        }
        if self.model_storage_directory is not None:
            options["model_storage_directory"] = str(self.model_storage_directory)
        if self.user_network_directory is not None:
            options["user_network_directory"] = str(self.user_network_directory)
        options.update(self.extra_options)
        return options


class EasyOCRProviderError(ProviderError):
    """Expected failure while constructing or invoking the EasyOCR adapter."""


class EasyOCRProvider:
    """Adapt EasyOCR's detection/recognition results to normalized contracts.

    ``engine`` and ``engine_factory`` are dependency-injection seams for unit
    tests and application composition. With neither supplied, the provider
    lazily constructs ``easyocr.Reader`` using ``config``. No resource manager
    is consulted here: model storage and language configuration are explicit
    constructor inputs.
    """

    def __init__(
        self,
        config: EasyOCRConfig | None = None,
        *,
        engine: Any | None = None,
        engine_factory: Callable[..., Any] | None = None,
    ) -> None:
        if engine is not None and engine_factory is not None:
            raise ValueError("engine and engine_factory are mutually exclusive")

        provider_config = config or EasyOCRConfig()
        if engine is None:
            factory = engine_factory or self._load_reader_factory()
            if engine_factory is None:
                # Only the real EasyOCR path loads Torch, so only it takes the
                # process-global thread bound. An injected factory need not be
                # Torch-backed at all.
                _limit_torch_threads(provider_config.cpu_threads)
            try:
                engine = factory(**provider_config.to_reader_kwargs())
            except Exception as exc:
                raise EasyOCRProviderError(
                    f"EasyOCR initialization failed: {exc}"
                ) from exc

        if not callable(getattr(engine, "readtext", None)):
            raise EasyOCRProviderError(
                "EasyOCR engine must provide a callable readtext method"
            )
        self._engine = engine
        self._config = provider_config
        self._readtext_options = dict(provider_config.readtext_options)
        self._prewarmed = False

    @staticmethod
    def _load_reader_factory() -> Callable[..., Any]:
        try:
            from easyocr import Reader
        except Exception as exc:
            raise EasyOCRProviderError(f"EasyOCR is unavailable: {exc}") from exc
        return Reader

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        """Run EasyOCR for one ROI and return normalized results in reading order."""

        if not isinstance(image, ROIImage):
            raise TypeError("image must be an ROIImage")

        try:
            easyocr_image = self._to_easyocr_image(image)
        except EasyOCRProviderError:
            raise
        except Exception as exc:
            raise EasyOCRProviderError(
                f"EasyOCR input conversion failed: {exc}"
            ) from exc

        try:
            raw_results = self._engine.readtext(easyocr_image, **self._readtext_options)
        except Exception as exc:
            raise EasyOCRProviderError(f"EasyOCR recognition failed: {exc}") from exc

        try:
            return _in_reading_order(_normalize_results(raw_results))
        except EasyOCRProviderError:
            raise
        except Exception as exc:
            raise EasyOCRProviderError(
                f"EasyOCR returned malformed OCR output: {exc}"
            ) from exc

    def prewarm(self) -> None:
        """Run one real, idempotent inference before the worker becomes ready.

        Constructing ``easyocr.Reader`` loads both model files, but the first
        real call still pays for Torch's lazy kernel setup. Paying it here keeps
        it off the first hover.
        """

        if self._prewarmed:
            return
        blank = ROIImage(96, 32, PixelFormat.GRAYSCALE_8, bytes(96 * 32))
        self.recognize(blank)
        self._prewarmed = True

    def sensitive_variant(self) -> "EasyOCRProvider | None":
        """Return a provider reading the same engine with a slower, keener pass.

        The engine is shared rather than rebuilt: a second ``easyocr.Reader``
        would load both models again for a retry that most lookups never need.
        Returns ``None`` when no sensitive options are configured, which is how
        a caller disables the retry entirely.
        """

        options = self._config.sensitive_readtext_options
        if not options:
            return None
        variant = EasyOCRProvider(self._config, engine=self._engine)
        variant._readtext_options = {**self._readtext_options, **options}
        variant._prewarmed = True
        return variant

    @staticmethod
    def _to_easyocr_image(image: ROIImage) -> Any:
        try:
            import numpy as np
        except Exception as exc:
            raise EasyOCRProviderError(f"NumPy is required by EasyOCR: {exc}") from exc

        channels = image.bytes_per_pixel
        shape: tuple[int, ...] = (image.height, image.width)
        if channels > 1:
            shape += (channels,)
        array: Any = np.frombuffer(image.data, dtype=np.uint8).reshape(shape)

        if image.pixel_format is PixelFormat.RGB_888:
            # EasyOCR reads a three-channel array as BGR, a four-channel one as
            # RGBA, and a two-dimensional one as grayscale. Only RGB needs a
            # channel swap to arrive as the library expects.
            array = array[..., ::-1]

        # OpenCV, which EasyOCR normalizes its input with, needs a writable
        # contiguous buffer; ``frombuffer`` returns a read-only view.
        return np.array(array, dtype=np.uint8, copy=True)


def default_cpu_threads(core_count: int | None = None) -> int:
    """Return the Torch thread bound to use when a config states none.

    Torch otherwise claims every core, which on a small machine starves the Qt
    UI thread and produces exactly the "the computer went heavy" symptom OCR
    is supposed to avoid. One core is always left for the rest of the desktop,
    and the bound is capped because measured latency stops improving
    meaningfully past four threads while total CPU keeps climbing.
    """

    cores = os.cpu_count() if core_count is None else core_count
    if not isinstance(cores, int) or cores < 1:
        return 1
    return max(1, min(_MAX_DEFAULT_CPU_THREADS, cores - 1))


def _limit_torch_threads(cpu_threads: int | None) -> None:
    """Apply a Torch intra-op thread bound before models are loaded.

    This is process-global state. An explicit ``cpu_threads`` wins; otherwise
    the bound is derived from the host so a two-core machine is not
    oversubscribed by a value tuned on an eight-core one.
    """

    bound = default_cpu_threads() if cpu_threads is None else cpu_threads
    try:
        import torch

        torch.set_num_threads(bound)
    except Exception as exc:
        raise EasyOCRProviderError(
            f"could not apply EasyOCR cpu_threads: {exc}"
        ) from exc


def _normalize_results(raw_results: Any) -> list[OCRResult]:
    """Convert EasyOCR's ``(box, text, confidence)`` triples to OCR results."""

    if raw_results is None:
        return []
    if not _is_sequence(raw_results):
        raise EasyOCRProviderError(
            "EasyOCR returned malformed OCR output: expected a result sequence"
        )

    normalized: list[OCRResult] = []
    for entry in raw_results:
        box, text, confidence = _detection_parts(entry)
        # EasyOCR can emit a blank recognition for a detected but unreadable
        # region. It carries no word for the resolver and its geometry is often
        # degenerate, so it is dropped rather than turned into a result.
        if not text:
            continue
        try:
            normalized.append(
                OCRResult(text=text, confidence=confidence, quad=_to_quad(box))
            )
        except Exception as exc:
            raise EasyOCRProviderError(
                f"EasyOCR returned malformed OCR output: {exc}"
            ) from exc
    return normalized


def _detection_parts(entry: Any) -> tuple[Any, str, float]:
    """Split one detection into its geometry, stripped text, and confidence."""

    parts = _as_list(entry) if _is_sequence(entry) else []
    if len(parts) != 3:
        raise EasyOCRProviderError(
            "EasyOCR returned malformed OCR output: expected (box, text, confidence)"
        )

    box, raw_text, raw_confidence = parts
    if not isinstance(raw_text, str) or isinstance(raw_confidence, bool):
        raise EasyOCRProviderError(
            "EasyOCR returned malformed OCR output: invalid text or confidence"
        )
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError) as exc:
        raise EasyOCRProviderError(
            "EasyOCR returned malformed OCR output: invalid confidence"
        ) from exc

    # EasyOCR's confidence is a product of per-character softmax scores and can
    # land marginally outside [0, 1]; clamping keeps a usable score from
    # failing the contract.
    return box, raw_text.strip(), min(1.0, max(0.0, confidence))


def _in_reading_order(results: Sequence[OCRResult]) -> tuple[OCRResult, ...]:
    """Order regions top to bottom, then left to right within a line.

    EasyOCR returns its horizontally grouped regions before free-form ones,
    which is not the reading order the provider contract promises. Lines are
    separated by bucketing each region's vertical centre against the median
    region height, which is accurate for the small, mostly single-line ROIs
    Hanly captures and does not attempt full page segmentation.
    """

    if len(results) < 2:
        return tuple(results)

    line_height = median(result.quad.height for result in results) or 1.0
    return tuple(
        sorted(
            results,
            key=lambda result: (
                floor(_vertical_centre(result.quad) / line_height),
                min(point.x for point in result.quad.points),
            ),
        )
    )


def _vertical_centre(quad: Quad) -> float:
    ys = [point.y for point in quad.points]
    return (min(ys) + max(ys)) / 2


def _to_quad(box: Any) -> Quad:
    if isinstance(box, Quad):
        return box

    corners = _as_list(box)
    if len(corners) != 4:
        raise ValueError("each EasyOCR box must contain four corners")

    points: list[Point] = []
    for corner in corners:
        coordinates = _as_list(corner)
        if len(coordinates) != 2:
            raise ValueError("each EasyOCR corner must contain an x and a y")
        points.append(Point(float(coordinates[0]), float(coordinates[1])))
    return Quad(p1=points[0], p2=points[1], p3=points[2], p4=points[3])


def _is_sequence(value: Any) -> bool:
    return not isinstance(value, (str, bytes, bytearray, Mapping)) and (
        isinstance(value, Sequence)
        or (hasattr(value, "__len__") and hasattr(value, "__getitem__"))
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return list(value)
    except TypeError:
        return [value]


__all__ = [
    "EasyOCRConfig",
    "EasyOCRProvider",
    "EasyOCRProviderError",
    "default_cpu_threads",
]
