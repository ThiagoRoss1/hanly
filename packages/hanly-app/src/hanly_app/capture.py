"""Desktop screen capture and cursor-relative ROI normalization.

The capture boundary deliberately deals in small, application-owned value
types. The concrete MSS screenshot object is consumed inside :class:`MSSBackend`
and never reaches the rest of the desktop client or the engine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import floor, isfinite
from typing import Protocol, TypeAlias, cast

from hanly import PixelFormat, Point, ROIImage

from .config import CaptureMode

# ROI origins are snapped to this many pixels so that small cursor movements
# reuse one identical ROI. At the 200x100 default this keeps the cursor within
# 16 px of centre, well inside the margin a captured text line needs.
DEFAULT_ROI_GRID = 32


class CaptureError(RuntimeError):
    """Base error for invalid capture requests or unusable capture data."""


class CaptureBackendError(CaptureError):
    """Raised when a capture backend cannot enumerate or capture a display."""


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class ScreenRect:
    """A non-empty integer rectangle in virtual-desktop screen coordinates."""

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        _integer(self.left, "left")
        _integer(self.top, "top")
        _integer(self.width, "width")
        _integer(self.height, "height")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen rectangle dimensions must be positive")

    @property
    def right(self) -> int:
        """Exclusive right edge."""

        return self.left + self.width

    @property
    def bottom(self) -> int:
        """Exclusive bottom edge."""

        return self.top + self.height

    def contains(self, point: Point) -> bool:
        """Return whether a screen-space point lies inside this rectangle."""

        return self.left <= point.x < self.right and self.top <= point.y < self.bottom


@dataclass(frozen=True, slots=True)
class BackendMonitor:
    """Backend-neutral monitor data returned by a capture adapter."""

    name: str
    bounds: ScreenRect

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("monitor name must be a non-empty string")
        if not isinstance(self.bounds, ScreenRect):
            raise TypeError("monitor bounds must be a ScreenRect")


@dataclass(frozen=True, slots=True)
class BackendCapture:
    """RGB bytes and dimensions normalized by a capture backend."""

    width: int
    height: int
    rgb: bytes

    def __post_init__(self) -> None:
        _integer(self.width, "capture width")
        _integer(self.height, "capture height")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("capture dimensions must be positive")
        if not isinstance(self.rgb, bytes):
            raise TypeError("capture rgb data must be bytes")


class CaptureBackend(Protocol):
    """Narrow adapter seam used by :class:`CaptureService`."""

    def enumerate_monitors(self) -> Sequence[BackendMonitor]:
        """Return physical monitors in stable display order."""

    def grab(self, region: ScreenRect) -> BackendCapture:
        """Capture one screen-space rectangle as tightly packed RGB bytes."""


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """A user-selectable monitor with a stable one-based index."""

    index: int
    name: str
    bounds: ScreenRect

    def __post_init__(self) -> None:
        _integer(self.index, "monitor index")
        if self.index <= 0:
            raise ValueError("monitor index must be positive")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("monitor name must be a non-empty string")
        if not isinstance(self.bounds, ScreenRect):
            raise TypeError("monitor bounds must be a ScreenRect")


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """Normalized ROI, its screen-space origin, and the local target point."""

    image: ROIImage
    region: ScreenRect
    target: Point

    def __post_init__(self) -> None:
        if not isinstance(self.image, ROIImage):
            raise TypeError("image must be an ROIImage")
        if not isinstance(self.region, ScreenRect):
            raise TypeError("region must be a ScreenRect")
        if not isinstance(self.target, Point):
            raise TypeError("target must be a Point")
        if not 0 <= self.target.x < self.region.width:
            raise ValueError("target x must lie inside captured region")
        if not 0 <= self.target.y < self.region.height:
            raise ValueError("target y must lie inside captured region")
        if self.image.width != self.region.width or self.image.height != self.region.height:
            raise ValueError("image dimensions must match captured region")


class _MSSScreenShot(Protocol):
    """The slice of an MSS screenshot this adapter reads.

    ``size`` is MSS's ``Size`` named tuple and ``rgb`` may be any bytes-like
    buffer, so both are described structurally rather than by concrete type.
    """

    @property
    def size(self) -> Sequence[int]: ...

    @property
    def rgb(self) -> bytes | bytearray: ...


class _MSSSession(Protocol):
    """The slice of an MSS session this adapter drives."""

    @property
    def monitors(self) -> Sequence[Mapping[str, int]]: ...

    def grab(self, region: dict[str, int], /) -> _MSSScreenShot: ...

    def close(self) -> None: ...


_MSSSessionFactory: TypeAlias = Callable[[], _MSSSession]


class MSSBackend:
    """Lazy MSS adapter that normalizes screenshots before returning them."""

    def __init__(self, factory: _MSSSessionFactory | None = None) -> None:
        opener = factory if factory is not None else _import_mss_factory()

        try:
            self._session = opener()
        except Exception as error:
            raise CaptureBackendError(
                f"could not initialize MSS capture backend: {error}"
            ) from error

    def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
        try:
            monitors = _mss_physical_monitors(list(self._session.monitors))
            return tuple(
                BackendMonitor(name=f"Monitor {index}", bounds=_mss_rect(raw))
                for index, raw in enumerate(monitors, start=1)
            )
        except CaptureBackendError:
            raise
        except Exception as error:
            raise CaptureBackendError(f"could not enumerate monitors: {error}") from error

    def grab(self, region: ScreenRect) -> BackendCapture:
        try:
            screenshot = self._session.grab(_mss_region(region))
            return _mss_capture(screenshot)
        except CaptureBackendError:
            raise
        except Exception as error:
            raise CaptureBackendError(f"could not capture region: {error}") from error

    def close(self) -> None:
        try:
            self._session.close()
        except Exception as error:
            raise CaptureBackendError(
                f"could not close MSS capture backend: {error}"
            ) from error


def _import_mss_factory() -> _MSSSessionFactory:
    """Import MSS lazily so ``hanly_app`` stays importable without the extra."""

    try:
        import mss
    except Exception as error:
        raise CaptureBackendError("MSS capture backend is unavailable; install mss") from error
    
    return cast(_MSSSessionFactory, mss.MSS)


def _mss_region(region: ScreenRect) -> dict[str, int]:
    return {
        "left": region.left,
        "top": region.top,
        "width": region.width,
        "height": region.height,
    }


def _mss_capture(screenshot: _MSSScreenShot) -> BackendCapture:
    size = screenshot.size
    if len(size) != 2:
        raise ValueError("MSS screenshot did not provide a (width, height) size")

    width, height = size
    return BackendCapture(width=width, height=height, rgb=bytes(screenshot.rgb))


def _clamped_to(bounds: ScreenRect, point: Point) -> Point:
    """Move a point onto the closest position inside a rectangle."""

    return Point(
        min(max(point.x, float(bounds.left)), float(bounds.right - 1)),
        min(max(point.y, float(bounds.top)), float(bounds.bottom - 1)),
    )


def _distance_to(bounds: ScreenRect, point: Point) -> float:
    """Squared distance from a point to the closest edge of a rectangle."""

    dx = max(bounds.left - point.x, 0.0, point.x - (bounds.right - 1))
    dy = max(bounds.top - point.y, 0.0, point.y - (bounds.bottom - 1))
    return dx * dx + dy * dy


def _mss_rect(raw: object) -> ScreenRect:
    if not isinstance(raw, Mapping):
        raise CaptureBackendError("MSS monitor data must be a mapping")
    try:
        return ScreenRect(
            left=raw["left"],
            top=raw["top"],
            width=raw["width"],
            height=raw["height"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CaptureBackendError(f"MSS monitor has invalid geometry: {error}") from error


def _mss_physical_monitors(raw_monitors: Sequence[object]) -> Sequence[object]:
    """Drop MSS's virtual-desktop aggregate while tolerating test doubles."""

    if len(raw_monitors) <= 1:
        return raw_monitors

    first = _mss_rect(raw_monitors[0])
    rest = [_mss_rect(raw) for raw in raw_monitors[1:]]
    union = ScreenRect(
        left=min(rect.left for rect in rest),
        top=min(rect.top for rect in rest),
        width=max(rect.right for rect in rest) - min(rect.left for rect in rest),
        height=max(rect.bottom for rect in rest) - min(rect.top for rect in rest),
    )
    return raw_monitors[1:] if first == union else raw_monitors


