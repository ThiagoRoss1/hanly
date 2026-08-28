"""Human-operated benchmark over the real development hover path.

Importing this module is safe and does not construct Qt, listeners, capture, or
providers.  Those dependencies are imported lazily by :func:`run_live_hover`,
which is invoked only by the explicit ``live-hover`` command.
"""

from __future__ import annotations

import json
import queue
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Protocol, cast

from .live_telemetry import (
    LiveResourceSampler,
    LiveSummary,
    LiveTraceRecorder,
    ScenarioPhaseController,
    SessionPrivacy,
)
from .metadata import build_metadata


class _Listener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...


MarkerListenerFactory = Callable[[Mapping[str, Callable[[], None]]], _Listener]


class RuntimeTraceAdapter:
    """Add phase/privacy data and derive request-correlated perceived timing."""

    def __init__(
        self,
        recorder: LiveTraceRecorder,
        phases: ScenarioPhaseController,
        privacy: SessionPrivacy,
        *,
        retain_text: bool = False,
    ) -> None:
        self._recorder = recorder
        self._phases = phases
        self._privacy = privacy
        self._retain_text = retain_text
        self.retain_text = retain_text
        self._lock = threading.Lock()
        self._hover_started: dict[int, int] = {}
        self._lookup_to_hover: dict[int, int] = {}
        self._dispatch_started: dict[int, int] = {}

    def emit(self, event: Mapping[str, object]) -> bool:
        """Consume the production sink contract without blocking on I/O."""

        event_name = event.get("event", event.get("event_kind"))
        if not isinstance(event_name, str):
            return False
        timestamp = event.get("monotonic_ns", event.get("timestamp_ns"))
        observed_ns = (
            int(timestamp)
            if isinstance(timestamp, int) and not isinstance(timestamp, bool)
            else time.perf_counter_ns()
        )
        raw_fields = {
            str(key): value
            for key, value in event.items()
            if key
            not in {
                "event",
                "event_kind",
                "monotonic_ns",
                "timestamp_ns",
            }
        }
        fields = self._privacy.redact(raw_fields, retain_text=self._retain_text)
        fields["phase"] = self._phases.current

        hover_id = _integer_id(fields.get("hover_request_id"))
        lookup_id = _integer_id(fields.get("lookup_request_id"))
        self._add_stage_classification(event_name, fields)
        if self._lock.acquire(blocking=False):
            try:
                if event_name == "hover_mouse_opportunity" and hover_id is not None:
                    self._hover_started[hover_id] = observed_ns
                elif event_name == "hover_stable_fire" and hover_id is not None:
                    started = self._hover_started.get(hover_id)
                    if started is not None:
                        fields["dwell_duration_ns"] = max(0, observed_ns - started)
                elif event_name == "hover_submission":
                    if hover_id is not None and lookup_id is not None:
                        self._lookup_to_hover[lookup_id] = hover_id
                elif event_name == "lookup_dispatch_queued" and lookup_id is not None:
                    self._dispatch_started[lookup_id] = observed_ns
                elif event_name == "popup_visible" and lookup_id is not None:
                    correlated_hover = self._lookup_to_hover.get(lookup_id)
                    if correlated_hover is not None:
                        fields["hover_request_id"] = correlated_hover
                        started = self._hover_started.get(correlated_hover)
                        if started is not None:
                            fields["hover_to_visible_popup_ns"] = max(
                                0, observed_ns - started
                            )
                    dispatched = self._dispatch_started.get(lookup_id)
                    if dispatched is not None:
                        fields["ui_dispatch_to_popup_ns"] = max(
                            0, observed_ns - dispatched
                        )
                self._discard_terminal(event_name, hover_id, lookup_id, fields)
            finally:
                self._lock.release()
        else:
            # Correlation is optional evidence. A simultaneous producer must
            # never wait behind benchmark bookkeeping on the hover path.
            fields["correlation_skipped"] = True

        return self._recorder.record_at(event_name, observed_ns, **fields)

    def record(self, event: str, **fields: object) -> bool:
        """Record a benchmark-owned event with the current phase."""

        safe = self._privacy.redact(fields, retain_text=self._retain_text)
        safe["phase"] = self._phases.current
        return self._recorder.record(event, **safe)

    @staticmethod
    def _add_stage_classification(event_name: str, fields: dict[str, Any]) -> None:
        if event_name != "lookup_stage_completed":
            return
        if fields.get("stage") == "ocr":
            regions = int(fields.get("region_count", 0) or 0)
            hangul = int(fields.get("hangul_region_count", 0) or 0)
            fields["has_hangul"] = hangul > 0
            fields["non_hangul_ocr_result"] = regions > 0 and hangul == 0
        elif fields.get("stage") == "dictionary":
            found = fields.get("found")
            if isinstance(found, bool):
                fields["dictionary_status"] = "hit" if found else "miss"

    def _discard_terminal(
        self,
        event_name: str,
        hover_id: int | None,
        lookup_id: int | None,
        fields: Mapping[str, object],
    ) -> None:
        if event_name in {
            "hover_invalidation",
            "hover_cancellation",
            "hover_stale_after_capture",
            "hover_stale_after_submission",
        } and hover_id is not None:
            self._hover_started.pop(hover_id, None)
        terminal_lookup_id = lookup_id
        if event_name == "executor_pending_replaced":
            terminal_lookup_id = _integer_id(fields.get("replaced_lookup_request_id"))
        if event_name in {
            "popup_visible",
            "popup_suppressed",
            "lookup_stale_suppressed",
            "lookup_cancelled_early",
            "executor_pending_replaced",
            "executor_pending_cancelled",
        } and terminal_lookup_id is not None:
            mapped_hover = self._lookup_to_hover.pop(terminal_lookup_id, None)
            self._dispatch_started.pop(terminal_lookup_id, None)
            if mapped_hover is not None:
                self._hover_started.pop(mapped_hover, None)


