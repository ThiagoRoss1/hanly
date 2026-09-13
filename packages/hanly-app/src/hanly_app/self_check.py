"""Internal diagnostic mode for the one Hanly entry point.

A frozen bundle can only be trusted once its own executable has constructed
the real providers from its own collected dependencies. ``hanly --self-check``
does exactly that and prints a JSON report, so packaging tests never fall back
to the source checkout, the developer virtual environment, or developer model
caches. It reuses the production composition and adds no second application
lifecycle.
"""

from __future__ import annotations

import faulthandler
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any, TypeVar, cast

from .diagnostics import runtime_versions
from .runtime import HanlyRuntime, load_runtime

if TYPE_CHECKING:
    from .control_center_host import ControlCenterHost

#: What ``--self-check`` accepts. ``worker`` proves the lookup runtime and
#: ``ui`` proves the main window: a frozen build can fail at either one alone.
SELF_CHECK_MODES = ("worker", "ui")

#: Modes that need a validated runtime configuration. The window deliberately
#: opens before any resource exists, so checking it must not provision one.
RUNTIME_SELF_CHECK_MODES = ("worker",)

#: Controls the page has to have rendered before the window is usable. Between
#: them they cover starting capture, reporting readiness, and leaving.
UI_PROBE_ELEMENTS = ("control-center", "start-capture", "runtime-state", "quit-hanly")

#: How long the window may take to load its document and inject the bridge.
UI_READY_TIMEOUT_SECONDS = 60.0

#: Korean the morphology adapter must be able to analyze, and the lemma the
#: dictionary must be able to find. Both are ordinary vocabulary, so a bundle
#: that cannot handle them is broken rather than unlucky.
MORPHOLOGY_PROBE = "한국어"
DICTIONARY_PROBE = "한국어"

#: Progress markers go on stderr, one flushed JSON line each, because the
#: report on stdout is written last and a native abort destroys it. The
#: harness reads these to say which stage a killed process was inside.
STAGE_MARKER_PREFIX = "hanly-self-check:"
STAGE_STARTED = "stage_started"
STAGE_COMPLETED = "stage_completed"

StageValueT = TypeVar("StageValueT")


@dataclass(frozen=True, slots=True)
class StageResult:
    """One named step of a self-check, with its own pass/fail and timing."""

    name: str
    ok: bool
    detail: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass(frozen=True, slots=True)
class SelfCheckReport:
    """The machine-readable result the packaging harness consumes."""

    mode: str
    stages: tuple[StageResult, ...] = ()
    versions: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.stages) and all(stage.ok for stage in self.stages)

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": sys.executable,
            "stages": [stage.to_dict() for stage in self.stages],
            "versions": dict(self.versions),
        }


def run_self_check(
    runtime_config: str | Path | None = None,
    *,
    mode: str = "worker",
    image: str | Path | None = None,
) -> SelfCheckReport:
    """Exercise one half of the frozen desktop and report what happened.

    ``worker`` builds the real lookup runtime and calls each provider once;
    ``image`` adds a recognition stage over a Korean fixture, which is the only
    way to prove the frozen OCR stack reads text rather than merely importing.
    ``ui`` opens the real main window instead, and needs no runtime.
    """

    if mode not in SELF_CHECK_MODES:
        raise ValueError(f"unsupported self-check mode: {mode!r}")
    if mode == "ui":
        return _run_ui_check()
    if runtime_config is None:
        raise ValueError(f"the {mode!r} self-check needs a runtime configuration")

    stages: list[StageResult] = []
    runtime = _stage(stages, "runtime", lambda: load_runtime(Path(runtime_config)))
    if runtime is not None:
        worker = _stage(stages, "lookup worker", lambda: runtime.create_worker_factory()())
        if image is not None:
            _stage(stages, "ocr", lambda: _recognize(runtime, Path(image)))
        _stage(stages, "morphology", _analyze)
        _stage(stages, "dictionary", lambda: _lookup(runtime))
        if worker is not None:
            # Closing releases native handles the providers opened, so it is a
            # stage of its own: a crash here is not the dictionary's fault.
            _stage(stages, "worker close", worker.close)

    return SelfCheckReport(mode=mode, stages=tuple(stages), versions=_collected_versions())


