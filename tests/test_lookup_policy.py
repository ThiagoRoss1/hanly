"""When the lookup engine is loaded, and what a user's choice does about it.

The engine owns how residency happens; this is the policy that decides when.
Every row of the plan's preload matrix is here, plus the idle expiry that stops
one hotkey lookup from holding a gigabyte for the rest of the session.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus, PixelFormat, Point, ROIImage
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.config import AppConfig, HoverActivation, LookupPreload
from hanly_app.hotkeys import HotkeyAction, HotkeyService
from hanly_app.lookup_controller import LookupController, LookupRequest, ResultDispatcher
from hanly_app.manual_lookup import ManualLookupRuntime, create_manual_lookup

_IMAGE = ROIImage(2, 1, PixelFormat.RGB_888, b"\x00\x00\x00\xff\xff\xff")
_CURSOR = Point(120.0, 80.0)
_CAPTURE = CaptureResult(_IMAGE, ScreenRect(20, 30, 2, 1), Point(1.0, 0.5))
_LOOKUP_BINDING = "<ctrl>+<shift>+<space>"
_TOGGLE_BINDING = "<ctrl>+<shift>+<f9>"


class _Engine:
    """A lookup engine that records residency decisions instead of making them."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state = "sleeping"
        self.preload = False
        self.idle = 0.0

    def prepare(self) -> None:
        self.calls.append("prepare")
        self.state = "ready"

    def retire(self) -> None:
        self.calls.append("retire")
        self.state = "sleeping"

    def set_preload(self, preload: bool) -> None:
        self.preload = preload
        self.calls.append(f"preload={preload}")

    def reset_recovery_budget(self) -> None:
        self.calls.append("reset_budget")

    def idle_seconds(self) -> float:
        return self.idle


