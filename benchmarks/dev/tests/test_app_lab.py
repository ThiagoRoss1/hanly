"""Safety, evidence and continuation contracts for the whole-app lab."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from benchmarks.dev.app_lab import runner
from benchmarks.dev.app_lab.catalog import SCENARIOS, select_scenarios
from benchmarks.dev.app_lab.processes import Execution, execute, parse_test_counts
from benchmarks.dev.cli import _parser


def _execution(**changes: Any) -> Execution:
    fields: dict[str, Any] = dict(
        exit_code=0,
        timed_out=False,
        counts={"passed": 2},
        peak_rss_bytes=100,
        processes=(),
        sampling_interval_seconds=0.1,
        dropped_events=0,
    )
    fields.update(changes)
    return Execution(**fields)


@pytest.mark.parametrize("ids", [(), ("UNKNOWN",), ("SETTINGS", "SETTINGS")])
def test_unknown_empty_or_repeated_selection_is_refused(ids: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        select_scenarios(ids)


def test_catalog_targets_exist_and_each_area_is_visible() -> None:
    assert len({item.id for item in SCENARIOS}) == len(SCENARIOS)
    for scenario in SCENARIOS:
        for target in scenario.targets:
            path, _, name = target.partition("::")
            source = (runner.REPO_ROOT / path).read_text(encoding="utf-8")
            if name:
                assert f"def {name}(" in source
    assert {item.area for item in SCENARIOS} >= {
        "startup",
        "control_center",
        "capture",
        "hover_popup",
        "settings",
        "updater",
        "packaging",
        "resources",
        "processes",
    }


@pytest.mark.parametrize(
    ("changes", "outcome"),
    [
        ({}, "passed"),
        ({"counts": {"passed": 1, "skipped": 1}}, "unavailable"),
        ({"counts": {}}, "failed"),
        ({"exit_code": 1}, "failed"),
        ({"timed_out": True}, "failed"),
        ({"surviving_children": 1}, "failed"),
        ({"process_observation_available": False}, "unavailable"),
        ({"output_complete": False}, "failed"),
        ({"children_requiring_cleanup": 1}, "failed"),
    ],
)
def test_missing_skipped_failed_and_late_evidence_never_passes(
    changes: dict[str, Any],
    outcome: str,
) -> None:
    assert runner._verdict(_execution(**changes))[0] == outcome


def test_profile_output_and_inherited_options_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HANLY_KRDICT_DB", "/private/user-dictionary")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--unexpected-option")
    monkeypatch.setenv("HANLY_PACKAGED_APP", "/private/user-app")
    seen: list[Path] = []

    def fake(command: list[str], *, environment: dict[str, str], **kwargs: Any) -> Execution:
        workspace = Path(command[command.index("--basetemp") + 1]).parent
        seen.append(workspace)
        assert Path(environment["HOME"]).is_relative_to(workspace)
        assert Path(environment["XDG_CONFIG_HOME"]).is_relative_to(workspace)
        assert "HANLY_KRDICT_DB" not in environment
        assert "PYTEST_ADDOPTS" not in environment
        assert "HANLY_PACKAGED_APP" not in environment
        assert "--tb=no" in command
        return _execution()

    monkeypatch.setattr(runner, "execute", fake)
    result = runner._run_one(select_scenarios(("SETTINGS",))[0], None, None)
    assert result["outcome"] == "passed" and result["workspace_removed"] is True
    assert seen and not seen[0].exists()
    assert os.environ["HANLY_KRDICT_DB"] == "/private/user-dictionary"


def test_bundle_identity_requires_an_explicit_build_and_commit() -> None:
    scenario = select_scenarios(("BUNDLE-IDENTITY",))[0]
    assert runner._unavailable(scenario, None, None) == "bundle_not_supplied"
    assert runner._unavailable(scenario, runner.REPO_ROOT, None) == "expected_commit_not_supplied"


@pytest.mark.parametrize(
    ("samples", "events", "reason"),
    [
        (0, (), "application_identity_not_observed"),
        (2, ({"activation": "Foreground"},), "transient_foreground_child"),
    ],
)
def test_identity_needs_observation_and_refuses_a_transient_foreground_child(
    monkeypatch: pytest.MonkeyPatch,
    samples: int,
    events: tuple[dict[str, str], ...],
    reason: str,
) -> None:
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    monkeypatch.setattr(
        runner,
        "execute",
        lambda *args, **kwargs: _execution(
            identity_samples=samples,
            processes=events,
        ),
    )
    result = runner._run_one(select_scenarios(("MAC-IDENTITY",))[0], None, None)
    assert result["reason"] == reason and result["outcome"] != "passed"


def test_artifact_root_cannot_be_redirected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    try:
        artifacts.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    with pytest.raises(ValueError, match="artifact root"):
        runner.run_scenarios(("SETTINGS",))


def test_report_keeps_unrun_coverage_and_no_raw_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "execute", lambda *args, **kwargs: _execution())
    directory, summary = runner.run_scenarios(("SETTINGS",))
    assert len(summary["coverage"]) == len(SCENARIOS)
    assert summary["coverage"][0]["outcome"] == "not_run"
    files = {path.name for path in directory.iterdir()}
    assert files == {"metadata.json", "measurements.jsonl", "summary.json", "report.html"}
    assert json.loads((directory / "summary.json").read_text())["results"][0]["outcome"] == "passed"
    assert str(tmp_path) not in "".join(path.read_text() for path in directory.iterdir())


def test_output_is_bounded_and_private_text_is_not_returned(tmp_path: Path) -> None:
    result = execute(
        [sys.executable, "-c", "print('PRIVATE 초대받았어요 ' * 20000); print('3 passed in 0.1s')"],
        cwd=str(tmp_path),
        environment=os.environ,
        timeout_seconds=10,
    )
    assert result.exit_code == 0 and result.counts == {"passed": 3}
    assert "PRIVATE" not in repr(result) and "초대" not in repr(result)
    assert list(tmp_path.iterdir()) == []


def test_visual_report_escapes_content_and_shows_measurement_limits() -> None:
    report = runner.render_report(
        {
            "run_id": "test",
            "platform": "test",
            "commit": "test",
            "source_dirty": True,
            "coverage": [
                {
                    "id": "<script>",
                    "outcome": "passed",
                    "reason": "verified",
                    "evidence": "simulated",
                    "expected": "safe",
                    "duration_ms": 123,
                    "peak_rss_bytes": 2 * 1024 * 1024,
                    "processes": [
                        {
                            "elapsed_ms": 20,
                            "pid": 1234,
                            "role": "scenario_runner",
                            "activation": "not_observed",
                        }
                    ],
                }
            ],
        }
    )
    assert "<script>" not in report and "&lt;script&gt;" in report
    assert "modified checkout" in report and "not private app memory" in report
    assert "process timeline" in report and "2.0" in report


def test_a_blocked_child_is_stopped_at_the_deadline(tmp_path: Path) -> None:
    result = execute(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=str(tmp_path),
        environment=os.environ,
        timeout_seconds=0.1,
    )
    assert result.timed_out and result.exit_code != 0
    assert result.surviving_children == 0


def test_summary_uses_only_the_last_pytest_count_line() -> None:
    assert parse_test_counts("private: 99 failed\n2 passed, 1 skipped in 1.0s") == {
        "passed": 2,
        "skipped": 1,
    }


def test_denied_process_sampling_is_reported_without_raw_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.dev.app_lab import processes

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("PRIVATE 초대")

    monkeypatch.setattr(processes.psutil, "Process", denied)
    result = execute(
        [sys.executable, "-c", "print('1 passed in 0.1s')"],
        cwd=str(tmp_path),
        environment=os.environ,
        timeout_seconds=10,
    )
    assert not result.process_observation_available
    assert result.peak_rss_bytes is None
    assert "PRIVATE" not in repr(result)
    assert runner._verdict(result) == ("unavailable", "process_observation_denied")


def test_cli_requires_explicit_scenario_selection() -> None:
    assert _parser().parse_args(["app-lab", "list"]).lab_action == "list"
    with pytest.raises(SystemExit):
        _parser().parse_args(["app-lab", "run"])
