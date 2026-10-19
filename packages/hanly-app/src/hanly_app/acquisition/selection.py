"""Capture-selection values shared by the native shell and Python service."""

from __future__ import annotations

from dataclasses import dataclass

from hanly_app.acquisition.capture import ScreenRect
from hanly_app.config import CaptureMode


@dataclass(frozen=True, slots=True)
class CaptureSelection:
    """One monitor or region choice; cancellation remains ``None``."""

    capture_mode: CaptureMode
    region: ScreenRect | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capture_mode, CaptureMode):
            raise TypeError("capture_mode must be a CaptureMode")
        if self.capture_mode is CaptureMode.REGION:
            if not isinstance(self.region, ScreenRect):
                raise ValueError("region mode requires a screen region")
        elif self.region is not None:
            raise ValueError("whole-monitor mode cannot carry a region")

    @classmethod
    def whole_monitor(cls) -> CaptureSelection:
        return cls(CaptureMode.FULL_MONITOR)

    @classmethod
    def for_region(cls, region: ScreenRect) -> CaptureSelection:
        return cls(CaptureMode.REGION, region)


__all__ = ["CaptureSelection"]
