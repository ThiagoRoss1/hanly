"""Real accessible text for the stress campaign: lab-authored lines in an isolated Edge window.

The tour page paints its text, so UI Automation finds nothing there. A browser
exposes the text of its pages through UIA's TextPattern, which is the path
Hanly's direct text reads first, so these hovers exercise acquisition without
OCR. The window is an app-mode Edge started by the lab with its own profile
directory, showing a page the lab wrote; nothing of the person's browser is
touched or read.

Where each target character sits on screen is measured, not assumed: the page
reports the character's client rectangle over Edge's own DevTools port, and the
window manager reports where the page's content window is.
"""

from __future__ import annotations

import html
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from .. import devtools

_EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
_CONTENT_CLASS = "Chrome_RenderWidgetHostHWND"
_HWND_TOPMOST = -1
#: SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE.
_SWP_KEEP = 0x0002 | 0x0001 | 0x0010

_MEASURE = """
(() => {
  const points = [];
  for (const line of document.querySelectorAll('div.line')) {
    const text = line.firstChild;
    const middle = Math.floor(text.length / 2);
    const range = document.createRange();
    range.setStart(text, middle);
    range.setEnd(text, middle + 1);
    const rect = range.getBoundingClientRect();
    points.push([Math.round(rect.left + rect.width / 2), Math.round(rect.top + rect.height / 2)]);
  }
  return JSON.stringify(points);
})()
"""


class BrowserText:
    """One app-mode Edge window of lab text; ``points`` are screen points, one per line."""

    def __init__(self, lines: list[str], folder: Path, geometry: tuple[int, int, int, int]):
        self._lines = lines
        self._folder = folder
        self._geometry = geometry
        self._process: subprocess.Popen[bytes] | None = None
        self.points: list[tuple[int, int]] = []
        self.window_pid: int | None = None
        #: Why no points were produced: window classes found where the text should be.
        self.refusal: list[str] = []

    def __enter__(self) -> BrowserText:
        edge = next((path for path in _EDGE_PATHS if Path(path).is_file()), None)
        if edge is None or sys.platform != "win32":
            return self
        self._folder.mkdir(parents=True, exist_ok=True)
        page = self._folder / "lines.html"
        page.write_text(_page(self._lines), encoding="utf-8")
        port = _free_port()
        left, top, width, height = self._geometry
        self._process = subprocess.Popen(
            [
                edge,
                f"--user-data-dir={self._folder / 'profile'}",
                f"--remote-debugging-port={port}",
                # InPrivate never signs in, so no account dialog covers the page.
                "--inprivate",
                "--no-first-run",
                "--no-default-browser-check",
                "--force-device-scale-factor=1",
                f"--window-position={left},{top}",
                f"--window-size={width},{height}",
                f"--app={page.as_uri()}",
            ]
        )
        self.points = self._measure(port)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._process is not None:
            _stop_tree(self._process)
            self._process = None
        shutil.rmtree(self._folder / "profile", ignore_errors=True)

    def _measure(self, port: int) -> list[tuple[int, int]]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            origin = _content_origin(self._process.pid if self._process else 0)
            if origin is not None and devtools.page_targets(port):
                try:
                    measured = json.loads(devtools.evaluate(port, _MEASURE))
                except (OSError, ValueError, TypeError):
                    measured = None
                if measured and len(measured) == len(self._lines):
                    (x0, y0), pid = origin
                    points = [(x0 + x, y0 + y) for x, y in measured]
                    # A dialog or overlay of the browser's own would pass the owner
                    # check, so every point must be the page itself.
                    self.refusal = [_class_at(x, y) for x, y in points]
                    if all(name == _CONTENT_CLASS for name in self.refusal):
                        self.window_pid = pid
                        return points
            time.sleep(0.5)
        return []


def _page(lines: list[str]) -> str:
    body = "".join(f'<div class="line">{html.escape(line)}</div>' for line in lines)
    return (
        "<!doctype html><meta charset=utf-8><title>Hanly Lab text</title>"
        "<style>body{margin:0;padding:70px 140px;background:#fff;color:#1d1f23;"
        "font:30px/52px 'Malgun Gothic',sans-serif}</style>" + body
    )


def _content_origin(root_pid: int) -> tuple[tuple[int, int], int] | None:
    """Screen origin of the page's content window, and the process owning the window."""

    if sys.platform != "win32" or not root_pid:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    owned = {root_pid}
    try:
        owned |= {child.pid for child in psutil.Process(root_pid).children(recursive=True)}
    except psutil.Error:
        return None
    found: list[tuple[tuple[int, int], int]] = []

    def child(handle: int, top_pid: int) -> bool:
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(handle, name, 64)
        if name.value == _CONTENT_CLASS and user32.IsWindowVisible(handle):
            rect = wintypes.RECT()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            found.append(((rect.left, rect.top), top_pid))
        return True

    child_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(child)

    def top(handle: int, _parameter: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value in owned and user32.IsWindowVisible(handle):
            before = len(found)
            user32.EnumChildWindows(handle, child_callback, pid.value)
            if len(found) > before:
                # Above the tour page, which is itself always on top.
                user32.SetWindowPos(handle, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_KEEP)
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(top), 0
    )
    return found[0] if found else None


def _class_at(x: int, y: int) -> str:
    """The window class at a screen point, which tells page content from browser UI."""

    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handle = user32.WindowFromPoint(wintypes.POINT(x, y))
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(handle, name, 64)
    return name.value


def _stop_tree(process: subprocess.Popen[Any]) -> None:
    """Stop the browser the lab started and its own children, nothing else."""

    try:
        root = psutil.Process(process.pid)
        tree = [root, *root.children(recursive=True)]
    except psutil.Error:
        return
    for member in tree:
        try:
            member.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(tree, timeout=5)
    for member in alive:
        try:
            member.kill()
        except psutil.Error:
            pass


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


__all__ = ["BrowserText"]
