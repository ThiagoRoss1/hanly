"""Running native reads away from the caller's thread, and bounding them.

Accessibility calls are synchronous IPC that cannot be interrupted, so the
service must keep a slow target from holding the caller, from accumulating
work, and from ever publishing an answer that arrived too late to be true.
"""

from __future__ import annotations

from threading import Barrier, Event, current_thread
from typing import Any

import pytest
from hanly import BoundingBox, Point
from hanly_app.text_acquisition import (
    Acquisition,
    DirectText,
    DirectTextCoordinator,
    DirectTextService,
    Outcome,
)

_KOREAN = "초대받았어요"
_BOUNDS = BoundingBox(left=0, top=0, right=100, bottom=20)
_POINT = Point(50, 10)


class _Reader:
    """A provider whose answer, delay and failure are all controllable."""

    def __init__(self, *, block: Event | None = None, error: Exception | None = None):
        self.block = block
        self.error = error
        self.calls = 0
        self.entered = Event()
        self.threads: list[str] = []

    def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
        self.calls += 1
        self.threads.append(current_thread().name)
        self.entered.set()
        if self.block is not None:
            self.block.wait(timeout=5.0)
        if self.error is not None:
            raise self.error
        return DirectText(text=_KOREAN, cursor_index=0, bounds=_BOUNDS)


def _service(reader: Any, *, timeout_ms: int = 40) -> DirectTextService:
    return DirectTextService(DirectTextCoordinator(reader, timeout_ms=timeout_ms))


class _Collector:
    """Records delivered outcomes and signals when one has arrived."""

    def __init__(self) -> None:
        self.outcomes: list[Acquisition] = []
        self.done = Event()

    def __call__(self, acquired: Acquisition) -> None:
        self.outcomes.append(acquired)
        self.done.set()


def _collect() -> _Collector:
    return _Collector()


def test_the_read_never_runs_on_the_submitting_thread() -> None:
    reader = _Reader()
    service = _service(reader)
    collector = _collect()
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
    finally:
        service.close()

    assert collector.outcomes[0].outcome is Outcome.DIRECT
    assert reader.threads and current_thread().name not in reader.threads


def test_a_blocked_read_releases_the_caller_after_the_deadline() -> None:
    """Exactly one outcome, and it says the deadline passed."""

    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=30)
    collector = _collect()
    try:
        service.submit(_POINT, collector)
        assert reader.entered.wait(timeout=5.0)
        assert collector.done.wait(timeout=5.0), "the caller was never released"
        assert collector.outcomes[-1].outcome is Outcome.TIMED_OUT
    finally:
        block.set()
        service.close()

    # The native call finishes later; its answer must not be delivered twice.
    assert len(collector.outcomes) == 1


def test_a_late_answer_is_discarded_rather_than_published() -> None:
    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=20)
    collector = _collect()
    try:
        service.submit(_POINT, collector)
        assert reader.entered.wait(timeout=5.0)
        assert collector.done.wait(timeout=5.0)
        block.set()
        # Give the still-running call every chance to deliver a second time.
        service.close()
    finally:
        block.set()

    assert [a.outcome for a in collector.outcomes] == [Outcome.TIMED_OUT]


def test_repeated_hovers_do_not_accumulate_native_calls() -> None:
    """Only the newest pointer position is worth asking about."""

    gate = Barrier(2, timeout=5.0)
    started = Event()

    class _Gated:
        def __init__(self) -> None:
            self.calls = 0

        def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
            self.calls += 1
            if not started.is_set():
                started.set()
                gate.wait()
            return DirectText(text=_KOREAN, cursor_index=0, bounds=_BOUNDS)

    reader = _Gated()
    service = _service(reader, timeout_ms=5_000)
    delivered: list[Acquisition] = []
    try:
        service.submit(_POINT, delivered.append)
        assert started.wait(timeout=5.0)
        # Twenty more hovers arrive while the first call is still inside the
        # provider. They must collapse, not queue.
        for _ in range(20):
            service.submit(_POINT, delivered.append)
        gate.wait()
    finally:
        service.close()

    assert reader.calls <= 2, reader.calls


def test_a_superseded_request_reports_supersession() -> None:
    reader = _Reader()
    service = _service(reader, timeout_ms=5_000)
    first: list[Acquisition] = []
    second = _collect()
    try:
        service.submit(_POINT, first.append)
        service.submit(_POINT, second)
        assert second.done.wait(timeout=5.0)
    finally:
        service.close()

    assert second.outcomes[0].outcome is Outcome.DIRECT


