"""Freeze one real lookup, inspect it, and export it only when asked.

This is the developer-facing half of the microscope. It wires three things onto
a live desktop session: a trace sink that tees, a capture observer that hashes
off the capture path, and a freeze action.

**The tee is the privacy boundary.** The raw event, recognized text and all,
goes to the in-memory ring; a redacted copy goes to the recorder that writes
JSONL. Nothing that reaches disk during a session carries screen content, and
that stays true whether or not a lookup is frozen. Only :func:`export_frozen`
writes private artifacts, only when a developer explicitly asks, and only under
the gitignored artifact root.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from hanly import ROIImage
from hanly_app.capture import CaptureResult
from hanly_app.lookup_evidence import EVIDENCE_FIELDS

from .easyocr_stages import COMPARISON_REPLAY, StagedRun, run_staged_easyocr
from .frozen_lookup import DEFAULT_RING_SIZE, FreezeReport, FrozenLookup, LookupRing
from .live_telemetry import SessionPrivacy

#: The one root any export may write beneath. It is gitignored.
ARTIFACT_ROOT = Path("artifacts/benchmarks/runs")

#: The labelled layers the inspector draws. Naming them apart is the whole
#: point: one undifferentiated green box cannot say which stage was wrong.
LAYERS = (
    "actual_roi",
    "raw_detector_regions",
    "normalized_ocr_regions",
    "selected_ocr_region",
    "estimated_surface_bounds",
    "retained_bounds",
    "cursor",
)


class ExportRefused(RuntimeError):
    """Raised when an export would write outside the configured artifact root."""


def _is_private_evidence(key: str) -> bool:
    """Whether a trace field carries an encoded private diagnostic structure."""

    return key in EVIDENCE_FIELDS or key.endswith("_evidence")


class MicroscopeSink:
    """Tee one runtime event: raw to memory, evidence-stripped to the inner sink.

    Wraps the sink that would otherwise have received the event, so there is
    one recorder, one redaction pass, and one privacy rule. The tee is the
    privacy boundary: the in-memory ring keeps the full structures, and what
    continues towards persistence never carries screen content.

    ``emit`` runs on the hover path and on the lookup child's trace replay, so
    it does dictionary work and nothing else.
    """

    #: Ask the production tracing wrappers for the full private structures.
    retain_evidence = True

    def __init__(self, ring: LookupRing, inner: Any) -> None:
        self._ring = ring
        self._inner = inner

    def emit(self, event: Mapping[str, object]) -> object:
        name = event.get("event_kind", event.get("event"))
        if not isinstance(name, str):
            return False
        observed = event.get("timestamp_ns", event.get("monotonic_ns"))
        observed_ns = (
            int(observed)
            if isinstance(observed, int) and not isinstance(observed, bool)
            else time.perf_counter_ns()
        )
        raw = dict(event)
        raw.setdefault("event_kind", name)
        self._ring.observe_event(raw, observed_ns)
        return self._inner.emit(
            {key: value for key, value in raw.items() if not _is_private_evidence(key)}
        )


class MicroscopeCaptureObserver:
    """Hash and retain ROIs on a benchmark thread, never on the capture path.

    The capture callback only enqueues an already-immutable reference, exactly
    as the digest-only observer does; the keyed digest and the ring bookkeeping
    happen behind it.
    """

    def __init__(
        self, ring: LookupRing, privacy: SessionPrivacy, *, queue_size: int = 64
    ) -> None:
        self._ring = ring
        self._privacy = privacy
        self._queue: queue.Queue[tuple[Any, ...] | None] = queue.Queue(queue_size)
        self._closed = False
        self.dropped_observations = 0
        self._thread = threading.Thread(
            target=self._run, name="microscope-capture", daemon=True
        )
        self._thread.start()

    def observe(
        self,
        capture: CaptureResult,
        *,
        hover_request_id: int | None = None,
        lookup_request_id: int | None = None,
    ) -> bool:
        if self._closed:
            return False
        item = (time.perf_counter_ns(), capture, hover_request_id, lookup_request_id)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped_observations += 1
            return False
        return True

    def close(self, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.put(None, timeout=0.01)
                break
            except queue.Full:
                if not self._thread.is_alive():
                    break
        self._thread.join(max(0.0, timeout))

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            observed_ns, capture, hover_request_id, lookup_request_id = item
            image = capture.image
            digest = self._privacy.roi_digest(image.data, image.width, image.height)
            self._ring.observe_capture(
                capture,
                digest,
                observed_ns,
                hover_request_id=hover_request_id,
                lookup_request_id=lookup_request_id,
            )


@dataclass(frozen=True)
class ExportedFrozenLookup:
    """Where an explicit export put each file."""

    directory: Path
    files: tuple[Path, ...]


def freeze(ring: LookupRing) -> FreezeReport:
    """Pin the newest completed lookup. Writes nothing, ever."""

    frozen = ring.freeze()
    held = ring.records()
    if frozen is None:
        return FreezeReport(
            frozen=None,
            records_held=held,
            reason="no completed lookup is held; hover over a word and try again",
        )
    return FreezeReport(frozen=frozen, records_held=held, notes=frozen.missing)


def stage_frozen_roi(
    frozen: FrozenLookup, reader: Any, **options: Any
) -> StagedRun | None:
    """Replay a frozen ROI through EasyOCR's stages, as comparison evidence.

    The result is labelled ``comparison_replay`` and never attributed to the
    provider pass that actually produced this lookup's output.
    """

    if frozen.capture is None:
        return None
    return run_staged_easyocr(
        reader,
        frozen.capture.roi,
        evidence_class=COMPARISON_REPLAY,
        **options,
    )


def export_frozen(
    frozen: FrozenLookup,
    run_dir: Path,
    *,
    artifact_root: Path = ARTIFACT_ROOT,
    metadata: Mapping[str, Any] | None = None,
) -> ExportedFrozenLookup:
    """Write one pinned lookup's private evidence, on explicit request only.

    This is the only function in the microscope that touches the filesystem.
    Everything it writes -- the ROI, recognized text, provider crops -- is
    private screen content, so it must land under the gitignored root and
    nowhere else.
    """

    destination = _validated_destination(run_dir, artifact_root)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    written.append(_write_json(destination / "metadata.json", _metadata(frozen, metadata)))
    written.append(_write_json(destination / "diagnostic.json", describe_frozen(frozen)))
    written.append(_write_events(destination / "events.jsonl", frozen))
    written.append(_write_text(destination / "diagnostic.html", render_frozen_html(frozen)))

    if frozen.capture is not None:
        image = _write_png(destination / "input.png", frozen.capture.roi)
        if image is not None:
            written.append(image)
    written.extend(_write_staged(destination, frozen))
    return ExportedFrozenLookup(directory=destination, files=tuple(written))


def describe_frozen(frozen: FrozenLookup) -> dict[str, Any]:
    """Render one pinned lookup as the JSON the inspector and export share."""

    capture = frozen.capture
    return {
        "schema_version": 1,
        "hover_request_id": frozen.hover_request_id,
        "lookup_request_id": frozen.lookup_request_id,
        "terminal_event": frozen.terminal_event,
        "result_status": frozen.result_status,
        "live_ocr_backend": frozen.backend,
        "complete": frozen.complete,
        "missing": [_split_reason(entry) for entry in frozen.missing],
        "capture": None if capture is None else _capture_payload(capture),
        "stages": frozen.stages,
        "layers": _layers(frozen),
        "staged_ocr": _staged_payload(frozen.staged),
        "event_count": len(frozen.events),
    }


def render_frozen_html(frozen: FrozenLookup) -> str:
    """Render a standalone inspector for one pinned lookup.

    The page shows the numbers and the named layers; it draws no illustrative
    crop it does not have. An exported page sits beside the real ``input.png``
    and refers to it, so nothing here is invented.
    """

    payload = json.dumps(describe_frozen(frozen), ensure_ascii=False, indent=2, sort_keys=True)
    safe = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    status = escape(str(frozen.result_status or "unknown"))
    gaps = "".join(
        f"<li><code>{escape(stage)}</code> — {escape(reason)}</li>"
        for stage, reason in (_split_reason(entry) for entry in frozen.missing)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hanly Frozen Lookup</title>
<style>
  :root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
  body {{ margin: 2rem; background: #11161c; color: #e7edf3; }}
  main {{ max-width: 76rem; margin: auto; }}
  h1 {{ font-size: 1.4rem; }}
  pre {{ padding: 1rem; overflow: auto; border: 1px solid #394653;
    border-radius: .5rem; background: #1c252e; }}
  figure {{ margin: 0 0 1.5rem; }}
  img {{ max-width: 100%; image-rendering: pixelated;
    border: 1px solid #394653; border-radius: .25rem; }}
  ul.gaps li {{ color: #f0b429; }}
  code {{ color: #a9e6b8; }}
</style>
</head>
<body>
<main>
<h1>Frozen lookup {frozen.lookup_request_id} — {status}</h1>
<p>Live OCR backend: <code>{escape(str(frozen.backend or "unrecorded"))}</code></p>
<figure>
  <img src="input.png" alt="the exact captured ROI">
  <figcaption>The ROI this lookup was given. Present only in an export.</figcaption>
</figure>
<h2>Unavailable evidence</h2>
<ul class="gaps">{gaps or "<li>none</li>"}</ul>
<h2>Evidence</h2>
<pre id="frozen">{escape(payload)}</pre>
<script type="application/json" id="frozen-data">{safe}</script>
</main>
</body>
</html>
"""


