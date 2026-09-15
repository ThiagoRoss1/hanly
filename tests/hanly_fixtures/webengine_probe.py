"""The child that starts Qt WebEngine for real, and how to run it.

Shared rather than duplicated: the successful contract is every platform's,
and the Windows abort it guards against is asserted against the same child.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Printed by the child only after ``loadFinished(True)``.
LOADED_MARKER = "WEBENGINE_LOADED"

#: Generous enough for a cold Chromium start on a loaded CI runner, short
#: enough that a hung child fails the run instead of stalling it.
CHILD_TIMEOUT_SECONDS = 300

CHILD_PROGRAM = '''
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


def run_webengine_child(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    """Run the probe in a bounded child, in the mode the caller is checking."""

    program = tmp_path / "webengine_child.py"
    program.write_text(CHILD_PROGRAM, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(program), mode],
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )


__all__ = [
    "CHILD_PROGRAM",
    "CHILD_TIMEOUT_SECONDS",
    "LOADED_MARKER",
    "run_webengine_child",
]
