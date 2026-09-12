"""The shell's half of the Control Center: one child, an allowlist, and exits.

These drive the manager against a real pipe and a fake process, so the races
that matter -- a second open, an unknown operation, a refused flood, a child
that dies on its own -- are deterministic rather than timing-dependent.
"""

from __future__ import annotations

import inspect
import multiprocessing
import threading
from typing import Any

import pytest
from hanly_app.control_center import ControlCenterBridge, ControlCenterUnavailable
from hanly_app.control_center_process import (
    CONTROL_CENTER_OPERATIONS,
    MAX_OUTSTANDING_OPERATIONS,
    ControlCenterOptions,
    ControlCenterProcess,
    ControlCenterProxy,
    _ControlCenterChild,
    bridge_operations,
)
from hanly_app.process_transport import (
    MAX_CONTROL_MESSAGE_BYTES,
    MessageTooLarge,
    Transport,
    TransportClosed,
)

#: Bounded so a marshalling regression fails the test instead of hanging it.
_WAIT_SECONDS = 5.0


class _FakeProcess:
    """Enough of a child process to drive the manager's lifecycle decisions."""

    def __init__(self) -> None:
        self.alive = True
        self.joined: list[float | None] = []
        self.terminated = False

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        self.joined.append(timeout)

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def kill(self) -> None:
        self.alive = False


class _Child:
    """The other end of the pipe, standing in for the window process."""

    def __init__(self) -> None:
        parent_end, child_end = multiprocessing.Pipe(duplex=True)
        self.process = _FakeProcess()
        self.parent = Transport(parent_end, max_bytes=MAX_CONTROL_MESSAGE_BYTES)
        self.transport = Transport(child_end, max_bytes=MAX_CONTROL_MESSAGE_BYTES)
        self.spawned = 0

    def spawn(self, _target: Any, *_arguments: Any, **_keywords: Any) -> Any:
        self.spawned += 1
        return self.process, self.parent

    def call(self, method: str, *arguments: object, identifier: int = 1) -> dict[str, Any]:
        self.transport.send(
            {"kind": "call", "id": identifier, "method": method, "arguments": arguments}
        )
        return dict(self.transport.receive())

    def die(self) -> None:
        """Close the child end, which is the EOF a crashed window produces."""

        self.process.alive = False
        self.transport.close()


def _manager(child: _Child, **options: Any) -> ControlCenterProcess:
    bridge = ControlCenterBridge()
    return ControlCenterProcess(bridge_operations(bridge), spawn=child.spawn, **options)


def test_the_proxy_exposes_exactly_the_allowlisted_bridge_operations() -> None:
    """The page can only ask for what this list names, and the parent resolves
    a message against the same list rather than against the bridge object."""

    exposed = sorted(
        name
        for name, _member in inspect.getmembers(ControlCenterProxy, inspect.isfunction)
        if not name.startswith("_")
    )

    assert exposed == sorted(CONTROL_CENTER_OPERATIONS)
    assert sorted(bridge_operations(ControlCenterBridge())) == exposed


def test_a_bridge_missing_an_operation_is_a_composition_error() -> None:
    class Partial:
        def get_state(self) -> dict[str, object]:
            return {}

    with pytest.raises(TypeError, match="check_for_updates"):
        bridge_operations(Partial())


def test_opening_twice_focuses_the_existing_window() -> None:
    child = _Child()
    manager = _manager(child)

    manager.show()
    manager.show()

    assert child.spawned == 1
    assert manager.generation == 1
    assert dict(child.transport.receive()) == {"kind": "focus"}


def test_the_page_gets_an_answer_from_the_parent_owned_bridge() -> None:
    child = _Child()
    manager = _manager(child)
    manager.show()

    reply = child.call("get_state")

    assert reply["kind"] == "reply"
    assert reply["id"] == 1
    assert isinstance(reply["value"], dict)
    assert "config" in reply["value"]


def test_an_operation_outside_the_allowlist_is_refused() -> None:
    child = _Child()
    manager = _manager(child)
    manager.show()

    reply = child.call("__class__")

    assert reply["error"]["type"] == "ValueError"
    assert "__class__" in reply["error"]["message"]