def _layers(frozen: FrozenLookup) -> dict[str, Any]:
    """Separate the geometry by what it means, with unavailable layers named.

    Everything used to be one colour of rectangle, which made a detector box,
    a selected region, an estimated word, and a retained screen rectangle
    indistinguishable on screen.
    """

    resolution = frozen.stages.get("token_selection", {})
    ocr = frozen.stages.get("ocr", {})
    capture = frozen.capture
    staged = frozen.staged

    layers: dict[str, Any] = {name: {"available": False, "reason": None} for name in LAYERS}
    if capture is not None:
        layers["actual_roi"] = {
            "available": True,
            "space": "roi_local",
            "rect": {"left": 0, "top": 0, "right": capture.roi.width, "bottom": capture.roi.height},
        }
        if capture.plan is not None:
            layers["cursor"] = {
                "available": True,
                "space": "roi_local",
                "point": {"x": capture.plan.target.x, "y": capture.plan.target.y},
            }
        else:
            layers["cursor"] = {"available": False, "reason": "no capture plan"}
    else:
        reason = "no ROI was observed"
        layers["actual_roi"] = {"available": False, "reason": reason}
        layers["cursor"] = {"available": False, "reason": reason}

    layers["normalized_ocr_regions"] = _region_layer(
        ocr.get("regions"), "no normalized OCR evidence"
    )
    layers["selected_ocr_region"] = _selected_layer(resolution)
    layers["estimated_surface_bounds"] = _bounds_layer(resolution.get("word_bounds"))
    layers["retained_bounds"] = _retained_layer(frozen.events)
    layers["raw_detector_regions"] = _detector_layer(staged)
    return layers


