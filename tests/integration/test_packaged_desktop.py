"""The release gate: a frozen bundle must look a word up using only itself.

This is the only test that runs the produced artifact. It refuses every
developer fallback -- no repository, no virtual environment, no developer
model cache -- so a bundle that passes here is one a user could actually run.

It skips when no bundle has been built, and a skip is not a pass: the native
acceptance matrix in the review handoff records where it really ran.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from hanly_app.self_check import SELF_CHECK_MODES

from tools.build_package import PackageLayout, host_platform
from tools.smoke_packaged_runtime import (
    UI_TIMEOUT_SECONDS,
    inspect_bundle,
    run_packaged_self_check,
)

ROOT = Path(__file__).parents[2]

#: Points the gate at a bundle outside ``dist/``, such as an extracted release.
BUNDLE_VARIABLE = "HANLY_PACKAGED_APP"

#: The Korean fixture the frozen OCR stack must actually read.
FIXTURE_IMAGE = ROOT / "tests" / "hanly_fixtures" / "assets" / "korean_reading_roi.png"

#: A cold frozen start imports torch, provisions KRDICT, and warms two models.
_SMOKE_TIMEOUT_SECONDS = 1800

#: The same bound the harness uses, rather than a second, smaller number: a
#: cold or memory-pressured machine can take minutes to start Chromium, and a
#: slow start is not a broken window.
_WINDOW_TIMEOUT_SECONDS = UI_TIMEOUT_SECONDS


def _bundle() -> Path:
    configured = os.environ.get(BUNDLE_VARIABLE)
    if configured:
        return Path(configured).expanduser().resolve()
    return PackageLayout.for_platform(ROOT, host_platform()).application_directory


def _require_bundle() -> Path:
    bundle = _bundle()
    if not bundle.is_dir():
        pytest.skip(
            f"no frozen bundle at {bundle}; build one with tools/build_package.py "
            f"or set {BUNDLE_VARIABLE}"
        )
    return bundle


def test_the_frozen_bundle_carries_every_runtime_dependency() -> None:
    inventory = inspect_bundle(_require_bundle())

    assert inventory.ok, f"missing from the bundle: {', '.join(inventory.missing)}"


def _predates_the_window_check(report: Mapping[str, object]) -> bool:
    """Whether the bundle is older than the mode rather than failing it.

    A bundle built before ``--self-check ui`` existed rejects the argument
    outright. That says the artifact on disk is stale, which is a different
    fact from a window that cannot open.
    """

    stderr = report.get("stderr")
    return report.get("exit_code") == 2 and isinstance(stderr, str) and (
        "invalid choice" in stderr
    )


def _executable() -> Path:
    bundle = _require_bundle()
    executable = bundle / ("hanly-desktop.exe" if sys.platform == "win32" else "hanly-desktop")
    if not executable.is_file():
        pytest.skip(f"no Hanly executable in {bundle}")
    return executable


def _failures(report: Mapping[str, object]) -> tuple[list[Mapping[str, object]], str]:
    stages = report.get("stages")
    recorded = [stage for stage in stages if isinstance(stage, Mapping)] if isinstance(
        stages, list
    ) else []
    failed = "; ".join(
        f"{stage.get('name')}: {stage.get('detail')}"
        for stage in recorded
        if not stage.get("ok")
    )
    return recorded, failed


def test_the_frozen_worker_becomes_ready_on_an_isolated_profile(tmp_path: Path) -> None:
    """Inventory is not evidence: the executable has to construct providers."""

    executable = _executable()

    report = run_packaged_self_check(
        executable,
        image=FIXTURE_IMAGE,
        profile=tmp_path,
        timeout=_SMOKE_TIMEOUT_SECONDS,
    )

    recorded, failures = _failures(report)

    assert report.get("ok") is True, failures or str(report)
    assert report.get("exit_code") == 0
    assert report.get("frozen") is True
    assert {stage.get("name") for stage in recorded} >= {
        "runtime",
        "lookup worker",
        "ocr",
        "morphology",
        "dictionary",
    }


def test_the_frozen_control_center_opens_and_answers_its_own_page(
    tmp_path: Path,
) -> None:
    """Ready providers behind a window that aborts is what v0.1.0 shipped."""

    # A removed mode must fail here rather than quietly become a stale bundle.
    assert "ui" in SELF_CHECK_MODES
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("the frozen window needs a real display session")

    report = run_packaged_self_check(
        _executable(),
        mode="ui",
        profile=tmp_path,
        timeout=_WINDOW_TIMEOUT_SECONDS,
    )
    if _predates_the_window_check(report):
        pytest.skip(
            f"the bundle at {_bundle()} was built before --self-check ui; "
            "rebuild it with tools/build_package.py"
        )

    recorded, failures = _failures(report)

    assert report.get("ok") is True, failures or str(report)
    assert {stage.get("name") for stage in recorded} == {
        "main window",
        "document",
        "controls",
        "bridge",
    }
    assert report.get("frozen") is True
    # Separate claim, and a separate defect if it fails: the window did its
    # work, so what is left is whether the process actually leaves.
    assert not report.get("exit_timeout"), (
        "the window opened and answered its page, but the frozen process did "
        "not exit; see the review handoff on Qt WebEngine teardown"
    )
    assert report.get("exit_code") == 0
