"""OCR measured on its own, and the stages a mode refuses to pretend it ran.

The load-bearing test here asserts that no mode constructs Kiwi or KRDICT: the
cheapest way to get a misleading OCR number is to accidentally pay for a stage
the mode claims not to run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hanly import BoundingBox, OCRResult, PixelFormat, Quad, ROIImage

from benchmarks.dev.corpus import SCHEMA_VERSION, build_corpus
from benchmarks.dev.ocr_benchmark import (
    DETECTION_ONLY,
    EASYOCR,
    FROZEN_REPLAY,
    OCR_ONLY,
    RECOGNITION_ONLY,
    VISION,
    MemoryEvidence,
    OCRBenchmarkError,
    current_rss,
    load_case_image,
    peak_rss,
    run_campaign,
    write_samples,
)


def _image(path: Path, text_rows: int = 6) -> Path:
    from PIL import Image

    image = Image.new("L", (80, 24), 255)
    for row in range(8, 8 + text_rows):
        for column in range(4, 76, 3):
            image.putpixel((column, row), 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path


def _corpus(tmp_path: Path, **case_overrides: Any) -> Any:
    _image(tmp_path / "a.png")
    case: dict[str, Any] = {
        "id": "case-a",
        "image": "a.png",
        "provenance": "local_synthetic",
        "tags": ["synthetic"],
        "expected_text": "책을",
        "expected_target": [20.0, 12.0],
        "expected_surface": "책을",
    }
    case.update(case_overrides)
    return build_corpus(
        {"schema_version": SCHEMA_VERSION, "distribution": "local", "cases": [case]},
        tmp_path / "manifest.json",
    )


class _Provider:
    """A recognizer double that records how it was used."""

    def __init__(self, text: str = "책을") -> None:
        self.text = text
        self.calls: list[ROIImage] = []
        self.closed = False

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls.append(image)
        if not self.text:
            return ()
        return (
            OCRResult(
                text=self.text,
                confidence=0.9,
                quad=Quad.from_bounding_box(BoundingBox(4, 6, 76, 20)),
            ),
        )

    def close(self) -> None:
        self.closed = True


# --- No mode wakes the rest of the pipeline ---------------------------------


def test_no_mode_constructs_kiwi_or_krdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A morphology or dictionary provider would be paid for and never used."""

    constructed: list[str] = []

    class Tripwire:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            constructed.append(type(self).__name__)

    import hanly.kiwi_provider
    import hanly.krdict_provider

    monkeypatch.setattr(hanly.kiwi_provider, "KiwiProvider", Tripwire)
    monkeypatch.setattr(hanly.krdict_provider, "KRDICTProvider", Tripwire)

    run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=1,
        samples=2,
    )

    assert constructed == []


def test_a_campaign_closes_the_provider_it_built(tmp_path: Path) -> None:
    provider = _Provider()

    run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=lambda: provider,
        warmup=0,
        samples=1,
    )

    assert provider.closed is True


def test_a_failing_case_still_closes_the_provider(tmp_path: Path) -> None:
    class Exploding(_Provider):
        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            raise RuntimeError("recognizer exploded")

    provider = Exploding()
    report = run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=lambda: provider,
        warmup=0,
        samples=1,
    )

    assert provider.closed is True
    assert all(result.error is not None for result in report.results)
    assert "recognizer exploded" in (report.results[0].error or "")


# --- Mode validation --------------------------------------------------------


def test_an_unknown_mode_or_backend_is_refused(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)

    with pytest.raises(OCRBenchmarkError, match="unknown mode"):
        run_campaign(corpus, mode="guess", backend=VISION, provider_factory=_Provider)
    with pytest.raises(OCRBenchmarkError, match="unknown backend"):
        run_campaign(corpus, mode=OCR_ONLY, backend="tesseract", provider_factory=_Provider)


@pytest.mark.parametrize("mode", [DETECTION_ONLY, RECOGNITION_ONLY])
def test_a_staged_mode_is_refused_for_a_backend_with_no_stages(
    tmp_path: Path, mode: str
) -> None:
    """Vision exposes no detector; asking for one gets a refusal, not a guess."""

    with pytest.raises(OCRBenchmarkError, match="exposes none"):
        run_campaign(
            _corpus(tmp_path), mode=mode, backend=VISION, provider_factory=_Provider
        )


def test_a_staged_mode_needs_a_reader(tmp_path: Path) -> None:
    report = run_campaign(
        _corpus(tmp_path),
        mode=DETECTION_ONLY,
        backend=EASYOCR,
        provider_factory=_Provider,
        warmup=0,
        samples=1,
    )

    assert all("needs an EasyOCR reader" in (result.error or "") for result in report.results)


# --- Conditions and timings -------------------------------------------------


