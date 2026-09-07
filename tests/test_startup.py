"""The interface opens first; resources are prepared behind it."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from hanly_app.diagnostics import DiagnosticLog
from hanly_app.runtime_status import RuntimeStatus, RuntimeStatusPublisher
from hanly_app.startup import StartupCoordinator

_WAIT_SECONDS = 5.0


class _Runtime:
    """Stands in for ``HanlyRuntime``; the coordinator only passes it along."""

    def __init__(self, name: str = "runtime") -> None:
        self.name = name


class _Dispatcher:
    """Records what would be marshalled onto Qt, and runs it inline."""

    def __init__(self) -> None:
        self.threads: list[str] = []

    def __call__(self, callback: Any) -> None:
        self.threads.append(threading.current_thread().name)
        callback()


def _coordinator(
    prepare: Any,
    activate: Any,
    *,
    release: Any = None,
    diagnostics: DiagnosticLog | None = None,
) -> tuple[StartupCoordinator, RuntimeStatusPublisher, _Dispatcher]:
    status = RuntimeStatusPublisher()
    dispatcher = _Dispatcher()
    coordinator = StartupCoordinator(
        prepare,
        activate,
        status=status,
        dispatcher=dispatcher,
        diagnostics=diagnostics,
        release=release,
    )
    return coordinator, status, dispatcher


def test_preparation_runs_off_the_calling_thread_and_activates_after_it() -> None:
    prepared_on: list[str] = []
    activated: list[_Runtime] = []
    runtime = _Runtime()

    def prepare(_explicit: Path | None) -> _Runtime:
        prepared_on.append(threading.current_thread().name)
        return runtime

    coordinator, status, _ = _coordinator(prepare, activated.append)
    coordinator.start()
    assert coordinator.await_shutdown(_WAIT_SECONDS)

    assert prepared_on and prepared_on[0] != threading.current_thread().name
    assert activated == [runtime]
    assert status.status.phase == "preparing"


def test_the_explicit_configuration_reaches_preparation_unchanged() -> None:
    """An operator's ``--runtime-config`` must not trigger provisioning."""

    seen: list[Path | None] = []
    explicit = Path("runtime.json")

    def prepare(value: Path | None) -> _Runtime:
        seen.append(value)
        return _Runtime()

    coordinator, _, _ = _coordinator(prepare, lambda _runtime: None)
    coordinator.start(explicit)
    coordinator.await_shutdown(_WAIT_SECONDS)

    assert seen == [explicit]


def test_a_failed_preparation_is_visible_and_does_not_raise() -> None:
    diagnostics = DiagnosticLog()

    def prepare(_explicit: Path | None) -> _Runtime:
        raise RuntimeError("no dictionary could be downloaded")

    coordinator, status, _ = _coordinator(
        prepare, lambda _runtime: None, diagnostics=diagnostics
    )
    coordinator.start()
    coordinator.await_shutdown(_WAIT_SECONDS)

    assert status.status.failed
    assert status.status.stage == "resources"
    assert "no dictionary could be downloaded" in status.status.message
    assert any("no dictionary" in message for message in diagnostics.snapshot())


def test_a_failed_activation_is_reported_against_the_provider_stage() -> None:
    def activate(_runtime: _Runtime) -> None:
        raise RuntimeError("kiwipiepy is unavailable")

    coordinator, status, _ = _coordinator(lambda _explicit: _Runtime(), activate)
    coordinator.start()
    coordinator.await_shutdown(_WAIT_SECONDS)

    assert status.status.failed
    assert status.status.stage == "lookup providers"
    assert "kiwipiepy" in status.status.message


def test_retry_releases_the_previous_attempt_before_preparing_again() -> None:
    order: list[str] = []
    attempts: list[Path | None] = []

    def prepare(explicit: Path | None) -> _Runtime:
        order.append("prepare")
        attempts.append(explicit)
        return _Runtime()

    coordinator, _, _ = _coordinator(
        prepare,
        lambda _runtime: order.append("activate"),
        release=lambda: order.append("release"),
    )
    explicit = Path("runtime.json")
    coordinator.start(explicit)
    coordinator.await_shutdown(_WAIT_SECONDS)

    coordinator.retry()
    coordinator.await_shutdown(_WAIT_SECONDS)

    assert order == ["prepare", "activate", "release", "prepare", "activate"]
    assert attempts == [explicit, explicit]
    assert coordinator.attempts == 2


def test_a_second_start_while_preparing_does_not_duplicate_the_work() -> None:
    """Retrying must not start a second download or a second worker."""

    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def prepare(_explicit: Path | None) -> _Runtime:
        calls.append("prepare")
        started.set()
        release.wait(_WAIT_SECONDS)
        return _Runtime()

    coordinator, _, _ = _coordinator(prepare, lambda _runtime: None)
    coordinator.start()
    assert started.wait(_WAIT_SECONDS)

    coordinator.start()
    coordinator.retry()
    release.set()
    coordinator.await_shutdown(_WAIT_SECONDS)

    assert calls == ["prepare"]
    assert coordinator.attempts == 1


def test_shutdown_stops_activation_and_further_reporting() -> None:
    activated: list[_Runtime] = []
    started = threading.Event()
    finish = threading.Event()

    def prepare(_explicit: Path | None) -> _Runtime:
        started.set()
        finish.wait(_WAIT_SECONDS)
        return _Runtime()

    coordinator, status, _ = _coordinator(prepare, activated.append)
    coordinator.start()
    assert started.wait(_WAIT_SECONDS)

    coordinator.begin_shutdown()
    finish.set()
    assert coordinator.await_shutdown(_WAIT_SECONDS)

    assert activated == []
    assert status.status == RuntimeStatus(
        "preparing", "resources", "Preparing Hanly's resources..."
    )


def test_a_coordinator_rejects_seams_it_cannot_call() -> None:
    status = RuntimeStatusPublisher()
    with pytest.raises(TypeError, match="prepare"):
        StartupCoordinator(
            "not callable",  # type: ignore[arg-type]
            lambda _runtime: None,
            status=status,
            dispatcher=lambda callback: callback(),
        )


def test_a_retry_releases_on_its_own_thread_rather_than_through_the_ui() -> None:
    """The release waits for providers to close, so it must not sit on Qt."""

    released: list[str] = []

    def release() -> None:
        released.append(threading.current_thread().name)

    coordinator, _, dispatcher = _coordinator(
        lambda _explicit: _Runtime(),
        lambda _runtime: None,
        release=release,
    )
    coordinator.start()
    assert coordinator.await_shutdown(_WAIT_SECONDS)
    dispatched_before_retry = len(dispatcher.threads)

    coordinator.retry()
    assert coordinator.await_shutdown(_WAIT_SECONDS)

    assert released and released[0] != threading.current_thread().name
    # The release itself was never one of the marshalled callbacks.
    assert dispatcher.threads[dispatched_before_retry:] == [released[0]]


def test_a_failed_release_stops_the_retry_instead_of_replacing_a_live_runtime(
) -> None:
    """Activating over providers that never let go is worse than not retrying."""

    prepared: list[str] = []

    def release() -> None:
        raise RuntimeError("the previous worker is still holding the database")

    coordinator, status, _ = _coordinator(
        lambda _explicit: _Runtime(),
        lambda _runtime: prepared.append("activate"),
        release=release,
    )
    coordinator.start()
    assert coordinator.await_shutdown(_WAIT_SECONDS)

    coordinator.retry()
    assert coordinator.await_shutdown(_WAIT_SECONDS)

    assert prepared == ["activate"]
    assert status.status.phase == "failed"
    assert "previous runtime" in status.status.stage
