"""One window, one loop, and a close that only hides when it can come back."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from hanly_app.control_center import ControlCenterUnavailable
from hanly_app.control_center_host import QT_BACKEND_MODULE, ControlCenterHost


class _Event:
    """pywebview's cancellable event: a handler returning ``False`` cancels."""

    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def __iadd__(self, handler: Any) -> _Event:
        self.handlers.append(handler)
        return self

    def fire(self) -> bool:
        return any(handler() is False for handler in self.handlers)


class _Events:
    def __init__(self) -> None:
        self.shown = _Event()
        self.closing = _Event()
        self.closed = _Event()


class _Window:
    def __init__(self) -> None:
        self.events = _Events()
        self.actions: list[str] = []

    def show(self) -> None:
        self.actions.append("show")

    def hide(self) -> None:
        self.actions.append("hide")

    def destroy(self) -> None:
        self.actions.append("destroy")
        self.events.closed.fire()


class _Webview:
    """The pywebview surface the host uses, with the loop that ``start`` owns."""

    def __init__(self, *, backend_name: str = QT_BACKEND_MODULE) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.windows: list[_Window] = []
        self.backend = SimpleNamespace(__name__=backend_name)

    def initialize(self, gui: str) -> Any:
        self.calls.append(("initialize", {"gui": gui}))
        return self.backend

    def create_window(self, **kwargs: Any) -> _Window:
        self.calls.append(("create_window", kwargs))
        window = _Window()
        self.windows.append(window)
        return window

    def start(self, **kwargs: Any) -> None:
        self.calls.append(("start", kwargs))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _host(webview: _Webview) -> ControlCenterHost:
    return ControlCenterHost(object(), webview_module=webview)


def test_run_creates_one_window_and_starts_the_qt_backend_once() -> None:
    webview = _Webview()
    host = _host(webview)

    assert host.run() == 0

    assert webview.names == ["create_window", "initialize", "start"]
    assert webview.calls[-1][1] == {"gui": "qt", "debug": False}
    assert len(webview.windows) == 1
    assert not host.running


def test_a_non_qt_backend_is_an_actionable_startup_error() -> None:
    """Silently mixing GTK or WinForms with Hanly's shared Qt is not allowed."""

    webview = _Webview(backend_name="webview.platforms.winforms")
    host = _host(webview)

    with pytest.raises(ControlCenterUnavailable, match="winforms"):
        host.run()

    assert "start" not in webview.names


def test_the_loop_cannot_be_run_from_a_worker_thread() -> None:
    errors: list[BaseException] = []
    host = _host(_Webview())

    def run() -> None:
        try:
            host.run()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert "main thread" in str(errors[0])


def test_visibility_follows_window_events_not_the_return_of_start() -> None:
    webview = _Webview()
    host = _host(webview)
    host.run()
    window = webview.windows[0]

    assert not host.visible
    window.events.shown.fire()
    assert host.visible

    host.hide()
    assert not host.visible
    assert window.actions[-1] == "hide"

    host.show()
    assert host.visible
    assert window.actions[-1] == "show"


def test_closing_hides_the_window_when_a_restoration_route_exists() -> None:
    webview = _Webview()
    host = _host(webview)
    host.run()
    host.set_restorable(True)
    window = webview.windows[0]

    cancelled = window.events.closing.fire()

    assert cancelled
    assert window.actions == ["hide"]
    assert host.created


def test_closing_without_a_tray_lets_the_window_go() -> None:
    """Never leave a background process the user has no way back to."""

    webview = _Webview()
    host = _host(webview)
    host.run()
    window = webview.windows[0]

    cancelled = window.events.closing.fire()

    assert not cancelled
    assert window.actions == []


def test_quit_destroys_the_window_and_is_idempotent() -> None:
    webview = _Webview()
    host = _host(webview)
    host.run()
    host.set_restorable(True)
    window = webview.windows[0]

    host.close()
    host.close()

    assert window.actions == ["destroy"]
    assert not host.created


def test_the_loop_refuses_to_run_twice() -> None:
    class _BlockingWebview(_Webview):
        def __init__(self) -> None:
            super().__init__()
            self.reentered: list[BaseException] = []

        def start(self, **kwargs: Any) -> None:
            super().start(**kwargs)
            try:
                host.run()
            except BaseException as error:
                self.reentered.append(error)

    webview = _BlockingWebview()
    host = _host(webview)

    host.run()

    assert len(webview.reentered) == 1
    assert "already running" in str(webview.reentered[0])
    assert webview.names.count("start") == 1
