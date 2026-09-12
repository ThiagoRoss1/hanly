"""The lookup engine in a process of its own: residency, races, and exits.

These run the real child body on a thread over a real pipe, so the transport,
the reader/processing split, cancellation, and generation handling are the
production ones. The process boundary itself is covered by
``tests/integration/test_lookup_process_spawn.py``.
"""

from __future__ import annotations

import pickle
import threading
from pathlib import Path

import pytest
from hanly import LookupStatus, PixelFormat, Point, ROIImage
from hanly.errors import LookupCancelled
from hanly_app.lookup_controller import LookupRequest
from hanly_app.lookup_process import (
    LookupEngine,
    LookupProcessError,
    LookupSettings,
    create_process_lookup_controller,
)

from tests.hanly_fixtures.lookup_child import (
    PIXEL,
    TARGET,
    WORD,
    RecordingProviders,
    ThreadChildSpawner,
    settings,
)

#: Bounded so a transport regression fails the test instead of hanging it.
_WAIT_SECONDS = 5.0


def _image(seed: int) -> ROIImage:
    """A distinct ROI per request, so the worker's OCR cache never answers."""

    return ROIImage(
        width=1, height=1, pixel_format=PixelFormat.RGB_888, data=bytes((seed, 0, 0))
    )


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> RecordingProviders:
    recorder = RecordingProviders()
    recorder.install(monkeypatch)
    return recorder


def _engine(spawner: ThreadChildSpawner, **options: object) -> LookupEngine:
    """Build an engine and attach it the way the executor thread does."""

    engine = LookupEngine(settings(), spawn=spawner, **options)  # type: ignore[arg-type]
    engine.attach()
    return engine


def test_a_lookup_runs_in_the_child_and_comes_back_normalized(
    providers: RecordingProviders,
) -> None:
    engine = _engine(ThreadChildSpawner())
    try:
        result = engine(_request(1))
    finally:
        engine.close()

    assert result.status is LookupStatus.SUCCESS
    assert result.entries[0].headword == WORD


def test_the_child_owns_every_provider_on_one_thread(
    providers: RecordingProviders,
) -> None:
    """A SQLite connection opened off the processing thread cannot be used on
    it, and construction on the caller's thread would load the OCR stack there."""

    engine = _engine(ThreadChildSpawner())
    caller = threading.get_ident()
    try:
        engine(_request(1))
    finally:
        engine.close()

    used = set(providers.threads.values())
    assert set(providers.threads) == {
        "ocr",
        "ocr_prewarm",
        "ocr_recognize",
        "morphology",
        "dictionary",
        "dictionary_lookup",
        "dictionary_close",
    }
    assert len(used) == 1
    assert caller not in used


def test_the_value_that_crosses_the_boundary_is_plain(providers: RecordingProviders) -> None:
    """A HanlyRuntime carries a resource manager, factories, and a timeline;
    none of that may be pickled into a child."""

    value = settings(Path("/tmp/krdict.sqlite3"))

    restored = pickle.loads(pickle.dumps(value))

    assert restored == value
    assert isinstance(restored, LookupSettings)


def test_an_engine_starts_asleep_when_nothing_asked_for_residency(
    providers: RecordingProviders,
) -> None:
    spawner = ThreadChildSpawner()
    engine = _engine(spawner, preload=False)
    try:
        assert engine.state == "sleeping"
        assert spawner.spawns == 0
    finally:
        engine.close()


def test_a_request_wakes_a_sleeping_engine(providers: RecordingProviders) -> None:
    spawner = ThreadChildSpawner()
    engine = _engine(spawner, preload=False)
    try:
        result = engine(_request(1))
    finally:
        engine.close()

    assert spawner.spawns == 1
    assert result.status is LookupStatus.SUCCESS


