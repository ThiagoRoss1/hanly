"""Real-process proof that Qt WebEngine starts through the shared application.

Every other Control Center test injects a fake webview, so none of them ever
initializes Chromium. This one does: it launches a bounded subprocess that
builds the production ``QApplication`` and loads a document in a real
``QWebEngineView``. Surviving a few seconds is not the assertion -- the child
must report a finished load and exit cleanly.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.hanly_fixtures.capabilities import require_display, require_modules
from tests.hanly_fixtures.webengine_probe import (
    CHILD_TIMEOUT_SECONDS,
    LOADED_MARKER,
    run_webengine_child,
)

#: The ordering the production guard enforces, checked in a process of its own:
#: ``prepare_control_center_qt`` refuses once a ``QApplication`` exists, so a
#: run that shares a process with any Qt case asserts nothing about it.
_PREPARE_PROGRAM = """
from hanly_app.control_center import prepare_control_center_qt

prepare_control_center_qt()

from PyQt6.QtWidgets import QApplication

print("NO_APPLICATION" if QApplication.instance() is None else "APPLICATION")
"""


def test_the_webengine_backend_is_prepared_before_any_qapplication_exists(
    tmp_path: Path,
) -> None:
    """Preparing the shared pywebview backend must not be what creates the
    application: the shell owns that, and a backend that made one first would
    own the event loop too."""

    require_modules("PyQt6.QtWebEngineWidgets", "webview")
    program = tmp_path / "prepare_child.py"
    program.write_text(_PREPARE_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program)],
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )

    assert child.returncode == 0, child.stderr
    assert "NO_APPLICATION" in child.stdout


def test_the_shared_application_loads_a_document_in_qt_webengine(tmp_path: Path) -> None:
    require_modules("PyQt6.QtWebEngineWidgets")
    require_display()

    child = run_webengine_child(tmp_path, "shared")

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    assert LOADED_MARKER in child.stdout, f"stderr={child.stderr!r}"
