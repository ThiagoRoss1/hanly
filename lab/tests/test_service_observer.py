from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from hanly import PixelFormat, Point, ROIImage
from hanly_app.acquisition.capture import CaptureResult, ScreenRect

from lab.service_observer import MAX_CAPTURE_BYTES, _LabCaptureObserver


class _Loop:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def post(self, callback) -> None:
        self.callbacks.append(callback)


class _Service:
    def __init__(self) -> None:
        self._loop = _Loop()
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _emit_event(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append((name, payload))


def _capture(data: bytes) -> CaptureResult:
    image = ROIImage(2, 1, PixelFormat.RGB_888, data)
    return CaptureResult(image, ScreenRect(10, 20, 2, 1), Point(1, 0))


def test_capture_observer_keeps_only_newest_pending_roi_until_owner_callback() -> None:
    service = _Service()
    observer = _LabCaptureObserver(service)

    assert observer.observe(_capture(b"abcdef"), hover_request_id=1)
    assert observer.observe(_capture(b"ghijkl"), hover_request_id=2)
    assert observer.dropped == 1
    assert service.events == []
    assert len(service._loop.callbacks) == 1

    service._loop.callbacks.pop()()

    assert len(service.events) == 1
    name, payload = service.events[0]
    assert name == "lab_capture"
    assert payload["hover_request_id"] == 2
    assert base64.b64decode(payload["image"]["data_base64"]) == b"ghijkl"


def test_capture_observer_rejects_oversized_roi_before_queueing() -> None:
    service = _Service()
    observer = _LabCaptureObserver(service)
    width = MAX_CAPTURE_BYTES // 3 + 1
    capture = CaptureResult(
        ROIImage(width, 1, PixelFormat.RGB_888, b"x" * (width * 3)),
        ScreenRect(0, 0, width, 1),
        Point(0, 0),
    )

    assert not observer.observe(capture, lookup_request_id=9)
    assert observer.dropped == 1
    assert service._loop.callbacks == []
