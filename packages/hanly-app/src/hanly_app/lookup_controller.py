"""Desktop-side lookup request currency and result handoff.

The engine owns the lookup algorithm. This module owns the small amount of
runtime state needed to submit an image to a worker and decide whether the
result is still relevant when it comes back.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from hanly import HanlyError, LookupResult, LookupStatus, Point, ROIImage

from .job_executor import JobExecutor


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

    def __post_init__(self) -> None:
        if isinstance(self.request_id, bool) or not isinstance(self.request_id, int):
            raise TypeError("request_id must be an integer")
        if self.request_id <= 0:
            raise ValueError("request_id must be positive")
        if not isinstance(self.image, ROIImage):
            raise TypeError("image must be an ROIImage")
        if not isinstance(self.target, Point):
            raise TypeError("target must be a Point")


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
        )
        self._on_result = on_result
        self._on_error = on_error
        self._result_dispatcher = result_dispatcher or _inline_dispatch
        self._lock = threading.RLock()
        self._next_request_id = 1
        self._current_request_id: int | None = None
        self._started = False
        self._stopped = False

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

    def submit(self, image: ROIImage, target: Point) -> LookupRequest:
        """Create and submit a current lookup request.

        The request becomes current before it is handed to the executor.
        A result from an earlier request is therefore stale even if cancellation
        cannot remove its running job.
        """

        request = self._new_request(image, target)
        try:
            self._executor.submit(request)
        except Exception:
            # A failed submission is not a current request. Clear it only if
            # no later request has already superseded it.
            with self._lock:
                if self._current_request_id == request.request_id:
                    self._current_request_id = None
            raise
        return request

    # Explicit alias reads naturally at call sites that distinguish lookup
    # submission from generic executor submission.
    submit_lookup = submit

    def invalidate(self) -> None:
        """Invalidate the current request without submitting replacement work."""

        with self._lock:
            self._current_request_id = None

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
            self._current_request_id = None
        self._executor.shutdown(wait=wait, cancel_pending=cancel_pending)

    shutdown = stop
    close = stop

    def _new_request(self, image: ROIImage, target: Point) -> LookupRequest:
        if not isinstance(image, ROIImage):
            raise TypeError("image must be an ROIImage")
        if not isinstance(target, Point):
            raise TypeError("target must be a Point")
        with self._lock:
            if self._stopped:
                raise RuntimeError("lookup controller has been stopped")
            request = LookupRequest(self._next_request_id, image, target)
            self._next_request_id += 1
            self._current_request_id = request.request_id
            return request

    def _on_executor_result(self, request: object, result: object) -> None:
        """Validate currency immediately before handing a result to the sink."""

        if not isinstance(request, LookupRequest):
            return
        if not isinstance(result, LookupResult):
            result = _error_result(
                "lookup worker returned an invalid result",
                TypeError("worker result must be a LookupResult"),
            )
        self._result_dispatcher(
            lambda: self._deliver_if_current(request.request_id, cast(LookupResult, result))
        )

    def _deliver_if_current(self, request_id: int, result: LookupResult) -> None:
        """Validate currency in the presentation dispatch context."""

        # The dispatcher may marshal this closure to a UI thread. The final
        # currency check therefore happens after marshalling, immediately
        # before the application result callback rather than on the worker.
        with self._lock:
            if self._current_request_id != request_id:
                return
            if self._on_result is not None:
                self._on_result(result)

    def _on_executor_error(self, request: object, exception: BaseException) -> None:
        """Normalize worker failures, suppressing failures for stale work."""

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

        def deliver_error() -> None:
            with self._lock:
                if self._current_request_id != request_id:
                    return
                if self._on_result is not None:
                    self._on_result(result)
                if self._on_error is not None and isinstance(request, LookupRequest):
                    self._on_error(request, exception)

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
