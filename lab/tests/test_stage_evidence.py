"""Stage facts on controlled images, and stability kept apart from correctness."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hanly import BoundingBox, OCRResult, Quad, ROIImage

from lab.corpus import build_corpus
from lab.ocr_benchmark import OCR_ONLY, run_campaign
from lab.stage_evidence import FALSE, TRUE, UNAVAILABLE, ocr_facts, stability

SURFACE = {"text_present": True, "korean_present": True, "target": "surface", "regions": "complete"}
NO_KOREAN = {
    "text_present": True,
    "korean_present": False,
    "target": "no_korean",
    "regions": "complete",
}
EMPTY = {
    "text_present": False,
    "korean_present": False,
    "target": "no_korean",
    "regions": "complete",
}


def _corpus(tmp_path: Path, truth: dict[str, Any], **fields: Any) -> Any:
    from PIL import Image

    image = Image.new("L", (80, 24), 255)
    image.putpixel((10, 10), 0)
    image.save(tmp_path / "a.png")
    case = {
        "id": "a",
        "image": "a.png",
        "provenance": "local_synthetic",
        "truth": truth,
        "expected_target": [20.0, 12.0],
        "expected_regions": [{"text": "x", "left": 4, "top": 6, "right": 76, "bottom": 20}]
        if truth["text_present"]
        else [],
        **fields,
    }
    return build_corpus(
        {"schema_version": 2, "distribution": "local", "cases": [case]},
        tmp_path / "manifest.json",
    )


class _Scripted:
    """Answers each call with the next scripted text; an exception is raised."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers: Iterator[Any] = iter(answers)

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        answer = next(self._answers)
        if isinstance(answer, Exception):
            raise answer
        if not answer:
            return ()
        box = Quad.from_bounding_box(BoundingBox(4, 6, 76, 20))
        return (OCRResult(text=answer, confidence=0.9, quad=box),)


def _run(corpus: Any, answers: list[Any]) -> Any:
    return run_campaign(
        corpus,
        mode=OCR_ONLY,
        backend="vision",
        provider_factory=lambda: _Scripted(answers),
        warmup=0,
        samples=len(answers) - 1,
    )


def test_a_consistently_wrong_answer_is_stable_and_wrong(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, SURFACE, expected_surface="책을", expected_text="책을")

    report = _run(corpus, ["첵올", "첵올", "첵올", "첵올"])

    summary = report.summary()
    assert summary["stability"]["cases"]["a"]["classification"] == "stable_wrong"
    assert summary["stage_evidence"]["target_surface_correct"] == {FALSE: 3}
    assert summary["first_bad_stage"] == {"ocr_misread": 3}


def test_varying_outcomes_are_variable_and_errors_make_a_case_incomplete(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path, SURFACE, expected_surface="책을", expected_text="책을")

    variable = _run(corpus, ["책을", "책을", "첵을", "책을"]).summary()["stability"]["cases"]["a"]
    broken = _run(corpus, ["책을", "책을", RuntimeError("boom"), "책을"]).summary()

    assert variable["classification"] == "variable"
    assert (variable["correct"], variable["distinct_outputs"]) == (2, 2)
    case = broken["stability"]["cases"]["a"]
    assert case["classification"] == "incomplete" and case["errors"] == 1
    assert broken["first_bad_stage"] == {"processing_error": 1}


def test_false_hangul_on_a_case_without_korean_is_observed(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, NO_KOREAN, expected_text="漢字")

    summary = _run(corpus, ["로구", "로구"]).summary()

    assert summary["stage_evidence"]["false_hangul"] == {TRUE: 1}
    assert summary["stage_evidence"]["false_korean_selection"] == {TRUE: 1}
    assert summary["first_bad_stage"] == {"ocr_false_hangul": 1}
    # No UI ran, so presentation is never claimed either way.
    assert summary["stage_evidence"]["presentation"] == {UNAVAILABLE: 1}


def test_a_detector_response_is_only_claimed_where_a_detector_ran(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, EMPTY)
    case = corpus.cases[0]

    staged, _ = ocr_facts(
        case,
        mode="detection-only",
        texts=("",),
        region_count=1,
        transcribes=False,
        resolved=None,
        resolved_ran=False,
        error=False,
    )
    normalized, stage = ocr_facts(
        case,
        mode="ocr-only",
        texts=(),
        region_count=0,
        transcribes=True,
        resolved=None,
        resolved_ran=True,
        error=False,
    )

    assert staged["detector_response_on_empty"] == TRUE
    assert normalized["detector_response_on_empty"] == UNAVAILABLE
    assert normalized["false_hangul"] == FALSE and stage is None


def test_a_case_without_stated_truth_establishes_no_facts(tmp_path: Path) -> None:
    from PIL import Image

    from lab.corpus import build_corpus as build

    Image.new("L", (8, 8), 255).save(tmp_path / "b.png")
    corpus = build(
        {
            "schema_version": 1,
            "distribution": "local",
            "cases": [{"id": "b", "image": "b.png", "provenance": "local_synthetic"}],
        },
        tmp_path / "manifest.json",
    )

    summary = _run(corpus, ["가", "가"]).summary()

    assert all(set(counts) == {UNAVAILABLE} for counts in summary["stage_evidence"].values())
    assert summary["stability"]["cases"]["b"]["classification"] == "unavailable"


@pytest.mark.parametrize(
    ("oks", "outputs", "expected"),
    [
        ([True, True], ["a", "a"], "stable_correct"),
        ([True, True], ["a", "b"], "correct_with_varying_output"),
        ([False, False], ["a", "b"], "wrong_with_varying_output"),
        ([None, None], ["a", "a"], "unavailable"),
    ],
)
def test_stability_classes(oks: list[bool | None], outputs: list[str], expected: str) -> None:
    observations = [{"ok": ok, "output": out, "error": False} for ok, out in zip(oks, outputs)]

    assert stability(observations)["classification"] == expected
