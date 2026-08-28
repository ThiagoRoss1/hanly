"""Integration tests for benchmark campaigns over the real engine seams."""

from __future__ import annotations

from pathlib import Path

from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TokenAnalysis,
)

from benchmarks.dev.campaigns import (
    CampaignPlan,
    ExpectedLookup,
    ObservedLookupPipeline,
    run_lookup_campaign,
    summarize_stages,
)
from benchmarks.dev.metadata import build_metadata
from benchmarks.dev.run_store import RunStore


class _OCR:
    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls += 1
        assert image.width == 20
        return (
            OCRResult(
                text="읽습니다.",
                confidence=0.98,
                quad=Quad.from_bounding_box(BoundingBox(0, 0, 20, 10)),
            ),
        )


class _Morphology:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
        self.calls += 1
        assert text == "읽습니다."
        return (TokenAnalysis(token=text, lemma="읽다"),)


class _Dictionary:
    def __init__(self) -> None:
        self.calls = 0

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.calls += 1
        assert lemma == "읽다"
        return (DictionaryEntry(headword=lemma, definitions=("to read",)),)


def test_campaign_uses_real_pipeline_seams_and_keeps_stage_and_total_timings(
    tmp_path: Path,
) -> None:
    metadata = build_metadata(run_id="campaign-1", commit="abc", scenario={"name": "fixture"})
    image = ROIImage(20, 10, PixelFormat.RGB_888, bytes(20 * 10 * 3))
    ocr = _OCR()
    morphology = _Morphology()
    dictionary = _Dictionary()

    with RunStore(tmp_path / "run", metadata, fsync=False) as store:
        pipeline = ObservedLookupPipeline(ocr, morphology, dictionary, store=store)
        results = run_lookup_campaign(
            pipeline,
            image,
            Point(10, 5),
            store=store,
            scenario="fixture",
            plan=CampaignPlan(warmup_samples=1, warm_samples=2),
            expected=ExpectedLookup(
                status="SUCCESS",
                text="읽습니다.",
                lemma="읽다",
                headword="읽다",
            ),
        )
        samples = store.read_samples()

    assert [result.status for result in results] == [LookupStatus.SUCCESS] * 4
    assert ocr.calls == morphology.calls == dictionary.calls == 4
    assert {sample["stage"] for sample in samples} == {
        "ocr",
        "token_selection",
        "morphology",
        "dictionary",
        "total_pipeline",
    }
    assert [
        sample["condition"] for sample in samples if sample["stage"] == "total_pipeline"
    ] == ["cold", "warmup", "warm", "warm"]
    assert all(sample["correctness_status"] == "success" for sample in samples)

    summaries = summarize_stages(samples)
    assert summaries["total_pipeline"]["count"] == 2
    assert summaries["ocr"]["count"] == 2


def test_campaign_records_correctness_failure_without_dropping_latency(tmp_path: Path) -> None:
    metadata = build_metadata(run_id="campaign-2", commit="abc", scenario={"name": "fixture"})
    image = ROIImage(20, 10, PixelFormat.RGB_888, bytes(20 * 10 * 3))

    with RunStore(tmp_path / "run", metadata, fsync=False) as store:
        pipeline = ObservedLookupPipeline(_OCR(), _Morphology(), _Dictionary(), store=store)
        run_lookup_campaign(
            pipeline,
            image,
            Point(10, 5),
            store=store,
            scenario="fixture",
            plan=CampaignPlan(warmup_samples=0, warm_samples=1),
            expected=ExpectedLookup(status="SUCCESS", lemma="wrong"),
        )
        total = [
            sample for sample in store.read_samples() if sample["stage"] == "total_pipeline"
        ]

    assert [sample["correctness_status"] for sample in total] == ["failed", "failed"]
    assert all(sample["duration_ns"] >= 0 for sample in total)

