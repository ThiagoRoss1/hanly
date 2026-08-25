"""Automatic hover composition over the existing desktop lookup path.

This module only joins the desktop seams that already own observation,
stability, capture, and lookup execution.  It does not construct providers or
an additional pipeline.  A caller may share the resulting runtime's
``LookupController`` with the manual hotkey path; only hover-owned requests
are invalidated when the cursor moves.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock, Thread
from time import perf_counter_ns
from typing import Protocol

from hanly import Point

from .capture import CaptureResult
from .hover_controller import HoverController, HoverRequest, HoverScheduler
from .lookup_controller import LookupController
from .mouse_observer import MouseListenerFactory, MouseObserver
from .runtime_trace import RuntimeTraceSink, emit_trace


class CaptureSource(Protocol):
    """Capture seam used by the automatic hover path."""

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        """Capture a small cursor-centered ROI."""


HoverErrorHandler = Callable[[str, BaseException], None]
HoverDispatcher = Callable[[Callable[[], None]], None]


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


class HoverLookupRuntime:
    """Run stable hover attempts through a shared lookup controller.

    ``LookupController`` is started by :meth:`start` and stopped by
    :meth:`shutdown`, but capture ownership remains with the composition root
    so a manual hotkey runtime can share the same service safely.  The caller
    may pass the UI dispatcher used by the manual path; observation and stable
    callbacks then re-enter the UI before capture or submission.
    """

    def __init__(
        self,
        controller: LookupController,
        capture_service: CaptureSource,
        *,
        delay_ms: float = 150,
        scheduler: HoverScheduler | None = None,
        dispatcher: HoverDispatcher | None = None,
        listener_factory: MouseListenerFactory | None = None,
        on_error: HoverErrorHandler | None = None,
        on_invalidate: Callable[[], None] | None = None,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> None:
        if not isinstance(controller, LookupController):
            raise TypeError("controller must be a LookupController")
        if not callable(capture_service.capture_at_cursor):
            raise TypeError("capture_service must provide capture_at_cursor(cursor)")
        if dispatcher is not None and not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("on_error must be callable")
        if on_invalidate is not None and not callable(on_invalidate):
            raise TypeError("on_invalidate must be callable")

        dispatch = dispatcher or _inline_dispatch
        self._controller = controller
        self._capture_service = capture_service
        self._on_error = on_error
        self._on_invalidate = on_invalidate
        self._trace_sink = trace_sink
        self._dispatcher = dispatch
        self._lock = RLock()
        self._running = False
        self._closed = False
        self._failed = False
        self._active_hover_request_id: int | None = None
        self._active_hover_id: int | None = None
        self._startup_point: Point | None = None
        self._readiness_generation = 0
        self._readiness_waiting = False
        self._hover = HoverController(
            self._on_stable,
            delay_ms=delay_ms,
            scheduler=scheduler,
            dispatcher=dispatch,
        )
        self._mouse = MouseObserver(
            self._on_position,
            dispatcher=dispatch,
            listener_factory=listener_factory,
        )
        self._hover.pause()

    @property
    def controller(self) -> LookupController:
        """Return the shared desktop lookup controller."""

        return self._controller

    @property
    def hover_controller(self) -> HoverController:
        """Return the stability controller for deterministic integration tests."""

        return self._hover

    @property
    def mouse_observer(self) -> MouseObserver:
        """Return the global mouse observer owned by this runtime."""

        return self._mouse

    @property
    def running(self) -> bool:
        """Whether this runtime currently accepts hover movement."""

        with self._lock:
            return self._running and not self._closed and not self._failed

    @property
    def failed(self) -> bool:
        """Whether a fatal lookup failure disabled hover for this process."""

        with self._lock:
            return self._failed

    @property
    def delay_ms(self) -> float:
        """Return the live debounce delay used by the hover controller."""

        return self._hover.delay_ms

    def set_delay_ms(self, delay_ms: float) -> None:
        """Apply a debounce delay to future and pending hover attempts."""

        self._hover.set_delay_ms(delay_ms)

    def start(self) -> None:
        """Start lookup execution and global observation."""

        with self._lock:
            if self._closed:
                raise RuntimeError("hover lookup runtime has been shut down")
            if self._failed:
                raise RuntimeError(
                    "automatic hover is unavailable until Hanly is restarted"
                )
            if self._running:
                return
            self._running = True

        try:
            self._controller.start()
            self._mouse.start()
            self._arm_observation_when_ready()
        except Exception:
            with self._lock:
                self._running = False
            self._mouse.stop()
            self._hover.pause()
            raise

    def pause(self) -> None:
        """Stop observation and invalidate a submitted hover attempt."""

        with self._lock:
            if self._closed or not self._running:
                return
            self._running = False
            self._readiness_generation += 1
            self._readiness_waiting = False
            self._startup_point = None

        self._mouse.stop()
        hover_request_id = self._hover.current_request_id
        self._hover.pause()
        emit_trace(
            self._trace_sink,
            "hover_invalidation",
            hover_request_id=hover_request_id,
        )
        self._invalidate_active_hover()

    def resume(self) -> None:
        """Resume observation after :meth:`pause`."""

        with self._lock:
            if self._closed:
                raise RuntimeError("hover lookup runtime has been shut down")
            if self._failed:
                raise RuntimeError(
                    "automatic hover is unavailable until Hanly is restarted"
                )
            if self._running:
                return
            self._running = True

        try:
            self._controller.start()
            self._mouse.start()
            self._arm_observation_when_ready()
        except Exception:
            with self._lock:
                self._running = False
            self._mouse.stop()
            self._hover.pause()
            raise

    def invalidate(self) -> None:
        """Cancel the current hover attempt without stopping observation."""

        hover_request_id = self._hover.current_request_id
        emit_trace(
            self._trace_sink,
            "hover_invalidation",
            hover_request_id=hover_request_id,
        )
        self._hover.invalidate()
        self._invalidate_active_hover()

    def shutdown(self) -> None:
        """Stop observation, suppress queued work, and stop the shared worker."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._running = False
            self._readiness_generation += 1
            self._readiness_waiting = False
            self._startup_point = None

        self._mouse.stop()
        hover_request_id = self._hover.current_request_id
        self._hover.shutdown()
        emit_trace(
            self._trace_sink,
            "hover_cancellation",
            hover_request_id=hover_request_id,
        )
        self._invalidate_active_hover()
        self._controller.stop(wait=False)

    def _on_position(self, point: Point) -> None:
        with self._lock:
            if self._closed or not self._running:
                return
        self._notify_invalidation()
        with self._lock:
            if not self._controller.worker_ready:
                self._startup_point = point
                emit_trace(
                    self._trace_sink,
                    "hover_mouse_opportunity",
                    hover_request_id=None,
                    worker_ready=False,
                )
                return

        # A movement supersedes a submitted hover request. Manual requests
        # remain current when no hover request has actually been submitted.
        previous_hover_id = self._hover.current_request_id
        self._invalidate_active_hover()
        if previous_hover_id is not None:
            emit_trace(
                self._trace_sink,
                "hover_invalidation",
                hover_request_id=previous_hover_id,
            )
        self._hover.on_position(point)
        emit_trace(
            self._trace_sink,
            "hover_mouse_opportunity",
            hover_request_id=self._hover.current_request_id,
        )

    def _notify_invalidation(self) -> None:
        callback = self._on_invalidate
        if callback is None:
            return
        try:
            callback()
        except BaseException as error:
            self._report_error("popup clear", error)

    def _arm_observation_when_ready(self) -> None:
        """Enable dwell/capture only after background provider initialization."""

        with self._lock:
            if self._closed or not self._running:
                return
            self._readiness_generation += 1
            generation = self._readiness_generation
            if self._controller.worker_ready:
                ready_now = True
            elif self._readiness_waiting:
                return
            else:
                ready_now = False
                self._readiness_waiting = True

        if ready_now:
            self._finish_readiness(generation, True)
            return

        emit_trace(self._trace_sink, "hover_observation_waiting_for_worker")

        def wait_for_worker() -> None:
            ready = self._controller.wait_until_ready()
            try:
                self._dispatcher(
                    lambda: self._finish_readiness(generation, ready)
                )
            except BaseException as error:
                self._fail(error)

        Thread(
            target=wait_for_worker,
            name="hanly-hover-readiness",
            daemon=True,
        ).start()

    def _finish_readiness(self, generation: int, ready: bool) -> None:
        with self._lock:
            if generation != self._readiness_generation:
                return
            self._readiness_waiting = False
            if self._closed or not self._running:
                return
            startup_point = self._startup_point
            self._startup_point = None

        if not ready:
            self._fail(RuntimeError("lookup worker initialization failed"))
            return

        try:
            self._hover.start()
            if startup_point is not None:
                self._hover.on_position(startup_point)
        except BaseException as error:
            self._fail(error)
            return
        emit_trace(self._trace_sink, "hover_observation_started")

    def _on_stable(self, request: HoverRequest) -> None:
        with self._lock:
            if self._closed or not self._running:
                return
        if not self._hover.is_current(request):
            return

        emit_trace(
            self._trace_sink,
            "hover_stable_fire",
            hover_request_id=request.request_id,
        )

        capture_started_ns = perf_counter_ns() if self._trace_sink is not None else 0
        emit_trace(
            self._trace_sink,
            "hover_capture_attempted",
            hover_request_id=request.request_id,
        )
        try:
            capture = self._capture_service.capture_at_cursor(request.point)
            if not isinstance(capture, CaptureResult):
                raise TypeError("capture service returned an invalid CaptureResult")
        except Exception as error:
            emit_trace(
                self._trace_sink,
                "hover_capture_error",
                hover_request_id=request.request_id,
                duration_ns=(
                    perf_counter_ns() - capture_started_ns
                    if self._trace_sink is not None
                    else 0
                ),
                error_type=type(error).__name__,
            )
            self._report_error("hover capture", error)
            return

        emit_trace(
            self._trace_sink,
            "hover_capture_completed",
            hover_request_id=request.request_id,
            duration_ns=(
                perf_counter_ns() - capture_started_ns
                if self._trace_sink is not None
                else 0
            ),
            roi_width=capture.image.width,
            roi_height=capture.image.height,
            region_left=capture.region.left,
            region_top=capture.region.top,
            target_x=capture.target.x,
            target_y=capture.target.y,
        )

        if not self._hover.is_current(request):
            emit_trace(
                self._trace_sink,
                "hover_stale_after_capture",
                hover_request_id=request.request_id,
            )
            return

        try:
            lookup_request = self._controller.submit(
                capture.image,
                capture.target,
                hover_request_id=request.request_id,
            )
        except Exception as error:
            emit_trace(
                self._trace_sink,
                "hover_submission_error",
                hover_request_id=request.request_id,
                error_type=type(error).__name__,
            )
            # A controller that can no longer accept work will never succeed
            # again in this process, so hover stops instead of continuing to
            # capture the screen for results that cannot arrive.
            if not self._controller.accepting:
                self._fail(error)
            else:
                self._report_error("hover submission", error)
            return

        with self._lock:
            if self._closed or not self._running or not self._hover.is_current(request):
                stale = True
            else:
                self._active_hover_request_id = lookup_request.request_id
                self._active_hover_id = request.request_id
                stale = False
        if stale:
            emit_trace(
                self._trace_sink,
                "hover_stale_after_submission",
                hover_request_id=request.request_id,
                lookup_request_id=lookup_request.request_id,
            )
            self._controller.invalidate()
        else:
            emit_trace(
                self._trace_sink,
                "hover_submission",
                hover_request_id=request.request_id,
                lookup_request_id=lookup_request.request_id,
            )

    def _fail(self, error: BaseException) -> None:
        """Disable hover for the rest of the process after a fatal failure."""

        with self._lock:
            if self._failed:
                return
            self._failed = True
            self._running = False
            self._readiness_generation += 1
            self._readiness_waiting = False
            self._startup_point = None

        self._mouse.stop()
        self._hover.pause()
        self._invalidate_active_hover()
        self._report_error("automatic hover disabled", error)

    def _invalidate_active_hover(self) -> None:
        with self._lock:
            request_id = self._active_hover_request_id
            hover_id = self._active_hover_id
            self._active_hover_request_id = None
            self._active_hover_id = None
        if request_id is None:
            return
        emit_trace(
            self._trace_sink,
            "hover_cancellation",
            lookup_request_id=request_id,
            hover_request_id=hover_id,
        )
        if self._controller.is_current(request_id):
            self._controller.invalidate()

    def _report_error(self, stage: str, error: BaseException) -> None:
        if self._on_error is None:
            return
        try:
            self._on_error(stage, error)
        except Exception:
            # Error reporting must not terminate the mouse/stability callback.
            pass


__all__ = [
    "CaptureSource",
    "HoverDispatcher",
    "HoverErrorHandler",
    "HoverLookupRuntime",
]
