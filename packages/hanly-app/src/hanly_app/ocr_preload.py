"""Process bootstrap helpers that must run before desktop UI imports.

Windows changes native-library resolution after Qt initializes. Importing the
OCR runtime first preserves that ordering while leaving a missing optional
runtime as a visible provider/startup diagnostic.
"""

from __future__ import annotations

import importlib
import re
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .diagnostics import StartupTimeline

DiagnosticReporter = Callable[[str], None]

#: The OCR runtime imported before Qt.
OCR_RUNTIME_MODULE = "easyocr"

#: Third-party notices Hanly cannot act on, matched narrowly so a warning that
#: does concern Hanly still reaches the terminal. Torch emits the first when
#: EasyOCR builds its quantized recognition network, and the second on every
#: inference because its data loader asks for pinned memory on a CPU-only host.
_SUPPRESSED_RUNTIME_WARNINGS = (
    "torch.quantize_per_tensor",
    "'pin_memory' argument is set as true",
)


@dataclass(frozen=True, slots=True)
class PreloadTiming:
    """What the preload cost, kept until a diagnostics log exists to take it."""

    seconds: float
    outcome: str


#: The packaged runtime hook preloads before the session log exists, so the one
#: measurement waits here. Only the first import is measured, and it is taken
#: once, so the same cost is never claimed twice.
_timing: PreloadTiming | None = None
_measured = False


def take_preload_timing() -> PreloadTiming | None:
    """Return the pending preload measurement, clearing it."""

    global _timing

    timing, _timing = _timing, None
    return timing


def record_preload_timing(timeline: StartupTimeline) -> None:
    """Hand the pending preload measurement to a timeline, if there is one."""

    timing = take_preload_timing()
    if timing is not None:
        timeline.mark("ocr runtime preload", timing.seconds, outcome=timing.outcome)


def preload_ocr_runtime(
    *,
    on_diagnostic: DiagnosticReporter | None = None,
) -> str | None:
    """Import the OCR runtime before Qt, reporting failure as non-fatal."""

    global _measured, _timing

    silence_runtime_warnings()

    started = monotonic()
    try:
        # Imported for its side effect only: loading the native libraries while
        # the process DLL search path is still the one Python started with.
        importlib.import_module(OCR_RUNTIME_MODULE)
    except Exception as error:
        # Deliberately broad. This boundary fails in library-specific ways -
        # ImportError, OSError/WinError from the native loader, and assorted
        # RuntimeErrors raised during the library's own import - and none of
        # them should stop the desktop from starting with a reported diagnostic.
        message = f"OCR runtime preload skipped for {OCR_RUNTIME_MODULE}: {error}"
        _timing = _measure(started, "unavailable")
        if on_diagnostic is not None:
            on_diagnostic(message)
        else:
            print(f"Hanly: {message}", file=sys.stderr, flush=True)
        return message

    _timing = _measure(started, "loaded")
    return None


def _measure(started: float, outcome: str) -> PreloadTiming | None:
    """Measure the first import only; a later call finds the module cached."""

    global _measured

    if _measured:
        return _timing
    _measured = True
    return PreloadTiming(monotonic() - started, outcome)


def silence_runtime_warnings() -> None:
    """Filter the OCR runtime's own deprecation notices out of the terminal.

    Applied at the application entry point rather than in the engine: altering
    the warning filters is a process-wide decision, and a library importing
    ``hanly`` must keep making it for itself.
    """

    for message in _SUPPRESSED_RUNTIME_WARNINGS:
        warnings.filterwarnings(
            "ignore",
            message=re.escape(message),
            category=UserWarning,
        )


__all__ = [
    "OCR_RUNTIME_MODULE",
    "DiagnosticReporter",
    "PreloadTiming",
    "preload_ocr_runtime",
    "record_preload_timing",
    "silence_runtime_warnings",
    "take_preload_timing",
]
