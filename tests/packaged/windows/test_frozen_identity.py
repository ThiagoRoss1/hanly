"""Check the packaged Tauri root's taskbar identity and owned process family."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple, cast

import psutil
import pytest

from tests.hanly_fixtures.capabilities import require_display
from tests.packaged.shared.test_packaged_desktop import _require_bundle
from tools.build_smoke_krdict import build_smoke_krdict
from tools.smoke_packaged_runtime import isolated_environment, request_graceful_shutdown

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows app identity")

_INTERVAL = 0.1
_CHILD_GRACE = 15
_WS_EX_TOOLWINDOW = 0x80
_WS_EX_APPWINDOW = 0x40000
_GWL_EXSTYLE = -20
_GW_OWNER = 4
_DWMWA_CLOAKED = 14


class _Window(NamedTuple):
    pid: int
    handle: int
    kind: str
    taskbar: bool


def _top_level_windows() -> list[_Window]:
    """List top-level windows and whether Windows presents each to users."""

    import ctypes
    from ctypes import wintypes

    win_dll = cast(Any, getattr(ctypes, "WinDLL"))
    callback_type = cast(Any, getattr(ctypes, "WINFUNCTYPE"))
    user32 = win_dll("user32", use_last_error=True)
    dwmapi = win_dll("dwmapi", use_last_error=True)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindow.restype = wintypes.HWND
    found: list[_Window] = []

    @callback_type(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle: int, _parameter: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, name, len(name))
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

    callback = callback_type(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)
    return found


class _Observer:
    """Samples the Tauri root, Python service, WebView2 family, and windows."""

    def __init__(self, root: psutil.Process, application: Path) -> None:
        self.root = root
        self.service_executable = (
            application / "resources" / "hanly-service" / "hanly-service.exe"
        ).resolve()
        self.roles: dict[int, str] = {root.pid: "tauri-root"}
        self.taskbar_counts: dict[int, list[int]] = {}
        self.webview2: set[int] = set()
        self.legacy: set[int] = set()
        self.windows: list[_Window] = []
        self.timeline: list[tuple[float, int, str, int]] = []
        self.started = time.monotonic()

    def tree(self) -> list[psutil.Process]:
        try:
            return [self.root, *self.root.children(recursive=True)]
        except psutil.Error:
            return []

    def sample(self) -> None:
        tree = self.tree()
        for process in tree:
            try:
                name = process.name()
                executable = Path(process.exe()).resolve()
            except (OSError, psutil.Error):
                continue
            lowered = name.lower()
            if process.pid == self.root.pid:
                role = "tauri-root"
            elif executable == self.service_executable:
                role = "python-service"
            elif "msedgewebview2" in lowered:
                role = "webview2"
                self.webview2.add(process.pid)
            else:
                role = f"child:{name}"
            if "qt" in lowered or "pystray" in lowered:
                self.legacy.add(process.pid)
            self.roles[process.pid] = role

        owned = {process.pid for process in tree}
        self.windows = [window for window in _top_level_windows() if window.pid in owned]
        for process_id in owned:
            count = sum(window.taskbar for window in self.windows if window.pid == process_id)
            seen = self.taskbar_counts.setdefault(process_id, [])
            if not seen or seen[-1] != count:
                seen.append(count)
                role = self.roles.get(process_id, "?")
                elapsed = round(time.monotonic() - self.started, 2)
                self.timeline.append((elapsed, process_id, role, count))

    def service_process(self) -> psutil.Process | None:
        for process in self.tree()[1:]:
            try:
                if Path(process.exe()).resolve() == self.service_executable:
                    return process
            except (OSError, psutil.Error):
                continue
        return None

    def watch(self, seconds: float, until: Callable[[], bool] | None = None) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.sample()
            if until is not None and until():
                return True
            time.sleep(_INTERVAL)
        return until is None


def test_the_tauri_root_owns_one_persistent_window_and_the_private_service(
    tmp_path: Path,
) -> None:
    require_display()
    application = _require_bundle()
    executable = application / "hanly-desktop.exe"
    settings, home, models = tmp_path / "settings", tmp_path / "home", tmp_path / "models"
    for directory in (settings, home, models):
        directory.mkdir()
    profile = settings / "Hanly"
    profile.mkdir()
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
    launched = subprocess.Popen([str(executable)], cwd=application, env=environment)
    root = psutil.Process(launched.pid)
    observer = _Observer(root, application)
    service: psutil.Process | None = None
    exit_code: int | None = None
    survivors: list[psutil.Process] = []
    family: list[psutil.Process] = []
    try:
        assert observer.watch(
            180,
            lambda: observer.taskbar_counts.get(root.pid, [0])[-1] == 1
            and observer.service_process() is not None,
        ), "the native root did not create its window and Python service"
        observer.watch(5)
        service = observer.service_process()
        assert service is not None
        assert service.ppid() == root.pid
        assert observer.roles.get(root.pid) == "tauri-root"
        assert observer.taskbar_counts[root.pid] == [1]

        child_windows = {
            pid: counts
            for pid, counts in observer.taskbar_counts.items()
            if pid != root.pid and any(counts)
        }
        assert not child_windows, f"a child process exposed a taskbar window: {child_windows}"
        assert observer.taskbar_counts.get(service.pid) == [0]
        assert not observer.legacy, f"legacy Qt/tray processes remain: {observer.legacy}"

        family = observer.tree()[1:]
        assert request_graceful_shutdown(root.pid), "the native event loop did not accept quit"
        try:
            exit_code = launched.wait(timeout=30)
        except subprocess.TimeoutExpired:
            exit_code = None
        _, survivors = psutil.wait_procs(family, timeout=_CHILD_GRACE)
        for process in survivors:
            process.kill()
    finally:
        if launched.poll() is None:
            request_graceful_shutdown(root.pid)
            try:
                launched.wait(timeout=10)
            except subprocess.TimeoutExpired:
                launched.terminate()
                try:
                    launched.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    launched.kill()
        for process in [*family, *observer.tree()[1:]]:
            try:
                process.kill()
            except psutil.Error:
                pass
        (tmp_path / "identity.json").write_text(
            json.dumps(
                {
                    "root": root.pid,
                    "roles": observer.roles,
                    "taskbar_counts": observer.taskbar_counts,
                    "webview2_processes": sorted(observer.webview2),
                    "timeline": observer.timeline,
                    "service": None if service is None else service.pid,
                    "survivors_after_quit": [process.pid for process in survivors],
                },
                indent=1,
            ),
            encoding="utf-8",
        )

    assert exit_code == 0, f"the native root exited with {exit_code}"
    assert service is not None and observer.roles.get(service.pid) == "python-service"
    assert not survivors, f"processes outlived the native root: {[item.pid for item in survivors]}"
