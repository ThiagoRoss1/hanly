"""What the Windows adapter reads, and everything it refuses to read.

The UI Automation calls themselves are stood in for by a fake control, because
what has to be pinned down is the adapter's own judgement: which properties are
consulted before any text is touched, how a span is isolated when two real
providers disagree about what a character is, which rectangle answers for a
pointer, and that every interface it opens is released again. One group at the
end uses the real COM plumbing, since an apartment entered on a background
thread is not something a double can prove.
"""

from __future__ import annotations

import ctypes
import faulthandler
from threading import Thread
from typing import Any

import pytest
from hanly import BoundingBox, Point
from hanly_app import text_acquisition_uia as uia
from hanly_app.text_acquisition import DirectTextCoordinator, Outcome
from hanly_app.text_acquisition_uia import UIAutomationTextProvider

_UIA_IS_PASSWORD = 30019
_UIA_IS_OFFSCREEN = 30022

_LINE_TOP = 100
_LINE_BOTTOM = 130
_LINE_LEFT = 200
#: Every fixture line is laid out at ten pixels per character, so a pointer's
#: x coordinate names a character and a character span names a rectangle.
_CHARACTER_WIDTH = 10


class _Range:
    """A start/end pair over the fake control's text, in Python characters."""

    def __init__(self, control: _Control, start: int, end: int) -> None:
        self.control = control
        self.start = start
        self.end = end

    def text(self) -> str:
        return self.control.text[self.start : self.end]


