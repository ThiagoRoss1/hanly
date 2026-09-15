"""What each suite selection collects, and what it refuses to import.

A portable job runs on a machine with none of the desktop runtime; a native job
runs on a machine that has it and a window server; the packaged job runs a
frozen product. Selecting the wrong thing is not a failure anyone would notice
-- it is a green run that proved less than it looked like it did.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.hanly_fixtures import REPO_ROOT
from tests.hanly_fixtures.capabilities import REQUIRE_NATIVE, unavailable

#: pytest raises these rather than exporting them under a usable name.
Failed = pytest.fail.Exception
Skipped = pytest.skip.Exception

NATIVE_ROOT = REPO_ROOT / "tests" / "native"
PACKAGED_ROOT = REPO_ROOT / "tests" / "packaged"

#: What a portable run must never have loaded. Importing any of these is a
#: machine requirement the portable matrix does not meet.
DESKTOP_MODULES = (
    "PyQt6",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineWidgets",
    "webview",
    "easyocr",
    "torch",
    "kiwipiepy",
    "pynput",
    "mss",
)

#: Written to a temporary file and loaded with ``-p``: the modules a collection
#: pulled in are only visible from inside the process that collected them.
_REPORTER = """
import json
import os
import sys

FORBIDDEN = {forbidden!r}
REPORT = {report!r}


def pytest_collection_finish(session):
    loaded = sorted(name for name in FORBIDDEN if name in sys.modules)
    collected = [item.nodeid for item in session.items]
    with open(REPORT, "w", encoding="utf-8") as stream:
        json.dump({{"loaded": loaded, "collected": collected}}, stream)
"""


def _collect(tmp_path: Path, suite: str) -> dict[str, list[str]]:
    """Collect one suite in a clean process and report what it loaded."""

    report = tmp_path / "report.json"
    plugin = tmp_path / "suite_reporter.py"
    plugin.write_text(
        _REPORTER.format(forbidden=DESKTOP_MODULES, report=str(report)), encoding="utf-8"
    )
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--suite",
            suite,
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "suite_reporter",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env={**_child_environment(), "PYTHONPATH": str(tmp_path)},
    )
    assert report.is_file(), f"stdout={finished.stdout[-4000:]}\nstderr={finished.stderr[-4000:]}"
    return json.loads(report.read_text(encoding="utf-8"))


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    return environment


def test_the_portable_suite_imports_none_of_the_desktop_runtime(tmp_path: Path) -> None:
    """This is what lets the portable matrix run four Python versions on a
    machine with no display and no multi-gigabyte runtime installed."""

    report = _collect(tmp_path, "portable")

    assert report["loaded"] == []
    assert report["collected"]
    assert not any(
        node.startswith(("tests/native/", "tests/packaged/")) for node in report["collected"]
    )


def test_the_native_suite_is_the_shared_cases_plus_this_host_s_own(
    tmp_path: Path,
) -> None:
    report = _collect(tmp_path, "native")
    directories = {node.split("/")[2] for node in report["collected"]}

    assert all(node.startswith("tests/native/") for node in report["collected"])
    assert "shared" in directories
    assert directories <= {"shared", _host_directory()}


def test_the_packaged_suite_is_only_the_frozen_product(tmp_path: Path) -> None:
    report = _collect(tmp_path, "packaged")

    assert report["collected"]
    assert all(node.startswith("tests/packaged/") for node in report["collected"])


def test_another_platform_s_adapters_are_never_collected_on_this_host(
    tmp_path: Path,
) -> None:
    """A marker cannot do this: deselection happens after the import, and these
    modules import the adapter of an operating system that is not here."""

    foreign = [
        directory.name
        for directory in NATIVE_ROOT.iterdir()
        if directory.is_dir() and directory.name not in ("shared", _host_directory(), "__pycache__")
    ]
    assert foreign, "no other platform's directory to check against"

    collected = _collect(tmp_path, "native")["collected"]

    for name in foreign:
        assert not any(node.startswith(f"tests/native/{name}/") for node in collected), name


def test_every_native_directory_that_exists_holds_cases() -> None:
    """An empty suite is a gate that passes because it asked nothing."""

    for root in (NATIVE_ROOT, PACKAGED_ROOT):
        for directory in root.iterdir():
            if not directory.is_dir() or directory.name == "__pycache__":
                continue
            assert list(directory.glob("test_*.py")), f"{directory} holds no cases"


def test_a_missing_capability_fails_the_job_that_exists_to_exercise_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise a native runner without a display is a green run proving
    nothing, which is the only way this whole separation can be wasted."""

    monkeypatch.setenv(REQUIRE_NATIVE, "1")

    with pytest.raises(Failed, match="no display"):
        unavailable("no display")


def test_the_same_capability_only_skips_an_ordinary_developer_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REQUIRE_NATIVE, raising=False)

    with pytest.raises(Skipped, match="no display"):
        unavailable("no display")


def _host_directory() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
