"""The Control Center window, in a process the shell can throw away.

Qt WebEngine does not return its memory when the window is destroyed, so the
window lives in a child process instead of in the shell. The canonical
:class:`~hanly_app.control_center.ControlCenterBridge` stays in the parent,
which keeps configuration, permissions, capture selection, updates, and Quit
where they already were; the child only carries the page and a proxy whose
methods are a fixed list of that bridge's public UI operations.

Closing the window ends the child. It never ends the parent, never pauses
capture, and never takes the lookup engine with it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from multiprocessing.process import BaseProcess
from time import monotonic

from .control_center import ControlCenterUnavailable
from .control_center_host import ControlCenterHost
from .process_transport import (
    MAX_CONTROL_MESSAGE_BYTES,
    Message,
    PipeEnd,
    Transport,
    TransportClosed,
    spawn_child,
    stop_process,
)

#: The bridge operations the page may call. The proxy in the child declares
#: exactly these methods and the parent resolves them against this list, so a
#: message can never name something the UI is not allowed to invoke.
CONTROL_CENTER_OPERATIONS: tuple[str, ...] = (
    "check_for_updates",
    "clear_logs",
    "export_diagnostics",
    "get_logs",
    "get_state",
    "grant_permission",
    "install_application_update",
    "install_update",
    "open_release_notes",
    "quit",
    "refresh_permissions",
    "retry_runtime",
    "select_capture_area",
    "set_capture_mode",
    "set_hotkey",
    "set_hover_delay",
    "set_region",
    "set_target",
    "start_capture",
    "stop_capture",
    "update_settings",
)

#: How many page operations may be in flight in the parent at once. The page
#: issues them one at a time; anything past this is a defect, and is refused
#: rather than allowed to accumulate threads.
MAX_OUTSTANDING_OPERATIONS = 8

#: Upper bound on how long the child waits for one reply. Capture selection is
#: deliberately allowed to take minutes, so this only catches a parent that
#: will never answer at all.
CALL_TIMEOUT_SECONDS = 900.0

#: Bounded wait for the window to close before the child is terminated.
CLOSE_TIMEOUT_SECONDS = 10.0

#: Bounded wait for an in-progress open or close before another one is allowed
#: to start. Longer than a close so a reopen waits out the window it replaces
#: rather than racing it.
OWNERSHIP_TIMEOUT_SECONDS = CLOSE_TIMEOUT_SECONDS + 5.0

ChildSpawner = Callable[..., tuple[BaseProcess, Transport]]


class _ChildPhase(Enum):
    """Which ownership transition the one Control Center child is in.

    Spawning and reaping both take real time, and both are reachable from the
    tray, the page, and shutdown at once. Naming the transition is what stops
    two ``show`` calls from each deciding to spawn, and a reopen from starting
    a window while the previous one is still being joined.
    """

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"


@dataclass(frozen=True, slots=True)
class ControlCenterOptions:
    """Window geometry and debug flag, as one value the spawn boundary takes."""

    title: str = "Hanly · Control Center"
    width: int = 1080
    height: int = 760
    debug: bool = False

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Control Center dimensions must be positive")


def bridge_operations(bridge: object) -> dict[str, Callable[..., object]]:
    """Bind the allowlisted operations of one bridge, refusing a partial one.

    The names come from :data:`CONTROL_CENTER_OPERATIONS`, never from the wire,
    and a bridge missing one is a composition error rather than an operation
    that silently does nothing.
    """

    operations: dict[str, Callable[..., object]] = {}
    for name in CONTROL_CENTER_OPERATIONS:
        operation = getattr(bridge, name, None)
        if not callable(operation):
            raise TypeError(f"the Control Center bridge has no {name} operation")
        operations[name] = operation
    return operations


class ControlCenterProcess:
    """Own at most one Control Center child, and the parent half of its pipe.

    Opening while a child is alive focuses that window instead of spawning a
    second one. An unexpected child exit is recorded and nothing else: the
    shell keeps its tray, hotkeys, capture, and popup.
    """

    def __init__(
        self,
        operations: Mapping[str, Callable[..., object]],
        *,
        options: ControlCenterOptions | None = None,
        on_diagnostic: Callable[[str], None] | None = None,
        on_error: Callable[[str, BaseException], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        spawn: ChildSpawner = spawn_child,
    ) -> None:
        for name, seam in (
            ("on_diagnostic", on_diagnostic),
            ("on_error", on_error),
            ("on_closed", on_closed),
        ):
            if seam is not None and not callable(seam):
                raise TypeError(f"{name} must be callable")

        self._operations = dict(operations)
        self._options = options or ControlCenterOptions()
        self._on_diagnostic = on_diagnostic
        self._on_error = on_error
        self._on_closed = on_closed
        self._spawn = spawn

        self._lock = threading.RLock()
        self._settled = threading.Condition(self._lock)
        self._phase = _ChildPhase.IDLE
        self._generation = 0
        self._process: BaseProcess | None = None
        self._transport: Transport | None = None
        self._reader: threading.Thread | None = None
        self._ready = False
        self._outstanding = 0
        self._shutdown = False

    @property
    def running(self) -> bool:
        """Whether a Control Center child currently exists."""

        with self._lock:
            process = self._process
        return process is not None and process.is_alive()

    @property
    def ready(self) -> bool:
        """Whether the live child has reported a window it can actually show."""

        with self._lock:
            return self._ready

    @property
    def generation(self) -> int:
        """How many children this manager has started, for test assertions."""

        with self._lock:
            return self._generation

    def show(self) -> None:
        """Open the Control Center, or bring the existing one forward."""

        focus: Transport | None = None
        with self._lock:
            self._require_open()
            self._wait_for_settled()
            self._require_open()
            if self._phase is _ChildPhase.RUNNING and self._alive():
                focus = self._transport
            if focus is None:
                self._phase = _ChildPhase.STARTING

        if focus is not None:
            self._send(focus, {"kind": "focus"})
            return
        try:
            self._start()
        except BaseException:
            self._settle(_ChildPhase.IDLE)
            raise

    def notify_state_changed(self) -> None:
        """Tell a live window that parent-owned state moved under it."""

        with self._lock:
            transport = self._transport
            alive = self._alive()
        if alive and transport is not None:
            self._send(transport, {"kind": "state"})

    def close(self) -> None:
        """Ask the window to close and wait a bounded time for the child."""

        with self._lock:
            if self._phase is _ChildPhase.CLOSING:
                return
            self._wait_for_settled()
            transport = self._transport
            process = self._process
            generation = self._generation
            if transport is None and process is None:
                return
            self._phase = _ChildPhase.CLOSING
        try:
            if transport is not None:
                self._send(transport, {"kind": "close"})
            if process is not None and not stop_process(process, timeout=CLOSE_TIMEOUT_SECONDS):
                self._report_diagnostic(
                    f"Window {generation} (pid {process.pid}) did not close in "
                    f"{CLOSE_TIMEOUT_SECONDS:.0f}s and had to be terminated."
                )
        finally:
            exit_code = None if process is None else process.exitcode
            self._retire(generation)
            self._report_diagnostic(f"Window {generation} is closed (exit {exit_code}).")

    def shutdown(self) -> None:
        """Close the window for good; later opens are refused."""

        with self._lock:
            self._shutdown = True
        self.close()

    def _require_open(self) -> None:
        if self._shutdown:
            raise ControlCenterUnavailable("Hanly is shutting down")

    def _alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def _wait_for_settled(self) -> None:
        """Wait out an open or close already under way. Call holding the lock."""

        deadline = OWNERSHIP_TIMEOUT_SECONDS
        while self._phase in (_ChildPhase.STARTING, _ChildPhase.CLOSING):
            if not self._settled.wait(deadline):
                raise ControlCenterUnavailable(
                    "the Control Center is still finishing its previous window"
                )

    def _settle(self, phase: _ChildPhase) -> None:
        """End a transition this manager started, unless it already ended."""

        with self._lock:
            if self._phase is _ChildPhase.STARTING:
                self._phase = phase
            self._settled.notify_all()

    def _start(self) -> None:
        try:
            process, transport = self._spawn(
                control_center_child,
                self._options,
                name="hanly-control-center",
                max_bytes=MAX_CONTROL_MESSAGE_BYTES,
            )
        except Exception as error:
            raise ControlCenterUnavailable(
                f"the Control Center window could not be started: {error}"
            ) from error

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._process = process
            self._transport = transport
            self._ready = False
            self._outstanding = 0
            reader = threading.Thread(
                target=self._read_until_gone,
                args=(transport, generation),
                name="hanly-control-center-reader",
                daemon=True,
            )
            self._reader = reader
        self._settle(_ChildPhase.RUNNING)
        reader.start()
        self._report_diagnostic(
            f"Window {generation} started (pid {process.pid})."
        )

    def _read_until_gone(self, transport: Transport, generation: int) -> None:
        """Own the child-to-parent direction for one child's whole lifetime."""

        reason: str | None = f"Window {generation} closed unexpectedly."
        try:
            while True:
                message = transport.receive()
                if not self._is_current(generation):
                    return
                kind = message.get("kind")
                if kind == "ready":
                    self._mark_ready(generation)
                    continue
                if kind == "closing":
                    reason = None
                    continue
                if kind == "failed":
                    reason = None
                    self._report_diagnostic(
                        f"Window {generation} reported a failure: {message.get('message')}"
                    )
                    continue
                if kind == "note":
                    self._report_diagnostic(
                        f"Window {generation}: {message.get('message')}"
                    )
                    continue
                self._handle(transport, generation, message)
        except TransportClosed:
            pass
        except Exception as error:
            # Without this the child keeps a window whose bridge is dead, and
            # every page call waits out the whole call timeout.
            reason = (
                f"Window {generation} lost its connection: "
                f"{type(error).__name__}: {error}"
            )
            self._report_error("Control Center reader", error)
        finally:
            self._child_gone(generation, reason)

    def _mark_ready(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._ready = True
        self._report_diagnostic(f"Window {generation} is showing its page.")

    def _handle(self, transport: Transport, generation: int, message: Message) -> None:
        if message.get("kind") != "call":
            return
        identifier = message.get("id")
        method = message.get("method")
        arguments = message.get("arguments", ())
        if not isinstance(identifier, int) or not isinstance(method, str):
            return
        if method not in self._operations:
            self._send(
                transport,
                _failure(identifier, "ValueError", f"unsupported operation: {method}"),
            )
            return
        if not self._reserve(generation):
            self._send(
                transport,
                _failure(identifier, "RuntimeError", "Hanly is busy; try that again."),
            )
            return

        threading.Thread(
            target=self._run_operation,
            args=(transport, generation, identifier, method, tuple(arguments)),
            name=f"hanly-control-center-{method}",
            daemon=True,
        ).start()

    def _run_operation(
        self,
        transport: Transport,
        generation: int,
        identifier: int,
        method: str,
        arguments: tuple[object, ...],
    ) -> None:
        """Run one page operation off the parent's UI loop and reply once.

        A queued operation is rejected before it runs, not only before it
        replies: a mutation whose window has already been replaced must not
        reach settings, capture, or the lifecycle at all.
        """

        try:
            if not self._is_current(generation):
                return
            try:
                value = self._operations[method](*arguments)
                reply: Message = {"kind": "reply", "id": identifier, "value": value}
            except Exception as error:
                reply = _failure(identifier, type(error).__name__, str(error))
            if self._is_current(generation):
                self._send(transport, reply)
        finally:
            self._release(generation)

    def _child_gone(self, generation: int, reason: str | None) -> None:
        """Retire the child this reader owned, unless ``close`` owns it.

        A close in progress is already joining the process and will retire it,
        so the reader must leave that transition alone rather than opening the
        door for a replacement while the old window is still being reaped.

        EOF only says the pipe is gone. This reaps the process before giving
        ownership up, so a reopen cannot start a window beside one that is
        still exiting. It runs on the reader thread, never the shell's loop.
        """

        with self._lock:
            if generation != self._generation:
                return
            if self._phase is not _ChildPhase.RUNNING:
                return
            self._phase = _ChildPhase.CLOSING
            process = self._process
        if reason is not None:
            self._report_diagnostic(reason)
        try:
            if process is not None and not stop_process(
                process, timeout=CLOSE_TIMEOUT_SECONDS
            ):
                self._report_diagnostic(
                    f"Window {generation} (pid {process.pid}) did not exit in "
                    f"{CLOSE_TIMEOUT_SECONDS:.0f}s and had to be terminated."
                )
        finally:
            self._retire(generation)
        if self._on_closed is not None:
            try:
                self._on_closed()
            except Exception as error:
                self._report_error("Control Center close", error)

    def _retire(self, generation: int) -> None:
        """Detach exactly the generation that ended, and open ownership again."""

        with self._lock:
            if generation != self._generation:
                return
            transport = self._transport
            self._transport = None
            self._process = None
            self._reader = None
            self._ready = False
            self._outstanding = 0
            self._phase = _ChildPhase.IDLE
            self._settled.notify_all()
        if transport is not None:
            transport.close()

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return (
                generation == self._generation
                and self._phase is _ChildPhase.RUNNING
                and self._transport is not None
            )

    def _reserve(self, generation: int) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            if self._outstanding >= MAX_OUTSTANDING_OPERATIONS:
                return False
            self._outstanding += 1
            return True

    def _release(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._outstanding = max(0, self._outstanding - 1)

    def _send(self, transport: Transport, message: Message) -> None:
        try:
            transport.send(message)
        except TransportClosed:
            # The child is gone; its reader is already reporting that.
            pass
        except Exception as error:
            self._report_error("Control Center transport", error)

    def _report_diagnostic(self, message: str) -> None:
        if self._on_diagnostic is not None:
            self._on_diagnostic(message)

    def _report_error(self, stage: str, error: BaseException) -> None:
        if self._on_error is not None:
            self._on_error(stage, error)


def _failure(identifier: int, error_type: str, message: str) -> Message:
    """Build the reply that turns a parent-side exception into a page error."""

    return {
        "kind": "reply",
        "id": identifier,
        "error": {"type": error_type, "message": message},
    }


class ControlCenterProxy:
    """The page's ``window.pywebview.api``, forwarding to the parent bridge.

    Every method here is one of :data:`CONTROL_CENTER_OPERATIONS`, spelled with
    the parameter names the page already passes. pywebview runs each call on a
    thread of its own, so blocking for the parent's reply is safe and keeps the
    child's UI loop free.
    """

    def __init__(self, call: Callable[..., object]) -> None:
        self._call = call

    def get_state(self) -> object:
        return self._call("get_state")

    def get_logs(self) -> object:
        return self._call("get_logs")

    def clear_logs(self) -> object:
        return self._call("clear_logs")

    def export_diagnostics(self) -> object:
        return self._call("export_diagnostics")

    def start_capture(self) -> object:
        return self._call("start_capture")

    def stop_capture(self) -> object:
        return self._call("stop_capture")

    def set_capture_mode(self, mode: object) -> object:
        return self._call("set_capture_mode", mode)

    def set_target(self, target: object) -> object:
        return self._call("set_target", target)

    def set_region(self, region: object) -> object:
        return self._call("set_region", region)

    def select_capture_area(self) -> object:
        return self._call("select_capture_area")

    def set_hover_delay(self, delay_ms: object) -> object:
        return self._call("set_hover_delay", delay_ms)

    def set_hotkey(self, hotkey: object) -> object:
        return self._call("set_hotkey", hotkey)

    def update_settings(self, changes: object) -> object:
        return self._call("update_settings", changes)

    def grant_permission(self, permission: object) -> object:
        return self._call("grant_permission", permission)

    def refresh_permissions(self) -> object:
        return self._call("refresh_permissions")

    def retry_runtime(self) -> object:
        return self._call("retry_runtime")

    def quit(self) -> object:
        return self._call("quit")

    def check_for_updates(self) -> object:
        return self._call("check_for_updates")

    def install_update(self, resource_id: object = None) -> object:
        return self._call("install_update", resource_id)

    def install_application_update(self) -> object:
        return self._call("install_application_update")

    def open_release_notes(self) -> object:
        return self._call("open_release_notes")


class _ControlCenterChild:
    """The child half: one window, one reader, and replies waiting by id.

    The reader starts before the window exists, so every parent request is
    written against three phases rather than one: before the host is ready a
    focus is remembered and a close is obeyed as soon as there is something to
    close, and after the window is gone both are ignored.
    """

    def __init__(self, transport: Transport, options: ControlCenterOptions) -> None:
        self._transport = transport
        self._host = ControlCenterHost(
            ControlCenterProxy(self.call),
            title=options.title,
            width=options.width,
            height=options.height,
            debug=options.debug,
        )
        self._lock = threading.RLock()
        self._next_id = 1
        self._replies: dict[int, list[Message]] = {}
        self._events: dict[int, threading.Event] = {}
        self._refreshing = False
        self._ready = False
        self._closing = False
        self._pending_focus = False
        self._reader: threading.Thread | None = None

    def run(self) -> None:
        """Run the window's loop, and report the close on the way out."""

        reader = threading.Thread(
            target=self._read_until_gone, name="hanly-control-center-parent", daemon=True
        )
        with self._lock:
            self._reader = reader
        reader.start()
        try:
            self._host.run(on_started=self._host_ready)
        finally:
            self._release_waiters()
            try:
                self._transport.send({"kind": "closing"})
            except TransportClosed:
                pass
            self._transport.close()

    def _host_ready(self) -> None:
        """Apply what the parent asked for before there was a window.

        pywebview runs this once the loop is up, which is the first moment
        ``show`` and ``destroy`` mean anything. A close that arrived during
        startup is honoured here rather than leaving an orphan window.
        """

        with self._lock:
            self._ready = True
            closing = self._closing
            focus = self._pending_focus
            self._pending_focus = False

        self._notify_parent({"kind": "ready"})
        if closing:
            self._host.close()
            return
        if focus:
            self._show_window()

    def _request_focus(self) -> None:
        with self._lock:
            if self._closing:
                return
            if not self._ready:
                self._pending_focus = True
                return
        self._show_window()

    def _request_close(self) -> None:
        with self._lock:
            self._closing = True
            self._pending_focus = False
            ready = self._ready
        if ready:
            self._host.close()

    def _show_window(self) -> None:
        """Bring the window forward, tolerating one destroyed underneath us."""

        try:
            self._host.show()
        except ControlCenterUnavailable:
            pass

    def _notify_parent(self, message: Message) -> None:
        try:
            self._transport.send(message)
        except TransportClosed:
            pass

    def call(self, method: str, *arguments: object) -> object:
        """Ask the parent to run one bridge operation and return its answer."""

        identifier = self._register()
        try:
            self._transport.send(
                {"kind": "call", "id": identifier, "method": method, "arguments": arguments}
            )
            return self._await_reply(identifier, method)
        except TransportClosed as error:
            raise RuntimeError("Hanly is no longer available.") from error
        finally:
            with self._lock:
                self._events.pop(identifier, None)
                self._replies.pop(identifier, None)

    def _register(self) -> int:
        with self._lock:
            identifier = self._next_id
            self._next_id += 1
            self._events[identifier] = threading.Event()
            self._replies[identifier] = []
            return identifier

    def _await_reply(self, identifier: int, method: str) -> object:
        """Wait for one reply, naming the boundary if the wait runs out.

        A timeout used to arrive as one unattributed sentence for any of the
        twenty-one allowlisted operations, which said nothing about where the
        answer stopped. The operation, its id, and whether the reader is still
        alive are the three facts that separate a wedged parent from a
        connection that has already gone.
        """

        with self._lock:
            event = self._events[identifier]
        started = monotonic()
        if not event.wait(CALL_TIMEOUT_SECONDS):
            waited = monotonic() - started
            connected = "connected" if self._reader_alive() else "disconnected"
            self._notify_parent(
                {
                    "kind": "note",
                    "message": (
                        f"{method} (call {identifier}) had no answer after "
                        f"{waited:.0f}s; the window is {connected}."
                    ),
                }
            )
            raise RuntimeError(
                f"Hanly did not answer in time. ({method} waited {waited:.0f}s)"
            )
        with self._lock:
            replies = list(self._replies.get(identifier) or ())
        if not replies:
            raise RuntimeError("Hanly closed before answering.")
        return _value_of(replies[0])

    def _reader_alive(self) -> bool:
        with self._lock:
            reader = self._reader
        return reader is not None and reader.is_alive()

    def _read_until_gone(self) -> None:
        try:
            while True:
                self._receive_one(self._transport.receive())
        except TransportClosed:
            pass
        except BaseException as error:  # noqa: BLE001 - told to the parent, then out
            # Losing this thread strands every page call for the whole call
            # timeout, so a fault becomes a terminal child failure instead.
            self._notify_parent(
                {"kind": "failed", "message": f"{type(error).__name__}: {error}"}
            )
        finally:
            self._release_waiters()
            # The parent is gone, or asked for this window to close. Either way
            # this process has nothing left to show.
            self._request_close()

    def _receive_one(self, message: Message) -> None:
        kind = message.get("kind")
        if kind == "reply":
            self._deliver(message)
        elif kind == "focus":
            self._request_focus()
        elif kind == "state":
            self._refresh_page()
        elif kind == "close":
            self._request_close()

    def _deliver(self, message: Message) -> None:
        identifier = message.get("id")
        if not isinstance(identifier, int):
            return
        with self._lock:
            waiting = self._replies.get(identifier)
            event = self._events.get(identifier)
            if waiting is not None:
                waiting.append(message)
        if event is not None:
            event.set()

    def _refresh_page(self) -> None:
        """Nudge the page on a thread of its own, coalescing repeats.

        Evaluating a script waits for the page's answer, and the reader must
        stay free to take cancellation, replies, and EOF while it does. A push
        that arrives while one is already running is dropped rather than
        queued: they all ask the page for the same thing.
        """

        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True

        def refresh() -> None:
            try:
                self._host.evaluate("window.hanlyRefresh && window.hanlyRefresh();")
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=refresh, name="hanly-control-center-refresh", daemon=True).start()

    def _release_waiters(self) -> None:
        with self._lock:
            events = tuple(self._events.values())
        for event in events:
            event.set()


def _value_of(reply: Message) -> object:
    """Turn one reply into a return value, or the page's error."""

    error = reply.get("error")
    if isinstance(error, Mapping):
        raise RuntimeError(str(error.get("message") or "Hanly could not complete that."))
    return reply.get("value")


def control_center_child(connection: PipeEnd, options: ControlCenterOptions) -> None:
    """Child entry point: the only thing in Hanly that imports Qt WebEngine.

    Importable under ``spawn`` and deliberately narrow: it prepares WebEngine,
    shows the window, and exits. It does no first-run provisioning, no update
    acknowledgement, no hotkey registration, and starts no second runtime.
    """

    transport = Transport(connection, max_bytes=MAX_CONTROL_MESSAGE_BYTES)
    try:
        _ControlCenterChild(transport, options).run()
    except BaseException as error:  # noqa: BLE001 - reported to the parent, then out
        try:
            transport.send({"kind": "failed", "message": f"{type(error).__name__}: {error}"})
        except TransportClosed:
            pass
        transport.close()
        raise


__all__ = [
    "CALL_TIMEOUT_SECONDS",
    "CONTROL_CENTER_OPERATIONS",
    "MAX_OUTSTANDING_OPERATIONS",
    "OWNERSHIP_TIMEOUT_SECONDS",
    "ControlCenterOptions",
    "ControlCenterProcess",
    "ControlCenterProxy",
    "bridge_operations",
    "control_center_child",
]
