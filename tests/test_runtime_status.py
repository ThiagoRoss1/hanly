"""Runtime readiness is observable, and a startup failure is not a lookup."""

from __future__ import annotations

import pytest
from hanly import LookupResult, PixelFormat, Point, ROIImage
from hanly_app.lookup_controller import LookupController
from hanly_app.runtime_status import (
    RuntimeStatus,
    RuntimeStatusPublisher,
    watch_worker_readiness,
)

_READY_TIMEOUT_SECONDS = 5.0


class _BrokenProviders(RuntimeError):
    """The concrete cause a user must be shown, not a generic 'not ready'."""


def _roi_image() -> ROIImage:
    return ROIImage(width=4, height=4, pixel_format=PixelFormat.RGB_888, data=bytes(4 * 4 * 3))


def _failing_controller(**options: object) -> LookupController:
    def factory() -> object:
        raise _BrokenProviders("kiwipiepy is unavailable")

    return LookupController(factory, **options)  # type: ignore[arg-type]


def test_a_status_snapshot_is_immutable_and_json_ready() -> None:
    status = RuntimeStatus("preparing", "resources", "Checking resources...")

    assert status.to_dict() == {
        "phase": "preparing",
        "stage": "resources",
        "message": "Checking resources...",
    }
    assert not status.ready and not status.failed
    with pytest.raises(AttributeError):
        status.phase = "ready"  # type: ignore[misc]


def test_observers_receive_the_current_snapshot_and_every_change() -> None:
    publisher = RuntimeStatusPublisher()
    seen: list[RuntimeStatus] = []

    publisher.subscribe(seen.append)
    publisher.update("preparing", "resources", "Checking resources...")
    publisher.update("preparing", "resources", "Checking resources...")
    publisher.update("ready", "lookup providers", "Hanly is ready.")

    assert [status.phase for status in seen] == ["idle", "preparing", "ready"]


def test_a_failing_observer_does_not_stop_the_others() -> None:
    publisher = RuntimeStatusPublisher()
    delivered: list[RuntimeStatus] = []

    def broken(_status: RuntimeStatus) -> None:
        raise RuntimeError("presentation failed")

    publisher.subscribe(broken)
    publisher.subscribe(delivered.append)
    publisher.update("failed", "resources", "no dictionary")

    assert [status.phase for status in delivered] == ["idle", "failed"]


def test_worker_construction_failure_reaches_the_initialization_callback() -> None:
    """The regression: the cause arrives before any hover or hotkey request."""

    reported: list[BaseException] = []
    controller = _failing_controller(on_initialization_error=reported.append)

    controller.start()
    assert controller.wait_until_ready(_READY_TIMEOUT_SECONDS) is False

    assert not controller.worker_ready
    assert not controller.accepting
    assert isinstance(controller.initialization_error, _BrokenProviders)
    assert [type(error) for error in reported] == [_BrokenProviders]
    assert str(reported[0]) == "kiwipiepy is unavailable"


def test_a_startup_failure_does_not_invent_a_dictionary_result() -> None:
    results: list[LookupResult] = []
    controller = _failing_controller(on_result=results.append)

    controller.start()
    controller.wait_until_ready(_READY_TIMEOUT_SECONDS)

    assert results == []


def test_a_failure_after_a_request_still_reports_that_request() -> None:
    """Per-request errors and stale suppression keep working unchanged."""

    results: list[LookupResult] = []
    initialization: list[BaseException] = []
    controller = _failing_controller(
        on_result=results.append,
        on_initialization_error=initialization.append,
    )

    controller.start()
    controller.wait_until_ready(_READY_TIMEOUT_SECONDS)
    with pytest.raises(RuntimeError):
        controller.submit(_roi_image(), Point(1.0, 1.0))

    assert results == []
    assert len(initialization) == 1


def test_readiness_watching_publishes_the_original_cause() -> None:
    publisher = RuntimeStatusPublisher()
    controller = _failing_controller()

    controller.start()
    watch_worker_readiness(controller, publisher).join(_READY_TIMEOUT_SECONDS)

    status = publisher.status
    assert status.failed
    assert status.stage == "lookup providers"
    assert "kiwipiepy is unavailable" in status.message


def test_readiness_watching_publishes_ready_for_a_working_worker() -> None:
    class _Worker:
        def __call__(self, item: object) -> object:
            return item

        def close(self) -> None:
            return None

    publisher = RuntimeStatusPublisher()
    controller = LookupController(_Worker)

    controller.start()
    watch_worker_readiness(controller, publisher).join(_READY_TIMEOUT_SECONDS)

    assert publisher.status.ready
    assert controller.initialization_error is None
    controller.stop()


def test_a_retired_watcher_cannot_report_over_the_current_runtime() -> None:
    """A retry leaves the old worker's watcher waiting; it must stay quiet."""

    publisher = RuntimeStatusPublisher()
    publisher.update("preparing", "resources", "Preparing Hanly's resources...")
    controller = _failing_controller()

    controller.start()
    watch_worker_readiness(controller, publisher, is_current=lambda: False).join(
        _READY_TIMEOUT_SECONDS
    )

    assert publisher.status == RuntimeStatus(
        "preparing", "resources", "Preparing Hanly's resources..."
    )
