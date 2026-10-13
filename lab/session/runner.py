"""Launch the native desktop under observation and turn the session into a report.

Hanly runs as an external Tauri process. Lab observes its bounded trace stream
and samples the owned desktop family separately from the Qt fixture harness.
Each run has a disposable profile; the selected runtime configuration and its
dictionary and OCR models are reused read only.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import threading
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from hanly_app.config import AppConfig, ConfigManager, HoverActivation
from hanly_app.paths import default_app_config_path, default_runtime_config_path

from ..identity import RUNS_ROOT, fingerprint
from ..metadata import SESSION_MEASUREMENT_PROTOCOL, provenance, source_identity
from .browser_text import FOLDER as BROWSER_FOLDER
from .desktop_process import DesktopProcess, desktop_executable, is_debug_executable
from .recorder import LabRecorder, is_content_field

REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_RUNTIME = REPO_ROOT / "resources" / "dev" / "runtime-local.json"
#: Lab sessions; the runs root also holds older campaign evidence.
_SESSION_NAME = re.compile(r"^\d{8}-\d{6}-(run|tour|stress)$")


@dataclass(frozen=True)
class SessionOptions:
    mode: str  # "run" (a person drives), "tour" or "stress" (the lab drives)
    runtime_config: Path | None = None
    app_config: Path | None = None
    desktop: Path | None = None
    output_root: Path | None = None
    duration: float | None = None
    roi_size: tuple[int, int] | None = None
    hover_delay_ms: int | None = None
    hud_dwell_ms: int = 80
    show_roi: bool = True
    cpu_threads: int | None = None
    hover_timeout: float | None = None
    hud: bool = False
    open_report: bool = True
    story_sizes: tuple[int, ...] = (22,)
    words: int = 0
    word_sizes: tuple[int, ...] = (16, 22, 30, 40)
    seed: int = 7
    backend: str | None = None
    #: An earlier run, or ``"registered"`` for the registry's baseline for this run's key.
    baseline: Path | str | None = None
    #: Persist what verified tour hovers read (lab-authored text only).
    retain_fixture_text: bool = False
    #: Keep the region a failing verified stress hover captured, for an offline replay.
    retain_fixture_images: bool = False
    #: At most this many hovers per stress family; ``None`` runs the whole plan.
    per_family: int | None = None
    #: A controlled-image corpus manifest to hover instead of the seeded plan.
    corpus: Path | None = None
    #: Rounds over the corpus.
    repeats: int = 1

    @property
    def drives(self) -> bool:
        return self.mode in {"tour", "stress"}


def recorded_runs() -> list[Path]:
    """Recorded runs, oldest first. Names start with their start time; rebuilding a
    report changes a directory's modification time, so that is not used."""

    if not RUNS_ROOT.is_dir():
        return []
    return sorted(
        path
        for path in RUNS_ROOT.iterdir()
        if _SESSION_NAME.match(path.name) and (path / "events.jsonl").is_file()
    )


def resolve_run(name: str | Path) -> Path:
    """A run directory given as a path or as a bare name under the runs root."""

    for candidate in (Path(name), RUNS_ROOT / str(name)):
        if (candidate / "events.jsonl").is_file():
            return candidate
    raise SystemExit(f"lab: {name} is not a recorded run; `python -m lab report --list` shows them")


