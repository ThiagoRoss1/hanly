"""The Hanly Lab: run Hanly under observation, let the lab drive it, read the report.

  python -m lab               run Hanly; use it, quit it, the report opens
  python -m lab tour          the lab hovers lab-authored Korean and scores each answer
  python -m lab report        reopen the newest report (or name a run, or --list)

Everything else is a focused measurement campaign or the fixed regression checks.
Runs live under artifacts/lab/runs/.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import queue
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
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
from .identity import KINDS
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
        kind="real_lookup",
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
                    ProcessSampler(run_dir / "process.csv", append=True).run(
                        args.idle_seconds
                    )
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


def _ocr_provider_factory(
    args: argparse.Namespace,
) -> tuple[str, Callable[[], Any], Callable[[], Any] | None]:
    """Build exactly one recognizer, and the raw reader a staged mode needs.

    Selection is between recognizers that already exist. No mode here adds a
    backend, and none changes which one the product would pick.
    """

    from .ocr_benchmark import EASYOCR, VISION

    backend = str(args.backend)
    if backend == VISION:
        from hanly.vision_provider import VisionProvider

        if not VisionProvider.is_available():
            raise SystemExit("this machine provides no Apple Vision recognizer")
        return backend, VisionProvider, None

    config = EasyOCRConfig()
    if args.config is not None:
        runtime_config = load_runtime(args.config).easyocr_config
        if runtime_config is not None:
            config = runtime_config
    config = _benchmark_ocr_config(config, args)

    def reader() -> Any:
        from easyocr import Reader

        return Reader(**config.to_reader_kwargs())

    shared: list[Any] = []

    def shared_reader() -> Any:
        if not shared:
            shared.append(reader())
        return shared[0]

    return (
        EASYOCR,
        lambda: EasyOCRProvider(config, engine=shared_reader()),
        shared_reader,
    )


def run_ocr_campaign(args: argparse.Namespace) -> int:
    """Measure one OCR mode over a corpus, constructing nothing else."""

    from .corpus import inventory, load_corpus
    from .ocr_benchmark import run_campaign, write_samples

    corpus = load_corpus(args.manifest)
    if not corpus.cases:
        print(
            f"{args.manifest} holds no cases; see lab/fixtures/ocr/README.md "
            "for why the committed corpus can be empty and how to populate it"
        )
        return 2

    backend, provider_factory, reader_factory = _ocr_provider_factory(args)
    metadata = build_metadata(
        repo_root=Path.cwd(),
        kind="ocr_campaign",
        config={
            "mode": args.mode,
            "backend": backend,
            "manifest": str(args.manifest),
            "warmup": args.warmup,
            "samples": args.samples,
            "iou_threshold": args.iou_threshold,
            "cpu_threads": args.cpu_threads,
        },
        scenario={
            "name": f"ocr_{args.mode.replace('-', '_')}",
            "phases": ["cold", "warmup", "warm"],
            "endpoint": "normalized_ocr_results",
        },
        versions=_versions(),
    )
    run_dir = Path(args.output_root) / str(metadata["run_id"])
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / "metadata.json", metadata)
    _write_json(run_dir / "corpus-inventory.json", inventory(corpus))

    report = run_campaign(
        corpus,
        mode=args.mode,
        backend=backend,
        provider_factory=provider_factory,
        reader_factory=reader_factory,
        warmup=args.warmup,
        samples=args.samples,
        iou_threshold=args.iou_threshold,
    )
    write_samples(report, run_dir / "samples.jsonl")
    summary = report.summary()
    _write_json(run_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"evidence: {run_dir}")
    return 0


def run_corpus_inventory(args: argparse.Namespace) -> int:
    """Enumerate a corpus without loading an OCR runtime."""

    from .corpus import inventory, load_corpus

    if args.fonts:
        return _font_inventory()
    corpus = load_corpus(args.manifest, require_assets=not args.skip_assets)
    print(json.dumps(inventory(corpus), ensure_ascii=False, indent=2, sort_keys=True))
    for case in corpus.cases:
        print(f"  {case.case_id}  {case.provenance}  {','.join(case.tags)}")
    return 0


def _font_inventory() -> int:
    """Installed faces and the scripts each proves it can draw; nothing is installed."""

    from .synthetic_ocr import SCRIPT_PROBES, discover_faces

    faces = discover_faces(scripts=())
    for script in SCRIPT_PROBES:
        print(f"{script:7} {sum(script in face.scripts for face in faces)} faces")
    for face in faces:
        if "hangul" in face.scripts:
            print(
                f"  {face.family} {face.style} [{face.file}#{face.index}] "
                f"sha256 {face.sha256[:12]} scripts {','.join(face.scripts)} licence unknown"
            )
    return 0


def run_corpus_generate(args: argparse.Namespace) -> int:
    """Render the synthetic corpus, or say exactly why it cannot be rendered."""

    if args.profile is not None:
        return _generate_profile(args)

    from .corpus import SCHEMA_VERSION
    from .synthetic_ocr import (
        SyntheticFontError,
        corpus_entry,
        load_generator_config,
        render_sample,
        resolve_font,
        write_sample,
    )

    font, samples = load_generator_config(args.generator)
    try:
        resolved = resolve_font(font)
    except SyntheticFontError as error:
        print(f"refused: {error}")
        return 2

    destination = Path(args.output)
    cases = []
    for spec in samples:
        rendered = render_sample(spec)
        relative = f"generated/{spec.case_id}.png"
        write_sample(rendered, destination.parent / relative)
        cases.append(
            corpus_entry(rendered, relative, redistributable=resolved.redistributable)
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "distribution": "committed" if resolved.redistributable else "local",
        "description": (
            f"Synthetic Korean samples rendered from {font.name} ({font.licence})."
        ),
        "cases": cases,
    }
    _write_json(destination, manifest)
    print(
        f"rendered {len(cases)} samples from {resolved.path} "
        f"(sha256 {resolved.sha256[:16]}) into {destination}"
    )
    if not resolved.redistributable:
        print(
            f"{font.licence} does not permit redistribution, so these are "
            "local_synthetic cases and cannot enter a committed manifest"
        )
    return 0


def _generate_profile(args: argparse.Namespace) -> int:
    from .synthetic_profiles import OUTPUT_ROOT, generate

    destination = args.output_dir or OUTPUT_ROOT / f"{args.profile}-seed{args.seed}"
    if (destination / "manifest.json").exists():
        print(f"refused: {destination} already holds a corpus; pass another --output-dir")
        return 2
    result = generate(
        args.profile,
        destination,
        seed=args.seed,
        max_cases=args.max_cases,
        max_bytes=args.max_bytes,
    )
    cases = result.manifest["cases"]
    families = Counter(str(case.get("family", "unstated")) for case in cases)
    print(
        f"rendered {len(cases)} cases ({dict(families)}) into {destination}, "
        f"{result.bytes_written / 2**20:.1f} MiB; {len(result.omitted)} omitted"
    )
    for omitted in result.omitted[:20]:
        print(f"  omitted {omitted['case']}: {omitted['reason']}")
    return 0 if cases else 2


def run_package(args: argparse.Namespace) -> int:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = write_package_report(
        args.root,
        args.output,
        large_component_threshold_bytes=args.large_threshold,
        hash_duplicates=args.hash_duplicates,
        hash_max_files=args.hash_max_files,
        hash_max_bytes=args.hash_max_bytes,
        archive=args.archive,
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
    from hanly_app.acquisition.capture import CaptureService
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
        kind="real_hover",
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

    # OCR runs in this process here, unlike the desktop, so its native runtime
    # is prepared before Qt exactly as the lookup child prepares its own.
    from hanly_app.lookup.preload import preload_ocr_runtime

    preload_ocr_runtime()
    from hanly_app.hover.controller import HoverController
    from hanly_app.lookup.controller import LookupController
    from hanly_app.popup.presentation import PopupPosition
    from hanly_app.popup.qt import QtPopupView
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


def run_app_lab(args: argparse.Namespace) -> int:
    """List or execute app-wide checks with isolated profiles."""

    from .checks.catalog import SCENARIOS

    if args.lab_action == "list":
        for item in SCENARIOS:
            print(f"{item.id}: {item.title} [{item.evidence}]")
        return 0
    from .checks.runner import run_scenarios

    run_dir, summary = run_scenarios(
        tuple(args.scenario), bundle=args.bundle, expected_commit=args.expected_commit,
    )
    for item in summary["results"]:
        print(f"{item['id']}: {item['outcome']} ({item['reason']})")
    print(f"evidence: {run_dir}")
    return 1 if any(item["outcome"] != "passed" for item in summary["results"]) else 0


def _run_stress_replay(args: argparse.Namespace) -> int:
    from .session.runner import _runtime_config, resolve_run
    from .session.stress_replay import replay_run

    report = replay_run(resolve_run(args.run_dir), _runtime_config(args.config))
    print(
        f"lab: replayed {report['replayed']} regions; {report['same_as_live']} gave the live "
        f"outcome again ({report['label']})"
    )
    return 0


def _run_windows_update(args: argparse.Namespace) -> int:
    from .checks.windows_update import run_windows_update

    return run_windows_update(args.source_tag, args.mode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lab",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _session_parsers(subcommands)

    hud = subcommands.add_parser(
        "dev-hud",
        help="run the real Hanly desktop with the on-screen developer HUD",
    )

    lab = subcommands.add_parser(
        "check", help="run fixed regression scenarios on disposable profiles"
    )
    lab_actions = lab.add_subparsers(dest="lab_action", required=True)
    lab_list = lab_actions.add_parser("list", help="list scenarios and evidence limits")
    lab_list.set_defaults(handler=run_app_lab)
    lab_run = lab_actions.add_parser("run", help="run selected checks on disposable profiles")
    lab_run.add_argument("--scenario", action="append", required=True)
    lab_run.add_argument("--bundle", type=Path, help="explicit frozen application directory")
    lab_run.add_argument(
        "--expected-commit", help="complete source commit required by bundle identity"
    )
    lab_run.set_defaults(handler=run_app_lab)
    windows_update = lab_actions.add_parser(
        "windows-update",
        help="update an owned, isolated Windows installation of a published release",
        description=(
            "Unpack a published release into its own run directory, profile and TEMP, then "
            "update it with this checkout's updater against the real release source: "
            "install (commit), cancel (during preparation) or rollback (a staged build "
            "that cannot start)."
        ),
    )
    windows_update.add_argument("--from", dest="source_tag", default="v0.9.0")
    windows_update.add_argument(
        "--mode", choices=("install", "cancel", "rollback"), default="install"
    )
    windows_update.set_defaults(handler=_run_windows_update)

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
    real.add_argument("--cpu-threads", type=_parse_cpu_threads)
    real.add_argument("--expected-status", default="SUCCESS")
    real.add_argument("--expected-text", default="읽습니다.")
    real.add_argument("--expected-lemma", default="읽다")
    real.add_argument("--expected-headword", default="읽다")
    real.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/lab/runs"),
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
        "--output-root", type=Path, default=Path("artifacts/lab/runs")
    )
    hover.set_defaults(handler=run_real_hover)

    live = subcommands.add_parser(
        "live-hover",
        help="measure the real desktop hover pipeline during a human session",
        description=(
            "Run a bounded interactive session over the real desktop. "
            "Ctrl+Alt+Shift+B advances the scenario marker, Ctrl+Alt+Shift+F "
            "pins the newest completed lookup in memory, and Ctrl+Alt+Shift+E "
            "exports that pinned lookup. Only the export writes screen content."
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
        default=Path("artifacts/lab/runs"),
        help="directory in which the live run evidence directory is created",
    )
    live.add_argument(
        "--marker-hotkey",
        default="Ctrl+Alt+Shift+B",
        help="global scenario-marker hotkey (default: Ctrl+Alt+Shift+B)",
    )
    live.add_argument(
        "--freeze-hotkey",
        default="Ctrl+Alt+Shift+F",
        help=(
            "global hotkey that pins the newest completed lookup in memory "
            "(default: Ctrl+Alt+Shift+F); it writes nothing"
        ),
    )
    live.add_argument(
        "--export-hotkey",
        default="Ctrl+Alt+Shift+E",
        help=(
            "global hotkey that writes the pinned lookup's private evidence "
            "under the run directory (default: Ctrl+Alt+Shift+E)"
        ),
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
        default=Path("artifacts/lab/hover-invocation-rate.json"),
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
        default=Path("artifacts/lab/desktop-capture.json"),
    )
    capture.set_defaults(handler=run_desktop_capture)

    ocr = subcommands.add_parser(
        "ocr-campaign",
        help="measure one OCR mode over a corpus, constructing nothing else",
        description=(
            "Run OCR without Kiwi, KRDICT, LookupPipeline, hover, or UI. "
            "detection-only and recognition-only need separately addressable "
            "stages, which only EasyOCR exposes."
        ),
    )
    ocr.add_argument(
        "--mode",
        choices=("ocr-only", "detection-only", "recognition-only", "frozen-replay"),
        default="ocr-only",
    )
    ocr.add_argument("--backend", choices=("easyocr", "vision"), default="easyocr")
    ocr.add_argument(
        "--manifest",
        type=Path,
        default=Path("lab/fixtures/ocr/manifest.json"),
        help="corpus manifest to score (default: the committed one)",
    )
    ocr.add_argument("--config", type=Path, help="runtime config supplying EasyOCR options")
    ocr.add_argument("--warmup", type=int, default=1)
    ocr.add_argument(
        "--samples",
        "--repeats",
        dest="samples",
        type=int,
        default=3,
        help="warm repetitions per case; stability is summarized over these (default: 3)",
    )
    ocr.add_argument("--iou-threshold", type=float, default=0.5)
    ocr.add_argument("--cpu-threads", type=_parse_cpu_threads)
    ocr.add_argument(
        "--output-root", type=Path, default=Path("artifacts/lab/runs")
    )
    ocr.set_defaults(handler=run_ocr_campaign)

    corpus = subcommands.add_parser(
        "ocr-corpus", help="enumerate a corpus without loading an OCR runtime"
    )
    corpus.add_argument(
        "--manifest", type=Path, default=Path("lab/fixtures/ocr/manifest.json")
    )
    corpus.add_argument(
        "--fonts",
        action="store_true",
        help="list installed faces and the scripts each can draw, instead of a corpus",
    )
    corpus.add_argument(
        "--skip-assets",
        action="store_true",
        help="validate the manifest without requiring its images to be present",
    )
    corpus.set_defaults(handler=run_corpus_inventory)

    generate = subcommands.add_parser(
        "ocr-corpus-generate",
        help="render the synthetic Korean corpus from a licensed face",
        description=(
            "Refuses rather than substituting a face when the named one is not "
            "installed, and marks samples local_synthetic when its licence does "
            "not permit redistribution."
        ),
    )
    generate.add_argument(
        "--generator", type=Path, default=Path("lab/fixtures/ocr/generator.json")
    )
    generate.add_argument(
        "--output", type=Path, default=Path("lab/fixtures/ocr/manifest.json")
    )
    generate.add_argument(
        "--profile",
        choices=("golden", "smoke", "balanced", "difficult"),
        help=(
            "render a named profile from installed faces into gitignored local output "
            "instead of the committed generator description"
        ),
    )
    generate.add_argument("--seed", type=int, default=0, help="profile seed (default: 0)")
    generate.add_argument("--max-cases", type=int, help="case budget (default: per profile)")
    generate.add_argument(
        "--max-bytes", type=int, default=64 * 2**20, help="image byte budget (default: 64 MiB)"
    )
    generate.add_argument(
        "--output-dir", type=Path, help="profile output (default: artifacts/lab/corpus/...)"
    )
    generate.set_defaults(handler=run_corpus_generate)

    package = subcommands.add_parser("package", help="analyze one frozen package tree")
    package.add_argument("--root", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--large-threshold", type=int, default=50 * 1024 * 1024)
    package.add_argument("--hash-duplicates", action="store_true")
    package.add_argument("--hash-max-files", type=int, default=10_000)
    package.add_argument("--hash-max-bytes", type=int, default=2 * 1024**3)
    package.add_argument(
        "--archive",
        type=Path,
        help="optional ZIP archive to measure alongside the package tree",
    )
    package.set_defaults(handler=run_package)
    return parser


def _session_parsers(subcommands: Any) -> None:
    run = subcommands.add_parser(
        "run",
        help="run the real Hanly under observation; you use it, quit it, get a report",
        description=(
            "Start the real desktop on a disposable profile with every trace, startup "
            "phase and process recorded. Use Hanly normally, quit it from the tray or "
            "with Ctrl+C, and the report opens. No recognized text is retained."
        ),
    )
    _common_session_arguments(run)
    run.add_argument("--duration", type=float, help="quit by itself after SECONDS")
    run.add_argument("--hud", action="store_true", help="also draw the on-screen HUD")
    run.set_defaults(handler=run_lab_session, mode="run")

    tour = subcommands.add_parser(
        "tour",
        help="the lab uses Hanly itself: hovers lab-authored Korean and scores every answer",
        description=(
            "Covers the screen with lab-authored Korean, presses the real capture "
            "shortcut, glides the real pointer onto each word, and checks each popup "
            "against the known answer. Move the mouse yourself to stop it."
        ),
    )
    _common_session_arguments(tour)
    tour.add_argument(
        "--words",
        type=int,
        default=300,
        help="KRDICT headwords to hover (default: 300, the standard comparable tour)",
    )
    tour.add_argument(
        "--quick", action="store_true", help="a short smoke tour: 24 words, no story"
    )
    _baseline_option(tour, "tour")
    tour.add_argument(
        "--retain-fixture-text",
        action="store_true",
        help=(
            "also save what verified hovers read from the lab's own pages "
            "(default: only verdicts and text-free facts are saved)"
        ),
    )
    tour.add_argument(
        "--story-sizes",
        type=_parse_sizes,
        default=(22,),
        help="font pixel sizes for the story, comma separated; 0 skips it (default: 22)",
    )
    tour.add_argument(
        "--word-sizes", type=_parse_sizes, default=(16, 22, 30, 40),
        help="font pixel sizes cycled over words (default: 16,22,30,40)",
    )
    tour.add_argument("--seed", type=int, default=7, help="word sample seed (default: 7)")
    tour.add_argument("--hud", action="store_true", help="also draw the on-screen HUD")
    tour.set_defaults(handler=run_lab_session, mode="tour")

    report = subcommands.add_parser("report", help="rebuild and open a run's report")
    report.add_argument(
        "run_dir",
        nargs="?",
        help="run directory or name under artifacts/lab/runs (default: newest)",
    )
    report.add_argument("--list", action="store_true", help="list recorded runs and exit")
    report.add_argument(
        "--kind",
        choices=KINDS,
        help="with --list, only runs of this kind",
    )
    report.add_argument(
        "--limit", type=int, default=0, help="with --list, only the newest N (default: all)"
    )
    _baseline_option(report, "session")
    report.add_argument("--no-open", action="store_true")
    report.set_defaults(handler=run_lab_report)

    baseline = subcommands.add_parser(
        "baseline", help="list the registered baselines, or set or unset one"
    )
    baseline.set_defaults(handler=run_lab_baseline, baseline_action=None)
    baseline_actions = baseline.add_subparsers(dest="baseline_action")
    baseline_set = baseline_actions.add_parser(
        "set", help="make a finished, fully attributed run the baseline for its kind"
    )
    baseline_set.add_argument("run", help="run name under artifacts/lab/runs")
    baseline_set.add_argument("--reason", required=True)
    baseline_set.add_argument(
        "--allow-dirty", action="store_true", help="accept a run from a modified checkout"
    )
    baseline_set.add_argument(
        "--replace", action="store_true", help="replace the current baseline for the same key"
    )
    baseline_unset = baseline_actions.add_parser("unset", help="remove one run's baseline role")
    baseline_unset.add_argument("run")

    pin = subcommands.add_parser("pin", help="keep a run out of any clean-up")
    pin.add_argument("run")
    pin.add_argument("--reason", required=True)
    pin.set_defaults(handler=run_lab_pin, unpin=False)
    unpin = subcommands.add_parser("unpin", help="stop keeping a run (its files stay)")
    unpin.add_argument("run")
    unpin.set_defaults(handler=run_lab_pin, unpin=True)

    storage = subcommands.add_parser(
        "storage", help="show where Lab, packaging and unknown material use disk (read only)"
    )
    storage.add_argument("--json", action="store_true", help="print the full inventory as JSON")
    storage.add_argument("--top", type=int, default=15, help="largest entries to list")
    storage.set_defaults(handler=run_lab_storage)

    gc = subcommands.add_parser(
        "gc",
        help="preview (default) or apply removal of declared disposable working copies",
        description=(
            "Only subtrees a run's own writer declared disposable are eligible: an update "
            "check's unpacked installation, a stress run's browser profile. Run roots, "
            "recordings, reports, replay material and pinned, active or unknown runs are "
            "never touched, and dist/ is never collected."
        ),
    )
    gc.add_argument("--apply", action="store_true", help="delete exactly the given preview")
    gc.add_argument("--plan", type=Path, help="the plan file a preview wrote")
    gc.set_defaults(handler=run_lab_gc)

    stress = subcommands.add_parser(
        "stress",
        help="a seeded text-acquisition stress campaign over lab-authored pages",
        description=(
            "A fixed plan of more than a thousand hovers with a known answer for each: "
            "dictionary words across faces, sizes and themes, the story, cursor positions, "
            "dense and mixed lines, raster images, negatives (blank, numbers, punctuation, "
            "Latin, icons, illustrations), repeats, rapid moves, late answers, changing "
            "content, a covering window, and real accessible text read through UI "
            "Automation. Writes campaign.html beside the usual report."
        ),
    )
    _common_session_arguments(stress)
    stress.add_argument("--seed", type=int, default=11, help="campaign seed (default: 11)")
    _baseline_option(stress, "stress campaign")
    stress.add_argument(
        "--per-family", type=int, help="at most N hovers per family, for a short check"
    )
    stress.add_argument(
        "--corpus",
        type=Path,
        help=(
            "hover a controlled-image corpus manifest instead of the seeded plan, judged "
            "under corpus-surface-v1 (the selected word, not the dictionary answer)"
        ),
    )
    stress.add_argument(
        "--repeats", type=int, default=1, help="rounds over the corpus (default: 1)"
    )
    stress.add_argument(
        "--retain-fixture-text",
        action="store_true",
        help="also save what verified hovers read from the lab's own pages",
    )
    stress.add_argument(
        "--retain-fixture-images",
        action="store_true",
        help=(
            "save the region a failing verified hover captured, re-grabbed from the lab's "
            "own page, for an offline OCR replay"
        ),
    )
    stress.set_defaults(handler=run_lab_session, mode="stress", hud=False)

    replay = subcommands.add_parser(
        "stress-replay",
        help="replay a stress run's failing regions through the production lookup worker",
    )
    replay.add_argument("run_dir", help="stress run directory or name")
    replay.add_argument(
        "--config", type=Path, help="runtime configuration (default: the one `hanly` uses)"
    )
    replay.set_defaults(handler=_run_stress_replay)


def _baseline_option(parser: argparse.ArgumentParser, kind: str) -> None:
    parser.add_argument(
        "--baseline",
        nargs="?",
        const="registered",
        metavar="RUN",
        help=(
            f"earlier {kind} (directory or name) to compare with under the current rule; "
            "alone, the registered baseline for this run's kind and settings"
        ),
    )


def _common_session_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", type=Path, help="runtime configuration (default: the one `hanly` uses)"
    )
    parser.add_argument(
        "--backend", choices=("auto", "vision", "easyocr"), help="text recognizer for this run"
    )
    parser.add_argument("--no-open", action="store_true", help="do not open the report")


def _parse_sizes(value: str) -> tuple[int, ...]:
    try:
        sizes = tuple(int(part) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("sizes are comma-separated integers") from error
    if any(size < 0 or size > 200 for size in sizes):
        raise argparse.ArgumentTypeError("sizes must be between 0 and 200 pixels")
    return tuple(size for size in sizes if size > 0)


def run_lab_session(args: argparse.Namespace) -> int:
    """Run the real desktop under observation, driven by a person or by the lab."""

    from .session.runner import SessionOptions, run_session

    quick = getattr(args, "quick", False)
    return run_session(
        SessionOptions(
            mode=args.mode,
            baseline=_baseline_argument(getattr(args, "baseline", None)),
            retain_fixture_text=getattr(args, "retain_fixture_text", False),
            runtime_config=args.config,
            duration=getattr(args, "duration", None),
            hud=args.hud,
            open_report=not args.no_open,
            story_sizes=() if quick else getattr(args, "story_sizes", ()),
            words=24 if quick else getattr(args, "words", 0),
            word_sizes=getattr(args, "word_sizes", (16, 22, 30, 40)),
            seed=getattr(args, "seed", 7),
            backend=args.backend,
            retain_fixture_images=getattr(args, "retain_fixture_images", False),
            per_family=getattr(args, "per_family", None),
            corpus=getattr(args, "corpus", None),
            repeats=getattr(args, "repeats", 1),
        )
    )


def run_lab_report(args: argparse.Namespace) -> int:
    """Rebuild one session's report from what it recorded, or list every run."""

    import webbrowser

    from .identity import run_identity
    from .report.build import build_report
    from .session.runner import RUNS_ROOT, recorded_runs

    if args.list:
        return _list_runs(args.kind, args.limit)
    if args.run_dir is None:
        runs = recorded_runs()
        if not runs:
            raise SystemExit(
                f"lab: no recorded run under {RUNS_ROOT}; start one with `python -m lab`"
            )
        run_dir = runs[-1]
    else:
        run_dir = _session_or_explain(args.run_dir)
    baseline = _baseline_argument(args.baseline)
    report = build_report(run_dir, baseline=baseline)
    print(f"lab: report {report}")
    if run_identity(run_dir).kind == "stress":
        from .report.campaign import build_campaign

        build_campaign(run_dir, baseline=baseline)
        report = run_dir / "campaign.html"
        print(f"lab: campaign {report}")
    if not args.no_open:
        webbrowser.open(report.resolve().as_uri())
    return 0