class _Control:
    """One line of text answering the way a real UIA provider answers.

    ``unit`` names what this control thinks ``MoveEndpointByUnit`` counts:
    Chromium was measured counting code points and RichEdit UTF-16 code units,
    and the adapter has to reach the same span through either.
    """

    def __init__(
        self,
        text: str,
        *,
        unit: str = "code_points",
        password: bool = False,
        offscreen: bool = False,
        has_pattern: bool = True,
        denied: bool = False,
        rectangles: list[BoundingBox] | None = None,
        nearest: bool = False,
    ) -> None:
        self.text = text
        self.unit = unit
        self.password = password
        self.offscreen = offscreen
        self.has_pattern = has_pattern
        self.denied = denied
        self.rectangles = rectangles
        self.nearest = nearest

    def index_at(self, point: Point) -> int:
        offset = int((point.x - _LINE_LEFT) // _CHARACTER_WIDTH)
        if self.nearest:
            # The failure that would silently define the wrong word: the
            # control answers about whatever is closest instead of refusing.
            return 0
        return max(0, min(offset, max(len(self.text) - 1, 0)))

    def offsets_of(self, index: int) -> int:
        if self.unit == "code_points":
            return index
        return len(self.text[:index].encode("utf-16-le")) // 2

    def index_of(self, offset: int) -> int | None:
        for index in range(len(self.text) + 1):
            if self.offsets_of(index) == offset:
                return index
        return None

    def box_for(self, start: int, end: int) -> list[BoundingBox]:
        if self.rectangles is not None:
            return self.rectangles
        if end <= start:
            return []
        return [
            BoundingBox(
                left=_LINE_LEFT + start * _CHARACTER_WIDTH,
                top=_LINE_TOP,
                right=_LINE_LEFT + end * _CHARACTER_WIDTH,
                bottom=_LINE_BOTTOM,
            )
        ]


class _Bridge:
    """Stands in for the COM bridge and counts what the adapter fails to free."""

    def __init__(self, control: _Control | None) -> None:
        self.control = control
        self._objects: dict[int, Any] = {}
        self._next = 1
        self.live = 0

    # --- handle bookkeeping ----------------------------------------------

    def _hold(self, value: Any) -> ctypes.c_void_p:
        handle = self._next
        self._next += 1
        self._objects[handle] = value
        self.live += 1
        return ctypes.c_void_p(handle)

    def _get(self, pointer: ctypes.c_void_p) -> Any:
        assert pointer.value is not None, "the adapter passed back a null interface"
        return self._objects[pointer.value]

    def release(self, pointer: ctypes.c_void_p | None) -> None:
        if pointer and pointer.value in self._objects:
            del self._objects[pointer.value]
            self.live -= 1

    # --- the surface the adapter calls -----------------------------------

    def element_at(self, point: Point) -> ctypes.c_void_p | None:
        return None if self.control is None else self._hold(self.control)

    def flag(self, element: ctypes.c_void_p, property_id: int) -> bool | None:
        control = self._get(element)
        if control.denied:
            return None
        if property_id == _UIA_IS_PASSWORD:
            return control.password
        if property_id == _UIA_IS_OFFSCREEN:
            return control.offscreen
        return None

    def text_pattern(self, element: ctypes.c_void_p) -> ctypes.c_void_p | None:
        control = self._get(element)
        if control.denied or not control.has_pattern:
            return None
        return self._hold(control)

    def range_at(
        self, pattern: ctypes.c_void_p, point: Point
    ) -> ctypes.c_void_p | None:
        control = self._get(pattern)
        index = control.index_at(point)
        return self._hold(_Range(control, index, index))

    def clone(self, pointer: ctypes.c_void_p) -> ctypes.c_void_p | None:
        found = self._get(pointer)
        return self._hold(_Range(found.control, found.start, found.end))

    def expand(self, pointer: ctypes.c_void_p, unit: int) -> bool:
        found = self._get(pointer)
        found.start, found.end = 0, len(found.control.text)
        return True

    def text_of(self, pointer: ctypes.c_void_p, limit: int) -> str | None:
        return self._get(pointer).text()[:limit]

    def align_endpoint(
        self,
        pointer: ctypes.c_void_p,
        endpoint: int,
        other: ctypes.c_void_p,
        other_endpoint: int,
    ) -> bool:
        found, source = self._get(pointer), self._get(other)
        found.end = source.start if other_endpoint == 0 else source.end
        return True

    def move_endpoint(
        self, pointer: ctypes.c_void_p, endpoint: int, unit: int, count: int
    ) -> bool:
        found = self._get(pointer)
        control = found.control
        current = found.start if endpoint == 0 else found.end
        moved = control.index_of(control.offsets_of(current) + count)
        if moved is None:
            return False
        if endpoint == 0:
            found.start = moved
        else:
            found.end = moved
        return True

    def rectangles(self, pointer: ctypes.c_void_p) -> list[BoundingBox]:
        found = self._get(pointer)
        return found.control.box_for(found.start, found.end)


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Install one fake bridge and hand the test its handle ledger."""

    installed: list[_Bridge] = []

    def use(control: _Control | None) -> _Bridge:
        made = _Bridge(control)
        installed.append(made)
        monkeypatch.setattr(uia, "_bridge_for_thread", lambda: made)
        return made

    return use


def _point(index: int) -> Point:
    """The pointer sitting on the ``index``-th character of a fixture line."""

    return Point(
        _LINE_LEFT + index * _CHARACTER_WIDTH + _CHARACTER_WIDTH / 2,
        (_LINE_TOP + _LINE_BOTTOM) / 2,
    )


def _read(control: _Control, index: int, bridge: Any) -> Any:
    ledger = bridge(control)
    reading = UIAutomationTextProvider().read_at(_point(index), timeout_ms=40)
    assert ledger.live == 0, "every interface the adapter opened must be released"
    return reading


# --- what the pointer is on ----------------------------------------------


def test_the_line_under_the_pointer_is_read_with_the_pointer_inside_it(
    bridge: Any,
) -> None:
    reading = _read(_Control("초대받았어요"), 2, bridge)

    assert reading is not None
    assert reading.text == "초대받았어요"
    assert reading.cursor_index == 2
    assert reading.bounds == BoundingBox(200, 100, 260, 130)


@pytest.mark.parametrize(
    ("line", "index", "expected"),
    [
        ("초대받았어요", 0, "초"),
        ("초대받았어요", 5, "요"),
        ("Hello 초대받았어요 world", 8, "받"),
        ("가공식품, 초대받았어요", 0, "가"),
        ("  초대받았어요", 3, "대"),
        ("🙂🙂초대받았어요", 3, "대"),
        ("초대\n받았어요", 3, "받"),
    ],
)
def test_the_cursor_index_names_the_character_the_pointer_is_over(
    bridge: Any, line: str, index: int, expected: str
) -> None:
    """Counted from the text before the pointer, the one measure providers agree on."""

    reading = _read(_Control(line), index, bridge)

    assert reading is not None
    assert reading.text[reading.cursor_index] == expected


def test_a_nearest_range_is_reported_with_geometry_that_gives_it_away(
    bridge: Any,
) -> None:
    """``RangeFromPoint`` may answer about the closest text rather than refuse."""

    reading = _read(_Control("초대받았어요", nearest=True), 40, bridge)

    assert reading is not None
    assert reading.bounds is not None
    assert not (reading.bounds.left <= _point(40).x <= reading.bounds.right)


def test_a_line_longer_than_the_adapter_will_read_is_refused(bridge: Any) -> None:
    """Past the cap the truncation point, not the pointer, would set every offset."""

    assert _read(_Control("초" * (uia._MAX_LINE_CHARACTERS + 5)), 3, bridge) is None


# --- refusals before any text is touched ---------------------------------


def test_a_password_field_is_reported_secure_and_carries_nothing(
    bridge: Any,
) -> None:
    """Chromium really does expose a text pattern on a password input."""

    reading = _read(_Control("초대받았어요", password=True), 2, bridge)

    assert reading is not None
    assert reading.secure is True
    assert reading.text == ""
    assert reading.bounds is None


def test_a_secure_field_never_reaches_the_text_pattern(bridge: Any) -> None:
    ledger = bridge(_Control("초대받았어요", password=True))
    ledger.text_pattern = _refuse_to_be_called

    assert UIAutomationTextProvider().read_at(_point(2), timeout_ms=40) is not None


def _refuse_to_be_called(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("secure content must be refused before it is read")


@pytest.mark.parametrize(
    "control",
    [
        _Control("초대받았어요", offscreen=True),
        _Control("초대받았어요", has_pattern=False),
        _Control("초대받았어요", denied=True),
    ],
    ids=["offscreen", "no_text_pattern", "access_denied"],
)
def test_an_unreadable_element_answers_nothing_rather_than_raising(
    bridge: Any, control: _Control
) -> None:
    """A higher-integrity target refuses every property; that is not an error."""

    assert _read(control, 2, bridge) is None


def test_a_window_that_is_not_there_answers_nothing(bridge: Any) -> None:
    ledger = bridge(None)

    assert UIAutomationTextProvider().read_at(_point(2), timeout_ms=40) is None
    assert ledger.live == 0


def test_the_adapter_has_nothing_to_say_without_a_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uia, "_bridge_for_thread", lambda: None)
    provider = UIAutomationTextProvider()

    assert provider.read_at(_point(2), timeout_ms=40) is None
    assert provider.refine_bounds(_point(2), 0, 3, timeout_ms=40) is None


# --- narrowing a line to one word ----------------------------------------


@pytest.mark.parametrize("unit", ["code_points", "utf16"])
@pytest.mark.parametrize(
    ("line", "start", "end"),
    [
        ("초대받았어요", 0, 6),
        ("Hello 초대받았어요 world", 6, 12),
        ("🙂🙂초대받았어요", 2, 8),
        ("가공식품, 떨어뜨렸어요", 5, 11),
        ("초대\n깨뜨렸습니다", 3, 9),
    ],
)
def test_a_span_is_isolated_however_the_provider_counts_characters(
    bridge: Any, unit: str, line: str, start: int, end: int
) -> None:
    """Chromium counts code points and RichEdit counts UTF-16 units."""

    ledger = bridge(_Control(line, unit=unit))

    bounds = UIAutomationTextProvider().refine_bounds(
        _point(start), start, end, timeout_ms=40
    )

    assert bounds == BoundingBox(
        _LINE_LEFT + start * _CHARACTER_WIDTH,
        _LINE_TOP,
        _LINE_LEFT + end * _CHARACTER_WIDTH,
        _LINE_BOTTOM,
    )
    assert ledger.live == 0


def test_a_span_whose_text_is_not_the_text_asked_for_is_refused(
    bridge: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verification is the whole defence against a miscounted offset."""

    ledger = bridge(_Control("초대받았어요"))
    monkeypatch.setattr(
        ledger, "text_of", lambda pointer, limit: "초대받았어요"[: limit or None]
    )

    assert (
        UIAutomationTextProvider().refine_bounds(_point(0), 0, 3, timeout_ms=40) is None
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 3), (0, 0), (3, 1), (0, 99), (7, 9)],
)
def test_a_span_that_does_not_fit_the_line_cannot_be_asked_about(
    bridge: Any, start: int, end: int
) -> None:
    """The line may have changed under the pointer between the two calls."""

    bridge(_Control("초대받았어요"))

    assert (
        UIAutomationTextProvider().refine_bounds(
            _point(0), start, end, timeout_ms=40
        )
        is None
    )


