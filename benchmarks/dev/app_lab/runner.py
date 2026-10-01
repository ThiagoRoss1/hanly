"""Execute selected scenarios with disposable profiles and safe durable results."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.build_smoke_krdict import build_smoke_krdict
from tools.smoke_packaged_runtime import isolated_environment

from ..metadata import build_metadata
from ..run_store import RunStore
from .catalog import SCENARIOS, Scenario, select_scenarios
from .processes import Execution, execute

REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _unavailable(scenario: Scenario, bundle: Path | None, commit: str | None) -> str | None:
    if scenario.platforms and sys.platform not in scenario.platforms:
        return "unsupported_platform"
    if not scenario.targets:
        return "human_operated" if scenario.id == "LIVE-HOVER" else "windows_phase_pending"
    if scenario.needs_bundle and (bundle is None or not bundle.is_dir()):
        return "bundle_not_supplied"
    if scenario.id == "BUNDLE-IDENTITY" and not commit:
        return "expected_commit_not_supplied"
    return None


def _verdict(result: Execution) -> tuple[str, str]:
    if result.surviving_children:
        return "failed", "owned_children_survived"
    if result.timed_out:
        return "failed", "deadline_exceeded"
    if result.children_requiring_cleanup:
        return "failed", "owned_children_required_cleanup"
    if not result.output_complete:
        return "failed", "output_reader_did_not_close"
    if result.exit_code != 0 or any(
        result.counts.get(key) for key in ("failed", "error", "errors")
    ):
        return "failed", "test_failure"
    if result.counts.get("skipped") or result.counts.get("xfailed"):
        return "unavailable", "required_cases_skipped"
    if not result.counts.get("passed") or result.counts.get("xpassed"):
        return "failed", "no_verified_pass"
    if not result.process_observation_available:
        return "unavailable", "process_observation_denied"
    return "passed", "expectations_verified"


def _run_one(scenario: Scenario, bundle: Path | None, commit: str | None) -> dict[str, Any]:
    reason = _unavailable(scenario, bundle, commit)
    base: dict[str, Any] = {
        "id": scenario.id,
        "area": scenario.area,
        "evidence": scenario.evidence,
        "expected": scenario.expected,
        "duration_ms": 0.0,
        "targets": list(scenario.targets),
        "safety": "isolated_test_workspace",
    }
    if reason is not None:
        return {**base, "outcome": "unavailable", "reason": reason}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="hanly-app-lab-") as temporary:
        workspace = Path(temporary)
        environment = isolated_environment(
            os.environ,
            workspace / "settings",
            workspace / "home",
            workspace / "models",
        )
        for variable in (
            "HANLY_PACKAGED_APP",
            "HANLY_EXPECTED_SOURCE_COMMIT",
            "HANLY_REQUIRE_NATIVE",
            "HANLY_REQUIRE_PACKAGED",
            "PYTEST_ADDOPTS",
            "PYTHONHOME",
            "PYTHONPATH",
        ):
            environment.pop(variable, None)
        if bundle is not None:
            environment["HANLY_PACKAGED_APP"] = str(bundle.resolve())
        if commit is not None:
            environment["HANLY_EXPECTED_SOURCE_COMMIT"] = commit
        if scenario.id == "APP-STARTUP":
            environment["HANLY_KRDICT_DB"] = str(build_smoke_krdict(workspace / "seed.sqlite3"))
        command = [
            sys.executable,
            "-m",
            "pytest",
            "--suite",
            "all",
            "-q",
            "--tb=no",
            "-rN",
            "--disable-warnings",
            "--basetemp",
            str(workspace / "tests"),
            *scenario.targets,
        ]
        try:
            result = execute(
                command,
                cwd=str(REPO_ROOT),
                environment=environment,
                timeout_seconds=scenario.timeout_seconds,
                observe_identity=scenario.observe_identity,
            )
        except OSError:
            return {**base, "outcome": "unavailable", "reason": "process_launch_failed"}
        outcome, reason = _verdict(result)
        if outcome == "passed" and scenario.observe_identity and sys.platform == "darwin":
            if not result.identity_samples:
                outcome, reason = "unavailable", "application_identity_not_observed"
            elif scenario.id == "MAC-IDENTITY" and any(
                event["activation"] == "Foreground" for event in result.processes
            ):
                outcome, reason = "failed", "transient_foreground_child"
    return {
        **base,
        "outcome": outcome,
        "reason": reason,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        **asdict(result),
        "workspace_removed": not workspace.exists(),
    }


def run_scenarios(
    ids: tuple[str, ...],
    *,
    bundle: Path | None = None,
    expected_commit: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Persist safe results under the existing private benchmark artifact root."""

    selected = select_scenarios(ids)
    if expected_commit is not None and not _COMMIT.fullmatch(expected_commit):
        raise ValueError("expected commit must be a complete lowercase Git SHA")
    artifact_root = REPO_ROOT / "artifacts" / "benchmarks" / "runs"
    if artifact_root.resolve() != artifact_root:
        raise ValueError("the artifact root must not redirect outside the repository")
    metadata = build_metadata(repo_root=REPO_ROOT, scenario={"app_lab": list(ids)})
    run_dir = artifact_root / metadata["run_id"]
    results = []
    with RunStore(run_dir, metadata, fsync=False) as store:
        for iteration, scenario in enumerate(selected):
            result = _run_one(scenario, bundle, expected_commit)
            results.append(result)
            store.append_sample(
                evidence_class="measured",
                scenario=scenario.id,
                stage="scenario",
                iteration=iteration,
                condition="cold",
                duration_ns=round(result["duration_ms"] * 1_000_000),
                correctness_status=result["outcome"],
                reason=result["reason"],
            )
    outcomes = {item["id"]: item for item in results}
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=5,
        )
        dirty = bool(status.stdout) if status.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        dirty = None
    summary = {
        "schema_version": 1,
        "run_id": metadata["run_id"],
        "commit": metadata["commit"],
        "platform": sys.platform,
        "source_dirty": dirty,
        "results": results,
        "coverage": [
            outcomes.get(
                item.id,
                {
                    "id": item.id,
                    "area": item.area,
                    "outcome": "not_run",
                    "reason": "not_selected",
                    "evidence": item.evidence,
                    "expected": item.expected,
                },
            )
            for item in SCENARIOS
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.html").write_text(render_report(summary), encoding="utf-8")
    return run_dir, summary


def render_report(summary: dict[str, Any]) -> str:
    """Render the same safe coverage records without embedding private output."""

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(item.get(key, '')))}</td>"
            for key in ("id", "outcome", "reason", "evidence", "expected")
        )
        + "</tr>"
        for item in summary["coverage"]
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Hanly app lab</title>'
        "<style>body{font:15px system-ui;margin:32px;background:#202124;color:#eee}"
        "table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:left;"
        "border-bottom:1px solid #555}td:nth-child(2){font-weight:700}</style>"
        f"<h1>Hanly app lab</h1><p>Run {html.escape(summary['run_id'])} · "
        f"{html.escape(summary['platform'])} · {html.escape(summary['commit'])}</p>"
        "<p>Evidence describes its scope. Unavailable and unrun checks are not passes.</p>"
        "<table><thead><tr><th>Scenario</th><th>Outcome</th><th>Reason</th><th>Evidence</th>"
        f"<th>Expectation</th></tr></thead><tbody>{rows}</tbody></table></html>"
    )
