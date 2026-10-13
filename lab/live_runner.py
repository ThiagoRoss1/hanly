"""Human-operated benchmark over the real development hover path.

Importing this module is safe and does not construct Qt, listeners, capture, or
providers.  Those dependencies are imported lazily by :func:`run_live_hover`,
which is invoked only by the explicit ``live-hover`` command.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Protocol, cast

from .frozen_lookup import FreezeReport, LookupRing
from .live_telemetry import (
    LiveResourceSampler,
    LiveSummary,
    LiveTraceRecorder,
    ScenarioPhaseController,
    SessionPrivacy,
)
from .metadata import build_metadata
from .microscope import (
    ARTIFACT_ROOT,
    MicroscopeCaptureObserver,
    MicroscopeSink,
    build_ring,
    export_frozen,
    freeze,
)


class _Listener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...


MarkerListenerFactory = Callable[[Mapping[str, Callable[[], None]]], _Listener]


class RuntimeTraceAdapter:
    """Add phase/privacy data and derive request-correlated perceived timing.

    Nothing that reaches this recorder carries screen content. Raw text and
    recognized geometry are privacy-minimized on the way through, whether or not
    a lookup is later frozen; persisting them is an explicit export of one
    pinned lookup, never a property of tracing.
    """

    def __init__(
        self,
        recorder: LiveTraceRecorder,
        phases: ScenarioPhaseController,
        privacy: SessionPrivacy,
    ) -> None:
        self._recorder = recorder
        self._phases = phases
        self._privacy = privacy
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
        fields = self._privacy.redact(raw_fields)
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

        safe = self._privacy.redact(fields)
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


class _CaptureSource(Protocol):
    """The two capture operations the observing wrapper delegates to."""

    def capture_at_cursor(self, cursor: Any) -> Any: ...

    def close(self) -> None: ...


class ObservedCaptureSource:
    """Delegate the real capture and enqueue a private digest observation."""

    def __init__(self, source: _CaptureSource, observer: DeferredRoiObserver) -> None:
        self._source = source
        self._observer = observer

    def capture_at_cursor(self, cursor: Any) -> Any:
        capture = self._source.capture_at_cursor(cursor)
        self._observer.observe(capture)
        return capture

    def close(self) -> None:
        self._source.close()


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
        from hanly_app.hotkeys import canonical_hotkey

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


def freeze_lookup_into(
    ring: LookupRing, holder: list[Any], counts: SessionEvidenceCounts | None = None
) -> FreezeReport:
    """Pin the newest completed lookup and remember it for a later export.

    The hotkey callback runs on the listener thread, so this only selects and
    copies an in-memory record. Encoding and writing belong to the separate
    export action.
    """

    report = freeze(ring)
    if report.frozen is not None:
        holder.append(report.frozen)
        if counts is not None:
            counts.frozen += 1
    return report


def _freeze_message(report: FreezeReport) -> str:
    if report.frozen is None:
        return f"freeze: nothing to pin ({report.reason})"
    frozen = report.frozen
    gaps = f"; unavailable: {', '.join(report.notes)}" if report.notes else ""
    return (
        f"freeze: pinned lookup {frozen.lookup_request_id} "
        f"({frozen.result_status or 'no status'}) from {report.records_held} held{gaps}"
    )


@dataclass
class SessionEvidenceCounts:
    """How many times each act happened, kept apart because they differ.

    Freezing pins a lookup in memory; exporting writes it. Counting one as the
    other is what made an earlier run report nine exports against eight
    directories. Only counts live here -- no identifiers, no screen content.
    """

    frozen: int = 0
    export_attempts: int = 0
    exports_succeeded: int = 0
    exports_failed: int = 0
    exports_refused_nothing_frozen: int = 0
    reexports: int = 0
    exported_directories: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, int]:
        return {
            "frozen_lookups_pinned": self.frozen,
            "frozen_lookup_export_attempts": self.export_attempts,
            "frozen_lookup_exports_succeeded": self.exports_succeeded,
            "frozen_lookup_exports_failed": self.exports_failed,
            "frozen_lookup_exports_refused_nothing_frozen": (
                self.exports_refused_nothing_frozen
            ),
            "frozen_lookup_reexports": self.reexports,
            "frozen_lookups_exported": len(self.exported_directories),
        }


def _export_message(
    holder: list[Any],
    run_dir: Path,
    artifact_root: Path,
    counts: SessionEvidenceCounts | None = None,
) -> str:
    """Write the pinned lookup, which is the only path to private artifacts."""

    tally = counts if counts is not None else SessionEvidenceCounts()
    tally.export_attempts += 1
    if not holder:
        tally.exports_refused_nothing_frozen += 1
        return "export: nothing is frozen; press the freeze hotkey first"
    frozen = holder[-1]
    destination = run_dir / f"frozen-{frozen.lookup_request_id}"
    try:
        exported = export_frozen(
            frozen, destination, artifact_root=Path(artifact_root)
        )
    except BaseException as error:
        tally.exports_failed += 1
        return f"export failed: {type(error).__name__}: {error}"
    tally.exports_succeeded += 1
    directory = str(exported.directory)
    if directory in tally.exported_directories:
        tally.reexports += 1
    tally.exported_directories.add(directory)
    return f"export: {len(exported.files)} files in {exported.directory}"


def production_capture_service(backend: Any | None = None) -> Any:
    """Build capture exactly as the desktop composition does.

    ``CaptureService`` defaults to an unsnapped grid, while the desktop passes
    ``DEFAULT_ROI_GRID``. The snap is what lets nearby cursor positions reuse
    one ROI and hit the OCR cache, so a benchmark that leaves it at the default
    measures a runtime the product does not ship.
    """

    from hanly_app.acquisition.capture import DEFAULT_ROI_GRID, CaptureService

    if backend is None:
        return CaptureService(roi_grid=DEFAULT_ROI_GRID)
    return CaptureService(backend=backend, roi_grid=DEFAULT_ROI_GRID)


class _DesktopRecorder:
    """Adapt the live recorder to the native process observer contract."""

    retain_evidence = True
    retain_geometry = True

    def __init__(self, adapter: RuntimeTraceAdapter, microscope: MicroscopeSink) -> None:
        self._adapter = adapter
        self._microscope = microscope

    def lab(self, event: str, /, **fields: Any) -> None:
        self._adapter.record(event, **fields)

    def emit(self, event: Mapping[str, Any]) -> object:
        return self._microscope.emit(event)


def _capture_from_payload(payload: Mapping[str, Any]) -> tuple[Any, int | None, int | None]:
    """Decode one bounded Lab-only capture frame into the app's value types."""

    import base64

    from hanly import PixelFormat, ROIImage
    from hanly_app.acquisition.capture import CaptureResult

    image_value = payload.get("image")
    region_value = payload.get("region")
    target_value = payload.get("target")
    if not isinstance(image_value, Mapping):
        raise ValueError("capture image is missing")
    if not isinstance(region_value, Mapping) or not isinstance(target_value, Mapping):
        raise ValueError("capture geometry is missing")
    width = _positive_int(image_value.get("width"))
    height = _positive_int(image_value.get("height"))
    if width is None or height is None or width > 4096 or height > 4096:
        raise ValueError("capture dimensions are invalid")
    if image_value.get("pixel_format") != PixelFormat.RGB_888.value:
        raise ValueError("capture pixel format is unsupported")
    encoded = image_value.get("data_base64")
    if not isinstance(encoded, str) or len(encoded) > 934_000:
        raise ValueError("capture frame exceeds the Lab limit")
    data = base64.b64decode(encoded, validate=True)
    if len(data) != width * height * 3 or len(data) > 700_000:
        raise ValueError("capture image length is invalid")
    image = ROIImage(width, height, PixelFormat.RGB_888, data)
    region = _screen_rect(region_value)
    target = _point(target_value)
    plan_value = payload.get("plan")
    plan = None if plan_value is None else _capture_plan(plan_value)
    capture = CaptureResult(image=image, region=region, target=target, plan=plan)
    return (
        capture,
        _integer_id(payload.get("hover_request_id")),
        _integer_id(payload.get("lookup_request_id")),
    )