class DeferredRoiObserver:
    """Hash captured pixels on a benchmark thread, never on the capture path."""

    def __init__(
        self,
        recorder: LiveTraceRecorder,
        privacy: SessionPrivacy,
        *,
        phase: Callable[[], str] | None = None,
        queue_size: int = 128,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        self._recorder = recorder
        self._privacy = privacy
        self._phase = phase or (lambda: "unknown")
        self._queue: queue.Queue[tuple[object, ...] | None] = queue.Queue(queue_size)
        self._thread = threading.Thread(
            target=self._run,
            name="benchmark-roi-digest",
            daemon=True,
        )
        self._closed = False
        self.dropped_observations = 0
        self._thread.start()

    def observe(self, capture: object) -> bool:
        """Queue immutable ROI bytes by reference and return immediately."""

        if self._closed:
            return False
        image = getattr(capture, "image")
        region = getattr(capture, "region")
        item = (
            time.perf_counter_ns(),
            self._phase(),
            image.data,
            int(image.width),
            int(image.height),
            int(region.left),
            int(region.top),
            int(region.width),
            int(region.height),
        )
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped_observations += 1
            return False
        return True

    def close(self, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.put(None, timeout=0.01)
                break
            except queue.Full:
                if not self._thread.is_alive():
                    break
        self._thread.join(max(0.0, timeout))

    def _run(self) -> None:
        previous_digest: str | None = None
        previous_region: tuple[int, int, int, int] | None = None
        while True:
            item = self._queue.get()
            if item is None:
                return
            (
                observed_ns,
                phase,
                data,
                width,
                height,
                left,
                top,
                region_width,
                region_height,
            ) = item
            typed_data = cast(bytes, data)
            typed_width = cast(int, width)
            typed_height = cast(int, height)
            typed_left = cast(int, left)
            typed_top = cast(int, top)
            typed_region_width = cast(int, region_width)
            typed_region_height = cast(int, region_height)
            digest = self._privacy.roi_digest(
                typed_data, typed_width, typed_height
            )
            region = (
                typed_left,
                typed_top,
                typed_region_width,
                typed_region_height,
            )
            self._recorder.record_at(
                "roi_observation",
                cast(int, observed_ns),
                phase=str(phase),
                roi_digest=digest,
                roi_width=typed_width,
                roi_height=typed_height,
                region_left=typed_left,
                region_top=typed_top,
                repeated_frame=digest == previous_digest,
                repeated_region=region == previous_region,
                repeated_frame_suppressed=False,
                repeated_region_suppressed=False,
            )
            previous_digest = digest
            previous_region = region


class ObservedCaptureSource:
    """Delegate the real capture and enqueue a private digest observation."""

    def __init__(self, source: object, observer: DeferredRoiObserver) -> None:
        self._source = source
        self._observer = observer

    def capture_at_cursor(self, cursor: Any) -> Any:
        capture = self._source.capture_at_cursor(cursor)  # type: ignore[attr-defined]
        self._observer.observe(capture)
        return capture

    def close(self) -> None:
        self._source.close()  # type: ignore[attr-defined]


class MarkerHotkey:
    """Small benchmark-only global hotkey with injected deterministic seam."""

    def __init__(
        self,
        binding: str,
        on_marker: Callable[[], None],
        listener_factory: MarkerListenerFactory | None = None,
    ) -> None:
        if not callable(on_marker):
            raise TypeError("on_marker must be callable")
        self._binding = binding
        self._on_marker = on_marker
        self._factory = listener_factory or _marker_listener_factory
        self._listener: _Listener | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        from hanly_app.hotkeys import canonical_hotkey  # type: ignore[import-untyped]

        listener = self._factory({canonical_hotkey(self._binding): self._on_marker})
        listener.start()
        self._listener = listener

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        listener.stop()
        try:
            listener.join(1.0)
        except RuntimeError:
            pass


def _marker_listener_factory(
    callbacks: Mapping[str, Callable[[], None]],
) -> _Listener:
    from pynput import keyboard

    return keyboard.GlobalHotKeys(dict(callbacks))


def _integer_id(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "unavailable"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_cleanup_steps(
    *steps: tuple[str, Callable[[], object]],
) -> list[str]:
    """Attempt every independent cleanup step and retain safe error types."""

    errors: list[str] = []
    for name, step in steps:
        try:
            step()
        except BaseException as error:
            errors.append(f"{name}:{type(error).__name__}")
    return errors


def run_live_hover(args: Any) -> int:
    """Run the explicitly requested real interactive development benchmark."""

    phases = ScenarioPhaseController()
    metadata = build_metadata(
        repo_root=Path.cwd(),
        config={
            "runtime_config": args.config,
            "duration_seconds": args.duration,
            "dwell_ms": args.dwell_ms,
            "cpu_threads": args.cpu_threads,
            "marker_hotkey": args.marker_hotkey,
            "retain_text": args.retain_text,
            "stationary_cursor_polling": False,
            "trace_sink": "bounded_best_effort",
        },
        scenario={
            "name": "live_hover_real_desktop",
            "phases": list(phases.phases),
            "endpoint": "development_qt_popup_visible",
        },
        versions={
            name: _version(distribution)
            for name, distribution in {
                "hanly": "hanly",
                "hanly-app": "hanly-app",
                "easyocr": "easyocr",
                "torch": "torch",
                "PyQt6": "PyQt6",
                "mss": "mss",
                "pynput": "pynput",
                "psutil": "psutil",
            }.items()
        },
    )
    run_dir = Path(args.output_root) / str(metadata["run_id"])
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / "metadata.json", metadata)
    log = (run_dir / "stdout.log").open("w", encoding="utf-8", newline="\n")
    log_lock = threading.Lock()

    def report(message: str) -> None:
        with log_lock:
            print(message, flush=True)
            log.write(message + "\n")
            log.flush()

    recorder = LiveTraceRecorder(run_dir / "live-events.jsonl")
    privacy = SessionPrivacy()
    adapter = RuntimeTraceAdapter(
        recorder,
        phases,
        privacy,
        retain_text=bool(args.retain_text),
    )
    sampler = LiveResourceSampler(
        run_dir / "process.csv",
        phase=lambda: phases.current,
    )
    roi_observer = DeferredRoiObserver(
        recorder,
        privacy,
        phase=lambda: phases.current,
    )
    manual: Any | None = None
    capture: Any | None = None
    marker: MarkerHotkey | None = None
    previous_sigint: Any = None
    exit_reason = ["qt_event_loop_exit"]
    cleanup_errors: list[str] = []

    try:
        sampler.start()
        adapter.record("session_preparing")
        report(f"Live benchmark run {metadata['run_id']}")
        report("Preparing the real resident hover composition; do not move yet.")

        # Match production startup ordering: native OCR preload precedes Qt.
        from hanly_app.ocr_preload import preload_ocr_runtime  # type: ignore[import-untyped]

        preload_ocr_runtime()
        from hanly_app.capture import CaptureService  # type: ignore[import-untyped]
        from hanly_app.manual_lookup import (  # type: ignore[import-untyped]
            create_qt_manual_lookup,
        )
        from hanly_app.runtime import load_runtime  # type: ignore[import-untyped]
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([sys.argv[0]])
        runtime = load_runtime(args.config)
        if args.cpu_threads is not None and runtime.easyocr_config is not None:
            runtime = replace(
                runtime,
                easyocr_config=replace(runtime.easyocr_config, cpu_threads=args.cpu_threads),
            )
        capture = CaptureService()
        observed_capture = ObservedCaptureSource(capture, roi_observer)
        manual = create_qt_manual_lookup(
            runtime,
            observed_capture,
            hover_enabled=True,
            hover_delay_ms=float(args.dwell_ms),
            trace_sink=adapter,
        )

        def mark_phase() -> None:
            transition = phases.advance()
            adapter.record("phase_marker", **transition.as_dict())
            report(f"phase -> {transition.phase}")

        marker = MarkerHotkey(args.marker_hotkey, mark_phase)
        manual.start()
        session_started = [False]
        startup_error: list[str | None] = [None]
        readiness_deadline = time.monotonic() + 120.0

        def duration_elapsed() -> None:
            exit_reason[0] = "duration_elapsed"
            application.quit()

        def interrupted(_signum: int, _frame: object) -> None:
            exit_reason[0] = "keyboard_interrupt"
            application.quit()

        previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, interrupted)
        readiness_timer = QTimer()

        def check_readiness() -> None:
            if manual.controller.worker_ready:
                readiness_timer.stop()
                try:
                    marker.start()
                except BaseException as error:
                    startup_error[0] = (
                        f"marker hotkey startup failed: {type(error).__name__}: {error}"
                    )
                    exit_reason[0] = "startup_error"
                    application.quit()
                    return
                session_started[0] = True
                adapter.record(
                    "session_started",
                    requested_duration_seconds=args.duration,
                )
                report(
                    f"READY: phase={phases.current}; marker={args.marker_hotkey}; "
                    f"duration={args.duration}s"
                )
                QTimer.singleShot(
                    round(float(args.duration) * 1000), duration_elapsed
                )
                return
            if not manual.controller.accepting:
                startup_error[0] = "resident hover worker initialization failed"
            elif time.monotonic() >= readiness_deadline:
                startup_error[0] = "resident hover worker was not ready within 120 seconds"
            else:
                return
            readiness_timer.stop()
            exit_reason[0] = "startup_error"
            application.quit()

        readiness_timer.timeout.connect(check_readiness)
        readiness_timer.start(10)
        QTimer.singleShot(0, check_readiness)
        application.exec()
        if startup_error[0] is not None:
            raise RuntimeError(startup_error[0])
        if session_started[0]:
            adapter.record("session_finished", reason=exit_reason[0])
    except BaseException as error:
        exit_reason[0] = "error"
        adapter.record("session_failed", error_type=type(error).__name__)
        report(f"live session failed: {type(error).__name__}: {error}")
        raise
    finally:
        steps: list[tuple[str, Callable[[], object]]] = []
        if previous_sigint is not None:
            steps.append(
                (
                    "restore_sigint",
                    lambda: signal.signal(signal.SIGINT, previous_sigint),
                )
            )
        if marker is not None:
            steps.append(("marker_stop", marker.stop))
        if manual is not None:
            steps.append(("manual_begin_shutdown", manual.begin_shutdown))
        elif capture is not None:
            steps.append(("capture_close", capture.close))
        steps.append(("resource_sampler_stop", sampler.stop))
        if manual is not None:
            def await_manual() -> None:
                if not manual.await_shutdown(30.0):
                    raise TimeoutError("lookup worker did not stop within 30 seconds")

            steps.append(("manual_await_shutdown", await_manual))
        steps.extend(
            (
                ("roi_observer_close", roi_observer.close),
                ("trace_recorder_close", recorder.close),
            )
        )
        cleanup_errors.extend(_run_cleanup_steps(*steps))
        try:
            summary = LiveSummary.from_files(
                run_dir / "live-events.jsonl", run_dir / "process.csv"
            )
            summary.update(
                {
                    "exit_reason": exit_reason[0],
                    "trace_events_dropped": recorder.dropped_events,
                    "trace_write_errors": recorder.write_errors,
                    "roi_observations_dropped": roi_observer.dropped_observations,
                    "stationary_cursor_polling": False,
                    "raw_text_retained": bool(args.retain_text),
                    "cleanup_errors": cleanup_errors,
                }
            )
            _write_json(run_dir / "summary.json", summary)
            report(f"evidence: {run_dir}")
        except BaseException as error:
            cleanup_errors.append(f"summary:{type(error).__name__}")
            report(f"summary generation failed: {type(error).__name__}: {error}")
        finally:
            log.close()
    return 1 if cleanup_errors else 0


__all__ = [
    "DeferredRoiObserver",
    "MarkerHotkey",
    "ObservedCaptureSource",
    "RuntimeTraceAdapter",
    "run_live_hover",
]
