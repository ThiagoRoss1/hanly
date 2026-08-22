"""Composition for the first developer-runnable manual lookup alpha.

This module owns only desktop wiring.  The existing :class:`HanlyRuntime`
still supplies the concrete provider factories, while
:class:`LookupController` keeps lookup work bounded and worker-owned. The
composition root supplies one dispatcher to both hotkeys and lookup results so
application work always returns to the UI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock, Thread
from typing import TYPE_CHECKING, Protocol, TypeAlias

from hanly import HanlyError, LookupResult, LookupStatus, Point

from .capture import CaptureResult
from .config import AppConfig
from .hotkeys import (
    DEFAULT_HOTKEYS,
    HotkeyAction,
    HotkeyBindings,
    HotkeyDispatcher,
    HotkeyHandler,
    HotkeyService,
)
from .hover_controller import HoverScheduler
from .hover_lookup import HoverErrorHandler, HoverLookupRuntime
from .lookup_controller import LookupController, ResultDispatcher, ResultHandler
from .mouse_observer import MouseListenerFactory

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


class RuntimeComposition(Protocol):
    """The existing runtime seam consumed by desktop composition."""

    def create_lookup_controller(
        self,
        on_result: ResultHandler | None = None,
        *,
        result_dispatcher: ResultDispatcher | None = None,
        thread_name: str | None = None,
    ) -> LookupController:
        """Build the already-composed worker-backed lookup controller."""


class CaptureSource(Protocol):
    """Capture and lifecycle operations used by manual lookup."""

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        """Capture a cursor-centered ROI and return its local target point."""

    def close(self) -> None:
        """Release any owned capture backend."""


class HotkeyRuntime(Protocol):
    """Lifecycle subset needed by the manual composition."""

    def register(self) -> None:
        """Start listening for the configured lookup hotkey."""

    def shutdown(self) -> None:
        """Stop listening and release the listener."""


PopupPresenter: TypeAlias = Callable[[LookupResult], object]
CursorProvider: TypeAlias = Callable[[], Point]
ShutdownScheduler: TypeAlias = Callable[[Callable[[], None]], None]
HotkeyFactory: TypeAlias = Callable[
    [HotkeyHandler, HotkeyBindings, HotkeyDispatcher], HotkeyRuntime
]


class ManualLookupStartupError(RuntimeError):
    """Raised when the manual desktop path cannot start cleanly."""


class ManualLookupRuntime:
    """Own one running manual hotkey-to-capture-to-popup desktop path."""

    def __init__(
        self,
        controller: LookupController,
        capture_service: CaptureSource,
        popup: PopupPresenter,
        *,
        close_popup: Callable[[], None],
        current_cursor: CursorProvider,
        dispatcher: ResultDispatcher,
        clear_popup: Callable[[], None] | None = None,
        hotkey: str = DEFAULT_HOTKEYS[HotkeyAction.LOOKUP],
        hotkey_factory: HotkeyFactory | None = None,
        shutdown_scheduler: ShutdownScheduler | None = None,
        hover_runtime: HoverLookupRuntime | None = None,
    ) -> None:
        if not isinstance(controller, LookupController):
            raise TypeError("controller must be a LookupController")
        if not callable(capture_service.capture_at_cursor):
            raise TypeError("capture_service must provide capture_at_cursor(cursor)")
        if not callable(capture_service.close):
            raise TypeError("capture_service must provide close()")
        if not callable(popup):
            raise TypeError("popup must be callable")
        if not callable(close_popup):
            raise TypeError("close_popup must be callable")
        if clear_popup is not None and not callable(clear_popup):
            raise TypeError("clear_popup must be callable")
        if not callable(current_cursor):
            raise TypeError("current_cursor must be callable")
        if not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if not isinstance(hotkey, str) or not hotkey.strip():
            raise TypeError("hotkey must be a non-empty string")
        if hover_runtime is not None and not isinstance(hover_runtime, HoverLookupRuntime):
            raise TypeError("hover_runtime must be a HoverLookupRuntime")

        self._controller = controller
        self._capture_service = capture_service
        self._popup = popup
        self._close_popup = close_popup
        self._clear_popup = clear_popup or close_popup
        self._current_cursor = current_cursor
        self._dispatcher = dispatcher
        self._shutdown_scheduler = shutdown_scheduler or _schedule_shutdown
        self._hover_runtime = hover_runtime
        self._hotkeys = (hotkey_factory or _create_hotkey)(
            self._handle_action,
            {HotkeyAction.LOOKUP: hotkey},
            dispatcher,
        )
        self._lock = RLock()
        self._started = False
        self._closed = False

    @property
    def controller(self) -> LookupController:
        """Return the existing bounded lookup controller used by the path."""

        return self._controller

    @property
    def hotkeys(self) -> HotkeyRuntime:
        """Return the configured hotkey service for lifecycle diagnostics."""

        return self._hotkeys

    @property
    def hover_runtime(self) -> HoverLookupRuntime | None:
        """Return the optional automatic-hover path sharing this composition."""

        return self._hover_runtime

    def attach_hover(self, hover_runtime: HoverLookupRuntime) -> None:
        """Attach automatic hover before startup, sharing controller and capture."""

        if not isinstance(hover_runtime, HoverLookupRuntime):
            raise TypeError("hover_runtime must be a HoverLookupRuntime")
        if hover_runtime.controller is not self._controller:
            raise ValueError("hover_runtime must use the manual lookup controller")
        with self._lock:
            if self._started or self._closed:
                raise RuntimeError("hover runtime must be attached before startup")
            if self._hover_runtime is not None:
                raise RuntimeError("manual lookup already has a hover runtime")
            self._hover_runtime = hover_runtime

    @property
    def started(self) -> bool:
        """Whether the manual path accepts lookup actions."""

        with self._lock:
            return self._started and not self._closed

    def start(self) -> None:
        """Start the worker and then register the sole lookup hotkey."""

        with self._lock:
            if self._closed:
                raise RuntimeError("manual lookup runtime has been shut down")
            if self._started:
                hover_runtime = self._hover_runtime
                if hover_runtime is not None and not hover_runtime.failed:
                    hover_runtime.resume()
                return
            self._started = True

        try:
            self._controller.start()
            self._hotkeys.register()
            if self._hover_runtime is not None:
                self._hover_runtime.start()
        except Exception as error:
            # Roll back through the ordinary shutdown path so the popup and
            # capture service acquired before start() are closed too. Marking
            # the runtime closed first would make that cleanup unreachable.
            with self._lock:
                self._started = False
            self.shutdown()
            raise ManualLookupStartupError(
                f"could not start manual lookup hotkey path: {error}"
            ) from error

    def shutdown(self) -> None:
        """Close UI resources and request non-blocking worker/listener shutdown."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._started = False

        # Invalidate before stop so queued or in-flight results fail the
        # controller's final currency check. The worker is never joined here.
        if self._hover_runtime is not None:
            self._hover_runtime.shutdown()
        self._controller.invalidate()
        try:
            self._controller.stop(wait=False)
        finally:
            try:
                self._close_popup()
            finally:
                try:
                    self._capture_service.close()
                finally:
                    self._schedule_hotkey_shutdown()

    def invalidate(self) -> None:
        """Drop the current lookup attempt while both triggers keep running."""

        with self._lock:
            if self._closed:
                return
            hover_runtime = self._hover_runtime
        self._controller.invalidate()
        if hover_runtime is not None:
            hover_runtime.invalidate()

    def pause(self) -> None:
        """Stop automatic hover observation, leaving the manual hotkey live."""

        with self._lock:
            if self._closed:
                return
            hover_runtime = self._hover_runtime
        self._controller.invalidate()
        if hover_runtime is not None:
            hover_runtime.pause()
        # Whatever the popup is showing describes work that is no longer
        # running, so stopping capture must not leave it on screen.
        self._clear_popup()

    def resume(self) -> None:
        """Resume the shared lookup path after :meth:`pause`."""

        self.start()

    def _handle_action(self, action: HotkeyAction) -> None:
        """Capture and submit from the UI-dispatched application callback."""

        with self._lock:
            if self._closed or not self._started:
                return
        if action is not HotkeyAction.LOOKUP:
            return

        stage = "cursor position"
        try:
            cursor = self._current_cursor()
            stage = "screen capture"
            capture = self._capture_service.capture_at_cursor(cursor)
            if not isinstance(capture, CaptureResult):
                raise TypeError("capture service returned an invalid CaptureResult")
            stage = "lookup submission"
            self._controller.submit(capture.image, capture.target)
        except Exception as error:
            self._popup(_action_error(stage, error))

    def _schedule_hotkey_shutdown(self) -> None:
        try:
            self._shutdown_scheduler(self._hotkeys.shutdown)
        except Exception:
            # Lifecycle cleanup should not replace the startup/shutdown error
            # with a failure from a best-effort background scheduler.
            pass