def _capture_plan(value: object) -> Any:
    from hanly import PixelFormat
    from hanly_app.acquisition.capture import CapturePlan

    if not isinstance(value, Mapping):
        raise ValueError("capture plan is invalid")
    roi_size = value.get("roi_size")
    if (
        not isinstance(roi_size, list)
        or len(roi_size) != 2
        or any(_positive_int(item) is None for item in roi_size)
    ):
        raise ValueError("capture plan ROI size is invalid")
    configured = value.get("configured_region")
    return CapturePlan(
        requested_cursor=_point(_mapping(value, "requested_cursor")),
        effective_cursor=_point(_mapping(value, "effective_cursor")),
        monitor_index=_required_int(value, "monitor_index"),
        monitor_name=_required_str(value, "monitor_name"),
        monitor_bounds=_screen_rect(_mapping(value, "monitor_bounds")),
        configured_region=None if configured is None else _screen_rect(_as_mapping(configured)),
        clip_bounds=_screen_rect(_mapping(value, "clip_bounds")),
        roi_size=(int(roi_size[0]), int(roi_size[1])),
        roi_grid=_required_int(value, "roi_grid"),
        ideal_region=_screen_rect(_mapping(value, "ideal_region")),
        desired_region=_screen_rect(_mapping(value, "desired_region")),
        actual_region=_screen_rect(_mapping(value, "actual_region")),
        target=_point(_mapping(value, "target")),
        image_width=_required_int(value, "image_width"),
        image_height=_required_int(value, "image_height"),
        pixel_format=PixelFormat(_required_str(value, "pixel_format")),
        image_byte_length=_required_int(value, "image_byte_length"),
    )


