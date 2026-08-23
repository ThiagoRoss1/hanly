"""UI-side coordination for the UI-independent resource update service.

``UpdateService`` deliberately exposes synchronous, client-independent operations.
This module is the small application seam that lets a Control Center request those
operations without running network or validation work on the bridge caller's
thread.  It stores only JSON-compatible snapshots; the UI never receives a
provider, database, or update-service implementation object.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from threading import Lock, Thread
from typing import Any, Protocol

from hanly.resource_manager import ResourceManager

from .update_service import (
    DownloadProgress,
    ProgressCallback,
    UpdateAvailability,
    UpdateResult,
)


class UpdateServicePort(Protocol):
    """The synchronous service operations needed by the app coordinator."""

    def check_for_updates(self) -> tuple[UpdateAvailability, ...]:
        """Return normalized local/remote availability values."""

    def install(
        self, resource_id: str, *, on_progress: ProgressCallback | None = None
    ) -> UpdateResult:
        """Install one resource and return normalized activation details."""


class UpdateCoordinator:
    """Run update operations off the UI thread and expose normalized snapshots."""

    def __init__(
        self,
        update_service: UpdateServicePort,
        *,
        resource_manager: ResourceManager | None = None,
        executor: Executor | None = None,
        before_install: Callable[[str], None] | None = None,
        after_install: Callable[[str], None] | None = None,
    ) -> None:
        if before_install is not None and not callable(before_install):
            raise TypeError("before_install must be callable")
        if after_install is not None and not callable(after_install):
            raise TypeError("after_install must be callable")
        self._service = update_service
        self._resource_manager = resource_manager
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="hanly-update",
        )
        self._owns_executor = executor is None
        self._before_install = before_install
        self._after_install = after_install
        self._lock = Lock()
        self._future: Future[Any] | None = None
        self._state: dict[str, Any] = {
            "available": False,
            "status": "idle",
            "message": "No update check has been run.",
            "resources": [],
            "active_resource_id": None,
            "progress": None,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the latest normalized state for a UI client."""

        with self._lock:
            return _copy_snapshot(self._state)

    def check_for_updates(self) -> dict[str, Any]:
        """Schedule a remote availability check and return its pending state."""

        with self._lock:
            if self._active_locked():
                return _copy_snapshot(self._state)
            self._state = _state(
                status="checking",
                message="Checking for resource updates…",
            )
            self._submit_locked(self._service.check_for_updates, self._finish_check)
            return _copy_snapshot(self._state)

    def install_update(self, resource_id: object | None = None) -> dict[str, Any]:
        """Schedule installation of one advertised update.

        With no id, the first available resource is selected.  This keeps the
        bridge small while still allowing the UI to select a specific resource.
        """

        with self._lock:
            if self._active_locked():
                return _copy_snapshot(self._state)
            selected = self._select_resource_locked(resource_id)
            self._state["status"] = "downloading"
            self._state["message"] = f"Downloading {selected}…"
            self._state["active_resource_id"] = selected
            self._state["progress"] = {
                "resource_id": selected,
                "phase": "downloading",
                "completed": 0,
                "total": None,
                "fraction": None,
            }
            self._submit_locked(
                lambda: self._install(selected),
                self._finish_install,
            )
            return _copy_snapshot(self._state)

    def shutdown(self, *, wait: bool = False) -> None:
        """Release the coordinator-owned worker when the desktop shuts down."""

        if self._owns_executor:
            self._executor.shutdown(wait=wait, cancel_futures=True)

    def _submit_locked(
        self,
        operation: Callable[[], Any],
        callback: Callable[[Future[Any]], None],
    ) -> None:
        future = self._executor.submit(operation)
        self._future = future
        # ``Future.add_done_callback`` invokes immediately when a very fast
        # test double completes before registration. The bridge call holds
        # the coordinator lock while submitting, so always hand the callback
        # to a tiny daemon thread to avoid re-entering that lock synchronously.
        future.add_done_callback(
            lambda completed: Thread(
                target=callback,
                args=(completed,),
                name="hanly-update-result",
                daemon=True,
            ).start()
        )

    def _install(self, resource_id: str) -> UpdateResult:
        prepared = False
        if self._before_install is not None:
            self._before_install(resource_id)
            prepared = True
        try:
            return self._service.install(resource_id, on_progress=self._on_progress)
        finally:
            if prepared and self._after_install is not None:
                self._after_install(resource_id)

    def _active_locked(self) -> bool:
        return self._future is not None and not self._future.done()

    def _select_resource_locked(self, resource_id: object | None) -> str:
        if resource_id is not None and (
            not isinstance(resource_id, str) or not resource_id.strip()
        ):
            raise ValueError("resource_id must be a non-empty string")
        if isinstance(resource_id, str):
            return resource_id
        for resource in self._state["resources"]:
            if resource.get("available"):
                return str(resource["id"])
        raise ValueError("no available resource update to install")

    def _on_progress(self, progress: DownloadProgress) -> None:
        with self._lock:
            self._state["status"] = progress.phase
            self._state["message"] = _progress_message(progress)
            self._state["progress"] = _progress_dict(progress)

    def _finish_check(self, future: Future[tuple[UpdateAvailability, ...]]) -> None:
        try:
            availability = future.result()
        except Exception as error:
            self._finish_error(error)
            return
        with self._lock:
            resources = [_availability_dict(item) for item in availability]
            available = any(item["available"] for item in resources)
            self._state.update(
                status="available" if available else "current",
                available=available,
                message=(
                    "Resource updates are available."
                    if available
                    else "All local resources are current."
                ),
                resources=resources,
                active_resource_id=None,
                progress=None,
            )
            self._future = None

    def _finish_install(self, future: Future[UpdateResult]) -> None:
        try:
            result = future.result()
            if self._resource_manager is not None:
                self._resource_manager.validate()
        except Exception as error:
            self._finish_error(error)
            return
        with self._lock:
            resource_id = self._state["active_resource_id"]
            for item in self._state["resources"]:
                if item.get("id") == resource_id:
                    item["available"] = False
                    item["current_version"] = result.resource.version
            remaining = any(item.get("available") for item in self._state["resources"])
            self._state.update(
                status="success",
                available=remaining,
                message=f"Installed {resource_id}; local resources were revalidated.",
                progress=None,
            )
            self._future = None

    def _finish_error(self, error: Exception) -> None:
        with self._lock:
            self._state.update(
                status="failed",
                message=f"Update failed: {error}",
                progress=None,
            )
            self._future = None


def _state(*, status: str, message: str) -> dict[str, Any]:
    return {
        "available": False,
        "status": status,
        "message": message,
        "resources": [],
        "active_resource_id": None,
        "progress": None,
    }


def _availability_dict(value: UpdateAvailability) -> dict[str, Any]:
    resource = value.resource
    return {
        "id": resource.resource_id,
        "version": resource.version,
        "current_version": value.current_version,
        "available": value.available,
    }


def _progress_dict(progress: DownloadProgress) -> dict[str, Any]:
    return {
        "resource_id": progress.resource_id,
        "phase": progress.phase,
        "completed": progress.completed,
        "total": progress.total,
        "fraction": progress.fraction,
    }


def _progress_message(progress: DownloadProgress) -> str:
    labels = {
        "downloading": "Downloading resource…",
        "validating": "Validating resource…",
        "complete": "Resource update complete.",
    }
    return labels.get(progress.phase, f"Resource update: {progress.phase}.")


def _copy_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["resources"] = [dict(item) for item in value["resources"]]
    progress = value.get("progress")
    result["progress"] = None if progress is None else dict(progress)
    return result


__all__ = ["UpdateCoordinator", "UpdateServicePort"]
