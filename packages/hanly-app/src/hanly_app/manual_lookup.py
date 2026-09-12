"""Composition for the first developer-runnable manual lookup alpha.

This module owns only desktop wiring.  The existing :class:`HanlyRuntime`
still supplies the concrete provider factories, while
:class:`LookupController` keeps lookup work bounded and worker-owned. The
composition root supplies one dispatcher to both hotkeys and lookup results so
application work always returns to the UI thread.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock, Thread, Timer
from typing import Any, Protocol, TypeAlias, cast

from hanly import HanlyError, LookupResult, LookupStatus, Point

from .capture import CaptureResult, ConfiguredCaptureService, ScreenRect
from .config import DEFAULT_HOVER_HOTKEY, AppConfig, CaptureMode, LookupPreload
from .hotkeys import (
    DEFAULT_HOTKEYS,
    HotkeyAction,
    HotkeyBindings,
    HotkeyDispatcher,
    HotkeyHandler,
    HotkeyService,
)
from .hover_controller import Cancellable, HoverScheduler
from .hover_lookup import HoverErrorHandler, HoverLookupRuntime
from .hover_target import CaptureOrigins, RetainedTarget, screen_rect
from .lookup_controller import LookupController, ResultDispatcher, ResultHandler
from .mouse_observer import MouseListenerFactory
from .popup import PopupController
from .runtime_trace import RuntimeTraceSink, emit_trace


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

    @property
    def bindings(self) -> Mapping[HotkeyAction, str]:
        """The combinations this service currently owns, not what was asked for."""

    @property
    def registered(self) -> bool:
        """Whether the operating system actually accepted those combinations."""

    def register(self) -> None:
        """Start listening for the configured shortcuts."""

    def shutdown(self) -> None:
        """Stop listening and release the listener."""


class LookupResidency(Protocol):
    """Where a preload policy touches the lookup engine, and nothing else.

    The engine decides how residency is achieved; this is the small surface
    that decides when. Keeping it this narrow is what lets a composition
    without a disposable engine -- a narrow test runtime, an embedded client --
    keep working with no policy at all.
    """

    @property
    def state(self) -> str:
        """Sleeping, preparing, ready, or error."""

    def prepare(self) -> None:
        """Ask for residency without waiting for it."""

    def retire(self) -> None:
        """Drop the providers now, leaving an engine a later request can wake."""

    def set_preload(self, preload: bool) -> None:
        """Record whether a later wake should be eager."""

    def reset_recovery_budget(self) -> None:
        """Refresh the automatic-recovery allowance for a deliberate start."""

    def idle_seconds(self) -> float:
        """How long since a lookup last finished."""


PopupPresenter: TypeAlias = Callable[[LookupResult], object]
InitializationErrorHandler: TypeAlias = Callable[[BaseException], None]
CursorProvider: TypeAlias = Callable[[], Point]
ShutdownScheduler: TypeAlias = Callable[[Callable[[], None]], None]
HotkeyFactory: TypeAlias = Callable[
    [HotkeyHandler, HotkeyBindings, HotkeyDispatcher], HotkeyRuntime
]
ErrorReporter: TypeAlias = Callable[[str, BaseException], None]
#: Returns why the screen cannot be captured right now, or ``None``. Composition
#: supplies it because only the desktop knows the platform's privacy model.
CaptureRefusal: TypeAlias = Callable[[], str | None]
#: Schedule one callback after a delay in seconds, returning its handle.
IdleScheduler: TypeAlias = Callable[[float, Callable[[], None]], Cancellable]

#: How long a manual session keeps the engine loaded once capture is off. Not a
#: preference: it exists so a single hotkey lookup does not hold a gigabyte for
#: the rest of the session, and a user has no way to reason about the number.
IDLE_TIMEOUT_SECONDS = 60.0


def _schedule_idle(seconds: float, callback: Callable[[], None]) -> Cancellable:
    """Default one-shot timer; composition may supply a deterministic one."""

    timer = Timer(seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


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
        hover_hotkey: str = DEFAULT_HOVER_HOTKEY,
        hotkey_factory: HotkeyFactory | None = None,
        shutdown_scheduler: ShutdownScheduler | None = None,
        trace_sink: RuntimeTraceSink | None = None,
        engine: LookupResidency | None = None,
        preload: LookupPreload = LookupPreload.WHEN_CAPTURE_STARTS,
        on_toggle_hover: Callable[[], None] | None = None,
        on_error: ErrorReporter | None = None,
        capture_refusal: CaptureRefusal | None = None,
        origins: CaptureOrigins | None = None,
        idle_scheduler: IdleScheduler | None = None,
        idle_timeout_seconds: float = IDLE_TIMEOUT_SECONDS,
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

        self._controller = controller
        self._capture_service = (
            capture_service
            if isinstance(capture_service, ConfiguredCaptureService)
            else ConfiguredCaptureService(capture_service)
        )
        self._popup = popup
        self._close_popup = close_popup
        self._clear_popup = clear_popup or close_popup
        self._current_cursor = current_cursor
        self._dispatcher = dispatcher
        self._shutdown_scheduler = shutdown_scheduler or _schedule_shutdown
        self._hover_runtime: HoverLookupRuntime | None = None
        self._trace_sink = trace_sink
        self._engine = engine
        self._preload = preload
        self._on_toggle_hover = on_toggle_hover
        self._on_error = on_error
        self._capture_refusal = capture_refusal
        self._origins = origins if origins is not None else CaptureOrigins()
        self._idle_scheduler = idle_scheduler or _schedule_idle
        self._idle_timeout = float(idle_timeout_seconds)
        self._hotkeys = (hotkey_factory or _create_hotkey)(
            self._handle_action,
            {HotkeyAction.LOOKUP: hotkey, HotkeyAction.TOGGLE_HOVER: hover_hotkey},
            dispatcher,
        )
        self._lock = RLock()
        self._prepared = False
        self._started = False
        self._closed = False
        self._hotkey = hotkey
        self._hover_hotkey = hover_hotkey
        self._capture_mode = CaptureMode.FULL_MONITOR
        self._idle_timer: Cancellable | None = None
        self._idle_generation = 0

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

    @property
    def capture_service(self) -> ConfiguredCaptureService:
        """Return the shared capture seam used by manual and hover paths."""

        return self._capture_service

    def apply_config(self, config: AppConfig) -> None:
        """Apply desktop preferences to already-running services."""

        if not isinstance(config, AppConfig):
            raise TypeError("config must be an AppConfig")

        with self._lock:
            if self._closed:
                return
            changed = {
                HotkeyAction.LOOKUP: config.hotkey,
                HotkeyAction.TOGGLE_HOVER: config.hover_hotkey,
            }
            current = {
                HotkeyAction.LOOKUP: self._hotkey,
                HotkeyAction.TOGGLE_HOVER: self._hover_hotkey,
            }
            hover_runtime = self._hover_runtime

        for action, binding in changed.items():
            if binding != current[action]:
                self._rebind(action, binding)

        if hover_runtime is not None:
            hover_runtime.set_delay_ms(float(config.hover_delay_ms))

        self._apply_preload_change(config.lookup_preload)

        self._capture_mode = config.capture_mode
        self._capture_service.set_preferences(
            capture_mode=config.capture_mode,
            monitor=self._capture_service.monitor,
            region=self._capture_service.region,
        )
        with self._lock:
            self._hotkey = config.hotkey
            self._hover_hotkey = config.hover_hotkey

    def _rebind(self, action: HotkeyAction, binding: str) -> None:
        """Replace one live binding, or refuse if the backend cannot."""

        rebind = getattr(self._hotkeys, "rebind", None)
        if callable(rebind):
            rebind(action, binding)
            return
        with self._lock:
            if self._prepared:
                raise RuntimeError("configured hotkey cannot be changed while running")

    def _apply_preload_change(self, preload: LookupPreload) -> None:
        """Apply a policy change immediately, without disturbing capture.

        Changing away from Always while nothing is watching the screen stops
        residency, unless a manual session is still using the engine -- which
        is exactly what the idle expiry is already counting down.
        """

        with self._lock:
            previous = self._preload
            if preload is previous:
                return
            self._preload = preload
            watching = self._started
            manual_session = self._idle_timer is not None

        if preload is LookupPreload.ALWAYS:
            self._apply_preload_policy()
            return

        self._with_engine(lambda engine: engine.set_preload(False))
        if not watching and not manual_session:
            self._with_engine(lambda engine: engine.retire())

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        """Apply Control Center target and region choices to both triggers."""

        if not isinstance(capture_mode, CaptureMode):
            raise TypeError("capture_mode must be a CaptureMode")
        # Whatever was retained describes a region of a screen Hanly is no
        # longer reading.
        hover = self._hover_runtime
        if hover is not None:
            hover.clear_target()
        self._capture_mode = capture_mode
        self._capture_service.set_preferences(
            capture_mode=capture_mode,
            monitor=monitor,
            region=region,
        )

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
        """Whether Hanly is currently watching the screen."""

        with self._lock:
            return self._started and not self._closed

    @property
    def prepared(self) -> bool:
        """Whether the session's shortcuts and lookup path are up."""

        with self._lock:
            return self._prepared and not self._closed

    @property
    def engine(self) -> LookupResidency | None:
        """The lookup engine whose residency this policy controls, if any."""

        return self._engine

    @property
    def preload(self) -> LookupPreload:
        """The residency policy currently in force."""

        with self._lock:
            return self._preload

    def prepare(self) -> None:
        """Bring the session up without watching the screen yet.

        Shortcut registration belongs here rather than to capture: the lookup
        key and the hover toggle are how a user asks for either, so a denied
        capture permission must not also cost them the keys. Provider residency
        is the preload policy's decision, applied before the executor starts so
        an eager policy pays for it on the executor thread.
        """

        with self._lock:
            if self._closed:
                raise RuntimeError("manual lookup runtime has been shut down")
            already = self._prepared
            self._prepared = True
        if already:
            return
        self._apply_preload_policy()
        self._controller.start()
        self._register_hotkeys()

    def start(self) -> None:
        """Begin watching the screen: the user's Start or toggle-on action."""

        self.prepare()
        with self._lock:
            if self._closed:
                raise RuntimeError("manual lookup runtime has been shut down")
            if self._started:
                hover_runtime = self._hover_runtime
                if hover_runtime is not None and not hover_runtime.failed:
                    hover_runtime.resume()
                return
            self._started = True

        # A deliberate activation, so the engine gets a fresh allowance for the
        # one automatic restart an unexpected exit is permitted.
        self._cancel_idle_expiry()
        self._with_engine(lambda engine: engine.reset_recovery_budget())
        if self._preload is not LookupPreload.ON_DEMAND:
            self._with_engine(lambda engine: engine.prepare())

        try:
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
                f"could not start automatic hover: {error}"
            ) from error

    def _register_hotkeys(self) -> None:
        """Register the shell's shortcuts, reporting rather than refusing.

        A combination another application already owns costs the user that one
        shortcut. It must not also cost them the tray, the window, the popup,
        and everything else the session was about to provide.
        """

        try:
            self._hotkeys.register()
        except Exception as error:
            self._report_error("Keyboard shortcuts", error)

    def _apply_preload_policy(self) -> None:
        """Tell the engine whether waking should be eager, and wake it if so."""

        eager = self._preload is LookupPreload.ALWAYS
        self._with_engine(lambda engine: engine.set_preload(eager))
        if eager:
            self._with_engine(lambda engine: engine.prepare())

    def _with_engine(self, action: Callable[[LookupResidency], None]) -> None:
        """Apply one residency decision, if this composition has an engine."""

        engine = self._engine
        if engine is None:
            return
        try:
            action(engine)
        except Exception as error:
            self._report_error("Lookup engine", error)

    def _report_error(self, stage: str, error: BaseException) -> None:
        if self._on_error is None:
            return
        try:
            self._on_error(stage, error)
        except Exception:
            # Reporting is a presentation callback like any other; a failure
            # here must not replace the lifecycle outcome it was describing.
            pass

    def shutdown(self) -> None:
        """Close UI resources and request non-blocking worker/listener shutdown."""

        self._shutdown(wait=False)

    def shutdown_gracefully(self) -> None:
        """Close desktop resources and wait for worker-owned providers to close.

        Only safe on a thread that may block, such as process exit. A UI
        thread must use :meth:`begin_shutdown` and :meth:`await_shutdown`.
        """

        self._shutdown(wait=True)
        self.await_shutdown()

    def begin_shutdown(self) -> None:
        """Release UI-owned resources and request worker shutdown without waiting.

        Safe to call on the Qt thread: it never joins the lookup worker, so an
        in-flight OCR job cannot freeze the popup, tray, or Control Center.
        """

        self._shutdown(wait=False)

    def await_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for worker-owned providers to close after :meth:`begin_shutdown`.

        Must be called from a thread that may block. Returns whether the
        worker finished, so a caller can decide not to touch files it still
        holds open.
        """

        return self._controller.join(timeout)

    def _shutdown(self, *, wait: bool) -> None:
        """Shared teardown with an explicit UI-safe or process-exit wait policy."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._started = False
            self._prepared = False
        self._cancel_idle_expiry()

        # Invalidate before stop so queued or in-flight results fail the
        # controller's final currency check. Production shutdown waits so
        # worker-owned provider and SQLite cleanup completes before exit.
        if self._hover_runtime is not None:
            self._hover_runtime.shutdown()
        self._controller.invalidate()
        try:
            self._controller.stop(wait=wait)
        finally:
            try:
                self._close_popup()
            finally:
                try:
                    self._capture_service.close()
                finally:
                    if wait:
                        self._hotkeys.shutdown()
                    else:
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
        """Stop watching the screen, leaving the shortcuts live.

        Every policy but Always gives the providers back here. Always is the
        choice that deliberately opts into residency through a pause, which is
        the whole reason it exists.
        """

        with self._lock:
            if self._closed:
                return
            hover_runtime = self._hover_runtime
            self._started = False
        self._controller.invalidate()
        if hover_runtime is not None:
            hover_runtime.pause()
        # Whatever the popup is showing describes work that is no longer
        # running, so stopping capture must not leave it on screen.
        self._clear_popup()
        self._cancel_idle_expiry()
        if self._preload is not LookupPreload.ALWAYS:
            self._with_engine(lambda engine: engine.retire())

    def _arm_idle_expiry(self) -> None:
        """Give a manual session an expiry, but only while capture is off.

        A hotkey lookup with nothing watching the screen should not hold the
        engine for the rest of the session, and capture that is already running
        keeps it warm on its own.
        """

        with self._lock:
            if self._closed or self._started or self._engine is None:
                return
            if self._preload is LookupPreload.ALWAYS:
                return
            self._idle_generation += 1
            generation = self._idle_generation
            previous = self._idle_timer
            self._idle_timer = None
        if previous is not None:
            previous.cancel()
        self._schedule_expiry(generation, self._idle_timeout)

    def _schedule_expiry(self, generation: int, seconds: float) -> None:
        try:
            timer = self._idle_scheduler(seconds, lambda: self._idle_expired(generation))
        except Exception as error:
            self._report_error("Lookup engine", error)
            return
        with self._lock:
            current = generation == self._idle_generation and not self._closed
            if current:
                self._idle_timer = timer
        if not current:
            timer.cancel()

    def _idle_expired(self, generation: int) -> None:
        """Retire an engine nothing has used, or wait out the rest of its idle."""

        engine = self._engine
        with self._lock:
            if engine is None or self._closed or generation != self._idle_generation:
                return
            if self._started:
                return
            self._idle_timer = None
        remaining = self._idle_timeout - engine.idle_seconds()
        if remaining > 0:
            self._schedule_expiry(generation, remaining)
            return
        self._with_engine(lambda residency: residency.retire())

    def _cancel_idle_expiry(self) -> None:
        with self._lock:
            self._idle_generation += 1
            timer = self._idle_timer
            self._idle_timer = None
        if timer is not None:
            timer.cancel()

    def resume(self) -> None:
        """Resume the shared lookup path after :meth:`pause`."""

        self.start()

    def _handle_action(self, action: HotkeyAction) -> None:
        """Capture and submit from the UI-dispatched application callback.

        The trace events are what makes the one-shot hotkey path observable:
        the global backend delivers a key combination with no visible effect
        of its own, so each stage says where a lookup that never reached the
        popup actually stopped.
        """

        with self._lock:
            # Watching the screen is not required -- a manual lookup with
            # capture off is an ordinary way to use Hanly -- but a session that
            # has not been prepared has no lookup path to submit to.
            ignored = self._closed or not self._prepared
        if ignored:
            emit_trace(self._trace_sink, "manual_action_ignored", stage="manual_action")
            return
        if action is HotkeyAction.TOGGLE_HOVER:
            self._toggle_hover()
            return
        if action is not HotkeyAction.LOOKUP:
            return

        emit_trace(self._trace_sink, "manual_action_received", stage="manual_action")

        refusal = self._capture_refused()
        if refusal is not None:
            emit_trace(self._trace_sink, "manual_action_refused", stage="screen permission")
            self._popup(_refusal_result(refusal))
            return

        stage = "cursor position"
        try:
            cursor = self._current_cursor()
            stage = "screen capture"
            capture = self._capture_service.capture_at_cursor(cursor)
            if not isinstance(capture, CaptureResult):
                raise TypeError("capture service returned an invalid CaptureResult")
            emit_trace(
                self._trace_sink,
                "manual_capture_completed",
                stage="manual_capture",
                roi_width=capture.image.width,
                roi_height=capture.image.height,
                region_left=capture.region.left,
                region_top=capture.region.top,
                target_x=capture.target.x,
                target_y=capture.target.y,
            )
            stage = "lookup submission"
            request = self._controller.submit(capture.image, capture.target)
            # The origin belongs to this request, not to whatever was captured
            # most recently by the time the answer comes back.
            self._origins.remember(request.request_id, capture.region)
        except Exception as error:
            emit_trace(
                self._trace_sink,
                "manual_action_error",
                stage=stage,
                error_type=type(error).__name__,
            )
            self._popup(_action_error(stage, error))
            return

        emit_trace(
            self._trace_sink,
            "manual_submission",
            stage="manual_submission",
            lookup_request_id=request.request_id,
        )
        # A lookup with nothing watching the screen keeps the engine only as
        # long as it is still being used.
        self._arm_idle_expiry()

    def _capture_refused(self) -> str | None:
        """Say why a capture cannot work, rather than reading the wallpaper.

        Without Screen Recording macOS hands back a picture of the desktop
        background, which reads as "no Korean text here" instead of as a
        permission nobody granted.
        """

        if self._capture_refusal is None:
            return None
        try:
            return self._capture_refusal()
        except Exception as error:
            self._report_error("Screen permission", error)
            return None

    def note_presented(
        self,
        result: LookupResult,
        lookup_request_id: int | None,
        popup: ScreenRect | None = None,
    ) -> None:
        """Retain where a successful answer came from, so it can be read.

        Only a successful result is worth protecting: the others are already
        suppressed rather than shown, and keeping a region for them would
        freeze hover over a word Hanly could not read.
        """

        hover = self._hover_runtime
        if hover is None:
            return
        word = self._word_rect(result, lookup_request_id)
        if word is None or lookup_request_id is None:
            hover.clear_target()
            return
        hover.retain(RetainedTarget(lookup_request_id, word, popup))

    def _word_rect(
        self, result: LookupResult, lookup_request_id: int | None
    ) -> ScreenRect | None:
        """Place the resolved word on screen, using its own request's capture."""

        if result.status is not LookupStatus.SUCCESS or result.context is None:
            return None
        bounds = result.context.word_region
        region = self._origins.origin(lookup_request_id)
        if bounds is None or region is None:
            return None
        return screen_rect(region, bounds)

    def _toggle_hover(self) -> None:
        """Hand the toggle to whoever owns the capture lifecycle.

        The runtime does not decide this itself: the desktop controller holds
        the capture state, and a start that bypassed it would leave the tray
        and the Control Center describing something that is not happening.
        """

        emit_trace(self._trace_sink, "hover_toggle_received", stage="manual_action")
        callback = self._on_toggle_hover
        if callback is None:
            return
        try:
            callback()
        except Exception as error:
            self._report_error("Hover shortcut", error)

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
    on_initialization_error: InitializationErrorHandler | None = None,
    trace_sink: RuntimeTraceSink | None = None,
    on_toggle_hover: Callable[[], None] | None = None,
    on_error: ErrorReporter | None = None,
    capture_refusal: CaptureRefusal | None = None,
    on_diagnostic: Callable[[str], None] | None = None,
    on_engine_state: Callable[[str, str], None] | None = None,
    idle_scheduler: IdleScheduler | None = None,
) -> ManualLookupRuntime:
    """Compose a manual path from the existing runtime and desktop seams."""

    engine = _create_engine(
        runtime,
        app_config,
        trace_sink=trace_sink,
        on_diagnostic=on_diagnostic,
        on_state=on_engine_state,
    )
    origins = CaptureOrigins()
    manual_holder: list[ManualLookupRuntime] = []

    def present(result: LookupResult) -> None:
        popup(result)
        if manual_holder:
            manual_holder[0].note_presented(result, controller.current_request_id)

    controller = _create_runtime_controller(
        runtime,
        present,
        dispatcher,
        trace_sink=trace_sink,
        on_initialization_error=on_initialization_error,
        engine=engine,
    )
    configured_capture = (
        capture_service
        if isinstance(capture_service, ConfiguredCaptureService)
        else ConfiguredCaptureService(capture_service)
    )
    configured_hotkey = app_config.hotkey if app_config is not None else hotkey
    manual = ManualLookupRuntime(
        controller,
        configured_capture,
        popup,
        close_popup=close_popup,
        current_cursor=current_cursor,
        dispatcher=dispatcher,
        clear_popup=clear_popup,
        hotkey=configured_hotkey,
        hover_hotkey=_configured_hover_hotkey(app_config),
        hotkey_factory=hotkey_factory,
        shutdown_scheduler=shutdown_scheduler,
        trace_sink=trace_sink,
        engine=engine,
        preload=_configured_preload(app_config),
        on_toggle_hover=on_toggle_hover,
        on_error=on_error,
        capture_refusal=capture_refusal,
        origins=origins,
        idle_scheduler=idle_scheduler,
    )
    manual_holder.append(manual)
    if hover_enabled:
        manual.attach_hover(
            HoverLookupRuntime(
                controller,
                manual.capture_service,
                delay_ms=_hover_delay(hover_delay_ms, app_config),
                scheduler=hover_scheduler,
                dispatcher=dispatcher,
                listener_factory=hover_listener_factory,
                on_error=hover_on_error,
                on_invalidate=clear_popup or close_popup,
                trace_sink=trace_sink,
                origins=origins,
            )
        )
    if app_config is not None:
        manual.apply_config(app_config)
    return manual


