"""Real-process proof that Qt WebEngine starts through the shared application.

Every other Control Center test injects a fake webview, so none of them ever
initializes Chromium. This one does: it launches a bounded subprocess that
builds the production ``QApplication`` and loads a document in a real
``QWebEngineView``. Surviving a few seconds is not the assertion -- the child
must report a finished load and exit cleanly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

#: Printed by the child only after ``loadFinished(True)``.
LOADED_MARKER = "WEBENGINE_LOADED"

#: Generous enough for a cold Chromium start on a loaded CI runner, short
#: enough that a hung child fails the run instead of stalling it.
_CHILD_TIMEOUT_SECONDS = 300

_CHILD_PROGRAM = '''
import sys

MARKER = "WEBENGINE_LOADED"
HTML = "<html><body><p>\ud55c\uad6d\uc5b4</p></body></html>"


def _report_qt_messages():
    from PyQt6.QtCore import qInstallMessageHandler

    def handler(mode, context, message):
        print(f"QT {mode} {message}", file=sys.stderr, flush=True)

    qInstallMessageHandler(handler)


def main(mode):
    from hanly_app.ocr_preload import preload_ocr_runtime

    # Production ordering: the OCR runtime loads its native libraries before
    # Qt rewrites the process library search path.
    preload_ocr_runtime()

    from hanly_app.capture_selector import _shared_application
    from hanly_app.control_center import prepare_control_center_qt

    prepare_control_center_qt()
    _report_qt_messages()

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication

    if mode == "empty-argv":
        application = QApplication([])
    else:
        application = _shared_application(QApplication)
    application.setQuitOnLastWindowClosed(False)

    view = QWebEngineView()
    status = {"code": 4}

    def finished(ok):
        status["code"] = 0 if ok else 1
        if ok:
            print(MARKER, flush=True)
        application.quit()

    view.loadFinished.connect(finished)
    view.setHtml(HTML)

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(application.quit)
    watchdog.start(120000)

    application.exec()
    return status["code"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
'''


def _skip_without_a_desktop() -> None:
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("Qt WebEngine startup needs a real display session")


def _run_child(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    program = tmp_path / "webengine_child.py"
    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(program), mode],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )


def test_the_shared_application_loads_a_document_in_qt_webengine(tmp_path: Path) -> None:
    _skip_without_a_desktop()

    child = _run_child(tmp_path, "shared")

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    assert LOADED_MARKER in child.stdout, f"stderr={child.stderr!r}"


@pytest.mark.skipif(sys.platform != "win32", reason="the abort code is Windows-specific")
def test_an_empty_argument_list_still_aborts_chromium_on_windows(tmp_path: Path) -> None:
    """The defect this fix exists for, kept executable rather than anecdotal.

    Only the Windows abort code is asserted here; every other platform asserts
    the successful contract above instead of a native exception number.
    """

    _skip_without_a_desktop()

    child = _run_child(tmp_path, "empty-argv")

    assert child.returncode != 0
    assert LOADED_MARKER not in child.stdout
    assert "the program name is not passed" in child.stderr
