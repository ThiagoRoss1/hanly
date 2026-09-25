"""Copy logs, in a web view that has no clipboard of its own.

The embedded page's ``navigator.clipboard`` is missing, so its Copy action falls
back to the window's process. This drives the real page with that API removed
and reads the system clipboard back. The user's clipboard is restored after.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.hanly_fixtures.capabilities import require_display, require_modules

_CHILD_PROGRAM = '''
import json
import threading
import time

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_host import ControlCenterHost

REPORT_PREFIX = "COPY_REPORT "
host = ControlCenterHost(ControlCenterBridge(), width=1080, height=760)
report = {"errors": []}


def on_loop(action):
    done = threading.Event()
    box = []

    def run():
        try:
            box.append(action())
        finally:
            done.set()

    host._to_qt_thread(run)
    done.wait(5)
    return box[0] if box else None


def clipboard():
    from PyQt6.QtGui import QGuiApplication

    return QGuiApplication.clipboard()


def started():
    original = None
    try:
        time.sleep(2.5)
        original = on_loop(lambda: clipboard().text())
        report["direct"] = host.copy_text("synthetic direct copy")
        report["direct_read"] = on_loop(lambda: clipboard().text())
        report["refused"] = host.copy_text(12345)
        host.evaluate(
            'Object.defineProperty(navigator, "clipboard", {value: undefined, configurable: true});'
            'document.querySelector("[data-page=logs]").click(); "ok"'
        )
        time.sleep(0.6)
        host.evaluate('document.getElementById("copy-logs").click(); "ok"')
        time.sleep(1.5)
        report["summary"] = host.evaluate('document.getElementById("log-summary").textContent')
        report["error"] = host.evaluate(
            '(document.getElementById("action-error") || {}).textContent || ""'
        )
        report["page_read"] = on_loop(lambda: clipboard().text())
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        if original is not None:
            on_loop(lambda: clipboard().setText(original))
        host.close()


host.run(on_started=started)
print(REPORT_PREFIX + json.dumps(report), flush=True)
'''


def test_copy_logs_reaches_the_clipboard_without_the_page_api(tmp_path: Path) -> None:
    require_modules("PyQt6.QtWebEngineWidgets", "webview")
    require_display()
    program = tmp_path / "copy_child.py"
    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program)], capture_output=True, text=True, timeout=300, cwd=tmp_path
    )
    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    marker = "COPY_REPORT "
    line = next((item for item in child.stdout.splitlines() if item.startswith(marker)), None)
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    report = json.loads(line[len(marker) :])

    assert report["errors"] == []
    assert report["direct"] is True
    assert report["direct_read"] == "synthetic direct copy"
    assert report["refused"] is False
    assert report["summary"].startswith("Copied ")
    assert report["page_read"] != "synthetic direct copy", "the page's own copy landed"