def create_qt_manual_lookup(
    runtime: RuntimeComposition,
    capture_service: CaptureSource,
    *,
    hotkey: str = DEFAULT_HOTKEYS[HotkeyAction.LOOKUP],
    hotkey_factory: HotkeyFactory | None = None,
    shutdown_scheduler: ShutdownScheduler | None = None,
    hover_enabled: bool = True,
    hover_delay_ms: float | None = None,
    hover_scheduler: HoverScheduler | None = None,
    app_config: AppConfig | None = None,
    hover_listener_factory: MouseListenerFactory | None = None,
    hover_on_error: HoverErrorHandler | None = None,
    on_initialization_error: InitializationErrorHandler | None = None,
    trace_sink: RuntimeTraceSink | None = None,
    on_toggle_hover: Callable[[], None] | None = None,
    on_error: ErrorReporter | None = None,
    capture_refusal: CaptureRefusal | None = None,
    on_diagnostic: Callable[[str], None] | None = None,
    on_engine_state: Callable[[str, str], None] | None = None,
    idle_scheduler: IdleScheduler | None = None,
) -> ManualLookupRuntime:
    """Build the real Qt alpha composition on the caller's UI thread.

    One :class:`QtResultDispatcher` is constructed first and shared by both the
    hotkey service and the lookup controller, so hotkey actions and results
    both re-enter application code on the Qt UI thread.
    """

    from PyQt6.QtGui import QCursor

    from .qt_hover_scheduler import QtHoverScheduler
    from .qt_popup import QtPopupTrigger, QtPopupView, QtResultDispatcher

    dispatcher = QtResultDispatcher()
    view = QtPopupView()
    popup_controller = PopupController(view, popup_size=view.popup_size)
    popup_trigger = QtPopupTrigger(popup_controller, trace_sink=trace_sink)

    controller: LookupController

    origins = CaptureOrigins()
    manual_holder: list[ManualLookupRuntime] = []

    def present_result(result: LookupResult) -> object:
        lookup_request_id = controller.current_request_id
        position = popup_trigger.open(result, lookup_request_id=lookup_request_id)
        if manual_holder:
            manual_holder[0].note_presented(
                result, lookup_request_id, _popup_rect(position, view.popup_size)
            )
        return position

    engine = _create_engine(
        runtime,
        app_config,
        trace_sink=trace_sink,
        on_diagnostic=on_diagnostic,
        on_state=on_engine_state,
    )
    controller = _create_runtime_controller(
        runtime,
        _as_result_handler(present_result),
        dispatcher,
        trace_sink=trace_sink,
        on_initialization_error=on_initialization_error,
        engine=engine,
    )

    def current_cursor() -> Point:
        cursor = QCursor.pos()
        return Point(float(cursor.x()), float(cursor.y()))

    configured_capture = (
        capture_service
        if isinstance(capture_service, ConfiguredCaptureService)
        else ConfiguredCaptureService(capture_service)
    )
    configured_hotkey = app_config.hotkey if app_config is not None else hotkey
    manual = ManualLookupRuntime(
        controller,
        configured_capture,
        popup_trigger.open,
        close_popup=popup_controller.close,
        clear_popup=popup_controller.clear,
        current_cursor=current_cursor,
        dispatcher=dispatcher,
        hotkey=configured_hotkey,
        hover_hotkey=_configured_hover_hotkey(app_config),
        hotkey_factory=hotkey_factory,
        shutdown_scheduler=shutdown_scheduler,
        trace_sink=trace_sink,
        engine=engine,
        preload=_configured_preload(app_config),
        on_toggle_hover=on_toggle_hover,
        on_error=on_error,
        capture_refusal=capture_refusal,
        origins=origins,
        idle_scheduler=idle_scheduler,
    )
    manual_holder.append(manual)
    if hover_enabled:
        manual.attach_hover(
            HoverLookupRuntime(
                controller,
                manual.capture_service,
                delay_ms=_hover_delay(hover_delay_ms, app_config),
                # Debounce on the Qt UI thread that already dispatches movement
                # rather than spawning a timer thread per cursor event.
                scheduler=hover_scheduler or QtHoverScheduler(),
                dispatcher=dispatcher,
                listener_factory=hover_listener_factory,
                on_error=hover_on_error,
                on_invalidate=popup_controller.clear,
                trace_sink=trace_sink,
                origins=origins,
            )
        )
    if app_config is not None:
        manual.apply_config(app_config)
    return manual


