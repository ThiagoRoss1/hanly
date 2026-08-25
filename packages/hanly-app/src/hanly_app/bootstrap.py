"""Process bootstrap helpers that must run before desktop UI imports.

Windows changes native-library resolution after Qt initializes. Importing the
configured OCR runtime first preserves the proven PaddleOCR/Qt ordering while
leaving a missing optional runtime as a visible provider/startup diagnostic.
The same ordering applies to any other OCR backend a runtime configuration
selects, so the module to import is the caller's choice.
"""

from __future__ import annotations

import importlib
import re
import sys
import warnings
from collections.abc import Callable

DiagnosticReporter = Callable[[str], None]

#: Imported when no runtime configuration has named a different OCR backend.
DEFAULT_OCR_RUNTIME_MODULE = "easyocr"

#: Third-party notices Hanly cannot act on, matched narrowly so a warning that
#: does concern Hanly still reaches the terminal. Torch emits the first when
#: EasyOCR builds its quantized recognition network, and the second on every
#: inference because its data loader asks for pinned memory on a CPU-only host.
_SUPPRESSED_RUNTIME_WARNINGS = (
    "torch.quantize_per_tensor",
    "'pin_memory' argument is set as true",
)


def preload_ocr_runtime(
    *,
    module_name: str = DEFAULT_OCR_RUNTIME_MODULE,
    on_diagnostic: DiagnosticReporter | None = None,
) -> str | None:
    """Import the OCR runtime before Qt, reporting failure as non-fatal."""

    silence_runtime_warnings()

    try:
        # Imported for its side effect only: loading the native libraries while
        # the process DLL search path is still the one Python started with.
        importlib.import_module(module_name)
    except Exception as error:
        # Deliberately broad. This boundary fails in library-specific ways -
        # ImportError, OSError/WinError from the native loader, and assorted
        # RuntimeErrors raised during the library's own import - and none of
        # them should stop the desktop from starting with a reported diagnostic.
        message = f"OCR runtime preload skipped for {module_name}: {error}"
        if on_diagnostic is not None:
            on_diagnostic(message)
        else:
            print(f"Hanly: {message}", file=sys.stderr, flush=True)
        return message
    return None


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
    "DEFAULT_OCR_RUNTIME_MODULE",
    "DiagnosticReporter",
    "preload_ocr_runtime",
    "silence_runtime_warnings",
]