def _region_layer(regions: Any, absent_reason: str) -> dict[str, Any]:
    if not isinstance(regions, list):
        return {"available": False, "reason": absent_reason}
    return {
        "available": True,
        "space": "roi_local",
        "quads": [region.get("quad") for region in regions],
        "texts": [region.get("text") for region in regions],
    }


def _selected_layer(resolution: Mapping[str, Any]) -> dict[str, Any]:
    index = resolution.get("selected_index")
    candidates = resolution.get("candidates")
    # A decoded payload is untrusted: a negative index would otherwise wrap and
    # present the last candidate as the selected one.
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not isinstance(candidates, list)
        or not 0 <= index < len(candidates)
    ):
        return {"available": False, "reason": resolution.get("reason") or "nothing resolved"}
    return {
        "available": True,
        "space": "roi_local",
        "index": index,
        "quad": candidates[index].get("quad"),
        "text": candidates[index].get("text"),
    }


def _bounds_layer(bounds: Any) -> dict[str, Any]:
    if not isinstance(bounds, dict):
        return {"available": False, "reason": "no surface word was resolved"}
    return {"available": True, "space": "roi_local", "rect": bounds}


def _retained_layer(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("event_kind") != "retained_target":
            continue
        return {
            "available": True,
            "space": "screen",
            "rect": {
                "left": event.get("word_left"),
                "top": event.get("word_top"),
                "width": event.get("word_width"),
                "height": event.get("word_height"),
            },
            "protected": {
                "left": event.get("protected_left"),
                "top": event.get("protected_top"),
                "width": event.get("protected_width"),
                "height": event.get("protected_height"),
            },
            "scale": event.get("screen_scale"),
        }
    for event in reversed(events):
        if event.get("event_kind") == "retained_target_cleared":
            return {"available": False, "reason": str(event.get("reason"))}
    return {"available": False, "reason": "nothing was retained"}


def _detector_layer(staged: StagedRun | None) -> dict[str, Any]:
    if staged is None:
        return {
            "available": False,
            # Vision exposes no detector boxes at all, and an EasyOCR
            # production pass went through readtext, which does not surface
            # them either. Neither is a missing measurement.
            "reason": "no staged EasyOCR run is attached to this lookup",
        }
    return {
        "available": True,
        "space": "roi_local",
        "evidence_class": staged.evidence_class,
        "boxes": [list(region.quad) for region in staged.regions],
        "kinds": [region.kind for region in staged.regions],
    }


def _capture_payload(capture: Any) -> dict[str, Any]:
    plan = capture.plan
    payload: dict[str, Any] = {
        "observed_ns": capture.observed_ns,
        "roi_digest": capture.roi_digest,
        "roi_width": capture.roi.width,
        "roi_height": capture.roi.height,
        "pixel_format": capture.roi.pixel_format.value,
        "byte_count": len(capture.roi.data),
        "region": {
            "left": capture.region.left,
            "top": capture.region.top,
            "width": capture.region.width,
            "height": capture.region.height,
        },
        "plan": None,
    }
    if plan is None:
        return payload
    payload["plan"] = {
        "requested_cursor": {"x": plan.requested_cursor.x, "y": plan.requested_cursor.y},
        "effective_cursor": {"x": plan.effective_cursor.x, "y": plan.effective_cursor.y},
        "cursor_clamped": plan.cursor_clamped,
        "monitor": {
            "index": plan.monitor_index,
            "name": plan.monitor_name,
            "bounds": _rect(plan.monitor_bounds),
        },
        "configured_region": None
        if plan.configured_region is None
        else _rect(plan.configured_region),
        "clip_bounds": _rect(plan.clip_bounds),
        "roi_size": list(plan.roi_size),
        "roi_grid": plan.roi_grid,
        "ideal_region": _rect(plan.ideal_region),
        "desired_region": _rect(plan.desired_region),
        "actual_region": _rect(plan.actual_region),
        "snapped": plan.snapped,
        "clipped": plan.clipped,
        "clipped_edges": list(plan.clipped_edges),
        "target": {"x": plan.target.x, "y": plan.target.y},
        "target_edge_distances": list(plan.target_edge_distances),
    }
    return payload


def _staged_payload(staged: StagedRun | None) -> dict[str, Any] | None:
    if staged is None:
        return None
    return {
        "evidence_class": staged.evidence_class,
        "is_replay": staged.is_replay,
        "easyocr_version": staged.easyocr_version,
        "detector_options": staged.detector_options,
        "recognizer_options": staged.recognizer_options,
        "notes": list(staged.notes),
        "regions": [
            {
                "index": region.index,
                "kind": region.kind,
                "raw_box": _plain(region.raw_box),
                "quad": _plain(region.quad),
                "text": region.text,
                "confidence": region.confidence,
                "crop": None
                if region.crop is None
                else {
                    "width": region.crop.width,
                    "height": region.crop.height,
                    "mode": region.crop.mode,
                    "byte_count": region.crop.byte_count,
                },
                "unavailable_reason": region.unavailable_reason,
            }
            for region in staged.regions
        ],
        "normalized": [
            {"text": result.text, "confidence": result.confidence}
            for result in staged.normalized
        ],
        "timings_ns": {
            "detection": staged.detection_ns,
            "recognition": staged.recognition_ns,
            "normalization": staged.normalization_ns,
            "total": staged.total_ns,
        },
    }


def _rect(rect: Any) -> dict[str, int]:
    return {
        "left": rect.left,
        "top": rect.top,
        "width": rect.width,
        "height": rect.height,
    }


def _plain(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _split_reason(entry: str) -> tuple[str, str]:
    stage, _, reason = entry.partition(":")
    return stage, reason


def _metadata(frozen: FrozenLookup, extra: Mapping[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "frozen_lookup",
        "schema_version": 1,
        "frozen_at_ns": frozen.frozen_at_ns,
        "hover_request_id": frozen.hover_request_id,
        "lookup_request_id": frozen.lookup_request_id,
        "live_ocr_backend": frozen.backend,
        "exported": True,
        "contains_private_screen_content": True,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _validated_destination(run_dir: Path, artifact_root: Path) -> Path:
    """Refuse any destination outside the configured gitignored root."""

    root = artifact_root.resolve()
    destination = run_dir if run_dir.is_absolute() else Path.cwd() / run_dir
    resolved = destination.resolve()
    if resolved != root and root not in resolved.parents:
        raise ExportRefused(
            f"{resolved} is outside the benchmark artifact root {root}; private "
            "screen content may only be written there"
        )
    return resolved


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _write_events(path: Path, frozen: FrozenLookup) -> Path:
    lines = [
        json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
        for event in frozen.events
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _write_png(path: Path, image: ROIImage) -> Path | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    mode = {"RGB_888": "RGB", "RGBA_8888": "RGBA", "GRAYSCALE_8": "L"}.get(
        image.pixel_format.value
    )
    if mode is None:
        return None
    rendered = Image.frombytes(mode, (image.width, image.height), image.data)
    rendered.save(path, format="PNG")
    rendered.close()
    return path


def _write_staged(destination: Path, frozen: FrozenLookup) -> list[Path]:
    """Write the staged run's crops, clearly separated from the live pass."""

    staged = frozen.staged
    if staged is None:
        return []
    directory = destination / "ocr"
    directory.mkdir(parents=True, exist_ok=True)
    written = [_write_json(directory / "staged-run.json", _staged_payload(staged))]

    crops = directory / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for region in staged.regions:
        crop = region.crop
        if crop is None:
            continue
        rendered = _write_crop(crops / f"region-{region.index:02d}.png", crop)
        if rendered is not None:
            written.append(rendered)
    return written


def _write_crop(path: Path, crop: Any) -> Path | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    mode = {"L": "L", "BGR": "RGB", "BGRA": "RGBA"}.get(crop.mode)
    if mode is None:
        return None
    rendered = Image.frombytes(mode, (crop.width, crop.height), crop.data)
    if crop.mode.startswith("BGR"):
        channels = rendered.split()
        rendered = Image.merge(mode, (channels[2], channels[1], channels[0], *channels[3:]))
    rendered.save(path, format="PNG")
    rendered.close()
    return path


def build_ring(size: int = DEFAULT_RING_SIZE) -> LookupRing:
    """Build the ring a microscope session pins its evidence in."""

    return LookupRing(size)


__all__ = [
    "ARTIFACT_ROOT",
    "LAYERS",
    "ExportRefused",
    "ExportedFrozenLookup",
    "MicroscopeCaptureObserver",
    "MicroscopeSink",
    "build_ring",
    "describe_frozen",
    "export_frozen",
    "freeze",
    "render_frozen_html",
    "stage_frozen_roi",
]
