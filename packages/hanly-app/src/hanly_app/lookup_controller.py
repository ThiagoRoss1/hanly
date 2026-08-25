"""Desktop-side lookup request currency and result handoff.

The engine owns the lookup algorithm. This module owns the small amount of
runtime state needed to submit an image to a worker and decide whether the
result is still relevant when it comes back.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from hanly import HanlyError, LookupResult, LookupStatus, Point, ROIImage
from hanly.errors import LookupCancelled

from .job_executor import JobExecutor
from .runtime_trace import RuntimeTraceSink, emit_trace


@dataclass(frozen=True)
class LookupRequest:
    """One immutable, numbered lookup input.

    ``request_id`` is allocated by :class:`LookupController`. Keeping the
    image and target in the same value means the executor callback can check
    currency against the exact request that produced a result.
    """

    request_id: int
    image: ROIImage
    target: Point
    hover_request_id: int | None = None
    _cancelled: threading.Event = field(
        default_factory=threading.Event,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if isinstance(self.request_id, bool) or not isinstance(self.request_id, int):
            raise TypeError("request_id must be an integer")
        if self.request_id <= 0:
            raise ValueError("request_id must be positive")
        if not isinstance(self.image, ROIImage):
            raise TypeError("image must be an ROIImage")
        if not isinstance(self.target, Point):
            raise TypeError("target must be a Point")
        if self.hover_request_id is not None and (
            isinstance(self.hover_request_id, bool)
            or not isinstance(self.hover_request_id, int)
            or self.hover_request_id <= 0
        ):
            raise TypeError("hover_request_id must be a positive integer or None")

    def cancel(self) -> None:
        """Mark this request obsolete without attempting provider interruption."""

        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Return whether the request was superseded or invalidated."""

        return self._cancelled.is_set()


ResultHandler = Callable[[LookupResult], None]

#: Must schedule the callback and return without waiting for it to run.
#: Blocking UI dispatch can deadlock executor shutdown.
ResultDispatcher = Callable[[Callable[[], None]], None]


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