def run_session(options: SessionOptions) -> int:
    if options.mode == "tour" and options.words <= 0 and not options.story_sizes:
        raise SystemExit("lab: a tour needs at least one story target or dictionary word")

    runtime_config = _runtime_config(options.runtime_config)
    user_settings = _read_user_settings(options.app_config or default_app_config_path())
    if options.drives:
        _require_tour_prerequisites(user_settings)
    plan = _stress_plan(options, runtime_config) if options.mode == "stress" else None
    executable = desktop_executable(options.desktop, REPO_ROOT)
    if options.drives and not is_debug_executable(executable, REPO_ROOT):
        raise SystemExit(
            "lab: driven tours require this checkout's debug Hanly binary so verified "
            "fixture evidence can stay in memory"
        )

    run_root = (
        RUNS_ROOT
        if options.output_root is None
        else options.output_root.expanduser().resolve()
    )
    run_dir = run_root / f"{datetime.now():%Y%m%d-%H%M%S}-{options.mode}"
    profile = run_dir / "profile"
    profile.mkdir(parents=True)
    app_config = profile / "config.json"
    settings = _lab_settings(user_settings, options)
    ConfigManager(app_config).save(settings)

    recorder = LabRecorder(
        run_dir / "events.jsonl",
        # The service provides evidence only to the verified Lab driver in memory.
        retain_evidence=options.drives,
        retain_geometry=options.drives,
    )
    started = datetime.now().isoformat(timespec="seconds")
    source = source_identity(REPO_ROOT)
    _write_json(
        run_dir / "metadata.json",
        _metadata(options, runtime_config, settings, started, source, plan),
    )
    print(f"lab: recording to {_display(run_dir)}", flush=True)

    from .sampler import ProcessSampler

    needs_qt = options.drives or options.hud
    application = None
    if needs_qt:
        from .qt import create_application

        application = create_application()

    sampler = ProcessSampler(
        run_dir / "processes.jsonl", recorder.origin_ns, sample_parent=False
    )
    environment = _desktop_environment(profile, options, executable)
    desktop = DesktopProcess(
        executable,
        runtime_config=runtime_config,
        app_config=app_config,
        environment=environment,
        recorder=recorder,
        sampler=sampler,
        repo_root=REPO_ROOT,
        roi_size=options.roi_size,
    )
    closers: list[Any] = []
    if options.hud:
        if application is None:
            raise RuntimeError("the Lab HUD requires its Qt harness")
        from ..hud.session import _resolved_backend

        for sink in _hud(
            application,
            settings,
            closers,
            dwell_ms=options.hud_dwell_ms,
            backend=_resolved_backend(runtime_config),
            show_roi=options.show_roi,
        ):
            recorder.subscribe(_listener(sink))
    start_driver = None
    if options.mode == "tour":
        start_driver = _start_tour(options, recorder, settings, runtime_config, closers)
    elif plan is not None:
        start_driver = _start_stress(options, plan, recorder, settings, run_dir, closers)

    recorder.lab("session_started", mode=options.mode)
    exit_code = 1
    duration_timer: threading.Timer | None = None
    try:
        sampler.start()
        desktop.start(
            retain_evidence=recorder.retain_evidence,
            retain_geometry=recorder.retain_geometry,
        )
        if start_driver is not None:
            start_driver(desktop)
        if application is not None:
            from PyQt6.QtCore import QTimer

            poller = QTimer(application)
            poller.setInterval(100)

            def poll_desktop() -> None:
                nonlocal exit_code
                result = desktop.poll()
                if result is None:
                    return
                exit_code = result
                poller.stop()
                application.quit()

            poller.timeout.connect(poll_desktop)
            poller.start()
            if options.duration:
                def stop_after_duration() -> None:
                    recorder.lab("session_duration_reached", seconds=options.duration)
                    desktop.request_stop()

                QTimer.singleShot(max(1, int(options.duration * 1000)), stop_after_duration)
            application.exec()
            if desktop.poll() is None:
                desktop.request_stop()
            result = desktop.poll()
            if result is None:
                result = desktop.wait(timeout=10)
            exit_code = result
        else:
            if options.duration:
                def stop_after_duration() -> None:
                    recorder.lab("session_duration_reached", seconds=options.duration)
                    desktop.request_stop()

                duration_timer = threading.Timer(options.duration, stop_after_duration)
                duration_timer.daemon = True
                duration_timer.start()
            exit_code = desktop.wait()
    except KeyboardInterrupt:
        desktop.request_stop()
        try:
            exit_code = desktop.wait(timeout=10)
        except Exception:
            exit_code = 130
    except Exception as error:
        recorder.lab("desktop_launch_failed", reason=type(error).__name__)
        print(f"lab: Hanly could not start ({type(error).__name__})", file=sys.stderr)
        exit_code = 1
    finally:
        if duration_timer is not None:
            duration_timer.cancel()
        cleanup = desktop.cleanup()
        if cleanup["survivors"]:
            recorder.lab("desktop_children_reaped", **cleanup)
        exit_code = _driven_exit_code(options.mode, exit_code, recorder.counts)
        recorder.lab("session_ended", exit_code=exit_code)
        for close in closers:
            try:
                close()
            except Exception:
                continue
        sampler.stop()
        recorder.close()
        _write_json(
            run_dir / "metadata.json",
            {
                **_metadata(
                    options,
                    runtime_config,
                    settings,
                    started,
                    source,
                    plan,
                    source_at_end=source_identity(REPO_ROOT),
                ),
                "exit_code": exit_code,
                "desktop": {
                    "build": "debug" if is_debug_executable(executable, REPO_ROOT) else "packaged",
                    "trace_lines": desktop.trace_lines,
                    "invalid_trace_lines": desktop.invalid_trace_lines,
                    "ignored_output_lines": desktop.ignored_output_lines,
                    "process_attribution": desktop.responsibility_attribution,
                },
                "dropped_events": recorder.dropped_events,
                "process_samples": sampler.samples,
                "process_access_denied": sampler.denied,
            },
        )

    from ..report.build import build_report

    report = build_report(run_dir, baseline=options.baseline)
    print(f"lab: report {_display(report)}  (summary: {_display(run_dir / 'summary.md')})")
    score = _score_line(run_dir)
    if score:
        print(f"lab: {score}", flush=True)
    if plan is not None:
        from ..report.campaign import build_campaign

        campaign = build_campaign(run_dir, baseline=options.baseline)
        report = run_dir / "campaign.html"
        print(f"lab: {_campaign_line(campaign)}; {_display(report)}", flush=True)
    if options.open_report:
        webbrowser.open(report.as_uri())
    return exit_code