def _popup_rect(position: object, size: object) -> ScreenRect | None:
    """Describe the frame the popup actually took, so the cursor may enter it."""

    if position is None:
        return None
    return ScreenRect(
        left=int(getattr(position, "x")),
        top=int(getattr(position, "y")),
        width=int(getattr(size, "width")),
        height=int(getattr(size, "height")),
    )


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


def _configured_preload(app_config: AppConfig | None) -> LookupPreload:
    return AppConfig().lookup_preload if app_config is None else app_config.lookup_preload


def _configured_hover_hotkey(app_config: AppConfig | None) -> str:
    return DEFAULT_HOVER_HOTKEY if app_config is None else app_config.hover_hotkey


def _create_engine(
    runtime: RuntimeComposition,
    app_config: AppConfig | None,
    *,
    trace_sink: RuntimeTraceSink | None,
    on_diagnostic: Callable[[str], None] | None,
    on_state: Callable[[str, str], None] | None,
) -> LookupResidency | None:
    """Build the disposable engine, for a runtime that offers one.

    A runtime without this seam keeps the controller it already composed, so a
    narrow custom composition still works -- it simply has no residency policy
    to apply.
    """

    factory = getattr(runtime, "create_lookup_engine", None)
    if not callable(factory):
        return None
    engine = factory(
        preload=_configured_preload(app_config) is LookupPreload.ALWAYS,
        trace_sink=trace_sink,
        on_diagnostic=on_diagnostic,
        on_state=on_state,
    )
    return cast(LookupResidency, engine)


