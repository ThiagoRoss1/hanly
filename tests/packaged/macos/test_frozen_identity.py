"""What macOS thinks each process of a normally launched frozen Hanly is.

The standalone window self-check proves the page renders; it does not launch the
shell. This starts the real bundle through LaunchServices on an isolated
profile, closes the Control Center with its own close button, reactivates the
app (which by design must not resurrect it), reopens it from the tray, and
samples every owned process's activation type throughout. The shell is a
Foreground application; no child may ever be one, because a Foreground child is
a second Dock entry.

Sampling every ~100 ms cannot exclude a registration shorter than that.
"""

from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from tests.hanly_fixtures.capabilities import require_display, unavailable
from tests.packaged.shared.test_packaged_desktop import _require_bundle
from tools.build_smoke_krdict import build_smoke_krdict
from tools.smoke_packaged_runtime import isolated_environment

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS activation identity")

_INTERVAL = 0.1
#: How long an owned child may take to exit once the shell has quit.
_CHILD_GRACE = 15
_BLOCK = re.compile(r'executable path="([^"]+)"\s+pid = (\d+) type="([^"]+)"')


def _registrations() -> dict[int, tuple[str, str]]:
    """Every registered application: PID -> (executable path, activation type)."""

    listing = subprocess.run(
        ["/usr/bin/lsappinfo", "list"], capture_output=True, text=True, timeout=5
    )
    return {int(pid): (path, kind) for path, pid, kind in _BLOCK.findall(listing.stdout)}


class _Observer:
    """Samples the owned process tree and its registrations, keeping transitions."""

    def __init__(self, executable: Path) -> None:
        self._executable = str(executable.resolve())
        self.shell: psutil.Process | None = None
        self.kinds: dict[int, list[str]] = {}
        self.parents: dict[int, int] = {}
        self.webengine: set[int] = set()
        self.timeline: list[tuple[float, int, str]] = []
        self._started = time.monotonic()

    def find_shell(self, timeout: float) -> psutil.Process:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            instances = [
                pid for pid, (path, _) in _registrations().items() if path == self._executable
            ]
            for pid in instances:
                try:
                    process = psutil.Process(pid)
                    parent = process.parent()
                except psutil.Error:
                    continue
                if parent is None or parent.pid not in instances:
                    self.shell = process
                    return process
            time.sleep(_INTERVAL)
        unavailable("the frozen shell never registered with LaunchServices")
        raise AssertionError("unreachable")

    def children(self) -> list[psutil.Process]:
        assert self.shell is not None
        try:
            return self.shell.children()
        except psutil.Error:
            return []

    def sample(self) -> None:
        assert self.shell is not None
        tree = [self.shell]
        try:
            tree += self.shell.children(recursive=True)
        except psutil.Error:
            pass
        registered = _registrations()
        for process in tree:
            try:
                parent = process.ppid()
                name = process.name()
            except psutil.Error:
                continue
            self.parents.setdefault(process.pid, parent)
            if "QtWebEngineProcess" in name:
                self.webengine.add(parent)
            kind = registered.get(process.pid, ("", "unregistered"))[1]
            seen = self.kinds.setdefault(process.pid, [])
            if not seen or seen[-1] != kind:
                seen.append(kind)
                elapsed = round(time.monotonic() - self._started, 2)
                self.timeline.append((elapsed, process.pid, kind))

    def watch(self, seconds: float, until: Callable[[], bool] | None = None) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.sample()
            if until is not None and until():
                return True
            time.sleep(_INTERVAL)
        return until is None

    def control_center(self) -> psutil.Process | None:
        """The shell's child that hosts Qt WebEngine."""

        for child in self.children():
            if child.pid in self.webengine:
                return child
        return None


def _press_close_button(pid: int) -> None:
    """Close the child's window with its own close button, through Accessibility."""

    script = (
        'tell application "System Events" to tell (first process whose unix id is '
        f"{pid}) to click (first button of window 1 whose subrole is \"AXCloseButton\")"
    )
    completed = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if completed.returncode:
        unavailable(f"Accessibility could not close the Control Center: {completed.stderr.strip()}")


