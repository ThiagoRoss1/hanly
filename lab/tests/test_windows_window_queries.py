"""Window-query contracts preserve 64-bit handles before native Windows validation."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from types import SimpleNamespace
from typing import Any

import pytest

from lab.session import browser_text, ownership, stress_driver

_HANDLE = 0x1_0000_0042
_CHILD = _HANDLE + 1
_PID = 72345


class _Enumeration:
    def __init__(self, callback: Callable[..., int]) -> None:
        self.callback = callback
        self.argtypes: list[type] | None = None
        self.restype: object = None

    def __call__(self, *args: Any) -> int:
        return self.callback(*args)


def _user32() -> SimpleNamespace:
    seen: list[int] = []

    def pid(handle: int, destination: Any) -> int:
        seen.append(handle)
        destination[0] = _PID if handle in {_HANDLE, _CHILD} else 0
        return _PID

    def rect(handle: int, destination: Any) -> int:
        seen.append(handle)
        destination[0] = wintypes.RECT(-120, 20, 220, 220)
        return 1

    def class_name(handle: int, destination: Any, size: int) -> int:
        seen.append(handle)
        value = browser_text._CONTENT_CLASS
        assert size > len(value)
        for index, char in enumerate(value + "\0"):
            destination[index] = char
        return len(value)

    window_at = ctypes.CFUNCTYPE(ctypes.c_void_p, wintypes.POINT)(lambda _point: _HANDLE)
    window_at.restype = ctypes.c_int
    get_pid = ctypes.CFUNCTYPE(wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))(pid)
    get_rect = ctypes.CFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT))(rect)
    get_class = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar), ctypes.c_int
    )(class_name)
    visible = ctypes.CFUNCTYPE(wintypes.BOOL, ctypes.c_void_p)(lambda _handle: 1)
    # Emulate WinDLL functions before a caller declares their native arguments.
    for function in (get_pid, get_rect, get_class, visible):
        setattr(function, "argtypes", None)

    return SimpleNamespace(
        WindowFromPoint=window_at,
        GetWindowThreadProcessId=get_pid,
        GetWindowRect=get_rect,
        GetClassNameW=get_class,
        IsWindowVisible=visible,
        EnumWindows=_Enumeration(lambda callback, parameter: callback(_HANDLE, parameter)),
        EnumChildWindows=_Enumeration(
            lambda _handle, callback, parameter: callback(_CHILD, parameter)
        ),
        SetWindowPos=_Enumeration(lambda *_args: 1),
        seen=seen,
    )


def _install(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    api = _user32()
    monkeypatch.setattr(ownership.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=api), raising=False)
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    return api


def test_point_owner_preserves_the_handle_returned_by_window_from_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _install(monkeypatch)

    assert ownership.owner_at(200, 150) == _PID
    assert api.seen == [_HANDLE]


def test_popup_query_keeps_callback_handles_and_signed_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _install(monkeypatch)

    rect = stress_driver._own_popup_rect(_PID)

    assert rect is not None
    assert (rect.x, rect.y, rect.width, rect.height) == (-120, 20, 340, 200)
    assert api.seen == [_HANDLE, _HANDLE]


def test_browser_content_query_keeps_parent_child_handles_and_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _install(monkeypatch)
    monkeypatch.setattr(
        browser_text.psutil, "Process", lambda _pid: SimpleNamespace(children=lambda **_kwargs: [])
    )

    assert browser_text._content_origin(_PID) == ((-120, 20), _PID)
    assert api.seen == [_HANDLE, _CHILD, _CHILD]
    assert browser_text._class_at(200, 150) == browser_text._CONTENT_CLASS
    assert api.seen[-1] == _HANDLE