def test_the_first_pass_is_cold_and_nothing_else_is(tmp_path: Path) -> None:
    report = run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=2,
        samples=3,
    )

    assert [result.condition for result in report.results] == [
        "cold",
        "warmup",
        "warmup",
        "warm",
        "warm",
        "warm",
    ]


def test_percentiles_come_from_the_retained_raw_samples(tmp_path: Path) -> None:
    report = run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=0,
        samples=5,
    )

    summary = report.summary()
    warm = summary["latency"]["warm"]
    raw = sorted(
        result.timings.total_ns for result in report.results if result.condition == "warm"
    )
    assert warm["count"] == len(raw) == 5
    assert warm["min_ns"] == raw[0] and warm["max_ns"] == raw[-1]
    assert warm["p50_ns"] == raw[len(raw) // 2]
    assert warm["evidence_class"] == "derived"


def test_only_warm_passes_are_scored(tmp_path: Path) -> None:
    """A cold or warm-up pass measures initialization, not accuracy."""

    report = run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=1,
        samples=2,
    )

    scored = {result.condition for result in report.results if result.metrics}
    assert scored == {"warm"}


def test_a_campaign_with_no_warm_samples_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OCRBenchmarkError, match="at least one warm sample"):
        run_campaign(
            _corpus(tmp_path),
            mode=OCR_ONLY,
            backend=VISION,
            provider_factory=_Provider,
            samples=0,
        )


# --- Honest unavailability --------------------------------------------------


def test_ocr_only_says_it_measured_no_separate_stages(tmp_path: Path) -> None:
    report = run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=0,
        samples=1,
    )

    result = report.results[0]
    assert set(result.unavailable) == {"detection_stage", "recognition_stage"}
    assert result.timings.detection_ns is None
    assert result.timings.recognition_ns is None


def test_unavailable_memory_is_reported_as_unavailable_not_as_zero() -> None:
    evidence = MemoryEvidence(
        baseline_rss=None, initialized_rss=None, steady_rss=None, peak_rss=None
    )
    payload = evidence.as_dict()

    assert payload["current_rss_available"] is False
    assert payload["baseline_rss_bytes"] is None
    assert payload["provider_construction_bytes"] is None
    assert payload["peak_growth_bytes"] is None


def test_memory_growth_is_derived_only_from_both_ends() -> None:
    evidence = MemoryEvidence(
        baseline_rss=100,
        initialized_rss=350,
        steady_rss=360,
        peak_rss=900,
        baseline_peak_rss=200,
    )

    assert evidence.provider_cost == 250
    assert evidence.peak_growth == 700


def test_peak_memory_is_readable_without_psutil() -> None:
    """``psutil`` is optional; the peak still has to be measurable."""

    peak = peak_rss()
    assert peak is not None and peak > 0
    current = current_rss()
    assert current is None or current > 0


# --- Raw evidence -----------------------------------------------------------


def test_every_raw_sample_is_retained_so_a_summary_can_be_regenerated(
    tmp_path: Path,
) -> None:
    report = run_campaign(
        _corpus(tmp_path),
        mode=OCR_ONLY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=1,
        samples=3,
    )
    destination = write_samples(report, tmp_path / "samples.jsonl")

    rows = [json.loads(line) for line in destination.read_text("utf-8").splitlines()]
    assert len(rows) == len(report.results) == 5
    assert {row["condition"] for row in rows} == {"cold", "warmup", "warm"}
    assert all(row["evidence_class"] == "measured" for row in rows)
    warm = [row for row in rows if row["condition"] == "warm"]
    assert all(row["metrics"] for row in warm)
    assert report.summary()["latency"]["warm"]["count"] == len(warm)


def test_a_case_image_is_checked_against_its_own_annotations(tmp_path: Path) -> None:
    from benchmarks.dev.corpus import CorpusError

    corpus = _corpus(tmp_path, expected_target=[500.0, 12.0])

    with pytest.raises(CorpusError, match="lies outside its 80x24 image"):
        load_case_image(corpus.cases[0])


def test_a_decoded_case_image_is_a_normalized_roi(tmp_path: Path) -> None:
    image = load_case_image(_corpus(tmp_path).cases[0])

    assert (image.width, image.height) == (80, 24)
    assert image.pixel_format is PixelFormat.RGB_888


def test_a_frozen_replay_is_labelled_as_a_replay(tmp_path: Path) -> None:
    report = run_campaign(
        _corpus(tmp_path),
        mode=FROZEN_REPLAY,
        backend=VISION,
        provider_factory=_Provider,
        warmup=0,
        samples=1,
    )

    assert report.mode == FROZEN_REPLAY
    assert report.summary()["mode"] == FROZEN_REPLAY