class CaptureService:
    """Capture cursor-centered ROIs clipped to a monitor or configured region."""

    def __init__(
        self,
        backend: CaptureBackend | None = None,
        *,
        roi_size: tuple[int, int] = (200, 100),
        roi_grid: int = 1,
    ) -> None:
        self._backend = backend if backend is not None else MSSBackend()
        self._roi_width, self._roi_height = _validate_roi_size(roi_size)
        self._roi_grid = _validate_roi_grid(roi_grid)

    def enumerate_monitors(self) -> tuple[MonitorInfo, ...]:
        """Return selectable monitors, normalizing backend failures."""

        try:
            raw_monitors = tuple(self._backend.enumerate_monitors())
            return tuple(
                MonitorInfo(index=index, name=monitor.name, bounds=monitor.bounds)
                for index, monitor in enumerate(raw_monitors, start=1)
            )
        except CaptureBackendError:
            raise
        except Exception as error:
            raise CaptureBackendError(f"could not enumerate monitors: {error}") from error

    def capture_at_cursor(
        self,
        cursor: Point,
        *,
        monitor: int | MonitorInfo | None = None,
        region: ScreenRect | None = None,
    ) -> CaptureResult:
        """Capture the ROI around ``cursor`` and translate the target locally."""

        _validate_cursor(cursor)

        monitors = self.enumerate_monitors()
        selected = self._select_monitor(monitors, cursor, monitor)
        if not selected.bounds.contains(cursor):
            if monitor is not None:
                raise CaptureError("cursor is outside selected monitor")
            # The monitor was resolved as nearest to a pre-clamp coordinate, so
            # capture the edge of that display the OS would have clamped to.
            cursor = _clamped_to(selected.bounds, cursor)
        clip_bounds = _resolve_clip_bounds(selected, cursor, region)

        desired = _centered_region(
            cursor, self._roi_width, self._roi_height, self._roi_grid
        )
        captured_region = _intersection(desired, clip_bounds)
        target = Point(cursor.x - captured_region.left, cursor.y - captured_region.top)
        if not 0 <= target.x < captured_region.width or not 0 <= target.y < captured_region.height:
            raise CaptureError("cursor could not be translated into captured region")

        capture = self._grab(captured_region)
        image = ROIImage(
            width=capture.width,
            height=capture.height,
            pixel_format=PixelFormat.RGB_888,
            data=capture.rgb,
        )
        return CaptureResult(image=image, region=captured_region, target=target)

    def _grab(self, region: ScreenRect) -> BackendCapture:
        """Capture ``region`` and reject anything the backend got wrong."""

        try:
            capture = self._backend.grab(region)
        except CaptureBackendError:
            raise
        except Exception as error:
            raise CaptureBackendError(f"could not capture region: {error}") from error

        if not isinstance(capture, BackendCapture):
            raise CaptureBackendError("capture backend returned an invalid capture object")
        if capture.width != region.width or capture.height != region.height:
            raise CaptureError("backend capture dimensions do not match requested region")

        expected_bytes = capture.width * capture.height * 3
        if len(capture.rgb) != expected_bytes:
            raise CaptureError(
                f"backend returned invalid RGB byte size: expected {expected_bytes}, "
                f"got {len(capture.rgb)}"
            )
        return capture

    def close(self) -> None:
        """Close a backend that owns a display session."""

        close = getattr(self._backend, "close", None)
        if close is not None:
            try:
                close()
            except CaptureBackendError:
                raise
            except Exception as error:
                raise CaptureBackendError(f"could not close capture backend: {error}") from error

    @staticmethod
    def _select_monitor(
        monitors: Sequence[MonitorInfo],
        cursor: Point,
        selection: int | MonitorInfo | None,
    ) -> MonitorInfo:
        if isinstance(selection, MonitorInfo):
            for candidate in monitors:
                if candidate.index == selection.index:
                    return candidate
            raise CaptureError(f"monitor {selection.index} was not found")

        if selection is not None:
            _integer(selection, "monitor selection")
            if selection <= 0:
                raise ValueError("monitor selection must be positive")
            for candidate in monitors:
                if candidate.index == selection:
                    return candidate
            raise CaptureError(f"monitor {selection} was not found")

        for candidate in monitors:
            if candidate.bounds.contains(cursor):
                return candidate

        # Global mouse hooks report some events with pre-clamp coordinates, so
        # a cursor the OS actually placed on a display can arrive outside every
        # monitor rectangle. Resolving to the nearest monitor keeps that event
        # usable; only having no monitor at all is a real failure.
        if not monitors:
            raise CaptureError("no monitor is available for capture")
        return min(monitors, key=lambda candidate: _distance_to(candidate.bounds, cursor))


