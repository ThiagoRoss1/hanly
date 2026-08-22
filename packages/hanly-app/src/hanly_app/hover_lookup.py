"""Automatic hover composition over the existing desktop lookup path.

This module only joins the desktop seams that already own observation,
stability, capture, and lookup execution.  It does not construct providers or
an additional pipeline.  A caller may share the resulting runtime's
``LookupController`` with the manual hotkey path; only hover-owned requests
are invalidated when the cursor moves.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Protocol

from hanly import Point

from .capture import CaptureResult
from .hover_controller import HoverController, HoverRequest, HoverScheduler
from .lookup_controller import LookupController
from .mouse_observer import MouseListenerFactory, MouseObserver


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
    ) -> None:
        if not isinstance(controller, LookupController):
            raise TypeError("controller must be a LookupController")
        if not callable(capture_service.capture_at_cursor):
            raise TypeError("capture_service must provide capture_at_cursor(cursor)")
        if dispatcher is not None and not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("on_error must be callable")

        dispatch = dispatcher or _inline_dispatch
        self._controller = controller
        self._capture_service = capture_service
        self._on_error = on_error
        self._lock = RLock()
        self._running = False
        self._closed = False
        self._failed = False
        self._active_hover_request_id: int | None = None
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
            self._hover.start()
            self._mouse.start()
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

        self._mouse.stop()
        self._hover.pause()
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
            self._hover.resume()
            self._mouse.start()
        except Exception:
            with self._lock:
                self._running = False
            self._mouse.stop()
            self._hover.pause()
            raise

    def invalidate(self) -> None:
        """Cancel the current hover attempt without stopping observation."""

        self._hover.invalidate()
        self._invalidate_active_hover()

    def shutdown(self) -> None:
        """Stop observation, suppress queued work, and stop the shared worker."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._running = False

        self._mouse.stop()
        self._hover.shutdown()
        self._invalidate_active_hover()
        self._controller.stop(wait=False)

    def _on_position(self, point: Point) -> None:
        with self._lock:
            if self._closed or not self._running:
                return

        # A movement supersedes a submitted hover request. Manual requests
        # remain current when no hover request has actually been submitted.
        self._invalidate_active_hover()
        self._hover.on_position(point)

    def _on_stable(self, request: HoverRequest) -> None:
        with self._lock:
            if self._closed or not self._running:
                return
        if not self._hover.is_current(request):
            return

        try:
            capture = self._capture_service.capture_at_cursor(request.point)
            if not isinstance(capture, CaptureResult):
                raise TypeError("capture service returned an invalid CaptureResult")
        except Exception as error:
            self._report_error("hover capture", error)
            return

        if not self._hover.is_current(request):
            return

        try:
            lookup_request = self._controller.submit(capture.image, capture.target)
        except Exception as error:
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
                stale = False
        if stale:
            self._controller.invalidate()

    def _fail(self, error: BaseException) -> None:
        """Disable hover for the rest of the process after a fatal failure."""

        with self._lock:
            if self._failed:
                return
            self._failed = True
            self._running = False

        self._mouse.stop()
        self._hover.pause()
        self._invalidate_active_hover()
        self._report_error("automatic hover disabled", error)

    def _invalidate_active_hover(self) -> None:
        with self._lock:
            request_id = self._active_hover_request_id
            self._active_hover_request_id = None
        if request_id is None:
            return
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
