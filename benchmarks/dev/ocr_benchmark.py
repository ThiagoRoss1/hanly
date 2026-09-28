"""Measure OCR on its own, without waking the rest of the lookup pipeline.

A `real-lookup` run measures capture, OCR, Kiwi, KRDICT and presentation
together, which is the right thing to measure for a product and the wrong thing
for finding out whether OCR read the word. These modes construct one recognizer
and nothing else: no morphology, no dictionary, no `LookupPipeline`, no hover,
no UI. A test asserts that, because the cheapest way to get a misleading number
is to accidentally pay for a stage the mode claims not to run.

Four modes, and each reports honestly on the stages its provider does not
expose. Apple Vision has no separately addressable detector, so asking it for
detection-only geometry gets `unavailable` rather than a fabricated box.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hanly import OCRProvider, OCRResult, PixelFormat, Point, ROIImage

from .corpus import Corpus, CorpusCase, validate_case_geometry
from .easyocr_stages import COMPARISON_REPLAY, STAGED_DIAGNOSTIC, run_staged_easyocr
from .ocr_metrics import Metric, Region, aggregate, score_case

#: What a run can be asked to do.
OCR_ONLY = "ocr-only"
DETECTION_ONLY = "detection-only"
RECOGNITION_ONLY = "recognition-only"
FROZEN_REPLAY = "frozen-replay"
MODES = (OCR_ONLY, DETECTION_ONLY, RECOGNITION_ONLY, FROZEN_REPLAY)

#: Recognizers a run may select. No mode adds one.
EASYOCR = "easyocr"
VISION = "vision"
BACKENDS = (EASYOCR, VISION)


class OCRBenchmarkError(RuntimeError):
    """Raised when a mode cannot run against the provider it was given."""


@dataclass(frozen=True)
class StageTimings:
    """Per-stage durations, absent where the provider exposes no such stage."""

    total_ns: int
    detection_ns: int | None = None
    recognition_ns: int | None = None
    normalization_ns: int | None = None


@dataclass(frozen=True)
class CaseResult:
    """One case, one mode, one measured pass."""

    case_id: str
    mode: str
    backend: str
    condition: str
    iteration: int
    regions: tuple[OCRResult, ...]
    timings: StageTimings
    metrics: tuple[Metric, ...] = ()
    unavailable: tuple[str, ...] = ()
    error: str | None = None

    @property
    def text(self) -> str:
        return " ".join(region.text for region in self.regions)


@dataclass(frozen=True)
class MemoryEvidence:
    """Resident memory at the points that distinguish a provider's cost.

    Current RSS needs ``psutil``; peak RSS does not, so the two are reported
    separately with their own availability rather than one silently standing in
    for the other.
    """

    baseline_rss: int | None
    initialized_rss: int | None
    steady_rss: int | None
    peak_rss: int | None
    baseline_peak_rss: int | None = None
    source: str = "psutil"

    @property
    def provider_cost(self) -> int | None:
        """What constructing the recognizer added, when both ends were read."""

        if self.baseline_rss is None or self.initialized_rss is None:
            return None
        return self.initialized_rss - self.baseline_rss

    @property
    def peak_growth(self) -> int | None:
        """How far peak RSS rose over the campaign."""

        if self.baseline_peak_rss is None or self.peak_rss is None:
            return None
        return self.peak_rss - self.baseline_peak_rss

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_class": "measured",
            "current_rss_source": self.source,
            "current_rss_available": self.baseline_rss is not None,
            "baseline_rss_bytes": self.baseline_rss,
            "initialized_rss_bytes": self.initialized_rss,
            "steady_rss_bytes": self.steady_rss,
            "provider_construction_bytes": self.provider_cost,
            "peak_rss_source": "resource.getrusage",
            "baseline_peak_rss_bytes": self.baseline_peak_rss,
            "peak_rss_bytes": self.peak_rss,
            "peak_growth_bytes": self.peak_growth,
        }


@dataclass
class CampaignReport:
    """Everything one campaign measured, before any of it is summarized."""

    mode: str
    backend: str
    results: list[CaseResult] = field(default_factory=list)
    memory: MemoryEvidence | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        warm = [result for result in self.results if result.condition == "warm"]
        return {
            "mode": self.mode,
            "backend": self.backend,
            "cases": len({result.case_id for result in self.results}),
            "samples": len(self.results),
            "errors": sum(1 for result in self.results if result.error is not None),
            "latency": {
                "cold": _latency(
                    [r for r in self.results if r.condition == "cold"]
                ),
                "warm": _latency(warm),
            },
            "metrics": aggregate([metric for result in warm for metric in result.metrics]),
            "memory": None if self.memory is None else self.memory.as_dict(),
            "notes": list(self.notes),
        }


def current_rss() -> int | None:
    """Resident set size right now, which needs ``psutil`` to read."""

    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def peak_rss() -> int | None:
    """High-water resident set size, from the standard library.

    ``ru_maxrss`` is bytes on the BSDs, macOS included, and kibibytes
    elsewhere; the same unit correction the process sampler applies.
    """

    try:
        import resource
        import sys
    except ImportError:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except (OSError, ValueError):
        return None
    scale = 1 if sys.platform == "darwin" else 1024
    return int(usage.ru_maxrss) * scale


def load_case_image(case: CorpusCase) -> ROIImage:
    """Decode one corpus image and check its annotations against it."""

    try:
        from PIL import Image
    except ImportError as error:
        raise OCRBenchmarkError("Pillow is required to read corpus images") from error

    with Image.open(case.image) as opened:
        rgb = opened.convert("RGB")
    validate_case_geometry(case, rgb.width, rgb.height)
    return ROIImage(rgb.width, rgb.height, PixelFormat.RGB_888, rgb.tobytes())


def run_campaign(
    corpus: Corpus,
    *,
    mode: str,
    backend: str,
    provider_factory: Callable[[], OCRProvider],
    reader_factory: Callable[[], Any] | None = None,
    warmup: int = 1,
    samples: int = 3,
    iou_threshold: float = 0.5,
    resolve_target: bool = True,
) -> CampaignReport:
    """Run one mode over one corpus, measuring cold, warm-up and warm passes.

    The provider is constructed here and nothing else is. Memory is sampled
    before and after that construction so the recognizer's own cost is
    separable from the process it happens to live in.
    """

    if mode not in MODES:
        raise OCRBenchmarkError(f"unknown mode {mode!r}; expected one of {list(MODES)}")
    if backend not in BACKENDS:
        raise OCRBenchmarkError(f"unknown backend {backend!r}")
    if mode in (DETECTION_ONLY, RECOGNITION_ONLY) and backend != EASYOCR:
        raise OCRBenchmarkError(
            f"{mode} needs separately addressable stages; {backend} exposes none. "
            "Run ocr-only against it instead of inventing a detector."
        )

    report = CampaignReport(mode=mode, backend=backend)
    baseline = current_rss()
    baseline_peak = peak_rss()
    provider = provider_factory()
    initialized = current_rss()
    reader = reader_factory() if reader_factory is not None else None

    try:
        for case in corpus.cases:
            image = load_case_image(case)
            repeats: list[str] = []
            for iteration, condition in enumerate(_conditions(warmup, samples)):
                result = _run_one(
                    case,
                    image,
                    mode=mode,
                    backend=backend,
                    provider=provider,
                    reader=reader,
                    condition=condition,
                    iteration=iteration,
                    iou_threshold=iou_threshold,
                    resolve_target=resolve_target,
                    repeats=tuple(repeats),
                )
                repeats.append(result.text)
                report.results.append(result)
    finally:
        _close(provider)
        _close(reader)

    report.memory = MemoryEvidence(
        baseline_rss=baseline,
        initialized_rss=initialized,
        steady_rss=current_rss(),
        peak_rss=peak_rss(),
        baseline_peak_rss=baseline_peak,
    )
    return report


def _conditions(warmup: int, samples: int) -> list[str]:
    """The first pass is cold by definition; nothing else can be."""

    if samples < 1:
        raise OCRBenchmarkError("a campaign needs at least one warm sample")
    return ["cold"] + ["warmup"] * max(0, warmup) + ["warm"] * samples


def _run_one(
    case: CorpusCase,
    image: ROIImage,
    *,
    mode: str,
    backend: str,
    provider: OCRProvider,
    reader: Any,
    condition: str,
    iteration: int,
    iou_threshold: float,
    resolve_target: bool,
    repeats: tuple[str, ...],
) -> CaseResult:
    started = time.perf_counter_ns()
    try:
        regions, timings, unavailable = _recognize(
            mode, provider, reader, image, started
        )
    except Exception as error:
        return CaseResult(
            case_id=case.case_id,
            mode=mode,
            backend=backend,
            condition=condition,
            iteration=iteration,
            regions=(),
            timings=StageTimings(total_ns=time.perf_counter_ns() - started),
            error=f"{type(error).__name__}: {error}",
        )

    metrics: tuple[Metric, ...] = ()
    if condition == "warm":
        # A mode that drops the text cannot be scored on it. Passing the
        # expectations through anyway would report a perfect error rate for a
        # transcription this mode never attempted.
        transcribes = "transcription" not in unavailable
        metrics = score_case(
            expected_text=case.expected_text if transcribes else None,
            expected_surface=case.expected_surface if transcribes else None,
            expected_target=case.expected_target,
            expected_regions=tuple(
                Region(region.text, region.left, region.top, region.right, region.bottom)
                for region in case.expected_regions
            ),
            actual_regions=tuple(_as_region(region) for region in regions),
            resolved_surface=(
                _resolved_surface(case, regions) if resolve_target and transcribes else None
            ),
            repeats=repeats if transcribes else (),
            iou_threshold=iou_threshold,
        )
    return CaseResult(
        case_id=case.case_id,
        mode=mode,
        backend=backend,
        condition=condition,
        iteration=iteration,
        regions=tuple(regions),
        timings=timings,
        metrics=metrics,
        unavailable=unavailable,
    )


def _recognize(
    mode: str,
    provider: OCRProvider,
    reader: Any,
    image: ROIImage,
    started: int,
) -> tuple[Sequence[OCRResult], StageTimings, tuple[str, ...]]:
    """Run whichever stages the requested mode actually covers."""

    if mode in (OCR_ONLY, FROZEN_REPLAY):
        regions = tuple(provider.recognize(image))
        return (
            regions,
            StageTimings(total_ns=time.perf_counter_ns() - started),
            ("detection_stage", "recognition_stage") if mode == OCR_ONLY else (),
        )

    if reader is None:
        raise OCRBenchmarkError(f"{mode} needs an EasyOCR reader")
    staged = run_staged_easyocr(
        reader,
        image,
        evidence_class=STAGED_DIAGNOSTIC if mode != FROZEN_REPLAY else COMPARISON_REPLAY,
    )
    timings = StageTimings(
        total_ns=staged.total_ns,
        detection_ns=staged.detection_ns,
        recognition_ns=staged.recognition_ns,
        normalization_ns=staged.normalization_ns,
    )
    if mode == DETECTION_ONLY:
        # Geometry only: the text is deliberately dropped so no transcription
        # score can be read off a mode that did not claim to measure one.
        regions = tuple(
            OCRResult(text="", confidence=0.0, quad=result.quad)
            for result in staged.normalized
        )
        return regions, timings, ("transcription",)
    return tuple(staged.normalized), timings, ()


def _resolved_surface(case: CorpusCase, regions: Sequence[OCRResult]) -> str | None:
    """Ask the engine's own resolver which word the annotated pointer selects."""

    if case.expected_target is None:
        return None
    from hanly.word_resolver import WordResolver

    resolution = WordResolver.resolve_target_detail(
        list(regions), Point(*case.expected_target)
    )
    return None if resolution is None else resolution.text


