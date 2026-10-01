"""Real Chromium proof that update progress does not restart the stage label."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.hanly_fixtures.capabilities import require_display, require_modules
from tools.smoke_packaged_runtime import isolated_environment


@pytest.mark.parametrize("reduced", [False, True])
def test_stage_motion_tracks_label_changes_not_progress(tmp_path: Path, reduced: bool) -> None:
    require_modules("PyQt6.QtWebEngineWidgets", "webview")
    require_display()
    environment = isolated_environment(
        os.environ,
        tmp_path / "settings",
        tmp_path / "home",
        tmp_path / "models",
    )
    if reduced:
        flags = environment.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        environment["QTWEBENGINE_CHROMIUM_FLAGS"] = flags + " --force-prefers-reduced-motion"
    child = subprocess.run(
        [sys.executable, "-m", "benchmarks.dev.app_lab.ui_probe"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        cwd=Path(__file__).resolve().parents[3],
    )
    # The probe emits only allowlisted synthetic data, never UI/profile contents.
    marker = "APP_LAB_UI "
    line = next((line for line in child.stdout.splitlines() if line.startswith(marker)), None)
    assert child.returncode == 0, f"probe exit={child.returncode}"
    assert line is not None, "the real page produced no measurements"
    report: dict[str, Any] = json.loads(line[len(marker) :])
    assert report["errors"] == []
    steps = report["steps"]
    assert len(steps) == 4 and report["idle_mode"] == "idle"
    assert all(step["visible"] and step["mode"] == "busy" for step in steps)
    assert [step["percent"] for step in steps] == ["10%", "20%", "30%", "40%"]
    assert all(step["retained"] for step in steps)
    assert all(step["iterations"] == "1" for step in steps)
    for step in steps:
        duration = float(step["duration"].removesuffix("s"))
        if step["reduced"]:
            assert duration <= 0.001
        else:
            assert 0.1 < duration <= 0.5
    assert len(steps[2]["starts"]) == 1, steps[2]
    assert len(steps[3]["starts"]) == 2, steps[3]
    if reduced:
        assert all(step["reduced"] for step in steps)
