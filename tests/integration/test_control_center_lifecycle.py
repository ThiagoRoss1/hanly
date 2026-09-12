"""Real-desktop proof that the Control Center is a window the shell can drop.

Every other Control Center test injects a fake webview or a fake spawner, so
none of them starts a GUI loop or a real process. This one launches a bounded
subprocess that plays the shell: it never creates a ``QApplication`` and never
imports Qt WebEngine, opens the real window in a child, lets the page call the
bridge across the pipe, closes the window, and opens a second one -- asserting
that the shell survived both and that Qt never reported a nested event loop.
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

#: What the shell must never load. The window's memory is only released if the
#: process that keeps running never had it in the first place.
HEAVY_MODULES = ("PyQt6.QtWebEngineWidgets", "easyocr", "torch", "kiwipiepy")

_CHILD_TIMEOUT_SECONDS = 300

_CHILD_PROGRAM = '''
import json
import sys
import threading

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_process import ControlCenterProcess, bridge_operations

REPORT_PREFIX = "LIFECYCLE_REPORT "
HEAVY_MODULES = ("PyQt6.QtWebEngineWidgets", "easyocr", "torch", "kiwipiepy")


class CountingBridge(ControlCenterBridge):
    """The real bridge, recording what the page actually asked it for."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def get_state(self):
        self.calls.append("get_state")
        return super().get_state()


def await_call(bridge, count):
    """Wait for the page to reach the parent bridge, which is the handshake."""

    waiter = threading.Event()
    for _ in range(240):
        if len(bridge.calls) >= count:
            return True
        waiter.wait(0.25)
    return False


def main():
    bridge = CountingBridge()
    notes = []
    control = ControlCenterProcess(
        bridge_operations(bridge), on_diagnostic=notes.append
    )
    report = {"errors": []}

    try:
        control.show()
        report["page_reached_the_bridge"] = await_call(bridge, 1)
        report["running_after_open"] = control.running
        report["generation_after_open"] = control.generation

        control.close()
        report["running_after_close"] = control.running

        control.show()
        report["page_reached_the_bridge_again"] = await_call(bridge, 2)
        report["generation_after_reopen"] = control.generation
        report["running_after_reopen"] = control.running

        control.shutdown()
        report["running_after_shutdown"] = control.running
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
        control.shutdown()

    report["heavy_modules_in_the_shell"] = [
        name for name in HEAVY_MODULES if name in sys.modules
    ]
    report["diagnostics"] = list(notes)
    print(REPORT_PREFIX + json.dumps(report), flush=True)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


#: The exact reproducer for the reader failure the released build produced: a
#: second ``show`` lands while the child has a reader but not yet a window.
_RACING_FOCUS_PROGRAM = '''
import json
import sys
import threading

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_process import ControlCenterProcess, bridge_operations

REPORT_PREFIX = "FOCUS_RACE_REPORT "


class CountingBridge(ControlCenterBridge):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get_state(self):
        self.calls.append("get_state")
        return super().get_state()


def await_call(bridge, count):
    waiter = threading.Event()
    for _ in range(240):
        if len(bridge.calls) >= count:
            return True
        waiter.wait(0.25)
    return False


def main():
    bridge = CountingBridge()
    notes = []
    control = ControlCenterProcess(bridge_operations(bridge), on_diagnostic=notes.append)
    report = {"errors": []}

    try:
        for cycle in range(3):
            control.show()
            # No wait: the child is still starting its window, and this used to
            # raise inside its reader and leave the page without a bridge.
            control.show()
            report[f"page_reached_the_bridge_{cycle}"] = await_call(bridge, cycle + 1)
            report[f"running_{cycle}"] = control.running
            control.close()
        report["generation"] = control.generation
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        control.shutdown()

    report["diagnostics"] = list(notes)
    print(REPORT_PREFIX + json.dumps(report), flush=True)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


#: macOS registers every process that creates a ``QApplication`` as a
#: user-facing application, which made the Control Center child a second Hanly
#: in the Dock and the app switcher beside the shell.
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


def _skip_without_a_desktop() -> None:
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    pytest.importorskip("webview")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("the Control Center lifecycle needs a real desktop session")


def test_the_window_opens_closes_and_reopens_without_touching_the_shell(
    tmp_path: Path,
) -> None:
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
    # The page itself calls the parent bridge, which is the whole proxy path:
    # JS to pywebview to the pipe to the canonical bridge and back.
    assert report["page_reached_the_bridge"] is True
    assert report["running_after_open"] is True
    assert report["generation_after_open"] == 1

    assert report["running_after_close"] is False
    assert report["page_reached_the_bridge_again"] is True
    assert report["generation_after_reopen"] == 2
    assert report["running_after_reopen"] is True
    assert report["running_after_shutdown"] is False

    assert report["heavy_modules_in_the_shell"] == []
    recorded = "\n".join(report["diagnostics"]) + child.stderr
    assert NESTED_LOOP_WARNING not in recorded


def test_focusing_a_window_that_is_still_starting_keeps_the_page_connected(
    tmp_path: Path,
) -> None:
    """Three rapid double-opens, which is what reproduced the reader failure.

    The assertion is the page, not the absence of a traceback: a child whose
    reader died still shows a window, and the page falls back to its own
    placeholder state rather than reporting that nothing answered.
    """

    _skip_without_a_desktop()

    program = tmp_path / "focus_race_child.py"
    program.write_text(_RACING_FOCUS_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program)],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    marker = "FOCUS_RACE_REPORT "
    line = next(
        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
    )
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    report = json.loads(line[len(marker) :])

    assert report["errors"] == []
    for cycle in range(3):
        assert report[f"page_reached_the_bridge_{cycle}"] is True
        assert report[f"running_{cycle}"] is True
    # One window per cycle: focusing must never spawn a second child.
    assert report["generation"] == 3
    assert "ControlCenterUnavailable" not in child.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS application identity")
def test_the_window_child_is_not_a_second_application_on_macos(tmp_path: Path) -> None:
    """One Hanly in the Dock, whatever the window is running in.

    ``Foreground`` is a full application: a Dock tile, a menu bar, and an entry
    in the app switcher. ``UIElement`` still shows windows and still takes the
    keyboard, which is what a panel owned by another process needs.
    """

    _skip_without_a_desktop()

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
