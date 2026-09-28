"""Drive EasyOCR's detection and recognition stages one region at a time.

The shipped provider calls ``Reader.readtext`` and sees only its normalized
output. That is the right shape for a product and the wrong shape for finding
out *why* a word came back wrong, so this module reproduces what ``readtext``
does internally and keeps every intermediate image.

It is developer-only and pinned to one EasyOCR version, because it uses
implementation detail the library makes no promises about. Normalization is not
reimplemented here: the adapter's own helpers turn raw detections into contract
values, so a staged run and a production run cannot disagree about what a
detection means.

**Two evidence classes, never mixed.** A lookup deliberately executed through
this path owns its crops. Staging a frozen ROI *after* a production lookup is
``comparison_replay``: it may agree or disagree with the live result, and a
disagreement is reported rather than resolved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hanly import OCRResult, ROIImage
from hanly.easyocr_provider import easyocr_image_from_roi, normalize_easyocr_results

#: The EasyOCR release whose internals this module reproduces.
PINNED_EASYOCR_VERSION = "1.7.2"

#: The recognizer's fixed input height; every crop is resized to it.
RECOGNIZER_HEIGHT = 64

#: A staged run that *was* the lookup, versus one replayed against a frozen ROI
#: that a production provider already read.
STAGED_DIAGNOSTIC = "staged_diagnostic"
COMPARISON_REPLAY = "comparison_replay"


class StagedEasyOCRError(RuntimeError):
    """Raised when the installed EasyOCR does not expose the expected stages."""


@dataclass(frozen=True)
class StageImage:
    """One intermediate image, held as bytes so no library object escapes."""

    width: int
    height: int
    mode: str
    data: bytes

    @property
    def byte_count(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class StagedRegion:
    """One detected region and every image it passed through."""

    index: int
    #: ``horizontal`` regions come from the detector's axis-aligned grouping;
    #: ``free`` ones are the rotated quads it could not group that way.
    kind: str
    #: The detector's own geometry, before any Hanly normalization.
    raw_box: tuple[float, ...] | tuple[tuple[float, float], ...]
    quad: tuple[tuple[float, float], ...]
    crop: StageImage | None = None
    recognizer_input: StageImage | None = None
    text: str | None = None
    confidence: float | None = None
    crop_ns: int | None = None
    recognition_ns: int | None = None
    #: Why a stage produced nothing, when it did not.
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class StagedRun:
    """Everything one staged EasyOCR invocation saw, in memory only."""

    evidence_class: str
    easyocr_version: str
    detector_options: dict[str, Any]
    recognizer_options: dict[str, Any]
    source: StageImage
    grayscale: StageImage
    regions: tuple[StagedRegion, ...] = ()
    normalized: tuple[OCRResult, ...] = ()
    detection_ns: int = 0
    recognition_ns: int = 0
    normalization_ns: int = 0
    total_ns: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_replay(self) -> bool:
        """Whether these internals belong to a replay rather than a live pass."""

        return self.evidence_class == COMPARISON_REPLAY


@dataclass(frozen=True)
class StagedComparison:
    """Whether a staged replay agreed with the live normalized output."""

    live: tuple[OCRResult, ...]
    staged: tuple[OCRResult, ...]
    matches: bool
    differences: tuple[str, ...]


def installed_easyocr_version() -> str:
    """Return the installed EasyOCR version, or ``unavailable``."""

    from importlib import metadata

    try:
        return metadata.version("easyocr")
    except metadata.PackageNotFoundError:
        return "unavailable"


def verify_easyocr_api(reader: Any) -> str:
    """Fail loudly and specifically when the pinned internals have moved.

    This module reproduces ``Reader.readtext``'s body. When an upgrade changes
    that body, the failure has to name what moved rather than surface as a
    silently different set of crops.
    """

    version = installed_easyocr_version()
    missing = [
        name
        for name in ("detect", "recognize")
        if not callable(getattr(reader, name, None))
    ]
    if missing:
        raise StagedEasyOCRError(
            f"EasyOCR {version} reader is missing {', '.join(missing)}; the staged "
            "diagnostic runner reproduces Reader.readtext and must be updated"
        )
    try:
        from easyocr.utils import get_image_list, reformat_input
    except Exception as error:
        raise StagedEasyOCRError(
            f"EasyOCR {version} does not expose easyocr.utils.reformat_input/"
            f"get_image_list ({error}); the staged diagnostic runner must be updated"
        ) from error
    if not callable(reformat_input) or not callable(get_image_list):
        raise StagedEasyOCRError(
            f"EasyOCR {version} exposes reformat_input/get_image_list as non-callables"
        )
    return version


def run_staged_easyocr(
    reader: Any,
    image: ROIImage,
    *,
    evidence_class: str = STAGED_DIAGNOSTIC,
    detector_options: dict[str, Any] | None = None,
    recognizer_options: dict[str, Any] | None = None,
) -> StagedRun:
    """Reproduce ``readtext`` stage by stage, retaining every image in memory.

    Nothing is written to disk. The caller decides whether these internals
    belong to a diagnostic invocation or to a replay of an earlier one.
    """

    if evidence_class not in (STAGED_DIAGNOSTIC, COMPARISON_REPLAY):
        raise ValueError(f"unknown evidence class: {evidence_class!r}")
    version = verify_easyocr_api(reader)

    from easyocr.utils import reformat_input

    detect_kwargs = dict(detector_options or {})
    recognize_kwargs = dict(recognizer_options or {})
    started = time.perf_counter_ns()

    source_array = easyocr_image_from_roi(image)
    colour, grayscale = reformat_input(source_array)

    detect_started = time.perf_counter_ns()
    horizontal_list, free_list = reader.detect(colour, reformat=False, **detect_kwargs)
    detection_ns = time.perf_counter_ns() - detect_started
    # ``detect`` returns a list per input image; ``readtext`` takes the first.
    horizontal, free = _first_of_each(horizontal_list, free_list)

    regions, recognition_ns = _staged_regions(
        reader, grayscale, horizontal, free, recognize_kwargs
    )

    normalize_started = time.perf_counter_ns()
    normalized = normalize_easyocr_results(
        [
            (list(region.quad), region.text, region.confidence)
            for region in regions
            if region.text is not None and region.confidence is not None
        ]
    )
    normalization_ns = time.perf_counter_ns() - normalize_started

    return StagedRun(
        evidence_class=evidence_class,
        easyocr_version=version,
        detector_options=detect_kwargs,
        recognizer_options=recognize_kwargs,
        source=_stage_image(colour),
        grayscale=_stage_image(grayscale),
        regions=regions,
        normalized=normalized,
        detection_ns=detection_ns,
        recognition_ns=recognition_ns,
        normalization_ns=normalization_ns,
        total_ns=time.perf_counter_ns() - started,
        notes=() if version == PINNED_EASYOCR_VERSION else (
            f"installed EasyOCR {version} differs from the pinned "
            f"{PINNED_EASYOCR_VERSION}; staged internals may not match readtext",
        ),
    )


def compare_to_live(
    live: tuple[OCRResult, ...] | list[OCRResult], staged: StagedRun
) -> StagedComparison:
    """Report agreement between a live pass and a staged replay of the same ROI.

    A disagreement is surfaced as itself. The live result stays authoritative:
    a replay never replaces or explains away what the provider actually read.
    """

    live_results = tuple(live)
    differences: list[str] = []
    if len(live_results) != len(staged.normalized):
        differences.append(
            f"region count: live {len(live_results)} vs staged "
            f"{len(staged.normalized)}"
        )
    for index, (one, other) in enumerate(zip(live_results, staged.normalized)):
        if one.text != other.text:
            differences.append(f"region {index} text: {one.text!r} vs {other.text!r}")
        elif abs(one.confidence - other.confidence) > 1e-6:
            differences.append(
                f"region {index} confidence: {one.confidence:.6f} vs "
                f"{other.confidence:.6f}"
            )
    return StagedComparison(
        live=live_results,
        staged=staged.normalized,
        matches=not differences,
        differences=tuple(differences),
    )


def _first_of_each(horizontal_list: Any, free_list: Any) -> tuple[list[Any], list[Any]]:
    """Unwrap ``detect``'s per-image nesting the way ``readtext`` does."""

    try:
        return list(horizontal_list[0]), list(free_list[0])
    except (IndexError, TypeError) as error:
        raise StagedEasyOCRError(
            f"EasyOCR detect returned an unexpected shape: {error}"
        ) from error


