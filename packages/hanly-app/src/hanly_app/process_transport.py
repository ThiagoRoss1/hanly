"""Messaging between Hanly's persistent shell and its optional child processes.

Hanly's heavy parts — Qt WebEngine and the OCR/morphology/dictionary providers
— do not give their memory back when their objects are destroyed, so each one
lives in a child process the shell can retire. This module owns the one way
those processes talk: an inherited duplex ``Pipe``, explicit pickling so every
message has a checked size, one reader per direction, and serialized sends.

There is deliberately no listening socket, no method dispatch by name from the
wire, and no shell command line: both ends are Hanly, started by Hanly.
"""

from __future__ import annotations

import os
import pickle
import socket
import sys
import threading
from collections.abc import Callable, Mapping
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any

#: Ceiling for one message. A default ROI is 200x100 RGB, about 60 KB, and an
#: operator-chosen ``--roi`` stays far below this; anything larger is a defect
#: rather than a lookup, and is refused instead of being allocated.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

#: The Control Center carries settings snapshots and log records, never images.
MAX_CONTROL_MESSAGE_BYTES = 4 * 1024 * 1024

#: How a pipe reports that this end, or the other one, is gone.
_CLOSED_ERRORS = (EOFError, OSError, ValueError)

if sys.platform == "win32":
    from multiprocessing.connection import PipeConnection

    #: What ``Pipe`` hands back. Windows names its end differently, and a
    #: signature written for one platform's name rejects the other's.
    PipeEnd = Connection | PipeConnection
else:
    PipeEnd = Connection

Message = Mapping[str, Any]

#: A child entry point: it receives its end of the pipe plus one plain value.
ChildTarget = Callable[..., None]


class TransportClosed(RuntimeError):
    """Raised when the other end is gone, or this end has been closed.

    EOF is the protocol's only end-of-life signal, so both a normal child exit
    and a crash arrive here; the caller decides which one it was.
    """


class MessageTooLarge(ValueError):
    """Raised before an oversized message is written to the pipe."""


