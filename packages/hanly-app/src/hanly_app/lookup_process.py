"""The lookup engine, in a process the shell can throw away.

EasyOCR, Torch, and Kiwi allocate hundreds of megabytes natively and give none
of it back when their objects are destroyed, so the providers live in a child
process. The child owns provider construction, every lookup, and provider
close on one processing thread, which is what keeps SQLite's connection on the
thread that opened it.

The parent keeps everything that decides what a lookup means:
:class:`~hanly_app.lookup_controller.LookupController` still allocates request
IDs and still makes the final currency check before a result is presented, and
:class:`~hanly_app.job_executor.JobExecutor` still bounds work to one running
job plus one latest pending one. Only the worker at the bottom changed: it is
now a proxy that sends an ROI down a pipe instead of calling providers.

Nothing library-specific crosses the boundary. Images travel as bytes and
dimensions, results as the engine's own normalized values, and failures as a
stable error type and message rather than as a foreign exception object.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from queue import Empty, Queue
from time import monotonic
from typing import Any, Literal

from hanly import LookupResult, PixelFormat, Point, ROIImage
from hanly.easyocr_provider import EasyOCRConfig
from hanly.errors import HanlyError, LookupCancelled, ProviderError

from .lookup_controller import LookupController, LookupRequest, ResultDispatcher, ResultHandler
from .process_transport import (
    Message,
    Transport,
    TransportClosed,
    spawn_child,
    stop_process,
)
from .runtime_trace import JSONPrimitive, RuntimeTraceSink

#: How long provider construction may take before the child is given up on.
#: Cold EasyOCR and Kiwi construction is measured in seconds, not minutes; this
#: only catches a child that will never report at all.
READY_TIMEOUT_SECONDS = 300.0

#: Bounded wait for the child to close its providers and SQLite handle.
STOP_TIMEOUT_SECONDS = 10.0

#: How often a blocked lookup rechecks whether its request was superseded, so
#: a cancellation can reach the child between provider stages.
CANCEL_POLL_SECONDS = 0.02

#: Automatic restarts allowed for one active session after an unexpected exit.
DEFAULT_RECOVERY_BUDGET = 1

#: A lookup slower than this is worth a line in the log. Recording every one
#: would turn hover into a motion stream, which diagnostics must never be.
SLOW_LOOKUP_MS = 1500.0

#: The whole of the lookup engine's lifecycle, kept apart from shell and
#: resource readiness: a stopped engine can still accept a new request.
EngineState = Literal["sleeping", "preparing", "ready", "error"]

ChildSpawner = Callable[..., tuple[BaseProcess, Transport]]
DiagnosticReporter = Callable[[str], None]
StateReporter = Callable[[str, str], None]
TraceReplay = Callable[[Mapping[str, JSONPrimitive]], None]


class LookupProcessError(HanlyError):
    """Raised when the lookup child cannot be started, reached, or trusted."""


@dataclass(frozen=True, slots=True)
class LookupSettings:
    """Everything the child needs to build providers, as one spawn value.

    Deliberately not a :class:`~hanly_app.runtime.HanlyRuntime`: that carries a
    ``ResourceManager``, factories, and a diagnostics timeline, none of which
    may cross a spawn boundary. Resource validation has already happened in the
    parent, and only the validated paths and explicit options travel.
    """

    krdict_path: Path
    easyocr: EasyOCRConfig
    confidence_threshold: float | None = None
    skip_flat_rois: bool = False
    #: Whether the child should report per-stage timings back for the
    #: developer-only trace sink. Off is the shipped path and costs nothing.
    trace: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.krdict_path, Path):
            raise TypeError("krdict_path must be a Path")
        if not isinstance(self.easyocr, EasyOCRConfig):
            raise TypeError("easyocr must be an EasyOCRConfig")


class LookupProcess:
    """One lookup child, its pipe, and the generation both belong to.

    A retired or crashed child's generation stops matching, so nothing it says
    afterwards -- a late result, a readiness report, a failure -- is mistaken
    for news about the child that replaced it.
    """

    def __init__(
        self,
        settings: LookupSettings,
        *,
        generation: int,
        spawn: ChildSpawner = spawn_child,
        on_diagnostic: DiagnosticReporter | None = None,
        on_trace: TraceReplay | None = None,
        on_exit: Callable[[int, bool], None] | None = None,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._generation = generation
        self._spawn = spawn
        self._on_diagnostic = on_diagnostic
        self._on_trace = on_trace
        self._on_exit = on_exit
        self._ready_timeout = ready_timeout

        self._lock = threading.RLock()
        self._process: BaseProcess | None = None
        self._transport: Transport | None = None
        self._ready = threading.Event()
        self._ready_ok = False
        self._failure: str | None = None
        self._gone = False
        self._stopping = False
        self._pending: dict[int, list[Message]] = {}
        self._waiters: dict[int, threading.Event] = {}

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def ready(self) -> bool:
        """Whether providers are constructed and the child accepts lookups."""

        with self._lock:
            return self._ready_ok and not self._gone

    def start(self) -> None:
        """Spawn the child and block until its providers are built.

        Called on the executor thread, so blocking here is what makes the
        existing ``worker_ready`` and ``initialization_error`` reporting keep
        meaning what it already meant.
        """

        process, transport = self._spawn(
            lookup_child, self._settings, name="hanly-lookup"
        )
        with self._lock:
            self._process = process
            self._transport = transport
        threading.Thread(
            target=self._read_until_gone,
            args=(transport,),
            name="hanly-lookup-reader",
            daemon=True,
        ).start()

        if not self._ready.wait(self._ready_timeout):
            self.close()
            raise LookupProcessError("the lookup engine did not finish starting in time")
        with self._lock:
            failure = self._failure
            ok = self._ready_ok
        if not ok:
            self.close()
            raise LookupProcessError(failure or "the lookup engine could not start")

    def lookup(self, request: LookupRequest) -> LookupResult:
        """Run one request in the child and return its normalized outcome."""

        transport = self._require_transport()
        waiter = self._register(request.request_id)
        try:
            transport.send(_lookup_message(request))
            self._await_reply(transport, request, waiter)
            return self._reply_value(request.request_id)
        except TransportClosed as error:
            raise LookupProcessError("the lookup engine stopped") from error
        finally:
            with self._lock:
                self._waiters.pop(request.request_id, None)
                self._pending.pop(request.request_id, None)

    def close(self) -> None:
        """Ask the child to close its providers, then make sure it is gone."""

        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            transport = self._transport
            process = self._process

        if transport is not None:
            try:
                transport.send({"kind": "stop"})
            except TransportClosed:
                pass
        if process is not None and not stop_process(process, timeout=STOP_TIMEOUT_SECONDS):
            self._report("The lookup engine process had to be terminated.")
        self._retire()

    def _read_until_gone(self, transport: Transport) -> None:
        """Own the child-to-parent direction, so EOF is never missed."""

        try:
            while True:
                self._receive_one(transport.receive())
        except TransportClosed:
            pass
        finally:
            with self._lock:
                stopping = self._stopping
            self._retire()
            if self._on_exit is not None:
                self._on_exit(self._generation, not stopping)

    def _receive_one(self, message: Message) -> None:
        kind = message.get("kind")
        if kind in {"result", "error"}:
            self._deliver(message)
        elif kind == "ready":
            self._settle(True, None)
        elif kind == "failed":
            self._settle(False, str(message.get("message") or "the lookup engine failed"))
        elif kind == "log":
            self._report(str(message.get("message") or ""))
        elif kind == "trace" and self._on_trace is not None:
            event = message.get("event")
            if isinstance(event, Mapping):
                self._on_trace(event)

    def _settle(self, ok: bool, failure: str | None) -> None:
        with self._lock:
            self._ready_ok = ok
            self._failure = failure
        self._ready.set()

    def _deliver(self, message: Message) -> None:
        identifier = message.get("request_id")
        if not isinstance(identifier, int):
            return
        with self._lock:
            replies = self._pending.get(identifier)
            waiter = self._waiters.get(identifier)
            if replies is not None:
                replies.append(message)
        if waiter is not None:
            waiter.set()

    def _register(self, request_id: int) -> threading.Event:
        waiter = threading.Event()
        with self._lock:
            if self._gone or not self._ready_ok:
                raise LookupProcessError("the lookup engine is not running")
            self._waiters[request_id] = waiter
            self._pending[request_id] = []
        return waiter

    def _await_reply(
        self,
        transport: Transport,
        request: LookupRequest,
        waiter: threading.Event,
    ) -> None:
        """Wait for the child, forwarding a supersession that happens meanwhile.

        Cancellation is resource control, not the correctness gate: the child
        may stop between stages, and whatever comes back still faces the
        controller's currency check before anything is presented.
        """

        forwarded = False
        while not waiter.wait(None if forwarded else CANCEL_POLL_SECONDS):
            if not request.is_cancelled():
                continue
            forwarded = True
            try:
                transport.send({"kind": "cancel", "request_id": request.request_id})
            except TransportClosed:
                return

    def _reply_value(self, request_id: int) -> LookupResult:
        with self._lock:
            replies = list(self._pending.get(request_id) or ())
            gone = self._gone
        if not replies:
            raise LookupProcessError(
                "the lookup engine stopped" if gone else "the lookup engine did not answer"
            )
        reply = replies[0]
        if reply.get("kind") == "error":
            raise _child_error(reply)
        result = reply.get("result")
        if not isinstance(result, LookupResult):
            raise LookupProcessError("the lookup engine returned an unusable result")
        return result

    def _require_transport(self) -> Transport:
        with self._lock:
            transport = self._transport
            if transport is None or self._gone:
                raise LookupProcessError("the lookup engine is not running")
            return transport

    def _retire(self) -> None:
        """Mark this child gone and release everything waiting on it."""

        with self._lock:
            if self._gone:
                return
            self._gone = True
            transport = self._transport
            waiters = tuple(self._waiters.values())
            self._transport = None
        self._ready.set()
        for waiter in waiters:
            waiter.set()
        if transport is not None:
            transport.close()

    def _report(self, message: str) -> None:
        if message and self._on_diagnostic is not None:
            self._on_diagnostic(message)


class LookupEngine:
    """Owns whether the lookup providers are resident, and in which child.

    This is also the :class:`JobExecutor` worker: a lookup asks for a live
    child and gets one, starting it if the current policy left the engine
    asleep. Residency itself is decided elsewhere -- preparing on capture
    start, retiring on pause, expiring after an idle manual session -- and
    this class only carries it out.

    Engine state is exactly sleeping, preparing, ready, or error, plus the
    generation that owns the current child and the last failure. A retired or
    crashed child's generation stops matching, so nothing it reports
    afterwards is mistaken for news about its replacement.
    """

    def __init__(
        self,
        settings: LookupSettings,
        *,
        preload: bool = True,
        spawn: ChildSpawner = spawn_child,
        on_diagnostic: DiagnosticReporter | None = None,
        on_trace: TraceReplay | None = None,
        on_state: StateReporter | None = None,
        recovery_budget: int = DEFAULT_RECOVERY_BUDGET,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._spawn = spawn
        self._on_diagnostic = on_diagnostic
        self._on_trace = on_trace
        self._on_state = on_state
        self._ready_timeout = ready_timeout

        self._lock = threading.RLock()
        # Serializes starts without holding the state lock across the seconds
        # a child takes to build its providers.
        self._start_lock = threading.Lock()
        self._generation = 0
        self._budget = max(0, int(recovery_budget))
        self._blocked = False
        self._closed = False
        self._state: EngineState = "sleeping"
        self._failure: str | None = None
        self._preload = preload
        self._process: LookupProcess | None = None
        self._last_used = monotonic()

    @property
    def state(self) -> EngineState:
        with self._lock:
            return self._state

    @property
    def failure(self) -> str | None:
        """The last provider-construction or exit failure, if there was one."""

        with self._lock:
            return self._failure

    @property
    def generation(self) -> int:
        """Which child is current; a retired one's answers are not news."""

        with self._lock:
            return self._generation

    @property
    def recovery_budget(self) -> int:
        with self._lock:
            return self._budget

    def attach(self) -> LookupEngine:
        """Become the executor's worker, honouring an eager residency policy.

        The executor calls this on its own thread, which is the one place a
        wait for provider construction belongs: never on the UI thread, and
        never so late that a first lookup pays for a policy that asked for
        residency up front.
        """

        if self._preload:
            self._ensure()
        return self

    def set_preload(self, preload: bool) -> None:
        """Record whether a later wake should also be eager. Policy decides."""

        with self._lock:
            self._preload = bool(preload)

    def prepare(self) -> None:
        """Ask for residency without waiting for it."""

        with self._lock:
            if self._closed or (self._process is not None and self._process.ready):
                return
        threading.Thread(
            target=self._prepare_quietly, name="hanly-lookup-prepare", daemon=True
        ).start()

    def retire(self) -> None:
        """Drop the providers now, leaving an engine a later request can wake.

        Invalidating the generation first is what makes this safe during
        preparation: a child that finishes starting afterwards finds itself
        already superseded and closes instead of becoming current.
        """

        with self._lock:
            process = self._process
            self._process = None
            self._generation += 1
            self._failure = None
            already_asleep = self._state == "sleeping"
            self._state = "sleeping"
        if process is not None:
            process.close()
        with self._lock:
            self._last_used = monotonic()
        if not already_asleep:
            self._publish("sleeping", "The lookup engine is not loaded.")

    def reset_recovery_budget(self, budget: int = DEFAULT_RECOVERY_BUDGET) -> None:
        """Give a deliberate activation a fresh automatic-recovery allowance.

        A replacement child reporting ready is deliberately not enough: a crash
        loop would otherwise refill its own budget every time it briefly came up.
        """

        with self._lock:
            self._budget = max(0, int(budget))
            self._blocked = False

    def idle_seconds(self) -> float:
        """How long since a lookup last finished, for an idle-expiry policy."""

        with self._lock:
            return monotonic() - self._last_used

    def __call__(self, item: LookupRequest) -> LookupResult:
        if not isinstance(item, LookupRequest):
            raise TypeError("lookup worker items must be LookupRequest values")
        if item.is_cancelled():
            raise LookupCancelled("lookup was superseded before worker execution")
        process = self._ensure()
        started = monotonic()
        try:
            return process.lookup(item)
        finally:
            # Measured from completion rather than from submission: a cold
            # first lookup takes seconds, and an expiry that started counting
            # before it finished would be counting the wrong thing.
            finished = monotonic()
            with self._lock:
                self._last_used = finished
            elapsed_ms = (finished - started) * 1000
            if elapsed_ms >= SLOW_LOOKUP_MS:
                self._report(f"A lookup took {elapsed_ms:.0f} ms.")

    def close(self) -> None:
        """Retire the current child for good; nothing starts another."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.retire()

    def _prepare_quietly(self) -> None:
        try:
            self._ensure()
        except Exception:
            # The failure is already published as engine state and reported as
            # a diagnostic; a background preparation has nowhere else to raise.
            pass

    def _ensure(self) -> LookupProcess:
        """Return a live child, starting one and waiting if there is none."""

        with self._lock:
            if self._closed:
                raise LookupProcessError("the lookup engine has been shut down")
            if self._blocked:
                raise LookupProcessError(
                    self._failure or "the lookup engine stopped and was not restarted"
                )
            process = self._process
        if process is not None and process.ready:
            return process

        with self._start_lock:
            with self._lock:
                process = self._process
            if process is not None and process.ready:
                return process
            return self._start_now()

    def _start_now(self) -> LookupProcess:
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._state = "preparing"
        self._publish("preparing", "Loading the lookup engine...")

        process = LookupProcess(
            self._settings,
            generation=generation,
            spawn=self._spawn,
            on_diagnostic=self._on_diagnostic,
            on_trace=self._on_trace,
            on_exit=self._child_exited,
            ready_timeout=self._ready_timeout,
        )
        try:
            process.start()
        except BaseException as error:
            self._fail(generation, str(error))
            raise

        stale = None
        with self._lock:
            if generation != self._generation or self._closed:
                stale = process
            else:
                self._process = process
                self._state = "ready"
                self._failure = None
        if stale is not None:
            stale.close()
            raise LookupProcessError("the lookup engine was retired while it was starting")
        self._publish("ready", "Hanly is ready.")
        return process

    def _fail(self, generation: int, message: str) -> None:
        with self._lock:
            if generation != self._generation or self._closed:
                return
            self._process = None
            self._state = "error"
            self._failure = message
        self._publish("error", message)

    def _child_exited(self, generation: int, unexpected: bool) -> None:
        """React once to a child that is gone, and only for the current one."""

        with self._lock:
            if self._closed or generation != self._generation or not unexpected:
                return
            self._process = None
            self._state = "error"
            self._failure = "The lookup engine stopped unexpectedly."
            recoverable = self._budget > 0
            if recoverable:
                self._budget -= 1
            else:
                self._blocked = True
        self._report("The lookup engine stopped unexpectedly.")
        if not recoverable:
            self._publish("error", "The lookup engine stopped and could not be restarted.")
            return
        self._publish("error", "The lookup engine stopped unexpectedly.")
        threading.Thread(
            target=self._prepare_quietly, name="hanly-lookup-recovery", daemon=True
        ).start()

    def _publish(self, state: str, detail: str) -> None:
        if self._on_state is not None:
            self._on_state(state, detail)

    def _report(self, message: str) -> None:
        if self._on_diagnostic is not None:
            self._on_diagnostic(message)


def create_lookup_engine(
    settings: LookupSettings,
    *,
    preload: bool = True,
    trace_sink: RuntimeTraceSink | None = None,
    on_diagnostic: DiagnosticReporter | None = None,
    on_state: StateReporter | None = None,
    spawn: ChildSpawner = spawn_child,
) -> LookupEngine:
    """Build the engine that owns provider residency for one session."""

    replay = _trace_replay(trace_sink)
    return LookupEngine(
        replace(settings, trace=replay is not None),
        preload=preload,
        spawn=spawn,
        on_diagnostic=on_diagnostic,
        on_trace=replay,
        on_state=on_state,
    )


def create_process_lookup_controller(
    engine: LookupEngine,
    on_result: ResultHandler | None = None,
    *,
    on_error: Callable[[LookupRequest, BaseException], None] | None = None,
    on_initialization_error: Callable[[BaseException], None] | None = None,
    result_dispatcher: ResultDispatcher | None = None,
    thread_name: str | None = None,
    trace_sink: RuntimeTraceSink | None = None,
) -> LookupController:
    """Compose the existing bounded controller over a disposable child.

    The controller and its executor are unchanged: request IDs, latest-wins
    submission, and the final currency check all still happen here. What moved
    is only where the pipeline runs.
    """

    return LookupController(
        engine.attach,
        on_result,
        on_error=on_error,
        on_initialization_error=on_initialization_error,
        result_dispatcher=result_dispatcher,
        thread_name=thread_name,
        trace_sink=trace_sink,
    )


def _trace_replay(sink: RuntimeTraceSink | None) -> TraceReplay | None:
    """Replay the child's stage events into the developer sink in the parent."""

    if sink is None:
        return None

    def replay(event: Mapping[str, JSONPrimitive]) -> None:
        try:
            sink.emit(dict(event))
        except BaseException:
            # Instrumentation must never perturb the lookup path, here no more
            # than at the sink's own boundary.
            pass

    return replay


