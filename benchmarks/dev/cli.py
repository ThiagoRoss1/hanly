"""Command-line entry point for isolated benchmark campaigns."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import queue
import threading
import time
from collections.abc import Sequence
from dataclasses import replace
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from hanly import PixelFormat, Point, ROIImage
from hanly.easyocr_provider import EasyOCRConfig, EasyOCRProvider
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly_app.runtime import load_runtime

from .campaigns import (
    CampaignPlan,
    ExpectedLookup,
    ObservedLookupPipeline,
    run_lookup_campaign,
    summarize_stages,
)
from .desktop_probes import measure_capture_service
from .diagnostics import (
    DiagnosticSnapshot,
    DictionaryDiagnostic,
    MorphologyDiagnostic,
    MorphologyTokenDiagnostic,
    OCRDiagnostic,
    OCRRegionDiagnostic,
    PointDiagnostic,
    RectangleDiagnostic,
    StageTiming,
    TargetDiagnostic,
    render_annotated_png,
    render_diagnostic_html,
    write_diagnostic_json,
)
from .hover_rate import hover_invocation_matrix
from .metadata import build_metadata
from .package_composition import write_package_report
from .probes import ProcessSampler
from .run_store import RunStore


def _version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "unavailable"


def _parse_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("ROI size must use WIDTHxHEIGHT") from error
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("ROI dimensions must be positive")
    return width, height


def _parse_live_duration(value: str) -> int:
    """Parse the human-operated live session duration.

    The lower bound leaves enough time for each prescribed phase while the
    upper bound keeps an accidental unattended run from becoming an
    unbounded resource observation.  This is intentionally a parser-level
    contract so help/validation never imports the live desktop composition.
    """

    try:
        duration = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "live duration must be an integer number of seconds"
        ) from error
    if not 120 <= duration <= 300:
        raise argparse.ArgumentTypeError("live duration must be between 120 and 300 seconds")
    return duration


def _parse_cpu_threads(value: str) -> int:
    try:
        threads = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("cpu threads must be an integer") from error
    if not 1 <= threads <= 64:
        raise argparse.ArgumentTypeError("cpu threads must be between 1 and 64")
    return threads


def _benchmark_ocr_config(
    config: EasyOCRConfig | None,
    args: argparse.Namespace,
) -> EasyOCRConfig:
    """Apply only explicit benchmark overrides to an immutable OCR config."""

    if config is None:
        raise RuntimeError("runtime config carries no EasyOCR configuration")
    cpu_threads = getattr(args, "cpu_threads", None)
    if cpu_threads is None:
        return config
    return replace(config, cpu_threads=cpu_threads)


def prepare_roi(
    image_path: Path,
    *,
    target: Point,
    size: tuple[int, int] | None,
) -> tuple[ROIImage, Point, Any, dict[str, Any]]:
    """Crop/pad one retained input while preserving its target coordinate."""

    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - optional benchmark extra
        raise RuntimeError("Pillow is required for real benchmark campaigns") from error

    with Image.open(image_path) as source_file:
        source = source_file.convert("RGB")
    requested_width, requested_height = size or source.size

    crop_width = min(requested_width, source.width)
    crop_height = min(requested_height, source.height)
    crop_left = min(max(round(target.x - crop_width / 2), 0), source.width - crop_width)
    crop_top = min(max(round(target.y - crop_height / 2), 0), source.height - crop_height)
    cropped = source.crop(
        (crop_left, crop_top, crop_left + crop_width, crop_top + crop_height)
    )

    pad_left = (requested_width - crop_width) // 2
    pad_top = (requested_height - crop_height) // 2
    prepared = Image.new("RGB", (requested_width, requested_height), "white")
    prepared.paste(cropped, (pad_left, pad_top))
    prepared_target = Point(
        target.x - crop_left + pad_left,
        target.y - crop_top + pad_top,
    )
    if not 0 <= prepared_target.x < requested_width:
        raise ValueError("transformed target lies outside requested ROI width")
    if not 0 <= prepared_target.y < requested_height:
        raise ValueError("transformed target lies outside requested ROI height")

    image = ROIImage(
        requested_width,
        requested_height,
        PixelFormat.RGB_888,
        prepared.tobytes(),
    )
    transformation = {
        "source_size": [source.width, source.height],
        "requested_size": [requested_width, requested_height],
        "crop": [crop_left, crop_top, crop_width, crop_height],
        "padding": [pad_left, pad_top],
        "source_target": [target.x, target.y],
        "prepared_target": [prepared_target.x, prepared_target.y],
    }
    source.close()
    cropped.close()
    return image, prepared_target, prepared, transformation


def _versions() -> dict[str, str]:
    return {
        name: _version(distribution)
        for name, distribution in {
            "hanly": "hanly",
            "hanly-app": "hanly-app",
            "easyocr": "easyocr",
            "torch": "torch",
            "kiwipiepy": "kiwipiepy",
            "PyQt6": "PyQt6",
            "pywebview": "pywebview",
            "mss": "mss",
            "pynput": "pynput",
            "psutil": "psutil",
        }.items()
    }


def _selected_ocr_index(regions: Sequence[Any], selected: Any) -> int | None:
    if selected is None:
        return None
    for index, region in enumerate(regions):
        if region is selected or region == selected:
            return index
    return None


def _snapshot(
    pipeline: ObservedLookupPipeline,
    result: Any,
    image: ROIImage,
    target: Point,
    total_duration_ns: int,
) -> DiagnosticSnapshot:
    ocr_regions = tuple(pipeline.last_results.get("ocr", ()))
    resolution = pipeline.last_results.get("token_selection")
    selected_region = resolution[0] if isinstance(resolution, tuple) and resolution else None
    analyses = tuple(pipeline.last_results.get("morphology", ()))
    context = result.context
    lemma = context.lemma if context is not None else None
    selected_token = next(
        (index for index, token in enumerate(analyses) if token.lemma == lemma),
        None,
    )
    timings = [
        StageTiming(stage, duration / 1_000_000)
        for stage, duration in pipeline.latest_duration_ns.items()
    ]
    timings.append(StageTiming("total_pipeline", total_duration_ns / 1_000_000))

    return DiagnosticSnapshot(
        roi=RectangleDiagnostic(0, 0, image.width, image.height),
        target=TargetDiagnostic(PointDiagnostic(target.x, target.y), available=True),
        ocr=OCRDiagnostic(
            tuple(OCRRegionDiagnostic(region) for region in ocr_regions),
            _selected_ocr_index(ocr_regions, selected_region),
        ),
        morphology=MorphologyDiagnostic(
            tuple(
                MorphologyTokenDiagnostic(
                    token=token.token,
                    start=None,
                    end=None,
                    lemma=token.lemma,
                )
                for token in analyses
            ),
            selected_token,
            lemma,
        ),
        dictionary=DictionaryDiagnostic(
            key=lemma,
            status=result.status.value,
        ),
        timings=tuple(timings),
        providers=("EasyOCRProvider", "KiwiProvider", "KRDICTProvider"),
        resources=("runtime-config:validated",),
        request=None,
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _serialize_result(result: Any) -> dict[str, Any]:
    context = result.context
    return {
        "status": result.status.value,
        "entries": [
            {
                "headword": entry.headword,
                "definitions": list(entry.definitions),
                "part_of_speech": entry.part_of_speech,
            }
            for entry in result.entries
        ],
        "diagnostics": list(result.diagnostics),
        "context": None
        if context is None
        else {
            "text": context.text,
            "lemma": context.lemma,
            "ocr_results": [
                {
                    "text": region.text,
                    "confidence": region.confidence,
                    "quad": [
                        {"x": point.x, "y": point.y}
                        for point in region.quad.points
                    ],
                }
                for region in context.ocr_results
            ],
        },
        "error": None
        if result.error is None
        else {"type": type(result.error).__name__, "message": str(result.error)},
    }


def run_real_lookup(args: argparse.Namespace) -> int:
    """Run one real provider campaign and retain its complete evidence ledger."""

    source_target = Point(args.target_x, args.target_y)
    image, target, prepared_image, transformation = prepare_roi(
        args.image,
        target=source_target,
        size=args.roi_size,
    )
    scenario = f"real_lookup_roi_{image.width}x{image.height}"
    config_metadata = {
        "runtime_config": args.config,
        "cpu_threads": args.cpu_threads,
        "thread_environment": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        },
        "ledger_fsync": False,
        "idle_observation_seconds": args.idle_seconds,
    }
    metadata = build_metadata(
        repo_root=Path.cwd(),
        config=config_metadata,
        scenario={
            "name": scenario,
            "image": args.image,
            "transformation": transformation,
            "warmup_samples": args.warmup,
            "warm_samples": args.samples,
        },
        versions=_versions(),
    )
    run_dir = args.output_root / str(metadata["run_id"])
    stdout_path = run_dir / "stdout.log"
    run_dir.mkdir(parents=True, exist_ok=True)

    ocr: Any | None = None
    morphology: Any | None = None
    dictionary: Any | None = None
    with stdout_path.open("w", encoding="utf-8", newline="\n") as log:
        def report(message: str) -> None:
            print(message)
            log.write(message + "\n")
            log.flush()

        report(f"Benchmark run {metadata['run_id']} ({scenario})")
        # Every JSONL record is flushed immediately. Per-stage fsync would sit
        # inside the end-to-end timer and measure disk barriers, not Hanly.
        with RunStore(run_dir, metadata, fsync=False) as store:
            ProcessSampler(run_dir / "process.csv").run(0)
            try:
                with store.timed_sample(
                    evidence_class="measured",
                    scenario=scenario,
                    stage="runtime_validation",
                    iteration=0,
                    condition="cold",
                ):
                    runtime = load_runtime(args.config)

                ocr_config = _benchmark_ocr_config(runtime.easyocr_config, args)
                with store.timed_sample(
                    evidence_class="measured",
                    scenario=scenario,
                    stage="provider_initialization_ocr",
                    iteration=0,
                    condition="cold",
                ):
                    ocr = EasyOCRProvider(config=ocr_config)
                with store.timed_sample(
                    evidence_class="measured",
                    scenario=scenario,
                    stage="provider_initialization_kiwi",
                    iteration=0,
                    condition="cold",
                ):
                    morphology = KiwiProvider()
                with store.timed_sample(
                    evidence_class="measured",
                    scenario=scenario,
                    stage="provider_initialization_krdict",
                    iteration=0,
                    condition="cold",
                ):
                    dictionary = KRDICTProvider(runtime.krdict_path)

                pipeline = ObservedLookupPipeline(
                    ocr,
                    morphology,
                    dictionary,
                    store=store,
                    confidence_threshold=runtime.confidence_threshold,
                )
                if args.idle_seconds > 0:
                    report(
                        f"observing resident-provider idle state for {args.idle_seconds:g}s"
                    )
                    ProcessSampler(run_dir / "process.csv").run(args.idle_seconds)
                results = run_lookup_campaign(
                    pipeline,
                    image,
                    target,
                    store=store,
                    scenario=scenario,
                    plan=CampaignPlan(args.warmup, args.samples),
                    expected=ExpectedLookup(
                        status=args.expected_status,
                        text=args.expected_text,
                        lemma=args.expected_lemma,
                        headword=args.expected_headword,
                    ),
                )
                samples = store.read_samples()
                summaries = summarize_stages(samples)
                _write_json(run_dir / "summary.json", summaries)

                total_samples = [
                    sample for sample in samples if sample["stage"] == "total_pipeline"
                ]
                latest_total = int(total_samples[-1]["duration_ns"])
                snapshot = _snapshot(
                    pipeline,
                    results[-1],
                    image,
                    target,
                    latest_total,
                )
                prepared_image.save(run_dir / "input.png", format="PNG")
                write_diagnostic_json(snapshot, run_dir / "diagnostic.json")
                render_annotated_png(
                    prepared_image,
                    run_dir / "diagnostic.png",
                    snapshot,
                )
                render_diagnostic_html(snapshot, run_dir / "diagnostic.html")
                result_payload = _serialize_result(results[-1])
                _write_json(run_dir / "result.json", result_payload)

                failed = sum(
                    sample["correctness_status"] != "success"
                    for sample in total_samples
                )
                report(
                    f"completed {len(total_samples)} lookups; correctness failures={failed}"
                )
                if "total_pipeline" in summaries:
                    report(
                        "warm total p50={p50:.3f} ms p95={p95:.3f} ms".format(
                            p50=summaries["total_pipeline"]["p50"] / 1_000_000,
                            p95=summaries["total_pipeline"]["p95"] / 1_000_000,
                        )
                    )
                report(f"evidence: {run_dir}")
                return 1 if failed else 0
            except BaseException as error:
                report(f"campaign failed: {type(error).__name__}: {error}")
                raise
            finally:
                for provider in (dictionary, morphology, ocr):
                    close = getattr(provider, "close", None)
                    if callable(close):
                        close()
                prepared_image.close()


def run_package(args: argparse.Namespace) -> int:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = write_package_report(
        args.root,
        args.output,
        large_component_threshold_bytes=args.large_threshold,
        hash_duplicates=args.hash_duplicates,
        hash_max_files=args.hash_max_files,
        hash_max_bytes=args.hash_max_bytes,
    )
    print(
        f"analyzed {report['file_count']} files / {report['total_bytes']} bytes -> {args.output}"
    )
    return 0


def run_hover_rate(args: argparse.Namespace) -> int:
    matrix = hover_invocation_matrix(dwell_ms=args.dwell_ms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.output, matrix)
    print(f"wrote hover OCR invocation matrix -> {args.output}")
    return 0


def run_desktop_capture(args: argparse.Namespace) -> int:
    from hanly_app.capture import CaptureService
    from PyQt6.QtGui import QCursor

    cursor = QCursor.pos()
    service = CaptureService(roi_size=args.roi_size)
    try:
        report = measure_capture_service(
            service,
            cursor=Point(float(cursor.x()), float(cursor.y())),
            enumeration_samples=args.enumerations,
            capture_samples=args.captures,
        )
    finally:
        service.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.output, report)
    print(f"wrote desktop capture measurements -> {args.output}")
    return 0


def run_live_hover(args: argparse.Namespace) -> int:
    """Delegate to the live runner without importing desktop dependencies.

    The real runner is deliberately imported only after argument parsing and
    only when this command is executed.  That keeps ``--help`` and parser
    tests deterministic and prevents the benchmark package from becoming a
    runtime dependency of normal Hanly startup.  The implementation module is
    the seam owned by the live-benchmark composition work.
    """

    runner_module = importlib.import_module(".live_runner", package=__package__)
    return int(runner_module.run_live_hover(args))


def run_real_hover(args: argparse.Namespace) -> int:
    """Measure dwell-to-visible latency through the real resident controller."""

    image, target, prepared_image, transformation = prepare_roi(
        args.image,
        target=Point(args.target_x, args.target_y),
        size=args.roi_size,
    )
    scenario = f"real_hover_roi_{image.width}x{image.height}"
    metadata = build_metadata(
        repo_root=Path.cwd(),
        config={
            "runtime_config": args.config,
            "dwell_ms": args.dwell_ms,
            "cpu_threads": args.cpu_threads,
            "capture_source": "retained_static_fixture",
            "visible_endpoint": "development_qt_popup",
            "ledger_fsync": False,
        },
        scenario={
            "name": scenario,
            "image": args.image,
            "transformation": transformation,
            "warmup_samples": args.warmup,
            "warm_samples": args.samples,
        },
        versions=_versions(),
    )
    run_dir = args.output_root / str(metadata["run_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    log = (run_dir / "stdout.log").open("w", encoding="utf-8", newline="\n")

    def report(message: str) -> None:
        print(message)
        log.write(message + "\n")
        log.flush()

    report(f"Benchmark run {metadata['run_id']} ({scenario})")
    runtime = load_runtime(args.config)
    runtime = replace(
        runtime,
        easyocr_config=_benchmark_ocr_config(runtime.easyocr_config, args),
    )
    factory = runtime.create_worker_factory()
    counters = {"worker_constructions": 0, "lookup_invocations": 0}

    class CountingWorker:
        def __init__(self) -> None:
            counters["worker_constructions"] += 1
            self._delegate = factory()

        def __call__(self, request: Any) -> Any:
            counters["lookup_invocations"] += 1
            return self._delegate(request)

        def close(self) -> None:
            self._delegate.close()

    callbacks: queue.Queue[Any] = queue.Queue()
    delivered = threading.Event()
    latest_result: list[Any] = []
    current: dict[str, Any] = {}

    # Match production startup ordering: prepare the OCR native runtime before
    # importing Qt, then use the real popup widget and process its paint event.
    from hanly_app.ocr_preload import preload_ocr_runtime

    preload_ocr_runtime()
    from hanly_app.hover_controller import HoverController
    from hanly_app.lookup_controller import LookupController
    from hanly_app.popup import PopupPosition
    from hanly_app.qt_popup import QtPopupView
    from PyQt6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    popup = QtPopupView()

    with RunStore(run_dir, metadata, fsync=False) as store:
        ProcessSampler(run_dir / "process.csv").run(0)

        def on_result(result: Any) -> None:
            render_started = time.perf_counter_ns()
            popup.show_result(result, PopupPosition(20, 20))
            application.processEvents()
            render_duration = time.perf_counter_ns() - render_started
            visible = popup.isVisible()
            store.append_sample(
                evidence_class="measured",
                scenario=scenario,
                stage="popup_visible",
                iteration=current["iteration"],
                condition=current["condition"],
                duration_ns=render_duration,
                correctness_status="success" if visible else "failed",
                development_runtime=True,
            )
            latest_result[:] = [result]
            delivered.set()

        controller = LookupController(
            CountingWorker,
            on_result,
            result_dispatcher=callbacks.put,
            thread_name="benchmark-real-hover",
        )
        controller.start()

        def on_stable(_request: Any) -> None:
            dwell_duration = time.perf_counter_ns() - current["started_ns"]
            store.append_sample(
                evidence_class="measured",
                scenario=scenario,
                stage="dwell",
                iteration=current["iteration"],
                condition=current["condition"],
                duration_ns=dwell_duration,
                correctness_status="success",
                configured_dwell_ms=args.dwell_ms,
            )
            capture_started = time.perf_counter_ns()
            captured_image, captured_target = image, target
            capture_duration = time.perf_counter_ns() - capture_started
            store.append_sample(
                evidence_class="measured",
                scenario=scenario,
                stage="capture_static_fixture",
                iteration=current["iteration"],
                condition=current["condition"],
                duration_ns=capture_duration,
                correctness_status="success",
            )
            controller.submit(captured_image, captured_target)

        hover = HoverController(on_stable, delay_ms=args.dwell_ms)
        results: list[Any] = []
        try:
            for iteration, condition in enumerate(
                CampaignPlan(args.warmup, args.samples).conditions()
            ):
                delivered.clear()
                latest_result.clear()
                current.update(
                    iteration=iteration,
                    condition=condition,
                    started_ns=time.perf_counter_ns(),
                )
                hover.on_position(Point(target.x, target.y))
                deadline = time.monotonic() + args.timeout
                while not delivered.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("hover result did not become visible in time")
                    try:
                        callback = callbacks.get(timeout=min(0.05, remaining))
                    except queue.Empty:
                        application.processEvents()
                        continue
                    callback()
                result = latest_result[0]
                status = "success" if result.status.value == args.expected_status else "failed"
                store.append_sample(
                    evidence_class="measured",
                    scenario=scenario,
                    stage="perceived_hover_total",
                    iteration=iteration,
                    condition=condition,
                    duration_ns=time.perf_counter_ns() - current["started_ns"],
                    correctness_status=status,
                    endpoint="development_qt_popup_visible",
                    request_current=controller.current_request_id is not None,
                )
                results.append(result)
        finally:
            hover.shutdown()
            controller.stop(wait=True)
            popup.close()
            application.processEvents()

        samples = store.read_samples()
        summaries = summarize_stages(samples)
        _write_json(run_dir / "summary.json", summaries)
        _write_json(run_dir / "counts.json", counters)
        if results:
            _write_json(run_dir / "result.json", _serialize_result(results[-1]))
        prepared_image.save(run_dir / "input.png", format="PNG")
        prepared_image.close()

        failed = sum(
            sample["correctness_status"] != "success"
            for sample in samples
            if sample["stage"] == "perceived_hover_total"
        )
        report(
            f"completed {len(results)} visible hover traces; failures={failed}; "
            f"worker constructions={counters['worker_constructions']}; "
            f"lookup/OCR invocations={counters['lookup_invocations']}"
        )
        if "perceived_hover_total" in summaries:
            report(
                "warm perceived p50={p50:.3f} ms p95={p95:.3f} ms".format(
                    p50=summaries["perceived_hover_total"]["p50"] / 1_000_000,
                    p95=summaries["perceived_hover_total"]["p95"] / 1_000_000,
                )
            )
        report(f"evidence: {run_dir}")
    log.close()
    return 1 if failed else 0


def run_dev_hud(args: argparse.Namespace) -> int:
    """Start the real desktop with the on-screen HUD attached.

    Imported here rather than at module scope: this is the only command that
    needs Qt, and the others must stay runnable without it.
    """

    from .hud.session import run_hud_session

    return run_hud_session(
        runtime_config=args.config,
        app_config=args.app_config,
        roi_size=args.roi_size,
        dwell_ms=args.dwell_ms,
        show_roi=not args.no_roi,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    hud = subcommands.add_parser(
        "dev-hud",
        help="run the real Hanly desktop with the on-screen developer HUD",
    )
    hud.add_argument(
        "--config",
        type=Path,
        help="explicit runtime configuration; omit to use the normal per-user one",
    )
    hud.add_argument("--app-config", type=Path)
    hud.add_argument("--roi-size", type=_parse_size)
    hud.add_argument(
        "--dwell-ms",
        type=int,
        default=80,
        help="dwell the panel labels its timeline with (display only)",
    )
    hud.add_argument(
        "--no-roi",
        action="store_true",
        help="show only the panel, without the captured-region outline",
    )
    hud.set_defaults(handler=run_dev_hud)

    real = subcommands.add_parser("real-lookup", help="run real resident providers")
    real.add_argument("--image", type=Path, required=True)
    real.add_argument("--config", type=Path, required=True)
    real.add_argument("--target-x", type=float, required=True)
    real.add_argument("--target-y", type=float, required=True)
    real.add_argument("--roi-size", type=_parse_size)
    real.add_argument("--warmup", type=int, default=2)
    real.add_argument("--samples", type=int, default=30)
    real.add_argument("--idle-seconds", type=float, default=0.0)
    real.add_argument(
        "--enable-mkldnn",
        choices=("configured", "true", "false"),
        default="configured",
    )
    real.add_argument("--cpu-threads", type=_parse_cpu_threads)
    real.add_argument("--expected-status", default="SUCCESS")
    real.add_argument("--expected-text", default="읽습니다.")
    real.add_argument("--expected-lemma", default="읽다")
    real.add_argument("--expected-headword", default="읽다")
    real.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/benchmarks/runs"),
    )
    real.set_defaults(handler=run_real_lookup)

    hover = subcommands.add_parser(
        "real-hover", help="measure dwell through a visible development Qt popup"
    )
    hover.add_argument("--image", type=Path, required=True)
    hover.add_argument("--config", type=Path, required=True)
    hover.add_argument("--target-x", type=float, required=True)
    hover.add_argument("--target-y", type=float, required=True)
    hover.add_argument("--roi-size", type=_parse_size)
    hover.add_argument("--dwell-ms", type=float, default=150.0)
    hover.add_argument("--cpu-threads", type=_parse_cpu_threads)
    hover.add_argument("--warmup", type=int, default=2)
    hover.add_argument("--samples", type=int, default=10)
    hover.add_argument("--timeout", type=float, default=120.0)
    hover.add_argument("--expected-status", default="SUCCESS")
    hover.add_argument(
        "--output-root", type=Path, default=Path("artifacts/benchmarks/runs")
    )
    hover.set_defaults(handler=run_real_hover)

    live = subcommands.add_parser(
        "live-hover",
        help="measure the real desktop hover pipeline during a human session",
        description=(
            "Run a bounded interactive session over the real desktop. "
            "Use Ctrl+Alt+Shift+B to advance the scenario marker."
        ),
    )
    live.add_argument("--config", type=Path, required=True)
    live.add_argument(
        "--duration",
        type=_parse_live_duration,
        default=300,
        metavar="SECONDS",
        help="session duration in seconds (120-300; default: 300)",
    )
    live.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/benchmarks/runs"),
        help="directory in which the live run evidence directory is created",
    )
    live.add_argument(
        "--marker-hotkey",
        default="Ctrl+Alt+Shift+B",
        help="global scenario-marker hotkey (default: Ctrl+Alt+Shift+B)",
    )
    live.add_argument(
        "--retain-text",
        action="store_true",
        help="retain raw OCR text fields in the live trace (privacy-sensitive)",
    )
    live.add_argument(
        "--dwell-ms",
        type=float,
        default=150.0,
        help="development hover dwell setting recorded in the run metadata",
    )
    live.add_argument(
        "--cpu-threads",
        type=_parse_cpu_threads,
        help="explicit OCR CPU thread limit for this benchmark run",
    )
    live.set_defaults(handler=run_live_hover)

    rate = subcommands.add_parser(
        "hover-rate", help="count deterministic OCR triggers by hover condition"
    )
    rate.add_argument("--dwell-ms", type=float, default=150.0)
    rate.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/benchmarks/hover-invocation-rate.json"),
    )
    rate.set_defaults(handler=run_hover_rate)

    capture = subcommands.add_parser(
        "desktop-capture", help="measure real monitor enumeration and ROI capture"
    )
    capture.add_argument("--roi-size", type=_parse_size, default=(200, 100))
    capture.add_argument("--enumerations", type=int, default=100)
    capture.add_argument("--captures", type=int, default=30)
    capture.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/benchmarks/desktop-capture.json"),
    )
    capture.set_defaults(handler=run_desktop_capture)

    package = subcommands.add_parser("package", help="analyze one frozen package tree")
    package.add_argument("--root", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--large-threshold", type=int, default=50 * 1024 * 1024)
    package.add_argument("--hash-duplicates", action="store_true")
    package.add_argument("--hash-max-files", type=int, default=10_000)
    package.add_argument("--hash-max-bytes", type=int, default=2 * 1024**3)
    package.set_defaults(handler=run_package)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if getattr(args, "warmup", 0) < 0 or getattr(args, "samples", 0) < 0:
        raise SystemExit("--warmup and --samples must be non-negative")
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover - exercised as a module
    raise SystemExit(main())


__all__ = [
    "main",
    "prepare_roi",
    "run_desktop_capture",
    "run_hover_rate",
    "run_live_hover",
    "run_package",
    "run_real_hover",
    "run_real_lookup",
]
