"""Real-desktop proof that Hanly runs one window inside one event loop.

Every other Control Center test injects a fake webview, so none of them ever
starts a GUI loop. This one launches a bounded subprocess that opens the real
window through pywebview's Qt backend, calls the bridge from the page, hides
and restores twice, and quits -- asserting on the way that Qt never reported a
nested event loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: Qt's own complaint when a second ``exec`` runs inside a live loop. This is
#: what the released build produced, and what one loop owner removes.
NESTED_LOOP_WARNING = "The event loop is already running"

_CHILD_TIMEOUT_SECONDS = 300

_CHILD_PROGRAM = '''
import json
import sys
import threading

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_host import ControlCenterHost
from hanly_app.diagnostics import DiagnosticLog
from hanly_app.qt_bootstrap import ensure_qt_application

REPORT_PREFIX = "LIFECYCLE_REPORT "


class CountingBridge(ControlCenterBridge):
    """The real bridge, recording what the page actually asked it for."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def get_state(self):
        self.calls.append("get_state")
        return super().get_state()


def main():
    diagnostics = DiagnosticLog()
    ensure_qt_application(diagnostics=diagnostics)
    bridge = CountingBridge()
    host = ControlCenterHost(bridge, diagnostics=diagnostics, title="Hanly lifecycle")
    report = {"errors": []}

    def drive():
        try:
            window = host.window
            window.events.loaded.wait(60)
            deadline = threading.Event()
            for _ in range(60):
                if bridge.calls:
                    break
                deadline.wait(0.25)
            report["page_title"] = window.evaluate_js("document.title")
            report["bridge_calls"] = list(bridge.calls)

            host.set_restorable(True)
            for _ in range(2):
                host.hide()
                threading.Event().wait(0.3)
                host.show()
                threading.Event().wait(0.3)

            report["visible_before_quit"] = host.visible
            report["created_before_quit"] = host.created
            host.close()
        except BaseException as error:
            report["errors"].append(f"{type(error).__name__}: {error}")
            host.close()

    status = host.run(drive)

    report["status"] = status
    report["created_after_quit"] = host.created
    report["running_after_quit"] = host.running
    report["diagnostics"] = list(diagnostics.snapshot())
    print(REPORT_PREFIX + json.dumps(report), flush=True)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _skip_without_a_desktop() -> None:
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    pytest.importorskip("webview")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("the Control Center lifecycle needs a real desktop session")


def test_one_window_one_loop_survives_hide_restore_and_quit(tmp_path: Path) -> None:
    _skip_without_a_desktop()

    program = tmp_path / "lifecycle_child.py"
    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program)],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    marker = "LIFECYCLE_REPORT "
    line = next(
        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
    )
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    report = json.loads(line[len(marker) :])

    assert report["errors"] == []
    # The page itself calls the bridge, which is the JS handshake working.
    assert report["bridge_calls"] == ["get_state"]
    assert report["page_title"]
    assert report["visible_before_quit"] is True
    assert report["created_before_quit"] is True
    assert report["created_after_quit"] is False
    assert report["running_after_quit"] is False
    assert report["status"] == 0

    recorded = "\n".join(report["diagnostics"]) + child.stderr
    assert NESTED_LOOP_WARNING not in recorded