def _as_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("capture geometry is invalid")
    return value


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(value.get(key))


def _screen_rect(value: Mapping[str, Any]) -> Any:
    from hanly_app.acquisition.capture import ScreenRect

    return ScreenRect(
        left=_required_int(value, "left"),
        top=_required_int(value, "top"),
        width=_required_int(value, "width"),
        height=_required_int(value, "height"),
    )


def _point(value: Mapping[str, Any]) -> Any:
    from hanly import Point

    x = value.get("x")
    y = value.get("y")
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError("point x is invalid")
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise ValueError("point y is invalid")
    return Point(float(x), float(y))


def _required_int(value: Mapping[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"{key} is invalid")
    return result


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _required_str(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ValueError(f"{key} is invalid")
    return result


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
    """Run the explicitly requested native Tauri hover measurement."""

    import os

    from hanly_app.config import ConfigManager, HoverActivation
    from hanly_app.paths import default_app_config_path

    from .session.desktop_process import (
        DesktopProcess,
        desktop_executable,
        is_debug_executable,
    )
    from .session.runner import _read_user_settings, _runtime_config
    from .session.sampler import ProcessSampler

    repo_root = Path.cwd().resolve()
    runtime_config = _runtime_config(Path(args.config))
    executable = desktop_executable(getattr(args, "desktop", None), repo_root)
    if not is_debug_executable(executable, repo_root):
        raise SystemExit(
            "lab: live-hover requires this checkout's debug Tauri app so its private, "
            "opt-in microscope stays outside the packaged application"
        )
    source_config = getattr(args, "app_config", None) or default_app_config_path()
    settings = _read_user_settings(source_config)
    dwell_ms = int(round(float(args.dwell_ms)))
    settings = replace(
        settings,
        hover_activation=HoverActivation.ALWAYS_ACTIVE,
        hover_delay_ms=dwell_ms,
        update_checks_enabled=False,
    )

    phases = ScenarioPhaseController()
    metadata = build_metadata(
        repo_root=repo_root,
        kind="live_hover",
        config={
            "runtime_config": str(runtime_config),
            "duration_seconds": args.duration,
            "dwell_ms": dwell_ms,
            "cpu_threads": args.cpu_threads,
            "marker_hotkey": args.marker_hotkey,
            "freeze_hotkey": args.freeze_hotkey,
            "export_hotkey": args.export_hotkey,
            "stationary_cursor_polling": False,
            "trace_sink": "bounded_debug_protocol",
            "capture_observer": "explicit_private_live_hover_opt_in",
        },
        scenario={
            "name": "live_hover_native_tauri",
            "phases": list(phases.phases),
            "endpoint": "native_tauri_popup_visible",
        },
        versions={
            name: _version(distribution)
            for name, distribution in {
                "hanly": "hanly",
                "hanly-app": "hanly-app",
                "easyocr": "easyocr",
                "torch": "torch",
                "mss": "mss",
                "pynput": "pynput",
                "psutil": "psutil",
            }.items()
        },
    )
    run_root = Path(args.output_root).expanduser().resolve()
    run_dir = run_root / str(metadata["run_id"])
    profile = run_dir / "profile"
    profile.mkdir(parents=True, exist_ok=False)
    app_config = profile / "config.json"
    ConfigManager(app_config).save(settings)
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
    adapter = RuntimeTraceAdapter(recorder, phases, privacy)
    ring = build_ring()
    microscope = MicroscopeSink(ring, adapter)
    desktop_recorder = _DesktopRecorder(adapter, microscope)
    capture_observer = MicroscopeCaptureObserver(ring, privacy)
    capture_running = threading.Event()
    runtime_ready = threading.Event()
    runtime_failed = threading.Event()
    provider_ready = threading.Event()
    provider_failed = threading.Event()
    resolved_backend: list[str | None] = [None]

    def receive_trace(event: Mapping[str, Any]) -> None:
        microscope.emit(event)
        name = event.get("event_kind", event.get("event"))
        if name == "lab_runtime_ready":
            runtime_ready.set()
        elif name == "lab_runtime_failed":
            runtime_failed.set()
        elif name == "lab_capture_started":
            capture_running.set()
        elif name == "executor_worker_ready":
            provider_ready.set()
        elif name in {"executor_worker_construction_failed", "executor_worker_failed"}:
            provider_failed.set()
        elif name == "lookup_stage_completed" and event.get("stage") == "ocr":
            backend = event.get("ocr_backend")
            if isinstance(backend, str):
                resolved_backend[0] = backend

    def receive_capture(payload: Mapping[str, Any]) -> None:
        capture, hover_id, lookup_id = _capture_from_payload(payload)
        capture_observer.observe(
            capture,
            hover_request_id=hover_id,
            lookup_request_id=lookup_id,
        )

    environment = os.environ.copy()
    environment.update(
        {
            "XDG_CONFIG_HOME": str(profile),
            "XDG_DATA_HOME": str(profile / "data"),
            "LOCALAPPDATA": str(profile),
            "APPDATA": str(profile),
            "HANLY_DESKTOP_SERVICE_MODULE": "lab.service_observer",
            "HANLY_LAB_RETAIN_EVIDENCE": "1",
            "HANLY_LAB_RETAIN_GEOMETRY": "1",
            "HANLY_LAB_CAPTURE_EXPORT": "1",
        }
    )
    for variable in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        if args.cpu_threads is None:
            environment.pop(variable, None)
        else:
            environment[variable] = str(args.cpu_threads)

    process_sampler = ProcessSampler(
        run_dir / "processes.jsonl", recorder.clock(), sample_parent=False
    )
    desktop = DesktopProcess(
        executable,
        runtime_config=runtime_config,
        app_config=app_config,
        environment=environment,
        recorder=desktop_recorder,
        sampler=process_sampler,
        repo_root=repo_root,
        trace_consumer=receive_trace,
        capture_consumer=receive_capture,
    )
    resource_sampler: LiveResourceSampler | None = None
    marker: MarkerHotkey | None = None
    freezer: MarkerHotkey | None = None
    exporter: MarkerHotkey | None = None
    frozen_holder: list[Any] = []
    evidence_counts = SessionEvidenceCounts()
    cleanup_errors: list[str] = []
    exit_reason = ["not_started"]
    session_started = False

    def mark_phase() -> None:
        transition = phases.advance()
        adapter.record("phase_marker", **transition.as_dict())
        report(f"phase -> {transition.phase}")

    def freeze_lookup() -> None:
        report(_freeze_message(freeze_lookup_into(ring, frozen_holder, evidence_counts)))

    def export_lookup() -> None:
        report(_export_message(frozen_holder, run_dir, ARTIFACT_ROOT, evidence_counts))

    try:
        adapter.record("session_preparing")
        report(f"Live Hanly Tauri benchmark run {metadata['run_id']}")
        report("Starting the native desktop and preparing its resident hover path.")
        process_sampler.start()
        desktop.start(retain_evidence=True, retain_geometry=True)
        process = desktop.process
        if process is None:
            raise RuntimeError("native desktop did not start")
        import psutil

        resource_sampler = LiveResourceSampler(
            run_dir / "process.csv",
            process=psutil.Process(process.pid),
            phase=lambda: phases.current,
        )
        resource_sampler.start()

        ready_deadline = time.monotonic() + 120.0
        while not runtime_ready.is_set() and not runtime_failed.is_set():
            if desktop.poll() is not None:
                raise RuntimeError("native desktop exited before service readiness")
            if time.monotonic() >= ready_deadline:
                raise TimeoutError("native desktop runtime was not ready within 120 seconds")
            time.sleep(0.05)
        if runtime_failed.is_set():
            raise RuntimeError("native desktop runtime preparation failed")

        if not capture_running.is_set():
            from .session.driver import ensure_capture

            how = ensure_capture(
                capture_running,
                lambda: _press_capture_hotkey(settings.capture_hotkey),
                launch_grace=3.0,
                after_press=60.0,
            )
            adapter.record("capture_activation", how=how)
            if how == "never_started":
                raise RuntimeError(
                    "capture did not start; check Hanly's Accessibility and Screen "
                    "Recording permissions"
                )

        if settings.lookup_preload.value != "on_demand":
            provider_deadline = time.monotonic() + 120.0
            while not provider_ready.is_set() and not provider_failed.is_set():
                if desktop.poll() is not None:
                    raise RuntimeError("native desktop exited before lookup providers were ready")
                if time.monotonic() >= provider_deadline:
                    raise TimeoutError("lookup providers were not ready within 120 seconds")
                time.sleep(0.05)
            if provider_failed.is_set():
                raise RuntimeError("lookup providers could not initialize")

        marker = MarkerHotkey(args.marker_hotkey, mark_phase)
        freezer = MarkerHotkey(args.freeze_hotkey, freeze_lookup)
        exporter = MarkerHotkey(args.export_hotkey, export_lookup)
        for hotkey in (marker, freezer, exporter):
            hotkey.start()
        session_started = True
        exit_reason[0] = "duration_elapsed"
        adapter.record("session_started", requested_duration_seconds=args.duration)
        report(
            f"READY: phase={phases.current}; marker={args.marker_hotkey}; "
            f"freeze={args.freeze_hotkey}; export={args.export_hotkey}; "
            f"duration={args.duration}s"
        )
        deadline = time.monotonic() + float(args.duration)
        while time.monotonic() < deadline:
            if desktop.poll() is not None:
                exit_reason[0] = "desktop_exit"
                break
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if desktop.poll() is not None and exit_reason[0] == "duration_elapsed":
            exit_reason[0] = "desktop_exit"
        elif exit_reason[0] == "duration_elapsed":
            desktop.request_stop()
        adapter.record("session_finished", reason=exit_reason[0])
    except KeyboardInterrupt:
        exit_reason[0] = "keyboard_interrupt"
        desktop.request_stop()
        if session_started:
            adapter.record("session_finished", reason=exit_reason[0])
    except BaseException as error:
        exit_reason[0] = "error"
        adapter.record("session_failed", error_type=type(error).__name__)
        report(f"live session failed: {type(error).__name__}: {error}")
        raise
    finally:
        cleanup_hotkeys: tuple[tuple[str, MarkerHotkey | None], ...] = (
            ("marker", marker),
            ("freeze_hotkey", freezer),
            ("export_hotkey", exporter),
        )
        for name, owned_hotkey in cleanup_hotkeys:
            if owned_hotkey is not None:
                cleanup_errors.extend(
                    _run_cleanup_steps((f"{name}_stop", owned_hotkey.stop))
                )
        cleanup = desktop.cleanup()
        if cleanup["survivors"] or cleanup["forced"]:
            cleanup_errors.append(
                f"desktop_children:survivors={cleanup['survivors']},forced={cleanup['forced']}"
            )
        capture_observer.close()
        if resource_sampler is not None:
            cleanup_errors.extend(
                _run_cleanup_steps(("resource_sampler_stop", resource_sampler.stop))
            )
        cleanup_errors.extend(
            _run_cleanup_steps(("process_sampler_stop", process_sampler.stop))
        )
        recorder.close()
        try:
            summary = LiveSummary.from_files(
                run_dir / "live-events.jsonl", run_dir / "process.csv"
            )
            summary.update(
                {
                    "resolved_ocr_backend": resolved_backend[0],
                    "exit_reason": exit_reason[0],
                    "trace_events_dropped": recorder.dropped_events,
                    "trace_write_errors": recorder.write_errors,
                    "stationary_cursor_polling": False,
                    "raw_text_retained": False,
                    **evidence_counts.as_dict(),
                    "microscope_captures_dropped": capture_observer.dropped_observations,
                    "desktop_trace_lines": desktop.trace_lines,
                    "desktop_capture_frames": desktop.capture_lines,
                    "desktop_trace_rejected": desktop.invalid_trace_lines,
                    "desktop_capture_rejected": desktop.invalid_capture_lines,
                    "process_family_samples": process_sampler.samples,
                    "process_family_access_denied": process_sampler.denied,
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


def _press_capture_hotkey(binding: str) -> None:
    """Press the configured native shortcut once, as a person would."""

    from pynput import keyboard

    controller = keyboard.Controller()
    aliases = {"control": "ctrl", "option": "alt", "command": "cmd"}
    parts = [part.strip().lower() for part in binding.split("+") if part.strip()]
    if not parts:
        raise RuntimeError("the capture shortcut is unbound")
    resolved = [
        getattr(keyboard.Key, aliases.get(part, part), None) or part for part in parts
    ]
    for key in resolved:
        controller.press(key)
        time.sleep(0.02)
    for key in reversed(resolved):
        controller.release(key)
        time.sleep(0.02)


__all__ = [
    "DeferredRoiObserver",
    "MarkerHotkey",
    "ObservedCaptureSource",
    "RuntimeTraceAdapter",
    "SessionEvidenceCounts",
    "freeze_lookup_into",
    "production_capture_service",
    "run_live_hover",
]
