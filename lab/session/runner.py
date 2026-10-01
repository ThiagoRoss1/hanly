"""Launch the real desktop under observation and turn the session into a report.

The shell runs in this process through ``run_desktop``, the same composition
``hanly`` uses, with the lab's recorder as its trace sink and diagnostics log.
Its lookup engine and Control Center are still the real spawned children.

Each run gets its own profile under the run directory, so settings changes,
logs and leftovers never touch the everyday profile. The runtime configuration
(and therefore the dictionary and OCR models) is the everyday one, read only.
"""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from hanly_app.config import AppConfig, ConfigManager, HoverActivation
from hanly_app.paths import default_app_config_path, default_runtime_config_path

from .recorder import LabDiagnosticLog, LabRecorder

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "artifacts" / "lab" / "runs"
_DEV_RUNTIME = REPO_ROOT / "resources" / "dev" / "runtime-local.json"
#: Lab sessions; the runs root also holds older campaign evidence.
_SESSION_NAME = re.compile(r"^\d{8}-\d{6}-(run|tour)$")


@dataclass(frozen=True)
class SessionOptions:
    mode: str  # "run" (a person drives) or "tour" (the lab drives)
    runtime_config: Path | None = None
    duration: float | None = None
    hud: bool = False
    open_report: bool = True
    story_sizes: tuple[int, ...] = (22,)
    words: int = 0
    word_sizes: tuple[int, ...] = (16, 22, 30, 40)
    seed: int = 7
    backend: str | None = None
    baseline: Path | None = None


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
    runtime_config = _runtime_config(options.runtime_config)
    user_settings = _read_user_settings()
    if options.mode == "tour":
        _require_tour_prerequisites(user_settings)

    run_dir = RUNS_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-{options.mode}"
    profile = run_dir / "profile"
    profile.mkdir(parents=True)
    _isolate_profile(profile)
    settings = _lab_settings(user_settings, options)
    ConfigManager(default_app_config_path()).save(settings)

    recorder = LabRecorder(
        run_dir / "events.jsonl",
        # Recognized text is retained only when every pixel hovered is the lab's.
        retain_evidence=options.mode == "tour",
        retain_geometry=options.mode == "tour",
    )
    diagnostics = LabDiagnosticLog(
        recorder, default_app_config_path().parent / "logs" / "hanly.log"
    )
    _write_json(run_dir / "metadata.json", _metadata(options, runtime_config, settings))
    print(f"lab: recording to {_display(run_dir)}", flush=True)

    from hanly_app.qt_bootstrap import ensure_qt_application

    from .sampler import ProcessSampler

    application = ensure_qt_application(diagnostics=diagnostics)
    sampler = ProcessSampler(run_dir / "processes.jsonl", recorder.origin_ns)
    sampler.start()

    sinks: list[Any] = [recorder]
    closers: list[Any] = []
    if options.hud:
        sinks.extend(_hud(application, runtime_config, closers))
    if options.mode == "tour":
        _start_tour(options, recorder, settings, runtime_config, closers)
    elif options.duration:
        _stop_after(options.duration, recorder)

    recorder.lab("session_started", mode=options.mode)
    exit_code = 1
    try:
        from hanly_app.application import run_desktop

        exit_code = run_desktop(
            runtime_config,
            trace_sink=sinks[0] if len(sinks) == 1 else _Broadcast(sinks),
            diagnostics=diagnostics,
        )
        if _QUIT_REQUESTED.is_set() and exit_code == 128 + signal.SIGINT:
            # The interrupt was the lab ending a finished tour or timed run.
            exit_code = 0
    finally:
        recorder.lab("session_ended", exit_code=exit_code)
        for close in closers:
            close()
        sampler.stop()
        recorder.close()
        _write_json(
            run_dir / "metadata.json",
            {
                **_metadata(options, runtime_config, settings),
                "exit_code": exit_code,
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
    if options.open_report:
        webbrowser.open(report.as_uri())
    return exit_code


def _score_line(run_dir: Path) -> str | None:
    try:
        tour = json.loads((run_dir / "report.json").read_text(encoding="utf-8")).get("tour")
    except (OSError, ValueError):
        return None
    if not tour or tour.get("accuracy") is None:
        return None
    return (
        f"tour {tour['passed']}/{tour['scored']} ({tour['accuracy']:.1%}) under {tour['rule']}, "
        f"{tour['unscored']} not scored"
    )


def _require_tour_prerequisites(settings: AppConfig) -> None:
    """Refuse before taking the pointer, with what to do about it."""

    problems = []
    if sys.platform == "darwin":
        from hanly_app import permissions_darwin

        if not permissions_darwin.screen_recording_granted():
            problems.append("Screen Recording is not granted to this terminal")
        if not permissions_darwin.accessibility_trusted():
            problems.append(
                "Accessibility is not granted to this terminal (needed to move the pointer)"
            )
    elif sys.platform != "win32":
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


def _read_user_settings() -> AppConfig:
    path = default_app_config_path()
    if not path.is_file():
        return AppConfig()
    try:
        return ConfigManager(path).load()
    except Exception:
        return AppConfig()


def _isolate_profile(profile: Path) -> None:
    """Point every per-user path the desktop resolves at the run's own profile."""

    os.environ["XDG_CONFIG_HOME"] = str(profile)
    if sys.platform == "win32":
        os.environ["LOCALAPPDATA"] = str(profile)


def _lab_settings(user: AppConfig, options: SessionOptions) -> AppConfig:
    settings = replace(user, update_checks_enabled=False)
    if options.backend:
        from hanly_app.config import OCRBackend

        settings = replace(settings, ocr_backend=OCRBackend(options.backend))
    if options.mode == "tour":
        # The lab cannot hold a chord while it glides the pointer.
        settings = replace(settings, hover_activation=HoverActivation.ALWAYS_ACTIVE)
    return settings


# -- the tour and timed sessions ---------------------------------------------------


def _start_tour(
    options: SessionOptions,
    recorder: LabRecorder,
    settings: AppConfig,
    runtime_config: Path,
    closers: list[Any],
) -> None:
    from .corpus import story_targets, word_targets
    from .driver import TourDriver
    from .page import TourPage

    story = story_targets() if options.story_sizes else []
    words = word_targets(_krdict(runtime_config), options.words, seed=options.seed)
    page = TourPage()
    page.lay_out(story, words, list(options.story_sizes), list(options.word_sizes))
    total = sum(len(p.placed) for p in page.pages)
    recorder.lab("tour_planned", pages=len(page.pages), targets=total)
    print(f"lab: tour of {total} hovers over {len(page.pages)} pages", flush=True)
    driver = TourDriver(recorder, page, capture_hotkey=settings.capture_hotkey)
    closers.append(page.close)

    def drive() -> None:
        try:
            driver.run()
        except Exception as error:
            import traceback

            traceback.print_exc()
            recorder.lab("tour_aborted", reason=type(error).__name__)
        finally:
            _request_quit()

    threading.Thread(target=drive, name="lab-tour", daemon=True).start()


def _stop_after(seconds: float, recorder: LabRecorder) -> None:
    def stop() -> None:
        recorder.lab("session_duration_reached", seconds=seconds)
        _request_quit()

    timer = threading.Timer(seconds, stop)
    timer.daemon = True
    timer.start()


_QUIT_REQUESTED = threading.Event()


def _request_quit() -> None:
    # The shell's own SIGINT route: the same shutdown Ctrl+C in a terminal takes.
    _QUIT_REQUESTED.set()
    os.kill(os.getpid(), signal.SIGINT)


def _krdict(runtime_config: Path) -> Path:
    raw = json.loads(runtime_config.read_text(encoding="utf-8"))
    path = Path(raw["resources"]["krdict"]["path"]).expanduser()
    return path if path.is_absolute() else (runtime_config.parent / path).resolve()


# -- the HUD ---------------------------------------------------------------------


class _Broadcast:
    """Feed one trace event to several sinks; the lab recorder decides evidence."""

    def __init__(self, sinks: list[Any]) -> None:
        self._sinks = sinks
        self.retain_evidence = getattr(sinks[0], "retain_evidence", False)
        self.retain_geometry = getattr(sinks[0], "retain_geometry", False)

    def emit(self, event: Any) -> object:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:
                continue
        return None


def _hud(application: Any, runtime_config: Path, closers: list[Any]) -> list[Any]:
    from ..hud.capture_overlay import CaptureOverlay
    from ..hud.hover_hud import HoverHUD
    from ..hud.session import _resolved_backend, _virtual_desktop

    panel = HoverHUD(dwell_ms=80, backend=_resolved_backend(runtime_config))
    panel.show()
    overlay = CaptureOverlay(_virtual_desktop(application))
    overlay.show()
    closers.extend([panel.close, overlay.close])
    return [panel, overlay]


# -- metadata --------------------------------------------------------------------


def _metadata(options: SessionOptions, runtime_config: Path, settings: AppConfig) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": options.mode,
        "started": datetime.now().isoformat(timespec="seconds"),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "runtime_config": _display(runtime_config),
        "settings": settings.to_dict(),
        "evidence_retained": options.mode == "tour",
        "options": {
            "words": options.words,
            "story_sizes": list(options.story_sizes),
            "word_sizes": list(options.word_sizes),
            "seed": options.seed,
            "duration": options.duration,
            "hud": options.hud,
            "baseline": None if options.baseline is None else options.baseline.name,
        },
    }


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path).replace(str(Path.home()), "~")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


__all__ = ["SessionOptions", "run_session"]