def _baseline_argument(value: str | None) -> Path | str | None:
    """A named earlier session, or the registered baseline when the flag stood alone."""

    from .report.build import REGISTERED
    from .session.runner import resolve_run

    if value is None or value == REGISTERED:
        return value
    return resolve_run(value)


def _session_or_explain(name: str) -> Path:
    """A session to rebuild; any other kind is pointed at the summary it already wrote."""

    from .identity import resolve_name, run_identity
    from .session.runner import resolve_run

    try:
        identity = run_identity(resolve_name(name))
    except ValueError:
        return resolve_run(name)
    if identity.kind in {"run", "tour", "stress"}:
        return identity.path
    written = [file for file, present in identity.evidence.items() if present]
    raise SystemExit(
        f"lab: {identity.name} is kind {identity.kind}, not a session; its own evidence is "
        f"{', '.join(written) or 'missing'} (nothing to rebuild)"
    )


def _list_runs(kind: str | None, limit: int) -> int:
    from .identity import identities
    from .pins import load

    registry = load()
    # Start times order every kind; a run that records none sorts first by name.
    rows = sorted(
        (identity for identity in identities() if kind is None or identity.kind == kind),
        key=lambda identity: (identity.started != "unknown", identity.started[:19], identity.name),
    )
    for identity in rows[-limit:] if limit else rows:
        roles = ",".join(sorted(registry.roles(identity.name)))
        print(
            f"{identity.name:38} {identity.kind:12} {identity.commit[:8]:8} "
            f"{identity.source_state:7} {identity.system}-{identity.machine:7} "
            f"{identity.backend:14} {identity.completion:15} {roles}"
        )
    return 0