def _staged_regions(
    reader: Any,
    grayscale: Any,
    horizontal: list[Any],
    free: list[Any],
    recognize_kwargs: dict[str, Any],
) -> tuple[tuple[StagedRegion, ...], int]:
    """Crop and recognize one region at a time, as EasyOCR itself does on CPU.

    Recognizing each box on its own is what makes the retained crop the exact
    image that reached the recognizer for that region, rather than one member of
    a batch whose padding depended on its neighbours.
    """

    regions: list[StagedRegion] = []
    recognition_ns = 0
    boxes = [("horizontal", box) for box in horizontal] + [("free", box) for box in free]
    for index, (kind, box) in enumerate(boxes):
        crop, crop_ns, crop_error = _crop_for(grayscale, kind, box)
        started = time.perf_counter_ns()
        text, confidence, quad, recognize_error = _recognize_one(
            reader, grayscale, kind, box, recognize_kwargs
        )
        recognition_ns += time.perf_counter_ns() - started
        regions.append(
            StagedRegion(
                index=index,
                kind=kind,
                raw_box=_raw_box(box),
                quad=quad if quad is not None else _quad_from_box(kind, box),
                crop=crop,
                recognizer_input=crop,
                text=text,
                confidence=confidence,
                crop_ns=crop_ns,
                recognition_ns=time.perf_counter_ns() - started,
                unavailable_reason=crop_error or recognize_error,
            )
        )
    return tuple(regions), recognition_ns


