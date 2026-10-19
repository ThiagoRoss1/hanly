"""Visual ownership must include pointer-transparent fixtures and reject occlusion."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from typing import Any

import pytest

from lab.session import ownership


class _Function:
    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.argtypes: list[Any] = []
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self.callback(*args)


@pytest.mark.parametrize("occluded", [False, True])
def test_windows_ownership_uses_visible_stacking_order_instead_of_input_hits(
    monkeypatch: pytest.MonkeyPatch, occluded: bool,
) -> None:
    own_handle, foreign_handle = 0x1_0000_0042, 0x1_0000_0043
    # Hidden, minimized and nonoverlapping windows precede the fixture.
    handles = [1, 2, 3, *([foreign_handle] if occluded else []), own_handle]

    def enumerate_windows(callback: Any, parameter: int) -> int:
        for handle in handles:
            if not callback(handle, parameter):
                return 0
        return 1

    def bounds(handle: int, pointer: Any) -> int:
        rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
        rect.left, rect.top = (100, 100) if handle == 3 else (0, 0)
        rect.right, rect.bottom = rect.left + 100, rect.top + 100
        return 1

    def process(handle: int, pointer: Any) -> int:
        pid = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents
        pid.value = 900 if handle == own_handle else 901
        return 1

    user32 = SimpleNamespace(
        EnumWindows=_Function(enumerate_windows),
        IsWindowVisible=_Function(lambda handle: handle != 1),
        IsIconic=_Function(lambda handle: handle == 2),
        GetWindowRect=_Function(bounds),
        GetWindowThreadProcessId=_Function(process),
    )
    monkeypatch.setattr(ownership.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)

    assert ownership.owner_at(20, 20) == (901 if occluded else 900)


def test_windows_ownership_is_unknown_when_window_enumeration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user32 = SimpleNamespace(**{
        name: _Function(lambda *_args: 0)
        for name in (
            "EnumWindows", "IsWindowVisible", "IsIconic", "GetWindowRect",
            "GetWindowThreadProcessId",
        )
    })
    monkeypatch.setattr(ownership.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)

    assert ownership.owner_at(20, 20) is None
