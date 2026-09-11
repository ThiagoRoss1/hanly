from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceMetadata
from hanly_app.app_update import ApplicationUpdate
from hanly_app.update_coordinator import UpdateCoordinator, _progress_message
from hanly_app.update_service import (
    DownloadProgress,
    ProgressCallback,
    RemoteResource,
    UpdateAvailability,
    UpdateResult,
)

#: The phases ``UpdateService.install`` emits, in order. The coordinator turns
#: each into a user-facing message, so the double must not invent its own.
_INSTALL_PHASES = ("downloading", "verifying", "installing", "complete")


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
            for phase in _INSTALL_PHASES:
                on_progress(DownloadProgress(resource_id, phase, 1, 1))
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


#: The coordinator publishes progress through its snapshot rather than an event,
#: so waiting on it is a deadline rather than a fixed number of tries -- a busy
#: machine must be slow here, never a failure.
_STATUS_TIMEOUT = 10.0


def _wait_for(coordinator: UpdateCoordinator, status: str) -> dict[str, Any]:
    deadline = time.monotonic() + _STATUS_TIMEOUT
    while time.monotonic() < deadline:
        state = coordinator.snapshot()
        if state["status"] == status:
            return state
        time.sleep(0.005)
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


def test_successful_install_is_recorded_before_runtime_refresh() -> None:
    service = _FakeService()
    events: list[str] = []
    coordinator = UpdateCoordinator(
        service,
        before_install=lambda resource_id: events.append(f"prepare:{resource_id}"),
        record_install=lambda result: events.append(
            f"record:{result.resource.resource_id}:{result.resource.version}"
        ),
        after_install=lambda resource_id: events.append(f"refresh:{resource_id}"),
    )
    try:
        coordinator.check_for_updates()
        _wait_for(coordinator, "available")
        coordinator.install_update("krdict")
        _wait_for(coordinator, "success")
    finally:
        coordinator.shutdown(wait=True)

    assert events == ["prepare:krdict", "record:krdict:2", "refresh:krdict"]


def test_every_install_phase_has_a_user_facing_message() -> None:
    """A phase without a label leaks the raw phase name into the UI, which is
    how ``verifying``/``installing`` progress was previously hidden."""

    messages = [
        _progress_message(DownloadProgress("krdict", phase, 1, 1))
        for phase in _INSTALL_PHASES
    ]
    fallbacks = [f"Resource update: {phase}." for phase in _INSTALL_PHASES]

    assert not set(messages) & set(fallbacks)
    assert len(set(messages)) == len(_INSTALL_PHASES)


def test_an_unreachable_release_channel_never_reaches_the_caller() -> None:
    """An offline launch must stay up. A failed availability check is state the
    Control Center can show, not an exception that escapes into startup."""

    class _Offline:
        def check_for_updates(self) -> tuple[UpdateAvailability, ...]:
            raise OSError("[Errno 11001] getaddrinfo failed")

        def install(
            self, resource_id: str, *, on_progress: ProgressCallback | None = None
        ) -> UpdateResult:
            raise AssertionError("nothing is installable while offline")

    coordinator = UpdateCoordinator(_Offline())
    try:
        assert coordinator.check_for_updates()["status"] == "checking"
        state = _wait_for(coordinator, "failed")

        assert "getaddrinfo failed" in state["message"]
        assert state["available"] is False
        # Still usable: a later check on a restored connection is accepted.
        assert coordinator.check_for_updates()["status"] == "checking"
    finally:
        coordinator.shutdown()


def _settle(coordinator: UpdateCoordinator) -> dict[str, Any]:
    """Return the snapshot once the background check has finished."""

    deadline = time.monotonic() + _STATUS_TIMEOUT
    while time.monotonic() < deadline:
        state = coordinator.snapshot()
        if state["status"] != "checking":
            return state
        time.sleep(0.005)
    raise AssertionError(f"update check did not finish: {coordinator.snapshot()!r}")


