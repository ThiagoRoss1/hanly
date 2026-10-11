"""Controlled images through the stress campaign: plan, judgement and summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lab.report.campaign import corpus_summary
from lab.session.stress import corpus_plan
from lab.session.stress_scoring import CORPUS_RULE, stress_verdict, summarize

SURFACE = {"text_present": True, "korean_present": True, "target": "surface", "regions": "complete"}
NONE = {
    "text_present": False,
    "korean_present": False,
    "target": "no_korean",
    "regions": "complete",
}


def _manifest(tmp_path: Path) -> Path:
    from PIL import Image

    cases = []
    for case_id, truth, surface in (
        ("pos", SURFACE, "책을"),
        ("neg", NONE, None),
        ("vague", {**NONE, "target": "none"}, None),
    ):
        Image.new("L", (40, 20), 255).save(tmp_path / f"{case_id}.png")
        case: dict[str, Any] = {
            "id": case_id,
            "image": f"{case_id}.png",
            "provenance": "local_synthetic",
            "truth": truth,
            "expected_target": [10.0, 10.0],
            "expected_regions": [],
        }
        if surface:
            case.update(
                expected_surface=surface,
                expected_text=surface,
                expected_regions=[
                    {"text": surface, "left": 1, "top": 1, "right": 30, "bottom": 18}
                ],
            )
        cases.append(case)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 2, "distribution": "local", "cases": cases}), "utf-8"
    )
    return manifest


def test_a_corpus_becomes_rounds_of_hovers_with_stated_targets(tmp_path: Path) -> None:
    items, omitted = corpus_plan(_manifest(tmp_path), repeats=2)

    assert [item.target.id for item in items] == ["neg#1", "pos#1", "neg#2", "pos#2"]
    assert omitted == [{"case": "vague", "reason": "no stated target truth"}]
    pos = items[1]
    assert (pos.family, pos.truth_target, pos.target.surface, pos.target.refuse) == (
        "corpus",
        "surface",
        "책을",
        False,
    )
    assert items[0].target.refuse is True and items[3].repeat_of == "pos#1"


def _row(**fields: Any) -> dict[str, Any]:
    return {"family": "corpus", "truth_target": "surface", "lookup_ids": [1], **fields}


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        # A correct selection the dictionary then missed is still the right read.
        ({"status": "NOT_FOUND", "facts": {"selection_is_target": True}}, "target_selected"),
        ({"status": "SUCCESS", "facts": {"selection_is_target": True}}, "target_selected"),
        ({"status": "EMPTY", "facts": {"has_recognized_text": False}}, "no_text"),
        (
            {"status": "SUCCESS", "facts": {"has_selection": True, "surface_was_read": False}},
            "misread",
        ),
        ({"truth_target": "no_korean", "status": "SUCCESS", "popup": "SUCCESS"}, "false_answer"),
        ({"truth_target": "no_korean", "status": "EMPTY"}, "quiet"),
        ({"truth_target": "no_korean", "timed_out": True}, "timed_out"),
        ({"foreign_popups": [1], "status": "SUCCESS"}, "stale_popup"),
        ({"unscored": "obscured"}, "obscured"),
        ({"error": "x", "status": None}, "error"),
    ],
)
def test_corpus_hovers_are_judged_on_the_selected_surface(
    fields: dict[str, Any], verdict: str
) -> None:
    assert stress_verdict(_row(**fields)) == verdict


def test_a_corpus_negative_counts_as_a_negative_and_a_timeout_is_no_false_answer() -> None:
    rows = [
        {"family": "corpus", "truth_target": "no_korean", "verdict": "false_answer"},
        {"family": "corpus", "truth_target": "no_korean", "verdict": "timed_out"},
        {"family": "corpus", "truth_target": "surface", "verdict": "target_selected"},
    ]

    summary = summarize(rows)

    assert (summary["negatives_scored"], summary["false_positives"]) == (2, 1)
    assert summary["negatives_failed_otherwise"] == 1
    assert summary["positives_scored"] == 1 and summary["missing_answers"] == 0


def test_the_corpus_summary_keeps_language_outcomes_and_stability_apart() -> None:
    rows = [
        {
            "case": "pos",
            "truth_target": "surface",
            "verdict": "target_selected",
            "status": "NOT_FOUND",
        },
        {
            "case": "pos",
            "truth_target": "surface",
            "verdict": "target_selected",
            "status": "SUCCESS",
        },
        {
            "case": "neg",
            "truth_target": "no_korean",
            "verdict": "false_answer",
            "stage": "resolver",
        },
        {
            "case": "neg",
            "truth_target": "no_korean",
            "verdict": "false_answer",
            "stage": "resolver",
        },
        {"case": "odd", "truth_target": "surface", "verdict": "obscured"},
    ]

    summary = corpus_summary([{**row, "family": "corpus"} for row in rows])

    assert summary is not None and summary["rule"] == CORPUS_RULE
    assert summary["language_after_selection"] == {"NOT_FOUND": 1, "SUCCESS": 1}
    assert summary["facts"]["target_surface_correct"] == {"observed_true": 2, "unavailable": 1}
    assert summary["facts"]["false_presentation"] == {"observed_true": 2}
    assert summary["not_judged"] == {"obscured": 1}
    cases = summary["stability"]["cases"]
    assert cases["pos"]["classification"] == "stable_correct"
    assert cases["neg"]["classification"] == "stable_wrong"
    assert cases["odd"]["classification"] == "unavailable"


def test_a_cached_repeat_is_not_counted_as_a_fresh_recognition() -> None:
    rows = [
        {"case": "pos", "truth_target": "surface", "verdict": "target_selected", "cache_hits": 0},
        {"case": "pos", "truth_target": "surface", "verdict": "target_selected", "cache_hits": 1},
    ]

    summary = corpus_summary([{**row, "family": "corpus"} for row in rows])

    assert summary is not None and summary["cached_hovers"] == 1
    assert summary["stability"]["cases"]["pos"]["judged"] == 1


def test_stress_latency_keeps_cached_answers_apart() -> None:
    from lab.report.campaign import _latency

    rows = [
        {"family": "repeat", "popup": "SUCCESS", "hover_to_popup_ms": 40.0, "cache_hits": 1},
        {"family": "word", "popup": "SUCCESS", "hover_to_popup_ms": 150.0, "cache_hits": 0},
    ]

    latency = _latency(rows)

    assert latency["all"]["n"] == 1 and latency["all"]["p50"] == 150.0
    assert latency["cached"]["n"] == 1