def test_a_control_that_cannot_move_an_endpoint_refuses_the_span(
    bridge: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = bridge(_Control("초대받았어요"))
    monkeypatch.setattr(ledger, "move_endpoint", lambda *args: False)

    assert (
        UIAutomationTextProvider().refine_bounds(_point(0), 0, 3, timeout_ms=40) is None
    )
    assert ledger.live == 0


# --- geometry -------------------------------------------------------------


def test_a_wrapped_run_answers_with_the_rectangle_holding_the_pointer(
    bridge: Any,
) -> None:
    """A run split over two visual lines has two rectangles, and one is the pointer's."""

    above = BoundingBox(200, 40, 400, 70)
    below = BoundingBox(200, _LINE_TOP, 400, _LINE_BOTTOM)
    bridge(_Control("초대받았어요", rectangles=[above, below]))

    reading = UIAutomationTextProvider().read_at(_point(2), timeout_ms=40)

    assert reading is not None
    assert reading.bounds == below


def test_several_rectangles_none_of_which_is_the_pointer_s_name_nothing(
    bridge: Any,
) -> None:
    elsewhere = [BoundingBox(0, 0, 10, 10), BoundingBox(20, 0, 30, 10)]
    bridge(_Control("초대받았어요", rectangles=elsewhere))

    reading = UIAutomationTextProvider().read_at(_point(2), timeout_ms=40)

    assert reading is not None
    assert reading.bounds is None


def test_a_single_rectangle_is_kept_so_the_caller_can_refuse_it_itself(
    bridge: Any,
) -> None:
    """Refusing here would hide from the policy layer why it was refused."""

    elsewhere = BoundingBox(0, 0, 10, 10)
    bridge(_Control("초대받았어요", rectangles=[elsewhere]))

    reading = UIAutomationTextProvider().read_at(_point(2), timeout_ms=40)

    assert reading is not None
    assert reading.bounds == elsewhere


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([200.0, 100.0, 60.0, 30.0], [BoundingBox(200, 100, 260, 130)]),
        # A monitor left of the primary one reports a negative origin.
        ([-1468.0, 213.0, 192.0, 43.0], [BoundingBox(-1468, 213, -1276, 256)]),
        # Fractions round outwards, so a pointer inside is never rounded out.
        ([10.4, 20.6, 5.3, 4.2], [BoundingBox(10, 20, 16, 25)]),
        # A degenerate range occupies nothing and names no rectangle.
        ([200.0, 100.0, 0.0, 30.0], []),
        ([200.0, 100.0, 60.0, 0.0], []),
        # A malformed answer is not stretched to fit.
        ([200.0, 100.0, 60.0], []),
        ([], []),
    ],
)
def test_rectangles_are_read_from_uia_quadruples(
    values: list[float], expected: list[BoundingBox]
) -> None:
    assert uia._boxes_from(values) == expected