def test_retiring_releases_the_child_and_a_later_request_starts_a_new_one(
    providers: RecordingProviders,
) -> None:
    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    try:
        first = engine.generation
        engine.retire()

        assert engine.state == "sleeping"
        assert not spawner.children[0].is_alive()

        engine(_request(2))
        assert spawner.spawns == 2
        assert engine.generation > first
        assert engine.state == "ready"
    finally:
        engine.close()


def test_retiring_while_a_child_is_still_preparing_leaves_it_retired(
    providers: RecordingProviders,
) -> None:
    """The generation moves first, so a child that finishes starting afterwards
    finds itself superseded and closes instead of becoming current."""

    holding = threading.Event()
    started = threading.Event()

    def hold(_settings: LookupSettings) -> None:
        started.set()
        holding.wait(_WAIT_SECONDS)

    spawner = ThreadChildSpawner(on_start=hold)
    engine = _engine(spawner, preload=False)
    try:
        engine.prepare()
        assert started.wait(_WAIT_SECONDS)
        engine.retire()
        holding.set()

        _settle(lambda: not spawner.children[0].is_alive())
        assert engine.state == "sleeping"
    finally:
        holding.set()
        engine.close()


def test_a_failing_child_reports_error_rather_than_a_fabricated_lookup(
    providers: RecordingProviders,
) -> None:
    spawner = ThreadChildSpawner(fail_with="no Korean model")
    states: list[tuple[str, str]] = []
    engine = _engine(spawner, preload=False, on_state=lambda *item: states.append(item))
    try:
        with pytest.raises(LookupProcessError, match="no Korean model"):
            engine(_request(1))

        assert engine.state == "error"
        assert states[-1][0] == "error"
    finally:
        engine.close()


def test_an_unexpected_exit_is_recovered_once_and_then_stays_an_error(
    providers: RecordingProviders,
) -> None:
    spawner = ThreadChildSpawner()
    notes: list[str] = []
    engine = _engine(spawner, on_diagnostic=notes.append)
    try:
        _crash(spawner)
        _settle(lambda: engine.state == "ready" and spawner.spawns == 2)
        assert engine.recovery_budget == 0

        _crash(spawner)
        _settle(lambda: engine.state == "error")
        assert spawner.spawns == 2

        with pytest.raises(LookupProcessError):
            engine(_request(3))

        engine.reset_recovery_budget()
        assert engine(_request(4)).status is LookupStatus.SUCCESS
        assert spawner.spawns == 3
    finally:
        engine.close()

    assert any("stopped unexpectedly" in note for note in notes)


def test_a_replacement_reporting_ready_does_not_refill_the_budget(
    providers: RecordingProviders,
) -> None:
    """Otherwise a crash loop funds its own restarts for the whole session."""

    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    try:
        _crash(spawner)
        _settle(lambda: spawner.spawns == 2 and engine.state == "ready")

        assert engine.recovery_budget == 0
    finally:
        engine.close()


def test_a_superseded_request_is_cancelled_in_the_child(
    providers: RecordingProviders,
) -> None:
    """Cancellation is resource control: it stops the child between stages,
    while currency in the parent remains what decides what is shown."""

    providers.hold = threading.Event()
    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    failures: list[BaseException] = []
    running = _request(1)

    def run() -> None:
        try:
            engine(running)
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=run, daemon=True)
    try:
        worker.start()
        assert providers.entered.acquire(timeout=_WAIT_SECONDS)
        running.cancel()
        # The child has taken the cancellation before recognition is released,
        # so the next stage boundary is where the lookup stops.
        _settle(lambda: spawner.child_transports[-1].saw("cancel"))
        providers.hold.set()
        worker.join(_WAIT_SECONDS)
    finally:
        providers.hold.set()
        engine.close()

    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], LookupCancelled)