class _Timer:
    def __init__(self, seconds: float, callback: Callable[[], None]) -> None:
        self.seconds = seconds
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Clock:
    """A one-shot scheduler the test fires by hand."""

    def __init__(self) -> None:
        self.timers: list[_Timer] = []

    def __call__(self, seconds: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer(seconds, callback)
        self.timers.append(timer)
        return timer

    @property
    def live(self) -> _Timer | None:
        return next((timer for timer in reversed(self.timers) if not timer.cancelled), None)

    def fire(self) -> None:
        timer = self.live
        assert timer is not None, "nothing is scheduled"
        timer.callback()


class _Dispatcher:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self.pending.append(callback)

    def drain(self) -> None:
        while self.pending:
            self.pending.pop(0)()


class _Listener:
    def __init__(self, callbacks: Mapping[str, Callable[[], None]]) -> None:
        self.callbacks = dict(callbacks)
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def join(self, timeout: float | None = None) -> None:
        del timeout

    def press(self, binding: str) -> None:
        self.callbacks[binding]()


class _Hotkeys:
    def __init__(self, *, fail: bool = False) -> None:
        self.listener: _Listener | None = None
        self._fail = fail

    def __call__(self, on_action: Any, bindings: Any, dispatcher: Any) -> HotkeyService:
        def factory(callbacks: Mapping[str, Callable[[], None]]) -> _Listener:
            if self._fail:
                raise RuntimeError("another application already uses that shortcut")
            self.listener = _Listener(callbacks)
            return self.listener

        return HotkeyService(
            on_action, bindings=bindings, dispatcher=dispatcher, listener_factory=factory
        )


class _Capture:
    def __init__(self) -> None:
        self.captures = 0
        self.closed = False

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        del cursor
        self.captures += 1
        return _CAPTURE

    def close(self) -> None:
        self.closed = True


class _Worker:
    def __call__(self, request: LookupRequest) -> LookupResult:
        del request
        return LookupResult(
            status=LookupStatus.SUCCESS,
            entries=(DictionaryEntry(headword="책", definitions=("book",)),),
        )

    def close(self) -> None:
        pass


class _Runtime:
    """A runtime that offers the disposable engine, the way the real one does."""

    def __init__(self, engine: _Engine) -> None:
        self.engine = engine
        self.preloads: list[bool] = []

    def create_lookup_engine(self, *, preload: bool, **_options: object) -> _Engine:
        self.preloads.append(preload)
        return self.engine

    def create_lookup_controller(
        self,
        on_result: Callable[[LookupResult], None] | None = None,
        *,
        result_dispatcher: ResultDispatcher | None = None,
        thread_name: str | None = None,
        engine: _Engine | None = None,
        **_options: object,
    ) -> LookupController:
        assert engine is self.engine
        return LookupController(
            lambda: _Worker(),
            on_result,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
        )


def _session(
    *,
    preload: LookupPreload = LookupPreload.WHEN_CAPTURE_STARTS,
    hotkeys: _Hotkeys | None = None,
    capture_refusal: Callable[[], str | None] | None = None,
    on_toggle_hover: Callable[[], None] | None = None,
    on_error: Callable[[str, BaseException], None] | None = None,
) -> tuple[ManualLookupRuntime, _Engine, _Clock, _Dispatcher, _Hotkeys, list[LookupResult]]:
    engine = _Engine()
    clock = _Clock()
    dispatcher = _Dispatcher()
    factory = hotkeys or _Hotkeys()
    results: list[LookupResult] = []
    manual = create_manual_lookup(
        cast(Any, _Runtime(engine)),
        _Capture(),
        results.append,
        close_popup=lambda: None,
        current_cursor=lambda: _CURSOR,
        dispatcher=dispatcher,
        hotkey_factory=factory,
        shutdown_scheduler=lambda callback: callback(),
        app_config=AppConfig(lookup_preload=preload),
        idle_scheduler=clock,
        on_toggle_hover=on_toggle_hover,
        on_error=on_error,
        capture_refusal=capture_refusal,
    )
    return manual, engine, clock, dispatcher, factory, results


def _press(factory: _Hotkeys, dispatcher: _Dispatcher, binding: str) -> None:
    assert factory.listener is not None
    factory.listener.press(binding)
    dispatcher.drain()


def _await_result(dispatcher: _Dispatcher, results: list[LookupResult]) -> None:
    """Drain until the worker thread's result has been presented."""

    for _ in range(200):
        dispatcher.drain()
        if results:
            return
        threading.Event().wait(0.01)
    raise AssertionError("no lookup result was presented")


def test_shortcuts_are_registered_with_the_session_not_with_capture() -> None:
    """A denied capture permission must not also cost the user their keys."""

    manual, _engine, _clock, _dispatcher, factory, _results = _session()
    manual.prepare()

    assert factory.listener is not None
    assert factory.listener.started == 1
    assert manual.started is False
    manual.shutdown()


def test_a_shortcut_another_application_owns_leaves_the_session_running() -> None:
    reported: list[str] = []
    manual, _engine, _clock, _dispatcher, _factory, _results = _session(
        hotkeys=_Hotkeys(fail=True),
        on_error=lambda stage, error: reported.append(f"{stage}: {error}"),
    )

    manual.prepare()

    assert reported == [
        "Keyboard shortcuts: another application already uses that shortcut"
    ]
    assert manual.prepared is True
    manual.shutdown()


def test_when_capture_starts_keeps_the_engine_asleep_until_capture_does() -> None:
    manual, engine, _clock, _dispatcher, _factory, _results = _session()

    manual.prepare()
    assert engine.calls == ["preload=False"]

    manual.start()
    assert "prepare" in engine.calls
    assert engine.state == "ready"

    manual.stop()
    assert engine.calls[-1] == "retire"
    assert engine.state == "sleeping"
    manual.shutdown()


def test_always_loads_at_launch_and_keeps_residency_through_a_hover_mute() -> None:
    """This is the choice that deliberately opts into holding the memory.

    It buys residency through a mute, which is what the warm pause is for. It
    does not survive an explicit Stop: the user asking Hanly to stop is the one
    action that gives the memory back whatever the policy says.
    """

    manual, engine, _clock, _dispatcher, _factory, _results = _session(
        preload=LookupPreload.ALWAYS
    )

    manual.prepare()
    assert engine.calls == ["preload=True", "prepare"]

    manual.start()
    manual.set_hover_muted(True)

    assert "retire" not in engine.calls
    assert engine.state == "ready"
    assert manual.hover_muted is True

    manual.stop()

    assert engine.calls[-1] == "retire"
    assert engine.state == "sleeping"
    assert manual.hover_muted is False
    manual.shutdown()


def test_a_hover_mute_never_retires_the_engine_under_any_policy() -> None:
    manual, engine, _clock, _dispatcher, _factory, _results = _session()
    manual.start()
    assert engine.state == "ready"

    manual.set_hover_muted(True)
    manual.set_hover_muted(False)

    assert "retire" not in engine.calls
    assert engine.state == "ready"
    assert manual.hover_muted is False
    manual.shutdown()


def test_starting_again_clears_a_mute_rather_than_resuming_into_it() -> None:
    manual, _engine, _clock, _dispatcher, _factory, _results = _session()
    manual.start()
    manual.set_hover_muted(True)

    manual.start()

    assert manual.hover_muted is False
    manual.shutdown()


def test_muting_a_session_that_is_not_started_does_nothing() -> None:
    manual, _engine, _clock, _dispatcher, _factory, _results = _session()
    manual.prepare()

    manual.set_hover_muted(True)

    assert manual.hover_muted is False
    manual.shutdown()


def test_on_demand_prepares_nothing_even_when_capture_starts() -> None:
    manual, engine, _clock, _dispatcher, _factory, _results = _session(
        preload=LookupPreload.ON_DEMAND
    )

    manual.prepare()
    manual.start()

    assert engine.calls == ["preload=False", "reset_budget"]
    assert engine.state == "sleeping"
    manual.shutdown()


def test_starting_capture_refreshes_the_automatic_recovery_allowance() -> None:
    """A deliberate activation is what refills it; a replacement coming up is
    deliberately not, or a crash loop would fund its own restarts."""

    manual, engine, _clock, _dispatcher, _factory, _results = _session()
    manual.prepare()
    assert "reset_budget" not in engine.calls

    manual.start()

    assert "reset_budget" in engine.calls
    manual.shutdown()


def test_a_manual_lookup_with_capture_off_expires_the_engine_when_idle() -> None:
    manual, engine, clock, dispatcher, factory, results = _session()
    manual.prepare()

    _press(factory, dispatcher, _LOOKUP_BINDING)
    _await_result(dispatcher, results)

    timer = clock.live
    assert timer is not None
    assert timer.seconds == pytest.approx(60.0)

    engine.idle = 60.0
    clock.fire()

    assert engine.calls[-1] == "retire"
    manual.shutdown()


def test_an_engine_used_again_before_expiry_waits_out_the_rest() -> None:
    manual, engine, clock, dispatcher, factory, _results = _session()
    manual.prepare()
    _press(factory, dispatcher, _LOOKUP_BINDING)

    engine.idle = 25.0
    clock.fire()

    assert "retire" not in engine.calls
    assert clock.live is not None
    assert clock.live.seconds == pytest.approx(35.0)
    manual.shutdown()


def test_capture_that_is_already_watching_keeps_the_engine_warm() -> None:
    """Nothing expires while Hanly is watching the screen: the session is in use."""

    manual, _engine, clock, dispatcher, factory, _results = _session()
    manual.start()

    _press(factory, dispatcher, _LOOKUP_BINDING)

    assert clock.live is None
    manual.shutdown()


def test_the_toggle_shortcut_asks_whoever_owns_the_capture_lifecycle() -> None:
    """Starting capture here directly would leave the tray and the window
    describing something that is not happening."""

    toggles: list[int] = []
    manual, _engine, _clock, dispatcher, factory, _results = _session(
        on_toggle_hover=lambda: toggles.append(1)
    )
    manual.prepare()

    _press(factory, dispatcher, _TOGGLE_BINDING)

    assert toggles == [1]
    manual.shutdown()


def test_a_manual_lookup_without_screen_permission_says_so() -> None:
    """macOS answers a capture without the grant with a picture of the desktop
    background, which would read as "no Korean text here"."""

    manual, _engine, _clock, dispatcher, factory, results = _session(
        capture_refusal=lambda: "Hanly needs Screen Recording access."
    )
    manual.prepare()

    _press(factory, dispatcher, _LOOKUP_BINDING)

    assert len(results) == 1
    assert results[0].status is LookupStatus.UNUSABLE
    assert results[0].diagnostics == ("Hanly needs Screen Recording access.",)
    manual.shutdown()


def test_choosing_always_while_paused_loads_the_engine_immediately() -> None:
    manual, engine, _clock, _dispatcher, _factory, _results = _session()
    manual.prepare()
    engine.calls.clear()

    manual.apply_config(AppConfig(lookup_preload=LookupPreload.ALWAYS))

    assert engine.calls == ["preload=True", "prepare"]
    manual.shutdown()


def test_choosing_away_from_always_with_capture_off_gives_the_memory_back() -> None:
    manual, engine, _clock, _dispatcher, _factory, _results = _session(
        preload=LookupPreload.ALWAYS
    )
    manual.prepare()
    engine.calls.clear()

    manual.apply_config(AppConfig(lookup_preload=LookupPreload.ON_DEMAND))

    assert engine.calls == ["preload=False", "retire"]
    manual.shutdown()


def test_a_policy_change_during_a_manual_session_leaves_it_alone() -> None:
    """The idle expiry is already counting down what that session is using."""

    manual, engine, _clock, dispatcher, factory, results = _session()
    manual.prepare()
    _press(factory, dispatcher, _LOOKUP_BINDING)
    _await_result(dispatcher, results)
    engine.calls.clear()

    manual.apply_config(AppConfig(lookup_preload=LookupPreload.ON_DEMAND))

    assert "retire" not in engine.calls
    manual.shutdown()


def test_changing_a_binding_alone_does_not_disturb_a_running_session() -> None:
    manual, engine, _clock, _dispatcher, factory, _results = _session()
    manual.start()
    engine.calls.clear()

    manual.apply_config(AppConfig(hotkey="ctrl+alt+k"))

    assert manual.started is True
    assert engine.calls == []
    assert factory.listener is not None
    assert "<ctrl>+<alt>+k" in factory.listener.callbacks
    assert manual.hotkeys.bindings[HotkeyAction.TOGGLE_HOVER] == "<ctrl>+<shift>+<f9>"
    manual.shutdown()


def test_the_default_activation_leaves_hover_off_until_it_is_asked_for() -> None:
    assert AppConfig().hover_activation is HoverActivation.HOTKEY
    assert AppConfig().lookup_preload is LookupPreload.WHEN_CAPTURE_STARTS


def test_stop_returns_before_the_lookup_child_has_been_joined() -> None:
    """Retiring joins a child process, which is far too slow for a UI action.

    The stop has to be visible immediately and confirmed afterwards, or the
    tray, the window, and the popup freeze for as long as the child takes.
    """

    engine = _Engine()
    retirements: list[Callable[[], None]] = []
    settled: list[str] = []
    manual = create_manual_lookup(
        cast(Any, _Runtime(engine)),
        _Capture(),
        lambda _result: None,
        close_popup=lambda: None,
        current_cursor=lambda: _CURSOR,
        dispatcher=_Dispatcher(),
        hotkey_factory=_Hotkeys(),
        shutdown_scheduler=retirements.append,
        app_config=AppConfig(),
        idle_scheduler=_Clock(),
        on_stopped=lambda: settled.append("stopped"),
    )
    manual.start()

    manual.stop()

    # The action is over; the child has not been joined yet.
    assert manual.started is False
    assert manual.retiring is True
    assert "retire" not in engine.calls
    assert settled == []

    retirements.pop()()

    assert manual.retiring is False
    assert engine.calls[-1] == "retire"
    assert settled == ["stopped"]
    manual.shutdown()