def test_a_failing_operation_comes_back_as_a_page_error() -> None:
    child = _Child()
    manager = _manager(child)
    manager.show()

    reply = child.call("set_hotkey", "not a hotkey at all")

    assert reply["id"] == 1
    assert reply["error"]["type"] == "ValueError"
    assert "hotkey" in reply["error"]["message"]


def test_outstanding_operations_are_bounded_rather_than_queued() -> None:
    """The page issues one at a time; a flood is a defect, and threads for it
    would be the parent's problem rather than the page's."""

    child = _Child()
    release = threading.Event()
    entered = threading.Semaphore(0)

    def blocking() -> str:
        entered.release()
        release.wait(_WAIT_SECONDS)
        return "done"

    manager = ControlCenterProcess(
        {name: blocking for name in CONTROL_CENTER_OPERATIONS}, spawn=child.spawn
    )
    manager.show()
    try:
        for identifier in range(1, MAX_OUTSTANDING_OPERATIONS + 1):
            child.transport.send(
                {"kind": "call", "id": identifier, "method": "get_state", "arguments": ()}
            )
            assert entered.acquire(timeout=_WAIT_SECONDS)

        refused = child.call("get_state", identifier=99)
    finally:
        release.set()

    assert refused["id"] == 99
    assert refused["error"]["type"] == "RuntimeError"
    assert "busy" in refused["error"]["message"]


def test_a_window_that_dies_retires_the_child_and_tells_the_shell() -> None:
    child = _Child()
    closed = threading.Event()
    manager = _manager(child, on_closed=closed.set)
    manager.show()

    child.die()

    assert closed.wait(_WAIT_SECONDS)
    assert manager.running is False


def test_reopening_after_a_close_starts_a_fresh_child() -> None:
    child = _Child()
    manager = _manager(child)
    manager.show()
    child.die()

    replacement = _Child()
    manager._spawn = replacement.spawn  # the next window is a new process
    manager.show()

    assert manager.generation == 2
    assert replacement.spawned == 1


def test_shutdown_refuses_to_open_the_window_again() -> None:
    child = _Child()
    manager = _manager(child)
    manager.shutdown()

    with pytest.raises(ControlCenterUnavailable, match="shutting down"):
        manager.show()


def test_a_state_change_is_pushed_only_while_a_window_exists() -> None:
    child = _Child()
    manager = _manager(child)

    manager.notify_state_changed()
    manager.show()
    manager.notify_state_changed()

    assert dict(child.transport.receive()) == {"kind": "state"}


def test_an_oversized_message_is_refused_before_it_reaches_the_pipe() -> None:
    parent_end, _child_end = multiprocessing.Pipe(duplex=True)
    transport = Transport(parent_end, max_bytes=64)

    with pytest.raises(MessageTooLarge):
        transport.send({"kind": "call", "arguments": ["x" * 1024]})


def test_a_transport_that_is_open_never_disguises_a_type_error_as_a_close() -> None:
    """Only a close landing mid-call may be read as the pipe going away; a
    caller's own type error has to surface as itself."""

    parent_end, _child_end = multiprocessing.Pipe(duplex=True)
    transport = Transport(parent_end)

    with pytest.raises(TypeError):
        transport.poll("soon")  # type: ignore[arg-type]

    transport.close()


def test_closing_a_transport_releases_a_reader_waiting_on_it() -> None:
    parent_end, _child_end = multiprocessing.Pipe(duplex=True)
    transport = Transport(parent_end)
    failures: list[BaseException] = []
    started = threading.Event()

    def read() -> None:
        started.set()
        try:
            transport.receive()
        except TransportClosed as error:
            failures.append(error)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    assert started.wait(_WAIT_SECONDS)
    transport.close()
    reader.join(_WAIT_SECONDS)

    assert not reader.is_alive()
    assert len(failures) == 1


def test_closing_a_transport_reaches_the_other_end_despite_a_blocked_reader() -> None:
    """A reader still waiting must not hold the pipe open behind the close.

    On POSIX that reader owns the open file description, so a close that only
    drops this end's descriptor would leave the peer waiting for an EOF that
    never comes -- which is how a retired child becomes an orphan.
    """

    parent_end, child_end = multiprocessing.Pipe(duplex=True)
    parent = Transport(parent_end)
    child = Transport(child_end)

    waiting = threading.Event()

    def read() -> None:
        waiting.set()
        try:
            parent.receive()
        except TransportClosed:
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    assert waiting.wait(_WAIT_SECONDS)
    parent.close()

    with pytest.raises(TransportClosed):
        child.receive()
    reader.join(_WAIT_SECONDS)
    assert not reader.is_alive()
    child.close()


