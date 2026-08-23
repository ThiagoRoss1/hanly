"""Process bootstrap helpers that must run before desktop UI imports.

Windows changes native-library resolution after Qt initializes. Importing the
configured OCR runtime first preserves the proven PaddleOCR/Qt ordering while
leaving a missing optional runtime as a visible provider/startup diagnostic.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

DiagnosticReporter = Callable[[str], None]


def preload_ocr_runtime(
    *,
    on_diagnostic: DiagnosticReporter | None = None,
) -> str | None:
    """Import PaddleOCR before Qt and return a non-fatal diagnostic on failure."""

    try:
        # Imported for its side effect only: loading the native libraries while
        # the process DLL search path is still the one Python started with.
        importlib.import_module("paddleocr")
    except Exception as error:
        # Deliberately broad. This boundary fails in library-specific ways -
        # ImportError, OSError/WinError from the native loader, and assorted
        # RuntimeErrors raised during Paddle's own import - and none of them
        # should stop the desktop from starting with a reported diagnostic.
        message = f"OCR runtime preload skipped: {error}"
        if on_diagnostic is not None:
            on_diagnostic(message)
        else:
            print(f"Hanly: {message}", file=sys.stderr, flush=True)
        return message
    return None


__all__ = ["DiagnosticReporter", "preload_ocr_runtime"]