def _create_runtime_controller(
    runtime: RuntimeComposition,
    on_result: ResultHandler,
    dispatcher: ResultDispatcher,
    *,
    trace_sink: RuntimeTraceSink | None,
    on_initialization_error: InitializationErrorHandler | None = None,
    engine: LookupResidency | None = None,
) -> LookupController:
    """Pass optional seams only when used, preserving narrow custom runtimes."""

    options: dict[str, Any] = {}
    if trace_sink is not None:
        options["trace_sink"] = trace_sink
    if on_initialization_error is not None:
        options["on_initialization_error"] = on_initialization_error
    if engine is not None:
        options["engine"] = engine
    if not options:
        return runtime.create_lookup_controller(
            on_result,
            result_dispatcher=dispatcher,
            thread_name="hanly-manual-lookup",
        )

    extended_creator = cast(Any, runtime.create_lookup_controller)
    return extended_creator(
        on_result,
        result_dispatcher=dispatcher,
        thread_name="hanly-manual-lookup",
        **options,
    )


def _create_hotkey(
    on_action: HotkeyHandler,
    bindings: HotkeyBindings,
    dispatcher: HotkeyDispatcher,
) -> HotkeyRuntime:
    return HotkeyService(on_action, bindings=bindings, dispatcher=dispatcher)


def _refusal_result(message: str) -> LookupResult:
    """Present a permission refusal as itself, never as an empty lookup."""

    return LookupResult(
        status=LookupStatus.UNUSABLE,
        diagnostics=(message,),
    )


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
    "IDLE_TIMEOUT_SECONDS",
    "CaptureOrigins",
    "CaptureRefusal",
    "CaptureSource",
    "CursorProvider",
    "ErrorReporter",
    "IdleScheduler",
    "LookupResidency",
    "HotkeyFactory",
    "HotkeyRuntime",
    "HoverLookupRuntime",
    "HoverErrorHandler",
    "InitializationErrorHandler",
    "ManualLookupRuntime",
    "ManualLookupStartupError",
    "PopupPresenter",
    "RuntimeComposition",
    "ShutdownScheduler",
    "create_manual_lookup",
    "create_qt_manual_lookup",
]
