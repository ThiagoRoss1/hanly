from __future__ import annotations

import sys
from collections.abc import Callable, Mapping

import pytest
from hanly_app.hotkeys import (
    DuplicateHotkeyError,
    HotkeyAction,
    HotkeyService,
)


class _Listener:
    def __init__(self, callbacks: Mapping[str, Callable[[], None]]) -> None:
        self.callbacks = dict(callbacks)
        self.started = 0
        self.stopped = 0
        self.joined = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def join(self, timeout: float | None = None) -> None:
        assert timeout == 1.0
        self.joined += 1

    def trigger(self, binding: str) -> None:
        self.callbacks[binding]()


def _service(
    on_action: Callable[[HotkeyAction], None],
    *,
    bindings: Mapping[HotkeyAction | str, str] | None = None,
    dispatcher: Callable[[Callable[[], None]], None] | None = None,
) -> tuple[HotkeyService, list[_Listener]]:
    listeners: list[_Listener] = []

    def factory(callbacks: Mapping[str, Callable[[], None]]) -> _Listener:
        listener = _Listener(callbacks)
        listeners.append(listener)
        return listener

    return (
        HotkeyService(
            on_action,
            bindings=bindings,
            dispatcher=dispatcher,
            listener_factory=factory,
        ),
        listeners,
    )


def test_registers_all_actions_with_normalized_pynput_bindings() -> None:
    service, listeners = _service(lambda _action: None)

    service.register()

    assert service.registered is True
    assert listeners[0].started == 1
    assert set(listeners[0].callbacks) == {
        "<ctrl>+<shift>+<space>",
        "<ctrl>+<shift>+<f9>",
        "<ctrl>+<shift>+<f10>",
    }


def test_trigger_delivers_normalized_actions_to_orchestration() -> None:
    received: list[HotkeyAction] = []
    service, listeners = _service(
        received.append,
        bindings={
            HotkeyAction.LOOKUP: "Ctrl+Shift+Space",
            HotkeyAction.START_CAPTURE: "Ctrl+Shift+F9",
            HotkeyAction.PAUSE_CAPTURE: "Ctrl+Shift+F10",
        },
    )
    service.register()

    listeners[0].trigger("<ctrl>+<shift>+<space>")
    listeners[0].trigger("<ctrl>+<shift>+<f9>")
    listeners[0].trigger("<ctrl>+<shift>+<f10>")

    assert received == [
        HotkeyAction.LOOKUP,
        HotkeyAction.START_CAPTURE,
        HotkeyAction.PAUSE_CAPTURE,
    ]


def test_dispatcher_posts_without_running_application_handler_on_listener_thread() -> None:
    received: list[HotkeyAction] = []
    posted: list[Callable[[], None]] = []
    service, listeners = _service(
        received.append,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        dispatcher=posted.append,
    )
    service.register()

    listeners[0].trigger("<ctrl>+<shift>+<space>")

    assert received == []
    assert len(posted) == 1
    posted[0]()
    assert received == [HotkeyAction.LOOKUP]


def test_duplicate_bindings_are_rejected_after_normalization() -> None:
    with pytest.raises(DuplicateHotkeyError):
        _service(
            lambda _action: None,
            bindings={
                HotkeyAction.LOOKUP: "ctrl+shift+space",
                HotkeyAction.PAUSE_CAPTURE: "SHIFT+CTRL+<space>",
            },
        )


def test_registration_is_idempotent_and_unregister_is_idempotent() -> None:
    service, listeners = _service(lambda _action: None)

    service.register()
    service.register()
    service.unregister()
    service.unregister()

    assert len(listeners) == 1
    assert listeners[0].started == 1
    assert listeners[0].stopped == 1
    assert listeners[0].joined == 1
    assert service.registered is False


def test_rebind_replaces_active_listener_without_losing_registration() -> None:
    received: list[HotkeyAction] = []
    service, listeners = _service(
        received.append,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
    )
    service.register()

    service.rebind(HotkeyAction.LOOKUP, "alt+shift+h")

    assert service.registered is True
    assert service.bindings[HotkeyAction.LOOKUP] == "<shift>+<alt>+h"
    assert listeners[0].stopped == 1
    assert listeners[1].started == 1
    listeners[1].trigger("<shift>+<alt>+h")
    assert received == [HotkeyAction.LOOKUP]


