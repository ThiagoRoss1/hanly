"""Behavioral tests for the isolated benchmark core."""

import json
from pathlib import Path

import pytest

from benchmarks.dev.metadata import MetadataError, build_metadata, write_metadata
from benchmarks.dev.run_store import RunStore, RunStoreError
from benchmarks.dev.statistics import StatisticsError, summarize


def test_metadata_is_stable_json_safe_and_redacts_sensitive_values(tmp_path: Path) -> None:
    metadata = build_metadata(
        run_id="run-fixed",
        commit="abc123",
        config={
            "api_token": "do-not-write",
            "resource_path": str(tmp_path / "private" / "database.sqlite3"),
            "threshold": 0.5,
        },
        scenario={"name": "fixture", "attempt": 1},
        versions={"hanly": "0.1.0"},
        environment={"ram_bytes": 1024, "custom": Path("relative/file")},
    )

    destination = tmp_path / "metadata.json"
    write_metadata(destination, metadata)
    loaded = json.loads(destination.read_text(encoding="utf-8"))

    assert loaded["run_id"] == "run-fixed"
    assert loaded["commit"] == "abc123"
    assert loaded["platform"]["system"]
    assert loaded["python"]["version"]
    assert loaded["cpu"]["count"] >= 1
    assert loaded["ram_bytes"] is None or loaded["ram_bytes"] > 0
    assert loaded["versions"]["hanly"] == "0.1.0"
    assert loaded["config"]["api_token"] == "[REDACTED]"
    assert str(tmp_path) not in destination.read_text(encoding="utf-8")
    assert loaded["environment"]["custom"] == "relative/file"
    assert loaded == metadata


def test_run_store_flushes_samples_and_recovers_a_partial_trailing_line(tmp_path: Path) -> None:
    metadata = build_metadata(run_id="run-1", commit="abc123", scenario={"name": "self-test"})
    store = RunStore(tmp_path / "run", metadata)

    store.append_sample(
        evidence_class="measured",
        scenario="self-test",
        stage="capture",
        iteration=0,
        condition="warm",
        duration_ns=100,
        correctness_status="success",
    )
    store.close()

    measurements = tmp_path / "run" / "measurements.jsonl"
    with measurements.open("ab") as stream:
        stream.write(b'{"schema_version": 1, "run_id": "run-1"')

    recovered = RunStore(tmp_path / "run", metadata)
    assert recovered.read_samples() == [
        {
            "schema_version": 1,
            "run_id": "run-1",
            "evidence_class": "measured",
            "scenario": "self-test",
            "stage": "capture",
            "iteration": 0,
            "condition": "warm",
            "duration_ns": 100,
            "correctness_status": "success",
            "timestamp": recovered.read_samples()[0]["timestamp"],
        }
    ]
    recovered.close()


def test_run_store_rejects_invalid_condition_and_run_id(tmp_path: Path) -> None:
    metadata = build_metadata(run_id="run-1", commit="abc123", scenario={"name": "self-test"})
    store = RunStore(tmp_path / "run", metadata)

    with pytest.raises(RunStoreError, match="condition"):
        store.append_sample(
            evidence_class="measured",
            scenario="self-test",
            stage="capture",
            iteration=0,
            condition="hot",
            duration_ns=100,
            correctness_status="success",
        )

    with pytest.raises(RunStoreError, match="run_id"):
        store.append(
            {
                "schema_version": 1,
                "run_id": "other-run",
                "evidence_class": "measured",
                "scenario": "self-test",
                "stage": "capture",
                "iteration": 0,
                "condition": "warm",
                "duration_ns": 100,
                "correctness_status": "success",
            }
        )
    store.close()


def test_summary_uses_only_warm_successes_and_nearest_rank_p95() -> None:
    samples = [
        {"condition": "warmup", "correctness_status": "success", "duration_ns": 1},
        {"condition": "warm", "correctness_status": "failed", "duration_ns": 2},
        {"condition": "warm", "correctness_status": "success", "duration_ns": 10},
        {"condition": "warm", "correctness_status": "success", "duration_ns": 20},
        {"condition": "warm", "correctness_status": "success", "duration_ns": 30},
        {"condition": "warm", "correctness_status": "success", "duration_ns": 40},
    ]

    summary = summarize(samples)

    assert summary == {
        "evidence_class": "derived",
        "count": 4,
        "min": 10,
        "max": 40,
        "mean": 25.0,
        "p50": 25.0,
        "p95": 40,
        "duration_unit": "ns",
    }


def test_summary_rejects_empty_and_invalid_measurements() -> None:
    with pytest.raises(StatisticsError, match="warm successful"):
        summarize([])

    with pytest.raises(StatisticsError, match="duration_ns"):
        summarize([{"condition": "warm", "correctness_status": "success"}])


def test_metadata_validation_rejects_missing_required_fields(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match="run_id"):
        write_metadata(tmp_path / "metadata.json", {"schema_version": 1})
