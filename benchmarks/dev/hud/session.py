"""Run the real Hanly desktop with the on-screen developer HUD attached.

This is the ordinary desktop — the same composition, the same providers, the
same hover behaviour — with a trace sink that draws instead of recording. It
answers "why did nothing appear when I hovered that word" while you hover.

Nothing here is imported by ``hanly`` or ``hanly_app``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hanly_app.runtime_trace import JSONPrimitive, RuntimeTraceSink


class _Broadcast:
    """Feed one runtime event to several sinks, tolerating a failing one.

    The desktop treats tracing as best effort, so a HUD that throws must not
    become a lookup failure.
    """

    def __init__(self, *sinks: RuntimeTraceSink) -> None:
        self._sinks = sinks

    def emit(self, event: Any) -> object:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except BaseException:
                continue
        return None


def run_hud_session(
    *,
    runtime_config: Path | None = None,
    app_config: Path | None = None,
    roi_size: tuple[int, int] | None = None,
    dwell_ms: int = 80,
    show_roi: bool = True,
) -> int:
    """Start the desktop with the HUD panel and optional ROI outline visible."""

    from hanly_app.control_center import prepare_control_center_qt
    from hanly_app.ocr_preload import preload_ocr_runtime

    # The same OCR-before-Qt ordering the shipped command uses.
    preload_ocr_runtime()
    prepare_control_center_qt()

    from hanly_app.application import resolve_runtime_config, run_desktop
    from PyQt6.QtWidgets import QApplication

    from .capture_overlay import CaptureOverlay
    from .hover_hud import HoverHUD

    application = QApplication.instance() or QApplication([])

    panel = HoverHUD(dwell_ms=dwell_ms, backend="easyocr")
    panel.show()
    sinks: list[RuntimeTraceSink] = [panel]

    overlay: CaptureOverlay | None = None
    if show_roi:
        overlay = CaptureOverlay(_virtual_desktop(application))
        overlay.show()
        sinks.append(overlay)

    try:
        return run_desktop(
            resolve_runtime_config(runtime_config),
            app_config=app_config,
            roi_size=roi_size,
            trace_sink=_Broadcast(*sinks),
        )
    finally:
        panel.close()
        if overlay is not None:
            overlay.close()


def _virtual_desktop(application: Any) -> Any:
    """Return the rectangle spanning every screen, in global coordinates."""

    from PyQt6.QtCore import QRect

    geometries = [screen.geometry() for screen in application.screens()]
    if not geometries:
        raise RuntimeError("no screen is available for the capture overlay")
    left = min(geometry.left() for geometry in geometries)
    top = min(geometry.top() for geometry in geometries)
    right = max(geometry.right() for geometry in geometries)
    bottom = max(geometry.bottom() for geometry in geometries)
    return QRect(left, top, right - left + 1, bottom - top + 1)


__all__ = ["JSONPrimitive", "run_hud_session"]
