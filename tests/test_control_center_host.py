"""One window, one loop, and a close that actually lets Qt WebEngine go."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from hanly_app import control_center_host
from hanly_app.control_center import ControlCenterUnavailable
from hanly_app.control_center_host import (
    MINIMUM_INITIAL_SIZE,
    QT_BACKEND_MODULE,
    ControlCenterHost,
    initial_window_size,
)


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
    """The pywebview window surface, modelled on pywebview 6.2.1.

    ``minimized`` is deliberately inert. In the real library it is the
    constructor's option, assigned once and never updated; the Qt backend
    signals minimize and restore through events instead. A fake that flipped it
    on minimize would let a guard branch on state that does not exist, which is
    precisely how the restore defect survived its own test.

    ``native_minimized`` is what the window system would actually show, so a
    test can assert the user-visible outcome rather than the flag.
    """

    def __init__(self, *, minimized: bool = False) -> None:
        self.events = _Events()
        self.actions: list[str] = []
        #: The construction option. Never changes, exactly as pywebview does.
        self.minimized = minimized
        #: The real window state, which only ``restore`` clears.
        self.native_minimized = minimized

    def minimize(self) -> None:
        """What the user does with the yellow button or Command-M."""

        self.actions.append("minimize")
        self.native_minimized = True

    def show(self) -> None:
        self.actions.append("show")

    def restore(self) -> None:
        self.actions.append("restore")
        self.native_minimized = False

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


def _host(webview: _Webview, **options: Any) -> ControlCenterHost:
    return ControlCenterHost(object(), webview_module=webview, **options)


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


def test_closing_is_never_cancelled_into_a_hidden_window() -> None:
    """The window lives in a process of its own now, so closing it releases
    Qt WebEngine instead of hiding several hundred megabytes behind a tray."""

    webview = _Webview()
    host = _host(webview)
    host.run()
    window = webview.windows[0]

    assert window.events.closing.handlers == []


def test_quit_destroys_the_window_and_is_idempotent() -> None:
    webview = _Webview()
    host = _host(webview)
    host.run()
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


def test_a_session_without_a_screen_is_reported_before_pywebview_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order is the whole point: past this call pywebview reaches the primary
    screen's geometry itself, and answers for a session that has none from
    inside its own window creation."""

    reached: list[str] = []
    monkeypatch.setattr(
        control_center_host, "prepare_control_center_qt", lambda: reached.append("backend")
    )
    monkeypatch.setattr(
        control_center_host,
        "ensure_qt_application",
        lambda **_: reached.append("application"),
    )

    def refuse() -> None:
        reached.append("screen")
        raise ControlCenterUnavailable("this session has no usable screen")

    monkeypatch.setattr(control_center_host, "verify_primary_screen", refuse)

    with pytest.raises(ControlCenterUnavailable, match="no usable screen"):
        ControlCenterHost(object())._load_webview()

    assert reached == ["backend", "application", "screen"]


def test_a_minimized_window_becomes_visible_again() -> None:
    """The user-visible outcome, asserted without touching the inert flag.

    Restore must come first: showing and then restoring would flash the old
    geometry. The window reports ``minimized is False`` throughout, because
    pywebview never updates that attribute, so nothing may branch on it.
    """

    webview = _Webview()
    host = _host(webview)
    host.run()
    window = webview.windows[0]
    window.minimize()
    window.actions.clear()

    host.show()

    assert window.actions == ["restore", "show"]
    assert window.native_minimized is False
    assert window.minimized is False, "pywebview never updates this; do not read it"
    assert host.visible


def test_restore_is_called_even_when_the_window_is_already_up() -> None:
    """There is no readable state saying whether a restore is needed.

    Restoring an un-minimized window is a no-op, so the unconditional call is
    the safe direction; skipping it is what left the window in the Dock.
    """

    webview = _Webview()
    host = _host(webview)
    host.run()
    window = webview.windows[0]
    window.actions.clear()

    host.show()

    assert window.actions == ["restore", "show"]
    assert window.native_minimized is False


def test_repeated_minimize_and_reopen_reuses_the_same_window() -> None:
    """A restore must never create a second window or a second Dock tile."""

    webview = _Webview()
    host = _host(webview)
    host.run()
    window = webview.windows[0]

    for _ in range(3):
        window.minimize()
        host.show()
        assert window.native_minimized is False

    assert len(webview.windows) == 1
    assert host.window is window


def test_the_initial_size_follows_the_work_area_instead_of_filling_it() -> None:
    """A fixed 1080x760 asked for 97% of a 1408x787 MacBook work area.

    Width is preserved because the composition was designed around it; height
    is derived, so a short display gets a proportional window.
    """

    assert initial_window_size(1408, 787) == (1080, 614)
    assert initial_window_size(2560, 1380) == (1080, 760)


def test_the_initial_size_never_exceeds_a_small_work_area() -> None:
    """Native window controls must stay reachable on a short display."""

    width, height = initial_window_size(900, 500)

    assert (width, height) == (860, 500)
    assert width <= 900 and height <= 500


def test_the_initial_size_respects_the_minimum_the_layout_needs() -> None:
    assert initial_window_size(1440, 700) == (1080, MINIMUM_INITIAL_SIZE[1])


def test_an_explicit_size_is_honoured_over_the_derived_one() -> None:
    webview = _Webview()
    host = _host(webview, width=1200, height=900)
    host.run()

    created = next(
        kwargs for name, kwargs in webview.calls if name == "create_window"
    )
    assert created["width"] == 1200
    assert created["height"] == 900
