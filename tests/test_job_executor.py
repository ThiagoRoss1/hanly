from __future__ import annotations

import threading
from threading import Event

import pytest
from hanly_app.job_executor import JobExecutor


class RecordingWorker:
    def __init__(
        self,
        calls: list[tuple[str, int]],
        close_calls: list[int],
        first_started: Event | None = None,
        release_first: Event | None = None,
    ) -> None:
        self._calls = calls
        self._close_calls = close_calls
        self._first_started = first_started
        self._release_first = release_first

    def __call__(self, item: str) -> str:
        self._calls.append((item, threading.get_ident()))
        if item == "first" and self._first_started is not None:
            self._first_started.set()
            assert self._release_first is not None
            assert self._release_first.wait(timeout=2)
        return item.upper()

    def close(self) -> None:
        self._close_calls.append(threading.get_ident())


def test_factory_work_and_close_run_on_one_background_thread() -> None:
    caller_thread = threading.get_ident()
    factory_threads: list[int] = []
    factory_thread_names: list[str] = []
    calls: list[tuple[str, int]] = []
    close_calls: list[int] = []
    results: list[tuple[str, str, int]] = []
    result_received = Event()

    def factory() -> RecordingWorker:
        factory_threads.append(threading.get_ident())
        factory_thread_names.append(threading.current_thread().name)
        return RecordingWorker(calls, close_calls)

    def on_result(item: str, result: str) -> None:
        results.append((item, result, threading.get_ident()))
        result_received.set()

    executor = JobExecutor(factory, on_result, thread_name="hanly-test-worker")
    executor.start()
    executor.submit("work")

    assert result_received.wait(timeout=2)
    executor.shutdown()

    assert len(factory_threads) == 1
    assert len(calls) == 1
    assert len(close_calls) == 1
    worker_thread = factory_threads[0]
    assert worker_thread != caller_thread
    assert factory_thread_names == ["hanly-test-worker"]
    assert calls[0][1] == worker_thread
    assert results == [("work", "WORK", worker_thread)]
    assert close_calls == [worker_thread]


def test_new_submission_replaces_the_single_pending_item() -> None:
    first_started = Event()
    release_first = Event()
    calls: list[tuple[str, int]] = []
    close_calls: list[int] = []
    results: list[str] = []
    result_received = Event()

    def factory() -> RecordingWorker:
        return RecordingWorker(calls, close_calls, first_started, release_first)

    def on_result(_item: str, result: str) -> None:
        results.append(result)
        if len(results) == 2:
            result_received.set()

    executor = JobExecutor(factory, on_result)
    executor.start()
    executor.submit("first")
    assert first_started.wait(timeout=2)

    executor.submit("superseded")
    executor.submit("latest")
    assert executor.pending is True
    release_first.set()

    assert result_received.wait(timeout=2)
    executor.shutdown()

    assert [item for item, _thread in calls] == ["first", "latest"]
    assert results == ["FIRST", "LATEST"]
    assert executor.pending is False


def test_shutdown_can_cancel_pending_work_but_finishes_running_work() -> None:
    first_started = Event()
    release_first = Event()
    close_calls: list[int] = []
    results: list[str] = []

    executor = JobExecutor(
        lambda: RecordingWorker(
            [], close_calls, first_started=first_started, release_first=release_first
        ),
        lambda _item, result: results.append(result),
    )
    executor.start()
    executor.submit("first")
    assert first_started.wait(timeout=2)
    executor.submit("pending")

    shutdown_done = Event()

    def shutdown() -> None:
        executor.shutdown(wait=True, cancel_pending=True)
        shutdown_done.set()

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    assert executor.stopping is True
    release_first.set()
    assert shutdown_done.wait(timeout=2)
    shutdown_thread.join(timeout=2)

    assert results == ["FIRST"]
    assert len(close_calls) == 1
    assert executor.stopped is True


def test_shutdown_can_drain_the_one_pending_item_when_requested() -> None:
    first_started = Event()
    release_first = Event()
    calls: list[tuple[str, int]] = []
    close_calls: list[int] = []
    results: list[str] = []

    executor = JobExecutor(
        lambda: RecordingWorker(
            calls, close_calls, first_started=first_started, release_first=release_first
        ),
        lambda _item, result: results.append(result),
    )
    executor.start()
    executor.submit("first")
    assert first_started.wait(timeout=2)
    executor.submit("pending")

    shutdown_thread = threading.Thread(
        target=executor.shutdown, kwargs={"wait": True, "cancel_pending": False}
    )
    shutdown_thread.start()
    assert executor.stopping is True
    release_first.set()
    shutdown_thread.join(timeout=2)

    assert not shutdown_thread.is_alive()
    assert [item for item, _thread in calls] == ["first", "pending"]
    assert results == ["FIRST", "PENDING"]
    assert len(close_calls) == 1


def test_item_errors_are_reported_and_do_not_stop_the_worker() -> None:
    errors: list[tuple[str | None, Exception, int]] = []
    results: list[str] = []
    error_received = Event()
    result_received = Event()

    class FailingWorker:
        def __call__(self, item: str) -> str:
            if item == "bad":
                raise ValueError("bad item")
            return item.upper()

        def close(self) -> None:
            pass

    def on_error(item: str | None, error: Exception) -> None:
        errors.append((item, error, threading.get_ident()))
        error_received.set()

    def on_result(_item: str, result: str) -> None:
        results.append(result)
        result_received.set()

    executor: JobExecutor[str, str] = JobExecutor(FailingWorker, on_result, on_error)
    executor.start()
    executor.submit("bad")
    assert error_received.wait(timeout=2)
    executor.submit("good")

    assert result_received.wait(timeout=2)
    executor.shutdown()

    assert len(errors) == 1
    assert errors[0][0] == "bad"
    assert str(errors[0][1]) == "bad item"
    assert errors[0][2] == executor.thread_ident
    assert results == ["GOOD"]


def test_factory_error_reports_no_item_and_leaves_executor_terminal() -> None:
    errors: list[tuple[str | None, Exception, int]] = []
    factory_thread = Event()

    def factory() -> RecordingWorker:
        factory_thread.set()
        raise RuntimeError("factory failed")

    def on_error(item: str | None, error: Exception) -> None:
        errors.append((item, error, threading.get_ident()))

    executor: JobExecutor[str, str] = JobExecutor(factory, lambda _item, _result: None, on_error)
    executor.start()

    assert factory_thread.wait(timeout=2)
    executor.shutdown()

    assert errors[0][0] is None
    assert str(errors[0][1]) == "factory failed"
    with pytest.raises(RuntimeError):
        executor.submit("after failure")
    assert executor.failed is True


def test_submit_requires_start_and_executor_cannot_restart() -> None:
    executor = JobExecutor(lambda: RecordingWorker([], []), lambda _item, _result: None)

    with pytest.raises(RuntimeError):
        executor.submit("before start")

    executor.shutdown()
    assert executor.stopped is True
    with pytest.raises(RuntimeError):
        executor.start()
