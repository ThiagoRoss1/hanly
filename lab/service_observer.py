"""Debug-only trace sink used by Lab's isolated native-app sessions.

The desktop starts this module only when a debug build receives the exact Lab
observer environment value. The regular packaged service entry point is
unchanged, and retained evidence stays in memory until the Lab's ownership
checks decide whether any derived fixture evidence may be written.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from collections.abc import Mapping
from importlib import import_module
from typing import Any

from hanly import Point
from hanly_app.acquisition.capture import CapturePlan, CaptureResult, ScreenRect

MAX_CAPTURE_BYTES = 700_000


class _LabCaptureObserver:
    """Forward only the newest explicitly opted-in ROI to the Lab process."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._pending: tuple[CaptureResult, int | None, int | None] | None = None
        self._scheduled = False
        self._lock = threading.Lock()
        self.dropped = 0

    def observe(
        self,
        capture: CaptureResult,
        *,
        hover_request_id: int | None = None,
        lookup_request_id: int | None = None,
    ) -> bool:
        """Retain one immutable frame and enqueue at most one owner callback."""

        if len(capture.image.data) > MAX_CAPTURE_BYTES:
            self.dropped += 1
            return False
        loop = self._service._loop
        if loop is None:
            self.dropped += 1
            return False
        with self._lock:
            if self._pending is not None:
                self.dropped += 1
            self._pending = (capture, hover_request_id, lookup_request_id)
            if self._scheduled:
                return True
            self._scheduled = True
        try:
            loop.post(self._emit_pending)
        except Exception:
            with self._lock:
                self._pending = None
                self._scheduled = False
            self.dropped += 1
            return False
        return True

    def _emit_pending(self) -> None:
        with self._lock:
            item = self._pending
            self._pending = None
            self._scheduled = False
        if item is None:
            return
        capture, hover_request_id, lookup_request_id = item
        data = capture.image.data
        if len(data) > MAX_CAPTURE_BYTES:
            self.dropped += 1
            return
        payload: dict[str, object] = {
            "image": {
                "width": capture.image.width,
                "height": capture.image.height,
                "pixel_format": capture.image.pixel_format.value,
                "data_base64": base64.b64encode(data).decode("ascii"),
            },
            "region": _rect(capture.region),
            "target": {"x": capture.target.x, "y": capture.target.y},
            "plan": _plan(capture.plan),
            "observed_ns": time.perf_counter_ns(),
        }
        if hover_request_id is not None:
            payload["hover_request_id"] = hover_request_id
        if lookup_request_id is not None:
            payload["lookup_request_id"] = lookup_request_id
        try:
            self._service._emit_event("lab_capture", payload)
        except Exception:
            self.dropped += 1


def _rect(rect: ScreenRect) -> dict[str, int]:
    return {
        "left": rect.left,
        "top": rect.top,
        "width": rect.width,
        "height": rect.height,
    }


def _plan(plan: CapturePlan | None) -> dict[str, object] | None:
    if plan is None:
        return None
    return {
        "requested_cursor": _point(plan.requested_cursor),
        "effective_cursor": _point(plan.effective_cursor),
        "monitor_index": plan.monitor_index,
        "monitor_name": plan.monitor_name,
        "monitor_bounds": _rect(plan.monitor_bounds),
        "configured_region": (
            None
            if plan.configured_region is None
            else _rect(plan.configured_region)
        ),
        "clip_bounds": _rect(plan.clip_bounds),
        "roi_size": list(plan.roi_size),
        "roi_grid": plan.roi_grid,
        "ideal_region": _rect(plan.ideal_region),
        "desired_region": _rect(plan.desired_region),
        "actual_region": _rect(plan.actual_region),
        "target": _point(plan.target),
        "image_width": plan.image_width,
        "image_height": plan.image_height,
        "pixel_format": plan.pixel_format.value,
        "image_byte_length": plan.image_byte_length,
    }


def _point(point: Point) -> dict[str, float]:
    return {"x": point.x, "y": point.y}


class _LabTraceSink:
    """Opt the supervised service into the existing trace/evidence seam."""

    retain_evidence = os.environ.get("HANLY_LAB_RETAIN_EVIDENCE") == "1"
    retain_geometry = os.environ.get("HANLY_LAB_RETAIN_GEOMETRY") == "1"

    def emit(self, _event: Mapping[str, object]) -> None:
        """The service forwards events over its existing bounded protocol."""


def _instrument_service() -> None:
    """Attach one factual readiness marker to the debug service trace stream."""

    from hanly_app.runtime_trace import emit_trace

    application: Any = import_module("hanly_app.service.application")
    protocol: Any = import_module("hanly_app.service.protocol")
    server: Any = import_module("hanly_app.service.server")

    protocol.EVENT_NAMES = protocol.EVENT_NAMES | {"lab_capture"}

    class LabDesktopService(application.DesktopService):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._lab_readiness_reported = False
            self._lab_capture_running = False
            self._lab_capture_observer = None
            if os.environ.get("HANLY_LAB_CAPTURE_EXPORT") == "1":
                self._lab_capture_observer = _LabCaptureObserver(self)
                kwargs["capture_observer"] = self._lab_capture_observer
            super().__init__(*args, **kwargs)

        def _publish_status(self) -> None:
            super()._publish_status()
            status = self._status.status
            if self._lab_readiness_reported:
                return
            if status.ready:
                event = "lab_runtime_ready"
            elif status.failed:
                event = "lab_runtime_failed"
            else:
                return
            self._lab_readiness_reported = True
            emit_trace(self._trace_sink, event)

        def _publish_state(self) -> None:
            super()._publish_state()
            running = self._lifecycle.state.value == "running"
            if running == self._lab_capture_running:
                return
            self._lab_capture_running = running
            if running:
                emit_trace(self._trace_sink, "lab_capture_started")
            else:
                emit_trace(self._trace_sink, "lab_capture_stopped")

    server.DesktopService = LabDesktopService
    setattr(server, "_ProtocolTraceSink", _LabTraceSink)


def main() -> int:
    """Run the production service protocol with Lab's in-memory trace opt-in."""

    # The debug launcher selects this exact module; only this process gets the
    # in-memory evidence opt-in and one readiness event on the existing stream.
    _instrument_service()
    server: Any = import_module("hanly_app.service.server")
    return server.main()


if __name__ == "__main__":
    raise SystemExit(main())