def test_shutdown_during_an_active_call_delivers_nothing_and_leaves_no_thread() -> None:
    import threading

    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=5_000)
    delivered: list[Acquisition] = []
    service.submit(_POINT, delivered.append)
    assert reader.entered.wait(timeout=5.0)

    block.set()
    service.close()

    assert delivered == []
    names = {t.name for t in threading.enumerate()}
    assert "hanly-text-acquisition" not in names
    assert "hanly-acquisition-deadline" not in names


def test_a_provider_exception_is_delivered_as_an_ordinary_refusal() -> None:
    reader = _Reader(error=RuntimeError("accessibility died"))
    service = _service(reader)
    collector = _collect()
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
    finally:
        service.close()

    assert collector.outcomes[0].outcome is Outcome.FAILED
    assert collector.outcomes[0].detail == "RuntimeError"


def test_a_denied_permission_is_delivered_without_reading() -> None:
    reader = _Reader()
    service = DirectTextService(
        DirectTextCoordinator(reader, permitted=lambda: False)
    )
    collector = _collect()
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
    finally:
        service.close()

    assert collector.outcomes[0].outcome is Outcome.NO_PERMISSION
    assert reader.calls == 0


def test_submitting_after_close_is_refused() -> None:
    service = _service(_Reader())
    service.close()

    with pytest.raises(RuntimeError):
        service.submit(_POINT, lambda _a: None)


def test_the_submitting_thread_keeps_working_while_a_read_is_blocked() -> None:
    """The thread that draws must not wait on accessibility IPC."""

    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=5_000)
    try:
        service.submit(_POINT, lambda _a: None)
        # Scheduling returned while the provider is still inside read_at, which
        # is the whole claim: it handed the work over rather than performing it.
        # Proved by ordering rather than by a clock, so a loaded host cannot
        # turn this into a flake.
        assert reader.entered.wait(timeout=5.0), "the read never started"
        assert not block.is_set(), "the reader was released before the check"

        # The submitting thread is free to keep working while it is stuck.
        ticks = sum(1 for _ in range(10_000))
        assert ticks == 10_000
        assert not block.is_set()
    finally:
        block.set()
        service.close()


def test_a_native_deadline_shorter_than_the_budget_leaves_room_to_classify() -> None:
    """A call that reaches the native deadline must still be usable evidence.

    The two deadlines were once equal, which made every slow call report as too
    late to use instead of as an ordinary unsupported element.
    """

    from hanly_app.text_acquisition_ax import _NATIVE_DEADLINE_SHARE

    assert 0 < _NATIVE_DEADLINE_SHARE < 1


def test_the_watcher_stops_working_once_a_deadline_is_answered() -> None:
    """A blocked call must not keep the deadline watcher busy.

    The deadline has passed and the native call cannot be stopped, so there is
    nothing left to decide until the job changes. Re-deciding it in a loop
    burns a core for as long as the target stays unresponsive.
    """

    from time import monotonic, sleep

    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=20)
    attempts = 0
    original = service._deliver

    def counting(job: object, outcome: Acquisition) -> None:
        nonlocal attempts
        attempts += 1
        original(job, outcome)  # type: ignore[arg-type]

    service._deliver = counting  # type: ignore[method-assign]
    collector = _collect()
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
        settled = attempts

        # The call is still stuck. Nothing further should be decided about it.
        deadline = monotonic() + 0.4
        while monotonic() < deadline:
            sleep(0.02)
        assert attempts - settled <= 2, attempts - settled
    finally:
        block.set()
        service.close()

    assert [a.outcome for a in collector.outcomes] == [Outcome.TIMED_OUT]


def test_a_failing_callback_does_not_disable_the_service() -> None:
    """A delivery that raises must not take the worker down with it.

    If it did, nothing would consume later jobs, no outcome would ever arrive,
    and the hover that scheduled one would never fall back to capture either.
    """

    reader = _Reader()
    service = _service(reader)
    collector = _collect()
    try:

        refused = Event()

        def refuse(_acquired: Acquisition) -> None:
            refused.set()
            raise RuntimeError("the dispatcher refused")

        service.submit(_POINT, refuse)
        # Wait for the failure to actually happen; latest-wins would otherwise
        # replace this job before it ever ran.
        assert refused.wait(timeout=5.0)

        # The next hover still has to be answered.
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0), "the service stopped delivering"
    finally:
        service.close()

    assert collector.outcomes[0].outcome is Outcome.DIRECT