def _crop_for(
    grayscale: Any, kind: str, box: Any
) -> tuple[StageImage | None, int | None, str | None]:
    """Extract the resized grayscale crop EasyOCR hands to the recognizer."""

    from easyocr.utils import get_image_list

    started = time.perf_counter_ns()
    horizontal = [box] if kind == "horizontal" else []
    free = [] if kind == "horizontal" else [box]
    try:
        image_list, _max_width = get_image_list(
            horizontal, free, grayscale, model_height=RECOGNIZER_HEIGHT
        )
    except Exception as error:
        return None, None, f"crop_failed:{type(error).__name__}"
    if not image_list:
        # A box whose resized width rounds to zero is dropped by EasyOCR before
        # recognition, which is itself the answer for a missing region.
        return None, time.perf_counter_ns() - started, "crop_degenerate"
    return (
        _stage_image(image_list[0][1]),
        time.perf_counter_ns() - started,
        None,
    )


def _recognize_one(
    reader: Any,
    grayscale: Any,
    kind: str,
    box: Any,
    recognize_kwargs: dict[str, Any],
) -> tuple[str | None, float | None, tuple[tuple[float, float], ...] | None, str | None]:
    horizontal = [box] if kind == "horizontal" else None
    free = None if kind == "horizontal" else [box]
    try:
        results = reader.recognize(
            grayscale,
            horizontal_list=horizontal or [],
            free_list=free or [],
            reformat=False,
            **recognize_kwargs,
        )
    except Exception as error:
        return None, None, None, f"recognition_failed:{type(error).__name__}"
    if not results:
        return None, None, None, "recognition_empty"

    quad_points, text, confidence = results[0]
    return (
        str(text),
        float(confidence),
        tuple((float(point[0]), float(point[1])) for point in quad_points),
        None,
    )


def _raw_box(box: Any) -> Any:
    """Return the detector's geometry as plain numbers, in its own shape."""

    values = box.tolist() if hasattr(box, "tolist") else box
    if not isinstance(values, (list, tuple)):
        return values
    if values and isinstance(values[0], (list, tuple)):
        return tuple(tuple(float(number) for number in corner) for corner in values)
    return tuple(float(number) for number in values)


def _quad_from_box(kind: str, box: Any) -> tuple[tuple[float, float], ...]:
    """Derive four corners from whichever shape the detector reported."""

    raw = _raw_box(box)
    if kind == "horizontal" and len(raw) == 4 and not isinstance(raw[0], tuple):
        left, right, top, bottom = (float(value) for value in raw)
        return ((left, top), (right, top), (right, bottom), (left, bottom))
    return tuple(corner for corner in raw if isinstance(corner, tuple))


def _stage_image(array: Any) -> StageImage:
    """Copy a NumPy image into plain bytes, keeping its channel layout."""

    shape = tuple(int(value) for value in array.shape)
    height, width = shape[0], shape[1]
    channels = shape[2] if len(shape) > 2 else 1
    mode = {1: "L", 3: "BGR", 4: "BGRA"}.get(channels, f"C{channels}")
    return StageImage(width=width, height=height, mode=mode, data=bytes(array.tobytes()))


__all__ = [
    "COMPARISON_REPLAY",
    "PINNED_EASYOCR_VERSION",
    "RECOGNIZER_HEIGHT",
    "STAGED_DIAGNOSTIC",
    "StageImage",
    "StagedComparison",
    "StagedEasyOCRError",
    "StagedRegion",
    "StagedRun",
    "compare_to_live",
    "installed_easyocr_version",
    "run_staged_easyocr",
    "verify_easyocr_api",
]