def test_dispatch_queued_before_unregister_is_suppressed() -> None:
    posted: list[Callable[[], None]] = []
    received: list[HotkeyAction] = []
    service, listeners = _service(
        received.append,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        dispatcher=posted.append,
    )
    service.register()
    listeners[0].trigger("<ctrl>+<shift>+<space>")

    service.unregister()
    posted[0]()

    assert received == []


def test_partial_registration_failure_rolls_back_listener_state() -> None:
    listeners: list[_Listener] = []

    class _FailingListener(_Listener):
        def start(self) -> None:
            super().start()
            raise RuntimeError("listener could not start")

    def factory(callbacks: Mapping[str, Callable[[], None]]) -> _FailingListener:
        listener = _FailingListener(callbacks)
        listeners.append(listener)
        return listener

    service = HotkeyService(
        lambda _action: None,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        listener_factory=factory,
    )

    with pytest.raises(RuntimeError, match="could not start"):
        service.register()

    assert service.registered is False
    assert listeners[0].stopped == 1
    assert listeners[0].joined == 1


def test_shutdown_unregisters_once_and_rejects_future_registration() -> None:
    service, listeners = _service(lambda _action: None)
    service.register()

    service.shutdown()
    service.shutdown()

    assert listeners[0].stopped == 1
    assert service.registered is False
    with pytest.raises(RuntimeError, match="shut down"):
        service.register()


def test_handler_that_shuts_down_the_service_does_not_self_join() -> None:
    # pynput's listener is a Thread and runs hotkey callbacks on it, so a
    # "quit" hotkey ends up joining the thread it is running on.
    class _SelfJoiningListener(_Listener):
        def join(self, timeout: float | None = None) -> None:
            self.joined += 1
            raise RuntimeError("cannot join current thread")

    listeners: list[_SelfJoiningListener] = []

    def factory(callbacks: Mapping[str, Callable[[], None]]) -> _SelfJoiningListener:
        listener = _SelfJoiningListener(callbacks)
        listeners.append(listener)
        return listener

    service = HotkeyService(
        lambda _action: service.shutdown(),
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
        listener_factory=factory,
    )
    service.register()

    listeners[0].trigger(service.bindings[HotkeyAction.LOOKUP])

    assert service.registered is False
    assert listeners[0].stopped == 1


def test_action_handler_does_not_block_shutdown_from_another_thread() -> None:
    # Holding the lifecycle lock across the handler would block any other
    # thread trying to unregister or shut the service down until it returns.
    import threading

    in_handler = threading.Event()
    release = threading.Event()
    shutdown_returned = threading.Event()

    def handler(_action: HotkeyAction) -> None:
        in_handler.set()
        release.wait(2.0)

    service, listeners = _service(handler)
    service.register()

    listener_thread = threading.Thread(
        target=lambda: listeners[0].trigger(service.bindings[HotkeyAction.LOOKUP])
    )
    listener_thread.start()
    assert in_handler.wait(2.0)

    def shutdown() -> None:
        service.shutdown()
        shutdown_returned.set()

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    returned_while_handler_ran = shutdown_returned.wait(1.0)

    release.set()
    listener_thread.join(timeout=5.0)
    shutdown_thread.join(timeout=5.0)

    assert not listener_thread.is_alive()
    assert not shutdown_thread.is_alive()
    assert shutdown_returned.is_set()
    assert returned_while_handler_ran


def test_register_reports_a_missing_pynput_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``None`` in sys.modules is the documented way to make an import fail, and
    # it keeps this test from touching real OS-level hotkey registration.
    monkeypatch.setitem(sys.modules, "pynput", None)
    service = HotkeyService(
        lambda _action: None,
        bindings={HotkeyAction.LOOKUP: "ctrl+shift+space"},
    )

    with pytest.raises(RuntimeError, match="pynput is required"):
        service.register()

    assert service.registered is False
