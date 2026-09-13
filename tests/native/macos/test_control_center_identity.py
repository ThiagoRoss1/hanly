"""What macOS thinks the window child is, run on a real Cocoa session."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.hanly_fixtures.capabilities import require_display, require_modules

_CHILD_TIMEOUT_SECONDS = 300

_IDENTITY_PROGRAM = '''
import json
import re
import subprocess
import threading
import time

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_process import ControlCenterProcess, bridge_operations

REPORT_PREFIX = "IDENTITY_REPORT "


def registrations(pids):
    """What LaunchServices thinks each of these processes is."""

    listing = subprocess.run(["lsappinfo", "list"], capture_output=True, text=True).stdout
    found = {}
    for block in listing.split("ASN:"):
        match = re.search(r"pid = (\\d+)", block)
        kind = re.search(r'type="([^"]+)"', block)
        if match and int(match.group(1)) in pids:
            found[int(match.group(1))] = kind.group(1) if kind else "unknown"
    return found


def descendants(root):
    rows = subprocess.run(
        ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True
    ).stdout
    children = []
    for line in rows.splitlines():
        parts = line.split()
        if len(parts) == 2 and int(parts[1]) == root:
            children.append(int(parts[0]))
    return children


class CountingBridge(ControlCenterBridge):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get_state(self):
        self.calls.append("get_state")
        return super().get_state()


def main():
    import os

    bridge = CountingBridge()
    control = ControlCenterProcess(bridge_operations(bridge))
    report = {"errors": []}
    try:
        control.show()
        waiter = threading.Event()
        for _ in range(240):
            if bridge.calls:
                break
            waiter.wait(0.25)
        report["page_reached_the_bridge"] = bool(bridge.calls)
        time.sleep(1.5)
        children = descendants(os.getpid())
        report["registrations"] = {
            str(pid): kind for pid, kind in registrations(set(children)).items()
        }
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        control.shutdown()
    print(REPORT_PREFIX + json.dumps(report), flush=True)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _require_a_desktop() -> None:
    require_modules("PyQt6.QtWebEngineWidgets", "webview")
    require_display()


def test_the_window_child_is_not_a_second_application_on_macos(tmp_path: Path) -> None:
    """One Hanly in the Dock, whatever the window is running in.

    ``Foreground`` is a full application: a Dock tile, a menu bar, and an entry
    in the app switcher. ``UIElement`` still shows windows and still takes the
    keyboard, which is what a panel owned by another process needs.
    """

    _require_a_desktop()

    program = tmp_path / "identity_child.py"
    program.write_text(_IDENTITY_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program)],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    marker = "IDENTITY_REPORT "
    line = next(
        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
    )
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    report = json.loads(line[len(marker) :])

    assert report["errors"] == []
    assert report["page_reached_the_bridge"] is True
    registrations = report["registrations"]
    assert registrations, "no owned process was registered with LaunchServices"
    assert "Foreground" not in registrations.values(), registrations