def _driven_exit_code(mode: str, process_exit_code: int, counts: dict[str, int]) -> int:
    """Keep failed driven sessions from looking like successful app exits."""

    if mode not in {"tour", "stress"} or process_exit_code != 0:
        return process_exit_code
    if counts.get("tour_aborted", 0):
        return 2
    if not (counts.get("tour_finished", 0) or counts.get("tour_stopped_by_user", 0)):
        return 2
    return process_exit_code


def _score_line(run_dir: Path) -> str | None:
    try:
        tour = json.loads((run_dir / "report.json").read_text(encoding="utf-8")).get("tour")
    except (OSError, ValueError):
        return None
    if not tour or tour.get("accuracy") is None:
        return None
    completion = tour.get("completion") or {}
    ended = completion.get("ended")
    partial = (
        ""
        if ended == "finished"
        else f"; {ended} after {completion.get('hovered')} of {completion.get('planned')} planned"
    )
    return (
        f"tour {tour['passed']}/{tour['scored']} ({tour['accuracy']:.1%}) under {tour['rule']}, "
        f"{tour['unscored']} not scored{partial}"
    )


def _require_tour_prerequisites(settings: AppConfig) -> None:
    """Refuse before taking the pointer, with what to do about it."""

    problems = []
    if sys.platform not in {"darwin", "win32"}:
        problems.append(
            "a tour cannot verify window ownership on this platform, so nothing would be scored"
        )
    if not settings.capture_hotkey:
        problems.append("the Start/Stop Capture shortcut is unbound; bind it in Hanly's settings")
    if problems:
        detail = "\n  - ".join(problems)
        raise SystemExit(
            f"lab: the tour cannot start:\n  - {detail}\n"
            "macOS: System Settings > Privacy & Security, then restart the terminal."
        )


# -- profile and settings -------------------------------------------------------


def _runtime_config(explicit: Path | None) -> Path:
    """The configuration ``hanly`` itself would use, resolved before isolation."""

    if explicit is not None:
        return explicit.expanduser().resolve()
    for candidate in (default_runtime_config_path(), _DEV_RUNTIME):
        if candidate.is_file():
            return candidate.resolve()
    raise SystemExit(
        "lab: no runtime configuration; launch `hanly` once, or pass --config "
        "resources/dev/runtime-local.json"
    )


