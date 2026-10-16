"""Resource attribution: readings, attribution arithmetic, phases and comparison.

The calibration tests run a real child that maps a known 64 MiB, so the method
itself is checked end to end; nothing else here loads a provider.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from lab import cli
from lab.identity import run_identity
from lab.metadata import build_metadata
from lab.resources import app_phases, compare, metrics, stages
from lab.resources.experiment import ExperimentPlan, run_experiment

MIB = 2**20


def test_a_live_process_is_read_and_a_missing_metric_stays_none() -> None:
    reading = metrics.snapshot(os.getpid())

    assert reading is not None and reading.rss is not None and reading.rss > 0
    assert reading.gpu is None
    if sys.platform == "darwin":
        assert reading.footprint is not None and reading.footprint > 0
    else:
        assert reading.footprint is None
    assert metrics.primary_memory(reading) == (reading.footprint or reading.rss)


def test_a_process_that_is_gone_reads_as_nothing() -> None:
    assert metrics.snapshot(2**22 + 12345) is None


def _stage(name: str, memory: int, *, peak: int | None = None, ticks: int = 0,
           growth: int = 0, cpu: float = 0.0) -> stages.StageRecord:
    return stages.StageRecord(
        name=name,
        duration_ns=1_000_000,
        detail={},
        after={"rss": memory, "footprint": memory, "cpu_user": cpu, "cpu_system": 0.0},
        sampled_peak=peak if peak is not None else memory,
        sampled_peak_rss=peak if peak is not None else memory,
        ticks=[
            {"index": i, "latency_ns": 1_000_000 * (i + 1), "memory": memory + i * growth}
            for i in range(ticks)
        ],
    )


def _record(rows: list[stages.StageRecord]) -> stages.ExperimentRecord:
    return stages.ExperimentRecord("x", rows, exit_seconds=0.1, returncode=0)


def test_attribution_separates_load_transient_release_and_retention() -> None:
    record = _record([
        _stage("interpreter", 10 * MIB),
        _stage("runtime_validation", 20 * MIB, cpu=1.0),
        _stage("load", 21 * MIB, cpu=1.5),
        _stage("first_use", 400 * MIB, peak=500 * MIB, cpu=3.0),
        _stage("idle", 400 * MIB),
        _stage("unload", 300 * MIB),
        _stage("after_unload_idle", 250 * MIB),
    ])

    result = stages.attribute(record)
    rows = {row["stage"]: row for row in result["stages"]}

    assert rows["first_use"]["delta"] == 379 * MIB
    assert rows["first_use"]["transient_above_boundary"] == 100 * MIB
    assert rows["first_use"]["cpu_seconds"] == pytest.approx(1.5)
    derived = result["derived"]
    assert derived["loaded"] == 1 * MIB
    assert derived["ready_cost"] == 380 * MIB
    assert derived["released_by_unload"] == 100 * MIB
    assert derived["retained_after_unload"] == 230 * MIB
    assert derived["released_at_exit_only"] == 250 * MIB


def test_growth_is_reported_only_from_enough_operations() -> None:
    few = stages.attribute(_record([_stage("repeated_varied", MIB, ticks=6, growth=4096)]))
    many = stages.attribute(_record([_stage("repeated_varied", MIB, ticks=12, growth=4096)]))

    assert few["stages"][0]["growth_per_operation"] is None
    assert many["stages"][0]["growth_per_operation"] == pytest.approx(4096)
    assert many["stages"][0]["latency_ms"]["p50"] == pytest.approx(6.0)


def test_missing_readings_are_unavailable_not_zero() -> None:
    record = _record([
        stages.StageRecord("interpreter", 1, {}, None, None, None),
        _stage("runtime_validation", 5 * MIB),
    ])

    result = stages.attribute(record)

    assert result["stages"][0]["memory_after"] is None
    assert result["stages"][1]["delta"] is None
    assert result["available"]["gpu"] is False


def test_repeats_aggregate_as_median_and_range() -> None:
    runs = [
        stages.attribute(_record([_stage("load", value * MIB)])) for value in (10, 30, 20)
    ]

    spread = stages.aggregate(runs)["stages"]["load"]["memory_after"]

    assert spread == {"median": 20 * MIB, "min": 10 * MIB, "max": 30 * MIB, "n": 3}


def test_calibration_attributes_and_releases_a_known_mapping(tmp_path: Path) -> None:
    plan = {
        "mode": "component", "component": "synthetic", "runtime_config": None,
        "ocr_backend": "easyocr", "inputs_path": None, "lookups": 2,
        "idle_seconds": 0.05, "synthetic_bytes": 64 * MIB,
    }

    record = stages.run_child(plan, tmp_path / "plan.json", tmp_path / "child.log", label="cal")
    derived = stages.attribute(record)["derived"]

    assert record.error is None and record.returncode == 0
    assert derived["loaded"] == pytest.approx(64 * MIB, rel=0.1)
    assert derived["released_by_unload"] == pytest.approx(64 * MIB, rel=0.1)
    assert record.exit_seconds is not None and record.exit_seconds < 10


def test_a_calibration_only_run_is_recorded_and_recognized(tmp_path: Path) -> None:
    plan = ExperimentPlan(
        runtime_config=None, ocr_backend="easyocr", lookups=2, idle_seconds=0.05, repeats=2,
        warmup_runs=0,
    )

    run_dir = run_experiment(plan, tmp_path, report=lambda _line: None)

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert set(summary["experiments"]) == {"calibration"}
    assert "gpu" in summary["unavailable"]
    assert "Method and limits" in (run_dir / "summary.md").read_text(encoding="utf-8")
    assert run_identity(run_dir).kind == "resource_attribution"


def test_the_cli_offers_stages_session_and_compare() -> None:
    parser = cli._parser()
    for argv in (
        ["resources", "stages", "--calibration-only"],
        ["resources", "session", "some-run"],
        ["resources", "compare", "a", "b"],
    ):
        assert callable(parser.parse_args(argv).handler)


# -- session phases ------------------------------------------------------------------------


def _session_run(tmp_path: Path) -> Path:
    run = tmp_path / "20260101-000000-run"
    run.mkdir()
    events = [
        {"event": "session_started", "t_ms": 0},
        {"event": "runtime_preparation_completed", "t_ms": 1_000},
        {"event": "provider_prewarm_started", "t_ms": 2_000},
        {"event": "provider_prewarm_completed", "t_ms": 3_000},
        {"event": "lookup_submit", "t_ms": 4_000},
        {"event": "lookup_current_delivered", "t_ms": 5_000},
        {"event": "desktop_stop_requested", "t_ms": 30_000},
        {"event": "desktop_stopped", "t_ms": 31_000},
    ]
    samples = []
    for step in range(0, 33_000, 500):
        processes = [{"pid": 1, "role": "shell", "rss": 100 * MIB + step * 1024}]
        if 2_000 <= step <= 31_000:
            processes.append({"pid": 2, "role": "lookup", "rss": 500 * MIB})
        if 10_000 <= step <= 10_500:
            processes.append({"pid": 3, "role": "lookup", "rss": 500 * MIB})
        if step > 31_000:
            processes = [{"pid": 4, "role": "service", "rss": 50 * MIB}]
        samples.append({"t_ms": step, "processes": processes})
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    (run / "processes.jsonl").write_text(
        "\n".join(json.dumps(s) for s in samples), encoding="utf-8"
    )
    return run


def test_session_phases_come_from_the_sessions_own_events(tmp_path: Path) -> None:
    analysis = app_phases.analyze_session(_session_run(tmp_path))

    assert {"startup", "engine_warm", "active", "idle", "shutdown"} <= set(analysis["phases"])
    assert analysis["phases"]["idle"]["windows"] == 1
    assert analysis["duplicates"] == {"lookup": 2}
    assert analysis["after_stop"]["surviving_roles"] == ["service"]
    shell_growth = analysis["growth"]["shell"]["bytes_per_minute"]
    assert shell_growth == pytest.approx(1024 * 60_000, rel=0.01)


def test_a_session_without_samples_is_refused(tmp_path: Path) -> None:
    run = tmp_path / "empty"
    run.mkdir()
    with pytest.raises(ValueError, match="no process samples"):
        app_phases.analyze_session(run)


# -- comparison ----------------------------------------------------------------------------


def _resource_run(
    root: Path,
    name: str,
    *,
    memory: float,
    spread: float = 0.0,
    digest: str = "d1",
    inputs: str = "sha256:a",
    kiwi: str = "0.23.2",
    repeats: int = 3,
) -> Path:
    run = root / name
    run.mkdir()
    metadata = build_metadata(
        run_id=name, kind="resource_attribution",
        config={"ocr_backend": "vision", "input_digest": inputs, "protocol": stages.PROTOCOL},
        scenario={"name": "resource_attribution"},
        versions={"kiwipiepy": kiwi, "hanly": name},
        source={"commit": "a" * 40, "dirty": False, "state": "clean"},
    )

    def value(median: float) -> dict[str, Any]:
        return {"median": median, "min": median - spread, "max": median + spread, "n": repeats}

    calibration = {"loaded": value(64 * MIB), "released_by_unload": value(64 * MIB)}
    summary = {
        "protocol": stages.PROTOCOL,
        "primary_memory": "footprint",
        "input_digest": inputs,
        "plan": {"ocr_backend": "vision", "lookups": 12, "idle_seconds": 5.0, "inputs": 8,
                 "warmup_runs": 1,
                 "repeats": repeats},
        "experiments": {
            "calibration": {"aggregate": {"derived": calibration, "stages": {}}},
            "sequence": {"aggregate": {
                "derived": {"sustained_after_idle": value(memory)},
                "stages": {"idle": {"memory_after": value(memory)}},
            }},
        },
        "correctness": {"signature": [digest], "stable_across_repeats": True},
    }
    (run / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return run


def test_a_clear_saving_is_labelled_improved_but_never_accepted(tmp_path: Path) -> None:
    base = _resource_run(tmp_path, "base", memory=500 * MIB, spread=MIB)
    cand = _resource_run(tmp_path, "cand", memory=400 * MIB, spread=MIB)

    result = compare.compare(base, cand)

    assert result["comparable"] is True
    assert result["behaviour"] == "unchanged"
    assert result["calibration"] == "passed"
    row = result["experiments"]["sequence"]["derived"]["sustained_after_idle"]
    assert row["label"] == "improved"
    assert "not made here" in result["decision"]


def test_noise_overlap_and_regression_are_labelled(tmp_path: Path) -> None:
    base = _resource_run(tmp_path, "base", memory=500 * MIB, spread=MIB)
    same = _resource_run(tmp_path, "same", memory=505 * MIB, spread=MIB)
    wide = _resource_run(tmp_path, "wide", memory=560 * MIB, spread=80 * MIB)
    worse = _resource_run(tmp_path, "worse", memory=600 * MIB, spread=MIB)

    def label(candidate: Path) -> str:
        experiment = compare.compare(base, candidate)["experiments"]["sequence"]
        return str(experiment["derived"]["sustained_after_idle"]["label"])

    assert label(same) == "unchanged"
    assert label(wide) == "inconclusive"
    assert label(worse) == "regressed"


def test_a_timing_change_needs_five_repeats_a_side() -> None:
    def spread(median: float, n: int) -> dict[str, float]:
        return {"median": median, "min": median - 1, "max": median + 1, "n": n}

    assert compare._label("startup_ms", spread(1800, 3), spread(1400, 3))["label"] == (
        "inconclusive"
    )
    assert compare._label("startup_ms", spread(1800, 5), spread(1400, 5))["label"] == "improved"
    assert compare._label("loaded", spread(500 * MIB, 3), spread(300 * MIB, 3))["label"] == (
        "improved"
    )


def test_an_unfair_pair_is_refused_with_reasons(tmp_path: Path) -> None:
    base = _resource_run(tmp_path, "base", memory=500 * MIB)
    other = _resource_run(
        tmp_path, "other", memory=400 * MIB, inputs="sha256:b", kiwi="0.24.0", repeats=1,
    )

    result = compare.compare(base, other)

    assert result["comparable"] is False
    reasons = " ".join(result["reasons"])
    assert "different inputs" in reasons and "kiwipiepy" in reasons and "repeats" in reasons


def test_changed_decisions_are_reported_beside_any_saving(tmp_path: Path) -> None:
    base = _resource_run(tmp_path, "base", memory=500 * MIB)
    cand = _resource_run(tmp_path, "cand", memory=300 * MIB, digest="d2")

    assert compare.compare(base, cand)["behaviour"] == "changed"
