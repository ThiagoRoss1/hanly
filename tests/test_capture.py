from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass

import pytest
from hanly import PixelFormat, Point, ROIImage
from hanly_app.capture import (
    BackendCapture,
    BackendMonitor,
    CaptureBackendError,
    CaptureError,
    CaptureResult,
    CaptureService,
    MonitorInfo,
    MSSBackend,
    ScreenRect,
    _import_mss_factory,
)


@dataclass
class FakeBackend:
    monitors: tuple[BackendMonitor, ...]
    pixels: bytes = b""
    error: BaseException | None = None
    last_region: ScreenRect | None = None

    def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
        return self.monitors

    def grab(self, region: ScreenRect) -> BackendCapture:
        self.last_region = region
        if self.error is not None:
            raise self.error
        return BackendCapture(width=region.width, height=region.height, rgb=self.pixels)


def _monitor(
    left: int = 0,
    top: int = 0,
    width: int = 200,
    height: int = 120,
    name: str = "Primary",
) -> BackendMonitor:
    return BackendMonitor(name=name, bounds=ScreenRect(left, top, width, height))


def _service(
    backend: FakeBackend,
    *,
    roi_size: tuple[int, int] = (40, 20),
) -> CaptureService:
    return CaptureService(backend=backend, roi_size=roi_size)


def test_capture_at_cursor_centers_roi_and_returns_local_target() -> None:
    backend = FakeBackend((_monitor(),), pixels=bytes(40 * 20 * 3))

    result = _service(backend).capture_at_cursor(Point(100, 60))

    assert isinstance(result, CaptureResult)
    assert result.region == ScreenRect(80, 50, 40, 20)
    assert result.target == Point(20, 10)
    assert result.image == ROIImage(40, 20, PixelFormat.RGB_888, bytes(40 * 20 * 3))
    assert backend.last_region == result.region


@pytest.mark.parametrize(
    ("cursor", "expected_region", "expected_target"),
    [
        (Point(5, 4), ScreenRect(0, 0, 25, 14), Point(5, 4)),
        (Point(195, 116), ScreenRect(175, 106, 25, 14), Point(20, 10)),
    ],
)
def test_cursor_roi_is_clipped_to_selected_monitor(
    cursor: Point,
    expected_region: ScreenRect,
    expected_target: Point,
) -> None:
    backend = FakeBackend(
        (_monitor(),), pixels=bytes(expected_region.width * expected_region.height * 3)
    )

    result = _service(backend).capture_at_cursor(cursor)

    assert result.region == expected_region
    assert result.target == expected_target


def test_monitors_are_enumerated_and_selected_by_index() -> None:
    backend = FakeBackend(
        (
            _monitor(name="Left", left=-200, width=200),
            _monitor(name="Right", left=0, width=300),
        ),
        pixels=bytes(40 * 20 * 3),
    )
    service = _service(backend)

    assert service.enumerate_monitors() == (
        MonitorInfo(index=1, name="Left", bounds=ScreenRect(-200, 0, 200, 120)),
        MonitorInfo(index=2, name="Right", bounds=ScreenRect(0, 0, 300, 120)),
    )
    result = service.capture_at_cursor(Point(100, 60), monitor=2)

    assert result.region == ScreenRect(80, 50, 40, 20)


def test_capture_rejects_cursor_outside_selected_monitor() -> None:
    backend = FakeBackend((_monitor(),), pixels=bytes(40 * 20 * 3))

    with pytest.raises(CaptureError, match="outside selected monitor"):
        _service(backend).capture_at_cursor(Point(250, 60), monitor=1)


def test_explicit_region_clips_cursor_roi_and_requires_cursor_inside_region() -> None:
    backend = FakeBackend((_monitor(),), pixels=bytes(30 * 20 * 3))
    service = _service(backend, roi_size=(40, 20))

    result = service.capture_at_cursor(Point(25, 30), region=ScreenRect(10, 20, 30, 20))

    assert result.region == ScreenRect(10, 20, 30, 20)
    assert result.target == Point(15, 10)

    with pytest.raises(CaptureError, match="outside configured region"):
        service.capture_at_cursor(Point(5, 30), region=ScreenRect(10, 20, 30, 20))


@pytest.mark.parametrize(
    "bad_region",
    [
        (0, 0, 0, 10),
        (0, 0, 10, 0),
        (0, 0, 1.5, 10),
    ],
)
def test_screen_geometry_requires_positive_integer_dimensions(
    bad_region: tuple[object, object, object, object],
) -> None:
    with pytest.raises((TypeError, ValueError), match="(integer|positive)"):
        ScreenRect(*bad_region)  # type: ignore[arg-type]


def test_backend_rgb_bytes_are_normalized_to_roi_image() -> None:
    pixels = bytes((1, 2, 3, 4, 5, 6))
    backend = FakeBackend((_monitor(width=2, height=1),), pixels=pixels)

    result = CaptureService(backend=backend, roi_size=(2, 1)).capture_at_cursor(Point(1, 0))

    assert result.image.pixel_format is PixelFormat.RGB_888
    assert result.image.data == pixels


def test_backend_malformed_rgb_size_is_normalized_to_capture_error() -> None:
    backend = FakeBackend((_monitor(),), pixels=b"too short")

    with pytest.raises(CaptureError, match="RGB byte size"):
        _service(backend).capture_at_cursor(Point(100, 60))


def test_monitor_enumeration_and_grab_failures_are_normalized() -> None:
    class BrokenEnumeration(FakeBackend):
        def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
            raise OSError("display unavailable")

    with pytest.raises(CaptureBackendError, match="enumerate monitors"):
        CaptureService(backend=BrokenEnumeration(())).enumerate_monitors()

    backend = FakeBackend((_monitor(),), pixels=bytes(40 * 20 * 3), error=OSError("grab failed"))
    with pytest.raises(CaptureBackendError, match="capture region"):
        _service(backend).capture_at_cursor(Point(100, 60))


def test_mss_backend_normalizes_mss_monitor_and_screenshot_without_leaking_objects() -> None:
    class FakeShot:
        size = (2, 1)
        rgb = bytearray((1, 2, 3, 4, 5, 6))

    class FakeMss:
        monitors = [
            {"left": 0, "top": 0, "width": 2, "height": 1},
        ]

        def __init__(self) -> None:
            self.closed = 0

        def grab(self, region: dict[str, int]) -> FakeShot:
            assert region == {"left": 0, "top": 0, "width": 2, "height": 1}
            return FakeShot()

        def close(self) -> None:
            self.closed += 1

    backend = MSSBackend(factory=FakeMss)

    monitors = backend.enumerate_monitors()
    capture = backend.grab(ScreenRect(0, 0, 2, 1))
    backend.close()

    assert monitors == (BackendMonitor(name="Monitor 1", bounds=ScreenRect(0, 0, 2, 1)),)
    assert capture == BackendCapture(width=2, height=1, rgb=bytes((1, 2, 3, 4, 5, 6)))
    assert not hasattr(capture, "rgb_image")


def test_mss_backend_reports_a_missing_mss_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``None`` in sys.modules is the documented way to make an import fail.
    monkeypatch.setitem(sys.modules, "mss", None)

    with pytest.raises(CaptureBackendError, match="install mss"):
        MSSBackend()


def test_default_factory_uses_the_current_non_deprecated_mss_api() -> None:
    # ``mss.mss()`` is deprecated since MSS 10.2 in favour of ``mss.MSS``, and
    # importing the factory must not construct a display session.
    mss = pytest.importorskip("mss")

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        factory = _import_mss_factory()

    assert factory is mss.MSS