def _open_from_tray(pid: int) -> None:
    """Choose "Open Control Center" from the shell's menu bar status item."""

    script = (
        'tell application "System Events" to tell (first process whose unix id is '
        f"{pid}) to tell menu bar item 1 of menu bar 2\n"
        "click\n"
        'click menu item "Open Control Center" of menu 1\n'
        "end tell"
    )
    completed = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if completed.returncode:
        unavailable(f"Accessibility could not use the tray: {completed.stderr.strip()}")


def test_only_the_shell_is_ever_an_application(tmp_path: Path) -> None:
    require_display()
    bundle = _require_bundle()
    executable = bundle / "Contents" / "MacOS" / "hanly-desktop"

    settings, home, models = tmp_path / "settings", tmp_path / "home", tmp_path / "models"
    for directory in (settings, home, models):
        directory.mkdir()
    profile = settings / "hanly"
    profile.mkdir()
    # Nothing in this check may reach the release channel.
    (profile / "config.json").write_text(
        json.dumps({"update_checks_enabled": False}), encoding="utf-8"
    )
    environment = isolated_environment(
        {},
        settings,
        home,
        models,
        krdict=build_smoke_krdict(tmp_path / "seed" / "krdict.sqlite3"),
    )
    launch_env = [
        argument
        for name in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "HOME", "HANLY_KRDICT_DB")
        if name in environment
        for argument in ("--env", f"{name}={environment[name]}")
    ]

    observer = _Observer(executable)
    subprocess.run(["open", "-n", str(bundle), *launch_env], check=True, timeout=30)
    shell = observer.find_shell(60)
    try:
        assert observer.watch(120, lambda: observer.control_center() is not None), (
            "the Control Center never opened at launch"
        )
        observer.watch(3)
        first = observer.control_center()
        assert first is not None

        _press_close_button(first.pid)
        assert observer.watch(30, lambda: not first.is_running()), "closing left the child running"
        observer.watch(2)

        # A second open of a running app is a reactivation, as a Dock click is.
        # By design it never resurrects a window the user closed on purpose.
        subprocess.run(["open", str(bundle)], check=True, timeout=30)
        assert not observer.watch(
            5, lambda: observer.control_center() is not None
        ), "reactivation resurrected a deliberately closed Control Center"

        _open_from_tray(shell.pid)
        assert observer.watch(
            120,
            lambda: (child := observer.control_center()) is not None and child.pid != first.pid,
        ), "the tray did not open a new Control Center"
        observer.watch(3)
        second = observer.control_center()
        assert second is not None
    finally:
        children = observer.children()
        names = {}
        for child in children:
            try:
                names[child.pid] = " ".join(child.cmdline()[1:3])
            except psutil.Error:
                names[child.pid] = "gone"
        try:
            shell.send_signal(signal.SIGINT)
            shell.wait(30)
        except psutil.Error:
            pass
        # A child notices its parent is gone a moment later; give it that moment.
        _, survivors = psutil.wait_procs(children, timeout=_CHILD_GRACE)
        for process in survivors:
            process.kill()
        (tmp_path / "identity.json").write_text(
            json.dumps(
                {
                    "shell": shell.pid,
                    "kinds": observer.kinds,
                    "webengine_hosts": sorted(observer.webengine),
                    "timeline": observer.timeline,
                    "children_at_quit": names,
                    "survivors_after_quit": [process.pid for process in survivors],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"identity evidence: {tmp_path / 'identity.json'}", file=sys.stderr)

    assert "Foreground" in observer.kinds[shell.pid]
    children = {pid: kinds for pid, kinds in observer.kinds.items() if pid != shell.pid}
    assert first.pid in children and second.pid in children
    foreground_children = {pid: kinds for pid, kinds in children.items() if "Foreground" in kinds}
    assert not foreground_children, f"a child became a Dock application: {foreground_children}"
    assert not survivors, f"processes outlived quitting the shell: {[p.pid for p in survivors]}"
