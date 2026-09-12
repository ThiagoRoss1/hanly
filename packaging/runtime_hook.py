"""PyInstaller startup hook, deliberately role-neutral.

This runs in every Hanly process, the Control Center and lookup children
included. Importing a role's libraries here would load Qt WebEngine or the
whole OCR stack into processes that must never carry them, which is what the
process split exists to prevent; each role initializes only itself.

Filtering third-party warnings is a process-wide decision and costs nothing,
so it is the one thing that stays.
"""

from hanly_app.ocr_preload import silence_runtime_warnings

silence_runtime_warnings()
