"""Bounded, latest-wins execution for desktop lookup work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, Literal, Protocol, TypeVar, cast

from .runtime_trace import RuntimeTraceSink, emit_trace

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")
WorkerItemT = TypeVar("WorkerItemT", contravariant=True)
WorkerResultT = TypeVar("WorkerResultT", covariant=True)
ExecutorState = Literal["new", "running", "stopping", "stopped", "failed"]

_NO_ITEM = object()


class Worker(Protocol[WorkerItemT, WorkerResultT]):
    """A callable unit of work with worker-thread lifecycle cleanup."""

    def __call__(self, item: WorkerItemT) -> WorkerResultT:
        ...

    def close(self) -> None:
        ...


class JobExecutor(Generic[ItemT, ResultT]):
    """Run at most one item and retain at most one latest pending item.

    The worker is constructed lazily by the executor thread. Submissions made
    while an item is running replace the one pending submission, which keeps
    hover-driven work bounded without requiring a cancellation protocol from
    every worker implementation.
    """

    def __init__(
        self,
        worker_factory: Callable[[], Worker[ItemT, ResultT]],
        on_result: Callable[[ItemT, ResultT], None],
        on_error: Callable[[ItemT | None, Exception], None] | None = None,
        thread_name: str | None = None,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> None:
        self._worker_factory = worker_factory
        self._on_result = on_result
        self._on_error = on_error
        self._thread_name = thread_name
        self._trace_sink = trace_sink

        self._condition = threading.Condition()
        self._state: ExecutorState = "new"
        self._stop_requested = False
        self._pending: object = _NO_ITEM
        self._thread: threading.Thread | None = None
        self._thread_ident: int | None = None
        self._worker: Worker[ItemT, ResultT] | None = None
        self._worker_ready = False
        self._ready_event = threading.Event()

    @property
    def state(self) -> ExecutorState:
        """Return the current lifecycle state."""

        with self._condition:
            return self._state

    @property
    def started(self) -> bool:
        """Whether :meth:`start` has been called successfully."""

        with self._condition:
            return self._state != "new"

    @property
    def running(self) -> bool:
        """Whether the executor accepts new submissions."""

        with self._condition:
            return self._state == "running"

    @property
    def stopping(self) -> bool:
        """Whether shutdown has begun but the worker has not exited."""

        with self._condition:
            return self._state == "stopping"

    @property
    def stopped(self) -> bool:
        """Whether the executor has completed shutdown (or never started)."""

        with self._condition:
            return self._state == "stopped"

    @property
    def failed(self) -> bool:
        """Whether worker construction failed."""

        with self._condition:
            return self._state == "failed"

    @property
    def pending(self) -> bool:
        """Whether one item is waiting behind the currently running item."""

        with self._condition:
            return self._pending is not _NO_ITEM

    @property
    def worker_ready(self) -> bool:
        """Whether provider construction and worker prewarming completed."""

        with self._condition:
            return self._worker_ready

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Wait outside the UI thread for worker initialization to finish."""

        if not self._ready_event.wait(timeout):
            return False
        return self.worker_ready

    @property
    def thread_ident(self) -> int | None:
        """The executor thread's identifier, retained after it exits."""

        with self._condition:
            return self._thread_ident

    def start(self) -> None:
        """Start the one executor thread.

        Starting is explicit so an accidental submission cannot construct a
        potentially heavy worker on a caller thread. An executor is
        single-use: after shutdown it cannot be restarted.
        """

        with self._condition:
            if self._state == "running":
                return
            if self._state != "new":
                raise RuntimeError("JobExecutor cannot be started again")

            self._state = "running"
            thread = threading.Thread(
                target=self._run,
                name=self._thread_name,
                daemon=True,
            )
            self._thread = thread
            try:
                thread.start()
            except BaseException:
                self._thread = None
                self._state = "failed"
                self._ready_event.set()
                raise
        emit_trace(self._trace_sink, "executor_started")

    def submit(self, item: ItemT) -> None:
        """Submit an item, replacing any item already waiting to run."""

        with self._condition:
            if self._state != "running":
                raise RuntimeError("JobExecutor is not running")
            replaced = self._pending is not _NO_ITEM
            previous = self._pending if replaced else None
            self._pending = item
            self._condition.notify()
        ids = _item_ids(item)
        emit_trace(
            self._trace_sink,
            "executor_submission_accepted",
            lookup_request_id=ids[0],
            hover_request_id=ids[1],
        )
        if replaced:
            previous_ids = _item_ids(previous)
            emit_trace(
                self._trace_sink,
                "executor_pending_replaced",
                lookup_request_id=ids[0],
                hover_request_id=ids[1],
                replaced_lookup_request_id=previous_ids[0],
                replaced_hover_request_id=previous_ids[1],
            )

    def shutdown(self, wait: bool = True, cancel_pending: bool = True) -> None:
        """Request shutdown and optionally wait for the worker thread.

        The currently running item is always allowed to finish. With
        ``cancel_pending=True`` (the default), a pending item is discarded;
        with ``False``, that one item drains before ``Worker.close`` runs.
        """

        pending_ids: tuple[int | None, int | None] = (None, None)
        with self._condition:
            if self._state == "new":
                self._state = "stopped"
                self._stop_requested = True
                self._ready_event.set()
                emit_trace(self._trace_sink, "executor_shutdown")
                return

            thread = self._thread
            if self._state == "running":
                self._state = "stopping"
                self._stop_requested = True
                if cancel_pending:
                    had_pending = self._pending is not _NO_ITEM
                    pending_ids = _item_ids(self._pending)
                    self._pending = _NO_ITEM
                    if had_pending:
                        emit_trace(
                            self._trace_sink,
                            "executor_pending_cancelled",
                            lookup_request_id=pending_ids[0],
                            hover_request_id=pending_ids[1],
                        )
                else:
                    pending_ids = (None, None)
                self._condition.notify_all()

            if self._state == "stopping":
                emit_trace(
                    self._trace_sink,
                    "executor_shutdown",
                    pending_cancelled=cancel_pending,
                    lookup_request_id=pending_ids[0],
                    hover_request_id=pending_ids[1],
                )

        if wait and thread is not None and thread is not threading.current_thread():
            thread.join()

    def join(self, timeout: float | None = None) -> bool:
        """Wait for an already-requested shutdown to finish its worker.

        Separating the wait from :meth:`shutdown` lets a caller request
        shutdown on a thread that must not block and complete the wait
        elsewhere. Returns whether the worker thread has finished.
        """

        with self._condition:
            thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        with self._condition:
            self._thread_ident = threading.get_ident()

        worker: Worker[ItemT, ResultT] | None = None
        try:
            try:
                emit_trace(self._trace_sink, "executor_worker_construction_started")
                worker = self._worker_factory()
            except Exception as error:
                with self._condition:
                    self._state = "failed"
                    self._stop_requested = True
                    self._pending = _NO_ITEM
                    self._ready_event.set()
                    self._condition.notify_all()
                self._report_error(None, error)
                emit_trace(
                    self._trace_sink,
                    "executor_worker_construction_failed",
                    error_type=type(error).__name__,
                )
                return

            with self._condition:
                self._worker = worker
                self._worker_ready = True
                self._ready_event.set()
            emit_trace(self._trace_sink, "executor_worker_ready")

            while True:
                with self._condition:
                    while self._pending is _NO_ITEM and not self._stop_requested:
                        self._condition.wait()

                    if self._pending is _NO_ITEM:
                        break

                    item = cast(ItemT, self._pending)
                    self._pending = _NO_ITEM

                ids = _item_ids(item)
                started_ns = _trace_clock() if self._trace_sink is not None else 0
                emit_trace(
                    self._trace_sink,
                    "executor_work_started",
                    lookup_request_id=ids[0],
                    hover_request_id=ids[1],
                )

                try:
                    result = worker(item)
                except Exception as error:
                    self._report_error(item, error)
                    emit_trace(
                        self._trace_sink,
                        "executor_work_error",
                        lookup_request_id=ids[0],
                        hover_request_id=ids[1],
                        duration_ns=(
                            _trace_clock() - started_ns
                            if self._trace_sink is not None
                            else 0
                        ),
                        error_type=type(error).__name__,
                    )
                else:
                    self._report_result(item, result)
                    emit_trace(
                        self._trace_sink,
                        "executor_work_completed",
                        lookup_request_id=ids[0],
                        hover_request_id=ids[1],
                        duration_ns=(
                            _trace_clock() - started_ns
                            if self._trace_sink is not None
                            else 0
                        ),
                    )
        finally:
            if worker is not None:
                try:
                    worker.close()
                except Exception as error:
                    self._report_error(None, error)
                    emit_trace(
                        self._trace_sink,
                        "executor_cleanup_error",
                        error_type=type(error).__name__,
                    )
                else:
                    emit_trace(self._trace_sink, "executor_cleanup_completed")

            with self._condition:
                self._worker = None
                self._worker_ready = False
                self._ready_event.set()
                if self._state != "failed":
                    self._state = "stopped"
                self._stop_requested = True
                self._pending = _NO_ITEM
                self._condition.notify_all()

    def _report_result(self, item: ItemT, result: ResultT) -> None:
        try:
            self._on_result(item, result)
        except Exception:
            # Callback failures belong to the client boundary. They must not
            # prevent the executor from draining/shutting down its worker.
            pass

    def _report_error(self, item: ItemT | None, error: Exception) -> None:
        if self._on_error is None:
            return
        try:
            self._on_error(item, error)
        except Exception:
            # Error handlers are callbacks too; never strand the worker thread
            # because an error presenter failed.
            pass


def _trace_clock() -> int:
    """Import the monotonic clock lazily only for the enabled trace path."""

    from time import perf_counter_ns

    return perf_counter_ns()


def _item_ids(item: object) -> tuple[int | None, int | None]:
    """Read only immutable request IDs from a generic executor item."""

    request_id = getattr(item, "request_id", None)
    hover_request_id = getattr(item, "hover_request_id", None)
    return (
        request_id if isinstance(request_id, int) and not isinstance(request_id, bool) else None,
        hover_request_id
        if isinstance(hover_request_id, int) and not isinstance(hover_request_id, bool)
        else None,
    )