@pytest.mark.parametrize(
    ("text", "start", "end", "expected"),
    [
        ("초대받았어요", 0, 6, ((0, 6, 6),)),
        ("Hello 초대", 6, 8, ((6, 8, 8),)),
        ("🙂🙂초대", 2, 4, ((2, 4, 4), (4, 6, 6))),
        ("초대🙂받다", 0, 2, ((0, 2, 5), (0, 2, 6))),
    ],
)
def test_a_span_is_offered_in_both_counts_only_when_they_differ(
    text: str, start: int, end: int, expected: tuple[tuple[int, int, int], ...]
) -> None:
    assert uia._span_offsets(text, start, end) == expected


# --- the decision the adapter feeds ---------------------------------------


@pytest.mark.parametrize("unit", ["code_points", "utf16"])
def test_korean_under_the_pointer_is_used_directly(bridge: Any, unit: str) -> None:
    bridge(_Control("Hello 초대받았어요 world", unit=unit))

    acquired = DirectTextCoordinator(UIAutomationTextProvider()).acquire(_point(8))

    assert acquired.outcome is Outcome.DIRECT
    assert acquired.selection is not None
    assert acquired.selection.text == "초대받았어요"
    assert acquired.selection.cursor_index == 2
    assert acquired.bounds == BoundingBox(260, 100, 320, 130)


