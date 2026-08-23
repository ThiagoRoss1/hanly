from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceMetadata
from hanly_app.update_coordinator import UpdateCoordinator
from hanly_app.update_service import (
    DownloadProgress,
    ProgressCallback,
    RemoteResource,
    UpdateAvailability,
    UpdateResult,
)


@dataclass
class _FakeService:
    thread_names: list[str]

    def __init__(self) -> None:
        self.thread_names = []

    def check_for_updates(self) -> tuple[UpdateAvailability, ...]:
        self.thread_names.append(threading.current_thread().name)
        return (
            UpdateAvailability(
                RemoteResource("krdict", "2", url="https://example.test/krdict"),
                current_version="1",
                available=True,
            ),
        )

    def install(
        self, resource_id: str, *, on_progress: ProgressCallback | None = None
    ) -> UpdateResult:
        self.thread_names.append(threading.current_thread().name)
        if on_progress is not None:
            on_progress(DownloadProgress(resource_id, "validating", 1, 1))
        return UpdateResult(
            resource=RemoteResource(resource_id, "2", url="https://example.test/asset"),
            path=Path("."),
            validation=cast(ResourceMetadata, None),
            backup_path=None,
        )


def _recording_manager(validations: list[str]) -> ResourceManager:
    """A real manager whose validate() call is observable."""

    manager = ResourceManager(ResourceManifest(()))
    original = manager.validate

    def validate() -> dict[str, ResourceMetadata]:
        validations.append("validate")
        return original()

    manager.validate = validate  # type: ignore[method-assign]
    return manager


def _wait_for(coordinator: UpdateCoordinator, status: str) -> dict[str, Any]:
    for _ in range(100):
        state = coordinator.snapshot()
        if state["status"] == status:
            return state
        time.sleep(0.01)
    raise AssertionError(f"coordinator did not reach {status!r}: {coordinator.snapshot()!r}")


def test_update_operations_are_backgrounded_and_install_revalidates_resources() -> None:
    service = _FakeService()
    validations: list[str] = []
    manager = _recording_manager(validations)
    coordinator = UpdateCoordinator(service, resource_manager=manager)
    try:
        assert coordinator.check_for_updates()["status"] == "checking"
        state = _wait_for(coordinator, "available")
        assert state["available"] is True
        assert state["resources"] == [
            {
                "id": "krdict",
                "version": "2",
                "current_version": "1",
                "available": True,
            }
        ]

        assert coordinator.install_update()["status"] == "downloading"
        state = _wait_for(coordinator, "success")
        assert state["available"] is False
        assert state["resources"][0]["current_version"] == "2"
        assert validations == ["validate"]
        assert all(name != threading.current_thread().name for name in service.thread_names)
    finally:
        coordinator.shutdown()


def test_update_coordinator_rejects_install_without_an_available_resource() -> None:
    coordinator = UpdateCoordinator(_FakeService())
    try:
        try:
            coordinator.install_update()
        except ValueError as error:
            assert "no available" in str(error)
        else:
            raise AssertionError("expected missing update to be rejected")
    finally:
        coordinator.shutdown()


def test_install_hooks_bracket_activation_on_the_update_worker() -> None:
    service = _FakeService()
    events: list[str] = []
    coordinator = UpdateCoordinator(
        service,
        before_install=lambda resource_id: events.append(f"before:{resource_id}"),
        after_install=lambda resource_id: events.append(f"after:{resource_id}"),
    )
    try:
        coordinator.check_for_updates()
        _wait_for(coordinator, "available")
        coordinator.install_update("krdict")
        _wait_for(coordinator, "success")
    finally:
        coordinator.shutdown(wait=True)

    assert events == ["before:krdict", "after:krdict"]