def create_manual_lookup(
    runtime: RuntimeComposition,
    capture_service: CaptureSource,
    popup: PopupPresenter,
    *,
    close_popup: Callable[[], None],
    current_cursor: CursorProvider,
    dispatcher: ResultDispatcher,
    clear_popup: Callable[[], None] | None = None,
    hotkey: str = DEFAULT_HOTKEYS[HotkeyAction.LOOKUP],
    hotkey_factory: HotkeyFactory | None = None,
    shutdown_scheduler: ShutdownScheduler | None = None,
    hover_enabled: bool = False,
    hover_delay_ms: float | None = None,
    hover_scheduler: HoverScheduler | None = None,
    app_config: AppConfig | None = None,
    hover_listener_factory: MouseListenerFactory | None = None,
    hover_on_error: HoverErrorHandler | None = None,
) -> ManualLookupRuntime:
    """Compose a manual path from the existing runtime and desktop seams."""

    controller = runtime.create_lookup_controller(
        _as_result_handler(popup),
        result_dispatcher=dispatcher,
        thread_name="hanly-manual-lookup",
    )
    manual = ManualLookupRuntime(
        controller,
        capture_service,
        popup,
        close_popup=close_popup,
        current_cursor=current_cursor,
        dispatcher=dispatcher,
        clear_popup=clear_popup,
        hotkey=hotkey,
        hotkey_factory=hotkey_factory,
        shutdown_scheduler=shutdown_scheduler,
    )
    if hover_enabled:
        manual.attach_hover(
            HoverLookupRuntime(
                controller,
                capture_service,
                delay_ms=_hover_delay(hover_delay_ms, app_config),
                scheduler=hover_scheduler,
                dispatcher=dispatcher,
                listener_factory=hover_listener_factory,
                on_error=hover_on_error,
            )
        )
    return manual


