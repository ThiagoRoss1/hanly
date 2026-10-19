"""In-memory, bounded desktop backdrop capture for the native region selector."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from io import BytesIO
from typing import Any, Protocol

from hanly_app.acquisition.capture import (
    CaptureBackend,
    MSSBackend,
    ScreenRect,
)

from .protocol import (
    MAX_SELECTION_SNAPSHOT_DIMENSION,
    MAX_SELECTION_SNAPSHOT_PIXELS,
)

MAX_JPEG_BYTES = 600 * 1024
MAX_THUMBNAIL_DIMENSION = 2048
_JPEG_QUALITIES = (84, 70, 56, 42)
_MINIMUM_ENCODE_DIMENSION = 256


class SnapshotError(RuntimeError):
    """A safe, user-facing failure to capture or encode the selection backdrop."""


class _ClosableCaptureBackend(CaptureBackend, Protocol):
    """The capture adapter contract needed by a temporary snapshot session."""

    def close(self) -> None: ...


def capture_selection_backdrop(
    bounds: ScreenRect,
    native_monitors: Sequence[ScreenRect],
    *,
    backend_factory: Callable[[], _ClosableCaptureBackend] | None = None,
) -> str:
    """Capture a trusted monitor area and return a bounded JPEG data URI."""

    _validate_bounds(bounds)
    _validate_monitor_scope(bounds, native_monitors)

    factory = MSSBackend if backend_factory is None else backend_factory
    backend: _ClosableCaptureBackend | None = None
    try:
        backend = factory()
        captured_monitors = tuple(
            monitor.bounds for monitor in backend.enumerate_monitors()
        )
        _validate_monitor_scope(bounds, captured_monitors)
        capture = backend.grab(bounds)
    except SnapshotError:
        raise
    except Exception as error:
        raise SnapshotError("The desktop backdrop could not be captured.") from error
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass

    _validate_capture_scale(bounds, capture.width, capture.height)
    if len(capture.rgb) != capture.width * capture.height * 3:
        raise SnapshotError("The desktop backdrop data was incomplete.")

    payload = _encode_jpeg(capture.width, capture.height, capture.rgb)
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def _validate_capture_scale(bounds: ScreenRect, width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise SnapshotError("The desktop backdrop dimensions were invalid.")
    scale_x, remainder_x = divmod(width, bounds.width)
    scale_y, remainder_y = divmod(height, bounds.height)
    if (
        remainder_x != 0
        or remainder_y != 0
        or scale_x != scale_y
        or not 1 <= scale_x <= 4
    ):
        raise SnapshotError("The desktop backdrop scale did not match the display area.")
    if (
        width > MAX_SELECTION_SNAPSHOT_DIMENSION
        or height > MAX_SELECTION_SNAPSHOT_DIMENSION
        or width * height > MAX_SELECTION_SNAPSHOT_PIXELS
    ):
        raise SnapshotError("The desktop backdrop exceeds the raw capture limit.")


def _validate_bounds(bounds: ScreenRect) -> None:
    if (
        bounds.width > MAX_SELECTION_SNAPSHOT_DIMENSION
        or bounds.height > MAX_SELECTION_SNAPSHOT_DIMENSION
        or bounds.width * bounds.height > MAX_SELECTION_SNAPSHOT_PIXELS
    ):
        raise SnapshotError("The selected desktop area exceeds the capture limit.")
    if (
        abs(bounds.left) > 100_000
        or abs(bounds.top) > 100_000
        or abs(bounds.right) > 100_000
        or abs(bounds.bottom) > 100_000
    ):
        raise SnapshotError("The selected desktop area is outside the supported coordinates.")


def _validate_monitor_scope(
    bounds: ScreenRect,
    monitors: Sequence[ScreenRect],
) -> None:
    if not monitors or len(monitors) > 32:
        raise SnapshotError("Native display geometry is unavailable.")
    if any(not isinstance(monitor, ScreenRect) for monitor in monitors):
        raise SnapshotError("Native display geometry is invalid.")

    union = _union(monitors)
    contained = any(
        monitor.left <= bounds.left
        and monitor.top <= bounds.top
        and bounds.right <= monitor.right
        and bounds.bottom <= monitor.bottom
        for monitor in monitors
    )
    if not contained and bounds != union:
        raise SnapshotError("The selected area does not match a native display.")


def _union(monitors: Sequence[ScreenRect]) -> ScreenRect:
    left = min(monitor.left for monitor in monitors)
    top = min(monitor.top for monitor in monitors)
    right = max(monitor.right for monitor in monitors)
    bottom = max(monitor.bottom for monitor in monitors)
    return ScreenRect(left, top, right - left, bottom - top)


def _encode_jpeg(width: int, height: int, rgb: bytes) -> bytes:
    try:
        from PIL import Image
    except ImportError as error:
        raise SnapshotError("The desktop backdrop encoder is unavailable.") from error

    try:
        image = Image.frombytes("RGB", (width, height), rgb)
    except Exception as error:
        raise SnapshotError("The desktop backdrop could not be encoded.") from error

    try:
        image.thumbnail(
            (MAX_THUMBNAIL_DIMENSION, MAX_THUMBNAIL_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        while True:
            for quality in _JPEG_QUALITIES:
                output = BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                payload = output.getvalue()
                output.close()
                if len(payload) <= MAX_JPEG_BYTES:
                    return payload

            if max(image.size) <= _MINIMUM_ENCODE_DIMENSION:
                break
            next_size = tuple(max(1, round(dimension * 0.75)) for dimension in image.size)
            smaller = image.resize(next_size, Image.Resampling.LANCZOS)
            image.close()
            image = smaller
    except Exception as error:
        raise SnapshotError("The desktop backdrop could not be encoded.") from error
    finally:
        image.close()

    raise SnapshotError("The desktop backdrop exceeds the transfer limit.")


def native_monitor_rects(monitors: Sequence[dict[str, Any]]) -> tuple[ScreenRect, ...]:
    """Normalize the validated host monitor objects for scope checks."""

    try:
        return tuple(
            ScreenRect(**monitor["bounds"])
            for monitor in monitors
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SnapshotError("Native display geometry is invalid.") from error


__all__ = [
    "MAX_JPEG_BYTES",
    "MAX_THUMBNAIL_DIMENSION",
    "SnapshotError",
    "capture_selection_backdrop",
    "native_monitor_rects",
]
