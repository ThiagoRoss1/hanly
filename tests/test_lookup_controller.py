"""Focused request-currency tests for the desktop lookup controller."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event

from hanly import (
    DictionaryEntry,
    LookupResult,
    LookupStatus,
    PixelFormat,
    Point,
    ROIImage,
)
from hanly_app.lookup_controller import LookupController, LookupRequest

_IMAGE = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x00")
_TARGET = Point(2, 3)
_RESULT = LookupResult(
    status=LookupStatus.SUCCESS,
    entries=(DictionaryEntry(headword="책", definitions=("book",)),),
)


class _BlockingWorker:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def __call__(self, request: LookupRequest) -> LookupResult:
        self.started.set()
        assert self.release.wait(timeout=2)
        return _RESULT

    def close(self) -> None:
        pass


def test_request_is_frozen_and_controller_allocates_monotonic_ids() -> None:
    worker = _BlockingWorker()
    results: list[LookupResult] = []
    controller = LookupController(lambda: worker, results.append)
    controller.start()

    first = controller.submit(_IMAGE, _TARGET)
    assert worker.started.wait(timeout=2)
    second = controller.submit(_IMAGE, _TARGET)
    worker.release.set()
    controller.stop()

    assert first.request_id == 1
    assert second.request_id == 2
    assert first.image is _IMAGE
    assert first.target is _TARGET
    assert controller.is_current(first) is False
    assert controller.is_current(second) is False


def test_running_superseded_result_is_suppressed_even_when_it_cannot_cancel() -> None:
    worker = _BlockingWorker()
    results: list[LookupResult] = []
    controller = LookupController(lambda: worker, results.append)
    controller.start()

    first = controller.submit(_IMAGE, _TARGET)
    assert worker.started.wait(timeout=2)
    controller.invalidate()
    worker.release.set()
    controller.stop()

    assert controller.is_current(first) is False
    assert results == []


def test_worker_exception_becomes_current_error_result() -> None:
    class FailingWorker:
        def __call__(self, _request: LookupRequest) -> LookupResult:
            raise RuntimeError("boom")

        def close(self) -> None:
            pass

    results: list[LookupResult] = []
    received = Event()

    def receive(result: LookupResult) -> None:
        results.append(result)
        received.set()

    controller = LookupController(
        lambda: FailingWorker(),
        receive,
    )
    controller.start()
    controller.submit(_IMAGE, _TARGET)

    assert received.wait(timeout=2)
    controller.stop()
    assert results[0].status is LookupStatus.ERROR
    assert results[0].error is not None
    assert "lookup worker" in str(results[0].error)


def test_current_success_result_is_handed_off() -> None:
    class SuccessfulWorker:
        def __call__(self, _request: LookupRequest) -> LookupResult:
            return _RESULT

        def close(self) -> None:
            pass

    results: list[LookupResult] = []
    received = Event()

    def receive(result: LookupResult) -> None:
        results.append(result)
        received.set()

    controller = LookupController(SuccessfulWorker, receive)
    controller.start()
    request = controller.submit(_IMAGE, _TARGET)

    assert received.wait(timeout=2)
    assert controller.is_current(request) is True
    controller.stop()

    assert results == [_RESULT]
    assert controller.current_request_id is None


def test_final_currency_check_runs_after_result_dispatch() -> None:
    class SuccessfulWorker:
        def __call__(self, _request: LookupRequest) -> LookupResult:
            return _RESULT

        def close(self) -> None:
            pass

    pending_delivery: list[Callable[[], None]] = []
    delivery_queued = Event()
    results: list[LookupResult] = []

    def dispatch(callback: Callable[[], None]) -> None:
        pending_delivery.append(callback)
        delivery_queued.set()

    controller = LookupController(
        SuccessfulWorker,
        results.append,
        result_dispatcher=dispatch,
    )
    controller.start()
    controller.submit(_IMAGE, _TARGET)

    assert delivery_queued.wait(timeout=2)
    controller.invalidate()
    pending_delivery.pop()()
    controller.stop()

    assert results == []


def test_point_value_is_carried_unchanged_by_request() -> None:
    target = Point(12.5, 8.25)
    request = LookupRequest(1, _IMAGE, target)
    assert request.target is target
