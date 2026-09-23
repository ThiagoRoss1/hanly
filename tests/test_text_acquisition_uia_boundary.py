"""Portable refusal, snapshot and ownership checks; these do not execute Windows COM."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hanly import Point
from hanly_app import text_acquisition_uia as uia
from hanly_app.text_acquisition import DirectTextCoordinator, Outcome

from tests.hanly_fixtures.uia import FakeBridge, FakeControl, point_at


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
        assert provider.refine_bounds(Point(1, 1), 0, 1, line="초", timeout_ms=40) is None
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


def _install(
    monkeypatch: pytest.MonkeyPatch, bridge: FakeBridge
) -> uia.UIAutomationTextProvider:
    monkeypatch.setattr(uia, "_bridge_for_thread", lambda: bridge)
    return uia.UIAutomationTextProvider()


def _changing_on_refinement(
    control: FakeControl, change: Callable[[FakeControl], FakeControl | None]
) -> FakeBridge:
    """A bridge whose second element lookup -- the refinement -- sees ``change``."""

    bridge = FakeBridge(control)
    lookups = {"count": 0}

    def element_at(point: Point) -> ctypes.c_void_p | None:
        lookups["count"] += 1
        current = control if lookups["count"] == 1 else change(control)
        return None if current is None else bridge.hold(current)

    bridge.element_at = element_at  # type: ignore[method-assign]
    return bridge


def _retitled(text: str) -> Callable[[FakeControl], FakeControl]:
    def change(control: FakeControl) -> FakeControl:
        control.text = text
        return control

    return change


def _secured(control: FakeControl) -> FakeControl:
    control.password = True
    return control


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda control: control, Outcome.DIRECT),
        (_retitled("사과받았어요"), Outcome.AMBIGUOUS),
        (_retitled("초대"), Outcome.AMBIGUOUS),
        (lambda control: FakeControl("사과했어요요"), Outcome.AMBIGUOUS),
        (lambda control: None, Outcome.AMBIGUOUS),
        (_secured, Outcome.AMBIGUOUS),
    ],
    ids=["unchanged", "same-length", "different-length", "other-element", "gone", "secure"],
)
def test_refinement_belongs_to_the_line_originally_read(
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[FakeControl], FakeControl | None],
    expected: Outcome,
) -> None:
    """A rectangle for different content must never retain this lookup's word."""

    bridge = _changing_on_refinement(FakeControl("초대받았어요"), change)
    provider = _install(monkeypatch, bridge)

    acquired = DirectTextCoordinator(provider).acquire(point_at(2))

    assert acquired.outcome is expected
    if expected is not Outcome.DIRECT:
        assert acquired.selection is None and acquired.bounds is None
    assert bridge.live == 0
