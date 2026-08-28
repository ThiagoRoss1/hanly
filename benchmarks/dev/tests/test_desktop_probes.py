"""Tests for desktop capture probes."""

from hanly import PixelFormat, Point, ROIImage
from hanly_app.capture import CaptureResult, MonitorInfo, ScreenRect

from benchmarks.dev.desktop_probes import measure_capture_service


class _Capture:
    def __init__(self) -> None:
        self.enumerations = 0
        self.captures = 0

    def enumerate_monitors(self):
        self.enumerations += 1
        return (MonitorInfo(1, "one", ScreenRect(0, 0, 20, 10)),)

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        self.captures += 1
        return CaptureResult(
            ROIImage(20, 10, PixelFormat.RGB_888, bytes(20 * 10 * 3)),
            ScreenRect(0, 0, 20, 10),
            cursor,
        )


def test_capture_probe_counts_calls_and_retains_only_shape() -> None:
    capture = _Capture()
    ticks = iter(range(20))

    report = measure_capture_service(
        capture,
        cursor=Point(5, 5),
        enumeration_samples=2,
        capture_samples=2,
        clock=lambda: next(ticks),
    )

    assert capture.enumerations == 2
    assert capture.captures == 2
    assert report["capture_shape"] == [20, 10, 600]
    assert report["summaries"]["monitor_enumeration"]["count"] == 2
    assert report["summaries"]["capture"]["p50"] == 1.0