class Transport:
    """One end of a parent/child pipe, with a checked size on every message.

    Sends are serialized so two threads cannot interleave halves of a message.
    Receives are not: exactly one reader thread owns each direction, which is
    what lets a reader keep taking cancellation and EOF while provider code
    runs on another thread.
    """

    def __init__(
        self,
        connection: PipeEnd,
        *,
        max_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        self._connection = connection
        self._max_bytes = max_bytes
        self._send_lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def send(self, message: Message) -> None:
        """Write one message, refusing an oversized payload before the pipe."""

        payload = pickle.dumps(dict(message), protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > self._max_bytes:
            raise MessageTooLarge(
                f"message of {len(payload)} bytes exceeds the {self._max_bytes} byte limit"
            )
        with self._send_lock:
            if self._closed:
                raise TransportClosed("transport is closed")
            try:
                self._connection.send_bytes(payload)
            except _CLOSED_ERRORS as error:
                raise TransportClosed(f"transport send failed: {error}") from error
            except TypeError as error:
                raise self._closed_mid_call("send", error) from error

    def receive(self) -> Message:
        """Block until one message arrives, or the other end is gone."""

        try:
            payload = self._connection.recv_bytes(maxlength=self._max_bytes)
        except _CLOSED_ERRORS as error:
            raise TransportClosed(f"transport receive failed: {error}") from error
        except TypeError as error:
            raise self._closed_mid_call("receive", error) from error
        return _decoded(payload)

    def poll(self, timeout: float | None = None) -> bool:
        """Return whether a message is already waiting to be received."""

        try:
            return bool(self._connection.poll(timeout))
        except _CLOSED_ERRORS as error:
            raise TransportClosed(f"transport poll failed: {error}") from error
        except TypeError as error:
            raise self._closed_mid_call("poll", error) from error

    def _closed_mid_call(self, action: str, error: TypeError) -> TransportClosed:
        """Translate the one ``TypeError`` a close landing mid-call produces.

        CPython reads the connection's handle without holding a lock, so a
        close between the closed check and the read leaves the read with a
        handle that has just become ``None``. That is this end going away.
        Every other ``TypeError`` is a defect and is re-raised untouched.
        """

        if not self._closed:
            raise error
        return TransportClosed(f"transport {action} failed: {error}")

    def close(self) -> None:
        """Close this end, releasing a reader blocked in :meth:`receive`."""

        with self._send_lock:
            if self._closed:
                return
            self._closed = True

        _release_reader(self._connection)
        try:
            self._connection.close()
        except OSError:
            # The pipe is already unusable, which is the state close() wanted.
            pass


def _release_reader(connection: PipeEnd) -> None:
    """Wake whatever thread is blocked reading ``connection``, before it closes.

    Closing the handle is enough on Windows, where it cancels the pending read.
    POSIX leaves that reader waiting on the open file description, and a waiting
    reader keeps the description open, so the other end never reaches EOF
    either — the shutdown below is what ends both waits. A duplex ``Pipe`` is a
    socketpair there, which is what makes a shutdown possible at all.
    """

    if sys.platform == "win32":
        return

    try:
        duplicate = os.dup(connection.fileno())
    except (OSError, ValueError):
        return
    try:
        end = socket.socket(fileno=duplicate)
    except OSError:
        # Not a socket, so there is nothing to shut down; close alone must do.
        os.close(duplicate)
        return
    with end:
        try:
            end.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _decoded(payload: bytes) -> Message:
    """Turn one received frame into a mapping, rejecting anything else.

    Both ends are Hanly, but a truncated or corrupt frame must fail as a
    transport error rather than as an attribute error three layers up.
    """

    try:
        message = pickle.loads(payload)
    except Exception as error:
        raise TransportClosed(f"transport received an undecodable message: {error}") from error
    if not isinstance(message, Mapping):
        raise TransportClosed("transport received a message that is not a mapping")
    return message


def spawn_child(
    target: ChildTarget,
    *arguments: object,
    name: str,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> tuple[BaseProcess, Transport]:
    """Start one child on the spawn context and return its process and pipe.

    ``spawn`` is explicit rather than inherited from the platform default: the
    child must start from a clean interpreter that imports only its own role,
    and a forked copy of a Qt process is not one. The child is daemonic so a
    parent that dies without shutting down cannot leave it running.
    """

    context = get_context("spawn")
    parent_end, child_end = context.Pipe(duplex=True)
    process = context.Process(
        target=target,
        args=(child_end, *arguments),
        name=name,
        daemon=True,
    )
    try:
        process.start()
    except BaseException:
        parent_end.close()
        child_end.close()
        raise
    finally:
        # The parent holding a copy of the child's end would keep EOF from ever
        # arriving when the child exits. Closed directly rather than through a
        # Transport: the child shares this file description, and a transport
        # close shuts the connection down for both of them.
        child_end.close()
    return process, Transport(parent_end, max_bytes=max_bytes)


def stop_process(
    process: BaseProcess,
    *,
    timeout: float,
    kill_timeout: float = 2.0,
) -> bool:
    """Join a child, escalating to terminate and kill so exit stays bounded.

    Returns whether the child is gone. Shutdown must not depend on a child
    choosing to cooperate, and a stuck OCR call is exactly the case where it
    will not.
    """

    process.join(timeout)
    if not process.is_alive():
        return True

    process.terminate()
    process.join(kill_timeout)
    if not process.is_alive():
        return True

    kill = getattr(process, "kill", None)
    if callable(kill):
        kill()
        process.join(kill_timeout)
    return not process.is_alive()


__all__ = [
    "MAX_CONTROL_MESSAGE_BYTES",
    "MAX_MESSAGE_BYTES",
    "ChildTarget",
    "Message",
    "MessageTooLarge",
    "PipeEnd",
    "Transport",
    "TransportClosed",
    "spawn_child",
    "stop_process",
]