def _as_region(result: OCRResult) -> Region:
    box = result.bounding_box
    return Region(result.text, box.left, box.top, box.right, box.bottom)


def _latency(results: Sequence[CaseResult]) -> dict[str, Any] | None:
    """Percentiles derived from the retained raw durations, never from a mean."""

    durations = sorted(
        result.timings.total_ns for result in results if result.error is None
    )
    if not durations:
        return None
    import math

    rank = max(1, math.ceil(0.95 * len(durations)))
    return {
        "evidence_class": "derived",
        "count": len(durations),
        "min_ns": durations[0],
        "max_ns": durations[-1],
        "p50_ns": durations[len(durations) // 2],
        "p95_ns": durations[rank - 1],
    }


def write_samples(report: CampaignReport, destination: Path) -> Path:
    """Append every raw per-sample record, so a summary can be regenerated."""

    import json

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8", newline="\n") as stream:
        for result in report.results:
            stream.write(
                json.dumps(
                    {
                        "case_id": result.case_id,
                        "mode": result.mode,
                        "backend": result.backend,
                        "condition": result.condition,
                        "iteration": result.iteration,
                        "evidence_class": "measured",
                        "total_ns": result.timings.total_ns,
                        "detection_ns": result.timings.detection_ns,
                        "recognition_ns": result.timings.recognition_ns,
                        "normalization_ns": result.timings.normalization_ns,
                        "region_count": len(result.regions),
                        "text": result.text,
                        "metrics": [metric.as_dict() for metric in result.metrics],
                        "unavailable": list(result.unavailable),
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return destination


def _close(candidate: Any) -> None:
    close = getattr(candidate, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def iter_case_images(corpus: Corpus) -> Iterable[tuple[CorpusCase, ROIImage]]:
    """Decode every case once, for a caller that wants them all in hand."""

    for case in corpus.cases:
        yield case, load_case_image(case)


__all__ = [
    "BACKENDS",
    "DETECTION_ONLY",
    "EASYOCR",
    "FROZEN_REPLAY",
    "MODES",
    "OCR_ONLY",
    "RECOGNITION_ONLY",
    "VISION",
    "CampaignReport",
    "CaseResult",
    "MemoryEvidence",
    "OCRBenchmarkError",
    "StageTimings",
    "current_rss",
    "iter_case_images",
    "peak_rss",
    "load_case_image",
    "run_campaign",
    "write_samples",
]
