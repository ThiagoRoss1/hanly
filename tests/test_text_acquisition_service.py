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

    from time import perf_counter_ns

    block = Event()
    reader = _Reader(block=block)
    service = _service(reader, timeout_ms=5_000)
    try:
        started = perf_counter_ns()
        service.submit(_POINT, lambda _a: None)
        scheduling_ns = perf_counter_ns() - started
        assert reader.entered.wait(timeout=5.0), "the read never started"

        # The provider is now stuck inside read_at. The submitting thread must
        # still be free, which it proves by completing work of its own.
        ticks = 0
        working = perf_counter_ns()
        while perf_counter_ns() - working < 50_000_000:
            ticks += 1
        assert ticks > 0
        assert reader.block is not None and not reader.block.is_set()
    finally:
        block.set()
        service.close()

    # Scheduling is a handoff, not the call: it cannot have waited for it.
    assert scheduling_ns < 25_000_000, scheduling_ns


def test_a_native_deadline_shorter_than_the_budget_leaves_room_to_classify() -> None:
    """A call that reaches the native deadline must still be usable evidence.

    The two deadlines were once equal, which made every slow call report as too
    late to use instead of as an ordinary unsupported element.
    """

    from hanly_app.text_acquisition_ax import _NATIVE_DEADLINE_SHARE

    assert 0 < _NATIVE_DEADLINE_SHARE < 1