def _read_user_settings(path: Path) -> AppConfig:
    if not path.is_file():
        return AppConfig()
    try:
        return ConfigManager(path).load()
    except Exception:
        return AppConfig()


def _desktop_environment(
    profile: Path, options: SessionOptions, executable: Path
) -> dict[str, str]:
    """Build a disposable child environment without changing Lab's own paths."""

    environment = os.environ.copy()
    environment["XDG_CONFIG_HOME"] = str(profile)
    environment["XDG_DATA_HOME"] = str(profile / "data")
    environment["LOCALAPPDATA"] = str(profile)
    environment["APPDATA"] = str(profile)
    if options.cpu_threads is not None:
        for name in (
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            environment[name] = str(options.cpu_threads)
    environment.pop("HANLY_DESKTOP_SERVICE_MODULE", None)
    environment.pop("HANLY_LAB_RETAIN_EVIDENCE", None)
    environment.pop("HANLY_LAB_RETAIN_GEOMETRY", None)
    if is_debug_executable(executable, REPO_ROOT) and (options.drives or options.hud):
        environment["HANLY_DESKTOP_SERVICE_MODULE"] = "lab.service_observer"
        if options.drives:
            environment["HANLY_LAB_RETAIN_EVIDENCE"] = "1"
            environment["HANLY_LAB_RETAIN_GEOMETRY"] = "1"
        elif options.hud:
            environment["HANLY_LAB_RETAIN_GEOMETRY"] = "1"
    return environment


def _lab_settings(user: AppConfig, options: SessionOptions) -> AppConfig:
    settings = replace(user, update_checks_enabled=False)
    if options.backend:
        from hanly_app.config import OCRBackend

        settings = replace(settings, ocr_backend=OCRBackend(options.backend))
    if options.drives:
        # The lab cannot hold a chord while it glides the pointer.
        settings = replace(settings, hover_activation=HoverActivation.ALWAYS_ACTIVE)
    if options.hover_delay_ms is not None:
        settings = replace(settings, hover_delay_ms=options.hover_delay_ms)
    return settings


# -- the tour and timed sessions ---------------------------------------------------


def _start_tour(
    options: SessionOptions,
    recorder: LabRecorder,
    settings: AppConfig,
    runtime_config: Path,
    closers: list[Any],
) -> Any:
    from .corpus import story_targets, word_targets
    from .driver import TourDriver
    from .page import TourPage

    story = story_targets() if options.story_sizes else []
    words = word_targets(_krdict(runtime_config), options.words, seed=options.seed)
    page = TourPage()
    page.lay_out(story, words, list(options.story_sizes), list(options.word_sizes))
    total = sum(len(p.placed) for p in page.pages)
    recorder.lab(
        "tour_planned",
        pages=len(page.pages),
        targets=total,
        plan_fingerprint=plan_fingerprint(page.pages),
        display_scale=page.devicePixelRatioF(),
    )
    print(f"lab: tour of {total} hovers over {len(page.pages)} pages", flush=True)
    closers.append(page.close)

    def start(desktop: DesktopProcess) -> None:
        desktop_pid = desktop.process.pid if desktop.process is not None else None
        driver = TourDriver(
            recorder,
            page,
            capture_hotkey=settings.capture_hotkey,
            retain_fixture_text=options.retain_fixture_text,
            owned_pids=set() if desktop_pid is None else {desktop_pid},
            settle_timeout=options.hover_timeout or 4.0,
            first_timeout=options.hover_timeout or 90.0,
        )

        def drive() -> None:
            try:
                driver.run()
            except Exception as error:
                import traceback

                traceback.print_exc()
                recorder.lab("tour_aborted", reason=type(error).__name__)
            finally:
                recorder.lab("tour_driver_finished", completed=driver.completed)
                desktop.request_stop()

        threading.Thread(target=drive, name="lab-tour", daemon=True).start()

    return start


def _stress_plan(options: SessionOptions, runtime_config: Path) -> list[Any]:
    """The seeded campaign, trimmed per family when a short run was asked for."""

    from .stress import corpus_plan, stress_plan

    if options.corpus is not None:
        items, omitted = corpus_plan(options.corpus, options.repeats)
        for entry in omitted:
            print(f"lab: corpus case {entry['case']} omitted: {entry['reason']}", flush=True)
        if not items:
            raise SystemExit("lab: the corpus holds no case with a stated target and pointer")
        return items

    plan = stress_plan(_krdict(runtime_config), seed=options.seed)
    if options.per_family is None:
        return plan
    taken: dict[str, int] = {}
    trimmed = []
    for item in plan:
        if taken.get(item.family, 0) < options.per_family:
            taken[item.family] = taken.get(item.family, 0) + 1
            trimmed.append(item)
    # A repeat needs the hover it repeats.
    kept = {item.target.id for item in trimmed}
    return [item for item in trimmed if item.repeat_of is None or item.repeat_of in kept]


def _start_stress(
    options: SessionOptions,
    plan: list[Any],
    recorder: LabRecorder,
    settings: AppConfig,
    run_dir: Path,
    closers: list[Any],
) -> Any:
    from .stress_driver import StressDriver
    from .stress_page import StressPage

    page = StressPage()
    uia = [item for item in plan if item.family in {"uia_korean", "uia_latin"}]
    page.lay_out_plan(plan, options.seed)
    for omitted in page.omitted:
        recorder.lab("tour_target_omitted", **omitted)
    total = sum(len(p.placed) for p in page.pages) + len(uia)
    recorder.lab(
        "tour_planned",
        pages=len(page.pages),
        targets=total,
        plan_fingerprint=plan_fingerprint(page.pages, uia),
        # Physical pixels per point of the page: what a 1:1 painted image is drawn at.
        display_scale=page.devicePixelRatioF(),
    )
    print(f"lab: stress campaign of {total} hovers over {len(page.pages)} pages", flush=True)
    closers.append(page.close)

    def start(desktop: DesktopProcess) -> None:
        desktop_pid = desktop.process.pid if desktop.process is not None else None
        driver = StressDriver(
            recorder,
            page,
            uia,
            capture_hotkey=settings.capture_hotkey,
            run_dir=run_dir,
            retain_fixture_text=options.retain_fixture_text,
            retain_fixture_images=options.retain_fixture_images,
            owned_pids=set() if desktop_pid is None else {desktop_pid},
            settle_timeout=options.hover_timeout or 4.0,
            first_timeout=options.hover_timeout or 90.0,
        )

        def drive() -> None:
            try:
                driver.run()
            except Exception as error:
                import traceback

                traceback.print_exc()
                recorder.lab("tour_aborted", reason=type(error).__name__)
            finally:
                recorder.lab("tour_driver_finished", completed=driver.completed)
                desktop.request_stop()

        threading.Thread(target=drive, name="lab-stress", daemon=True).start()

    return start


def _campaign_line(campaign: dict[str, Any]) -> str:
    summary = campaign["summary"]
    accuracy = summary["accuracy"]
    return (
        f"stress {summary['passed']}/{summary['scored']}"
        + ("" if accuracy is None else f" ({accuracy:.1%})")
        + f" under {campaign['rule']}; planned {campaign['planned_total']}, executed "
        f"{summary['executed']}, unscored {summary['unscored']}; false presentations "
        f"{summary['false_positives']}/{summary['negatives_scored']} (and "
        f"{summary['negatives_failed_otherwise']} timed out or errored), missing or wrong "
        f"{summary['missing_answers']}/{summary['positives_scored']}; ended {campaign['ended']}"
    )


def plan_fingerprint(pages: Sequence[Any], unplaced: Sequence[Any] = ()) -> str:
    """Every hover as rendered on this machine: target, face, size, theme, family."""

    def item_fields(item: Any) -> list[Any]:
        if item is None:
            return []
        return [item.family, item.behavior, item.raster, item.graphic, item.replacement]

    rows = [
        [
            placed.target.id,
            placed.target.surface,
            placed.target.cursor,
            placed.font_family,
            placed.font_px,
            placed.theme,
            *item_fields(getattr(placed, "item", None)),
        ]
        for page in pages
        for placed in page.placed
    ]
    rows += [[item.target.id, item.target.surface, *item_fields(item)] for item in unplaced]
    return fingerprint(rows)


def _krdict(runtime_config: Path) -> Path:
    raw = json.loads(runtime_config.read_text(encoding="utf-8"))
    path = Path(raw["resources"]["krdict"]["path"]).expanduser()
    return path if path.is_absolute() else (runtime_config.parent / path).resolve()


# -- the HUD ---------------------------------------------------------------------


def _listener(sink: Any) -> Any:
    """Give Lab-owned visual tools only geometry-free, text-free trace fields."""

    def receive(name: str, _observed_ns: int, fields: Any) -> None:
        event = {"event_kind": name}
        event.update({key: value for key, value in fields.items() if not is_content_field(key)})
        sink.emit(event)

    return receive


def _hud(
    application: Any,
    settings: AppConfig,
    closers: list[Any],
    *,
    dwell_ms: int,
    backend: str,
    show_roi: bool,
) -> list[Any]:
    from PyQt6.QtCore import QRect

    from ..hud.capture_overlay import CaptureOverlay
    from ..hud.hover_hud import HoverHUD

    panel = HoverHUD(dwell_ms=dwell_ms, backend=backend)
    panel.show()
    sinks: list[Any] = [panel]
    closers.append(panel.close)
    if show_roi:
        geometries = [screen.geometry() for screen in application.screens()]
        if not geometries:
            raise RuntimeError("no screen is available for the capture overlay")
        left = min(geometry.left() for geometry in geometries)
        top = min(geometry.top() for geometry in geometries)
        right = max(geometry.right() for geometry in geometries)
        bottom = max(geometry.bottom() for geometry in geometries)
        overlay = CaptureOverlay(QRect(left, top, right - left + 1, bottom - top + 1))
        overlay.show()
        closers.append(overlay.close)
        sinks.append(overlay)
    return sinks


# -- metadata --------------------------------------------------------------------


def _metadata(
    options: SessionOptions,
    runtime_config: Path,
    settings: AppConfig,
    started: str,
    source: dict[str, Any],
    plan: list[Any] | None = None,
    *,
    source_at_end: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if plan is not None:
        from .stress import summarize_plan

        extra = {
            "plan": summarize_plan(plan),
            "fixture_images_retained": options.retain_fixture_images,
        }
    return {
        **extra,
        "schema_version": 1,
        "mode": options.mode,
        "started": started,
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
        # Kept for older readers; ``lab_provenance`` is the authoritative block.
        "commit": source["commit"],
        "dirty": source["dirty"],
        "runtime_config": _display(runtime_config),
        "settings": settings.to_dict(),
        # Evidence is read in memory during a tour; only this decides persistence.
        "fixture_text_retained": options.drives and options.retain_fixture_text,
        "options": {
            "words": options.words,
            "story_sizes": list(options.story_sizes),
            "word_sizes": list(options.word_sizes),
            "seed": options.seed,
            "duration": options.duration,
            "roi_size": list(options.roi_size) if options.roi_size else None,
            "hover_delay_ms": options.hover_delay_ms,
            "cpu_threads": options.cpu_threads,
            "hover_timeout": options.hover_timeout,
            "hud": options.hud,
            "baseline": None if options.baseline is None else Path(options.baseline).name,
            "per_family": options.per_family,
            "backend": options.backend,
            "corpus": _corpus_identity(options.corpus),
            "corpus_manifest": None if options.corpus is None else _display(options.corpus),
            "repeats": options.repeats if options.corpus is not None else None,
        },
        "lab_provenance": provenance(
            options.mode,
            source,
            source_at_end=source_at_end,
            measurement_protocol=SESSION_MEASUREMENT_PROTOCOL,
            configured_backend=settings.ocr_backend.value,
            disposable=[BROWSER_FOLDER] if options.mode == "stress" else [],
        ),
    }


def _corpus_identity(manifest: Path | None) -> str | None:
    """The corpus by content, so two runs over the same images compare."""

    if manifest is None:
        return None
    from ..corpus import fingerprint, load_corpus

    return fingerprint(load_corpus(manifest))


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path).replace(str(Path.home()), "~")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


__all__ = ["SessionOptions", "run_session"]
