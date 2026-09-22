"""Portable refusal and ownership checks; these do not execute Windows COM."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hanly import Point
from hanly_app import text_acquisition_uia as uia


@pytest.mark.parametrize("password", [None, True])
@pytest.mark.parametrize("refine", [False, True])
def test_security_must_be_known_before_either_text_read(
    monkeypatch: pytest.MonkeyPatch, password: bool | None, refine: bool
) -> None:
    calls: list[str] = []
    bridge = SimpleNamespace(
        element_at=lambda point: ctypes.c_void_p(1),
        flag=lambda element, prop: password if prop == 30019 else False,
        text_pattern=lambda element: calls.append("pattern"),
        release=lambda element: None,
    )
    monkeypatch.setattr(uia, "_bridge_for_thread", lambda: bridge)
    provider = uia.UIAutomationTextProvider()
    if refine:
        assert provider.refine_bounds(Point(1, 1), 0, 1, timeout_ms=40) is None
    else:
        result = provider.read_at(Point(1, 1), timeout_ms=40)
        if password is True:
            assert result is not None and result.secure
            assert result.text == "" and result.bounds is None
        else:
            assert result is None
    assert calls == []


def test_timeout_setter_failure_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = uia._UIABridge(
        cast(Any, None), cast(Any, None), ctypes.c_void_p(1), owns_apartment=False
    )
    monkeypatch.setattr(bridge, "_method", lambda *args: lambda *args: -2147024809)
    assert bridge.limit_calls(50) is False


def test_changed_mode_matches_a_signed_windows_hresult() -> None:
    assert uia._RPC_E_CHANGED_MODE == ctypes.c_int32(0x80010106).value


@pytest.mark.parametrize("entered", [0, 1, ctypes.c_int32(0x80010106).value])
@pytest.mark.parametrize("timed, accepted", [(True, True), (True, False), (False, True)])
def test_bridge_creation_balances_owned_apartments_and_requires_timeouts(
    monkeypatch: pytest.MonkeyPatch, entered: int, timed: bool, accepted: bool
) -> None:
    released: list[object] = []
    uninitialized: list[bool] = []
    ole = SimpleNamespace(
        CoInitializeEx=lambda *args: entered,
        CoUninitialize=lambda: uninitialized.append(True),
    )
    monkeypatch.setattr(uia, "_load_library", lambda *args, **kwargs: ole)
    monkeypatch.setattr(uia, "_declare", lambda *args: None)
    monkeypatch.setattr(uia, "_create_automation", lambda *args: (ctypes.c_void_p(1), timed))
    monkeypatch.setattr(uia._UIABridge, "limit_calls", lambda *args: accepted)
    monkeypatch.setattr(uia._UIABridge, "release", lambda self, ptr: released.append(ptr))
    bridge = uia._create_bridge()
    assert (bridge is not None) is (timed and accepted)
    if bridge is not None:
        bridge.dispose()
    assert len(released) == 1
    assert len(uninitialized) == (entered in (0, 1))
