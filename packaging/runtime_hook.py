"""PyInstaller startup hook for native OCR loading before the GUI stack."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from hanly_app.bootstrap import preload_ocr_runtime

# Each handle keeps its search path registered for the life of the process;
# dropping it would let a future interpreter release the directory early.
_DLL_DIRECTORIES: list[object] = []


def _add_frozen_native_directories() -> None:
    """Make bundled native OCR libraries visible before importing PaddleOCR."""

    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return

    frozen_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidates = (
        frozen_root / "paddle" / "libs",
        frozen_root / "_internal" / "paddle" / "libs",
    )
    for directory in candidates:
        if directory.is_dir():
            _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))


_add_frozen_native_directories()
# The bootstrap imports paddleocr first; Qt is intentionally not imported here.
preload_ocr_runtime()