def run_lab_baseline(args: argparse.Namespace) -> int:
    """List, register or remove baselines in the local registry."""

    from . import pins

    try:
        registry = pins.load()
        if args.baseline_action == "set":
            _, identity, replaced = pins.set_baseline(
                registry,
                args.run,
                args.reason,
                allow_dirty=args.allow_dirty,
                replace=args.replace,
            )
            print(f"lab: {identity.name} is the baseline for {identity.compatibility_key}")
            if replaced is not None:
                print(f"lab: it replaces {replaced.run} (that run's files are untouched)")
            return 0
        if args.baseline_action == "unset":
            pins.remove(registry, args.run, "baseline")
            print(f"lab: {args.run} is no longer a baseline; its files are untouched")
            return 0
    except pins.PinError as error:
        print(f"lab: {error}", file=sys.stderr)
        return 2
    for row in pins.describe(registry, registry.baselines()):
        where = "MISSING" if row.get("dangling") else row["key"]
        print(f"{row['run']:38} {where}  -- {row['reason']}")
    return 0


def run_lab_storage(args: argparse.Namespace) -> int:
    """Where the disk goes: Lab, packaging and unknown material, read only."""

    from .storage import inventory

    report = inventory()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    for name, bucket in report["totals"].items():
        print(f"{name:24} {_gib(bucket['bytes']):>9}  {bucket['entries']} entries")
    print(f"{'total':24} {_gib(report['total_bytes']):>9}")
    print()
    largest = sorted(report["entries"], key=lambda entry: entry["size"]["bytes"], reverse=True)
    for entry in largest[: args.top]:
        protection = ",".join(entry["protection"]) or "-"
        print(
            f"{_gib(entry['size']['bytes']):>9}  {entry['ownership']:9} {entry['kind']:14} "
            f"{protection:16} {entry['path']}"
        )
    for name in report["dangling_pins"]:
        print(f"pinned but missing: {name}")
    print(f"\n{report['note']}; `python -m lab gc` previews what may be reclaimed")
    return 0