def test_checking_for_updates_also_reports_a_newer_application_build() -> None:
    coordinator = UpdateCoordinator(
        _FakeService(),
        application_check=lambda: ApplicationUpdate(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url="https://example.test/releases/tag/v0.2.0",
            available=True,
            message="Hanly 0.2.0 is available. You are running 0.1.0.",
        ),
    )
    try:
        coordinator.check_for_updates()
        state = _settle(coordinator)

        assert state["application"]["available"] is True
        assert state["application"]["latest_version"] == "0.2.0"
        assert state["available"] is True
        assert "new Hanly version" in state["message"]
    finally:
        coordinator.shutdown()


def test_an_application_check_failure_never_hides_an_available_resource_update() -> None:
    def explode() -> ApplicationUpdate:
        raise RuntimeError("release channel unreachable")

    coordinator = UpdateCoordinator(_FakeService(), application_check=explode)
    try:
        coordinator.check_for_updates()
        state = _settle(coordinator)

        assert state["resources"][0]["available"] is True
        assert state["available"] is True
        assert state["application"]["available"] is False
        assert "release channel unreachable" in state["application"]["message"]
    finally:
        coordinator.shutdown()


def test_without_an_application_check_the_snapshot_reports_no_application_state() -> None:
    coordinator = UpdateCoordinator(_FakeService())
    try:
        coordinator.check_for_updates()
        state = _settle(coordinator)

        assert state["application"] is None
        assert state["message"] == "Resource updates are available."
    finally:
        coordinator.shutdown()


def test_a_non_callable_application_check_is_refused_at_construction() -> None:
    try:
        UpdateCoordinator(_FakeService(), application_check=cast(Any, "not callable"))
    except TypeError as error:
        assert "application_check" in str(error)
    else:
        raise AssertionError("expected a non-callable application check to be refused")


def _installable(version: str = "0.2.0") -> ApplicationUpdate:
    return ApplicationUpdate(
        current_version="0.1.0",
        latest_version=version,
        release_url="https://github.com/example/hanly/releases/tag/v" + version,
        available=True,
        message=f"Hanly {version} is available.",
        installable=True,
    )


def test_a_resource_update_is_hot_swapped_and_asks_for_no_restart() -> None:
    """Replacing the dictionary must not cost the user a restart."""

    coordinator = UpdateCoordinator(_FakeService())
    try:
        coordinator.check_for_updates()
        _settle(coordinator)
        coordinator.install_update("krdict")
        state = _wait_for(coordinator, "success")

        assert state["restart_required"] is False
        assert "No restart is needed." in state["message"]
    finally:
        coordinator.shutdown()


def test_an_application_update_is_staged_in_app_and_then_restarts() -> None:
    staged: list[str | None] = []
    restarts: list[str] = []
    coordinator = UpdateCoordinator(
        _FakeService(),
        application_check=_installable,
        application_install=lambda update, on_progress: staged.append(update.latest_version),
        on_restart_required=lambda: restarts.append("quit"),
    )
    try:
        coordinator.check_for_updates()
        _settle(coordinator)

        coordinator.install_application_update()
        state = _wait_for(coordinator, "restart")

        assert staged == ["0.2.0"]
        assert restarts == ["quit"]
        assert state["restart_required"] is True
        assert "0.2.0" in state["message"]
    finally:
        coordinator.shutdown()


def test_a_failed_application_install_neither_restarts_nor_claims_success() -> None:
    restarts: list[str] = []

    def explode(update: ApplicationUpdate, on_progress: object) -> None:
        raise RuntimeError("checksum does not match")

    coordinator = UpdateCoordinator(
        _FakeService(),
        application_check=_installable,
        application_install=explode,
        on_restart_required=lambda: restarts.append("quit"),
    )
    try:
        coordinator.check_for_updates()
        _settle(coordinator)

        coordinator.install_application_update()
        state = _wait_for(coordinator, "failed")

        assert restarts == []
        assert state["restart_required"] is False
        assert "checksum does not match" in state["message"]
    finally:
        coordinator.shutdown()


