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


# --- which character the pointer is on ---------------------------------------


@pytest.mark.parametrize("unit", ["code_points", "utf16"])
@pytest.mark.parametrize("caret", ["character", "nearest"])
@pytest.mark.parametrize("side", ["left", "centre", "right"])
@pytest.mark.parametrize(
    ("line", "index"),
    [
        ("초대받았어요", 0),
        ("초대받았어요", 5),
        ("🙂🙂초대받았어요", 2),
        ("🙂초대 초대🙂", 4),
        ("초초초 초초", 4),
        ("가공식품, 초대받았어요", 6),
        ("초대\n받았어요", 3),
    ],
    ids=["first", "last", "emoji-prefix", "repeated-word", "repeated-syllable",
         "punctuation", "multiline"],
)
def test_the_cursor_is_the_character_whose_own_rectangle_holds_the_pointer(
    monkeypatch: pytest.MonkeyPatch,
    unit: str,
    caret: str,
    side: str,
    line: str,
    index: int,
) -> None:
    """Wherever the provider leaves its caret, the answer is the pointer's character."""

    bridge = FakeBridge(FakeControl(line, unit=unit, caret=caret))
    provider = _install(monkeypatch, bridge)

    reading = provider.read_at(point_at(index, side=side), timeout_ms=40)

    assert reading is not None
    assert reading.cursor_index == index
    assert bridge.live == 0


def _answering(
    bridge: FakeBridge, wrong: Callable[[Any], str | None]
) -> FakeBridge:
    """``bridge``, with some range texts replaced by an inconsistent provider's."""

    honest = bridge.text_of

    def text_of(pointer: ctypes.c_void_p, limit: int) -> str | None:
        answer = wrong(bridge.get(pointer))
        return honest(pointer, limit) if answer is None else answer

    bridge.text_of = text_of  # type: ignore[method-assign]
    return bridge


@pytest.mark.parametrize(
    "wrong",
    [
        # A shorter prefix that still matches the line's beginning.
        lambda span: "초" if (span.start, span.end) == (0, 2) else None,
        # A suffix that does not continue where the prefix stopped.
        lambda span: "았어요" if (span.start, span.end) == (2, 6) else None,
        # The character after the caret is some other character.
        lambda span: "사" if (span.start, span.end) == (2, 3) else None,
        # The character range answers with more than one character.
        lambda span: "받았" if (span.start, span.end) == (2, 3) else None,
    ],
    ids=["short-prefix", "gapped-suffix", "wrong-character", "wide-character"],
)
def test_an_inconsistent_provider_answer_is_refused(
    monkeypatch: pytest.MonkeyPatch, wrong: Callable[[Any], str | None]
) -> None:
    bridge = _answering(FakeBridge(FakeControl("초대받았어요")), wrong)
    provider = _install(monkeypatch, bridge)

    acquired = DirectTextCoordinator(provider).acquire(point_at(2))

    assert acquired.outcome is Outcome.UNSUPPORTED
    assert acquired.selection is None
    assert bridge.live == 0


def test_a_character_whose_rectangle_misses_the_pointer_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caret's own character must be where the pointer is, not merely nearby."""

    bridge = FakeBridge(FakeControl("초대받았어요"))
    honest = bridge.rectangles

    def rectangles(pointer: ctypes.c_void_p) -> list[Any]:
        span = bridge.get(pointer)
        return [] if span.end - span.start == 1 else honest(pointer)

    bridge.rectangles = rectangles  # type: ignore[method-assign]
    provider = _install(monkeypatch, bridge)

    assert provider.read_at(point_at(2), timeout_ms=40) is None
    assert bridge.live == 0


def test_a_character_the_provider_cannot_step_over_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = FakeBridge(FakeControl("초대받았어요"))
    monkeypatch.setattr(bridge, "move_endpoint", lambda *args: False)
    provider = _install(monkeypatch, bridge)

    assert provider.read_at(point_at(2), timeout_ms=40) is None
    assert bridge.live == 0


# --- cleanup when a native call raises ---------------------------------------


@pytest.mark.parametrize(
    ("refine", "failing"),
    [
        (False, "expand"),
        (False, "align_endpoint"),
        (False, "move_endpoint"),
        (False, "text_of"),
        (False, "rectangles"),
        # Refinement isolates a span by moving endpoints; it aligns none.
        (True, "expand"),
        (True, "move_endpoint"),
        (True, "text_of"),
        (True, "rectangles"),
    ],
)
def test_a_native_call_that_raises_leaves_no_interface_behind(
    monkeypatch: pytest.MonkeyPatch, failing: str, refine: bool
) -> None:
    """An access violation surfaces as an exception; every clone is still released."""

    bridge = FakeBridge(FakeControl("Hello 초대받았어요"))

    def explode(*args: Any) -> None:
        raise OSError("access violation")

    monkeypatch.setattr(bridge, failing, explode)
    provider = _install(monkeypatch, bridge)

    with pytest.raises(OSError):
        if refine:
            provider.refine_bounds(
                point_at(8), 6, 12, line="Hello 초대받았어요", timeout_ms=40
            )
        else:
            provider.read_at(point_at(8), timeout_ms=40)
    assert bridge.live == 0