class ConfiguredCaptureService:
    """Apply live desktop capture preferences at the app-owned seam.

    The underlying capture service remains responsible for monitor discovery,
    ROI geometry, and backend access. This wrapper only selects the monitor
    and optional region for each manual or hover request, so both triggers
    observe the same settings without leaking Control Center state into the
    engine or the capture backend.
    """

    def __init__(self, capture_service: object) -> None:
        if not callable(getattr(capture_service, "capture_at_cursor", None)):
            raise TypeError("capture_service must provide capture_at_cursor(cursor)")
        if not callable(getattr(capture_service, "close", None)):
            raise TypeError("capture_service must provide close()")
        self._capture_service = capture_service
        self._capture_mode = CaptureMode.FULL_MONITOR
        self._monitor: int | None = None
        self._region: ScreenRect | None = None

    @property
    def capture_mode(self) -> CaptureMode:
        """Return the live capture-area preference."""

        return self._capture_mode

    @property
    def monitor(self) -> int | None:
        """Return the selected monitor, or ``None`` for cursor resolution."""

        return self._monitor

    @property
    def region(self) -> ScreenRect | None:
        """Return the selected region, if one is configured."""

        return self._region

    def set_preferences(
        self,
        *,
        capture_mode: CaptureMode = CaptureMode.FULL_MONITOR,
        monitor: int | None = None,
        region: ScreenRect | None = None,
    ) -> None:
        """Atomically replace the monitor, region, and capture mode choices."""

        if not isinstance(capture_mode, CaptureMode):
            raise TypeError("capture_mode must be a CaptureMode")
        if monitor is not None:
            _integer(monitor, "monitor selection")
            if monitor <= 0:
                raise ValueError("monitor selection must be positive")
        if region is not None and not isinstance(region, ScreenRect):
            raise TypeError("region must be a ScreenRect")

        self._capture_mode = capture_mode
        self._monitor = monitor
        self._region = region

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        """Capture through the configured monitor/region selection."""

        monitor = self._monitor
        region = self._region if self._capture_mode is CaptureMode.REGION else None
        capture = getattr(self._capture_service, "capture_at_cursor")
        if monitor is None and region is None:
            return cast(CaptureResult, capture(cursor))

        try:
            return cast(CaptureResult, capture(cursor, monitor=monitor, region=region))
        except TypeError as error:
            # Preserve compatibility with narrow test/client capture seams
            # that predate configurable keyword arguments. A real
            # ``CaptureService`` accepts them and never takes this branch.
            if "unexpected keyword" not in str(error):
                raise
            return cast(CaptureResult, capture(cursor))

    def enumerate_monitors(self) -> tuple[MonitorInfo, ...]:
        """Forward monitor discovery for the Control Center."""

        enumerate_monitors = getattr(self._capture_service, "enumerate_monitors")
        return tuple(enumerate_monitors())

    def close(self) -> None:
        """Release the underlying capture backend."""

        getattr(self._capture_service, "close")()