def report_self_check(
    runtime_config: str | Path | None = None,
    *,
    mode: str = "worker",
    image: str | Path | None = None,
) -> int:
    """Print the report as one JSON document and return the process status."""

    _trace_native_crashes()
    report = run_self_check(runtime_config, mode=mode, image=image)
    # ASCII-escaped on purpose: a frozen Windows process writes to a console
    # codepage that cannot encode the Korean this report contains, and the
    # harness decodes the escapes back losslessly.
    print(json.dumps(report.to_dict(), indent=2), flush=True)
    return 0 if report.ok else 1


def _trace_native_crashes() -> None:
    """Make a fatal native error name the Python frame it happened in.

    Qt, torch, and Kiwi end the process outright rather than raising, so
    without this a crash reports as a bare exit status and an empty report.
    A build with no usable stderr keeps the status as its only account.
    """

    try:
        faulthandler.enable()
    except (OSError, RuntimeError, ValueError):
        return


def _run_ui_check() -> SelfCheckReport:
    """Open the real main window and drive it the way the desktop does."""

    opened: list[StageResult] = []
    probes: list[StageResult] = []

    # Importing Qt WebEngine is where a frozen build dies before a window ever
    # exists, so the import is its own stage rather than the window's preamble.
    host = _stage(opened, "window host", _create_window_host)
    if host is None:
        return SelfCheckReport(mode="ui", stages=tuple(opened), versions=_collected_versions())

    def drive() -> None:
        try:
            if _stage(probes, "document", lambda: _await_document(host)) is None:
                return
            _stage(probes, "controls", lambda: _rendered_controls(host))
            _stage(probes, "bridge", lambda: _bridge_round_trip(host))
        finally:
            host.close()

    # The probes run inside the loop this stage owns, so they are recorded
    # separately and reported after the window they were taken through.
    _stage(opened, "main window", lambda: _run_window(host, drive))
    return SelfCheckReport(
        mode="ui", stages=(*opened, *probes), versions=_collected_versions()
    )


def _create_window_host() -> ControlCenterHost:
    """Import the window's own stack and build the host that will run it."""

    from .control_center import ControlCenterBridge
    from .control_center_host import ControlCenterHost

    return ControlCenterHost(ControlCenterBridge())


def _run_window(host: object, drive: Callable[[], None]) -> str:
    """Run the GUI loop until the probe closes the window it opened."""

    cast(Any, host).run(on_started=drive)
    return "the window opened and the loop exited cleanly"


def _await_document(host: object) -> str:
    """Wait for the page to load and pywebview to inject its bridge."""

    ready = _poll(
        host,
        "document.readyState === 'complete'"
        " && !!(window.pywebview && window.pywebview.api)",
    )
    if not ready:
        raise RuntimeError("the Control Center document did not finish loading")
    return _evaluate(host, "document.title")


def _rendered_controls(host: object) -> str:
    """Report which of the page's own controls the window is missing."""

    names = ", ".join(f"'{name}'" for name in UI_PROBE_ELEMENTS)
    missing = _evaluate(
        host,
        f"[{names}].filter(function (id) {{ return !document.getElementById(id); }}).join(',')",
    )
    if missing:
        raise RuntimeError(f"the page did not render: {missing}")
    return f"{len(UI_PROBE_ELEMENTS)} controls rendered"


def _bridge_round_trip(host: object) -> str:
    """Call the bridge from the page, which is how every action reaches it."""

    _evaluate(
        host,
        "window.__hanly_probe = null;"
        " window.pywebview.api.get_state().then(function (state) {"
        " window.__hanly_probe = state.runtime.ocr_provider; });",
    )
    if not _poll(host, "window.__hanly_probe !== null"):
        raise RuntimeError("the page called the bridge but never got an answer")
    return f"get_state reported {_evaluate(host, 'window.__hanly_probe')}"


def _poll(host: object, condition: str) -> bool:
    """Wait for one JavaScript condition, which is how a loaded page reports."""

    deadline = perf_counter() + UI_READY_TIMEOUT_SECONDS
    while perf_counter() < deadline:
        if bool(_evaluate(host, condition)):
            return True
        sleep(0.1)
    return False


