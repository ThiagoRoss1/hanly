"""The macOS global-hotkey backend, exercised without touching the window server.

Carbon is replaced by a recording double, so these run on every platform and
never depend on an Accessibility or Input Monitoring grant.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from hanly_app.hotkeys import HotkeyAction, HotkeyEdge, HotkeyError, HotkeyService
from hanly_app.hotkeys_darwin import (
    _EVENT_HOT_KEY_PRESSED,
    _EVENT_HOT_KEY_RELEASED,
    _HANLY_SIGNATURE,
    carbon_binding,
    darwin_listener_factory,
)

_HOT_KEY_EXISTS = -9878
_EVENT_NOT_HANDLED = -9874


class _FakeCarbon:
    """The five Carbon entry points the backend calls, with a memory."""

    def __init__(self) -> None:
        self.registered: list[tuple[int, int, int]] = []
        self.unregistered: list[Any] = []
        self.installed = 0
        self.removed = 0
        self.install_status = 0
        self.register_statuses: list[int] = []
        self.parameter_status = 0
        self.reported_signature = _HANLY_SIGNATURE
        self.handler: Callable[[Any, Any, Any], int] | None = None
        self.kind = _EVENT_HOT_KEY_PRESSED

    def GetEventDispatcherTarget(self) -> int:
        return 0xC0FFEE

    def InstallEventHandler(
        self,
        _target: Any,
        proc: Callable[[Any, Any, Any], int],
        _count: int,
        _spec: Any,
        _user_data: Any,
        _out_ref: Any,
    ) -> int:
        if self.install_status != 0:
            return self.install_status
        self.installed += 1
        self.handler = proc
        return 0

    def RegisterEventHotKey(
        self,
        key_code: int,
        modifiers: int,
        hotkey_id: Any,
        _target: Any,
        _options: int,
        _out_ref: Any,
    ) -> int:
        status = self.register_statuses.pop(0) if self.register_statuses else 0
        if status == 0:
            self.registered.append((key_code, modifiers, hotkey_id.id))
        return status

    def UnregisterEventHotKey(self, reference: Any) -> int:
        self.unregistered.append(reference)
        return 0

    def RemoveEventHandler(self, _reference: Any) -> int:
        self.removed += 1
        return 0

    def GetEventParameter(
        self,
        event: Any,
        _name: int,
        _type: int,
        _actual_type: Any,
        _size: int,
        _actual_size: Any,
        data: Any,
    ) -> int:
        if self.parameter_status != 0:
            return self.parameter_status
        # ``event`` carries the hot key id the window server would have put in
        # the event record.
        data._obj.signature = self.reported_signature
        data._obj.id = event.value
        return 0

    def GetEventKind(self, _event: Any) -> int:
        return self.kind

    def press(self, hotkey_id: int) -> int:
        """Deliver one hot key press the way the main run loop would."""

        return self._deliver(hotkey_id, _EVENT_HOT_KEY_PRESSED)

    def release(self, hotkey_id: int) -> int:
        """Deliver the matching release, which is what makes a hold a hold."""

        return self._deliver(hotkey_id, _EVENT_HOT_KEY_RELEASED)

    def _deliver(self, hotkey_id: int, kind: int) -> int:
        assert self.handler is not None
        self.kind = kind
        # The hot key id travels as the event pointer, which is all the backend
        # hands back to ``GetEventParameter`` above.
        return self.handler(None, hotkey_id, None)


@pytest.fixture
def carbon(monkeypatch: pytest.MonkeyPatch) -> _FakeCarbon:
    fake = _FakeCarbon()
    monkeypatch.setattr("hanly_app.hotkeys_darwin._load_carbon", lambda: fake)
    return fake


@pytest.mark.parametrize(
    ("binding", "expected"),
    [
        # ctrl 0x1000 | shift 0x0200, over kVK_Space, kVK_F9 and kVK_ANSI_K.
        ("<ctrl>+<shift>+<space>", (49, 0x1200)),
        ("<ctrl>+<shift>+<f9>", (101, 0x1200)),
        ("<cmd>+<alt>+k", (40, 0x0900)),
        ("<shift>+<page_down>", (121, 0x0200)),
    ],
)
def test_canonical_bindings_become_virtual_key_codes(
    binding: str, expected: tuple[int, int]
) -> None:
    assert carbon_binding(binding) == expected


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        ("<ctrl>+<shift>", "needs a non-modifier key"),
        ("<ctrl>+a+b", "one non-modifier key"),
        ("<ctrl>+<media_play>", "no key for"),
    ],
)
def test_bindings_macos_cannot_register_are_rejected_before_anything_starts(
    binding: str, message: str
) -> None:
    with pytest.raises(HotkeyError, match=message):
        carbon_binding(binding)


def test_start_registers_every_binding_behind_one_handler(carbon: _FakeCarbon) -> None:
    listener = darwin_listener_factory(
        {"<ctrl>+<shift>+<space>": lambda _edge: None, "<ctrl>+<shift>+<f9>": lambda _edge: None}
    )

    listener.start()

    assert carbon.installed == 1
    assert [entry[:2] for entry in carbon.registered] == [(49, 0x1200), (101, 0x1200)]


def test_repeated_start_does_not_register_a_second_time(carbon: _FakeCarbon) -> None:
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})

    listener.start()
    listener.start()

    assert carbon.installed == 1
    assert len(carbon.registered) == 1


def test_stop_releases_the_hot_keys_and_the_handler_and_repeats_safely(
    carbon: _FakeCarbon,
) -> None:
    listener = darwin_listener_factory(
        {"<ctrl>+<shift>+<space>": lambda _edge: None, "<ctrl>+<shift>+<f9>": lambda _edge: None}
    )
    listener.start()

    listener.stop()
    listener.stop()

    assert len(carbon.unregistered) == 2
    assert carbon.removed == 1


def test_stop_then_start_registers_again(carbon: _FakeCarbon) -> None:
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})

    listener.start()
    listener.stop()
    listener.start()

    assert carbon.installed == 2
    assert len(carbon.registered) == 2
    assert len(carbon.unregistered) == 1


def test_join_returns_immediately_because_there_is_no_listener_thread(
    carbon: _FakeCarbon,
) -> None:
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})
    listener.start()

    listener.join(1.0)

    assert carbon.removed == 0


def test_a_hotkey_another_application_owns_fails_as_an_ordinary_error(
    carbon: _FakeCarbon,
) -> None:
    carbon.register_statuses = [_HOT_KEY_EXISTS]
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})

    with pytest.raises(RuntimeError, match="already uses the hotkey"):
        listener.start()


def test_a_failed_registration_releases_the_hot_keys_it_already_took(
    carbon: _FakeCarbon,
) -> None:
    carbon.register_statuses = [0, _HOT_KEY_EXISTS]
    listener = darwin_listener_factory(
        {"<ctrl>+<shift>+<space>": lambda _edge: None, "<ctrl>+<shift>+<f9>": lambda _edge: None}
    )

    with pytest.raises(RuntimeError):
        listener.start()

    assert len(carbon.unregistered) == 1
    assert carbon.removed == 1


def test_a_refused_handler_is_reported_and_registers_nothing(
    carbon: _FakeCarbon,
) -> None:
    carbon.install_status = -50
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})

    with pytest.raises(RuntimeError, match="event handler"):
        listener.start()

    assert carbon.registered == []


def test_a_pressed_hotkey_runs_only_its_own_callback(carbon: _FakeCarbon) -> None:
    edges: list[tuple[str, HotkeyEdge]] = []
    listener = darwin_listener_factory(
        {
            "<ctrl>+<shift>+<space>": lambda edge: edges.append(("lookup", edge)),
            "<ctrl>+<shift>+<f9>": lambda edge: edges.append(("start", edge)),
        }
    )
    listener.start()
    lookup_id = carbon.registered[0][2]

    assert carbon.press(lookup_id) == 0
    assert edges == [("lookup", HotkeyEdge.DOWN)]


def test_a_held_hotkey_reports_both_of_its_edges(carbon: _FakeCarbon) -> None:
    """Push to Hover is a hold, so the release is as load-bearing as the press.

    Carbon delivers ``kEventHotKeyReleased`` when the combination's own key
    goes up. Without installing that kind, hover would stay on after the user
    let the keys go.
    """

    edges: list[HotkeyEdge] = []
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": edges.append})
    listener.start()
    hotkey_id = carbon.registered[0][2]

    assert carbon.press(hotkey_id) == 0
    assert carbon.release(hotkey_id) == 0

    assert edges == [HotkeyEdge.DOWN, HotkeyEdge.UP]


def test_a_repeated_press_is_not_a_second_activation(carbon: _FakeCarbon) -> None:
    edges: list[HotkeyEdge] = []
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": edges.append})
    listener.start()
    hotkey_id = carbon.registered[0][2]

    carbon.press(hotkey_id)
    assert carbon.press(hotkey_id) == _EVENT_NOT_HANDLED
    carbon.release(hotkey_id)
    assert carbon.release(hotkey_id) == _EVENT_NOT_HANDLED

    assert edges == [HotkeyEdge.DOWN, HotkeyEdge.UP]


def test_an_event_from_another_application_is_declined(carbon: _FakeCarbon) -> None:
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})
    listener.start()
    carbon.reported_signature = 0x4F544852  # 'OTHR'

    assert carbon.press(carbon.registered[0][2]) == _EVENT_NOT_HANDLED


def test_a_hotkey_pressed_after_stop_reaches_nothing(carbon: _FakeCarbon) -> None:
    pressed: list[str] = []
    listener = darwin_listener_factory(
        {"<ctrl>+<shift>+<space>": lambda _edge: pressed.append("lookup")}
    )
    listener.start()
    hotkey_id = carbon.registered[0][2]
    listener.stop()

    assert carbon.press(hotkey_id) == _EVENT_NOT_HANDLED
    assert pressed == []


def test_a_failing_callback_never_raises_into_the_carbon_caller(
    carbon: _FakeCarbon,
) -> None:
    def explode(_edge: HotkeyEdge) -> None:
        raise RuntimeError("handler failed")

    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": explode})
    listener.start()

    assert carbon.press(carbon.registered[0][2]) == _EVENT_NOT_HANDLED


def test_an_unreadable_event_never_raises_into_the_carbon_caller(
    carbon: _FakeCarbon,
) -> None:
    listener = darwin_listener_factory({"<ctrl>+<shift>+<space>": lambda _edge: None})
    listener.start()
    carbon.parameter_status = -50

    assert carbon.press(carbon.registered[0][2]) == _EVENT_NOT_HANDLED


def test_the_service_still_delivers_darwin_actions_through_its_dispatcher(
    carbon: _FakeCarbon,
) -> None:
    """The main run loop must not run application orchestration itself."""

    posted: list[Callable[[], None]] = []
    actions: list[HotkeyAction] = []
    service = HotkeyService(
        lambda action, _edge: actions.append(action),
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        dispatcher=posted.append,
        listener_factory=darwin_listener_factory,
    )
    service.register()

    carbon.press(carbon.registered[0][2])

    assert actions == []
    for deliver in posted:
        deliver()
    assert actions == [HotkeyAction.LOOKUP]


def test_service_rebind_reuses_the_handler_and_replaces_the_registration(
    carbon: _FakeCarbon,
) -> None:
    actions: list[HotkeyAction] = []
    service = HotkeyService(
        lambda action, _edge: actions.append(action),
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        listener_factory=darwin_listener_factory,
    )
    service.register()

    service.rebind(HotkeyAction.LOOKUP, "cmd+alt+k")

    assert carbon.installed == 1
    assert carbon.removed == 0
    assert len(carbon.unregistered) == 1
    assert carbon.registered[-1][:2] == (40, 0x0900)
    assert service.bindings[HotkeyAction.LOOKUP] == "<alt>+<cmd>+k"
    assert carbon.press(carbon.registered[-1][2]) == 0
    assert actions == [HotkeyAction.LOOKUP]


def test_failed_service_rebind_restores_the_previous_carbon_registration(
    carbon: _FakeCarbon,
) -> None:
    actions: list[HotkeyAction] = []
    service = HotkeyService(
        lambda action, _edge: actions.append(action),
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        listener_factory=darwin_listener_factory,
    )
    service.register()
    carbon.register_statuses = [_HOT_KEY_EXISTS, 0]

    with pytest.raises(RuntimeError, match="already uses the hotkey"):
        service.rebind(HotkeyAction.LOOKUP, "cmd+alt+k")

    assert carbon.installed == 1
    assert service.bindings[HotkeyAction.LOOKUP] == "<ctrl>+<shift>+<space>"
    assert carbon.press(carbon.registered[-1][2]) == 0
    assert actions == [HotkeyAction.LOOKUP]


def test_service_shutdown_releases_the_carbon_registration(carbon: _FakeCarbon) -> None:
    service = HotkeyService(
        lambda _action, _edge: None,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        listener_factory=darwin_listener_factory,
    )
    service.register()

    service.shutdown()
    service.shutdown()

    assert len(carbon.unregistered) == 1
    assert carbon.removed == 1
    assert service.registered is False


def test_a_binding_macos_cannot_register_fails_at_registration(
    carbon: _FakeCarbon,
) -> None:
    service = HotkeyService(
        lambda _action, _edge: None,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+media_play"},
        listener_factory=darwin_listener_factory,
    )

    with pytest.raises(HotkeyError, match="no key for"):
        service.register()

    assert service.registered is False
    assert carbon.registered == []