def _resolve_clip_bounds(
    selected: MonitorInfo,
    cursor: Point,
    region: ScreenRect | None,
) -> ScreenRect:
    """Return the area the ROI is clipped to: the monitor, or a valid sub-region."""

    if region is None:
        return selected.bounds

    if not isinstance(region, ScreenRect):
        raise TypeError("region must be a ScreenRect")
    if not region.contains(cursor):
        raise CaptureError("cursor is outside configured region")
    if not _contains_rect(selected.bounds, region):
        raise CaptureError("configured region is outside selected monitor")
    return region


def _validate_roi_size(size: object) -> tuple[int, int]:
    if not isinstance(size, tuple) or len(size) != 2:
        raise TypeError("roi_size must be a (width, height) tuple")
    width, height = size
    _integer(width, "ROI width")
    _integer(height, "ROI height")
    if width <= 0 or height <= 0:
        raise ValueError("ROI dimensions must be positive")
    return width, height


def _validate_cursor(cursor: object) -> None:
    if not isinstance(cursor, Point):
        raise TypeError("cursor must be a Point")
    if not isfinite(cursor.x) or not isfinite(cursor.y):
        raise ValueError("cursor coordinates must be finite")


def _centered_region(
    cursor: Point,
    width: int,
    height: int,
    grid: int = 1,
) -> ScreenRect:
    """Return the ROI around ``cursor``, with its origin snapped to ``grid``.

    Snapping is what makes ROI caching possible at all. An origin computed
    directly from the cursor changes with every pixel of movement, so two
    hovers over the same word produce different pixels and no cache can ever
    match them. Rounding to the nearest grid step keeps small movements on one
    identical ROI while holding the cursor within half a step of centre, which
    is far inside the margin a text line needs.
    """

    # Use the pixel-center span so a one-pixel ROI centered at coordinate zero
    # still contains that coordinate.
    left = floor(cursor.x - (width - 1) / 2)
    top = floor(cursor.y - (height - 1) / 2)
    if grid > 1:
        left = _snap(left, grid, width)
        top = _snap(top, grid, height)
    return ScreenRect(left, top, width, height)


