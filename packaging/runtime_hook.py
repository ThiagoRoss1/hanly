"""PyInstaller startup hook that loads the OCR runtime before the GUI stack."""

from __future__ import annotations

from hanly_app.ocr_preload import preload_ocr_runtime

# EasyOCR ships its native code inside torch, which resolves its own DLL
# directories on import. Qt is intentionally not imported here.
preload_ocr_runtime()
