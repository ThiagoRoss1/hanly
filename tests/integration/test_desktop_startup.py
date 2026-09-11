"""Real-process proof that the desktop opens first and becomes ready behind it.

The unit tests drive the startup coordinator with doubles. This one runs the
production `run_desktop` in a bounded subprocess against a temporary profile
and an already-built dictionary, so the whole chain -- Qt bootstrap, the one
pywebview window, background preparation, provider warm-up, readiness -- is
exercised as a user would meet it.

It reads an existing KRDICT database and never writes to the user's profile.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: The child writes its report to a file rather than a pipe. Qt WebEngine
#: spawns helper processes that inherit stdout on Windows, so waiting for the
#: pipe to close can outlive the process being measured.
_CHILD_TIMEOUT_SECONDS = 420

#: How long the probe waits for preparation to settle before giving up.
_SETTLE_SECONDS = 180

_CHILD_PROGRAM = '''
import json
import sys
import threading

SETTLE_SECONDS = 180


def main(config_path, app_config_path, report_path):
    import hanly_app.application as application

    from hanly_app.diagnostics import DiagnosticLog

    publishers = []
    real_watch = application.watch_worker_readiness

    def watch(source, publisher, **options):
        publishers.append(publisher)
        return real_watch(source, publisher, **options)

    application.watch_worker_readiness = watch

    diagnostics = DiagnosticLog()
    report = {"errors": [], "phases": []}
    done = threading.Event()

    def drive():
        # The window is already up; wait for preparation to settle behind it.
        idle = threading.Event()
        for _ in range(int(SETTLE_SECONDS / 0.25)):
            if publishers:
                status = publishers[0].status
                if not report["phases"] or report["phases"][-1] != status.phase:
                    report["phases"].append(status.phase)
                if status.phase in {"ready", "failed"}:
                    report["message"] = status.message
                    break
            idle.wait(0.25)
        else:
            report["errors"].append("runtime never settled")
        done.set()
        _quit_on_the_qt_thread()

    def _quit_on_the_qt_thread():
        # Calling QApplication.quit() straight from this thread blocks. Hanly
        # itself only ever quits from the tray, which already marshals onto
        # Qt, so the probe marshals too.
        from PyQt6.QtCore import QMetaObject, Qt
        from PyQt6.QtWidgets import QApplication

        instance = QApplication.instance()
        if instance is not None:
            QMetaObject.invokeMethod(instance, "quit", Qt.ConnectionType.QueuedConnection)

    threading.Thread(target=drive, name="startup-probe", daemon=True).start()
    try:
        status = application.run_desktop(
            config_path,
            app_config=app_config_path,
            diagnostics=diagnostics,
        )
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
        status = -1

    report["status"] = status
    report["settled"] = done.is_set()
    report["diagnostics"] = list(diagnostics.snapshot())
    with open(report_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
'''


#: The weights a packaged build ships, and what this test reads instead of
#: downloading a hundred megabytes into a temporary cache on every run.
MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")


def _existing_models() -> Path | None:
    """Find prepared EasyOCR weights, which are an input rather than a download."""

    candidates = [
        Path(__file__).parents[2]
        / "packages"
        / "hanly-app"
        / "src"
        / "hanly_app"
        / "assets"
        / "easyocr_models",
        Path.home() / ".EasyOCR" / "model",
    ]
    return next(
        (
            directory
            for directory in candidates
            if all((directory / name).is_file() for name in MODEL_FILES)
        ),
        None,
    )


def _existing_dictionary() -> Path | None:
    configured = os.environ.get("HANLY_KRDICT_DB")
    candidates = [Path(configured)] if configured else []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Hanly" / "resources" / "krdict" / "krdict.sqlite3")
    candidates.append(Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3")
    return next((path for path in candidates if path.is_file()), None)


def _skip_without_a_desktop_runtime() -> tuple[Path, Path]:
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    pytest.importorskip("webview")
    pytest.importorskip("kiwipiepy")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("desktop startup needs a real display session")
    dictionary = _existing_dictionary()
    if dictionary is None:
        pytest.skip("no built KRDICT database; see data/README.md")
    models = _existing_models()
    if models is None:
        pytest.skip("no prepared EasyOCR weights; see tools/prepare_easyocr_models.py")
    return dictionary, models


def test_the_desktop_opens_and_reaches_ready_without_starting_capture(
    tmp_path: Path,
) -> None:
    dictionary, models = _skip_without_a_desktop_runtime()

    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "skip_flat_rois": True,
                "resources": {
                    "krdict": {"kind": "krdict", "path": str(dictionary)},
                },
                "easyocr": {
                    "languages": ["ko"],
                    "model_storage_directory": str(models),
                    "download_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    program = tmp_path / "startup_child.py"
    program.write_text(
        _CHILD_PROGRAM.replace("SETTLE_SECONDS = 180", f"SETTLE_SECONDS = {_SETTLE_SECONDS}"),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    output = tmp_path / "child.out"

    with output.open("w", encoding="utf-8") as stream:
        child = subprocess.run(
            [
                sys.executable,
                str(program),
                str(config),
                str(tmp_path / "config.json"),
                str(report_path),
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=_CHILD_TIMEOUT_SECONDS,
            cwd=tmp_path,
        )

    tail = output.read_text(encoding="utf-8", errors="replace")[-4000:]
    assert report_path.is_file(), f"no report; child output:\n{tail}"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["errors"] == [], report
    assert report["phases"][-1] == "ready", report
    assert report["status"] == 0
    assert child.returncode == 0, tail