def _snap(value: int, grid: int, extent: int) -> int:
    """Round ``value`` to the nearest multiple of ``grid``, bounding the shift.

    Floor division rounds toward negative infinity, so this is also correct for
    the negative origins a secondary monitor produces. The shift is capped at a
    quarter of the ROI so a grid chosen for one ROI size cannot push the cursor
    toward — or past — the edge of a smaller one.
    """

    snapped = ((value + grid // 2) // grid) * grid
    limit = max(1, extent // 4)
    return max(value - limit, min(value + limit, snapped))


def _validate_roi_grid(grid: object) -> int:
    _integer(grid, "ROI grid")
    assert isinstance(grid, int)
    if grid < 1:
        raise ValueError("ROI grid must be a positive integer")
    return grid


def _intersection(first: ScreenRect, second: ScreenRect) -> ScreenRect:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)
    if left >= right or top >= bottom:
        raise CaptureError("cursor-centered ROI does not intersect selected area")
    return ScreenRect(left, top, right - left, bottom - top)


def _contains_rect(outer: ScreenRect, inner: ScreenRect) -> bool:
    return (
        outer.left <= inner.left
        and outer.top <= inner.top
        and inner.right <= outer.right
        and inner.bottom <= outer.bottom
    )


__all__ = [
    "DEFAULT_ROI_GRID",
    "BackendCapture",
    "BackendMonitor",
    "CaptureBackend",
    "CaptureBackendError",
    "CaptureError",
    "CaptureResult",
    "CaptureService",
    "MSSBackend",
    "MonitorInfo",
    "ScreenRect",
]
