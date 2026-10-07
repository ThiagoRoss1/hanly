"""Compatibility, occurrence matching and the derived explanations of a comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lab import pins
from lab.comparison import (
    POLICY,
    compare_outcomes,
    compatibility,
    headline,
    occurrences,
    performance,
    tour_occurrence,
)
from lab.identity import reproduction, run_identity
from lab.metadata import provenance
from lab.report.build import REGISTERED, build_report
from lab.report.campaign import build_campaign
from lab.session.stress_scoring import summarize

CLEAN = {"commit": "a" * 40, "dirty": False, "state": "clean"}
HOST = {"release": "25.6.0", "cpu_count": 10, "ram_bytes": 16 * 2**30}


def _metadata(mode: str, **overrides: Any) -> dict[str, Any]:
    block = provenance(mode, CLEAN, measurement_protocol="p1", configured_backend="vision")
    block["host"] = overrides.pop("host", HOST)
    block["platform"] = {"system": "Darwin", "release": "25.6.0", "machine": "arm64"}
    return {
        "schema_version": 1,
        "mode": mode,
        "started": "2026-10-07T10:00:00",
        "settings": {"ocr_backend": "vision"},
        "options": overrides.pop(
            "options", {"words": 2, "story_sizes": [], "word_sizes": [22], "seed": 7}
        ),
        "fixture_text_retained": overrides.pop("retained", False),
        "lab_provenance": block,
        **overrides,
    }


def _tour_row(target: str, verdict: str, **fields: Any) -> dict[str, Any]:
    return {
        "event": "tour_result",
        "target": target,
        "source": "words",
        "surface": fields.pop("surface", target),
        "expected": target,
        "font": "F",
        "font_px": 22,
        "theme": "light",
        "rule": "strict-headword-v3",
        "status": "SUCCESS" if verdict == "correct" else "NOT_FOUND",
        "lookup_ids": [1],
        "facts": {"answer_matches_expected": verdict == "correct", "has_selection": False},
        "hover_to_popup_ms": fields.pop("popup_ms", 150.0),
        **fields,
    }


def _tour(
    run: Path,
    rows: list[dict[str, Any]],
    *,
    rss: float = 500.0,
    finished: bool = True,
    fingerprint: str = "sha256:plan",
    **metadata: Any,
) -> Path:
    run.mkdir(parents=True)
    (run / "metadata.json").write_text(json.dumps(_metadata("tour", **metadata)), "utf-8")
    events = [
        {"event": "tour_planned", "t_ms": 0, "targets": len(rows), "plan_fingerprint": fingerprint},
        {"event": "lookup_stage_completed", "t_ms": 1, "stage": "ocr", "ocr_backend": "vision"},
        *({**row, "t_ms": 2 + index} for index, row in enumerate(rows)),
    ]
    if finished:
        events.append({"event": "tour_finished", "t_ms": 99})
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", "utf-8")
    sample = {"t_ms": 5, "processes": [{"pid": 2, "role": "lookup", "rss": int(rss * 2**20)}]}
    (run / "processes.jsonl").write_text(json.dumps(sample) + "\n", "utf-8")
    return run


def _digest(run: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run.iterdir())
        if path.is_file()
    }


# -- occurrences -----------------------------------------------------------------------------


def test_one_word_in_two_renderings_is_two_occurrences() -> None:
    rows = [
        {"source": "words", "surface": "가다", "font": "F", "font_px": 16, "theme": "light"},
        {"source": "words", "surface": "가다", "font": "F", "font_px": 40, "theme": "dark"},
        {"source": "words", "surface": "가다", "font": "F", "font_px": 40, "theme": "dark"},
    ]

    keys = list(occurrences(rows, tour_occurrence))

    assert keys == ["words:가다@F/16/light", "words:가다@F/40/dark", "words:가다@F/40/dark#2"]


def test_outcomes_separate_unscored_informational_and_one_sided_rows() -> None:
    def row(target: str, verdict: str) -> dict[str, Any]:
        return {"target": target, "font": "F", "font_px": 1, "theme": "t", "verdict": verdict}

    before = [row("a", "correct"), row("b", "misread"), row("c", "misread"), row("d", "obscured")]
    before += [row("e", "observed"), row("gone", "correct")]
    after = [row("a", "no_text"), row("b", "correct"), row("c", "no_text"), row("d", "correct")]
    after += [row("e", "observed"), row("new", "correct")]

    result = compare_outcomes(
        before,
        after,
        key=lambda r: f"{r['target']}@{r['font']}/{r['font_px']}/{r['theme']}",
        passes=frozenset({"correct"}),
        unscored=frozenset({"obscured"}),
        informational=frozenset({"observed"}),
        eligible=True,
    )

    assert result["correctness"] == "mixed"
    assert result["failure_set"] == {
        "retained": ["c@F/1/t"],
        "introduced": ["a@F/1/t"],
        "resolved": ["b@F/1/t"],
    }
    assert result["counts"] == {"scored_in_both": 3, "unscored_in_either": 1, "informational": 1}
    assert (result["only_before"], result["only_after"]) == (1, 1)


@pytest.mark.parametrize(
    ("eligible", "introduced", "resolved", "expected"),
    [
        (True, [], [], "unchanged"),
        (True, ["x"], [], "regressed"),
        (True, [], ["x"], "improved"),
        (False, [], ["x"], "unavailable"),
    ],
)
def test_correctness_is_only_explained_when_eligible(
    eligible: bool, introduced: list[str], resolved: list[str], expected: str
) -> None:
    before = [{"target": "x", "verdict": "misread" if resolved else "correct"}]
    after = [{"target": "x", "verdict": "misread" if introduced else "correct"}]

    result = compare_outcomes(
        before,
        after,
        key=lambda r: str(r["target"]),
        passes=frozenset({"correct"}),
        unscored=frozenset(),
        eligible=eligible,
    )

    assert result["correctness"] == expected


# -- policy -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "verdict"),
    [
        (100.0, 105.0, "within indicative band"),  # the 5 ms floor beats 5 % of 100
        (100.0, 105.1, "higher"),
        (400.0, 380.0, "within indicative band"),  # 5 % of 400 is 20
        (400.0, 379.9, "lower"),
    ],
)
def test_popup_latency_bands_are_the_named_policy(
    before: float, after: float, verdict: str
) -> None:
    row = performance("popup p50", before, after, POLICY.popup_p50, eligible=True, samples=(9, 9))

    assert row["verdict"] == verdict
    assert row["policy"] == "indicative-bands-v1" and row["samples"] == [9, 9]
    assert row["delta"] == round(after - before, 3)


def test_memory_uses_its_own_floor_and_ineligible_values_stay_raw() -> None:
    assert performance("rss", 500, 531, POLICY.sampled_rss, eligible=True)["verdict"] == (
        "within indicative band"
    )
    assert performance("rss", 1000, 1051, POLICY.sampled_rss, eligible=True)["verdict"] == "higher"
    row = performance("rss", 500, 900, POLICY.sampled_rss, eligible=False)
    assert row["verdict"] == "unavailable" and row["delta"] == 400


# -- compatibility -----------------------------------------------------------------------------


def test_identical_settings_compare_fully(tmp_path: Path) -> None:
    before = run_identity(_tour(tmp_path / "a", [_tour_row("w1", "correct")]))
    after = run_identity(_tour(tmp_path / "b", [_tour_row("w1", "correct")]))

    result = compatibility(before, after)

    assert result["status"] == "comparable" and result["reasons"] == []
    assert result["eligible"] == {"correctness": True, "latency": True, "memory": True}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            {"options": {"words": 3, "story_sizes": [], "word_sizes": [22], "seed": 7}},
            "option words",
        ),
        ({"fingerprint": "sha256:other-fonts"}, "rendered plan differs"),
    ],
)
def test_different_options_or_renderings_are_not_comparable(
    tmp_path: Path, change: dict[str, Any], reason: str
) -> None:
    before = run_identity(_tour(tmp_path / "a", [_tour_row("w1", "correct")]))
    after = run_identity(_tour(tmp_path / "b", [_tour_row("w1", "correct")], **change))

    result = compatibility(before, after)

    assert result["status"] == "not_comparable"
    assert any(reason in item for item in result["reasons"])
    assert result["eligible"]["correctness"] is False


def test_a_different_backend_is_not_comparable(tmp_path: Path) -> None:
    before = _tour(tmp_path / "a", [_tour_row("w1", "correct")])
    after = _tour(tmp_path / "b", [_tour_row("w1", "correct")])
    events = after / "events.jsonl"
    events.write_text(events.read_text("utf-8").replace('"vision"', '"easyocr"'), "utf-8")

    result = compatibility(run_identity(before), run_identity(after))

    assert result["status"] == "not_comparable"


def test_a_partial_run_or_another_host_keeps_correctness_but_not_performance(
    tmp_path: Path,
) -> None:
    before = run_identity(_tour(tmp_path / "a", [_tour_row("w1", "correct")]))
    partial = run_identity(_tour(tmp_path / "b", [_tour_row("w1", "correct")], finished=False))
    elsewhere = run_identity(
        _tour(tmp_path / "c", [_tour_row("w1", "correct")], host={**HOST, "cpu_count": 4})
    )

    for after in (partial, elsewhere):
        result = compatibility(before, after)
        assert result["status"] == "comparable"
        assert result["eligible"] == {"correctness": True, "latency": False, "memory": False}
        assert result["performance_reasons"]


def test_a_recorded_rule_change_is_a_warning_not_a_refusal(tmp_path: Path) -> None:
    before = run_identity(
        _tour(tmp_path / "a", [_tour_row("w1", "correct", rule="strict-headword-v2")])
    )
    after = run_identity(_tour(tmp_path / "b", [_tour_row("w1", "correct")]))

    result = compatibility(before, after)

    assert result["status"] == "comparable"
    assert any("re-scored under the current rule" in warning for warning in result["warnings"])


# -- reports -----------------------------------------------------------------------------------


def test_a_tour_report_explains_the_comparison_and_leaves_the_baseline_identical(
    tmp_path: Path,
) -> None:
    rows = [_tour_row("w1", "correct"), _tour_row("w2", "misread")]
    baseline = _tour(tmp_path / "base", rows, rss=500)
    current = _tour(
        tmp_path / "new",
        [_tour_row("w1", "misread", popup_ms=300.0), _tour_row("w2", "correct", popup_ms=300.0)],
        rss=900,
    )
    before = _digest(baseline)

    build_report(current, baseline=baseline)

    assert _digest(baseline) == before
    comparison = json.loads((current / "report.json").read_text("utf-8"))["comparison"]
    assert comparison["outcomes"]["correctness"] == "mixed"
    assert headline(comparison)[:3] == [
        "correctness: mixed",
        "failure set: 0 retained / 1 introduced / 1 resolved",
        "process roles: same",
    ]
    verdicts = {row["measure"]: row["verdict"] for row in comparison["performance"]}
    assert verdicts == {
        "popup p50": "higher",
        "lookup peak sampled RSS": "higher",
        "shell peak sampled RSS": "unavailable",
    }
    summary = (current / "summary.md").read_text("utf-8")
    assert "## Provenance" in summary and "- correctness: mixed" in summary
    assert "band ±" in summary and "indicative-bands-v1" in summary


def test_an_incompatible_pair_is_shown_raw_and_never_explained(tmp_path: Path) -> None:
    baseline = _tour(tmp_path / "base", [_tour_row("w1", "correct")])
    current = _tour(
        tmp_path / "new",
        [_tour_row("w1", "misread")],
        options={"words": 300, "story_sizes": [22], "seed": 7},
    )

    build_report(current, baseline=baseline)

    summary = (current / "summary.md").read_text("utf-8")
    assert "raw comparison only: not_comparable" in summary
    assert "correctness:" not in summary
    assert "(raw only)" in summary


def test_a_bare_baseline_uses_the_registered_one_or_says_there_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    _tour(runs / "base", [_tour_row("w1", "correct")])
    current = _tour(runs / "new", [_tour_row("w1", "correct")])
    monkeypatch.setattr(pins, "PINS_PATH", tmp_path / "pins.json")
    monkeypatch.setattr(pins, "RUNS_ROOT", runs)

    build_report(current, baseline=REGISTERED)
    first = json.loads((current / "report.json").read_text("utf-8"))
    assert first["comparison"] is None and "no registered baseline" in first["comparison_note"]

    pins.set_baseline(pins.load(), "base", "the standard tour")
    build_report(current, baseline=REGISTERED)
    second = json.loads((current / "report.json").read_text("utf-8"))
    assert second["comparison"]["baseline"] == "base"


def test_reproduction_is_exact_only_when_everything_is_on_record(tmp_path: Path) -> None:
    run = _tour(tmp_path / "run", [_tour_row("w1", "correct")])
    metadata = json.loads((run / "metadata.json").read_text("utf-8"))

    exact = reproduction(run_identity(run), metadata)
    assert exact["exact"] is True and exact["prerequisites"]
    assert exact["command"].endswith(
        "python -m lab tour --words 2 --story-sizes 0 --word-sizes 22 --seed 7 --backend vision"
    )

    metadata["lab_provenance"]["source"] = {**CLEAN, "dirty": True, "state": "dirty"}
    (run / "metadata.json").write_text(json.dumps(metadata), "utf-8")
    dirty = reproduction(run_identity(run), metadata)
    assert dirty["exact"] is False and any("dirty" in item for item in dirty["missing"])


# -- stress ------------------------------------------------------------------------------------


def _stress_row(target: str, family: str, verdict_fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "stress_result",
        "target": target,
        "family": family,
        "font": "F",
        "font_px": 18,
        "theme": "light",
        "rule": "stress-v1",
        "refuse": family != "word",
        "lookup_ids": [1],
        **verdict_fields,
    }


def _stress(run: Path, rows: list[dict[str, Any]]) -> Path:
    run.mkdir(parents=True)
    metadata = _metadata("stress", options={"seed": 11, "per_family": 2}, plan={"word": 2})
    (run / "metadata.json").write_text(json.dumps(metadata), "utf-8")
    events = [
        {"event": "tour_planned", "t_ms": 0, "plan_fingerprint": "sha256:p"},
        {"event": "lookup_stage_completed", "t_ms": 1, "stage": "ocr", "ocr_backend": "vision"},
        *rows,
        {"event": "tour_finished", "t_ms": 9},
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", "utf-8")
    return run


def test_a_timed_out_negative_is_not_a_false_presentation() -> None:
    rows = [
        {"family": "blank", "verdict": "timed_out"},
        {"family": "blank", "verdict": "error"},
        {"family": "blank", "verdict": "false_answer"},
        {"family": "latin", "verdict": "stale_popup"},
        {"family": "latin", "verdict": "quiet"},
    ]

    summary = summarize(rows)

    assert summary["false_positives"] == 2
    assert summary["negatives_failed_otherwise"] == 2
    assert summary["negatives_scored"] == 5


def test_a_stress_campaign_compares_with_its_baseline_without_reading_text(
    tmp_path: Path,
) -> None:
    sentinel = "센티널비교"
    correct = {"status": "SUCCESS", "facts": {"answer_matches_expected": True}}
    wrong = {"status": "NOT_FOUND", "facts": {"has_selection": False}, "recognized": [sentinel]}
    quiet = {"status": "EMPTY"}
    shown = {"status": "SUCCESS", "popup": "SUCCESS", "headword": sentinel}
    baseline = _stress(
        tmp_path / "base",
        [
            _stress_row("w1", "word", {**correct, "refuse": False}),
            _stress_row("b1", "blank", quiet),
        ],
    )
    current = _stress(
        tmp_path / "new",
        [
            _stress_row("w1", "word", {**wrong, "refuse": False}),
            _stress_row("b1", "blank", shown),
        ],
    )
    before = _digest(baseline)

    model = build_campaign(current, baseline=baseline)

    assert _digest(baseline) == before
    comparison = model["comparison"]
    assert comparison["compatibility"]["status"] == "comparable"
    assert comparison["outcomes"]["correctness"] == "regressed"
    assert sorted(comparison["outcomes"]["failure_set"]["introduced"]) == [
        "b1@F/18/light",
        "w1@F/18/light",
    ]
    for name in ("campaign.json", "campaign.md", "campaign.html"):
        assert sentinel not in (current / name).read_text("utf-8"), name
