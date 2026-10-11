"""The backend differential: fresh children, identical inputs, no winner chosen."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lab import differential
from lab.identity import run_identity


def _manifest(tmp_path: Path) -> Path:
    from PIL import Image

    Image.new("L", (20, 10), 255).save(tmp_path / "a.png")
    manifest = tmp_path / "manifest.json"
    case = {"id": "a", "image": "a.png", "provenance": "local_synthetic"}
    manifest.write_text(
        json.dumps({"schema_version": 2, "distribution": "local", "cases": [case]}), "utf-8"
    )
    return manifest


def _child_run(root: Path, fingerprint: str | None, classes: dict[str, str]) -> None:
    run = root / "child-run"
    run.mkdir(parents=True)
    cases = {case: {"classification": value} for case, value in classes.items()}
    (run / "summary.json").write_text(
        json.dumps({"errors": 0, "stability": {"classes": {}, "cases": cases}}), "utf-8"
    )
    (run / "corpus-inventory.json").write_text(json.dumps({"fingerprint": fingerprint}), "utf-8")
    rows = [
        {"case_id": case, "condition": "warm", "text": value, "first_bad_stage": None}
        for case, value in classes.items()
    ]
    (run / "samples.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")


def _fake_run(tmp_path: Path, outcomes: dict[str, Any], expected: str | None) -> Any:
    real = subprocess.run

    def run(command: list[str], **kwargs: Any) -> Any:
        if "--backend" not in command:
            # The same module answers Git for provenance; only the children are faked.
            return real(command, **kwargs)
        backend = command[command.index("--backend") + 1]
        root = Path(command[command.index("--output-root") + 1])
        outcome = outcomes[backend]
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, dict):
            _child_run(root, outcome.get("fingerprint", expected), outcome["classes"])
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", outcome)

    return run


def _differential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, Any]
) -> dict[str, Any]:
    from lab.corpus import fingerprint, load_corpus

    manifest = _manifest(tmp_path)
    expected = fingerprint(load_corpus(manifest))
    monkeypatch.setattr(differential.subprocess, "run", _fake_run(tmp_path, outcomes, expected))
    run_dir, report = differential.run_differential(
        manifest, tuple(outcomes), output_root=tmp_path / "runs", warmup=0, samples=1
    )
    assert json.loads((run_dir / "differential.json").read_text("utf-8")) == json.loads(
        json.dumps(report, default=str)
    )
    assert run_identity(run_dir).kind == "ocr_differential"
    return report


def test_shared_and_backend_specific_observations_are_told_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _differential(
        tmp_path,
        monkeypatch,
        {
            "easyocr": {
                "classes": {"a": "stable_wrong", "b": "stable_correct", "c": "stable_wrong"}
            },
            "vision": {
                "classes": {"a": "stable_correct", "b": "stable_correct", "c": "stable_wrong"}
            },
        },
    )

    assert report["categories"] == {
        "backend_specific": 1,
        "shared_pass": 1,
        "shared_failure_same_stage": 1,
    }
    assert report["cases"]["a"]["passed_by"] == ["vision"]
    assert all(entry["identical_inputs"] for entry in report["backends"].values())
    assert "winner" not in json.dumps(report).replace("no winner is chosen", "")


def test_a_missing_backend_is_unavailable_and_a_crash_is_an_initialization_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _differential(
        tmp_path,
        monkeypatch,
        {
            "easyocr": "RuntimeError: secret recognized text in a traceback",
            "vision": "SystemExit: this machine provides no Apple Vision recognizer",
        },
    )

    assert report["backends"]["vision"]["state"] == "unavailable"
    easy = report["backends"]["easyocr"]
    assert easy["state"] == "initialization_failed" and easy["error_type"] == "RuntimeError"
    assert "secret" not in json.dumps(report)
    assert report["cases"] == {}


def test_different_inputs_are_flagged_and_a_timeout_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _differential(
        tmp_path,
        monkeypatch,
        {
            "easyocr": {"classes": {"a": "stable_correct"}, "fingerprint": "sha256:other"},
            "vision": subprocess.TimeoutExpired("python", 1),
        },
    )

    assert report["backends"]["easyocr"]["identical_inputs"] is False
    assert report["backends"]["vision"]["state"] == "timed_out"
    assert report["cases"]["a"]["category"] == "single_backend"


def test_an_interrupted_differential_keeps_what_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _differential(
        tmp_path,
        monkeypatch,
        {"easyocr": {"classes": {"a": "stable_correct"}}, "vision": KeyboardInterrupt()},
    )

    assert report["status"] == "interrupted"
    assert set(report["backends"]) == {"easyocr"}


def test_a_child_message_without_an_exception_type_never_reaches_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _differential(
        tmp_path,
        monkeypatch,
        {"easyocr": "lab: no runtime configuration at /Users/someone/private.json"},
    )

    entry = report["backends"]["easyocr"]
    assert entry["state"] == "initialization_failed" and entry["error_type"] == "unknown"
    assert "someone" not in json.dumps(report)


def test_first_passes_are_not_called_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _differential(tmp_path, monkeypatch, {"easyocr": {"classes": {"a": "stable_correct"}}})

    entry = report["backends"]["easyocr"]
    assert "initialization" not in entry and "cold_passes" in entry