def test_an_application_build_this_installation_cannot_apply_is_not_installed() -> None:
    """A source checkout is told a build exists; it is never asked to stage one."""

    staged: list[str] = []
    coordinator = UpdateCoordinator(
        _FakeService(),
        application_check=lambda: replace(_installable(), installable=False),
        application_install=lambda update, on_progress: staged.append("staged"),
    )
    try:
        coordinator.check_for_updates()
        _settle(coordinator)

        with pytest.raises(ValueError, match="no installable application update"):
            coordinator.install_application_update()

        assert staged == []
    finally:
        coordinator.shutdown()


def test_a_non_callable_application_install_is_refused_at_construction() -> None:
    with pytest.raises(TypeError, match="application_install"):
        UpdateCoordinator(_FakeService(), application_install=cast(Any, "not callable"))
    with pytest.raises(TypeError, match="on_restart_required"):
        UpdateCoordinator(_FakeService(), on_restart_required=cast(Any, "not callable"))


def test_no_restart_is_claimed_until_the_build_is_actually_staged() -> None:
    """Downloading and verifying change nothing on disk, so a restart is not
    yet required; only a completed stage with a ready handoff requires one."""

    observed: list[bool] = []
    release = threading.Event()

    def slow_install(update: ApplicationUpdate, on_progress: ProgressCallback | None) -> None:
        for phase in ("downloading", "verifying", "installing"):
            if on_progress is not None:
                on_progress(DownloadProgress("hanly-desktop", phase, 1, 2))
            observed.append(coordinator.snapshot()["restart_required"])
        release.wait(5)

    coordinator = UpdateCoordinator(
        _FakeService(),
        application_check=_installable,
        application_install=slow_install,
    )
    try:
        coordinator.check_for_updates()
        _settle(coordinator)

        pending = coordinator.install_application_update()
        assert pending["restart_required"] is False
        release.set()
        state = _wait_for(coordinator, "restart")

        assert observed == [False, False, False]
        assert state["restart_required"] is True
    finally:
        release.set()
        coordinator.shutdown()


def test_a_resource_check_failure_never_hides_a_new_hanly_version() -> None:
    """The two halves reach the same release channel and answer different
    questions. A manifest the user cannot fix is no reason to stop telling
    them a new Hanly exists - which is also the update that would fix it."""

    class _BrokenResources(_FakeService):
        def check_for_updates(self) -> tuple[UpdateAvailability, ...]:
            raise RuntimeError("resource manifest unreadable")

    coordinator = UpdateCoordinator(
        _BrokenResources(),
        application_check=lambda: ApplicationUpdate(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url=None,
            available=True,
            message="Hanly 0.2.0 is available.",
            installable=True,
        ),
    )
    try:
        coordinator.check_for_updates()
        state = _settle(coordinator)

        assert state["application"]["available"] is True
        assert state["resources"] == []
        assert state["available"] is True
        # And the half that could not answer says so, rather than passing for
        # "no resource updates" - which would read as everything being current.
        assert "resource manifest unreadable" in state["message"]
    finally:
        coordinator.shutdown()


def test_a_resource_check_that_could_not_run_is_never_reported_as_up_to_date() -> None:
    class _BrokenResources(_FakeService):
        def check_for_updates(self) -> tuple[UpdateAvailability, ...]:
            raise OSError("manifest is not valid JSON")

    coordinator = UpdateCoordinator(
        _BrokenResources(),
        application_check=lambda: ApplicationUpdate(
            current_version="0.1.0",
            latest_version="0.1.0",
            release_url=None,
            available=False,
            message="Hanly 0.1.0 is up to date.",
        ),
    )
    try:
        coordinator.check_for_updates()
        state = _settle(coordinator)

        assert state["status"] == "failed"
        assert state["available"] is False
        assert "manifest is not valid JSON" in state["message"]
        assert "current" not in state["message"]
    finally:
        coordinator.shutdown()


class _QuietService(_FakeService):
    """A service whose install reports no progress.

    ``_DeferredExecutor`` runs the operation on the caller's thread, and the
    caller is inside the coordinator's lock. Progress reporting reaches for
    that same lock, which only a real worker thread makes safe.
    """

    def install(
        self, resource_id: str, *, on_progress: ProgressCallback | None = None
    ) -> UpdateResult:
        return super().install(resource_id)