def run_lab_gc(args: argparse.Namespace) -> int:
    """Preview, or apply exactly, the removal of declared disposable working copies."""

    from .storage import StorageError, apply, preview, write_plan

    try:
        if not args.apply:
            plan = preview()
            for target in plan["targets"]:
                print(f"reclaim {_gib(target['bytes']):>9}  {target['run']}/{target['subtree']}")
            for kept in plan["kept"]:
                print(f"keep               {kept['run']}/{kept['subtree']}: {kept['reason']}")
            print(f"\n{_gib(plan['reclaimable_bytes'])} reclaimable; nothing was deleted.")
            if plan["targets"]:
                path = write_plan(plan)
                print(f"To delete exactly this: python -m lab gc --apply --plan {path}")
            return 0
        if args.plan is None:
            raise StorageError("--apply needs the --plan a preview wrote")
        result = apply(args.plan)
    except StorageError as error:
        print(f"lab: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "complete" else 1


def _gib(size: int) -> str:
    return f"{size / 2**30:.2f} GiB" if size >= 2**30 else f"{size / 2**20:.1f} MiB"


def run_lab_pin(args: argparse.Namespace) -> int:
    """Keep a run out of any clean-up, or stop keeping it."""

    from . import pins

    try:
        registry = pins.load()
        if args.unpin:
            pins.remove(registry, args.run, "keep")
            print(f"lab: {args.run} is no longer kept; its files are untouched")
        else:
            pins.keep(registry, args.run, args.reason or "")
            print(f"lab: keeping {args.run}")
    except pins.PinError as error:
        print(f"lab: {error}", file=sys.stderr)
        return 2
    return 0


def with_default_verb(arguments: Sequence[str]) -> list[str]:
    """Like `hanly`, the lab's one obvious action needs no verb."""

    arguments = list(arguments)
    if not arguments or (arguments[0].startswith("-") and arguments[0] not in {"-h", "--help"}):
        return ["run", *arguments]
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(with_default_verb(sys.argv[1:] if argv is None else argv))
    if getattr(args, "warmup", 0) < 0 or getattr(args, "samples", 0) < 0:
        raise SystemExit("--warmup and --samples must be non-negative")
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover - exercised as a module
    raise SystemExit(main())


__all__ = [
    "main",
    "prepare_roi",
    "run_corpus_generate",
    "run_corpus_inventory",
    "run_desktop_capture",
    "run_hover_rate",
    "run_ocr_campaign",
    "run_live_hover",
    "run_package",
    "run_real_hover",
    "run_real_lookup",
]