def _evaluate(host: object, script: str) -> Any:
    window = cast(Any, host).window
    if window is None:
        raise RuntimeError("the Control Center window was closed before it was checked")
    return window.evaluate_js(script)


def _stage(
    stages: list[StageResult],
    name: str,
    action: Callable[[], StageValueT],
) -> StageValueT | None:
    """Run one step, recording its outcome instead of raising out of the check."""

    started = perf_counter()
    _emit_marker(STAGE_STARTED, name)
    try:
        value = action()
    except BaseException as error:
        result = StageResult(
            name, False, f"{type(error).__name__}: {error}", _elapsed_ms(started)
        )
        stages.append(result)
        _emit_marker(STAGE_COMPLETED, name, ok=False, duration_ms=result.duration_ms)
        return None
    detail = value if isinstance(value, str) else ""
    result = StageResult(name, True, detail, _elapsed_ms(started))
    stages.append(result)
    _emit_marker(STAGE_COMPLETED, name, ok=True, duration_ms=result.duration_ms)
    return value


@contextmanager
def _marked(name: str) -> Iterator[None]:
    """Bracket work that is worth naming but does not belong in the report."""

    _emit_marker(STAGE_STARTED, name)
    started = perf_counter()
    try:
        yield
    finally:
        _emit_marker(STAGE_COMPLETED, name, duration_ms=round(_elapsed_ms(started), 1))


def _emit_marker(event: str, name: str, **fields: object) -> None:
    """Write one flushed progress line, on the stream the report does not use.

    A fatal native error never returns, so the harness cannot be told which
    stage was running after the fact. Each marker is written and flushed before
    the work it names, which is what survives an abort.
    """

    payload = {"event": event, "stage": name, **fields}
    try:
        print(f"{STAGE_MARKER_PREFIX} {json.dumps(payload)}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        # A frozen Windows build can be launched with no usable stderr at all;
        # losing progress evidence must not lose the check itself.
        return


def _collected_versions() -> dict[str, str]:
    """Read the identities the report carries, under a marker of its own."""

    with _marked("versions"):
        return runtime_versions()


def _recognize(runtime: HanlyRuntime, image_path: Path) -> str:
    """Recognize a Korean fixture through the OCR provider this build ships."""

    from hanly import PixelFormat, ROIImage
    from hanly.easyocr_provider import EasyOCRProvider
    from PIL import Image

    if runtime.easyocr_config is None:
        raise RuntimeError("the runtime configuration carries no EasyOCR configuration")
    with Image.open(image_path) as source:
        rgb = source.convert("RGB")
        roi = ROIImage(
            width=rgb.width,
            height=rgb.height,
            pixel_format=PixelFormat.RGB_888,
            data=rgb.tobytes(),
        )

    results = EasyOCRProvider(config=runtime.easyocr_config).recognize(roi)
    if not results:
        raise RuntimeError(f"OCR recognized nothing in {image_path.name}")
    return " ".join(result.text for result in results)


def _analyze() -> str:
    """Analyze Korean through the real morphology adapter this build ships."""

    from hanly.kiwi_provider import KiwiProvider

    tokens = KiwiProvider().analyze(MORPHOLOGY_PROBE)
    if not tokens:
        raise RuntimeError(f"morphology returned no tokens for {MORPHOLOGY_PROBE}")
    return ", ".join(token.lemma for token in tokens)


def _lookup(runtime: HanlyRuntime) -> str:
    """Look a known lemma up through the real dictionary adapter and database."""

    from hanly.krdict_provider import KRDICTProvider

    with KRDICTProvider(runtime.krdict_path) as dictionary:
        entries = dictionary.lookup(DICTIONARY_PROBE)
    if not entries:
        raise RuntimeError(f"dictionary has no entry for {DICTIONARY_PROBE}")
    return f"{len(entries)} entries for {DICTIONARY_PROBE}"


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


__all__ = [
    "DICTIONARY_PROBE",
    "MORPHOLOGY_PROBE",
    "RUNTIME_SELF_CHECK_MODES",
    "SELF_CHECK_MODES",
    "STAGE_COMPLETED",
    "STAGE_MARKER_PREFIX",
    "STAGE_STARTED",
    "UI_PROBE_ELEMENTS",
    "SelfCheckReport",
    "StageResult",
    "report_self_check",
    "run_self_check",
]
