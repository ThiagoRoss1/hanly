"""Diagnostic sampling and scoring must not hide OCR or fixture limitations."""

from dataclasses import replace
from pathlib import Path

import pytest
from hanly import OCRResult, Point, Quad

from lab.corpus import CorpusCase
from lab.easyocr_audit import alphabet_report, assess, select_cases, summarize


def _case(name: str, font: str = "normal") -> CorpusCase:
    return CorpusCase(
        name, Path("unused.png"), "unused.png", "local_synthetic",
        expected_text="학교에서 공부해요.", expected_surface="학교에서",
        expected_target=(15, 10), source={"font_name": font},
    )


def _reading(text: str) -> tuple[OCRResult, ...]:
    return (OCRResult(text, .9, Quad(
        Point(0, 0), Point(80, 0), Point(80, 20), Point(0, 20),
    )),)


def test_subset_balances_fonts_without_using_previous_ocr_answers() -> None:
    cases = tuple(_case(str(index), "pixel" if index < 4 else "normal") for index in range(20))
    chosen = select_cases(cases, 8)

    assert len({case.case_id for case in chosen}) == 8
    assert sum(case.source["font_name"] == "pixel" for case in chosen) == 4
    assert chosen == select_cases(tuple(reversed(cases)), 8)
    assert len(select_cases(cases, 100)) == 20


def test_private_captures_cannot_be_exported_through_this_authored_image_runner() -> None:
    with pytest.raises(ValueError, match="local_synthetic"):
        select_cases((replace(_case("one"), provenance="local_private"),), 1)


@pytest.mark.parametrize(("text", "category", "correct"), [
    ("학교에서 공부해요.", "exact_token", True),
    ("학교에셔 공부해요.", "changed_hangul", False),
    ("학교에서! 공부해요.", "non_hangul_difference", False),
])
def test_strict_scores_preserve_korean_and_punctuation_differences(
    text: str, category: str, correct: bool,
) -> None:
    result = assess(_case("one"), _reading(text))

    assert result["token_correct"] is correct
    assert result["category"] == category


def test_missing_target_and_unknown_truth_are_not_perfect_or_failed_readings() -> None:
    assert assess(_case("one"), ())["category"] == "no_target_selection"
    unknown = replace(_case("two"), expected_surface=None, expected_text=None)
    assert assess(unknown, _reading("학교에서"))["token_correct"] is None


def test_summary_keeps_execution_failures_and_unknown_truth_separate() -> None:
    rows = [
        {"variant": "product", "elapsed_ns": 1000000, **assess(_case("a"), ())},
        {"variant": "product", "error": "failed", "elapsed_ns": 2000000},
        {"variant": "product", "elapsed_ns": 3000000,
         **assess(replace(_case("b"), expected_surface=None), ())},
    ]
    result = summarize(rows)["product"]

    assert result["samples"] == 3
    assert result["errors"] == 1
    assert result["token_correct"] == 0
    assert result["token_judged"] == 1
    assert result["latency_ms"] == {"p50": 2., "p95": 3.}


def test_model_alphabet_limit_is_distinct_from_a_language_mask() -> None:
    case = replace(_case("past"), expected_surface="왔어요", expected_text="왔어요!")
    report = alphabet_report([case], "와어요!", "와어!")

    assert report["model_hangul"] == 3
    assert report["missing_from_model"] == [
        {"case_id": "past", "field": field, "characters": "왔"}
        for field in ("expected_surface", "expected_text")
    ]
    assert report["masked_by_language"] == [
        {"case_id": "past", "field": field, "characters": "요"}
        for field in ("expected_surface", "expected_text")
    ]
