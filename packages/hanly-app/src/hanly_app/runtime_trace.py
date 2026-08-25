"""Small, optional runtime tracing seam owned by the desktop application.

Tracing is deliberately not a logging framework. A caller supplies a sink
whose ``emit`` method is expected to be non-blocking; the production boundary
adds monotonic timing and thread identity, keeps values JSON-safe, and treats
the sink as best effort.  Passing ``None`` is the normal disabled path.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from threading import current_thread, get_ident
from time import perf_counter_ns
from typing import Protocol, TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None
TraceFields: TypeAlias = Mapping[str, JSONPrimitive]


class RuntimeTraceSink(Protocol):
    """Non-blocking consumer for one JSON-safe runtime event.

    Implementations must return promptly. The desktop runtime never waits
    for persistence, flushing, or transport, and a failing sink is ignored.
    """

    def emit(self, event: Mapping[str, JSONPrimitive]) -> object:
        """Consume one event without blocking the caller."""


def emit_trace(
    sink: RuntimeTraceSink | None,
    event_kind: str,
    *,
    lookup_request_id: int | None = None,
    hover_request_id: int | None = None,
    **fields: JSONPrimitive,
) -> None:
    """Best-effort emit one timestamped, correlation-safe event.

    The event contains only primitives, and no caller-provided exception text
    or provider data is accepted by this helper.  Sink exceptions are swallowed
    so tracing cannot affect lookup behavior or worker lifecycle.
    """

    if sink is None:
        return
    if not isinstance(event_kind, str) or not event_kind:
        return

    timestamp_ns = perf_counter_ns()
    thread_id = get_ident()
    event: dict[str, JSONPrimitive] = {
        "event_kind": event_kind,
        "timestamp_ns": timestamp_ns,
        "thread_id": thread_id,
        "thread_ident": thread_id,
        "thread_name": current_thread().name,
        "lookup_request_id": lookup_request_id,
        "hover_request_id": hover_request_id,
        # These aliases let a developer-only recorder consume the production
        # sink without importing it into the application package.
        "event": event_kind,
        "monotonic_ns": timestamp_ns,
    }
    # Keep event construction predictable and JSON-safe even if a caller uses
    # a dynamically typed integration to pass an unsupported value.
    for key, value in fields.items():
        supported = value is None or isinstance(value, (str, int, bool)) or (
            isinstance(value, float) and isfinite(value)
        )
        if not isinstance(key, str) or not supported:
            continue
        event[key] = value
    try:
        sink.emit(event)
    except BaseException:
        # Instrumentation must never perturb production behavior, including
        # when a sink has a buggy callback or a closed transport.
        pass


__all__ = ["JSONPrimitive", "RuntimeTraceSink", "TraceFields", "emit_trace"]