def _lookup_message(request: LookupRequest) -> Message:
    """Describe one request as bytes, dimensions, format, and a local target."""

    image = request.image
    return {
        "kind": "lookup",
        "request_id": request.request_id,
        "hover_request_id": request.hover_request_id,
        "width": image.width,
        "height": image.height,
        "pixel_format": image.pixel_format.value,
        "data": image.data,
        "target_x": request.target.x,
        "target_y": request.target.y,
    }


def _child_error(reply: Message) -> BaseException:
    """Rebuild a stable engine error from the child's type and message.

    The child never pickles the exception object a library raised; an OCR
    backend's own error class has no business being reconstructed in a process
    that does not import it.
    """

    error_type = str(reply.get("error_type") or "HanlyError")
    message = str(reply.get("message") or "the lookup engine failed")
    if error_type == "LookupCancelled":
        return LookupCancelled(message)
    if error_type == "ProviderError":
        return ProviderError(message)
    return LookupProcessError(message)


def _normalized_result(result: LookupResult) -> LookupResult:
    """Replace a foreign error object with the engine's own before sending."""

    error = result.error
    if error is None or type(error) in {HanlyError, ProviderError, LookupCancelled}:
        return result
    return replace(result, error=HanlyError(str(error)))


class _LookupChild:
    """The child half: one reader, one processing thread, one worker."""

    def __init__(self, transport: Transport, settings: LookupSettings) -> None:
        self._transport = transport
        self._settings = settings
        self._jobs: Queue[LookupRequest | None] = Queue()
        self._lock = threading.RLock()
        self._live: dict[int, LookupRequest] = {}
        self._stopping = False

    def run(self) -> None:
        """Read until the parent is gone, with providers on their own thread."""

        processing = threading.Thread(
            target=self._process_jobs, name="hanly-lookup-worker", daemon=False
        )
        processing.start()
        try:
            while True:
                message = self._transport.receive()
                if message.get("kind") == "stop":
                    break
                self._accept(message)
        except TransportClosed:
            # The shell is gone. A lookup child with nobody to answer has
            # nothing left to do.
            pass
        finally:
            self._stop()
            processing.join()
            self._transport.close()

    def _accept(self, message: Message) -> None:
        kind = message.get("kind")
        if kind == "lookup":
            self._submit(message)
        elif kind == "cancel":
            self._cancel(message.get("request_id"))

    def _submit(self, message: Message) -> None:
        try:
            request = _request_from(message)
        except (KeyError, TypeError, ValueError) as error:
            self._send(
                {
                    "kind": "error",
                    "request_id": message.get("request_id"),
                    "error_type": "HanlyError",
                    "message": f"unusable lookup request: {error}",
                }
            )
            return
        with self._lock:
            if self._stopping:
                return
            self._live[request.request_id] = request
        self._jobs.put(request)

    def _cancel(self, request_id: object) -> None:
        if not isinstance(request_id, int):
            return
        with self._lock:
            request = self._live.get(request_id)
        if request is not None:
            request.cancel()

    def _stop(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            live = tuple(self._live.values())
        for request in live:
            request.cancel()
        self._jobs.put(None)

    def _process_jobs(self) -> None:
        """Own provider construction, every lookup, and provider close."""

        worker = self._build_worker()
        if worker is None:
            return
        try:
            while True:
                request = self._next_job()
                if request is None:
                    return
                self._run_one(worker, request)
        finally:
            try:
                worker.close()
            except Exception as error:
                self._send({"kind": "log", "message": f"provider cleanup failed: {error}"})

    def _next_job(self) -> LookupRequest | None:
        while True:
            try:
                return self._jobs.get(timeout=1.0)
            except Empty:
                with self._lock:
                    if self._stopping:
                        return None

    def _build_worker(self) -> Any:
        from .composition import create_lookup_worker_factory

        settings = self._settings
        try:
            from hanly.easyocr_provider import EasyOCRProvider
            from hanly.kiwi_provider import KiwiProvider
            from hanly.krdict_provider import KRDICTProvider

            factory = create_lookup_worker_factory(
                lambda: EasyOCRProvider(config=settings.easyocr),
                KiwiProvider,
                lambda: KRDICTProvider(settings.krdict_path),
                confidence_threshold=settings.confidence_threshold,
                skip_flat_rois=settings.skip_flat_rois,
                trace_sink=_ChildTraceSink(self._transport) if settings.trace else None,
            )
            worker = factory()
        except BaseException as error:
            self._send(
                {"kind": "failed", "message": f"{type(error).__name__}: {error}"}
            )
            return None
        self._send({"kind": "ready"})
        return worker

    def _run_one(self, worker: Any, request: LookupRequest) -> None:
        try:
            result = worker(request)
        except BaseException as error:
            self._send(
                {
                    "kind": "error",
                    "request_id": request.request_id,
                    "error_type": _stable_error_type(error),
                    "message": str(error) or type(error).__name__,
                }
            )
        else:
            self._send(
                {
                    "kind": "result",
                    "request_id": request.request_id,
                    "result": _normalized_result(result),
                }
            )
        finally:
            with self._lock:
                self._live.pop(request.request_id, None)

    def _send(self, message: Message) -> None:
        try:
            self._transport.send(message)
        except TransportClosed:
            # The parent is gone; the reader is already unwinding this child.
            pass


class _ChildTraceSink:
    """Forward the child's stage events to the developer sink in the parent."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def emit(self, event: Mapping[str, JSONPrimitive]) -> object:
        try:
            self._transport.send({"kind": "trace", "event": dict(event)})
        except Exception:
            # Instrumentation must never perturb the lookup path.
            pass
        return None


def _stable_error_type(error: BaseException) -> str:
    """Name an error in terms the parent can rebuild without the library."""

    if isinstance(error, LookupCancelled):
        return "LookupCancelled"
    if isinstance(error, ProviderError):
        return "ProviderError"
    return "HanlyError"


def _request_from(message: Message) -> LookupRequest:
    """Rebuild the request locally, with cancellation state of its own."""

    image = ROIImage(
        width=int(message["width"]),
        height=int(message["height"]),
        pixel_format=PixelFormat(message["pixel_format"]),
        data=bytes(message["data"]),
    )
    hover_request_id = message.get("hover_request_id")
    return LookupRequest(
        int(message["request_id"]),
        image,
        Point(float(message["target_x"]), float(message["target_y"])),
        hover_request_id=hover_request_id if isinstance(hover_request_id, int) else None,
    )


def lookup_child(connection: Connection, settings: LookupSettings) -> None:
    """Child entry point: the only thing in Hanly that imports the OCR stack.

    Importable under ``spawn`` and deliberately narrow. It provisions nothing,
    acknowledges no update, registers no hotkey, and opens no window.
    """

    from .ocr_preload import preload_ocr_runtime

    transport = Transport(connection)
    # Load the native OCR libraries first, while this process's library search
    # path is still the one it started with.
    preload_ocr_runtime(
        on_diagnostic=lambda message: _report_preload(transport, message)
    )
    _LookupChild(transport, settings).run()


def _report_preload(transport: Transport, message: str) -> None:
    try:
        transport.send({"kind": "log", "message": message})
    except TransportClosed:
        pass


__all__ = [
    "CANCEL_POLL_SECONDS",
    "DEFAULT_RECOVERY_BUDGET",
    "READY_TIMEOUT_SECONDS",
    "SLOW_LOOKUP_MS",
    "STOP_TIMEOUT_SECONDS",
    "EngineState",
    "LookupEngine",
    "LookupProcess",
    "LookupProcessError",
    "LookupSettings",
    "create_lookup_engine",
    "create_process_lookup_controller",
    "lookup_child",
]