def test_closing_from_a_delivered_callback_does_not_fail() -> None:
    """Delivery runs on a service thread, so closing there must not self-join."""

    service = _service(_Reader())
    failure: list[BaseException] = []
    done = Event()

    def close_from_callback(_acquired: Acquisition) -> None:
        try:
            service.close()
        except BaseException as error:  # noqa: BLE001
            failure.append(error)
        finally:
            done.set()

    service.submit(_POINT, close_from_callback)
    assert done.wait(timeout=5.0)

    assert failure == []
    # And a second close from an ordinary thread is still safe.
    service.close()


class _BoundReader(_Reader):
    """A provider that has to prepare the thread it will be called on.

    Windows needs this: a COM apartment belongs to a thread, so the worker has
    to enter one before the first read and leave it after the last.
    """

    def __init__(self) -> None:
        super().__init__()
        self.bound: list[str] = []
        self.released: list[str] = []

    def bind_thread(self) -> None:
        self.bound.append(current_thread().name)

    def release_thread(self) -> None:
        self.released.append(current_thread().name)


def test_the_worker_is_prepared_before_its_first_read_and_undone_after_its_last() -> None:
    reader = _BoundReader()
    collector = _collect()
    service = _service(reader)
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
    finally:
        service.close()

    assert reader.bound == reader.threads == reader.released
    assert len(reader.bound) == 1


def test_a_service_that_was_never_used_still_undoes_its_preparation() -> None:
    reader = _BoundReader()
    service = _service(reader)
    service.close()

    assert reader.bound == reader.released
    assert reader.calls == 0


def test_a_provider_that_cannot_prepare_its_thread_still_reaches_the_fallback() -> None:
    """Refusing to start would leave every hover waiting for an outcome forever."""

    class _Unpreparable(_Reader):
        def bind_thread(self) -> None:
            raise RuntimeError("no apartment")

        def release_thread(self) -> None:
            raise RuntimeError("nothing to leave")

    collector = _collect()
    reader = _Unpreparable()
    service = _service(reader)
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0), "the worker never started"
    finally:
        service.close()

    assert collector.outcomes[0].outcome is Outcome.FAILED
    assert reader.calls == 0


def test_a_provider_with_nothing_to_prepare_is_left_alone() -> None:
    """The reviewed macOS adapter offers no hooks and must not be asked for any."""

    collector = _collect()
    service = _service(_Reader())
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
    finally:
        service.close()

    assert collector.outcomes[0].outcome is Outcome.DIRECT


def test_pending_deadline_is_answered_while_the_worker_remains_blocked() -> None:
    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=20)
    first, latest = _collect(), _collect()
    try:
        service.submit(_POINT, first)
        assert reader.entered.wait(timeout=1)
        assert first.done.wait(timeout=1)
        service.submit(_POINT, latest)
        assert latest.done.wait(timeout=1), "pending hover never reached fallback"
        assert latest.outcomes[0].outcome is Outcome.TIMED_OUT
        assert reader.calls == 1
    finally:
        block.set()
        service.close()


def test_completion_checks_deadline_even_if_watcher_has_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hanly_app.text_acquisition import _Job

    service = _service(_Reader())
    collector = _collect()
    try:
        job = _Job(0, _POINT, 10, collector, Event())
        monkeypatch.setattr(service, "_clock", lambda: 11)
        service._deliver(job, Acquisition(Outcome.DIRECT))
        assert collector.outcomes[0].outcome is Outcome.TIMED_OUT
    finally:
        service.close()


def test_a_failed_preparation_is_never_undone() -> None:
    """Undoing a binding that did not happen could leave an apartment never entered."""

    class _HalfBound(_BoundReader):
        def bind_thread(self) -> None:
            super().bind_thread()
            raise OSError("apartment refused")

    reader = _HalfBound()
    collector = _collect()
    service = _service(reader)
    try:
        service.submit(_POINT, collector)
        assert collector.done.wait(timeout=5.0)
    finally:
        service.close()

    assert len(reader.bound) == 1
    assert reader.released == []
    assert collector.outcomes[0].outcome is Outcome.FAILED
    assert reader.calls == 0