class _DeferredExecutor:
    """Run work immediately, but hold its completion callback until released.

    ``Future.done()`` turns true before the callback that finalizes the
    coordinator's state runs. This makes that window wide enough to click in.
    """

    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def submit(self, operation: Any) -> Any:
        from concurrent.futures import Future

        future: Future[Any] = Future()
        future.set_running_or_notify_cancel()
        try:
            future.set_result(operation())
        except BaseException as error:  # noqa: BLE001 - delivered to the callback
            future.set_exception(error)
        return _HeldFuture(future, self.callbacks)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None: ...

    def release(self) -> None:
        """Deliver the held callbacks and wait out the threads they run on."""

        for callback in self.callbacks:
            callback()
        self.callbacks.clear()
        deadline = time.monotonic() + _STATUS_TIMEOUT
        while time.monotonic() < deadline:
            if not any(
                thread.name == "hanly-update-result" for thread in threading.enumerate()
            ):
                return
            time.sleep(0.005)
        raise AssertionError("an update result thread never finished")


@dataclass
class _HeldFuture:
    """A completed future whose done-callback is queued instead of run."""

    future: Any
    callbacks: list[Any]

    def add_done_callback(self, callback: Any) -> None:
        # The real executor hands the callback the future it registered on,
        # which is what the coordinator compares against to spot a stale one.
        self.callbacks.append(lambda: callback(self))

    def done(self) -> bool:
        return True

    def result(self) -> Any:
        return self.future.result()


def test_an_operation_owns_the_coordinator_until_its_callback_finalizes() -> None:
    """A second click landing between completion and the callback would start
    an operation whose result the older callback then overwrites."""

    executor = _DeferredExecutor()
    coordinator = UpdateCoordinator(
        _QuietService(),
        executor=cast(Any, executor),
        application_check=lambda: ApplicationUpdate(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url=None,
            available=True,
            message="Hanly 0.2.0 is available.",
        ),
    )

    coordinator.check_for_updates()
    # The check has finished; only its callback has not.
    assert coordinator.snapshot()["status"] == "checking"
    assert coordinator.install_update("krdict")["status"] == "checking"

    executor.release()

    state = coordinator.snapshot()
    assert state["status"] == "available"
    # The second click never ran, so nothing overwrote the check's result.
    assert state["active_resource_id"] is None


def test_a_stale_callback_cannot_speak_for_the_operation_that_replaced_it() -> None:
    """Callbacks run on their own threads, so an old one can arrive at any
    moment. Only the operation the coordinator still holds may report."""

    executor = _DeferredExecutor()
    coordinator = UpdateCoordinator(_QuietService(), executor=cast(Any, executor))

    coordinator.check_for_updates()
    stale = list(executor.callbacks)
    executor.callbacks.clear()
    # Release ownership the way the first callback would have, then start the
    # operation that now holds it. Only the older callback is delivered.
    coordinator._future = None  # type: ignore[attr-defined]
    coordinator.install_update("krdict")
    pending = list(executor.callbacks)
    executor.callbacks[:] = stale

    executor.release()

    state = coordinator.snapshot()
    assert state["status"] == "downloading"
    assert state["active_resource_id"] == "krdict"
    assert len(pending) == 1


def test_no_further_update_is_started_once_the_swap_is_waiting_for_this_process() -> None:
    """The handoff is already waiting for this process to exit. A second click
    would download over the transaction that swap is about to use."""

    staged: list[str] = []
    coordinator = UpdateCoordinator(
        _FakeService(),
        application_check=lambda: _INSTALLABLE,
        application_install=lambda update, progress: staged.append("staged"),
        on_restart_required=lambda: None,
    )
    try:
        coordinator.check_for_updates()
        _settle(coordinator)
        coordinator.install_application_update()
        _wait_for(coordinator, "restart")

        assert coordinator.check_for_updates()["status"] == "restart"
        assert coordinator.install_application_update()["status"] == "restart"
        assert staged == ["staged"]
    finally:
        coordinator.shutdown()


_INSTALLABLE = ApplicationUpdate(
    current_version="0.1.0",
    latest_version="0.2.0",
    release_url=None,
    available=True,
    message="Hanly 0.2.0 is available.",
    installable=True,
)
