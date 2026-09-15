"""UI-side coordination for the UI-independent resource update service.

``UpdateService`` deliberately exposes synchronous, client-independent operations.
This module is the small application seam that lets a Control Center request those
operations without running network or validation work on the bridge caller's
thread.  It stores only JSON-compatible snapshots; the UI never receives a
provider, database, or update-service implementation object.

The two kinds of update are deliberately distinct in the state this exposes. A
resource is hot-swapped: lookups pause, the artifact is replaced, the runtime is
rebuilt, and Hanly keeps running.  An application build replaces the executable
this process runs from, so it can only be staged here and finished by a
restart.  ``restart_required`` says which of the two just happened, and it
says so only once a build is actually staged and its handoff is ready.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from threading import Event, Lock, Thread
from typing import Any, Protocol

from hanly.resource_manager import ResourceManager

from .app_update import APPLICATION_STEM, ApplicationUpdate
from .update_service import (
    DownloadProgress,
    ProgressCallback,
    UpdateAvailability,
    UpdateResult,
)

#: Stage one application build, reporting progress the way a resource does.
ApplicationInstall = Callable[[ApplicationUpdate, ProgressCallback | None], None]

#: How many activity lines the page can show. Old ones are dropped rather than
#: accumulated: the snapshot crosses a pipe on every poll.
ACTIVITY_LIMIT = 120

#: The floor between two progress snapshots. A download reports every megabyte,
#: which on a fast link is far more often than a person can read.
PROGRESS_INTERVAL_SECONDS = 0.2

#: Resource availability, the application update, its UI snapshot, and why the
#: resource half could not answer - each half reports its own failure.
_CheckOutcome = tuple[
    tuple[UpdateAvailability, ...],
    ApplicationUpdate | None,
    dict[str, Any] | None,
    str | None,
]


class ApplicationInstallPort(Protocol):
    """The two-step application install a differential updater exposes.

    Preparing reaches the network for metadata and reads the installation; it
    fetches no payload. Installing is what the user authorized once they were
    shown the real download size, which is why it is a second call.
    """

    def prepare(
        self,
        version: str,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Any:
        """Return a decided plan, having downloaded nothing but metadata."""

    def install(
        self,
        prepared: Any,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        """Fetch the planned payload and hand the transaction to the helper."""

    def abandon(self) -> None:
        """Drop a prepared or staged update that will not be applied."""


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
        record_install: Callable[[UpdateResult], None] | None = None,
        application_check: Callable[[], ApplicationUpdate] | None = None,
        application_install: ApplicationInstall | None = None,
        application_installer: ApplicationInstallPort | None = None,
        on_restart_required: Callable[[], None] | None = None,
    ) -> None:
        if before_install is not None and not callable(before_install):
            raise TypeError("before_install must be callable")
        if after_install is not None and not callable(after_install):
            raise TypeError("after_install must be callable")
        if record_install is not None and not callable(record_install):
            raise TypeError("record_install must be callable")
        if application_check is not None and not callable(application_check):
            raise TypeError("application_check must be callable")
        if application_install is not None and not callable(application_install):
            raise TypeError("application_install must be callable")
        if on_restart_required is not None and not callable(on_restart_required):
            raise TypeError("on_restart_required must be callable")
        self._service = update_service
        self._resource_manager = resource_manager
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="hanly-update",
        )
        self._owns_executor = executor is None
        self._before_install = before_install
        self._after_install = after_install
        self._record_install = record_install
        self._application_check = application_check
        self._application_install = application_install
        self._application_installer = application_installer
        self._on_restart_required = on_restart_required
        self._application: ApplicationUpdate | None = None
        self._lock = Lock()
        self._future: Future[Any] | None = None
        #: The decided plan an install is waiting to be authorized for, when
        #: preparing it turned up a download the user was not offered.
        self._prepared: Any | None = None
        self._cancel = Event()
        self._activity: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_LIMIT)
        self._last_progress = 0.0
        #: Set once a build has been handed to the swap script. From then on
        #: this process is on its way out and owns no further update work.
        self._handed_off = False
        self._state: dict[str, Any] = {
            "available": False,
            "status": "idle",
            "message": "No update check has been run.",
            "resources": [],
            "active_resource_id": None,
            "progress": None,
            "application": None,
            "restart_required": False,
            "plan": None,
            "awaiting_confirmation": False,
            "cancellable": False,
            "activity": [],
            "outcome": None,
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
                message="Checking for updates…",
                application=self._state.get("application"),
            )
            self._submit_locked(self._collect_updates, self._finish_check)
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

    def install_application_update(self, confirm_full: object = False) -> dict[str, Any]:
        """Start installing a new build, or authorize one that grew.

        ``confirm_full`` is the second click, and only the differential path
        ever asks for it: preparing can discover that the small download this
        installation was offered cannot be used here, and the full archive is a
        different bargain from the one the user agreed to.
        """

        with self._lock:
            if self._active_locked():
                return _copy_snapshot(self._state)
            update = self._application
            if update is None or not update.installable:
                raise ValueError("no installable application update")

            prepared = self._prepared if confirm_full else None
            self._prepared = None
            self._cancel = Event()
            self._begin_application_locked(update)

            if self._application_installer is not None:
                self._submit_locked(
                    lambda: self._install_application(update, prepared),
                    self._finish_application_install,
                )
            elif self._application_install is not None:
                install = self._application_install
                self._submit_locked(
                    lambda: install(update, self._on_progress),
                    self._finish_application_install,
                )
            else:
                raise ValueError("no installable application update")
            return _copy_snapshot(self._state)

    def cancel_update(self) -> dict[str, Any]:
        """Ask the running preparation or download to stop.

        This only ever reaches work that has not changed the installation.
        Once the helper owns the transaction there is nothing here to cancel,
        and the snapshot says so by no longer being cancellable.
        """

        with self._lock:
            if self._state.get("cancellable"):
                self._cancel.set()
                self._state["message"] = "Stopping…"
                return _copy_snapshot(self._state)
            waiting = self._state.get("awaiting_confirmation")
        if not waiting:
            return self.snapshot()

        # Nothing is running to interrupt: what is held is a decided plan and
        # the installation's update lock, and declining releases both.
        installer = self._application_installer
        if installer is not None:
            installer.abandon()
        with self._lock:
            self._prepared = None
            self._note_locked("The update was not installed.")
            self._state.update(
                status="cancelled",
                message="The update was not installed. Nothing was changed.",
                awaiting_confirmation=False,
                plan=None,
                progress=None,
            )
            return _copy_snapshot(self._state)

    def _begin_application_locked(self, update: ApplicationUpdate) -> None:
        self._activity.clear()
        self._state.update(
            status="preparing",
            message=f"Preparing the update to Hanly {update.latest_version}…",
            active_resource_id=APPLICATION_STEM,
            restart_required=False,
            awaiting_confirmation=False,
            cancellable=True,
            outcome=None,
            progress=_progress_dict(DownloadProgress(APPLICATION_STEM, "preparing", 0, None)),
            activity=[],
        )

    def _install_application(self, update: ApplicationUpdate, prepared: Any) -> Any:
        """Prepare, then install unless the download grew without permission."""

        installer = self._application_installer
        assert installer is not None
        version = update.latest_version or ""
        if prepared is None:
            prepared = installer.prepare(
                version, on_progress=self._on_progress, should_cancel=self._cancel.is_set
            )
            if getattr(prepared, "requires_confirmation", False):
                return prepared
        installer.install(
            prepared, on_progress=self._on_progress, should_cancel=self._cancel.is_set
        )
        return None

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
                target=self._deliver,
                args=(callback, completed),
                name="hanly-update-result",
                daemon=True,
            ).start()
        )

    def _deliver(self, callback: Callable[[Future[Any]], None], future: Future[Any]) -> None:
        """Run one result callback, unless it no longer speaks for this state.

        A callback runs on its own thread after its future completed, so an
        older one can arrive at any moment. Only the operation this coordinator
        still holds may report an outcome or release ownership.
        """

        with self._lock:
            stale = future is not self._future
        if not stale:
            callback(future)

    def _install(self, resource_id: str) -> UpdateResult:
        prepared = False
        if self._before_install is not None:
            self._before_install(resource_id)
            prepared = True
        try:
            result = self._service.install(resource_id, on_progress=self._on_progress)
            if self._record_install is not None:
                self._record_install(result)
            return result
        finally:
            if prepared and self._after_install is not None:
                self._after_install(resource_id)

    def _active_locked(self) -> bool:
        """Whether an operation still owns this coordinator.

        Ownership ends when the matching callback finalizes the state, not when
        the future completes: between those two moments a second request would
        otherwise start and have its result overwritten by the older callback.
        """

        return self._handed_off or self._future is not None

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
        """Record one progress report, without rebuilding the page for each.

        A megabyte-by-megabyte download reports far faster than anyone can
        read, and every snapshot crosses a pipe, so a report that only moves
        the counters is dropped unless enough time has passed. A change of
        phase always lands: that is what the page is actually reading.
        """

        now = time.monotonic()
        with self._lock:
            changed = self._state.get("status") != progress.phase
            if changed:
                self._note_locked(_progress_message(progress))
            elif now - self._last_progress < PROGRESS_INTERVAL_SECONDS:
                return
            self._last_progress = now
            self._state["status"] = progress.phase
            self._state["message"] = _progress_message(progress)
            self._state["progress"] = _progress_dict(progress)

    def _note_locked(self, message: str) -> None:
        """Add one line to the bounded activity tail the page can expand."""

        self._activity.append({"at": time.time(), "message": message})
        self._state["activity"] = [dict(item) for item in self._activity]

    def _collect_updates(self) -> _CheckOutcome:
        """Check resources and the application itself in one worker pass.

        Neither half hides the other: they reach the same release channel but
        answer different questions, and a manifest a user cannot fix is no
        reason to stop telling them a new Hanly exists - which may be what
        fixes it. Neither failure is swallowed either: a half that could not
        answer says so, rather than being reported as nothing to install.
        """

        availability, resource_error = self._check_resources()
        if self._application_check is None:
            return availability, None, None, resource_error
        try:
            update = self._application_check()
        except Exception as error:
            return availability, None, _application_check_failure(error), resource_error
        return availability, update, update.to_dict(), resource_error

    def _check_resources(self) -> tuple[tuple[UpdateAvailability, ...], str | None]:
        try:
            return self._service.check_for_updates(), None
        except Exception as error:
            return (), str(error) or type(error).__name__

    def _finish_check(self, future: Future[_CheckOutcome]) -> None:
        try:
            availability, update, application, resource_error = future.result()
        except Exception as error:
            self._finish_error(error)
            return
        with self._lock:
            self._application = update
            resources = [_availability_dict(item) for item in availability]
            resource_available = any(item["available"] for item in resources)
            application_available = bool(application and application.get("available"))
            available = resource_available or application_available
            self._state.update(
                status=_check_status(available, resource_error),
                available=available,
                message=_check_message(
                    resource_available, application_available, resource_error
                ),
                resources=resources,
                active_resource_id=None,
                progress=None,
                application=application,
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
                message=(
                    f"Installed {resource_id}; local resources were revalidated. "
                    "No restart is needed."
                ),
                progress=None,
                restart_required=False,
            )
            self._future = None

    def _finish_application_install(self, future: Future[Any]) -> None:
        """Report a staged build, then ask the desktop to restart into it.

        A prepared plan coming back instead means the install stopped before
        its payload: the download is not the one the user was offered, and the
        page asks again rather than starting it.
        """

        try:
            prepared = future.result()
        except Exception as error:
            self._finish_error(error)
            return
        if prepared is not None:
            self._await_confirmation(prepared)
            return
        with self._lock:
            version = self._application.latest_version if self._application else None
            self._note_locked(f"Hanly {version} is staged.")
            self._state.update(
                status="restart",
                message=f"Hanly {version} is staged. Restarting to finish the update.",
                progress=None,
                restart_required=True,
                cancellable=False,
                awaiting_confirmation=False,
            )
            self._future = None
            # The helper is already waiting for this process to exit.
            self._handed_off = True
        if self._on_restart_required is not None:
            self._on_restart_required()

    def _await_confirmation(self, prepared: Any) -> None:
        """Hold a decided plan, and say what the larger download would cost."""

        summary = _plan_summary(prepared)
        with self._lock:
            self._prepared = prepared
            reason = str(summary.get("fallback_reason") or "")
            self._note_locked(reason or "A full download is needed.")
            self._state.update(
                status="confirm",
                message=reason or "This installation needs the full download.",
                plan=summary,
                awaiting_confirmation=True,
                cancellable=False,
                progress=None,
            )
            self._future = None

    def _finish_error(self, error: Exception) -> None:
        # A failed or cancelled application install still holds a transaction
        # and the installation's lock, and releasing them is the installer's
        # own work - done outside the lock, because it touches the filesystem.
        cancelled = bool(getattr(error, "cancelled", False))
        with self._lock:
            owns_application = self._state.get("active_resource_id") == APPLICATION_STEM
        installer = self._application_installer
        if installer is not None and owns_application:
            installer.abandon()

        with self._lock:
            message = (
                "The update was stopped. Nothing was changed."
                if cancelled
                else f"Update failed: {error}"
            )
            self._prepared = None
            self._note_locked(message)
            self._state.update(
                status="cancelled" if cancelled else "failed",
                message=message,
                progress=None,
                restart_required=False,
                awaiting_confirmation=False,
                cancellable=False,
            )
            self._future = None


def _state(
    *,
    status: str,
    message: str,
    application: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "available": False,
        "status": status,
        "message": message,
        "resources": [],
        "active_resource_id": None,
        "progress": None,
        "application": application,
        "restart_required": False,
        "plan": None,
        "awaiting_confirmation": False,
        "cancellable": False,
        "activity": [],
        "outcome": None,
    }


def _check_status(available: bool, resource_error: str | None) -> str:
    """An update to offer outranks a half that could not answer."""

    if available:
        return "available"
    return "failed" if resource_error is not None else "current"


def _check_message(
    resource_available: bool, application_available: bool, resource_error: str | None
) -> str:
    if resource_error is not None:
        could_not_check = f"Could not check for resource updates: {resource_error}"
        if application_available:
            return f"{could_not_check} A new Hanly version is available."
        return could_not_check
    if resource_available and application_available:
        return "A new Hanly version and resource updates are available."
    if application_available:
        return "A new Hanly version is available."
    if resource_available:
        return "Resource updates are available."
    return "Hanly and all local resources are current."


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
    # Keys are exactly the phases ``UpdateService.install`` emits; a phase
    # without a label here would show the raw phase name to the user.
    application = progress.resource_id in (APPLICATION_STEM, "hanly-desktop")
    labels = {
        "preparing": "Preparing…",
        "inspecting": "Checking installed files…",
        "downloading": "Downloading Hanly…" if application else "Downloading resource…",
        "verifying": "Verifying the download…" if application else "Verifying resource…",
        "unpacking": "Preparing files…",
        "installing": "Installing…" if application else "Installing resource…",
        "staged": "Ready to restart.",
        "complete": "Update complete." if application else "Resource update complete.",
    }
    return labels.get(progress.phase, f"{progress.phase.capitalize()}…")


def _plan_summary(prepared: Any) -> dict[str, Any]:
    """Read a prepared update's own summary, whatever produced it."""

    summary = getattr(prepared, "summary", None)
    value = summary() if callable(summary) else None
    return dict(value) if isinstance(value, dict) else {}


def _copy_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["resources"] = [dict(item) for item in value["resources"]]
    result["activity"] = [dict(item) for item in value.get("activity", ())]
    plan = value.get("plan")
    result["plan"] = None if plan is None else dict(plan)
    progress = value.get("progress")
    result["progress"] = None if progress is None else dict(progress)
    application = value.get("application")
    result["application"] = None if application is None else dict(application)
    return result


def _application_check_failure(error: Exception) -> dict[str, Any]:
    return {
        "current_version": None,
        "latest_version": None,
        "release_url": None,
        "available": False,
        "installable": False,
        "message": f"Could not check for a new Hanly version: {error}",
    }


__all__ = [
    "ACTIVITY_LIMIT",
    "PROGRESS_INTERVAL_SECONDS",
    "ApplicationInstall",
    "ApplicationInstallPort",
    "UpdateCoordinator",
    "UpdateServicePort",
]