def test_only_the_latest_pending_request_reaches_the_child(
    providers: RecordingProviders,
) -> None:
    """The parent holds one latest pending job, so an image never queues up
    behind another in the pipe."""

    providers.hold = threading.Event()
    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    delivered: list[str] = []
    controller = create_process_lookup_controller(
        engine, lambda result: delivered.append(result.status.value)
    )
    try:
        controller.start()
        assert controller.wait_until_ready(timeout=_WAIT_SECONDS)

        first = controller.submit(_image(1), TARGET)
        assert providers.entered.acquire(timeout=_WAIT_SECONDS)
        controller.submit(_image(2), TARGET)
        latest = controller.submit(_image(3), TARGET)
        providers.hold.clear()
        providers.hold.set()

        _settle(lambda: controller.is_current(latest) and providers.lookups >= 1)
        _settle(lambda: delivered != [])
    finally:
        providers.hold.set()
        controller.stop()

    # The superseded first request never reaches presentation, and the
    # replaced middle one never reaches the child at all.
    assert first.is_cancelled()
    assert delivered == [LookupStatus.SUCCESS.value]


def test_closing_releases_a_lookup_waiting_on_a_child_that_is_gone(
    providers: RecordingProviders,
) -> None:
    providers.hold = threading.Event()
    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            engine(_request(1))
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert providers.entered.acquire(timeout=_WAIT_SECONDS)
    _crash(spawner)
    worker.join(_WAIT_SECONDS)
    providers.hold.set()
    engine.close()

    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], LookupProcessError)


def test_a_closed_engine_refuses_to_start_another_child(
    providers: RecordingProviders,
) -> None:
    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    engine.close()

    with pytest.raises(LookupProcessError, match="shut down"):
        engine(_request(1))
    assert spawner.spawns == 1


def _request(seed: int) -> LookupRequest:
    return LookupRequest(seed, _image(seed), TARGET)


def _crash(spawner: ThreadChildSpawner) -> None:
    """Close the child's own end, which is the EOF an abrupt exit produces."""

    spawner.child_transports[-1].close()


def _settle(condition: object, timeout: float = _WAIT_SECONDS) -> None:
    """Wait for a background transition rather than sleeping for one."""

    from time import monotonic, sleep

    assert callable(condition)
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if condition():
            return
        sleep(0.01)
    raise AssertionError("the engine never reached the expected state")


def test_the_one_pixel_fixture_stays_a_valid_roi() -> None:
    assert PIXEL.width == 1 and PIXEL.pixel_format is PixelFormat.RGB_888
    assert isinstance(TARGET, Point)


def test_a_stop_during_preparation_does_not_spawn_a_replacement(
    providers: RecordingProviders,
) -> None:
    """Waiting for the start lock can outlast the stop that was asked for.

    A background preparation queued behind a start is what made Stop a promise
    the engine could take back: the thread woke up on the far side of the
    retirement and loaded a child the user had just released.
    """

    spawner = ThreadChildSpawner()
    engine = LookupEngine(settings(), spawn=spawner)  # type: ignore[arg-type]
    holding = threading.Event()
    released = threading.Event()

    # Hold the start lock so the background preparation is parked behind it
    # while the retirement happens, which is the race in production.
    def hold_start_lock() -> None:
        with engine._start_lock:
            holding.set()
            released.wait(_WAIT_SECONDS)

    holder = threading.Thread(target=hold_start_lock, daemon=True)
    holder.start()
    assert holding.wait(_WAIT_SECONDS)
    try:
        engine.prepare()
        engine.retire()
    finally:
        released.set()
        holder.join(_WAIT_SECONDS)

    for _ in range(50):
        if spawner.spawns:
            break
        threading.Event().wait(0.02)

    assert spawner.spawns == 0
    assert engine.state == "sleeping"
    engine.close()


def test_a_lookup_after_a_stop_is_still_allowed_to_wake_the_engine(
    providers: RecordingProviders,
) -> None:
    """The guard is on queued residency requests, not on asking for an answer."""

    spawner = ThreadChildSpawner()
    engine = _engine(spawner)
    try:
        assert engine(_request(1)).status is LookupStatus.SUCCESS
        engine.retire()
        assert engine(_request(2)).status is LookupStatus.SUCCESS
    finally:
        engine.close()

    assert spawner.spawns == 2