class LookupController:
    """Submit latest-wins lookup work and hand off only current results.

    The controller owns the executor lifecycle while composition supplies the
    worker factory. Production composition should use the provider-factory
    worker from :mod:`hanly_app.composition`, keeping provider construction on
    the executor thread.
    """

    def __init__(
        self,
        worker_factory: Callable[[], Any],
        on_result: ResultHandler | None = None,
        *,
        on_error: Callable[[LookupRequest, BaseException], None] | None = None,
        result_dispatcher: ResultDispatcher | None = None,
        thread_name: str | None = None,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> None:
        if not callable(worker_factory):
            raise TypeError("worker_factory must be callable")
        if on_result is not None and not callable(on_result):
            raise TypeError("on_result must be callable")
        if result_dispatcher is not None and not callable(result_dispatcher):
            raise TypeError("result_dispatcher must be callable")

        self._executor = JobExecutor(
            worker_factory=worker_factory,
            on_result=self._on_executor_result,
            on_error=self._on_executor_error,
            thread_name=thread_name,
            trace_sink=trace_sink,
        )
        self._on_result = on_result
        self._on_error = on_error
        self._result_dispatcher = result_dispatcher or _inline_dispatch
        self._lock = threading.RLock()
        self._next_request_id = 1
        self._current_request_id: int | None = None
        self._current_request: LookupRequest | None = None
        self._started = False
        self._stopped = False
        self._trace_sink = trace_sink

    @property
    def accepting(self) -> bool:
        """Whether the executor can still accept submissions.

        This turns false permanently once the executor's worker cannot be
        constructed, which is the state a caller needs to stop offering work.
        """

        return self._executor.running

    @property
    def worker_ready(self) -> bool:
        """Whether resident providers are constructed and prewarmed."""

        return self._executor.worker_ready

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Wait for resident provider readiness from a non-UI thread."""

        return self._executor.wait_until_ready(timeout)

    @property
    def current_request_id(self) -> int | None:
        """Return the current request number, or ``None`` after invalidation."""

        with self._lock:
            return self._current_request_id

    def start(self) -> None:
        """Start the executor once."""

        with self._lock:
            if self._started:
                return
            if self._stopped:
                raise RuntimeError("lookup controller has been stopped")
            self._started = True
        try:
            self._executor.start()
        except Exception:
            with self._lock:
                self._started = False
            raise

    def submit(
        self,
        image: ROIImage,
        target: Point,
        *,
        hover_request_id: int | None = None,
    ) -> LookupRequest:
        """Create and submit a current lookup request.

        The request becomes current before it is handed to the executor.
        A result from an earlier request is therefore stale even if cancellation
        cannot remove its running job.
        """

        request = self._new_request(image, target, hover_request_id=hover_request_id)
        try:
            self._executor.submit(request)
        except Exception as error:
            # A failed submission is not a current request. Clear it only if
            # no later request has already superseded it.
            with self._lock:
                if self._current_request_id == request.request_id:
                    self._current_request_id = None
                    self._current_request = None
            request.cancel()
            emit_trace(
                self._trace_sink,
                "lookup_submit_error",
                lookup_request_id=request.request_id,
                hover_request_id=request.hover_request_id,
                error_type=type(error).__name__,
            )
            raise
        emit_trace(
            self._trace_sink,
            "lookup_submit",
            lookup_request_id=request.request_id,
            hover_request_id=request.hover_request_id,
        )
        emit_trace(
            self._trace_sink,
            "lookup_current",
            lookup_request_id=request.request_id,
            hover_request_id=request.hover_request_id,
        )
        return request

    def invalidate(self) -> None:
        """Invalidate the current request without submitting replacement work."""

        with self._lock:
            request_id = self._current_request_id
            request = self._current_request
            self._current_request_id = None
            self._current_request = None
        if request is not None:
            request.cancel()
        emit_trace(
            self._trace_sink,
            "lookup_invalidate",
            lookup_request_id=request_id,
        )

    def is_current(self, request: LookupRequest | int) -> bool:
        """Return whether ``request`` is the latest non-invalidated request."""

        request_id = request.request_id if isinstance(request, LookupRequest) else request
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            return False
        with self._lock:
            return self._current_request_id == request_id

    def stop(
        self,
        *,
        wait: bool = True,
        cancel_pending: bool = True,
    ) -> None:
        """Invalidate requests and stop the executor.

        With ``wait=True`` this joins the executor thread, so it must not be
        called from a context that a blocking ``result_dispatcher`` marshals
        into; see :data:`ResultDispatcher`.
        """

        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            request = self._current_request
            self._current_request_id = None
            self._current_request = None
        if request is not None:
            request.cancel()
        self._executor.shutdown(wait=wait, cancel_pending=cancel_pending)

    def join(self, timeout: float | None = None) -> bool:
        """Wait for a requested stop to release worker-owned providers.

        ``stop(wait=False)`` may be called from a thread that must not block,
        such as a UI thread; this completes that shutdown from a thread that
        may.
        """

        return self._executor.join(timeout)

    shutdown = stop
    close = stop

    def _new_request(
        self,
        image: ROIImage,
        target: Point,
        *,
        hover_request_id: int | None,
    ) -> LookupRequest:
        if not isinstance(image, ROIImage):
            raise TypeError("image must be an ROIImage")
        if not isinstance(target, Point):
            raise TypeError("target must be a Point")
        with self._lock:
            if self._stopped:
                raise RuntimeError("lookup controller has been stopped")
            previous = self._current_request
            if previous is not None:
                previous.cancel()
            request = LookupRequest(
                self._next_request_id,
                image,
                target,
                hover_request_id=hover_request_id,
            )
            self._next_request_id += 1
            self._current_request_id = request.request_id
            self._current_request = request
            return request

    def _on_executor_result(self, request: object, result: object) -> None:
        """Validate currency immediately before handing a result to the sink."""

        if not isinstance(request, LookupRequest):
            return
        if request.is_cancelled():
            emit_trace(
                self._trace_sink,
                "lookup_cancelled_early",
                lookup_request_id=request.request_id,
                hover_request_id=request.hover_request_id,
                stage="before_dispatch",
            )
            return
        if not isinstance(result, LookupResult):
            result = _error_result(
                "lookup worker returned an invalid result",
                TypeError("worker result must be a LookupResult"),
            )
        emit_trace(
            self._trace_sink,
            "lookup_dispatch_queued",
            lookup_request_id=request.request_id,
            hover_request_id=request.hover_request_id,
        )
        self._result_dispatcher(
            lambda: self._deliver_if_current(
                request.request_id,
                cast(LookupResult, result),
                request.hover_request_id,
            )
        )

    def _deliver_if_current(
        self,
        request_id: int,
        result: LookupResult,
        hover_request_id: int | None = None,
    ) -> None:
        """Validate currency in the presentation dispatch context."""

        # The dispatcher may marshal this closure to a UI thread. The final
        # currency check therefore happens after marshalling, immediately
        # before the application result callback rather than on the worker.
        with self._lock:
            if self._current_request_id != request_id:
                emit_trace(
                    self._trace_sink,
                    "lookup_stale_suppressed",
                    lookup_request_id=request_id,
                    hover_request_id=hover_request_id,
                )
                return
            if self._on_result is not None:
                self._on_result(result)
        emit_trace(
            self._trace_sink,
            "lookup_current_delivered",
            lookup_request_id=request_id,
            hover_request_id=hover_request_id,
        )

    def _on_executor_error(self, request: object, exception: BaseException) -> None:
        """Normalize worker failures, suppressing failures for stale work."""

        if isinstance(exception, LookupCancelled):
            emit_trace(
                self._trace_sink,
                "lookup_cancelled_early",
                lookup_request_id=(
                    request.request_id if isinstance(request, LookupRequest) else None
                ),
                hover_request_id=(
                    request.hover_request_id if isinstance(request, LookupRequest) else None
                ),
            )
            return

        with self._lock:
            if isinstance(request, LookupRequest):
                request_id = request.request_id
            else:
                # A worker-factory failure can happen before an executor has
                # an item to associate with it. Associate it with the current
                # item only when one still exists; otherwise there is nothing
                # safe to present. A concrete executor should pass the request
                # whenever it can.
                current_request_id = self._current_request_id
                if current_request_id is None:
                    return
                request_id = current_request_id
        result = _error_result("lookup worker", exception)
        hover_request_id = (
            request.hover_request_id if isinstance(request, LookupRequest) else None
        )
        emit_trace(
            self._trace_sink,
            "lookup_error",
            lookup_request_id=request_id,
            hover_request_id=hover_request_id,
            error_type=type(exception).__name__,
        )

        def deliver_error() -> None:
            with self._lock:
                if self._current_request_id != request_id:
                    emit_trace(
                        self._trace_sink,
                        "lookup_stale_suppressed",
                        lookup_request_id=request_id,
                        hover_request_id=hover_request_id,
                    )
                    return
                if self._on_result is not None:
                    self._on_result(result)
                if self._on_error is not None and isinstance(request, LookupRequest):
                    self._on_error(request, exception)

        emit_trace(
            self._trace_sink,
            "lookup_dispatch_queued",
            lookup_request_id=request_id,
            hover_request_id=hover_request_id,
        )
        self._result_dispatcher(deliver_error)


def _error_result(stage: str, exception: BaseException) -> LookupResult:
    message = f"{stage} failed: {exception}"
    error = exception if isinstance(exception, HanlyError) else HanlyError(message)
    return LookupResult(
        status=LookupStatus.ERROR,
        diagnostics=(message,),
        error=error,
    )


__all__ = ["LookupController", "LookupRequest", "ResultDispatcher", "ResultHandler"]