def create_qt_manual_lookup(
    runtime: RuntimeComposition,
    capture_service: CaptureSource,
    *,
    hotkey: str = DEFAULT_HOTKEYS[HotkeyAction.LOOKUP],
    parent: QWidget | None = None,
    hotkey_factory: HotkeyFactory | None = None,
    shutdown_scheduler: ShutdownScheduler | None = None,
    hover_enabled: bool = True,
    hover_delay_ms: float | None = None,
    hover_scheduler: HoverScheduler | None = None,
    app_config: AppConfig | None = None,
    hover_listener_factory: MouseListenerFactory | None = None,
    hover_on_error: HoverErrorHandler | None = None,
) -> ManualLookupRuntime:
    """Build the real Qt alpha composition on the caller's UI thread.

    One :class:`QtResultDispatcher` is constructed first and shared by both the
    hotkey service and the lookup controller, so hotkey actions and results
    both re-enter application code on the Qt UI thread.
    """

    from PyQt6.QtGui import QCursor

    from .popup import PopupController
    from .qt_hover_scheduler import QtHoverScheduler
    from .qt_popup import QtPopupTrigger, QtPopupView, QtResultDispatcher

    dispatcher = QtResultDispatcher(parent)
    view = QtPopupView(parent)
    popup_controller = PopupController(view, popup_size=view.popup_size)
    popup_trigger = QtPopupTrigger(popup_controller)
    controller = runtime.create_lookup_controller(
        _as_result_handler(popup_trigger.open),
        result_dispatcher=dispatcher,
        thread_name="hanly-manual-lookup",
    )

    def current_cursor() -> Point:
        cursor = QCursor.pos()
        return Point(float(cursor.x()), float(cursor.y()))

    manual = ManualLookupRuntime(
        controller,
        capture_service,
        popup_trigger.open,
        close_popup=popup_controller.close,
        clear_popup=popup_controller.clear,
        current_cursor=current_cursor,
        dispatcher=dispatcher,
        hotkey=hotkey,
        hotkey_factory=hotkey_factory,
        shutdown_scheduler=shutdown_scheduler,
    )
    if hover_enabled:
        manual.attach_hover(
            HoverLookupRuntime(
                controller,
                capture_service,
                delay_ms=_hover_delay(hover_delay_ms, app_config),
                # Debounce on the Qt UI thread that already dispatches movement
                # rather than spawning a timer thread per cursor event.
                scheduler=hover_scheduler or QtHoverScheduler(parent),
                dispatcher=dispatcher,
                listener_factory=hover_listener_factory,
                on_error=hover_on_error,
            )
        )
    return manual


def _hover_delay(delay_ms: float | None, app_config: AppConfig | None) -> float:
    """Resolve the hover debounce from the explicit value, then user config."""

    if delay_ms is not None:
        return delay_ms
    if app_config is not None:
        return float(app_config.hover_delay_ms)
    return AppConfig().hover_delay_ms


def _as_result_handler(popup: PopupPresenter) -> ResultHandler:
    """Adapt a popup presenter to the controller's result-handler contract.

    Presenters such as ``QtPopupTrigger.open`` return a placement value that
    the controller neither needs nor consumes.
    """

    def deliver(result: LookupResult) -> None:
        popup(result)

    return deliver


def _create_hotkey(
    on_action: HotkeyHandler,
    bindings: HotkeyBindings,
    dispatcher: HotkeyDispatcher,
) -> HotkeyRuntime:
    return HotkeyService(on_action, bindings=bindings, dispatcher=dispatcher)


def _action_error(stage: str, error: Exception) -> LookupResult:
    message = f"{stage} failed: {error}"
    return LookupResult(
        status=LookupStatus.ERROR,
        diagnostics=(message,),
        error=HanlyError(message),
    )


def _schedule_shutdown(callback: Callable[[], None]) -> None:
    Thread(target=callback, name="hanly-hotkey-shutdown", daemon=True).start()


__all__ = [
    "CaptureSource",
    "CursorProvider",
    "HotkeyFactory",
    "HotkeyRuntime",
    "HoverLookupRuntime",
    "HoverErrorHandler",
    "ManualLookupRuntime",
    "ManualLookupStartupError",
    "PopupPresenter",
    "RuntimeComposition",
    "ShutdownScheduler",
    "create_manual_lookup",
    "create_qt_manual_lookup",
]
