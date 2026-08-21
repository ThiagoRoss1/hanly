"""Bounded, latest-wins execution for desktop lookup work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, Literal, Protocol, TypeVar, cast

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
    ) -> None:
        self._worker_factory = worker_factory
        self._on_result = on_result
        self._on_error = on_error
        self._thread_name = thread_name

        self._condition = threading.Condition()
        self._state: ExecutorState = "new"
        self._stop_requested = False
        self._pending: object = _NO_ITEM
        self._thread: threading.Thread | None = None
        self._thread_ident: int | None = None
        self._worker: Worker[ItemT, ResultT] | None = None

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
                raise

    def submit(self, item: ItemT) -> None:
        """Submit an item, replacing any item already waiting to run."""

        with self._condition:
            if self._state != "running":
                raise RuntimeError("JobExecutor is not running")
            self._pending = item
            self._condition.notify()

    def shutdown(self, wait: bool = True, cancel_pending: bool = True) -> None:
        """Request shutdown and optionally wait for the worker thread.

        The currently running item is always allowed to finish. With
        ``cancel_pending=True`` (the default), a pending item is discarded;
        with ``False``, that one item drains before ``Worker.close`` runs.
        """

        with self._condition:
            if self._state == "new":
                self._state = "stopped"
                self._stop_requested = True
                return

            thread = self._thread
            if self._state == "running":
                self._state = "stopping"
                self._stop_requested = True
                if cancel_pending:
                    self._pending = _NO_ITEM
                self._condition.notify_all()

        if wait and thread is not None and thread is not threading.current_thread():
            thread.join()

    def _run(self) -> None:
        with self._condition:
            self._thread_ident = threading.get_ident()

        worker: Worker[ItemT, ResultT] | None = None
        try:
            try:
                worker = self._worker_factory()
            except Exception as error:
                with self._condition:
                    self._state = "failed"
                    self._stop_requested = True
                    self._pending = _NO_ITEM
                    self._condition.notify_all()
                self._report_error(None, error)
                return

            with self._condition:
                self._worker = worker

            while True:
                with self._condition:
                    while self._pending is _NO_ITEM and not self._stop_requested:
                        self._condition.wait()

                    if self._pending is _NO_ITEM:
                        break

                    item = cast(ItemT, self._pending)
                    self._pending = _NO_ITEM

                try:
                    result = worker(item)
                except Exception as error:
                    self._report_error(item, error)
                else:
                    self._report_result(item, result)
        finally:
            if worker is not None:
                try:
                    worker.close()
                except Exception as error:
                    self._report_error(None, error)

            with self._condition:
                self._worker = None
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