@pytest.mark.parametrize(
    ("control", "index", "outcome"),
    [
        (_Control("초대받았어요", password=True), 2, Outcome.SECURE),
        (_Control("초대받았어요", has_pattern=False), 2, Outcome.UNSUPPORTED),
        (_Control("초대받았어요", denied=True), 2, Outcome.UNSUPPORTED),
        (_Control("초대받았어요", offscreen=True), 2, Outcome.UNSUPPORTED),
        (_Control("초대받았어요", nearest=True), 40, Outcome.NOT_CONTAINING),
        (_Control("Hello world"), 2, Outcome.NOT_KOREAN),
        (_Control("🙂🙂초대받았어요"), 0, Outcome.NOT_KOREAN),
        (_Control("   "), 1, Outcome.EMPTY),
    ],
    ids=[
        "password",
        "no_text_pattern",
        "access_denied",
        "offscreen",
        "nearest_not_containing",
        "latin",
        "emoji",
        "blank",
    ],
)
def test_every_refusal_is_an_ordinary_outcome(
    bridge: Any, control: _Control, index: int, outcome: Outcome
) -> None:
    bridge(control)

    acquired = DirectTextCoordinator(UIAutomationTextProvider()).acquire(_point(index))

    assert acquired.outcome is outcome
    assert acquired.selection is None


def test_repeated_acquisition_leaves_no_interface_behind(bridge: Any) -> None:
    ledger = bridge(_Control("Hello 초대받았어요 world"))
    coordinator = DirectTextCoordinator(UIAutomationTextProvider())

    for _ in range(50):
        assert coordinator.acquire(_point(8)).outcome is Outcome.DIRECT

    assert ledger.live == 0


# --- the real apartment ---------------------------------------------------


@pytest.fixture
def quiet_com_teardown() -> Any:
    """Keep COM's own teardown noise out of the run's output.

    ``CoUninitialize`` raises two first-chance ``RPC_E_DISCONNECTED`` exceptions
    while dropping the cross-process connection a read established, and handles
    both itself. The count does not grow with the number of reads, so it is the
    connection going away rather than anything this adapter failed to release;
    pytest's fault handler would otherwise print it as though it were a crash.
    """

    faulthandler.disable()
    yield
    faulthandler.enable()


def test_com_is_entered_and_left_on_the_worker_thread() -> None:
    """A bridge belongs to the thread that made it, and is gone when it leaves."""

    provider = UIAutomationTextProvider()
    seen: list[object] = []

    def work() -> None:
        provider.bind_thread()
        seen.append(getattr(uia._thread_state, "bridge", None))
        provider.release_thread()
        seen.append(getattr(uia._thread_state, "bridge", None))

    worker = Thread(target=work)
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert seen == [seen[0], None]
    assert seen[0] is not None, "UI Automation must be reachable from a worker"
    assert getattr(uia._thread_state, "bridge", None) is None


def test_binding_and_releasing_repeatedly_stays_balanced(quiet_com_teardown: Any) -> None:
    provider = UIAutomationTextProvider()

    def work() -> None:
        for _ in range(5):
            provider.bind_thread()
            provider.read_at(Point(1, 1), timeout_ms=40)
            provider.release_thread()
        # Releasing a thread that holds nothing is not an error.
        provider.release_thread()

    worker = Thread(target=work)
    worker.start()
    worker.join(timeout=20)

    assert not worker.is_alive()


def test_a_real_read_at_an_arbitrary_point_never_raises(quiet_com_teardown: Any) -> None:
    """Whatever is on screen, the adapter answers with a value or with nothing."""

    provider = UIAutomationTextProvider()
    outcomes: list[object] = []

    def work() -> None:
        provider.bind_thread()
        try:
            for point in (Point(0, 0), Point(-1, -1), Point(5, 5), Point(10**6, 10**6)):
                outcomes.append(provider.read_at(point, timeout_ms=40))
                outcomes.append(provider.refine_bounds(point, 0, 1, timeout_ms=40))
        finally:
            provider.release_thread()

    worker = Thread(target=work)
    worker.start()
    worker.join(timeout=20)

    assert not worker.is_alive()
    assert len(outcomes) == 8