class _FakeHost:
    """A window that records what was asked of it, and when it existed."""

    def __init__(self, *, fail_before_ready: bool = True) -> None:
        self.ready = False
        self.fail_before_ready = fail_before_ready
        self.shown = 0
        self.closed = 0

    def show(self) -> None:
        if self.fail_before_ready and not self.ready:
            raise ControlCenterUnavailable("the Control Center window is not available")
        self.shown += 1

    def close(self) -> None:
        self.closed += 1

    def evaluate(self, _script: str) -> None:
        return None


def _child_half(host: _FakeHost) -> tuple[_ControlCenterChild, Transport]:
    """Build the child half against a fake window and a real pipe."""

    parent_end, child_end = multiprocessing.Pipe(duplex=True)
    child = _ControlCenterChild(
        Transport(child_end, max_bytes=MAX_CONTROL_MESSAGE_BYTES), ControlCenterOptions()
    )
    child._host = host  # type: ignore[assignment]
    return child, Transport(parent_end, max_bytes=MAX_CONTROL_MESSAGE_BYTES)


def test_focus_before_the_window_exists_is_deferred_rather_than_fatal() -> None:
    """The reader starts before the host does, so an early focus must not be
    the exception that kills the only thread answering the page."""

    host = _FakeHost()
    child, _parent = _child_half(host)

    child._receive_one({"kind": "focus"})
    assert host.shown == 0

    host.ready = True
    child._host_ready()

    assert host.shown == 1


def test_a_close_during_startup_does_not_leave_an_orphan_window() -> None:
    host = _FakeHost()
    child, _parent = _child_half(host)

    child._receive_one({"kind": "close"})
    assert host.closed == 0

    host.ready = True
    child._host_ready()

    assert host.closed == 1
    assert host.shown == 0


def test_a_reader_fault_fails_the_page_calls_instead_of_stranding_them() -> None:
    """A dead reader used to leave every call waiting out the whole timeout."""

    host = _FakeHost()
    child, parent = _child_half(host)
    host.ready = True
    child._host_ready()
    assert dict(parent.receive()) == {"kind": "ready"}

    failures: list[str] = []

    def call() -> None:
        try:
            child.call("get_state")
        except RuntimeError as error:
            failures.append(str(error))

    caller = threading.Thread(target=call, daemon=True)
    caller.start()
    assert dict(parent.receive())["method"] == "get_state"

    child._transport.close()
    child._read_until_gone()
    caller.join(_WAIT_SECONDS)

    assert failures == ["Hanly closed before answering."]


def test_two_simultaneous_opens_start_one_child() -> None:
    """Both callers see no window and would both have decided to spawn."""

    child = _Child()
    manager = _manager(child)
    barrier = threading.Barrier(2)

    def open_it() -> None:
        barrier.wait(_WAIT_SECONDS)
        manager.show()

    openers = [threading.Thread(target=open_it, daemon=True) for _ in range(2)]
    for opener in openers:
        opener.start()
    for opener in openers:
        opener.join(_WAIT_SECONDS)

    assert child.spawned == 1
    assert manager.generation == 1


def test_a_retired_generation_cannot_detach_its_replacement() -> None:
    """The old reader's cleanup runs late; it must not take the new window."""

    first = _Child()
    manager = _manager(first)
    manager.show()
    first.die()

    replacement = _Child()
    manager._spawn = replacement.spawn
    manager.show()
    assert manager.generation == 2

    manager._child_gone(1, "The Control Center window closed unexpectedly.")
    manager._retire(1)

    assert manager.running is True
    assert manager.generation == 2


def test_an_operation_from_a_replaced_window_neither_runs_nor_takes_capacity() -> None:
    child = _Child()
    calls: list[str] = []

    def record() -> str:
        calls.append("ran")
        return "done"

    manager = ControlCenterProcess(
        {name: record for name in CONTROL_CENTER_OPERATIONS}, spawn=child.spawn
    )
    manager.show()
    stale = manager.generation
    manager._generation += 1  # a replacement window took over

    manager._run_operation(child.parent, stale, 7, "get_state", ())

    assert calls == []
    assert manager._outstanding == 0
