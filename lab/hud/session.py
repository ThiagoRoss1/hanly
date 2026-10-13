"""Attach Lab's Qt HUD to a supervised native Hanly desktop session."""

from __future__ import annotations

from pathlib import Path


def run_hud_session(
    *,
    runtime_config: Path | None = None,
    app_config: Path | None = None,
    roi_size: tuple[int, int] | None = None,
    dwell_ms: int = 80,
    show_roi: bool = True,
    desktop: Path | None = None,
) -> int:
    """Run the Tauri desktop and show a separate, Lab-owned observation HUD."""

    from ..session.runner import SessionOptions, run_session

    return run_session(
        SessionOptions(
            mode="run",
            runtime_config=runtime_config,
            app_config=app_config,
            desktop=desktop,
            roi_size=roi_size,
            hud=True,
            hud_dwell_ms=dwell_ms,
            show_roi=show_roi,
        )
    )


def _resolved_backend(config_path: Path) -> str:
    """Name the recognizer selected by the runtime configuration."""

    from hanly_app.runtime import load_runtime

    try:
        return str(load_runtime(config_path).resolved_ocr_backend().value)
    except Exception:
        return "unresolved"


__all__ = ["run_hud_session"]
