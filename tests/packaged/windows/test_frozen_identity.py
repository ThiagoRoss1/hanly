"""What Windows shows for each process of a normally launched frozen Hanly.

The standalone window self-check proves the page renders; it does not launch
the shell. This starts the real executable on an isolated profile, closes the
Control Center with the message its own close button sends, reopens it from the
tray's default action, and quits from the page's own Quit control, sampling the
owned process tree and every top-level window throughout.

A window counts as a taskbar and Alt+Tab entry when it is visible, not cloaked,
and either asks for one (WS_EX_APPWINDOW) or is an unowned non-tool window. Only
the Control Center may ever have one; the shell, the lookup child and Qt
WebEngine's helpers never may. Sampling every ~100 ms cannot exclude a window
shorter-lived than that.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import psutil
import pytest

from tests.hanly_fixtures import devtools
from tests.hanly_fixtures.capabilities import require_display, unavailable
from tests.packaged.shared.test_packaged_desktop import _require_bundle
from tools.build_smoke_krdict import build_smoke_krdict
from tools.smoke_packaged_runtime import isolated_environment

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows shell identity")

_INTERVAL = 0.1
#: How long an owned child may take to exit once the shell has quit.
_CHILD_GRACE = 15
_WS_EX_TOOLWINDOW = 0x80
_WS_EX_APPWINDOW = 0x40000
_GWL_EXSTYLE = -20
_GW_OWNER = 4
_DWMWA_CLOAKED = 14
_WM_CLOSE = 0x0010
_WM_LBUTTONUP = 0x0202
#: pystray's tray callback message (``WM_USER + 11``) and its window class suffix.
_TRAY_NOTIFY = 0x400 + 11
_TRAY_CLASS_SUFFIX = "SystemTrayIcon"


class _Window(NamedTuple):
    pid: int
    handle: int
    kind: str
    taskbar: bool


def _top_level_windows() -> list[_Window]:
    """Every top-level window: owner PID, handle, class, and taskbar presence."""

    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindow.restype = wintypes.HWND
    found: list[_Window] = []

    def visit(handle: int, _parameter: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, name, 256)
        visible = bool(user32.IsWindowVisible(handle))
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(
            handle, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        style = user32.GetWindowLongPtrW(handle, _GWL_EXSTYLE)
        owned = bool(user32.GetWindow(handle, _GW_OWNER))
        listed = visible and not cloaked.value and (
            bool(style & _WS_EX_APPWINDOW) or (not style & _WS_EX_TOOLWINDOW and not owned)
        )
        found.append(_Window(int(pid.value), int(handle), name.value, bool(listed)))
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)
    return found


def _post(handle: int, message: int, wparam: int = 0, lparam: int = 0) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.user32.PostMessageW(handle, message, wparam, lparam)


class _Observer:
    """Samples the owned tree and its windows, keeping only transitions."""

    def __init__(self, shell: psutil.Process) -> None:
        self.shell = shell
        self.taskbar: dict[int, list[int]] = {}
        self.roles: dict[int, str] = {shell.pid: "shell"}
        self.webengine_hosts: set[int] = set()
        self.timeline: list[tuple[float, int, str, int]] = []
        self.windows: list[_Window] = []
        self._started = time.monotonic()

    def tree(self) -> list[psutil.Process]:
        try:
            return [self.shell, *self.shell.children(recursive=True)]
        except psutil.Error:
            return []

    def sample(self) -> None:
        tree = self.tree()
        for process in tree:
            try:
                name, parent = process.name(), process.ppid()
            except psutil.Error:
                continue
            if "QtWebEngineProcess" in name:
                self.webengine_hosts.add(parent)
                self.roles.setdefault(process.pid, "webengine_helper")
        for process in tree:
            if process.pid in self.webengine_hosts:
                self.roles[process.pid] = "control_center"
                continue
            try:
                direct = process.ppid() == self.shell.pid
                name = process.name()
            except psutil.Error:
                continue
            self.roles.setdefault(process.pid, "lookup" if direct else f"descendant:{name}")
        owned = {process.pid for process in tree}
        self.windows = [item for item in _top_level_windows() if item.pid in owned]
        for pid in owned:
            count = sum(1 for item in self.windows if item.pid == pid and item.taskbar)
            seen = self.taskbar.setdefault(pid, [])
            if not seen or seen[-1] != count:
                seen.append(count)
                elapsed = round(time.monotonic() - self._started, 2)
                self.timeline.append((elapsed, pid, self.roles.get(pid, "?"), count))

    def watch(self, seconds: float, until: Callable[[], bool] | None = None) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.sample()
            if until is not None and until():
                return True
            time.sleep(_INTERVAL)
        return until is None

    def control_center(self) -> psutil.Process | None:
        try:
            children = self.shell.children()
        except psutil.Error:
            return None
        return next((child for child in children if child.pid in self.webengine_hosts), None)

    def listed_window(self, pid: int) -> int | None:
        return next(
            (item.handle for item in self.windows if item.pid == pid and item.taskbar),
            None,
        )

    def tray_windows(self) -> list[int]:
        # pystray can leave an earlier message window beside the live one.
        return [
            item.handle
            for item in _top_level_windows()
            if item.pid == self.shell.pid and item.kind.endswith(_TRAY_CLASS_SUFFIX)
        ]


def _child_pids(shell: psutil.Process) -> list[int]:
    try:
        return [child.pid for child in shell.children()]
    except psutil.Error:
        return []


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _click(port: int, label: str) -> bool:
    script = (
        "(() => { const b = [...document.querySelectorAll('button')]"
        f".find(e => e.innerText.trim() === {json.dumps(label)});"
        " if (!b) return false; b.click(); return true; })()"
    )
    try:
        return bool(devtools.evaluate(port, script))
    except (OSError, ValueError):
        return False


def test_only_the_control_center_is_ever_a_taskbar_window(tmp_path: Path) -> None:
    require_display()
    bundle = _require_bundle()
    executable = bundle / "hanly-desktop.exe"

    settings, home, models = tmp_path / "settings", tmp_path / "home", tmp_path / "models"
    for directory in (settings, home, models):
        directory.mkdir()
    profile = settings / "Hanly"
    profile.mkdir()
    # Nothing in this check may reach the release channel.
    (profile / "config.json").write_text(
        json.dumps({"update_checks_enabled": False}), encoding="utf-8"
    )
    environment = isolated_environment(
        os.environ,
        settings,
        home,
        models,
        krdict=build_smoke_krdict(tmp_path / "seed" / "krdict.sqlite3"),
    )
    port = _free_port()
    environment["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{port}"

    launched = subprocess.Popen([str(executable)], cwd=bundle, env=environment)
    shell = psutil.Process(launched.pid)
    observer = _Observer(shell)
    survivors: list[psutil.Process] = []
    children: list[psutil.Process] = []
    try:
        assert observer.watch(
            180,
            lambda: (child := observer.control_center()) is not None
            and observer.listed_window(child.pid) is not None,
        ), "the Control Center never showed a window at launch"
        observer.watch(3)
        first = observer.control_center()
        assert first is not None

        # Starting capture is what loads the lookup engine under the default preload.
        deadline = time.monotonic() + 60
        while not _click(port, "Start capture"):
            if time.monotonic() > deadline:
                unavailable("the page's Start capture control could not be reached")
            time.sleep(0.5)
        assert observer.watch(
            180, lambda: any(pid != first.pid for pid in _child_pids(shell))
        ), "starting capture never started the lookup engine"
        observer.watch(3)
        lookup = next(pid for pid in _child_pids(shell) if pid != first.pid)

        window = observer.listed_window(first.pid)
        assert window is not None
        _post(window, _WM_CLOSE)
        assert observer.watch(30, lambda: not first.is_running()), "closing left the child running"
        assert shell.is_running(), "closing the window ended the shell"
        observer.watch(2)

        trays = observer.tray_windows()
        if not trays:
            unavailable("the shell's tray window was not found")
        for tray in trays:
            _post(tray, _TRAY_NOTIFY, 0, _WM_LBUTTONUP)
        assert observer.watch(
            180,
            lambda: (child := observer.control_center()) is not None
            and child.pid != first.pid
            and observer.listed_window(child.pid) is not None,
        ), "the tray did not open a new Control Center"
        observer.watch(3)
        second = observer.control_center()
        assert second is not None

        deadline = time.monotonic() + 60
        while not _click(port, "Quit Hanly"):
            if time.monotonic() > deadline:
                unavailable("the page's Quit control could not be reached")
            time.sleep(0.5)
        time.sleep(0.5)
        children = observer.tree()[1:]
        assert _click(port, "Quit"), "the Quit confirmation did not appear"
        try:
            exit_code = launched.wait(60)
        except subprocess.TimeoutExpired:
            exit_code = None
        _, survivors = psutil.wait_procs(children, timeout=_CHILD_GRACE)
    finally:
        for process in [*survivors, *observer.tree()]:
            try:
                process.kill()
            except psutil.Error:
                pass
        (tmp_path / "identity.json").write_text(
            json.dumps(
                {
                    "shell": shell.pid,
                    "roles": observer.roles,
                    "taskbar_counts": observer.taskbar,
                    "timeline": observer.timeline,
                    "survivors_after_quit": [process.pid for process in survivors],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"identity evidence: {tmp_path / 'identity.json'}", file=sys.stderr)

    assert exit_code == 0, f"the shell exited with {exit_code}"
    assert observer.roles.get(lookup) == "lookup"
    assert observer.taskbar.get(lookup) == [0], "the lookup engine showed a window"
    listed = {pid: counts for pid, counts in observer.taskbar.items() if any(counts)}
    assert set(listed) == {first.pid, second.pid}, f"unexpected taskbar entries: {listed}"
    assert all(max(counts) == 1 for counts in listed.values()), listed
    assert not survivors, f"processes outlived quitting the shell: {[p.pid for p in survivors]}"
