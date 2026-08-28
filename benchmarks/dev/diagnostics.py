"""Developer-only visual diagnostics for the benchmark campaign.

The module deliberately has no imports from the desktop application and keeps
Pillow optional.  A benchmark may collect normalized values from the current
capture/OCR/pipeline seams, serialize them as JSON, and render the same
snapshot as an annotated ROI and a standalone HTML inspector.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, TypeAlias

Number: TypeAlias = int | float


def _number(value: object, field: str) -> Number:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field} must be finite")
    return value


@dataclass(frozen=True)
class PointDiagnostic:
    """A finite point, normally in screen or ROI-local coordinates."""

    x: Number
    y: Number

    def __post_init__(self) -> None:
        _number(self.x, "x")
        _number(self.y, "y")


@dataclass(frozen=True)
class RectangleDiagnostic:
    """A non-empty rectangle using an exclusive right and bottom edge."""

    left: Number
    top: Number
    right: Number
    bottom: Number

    def __post_init__(self) -> None:
        for field, value in (
            ("left", self.left),
            ("top", self.top),
            ("right", self.right),
            ("bottom", self.bottom),
        ):
            _number(value, field)
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("rectangle must have positive extent")


@dataclass(frozen=True)
class MonitorDiagnostic:
    """The selected monitor and its virtual-desktop screen bounds."""

    name: str | None = None
    bounds: RectangleDiagnostic | None = None

    def __post_init__(self) -> None:
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("monitor name must be a string or None")
        if self.name is not None and not self.name.strip():
            raise ValueError("monitor name must not be blank")
        if self.bounds is not None and not isinstance(self.bounds, RectangleDiagnostic):
            object.__setattr__(self, "bounds", _coerce_rectangle(self.bounds))


@dataclass(frozen=True)
class TargetDiagnostic:
    """The ROI-local target and whether its source explicitly marked it available."""

    point: PointDiagnostic | None = None
    available: bool | None = None

    def __post_init__(self) -> None:
        if self.point is not None and not isinstance(self.point, PointDiagnostic):
            object.__setattr__(self, "point", _coerce_point(self.point))
        if self.available is not None and not isinstance(self.available, bool):
            raise TypeError("target availability must be a bool or None")


@dataclass(frozen=True)
class HoverDiagnostic:
    """Observed hover state; every field remains nullable when not exposed."""

    state: str | None = None
    radius: Number | None = None
    dwell_ms: Number | None = None
    pending: bool | None = None
    active: bool | None = None

    def __post_init__(self) -> None:
        if self.state is not None and not isinstance(self.state, str):
            raise TypeError("hover state must be a string or None")
        for field, value in (("radius", self.radius), ("dwell_ms", self.dwell_ms)):
            if value is not None:
                _number(value, field)
                if value < 0:
                    raise ValueError(f"{field} must not be negative")
        for field, value in (("pending", self.pending), ("active", self.active)):
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"hover {field} must be a bool or None")


@dataclass(frozen=True)
class OCRRegionDiagnostic:
    """One OCR quad and its evidence, in ROI-local coordinates."""

    quad: tuple[PointDiagnostic, ...] | Any
    text: str | None = None
    confidence: Number | None = None

    def __post_init__(self) -> None:
        source = self.quad
        if hasattr(source, "quad") and not _is_point_sequence(source):
            if self.text is None:
                object.__setattr__(self, "text", _optional_string(getattr(source, "text", None)))
            if self.confidence is None:
                object.__setattr__(
                    self,
                    "confidence",
                    _optional_number(getattr(source, "confidence", None)),
                )
            source = getattr(source, "quad")
        points = _coerce_quad(source)
        object.__setattr__(self, "quad", points)
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError("OCR text must be a string or None")
        if self.confidence is not None:
            _number(self.confidence, "confidence")
            if not 0 <= self.confidence <= 1:
                raise ValueError("OCR confidence must be between 0 and 1")


@dataclass(frozen=True)
class OCRDiagnostic:
    """OCR evidence and the selected region index, if one was resolved."""

    regions: tuple[OCRRegionDiagnostic, ...] | Sequence[Any] = ()
    selected_index: int | None = None

    def __post_init__(self) -> None:
        regions = tuple(
            region if isinstance(region, OCRRegionDiagnostic) else OCRRegionDiagnostic(region)
            for region in self.regions
        )
        object.__setattr__(self, "regions", regions)
        if self.selected_index is not None:
            if isinstance(self.selected_index, bool) or not isinstance(self.selected_index, int):
                raise TypeError("selected OCR index must be an integer or None")
            if not 0 <= self.selected_index < len(regions):
                raise ValueError("selected OCR index must refer to a region")


@dataclass(frozen=True)
class MorphologyTokenDiagnostic:
    """One token, optional source offsets, and its normalized lemma."""

    token: str | None = None
    start: int | None = None
    end: int | None = None
    lemma: str | None = None

    def __post_init__(self) -> None:
        for text_field, text_value in (("token", self.token), ("lemma", self.lemma)):
            if text_value is not None and not isinstance(text_value, str):
                raise TypeError(f"{text_field} must be a string or None")
        for offset_field, offset_value in (("start", self.start), ("end", self.end)):
            if offset_value is not None and (
                isinstance(offset_value, bool) or not isinstance(offset_value, int)
            ):
                raise TypeError(f"{offset_field} must be an integer or None")
        if self.start is not None and self.start < 0:
            raise ValueError("token start must not be negative")
        if self.end is not None and self.end < 0:
            raise ValueError("token end must not be negative")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("token offsets must be ordered")


@dataclass(frozen=True)
class MorphologyDiagnostic:
    """Morphology tokens, the selected token index, and the selected lemma."""

    tokens: tuple[MorphologyTokenDiagnostic, ...] | Sequence[Any] = ()
    selected_index: int | None = None
    lemma: str | None = None

    def __post_init__(self) -> None:
        tokens = tuple(
            token
            if isinstance(token, MorphologyTokenDiagnostic)
            else _coerce_morphology_token(token)
            for token in self.tokens
        )
        object.__setattr__(self, "tokens", tokens)
        if self.selected_index is not None:
            if isinstance(self.selected_index, bool) or not isinstance(self.selected_index, int):
                raise TypeError("selected morphology index must be an integer or None")
            if not 0 <= self.selected_index < len(tokens):
                raise ValueError("selected morphology index must refer to a token")
        if self.lemma is not None and not isinstance(self.lemma, str):
            raise TypeError("morphology lemma must be a string or None")


@dataclass(frozen=True)
class DictionaryDiagnostic:
    """Dictionary key and provider status, including non-success states."""

    key: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        for field, value in (("key", self.key), ("status", self.status)):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"dictionary {field} must be a string or None")


@dataclass(frozen=True)
class StageTiming:
    """One measured stage duration in milliseconds."""

    stage: str
    duration_ms: Number

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage.strip():
            raise ValueError("timing stage must be a non-empty string")
        _number(self.duration_ms, "duration_ms")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")


@dataclass(frozen=True)
class RequestDiagnostic:
    """Controller currency, cancellation, fallback, and delivery state."""

    request_id: int | None = None
    current: bool | None = None
    stale: bool | None = None
    cancelled: bool | None = None
    latest_wins: bool | None = None
    delivery: str | None = None
    fallback: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.request_id is not None and (
            isinstance(self.request_id, bool) or not isinstance(self.request_id, int)
        ):
            raise TypeError("request_id must be an integer or None")
        if self.request_id is not None and self.request_id <= 0:
            raise ValueError("request_id must be positive")
        for boolean_field, boolean_value in (
            ("current", self.current),
            ("stale", self.stale),
            ("cancelled", self.cancelled),
            ("latest_wins", self.latest_wins),
        ):
            if boolean_value is not None and not isinstance(boolean_value, bool):
                raise TypeError(f"request {boolean_field} must be a bool or None")
        for text_field, text_value in (
            ("delivery", self.delivery),
            ("fallback", self.fallback),
            ("error", self.error),
        ):
            if text_value is not None and not isinstance(text_value, str):
                raise TypeError(f"request {text_field} must be a string or None")


@dataclass(frozen=True)
class DiagnosticSnapshot:
    """A complete, nullable snapshot of one benchmark lookup observation."""

    cursor: PointDiagnostic | Any | None = None
    monitor: MonitorDiagnostic | Any | None = None
    screen: RectangleDiagnostic | Any | None = None
    roi: RectangleDiagnostic | Any | None = None
    target: TargetDiagnostic | Any | None = None
    hover: HoverDiagnostic | None = None
    ocr: OCRDiagnostic | None = None
    morphology: MorphologyDiagnostic | None = None
    dictionary: DictionaryDiagnostic | None = None
    timings: tuple[StageTiming, ...] | Sequence[StageTiming] = ()
    providers: tuple[str, ...] | Sequence[str] = ()
    resources: tuple[str, ...] | Sequence[str] = ()
    request: RequestDiagnostic | None = None

    def __post_init__(self) -> None:
        if self.cursor is not None and not isinstance(self.cursor, PointDiagnostic):
            object.__setattr__(self, "cursor", _coerce_point(self.cursor))
        if self.monitor is not None and not isinstance(self.monitor, MonitorDiagnostic):
            object.__setattr__(self, "monitor", _coerce_monitor(self.monitor))
        for field in ("screen", "roi"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, RectangleDiagnostic):
                object.__setattr__(self, field, _coerce_rectangle(value))
        if self.target is not None and not isinstance(self.target, TargetDiagnostic):
            object.__setattr__(self, "target", TargetDiagnostic(self.target))
        for field, expected in (
            ("hover", HoverDiagnostic),
            ("ocr", OCRDiagnostic),
            ("morphology", MorphologyDiagnostic),
            ("dictionary", DictionaryDiagnostic),
            ("request", RequestDiagnostic),
        ):
            value = getattr(self, field)
            if value is not None and not isinstance(value, expected):
                raise TypeError(f"{field} must be {expected.__name__} or None")
        timings = tuple(self.timings)
        if any(not isinstance(timing, StageTiming) for timing in timings):
            raise TypeError("timings must contain StageTiming values")
        if len({timing.stage for timing in timings}) != len(timings):
            raise ValueError("timing stages must be unique")
        object.__setattr__(self, "timings", timings)
        for field in ("providers", "resources"):
            values = tuple(getattr(self, field))
            if any(not isinstance(value, str) for value in values):
                raise TypeError(f"{field} must contain strings")
            object.__setattr__(self, field, values)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_number(value: object) -> Number | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _is_point_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 4


def _coerce_point(value: Any) -> PointDiagnostic:
    if isinstance(value, PointDiagnostic):
        return value
    if isinstance(value, Mapping):
        return PointDiagnostic(value["x"], value["y"])
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        return PointDiagnostic(value[0], value[1])
    if hasattr(value, "x") and hasattr(value, "y"):
        return PointDiagnostic(value.x, value.y)
    raise TypeError("point must expose x/y coordinates")


def _coerce_rectangle(value: Any) -> RectangleDiagnostic:
    if isinstance(value, RectangleDiagnostic):
        return value
    if isinstance(value, Mapping):
        if "right" in value and "bottom" in value:
            return RectangleDiagnostic(value["left"], value["top"], value["right"], value["bottom"])
        return RectangleDiagnostic(
            value["left"],
            value["top"],
            value["left"] + value["width"],
            value["top"] + value["height"],
        )
    if all(hasattr(value, field) for field in ("left", "top", "right", "bottom")):
        return RectangleDiagnostic(value.left, value.top, value.right, value.bottom)
    if all(hasattr(value, field) for field in ("left", "top", "width", "height")):
        return RectangleDiagnostic(
            value.left,
            value.top,
            value.left + value.width,
            value.top + value.height,
        )
    raise TypeError("rectangle must expose left/top/right/bottom or width/height")


def _coerce_monitor(value: Any) -> MonitorDiagnostic:
    if isinstance(value, MonitorDiagnostic):
        return value
    name = value.get("name") if isinstance(value, Mapping) else getattr(value, "name", None)
    bounds = value.get("bounds") if isinstance(value, Mapping) else getattr(value, "bounds", None)
    return MonitorDiagnostic(name, _coerce_rectangle(bounds) if bounds is not None else None)


def _coerce_quad(value: Any) -> tuple[PointDiagnostic, ...]:
    points = getattr(value, "points", value)
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise TypeError("OCR quad must expose four points")
    normalized = tuple(_coerce_point(point) for point in points)
    if len(normalized) != 4:
        raise ValueError("OCR quad must contain four points")
    return normalized


def _coerce_morphology_token(value: Any) -> MorphologyTokenDiagnostic:
    if isinstance(value, MorphologyTokenDiagnostic):
        return value
    if isinstance(value, Mapping):
        return MorphologyTokenDiagnostic(
            value.get("token"),
            value.get("start", value.get("offset_start")),
            value.get("end", value.get("offset_end")),
            value.get("lemma"),
        )
    return MorphologyTokenDiagnostic(
        getattr(value, "token", None),
        getattr(value, "start", getattr(value, "offset_start", None)),
        getattr(value, "end", getattr(value, "offset_end", None)),
        getattr(value, "lemma", None),
    )


def _serialize_point(point: PointDiagnostic | None) -> dict[str, Number] | None:
    return None if point is None else {"x": point.x, "y": point.y}


def _serialize_rectangle(rectangle: RectangleDiagnostic | None) -> dict[str, Number] | None:
    if rectangle is None:
        return None
    return {
        "left": rectangle.left,
        "top": rectangle.top,
        "right": rectangle.right,
        "bottom": rectangle.bottom,
    }


def serialize_diagnostic(snapshot: DiagnosticSnapshot) -> dict[str, Any]:
    """Return a JSON-compatible payload with explicit nulls for unavailable facts."""

    if not isinstance(snapshot, DiagnosticSnapshot):
        raise TypeError("snapshot must be a DiagnosticSnapshot")

    monitor = None
    if snapshot.monitor is not None:
        monitor = {
            "name": snapshot.monitor.name,
            "bounds": _serialize_rectangle(snapshot.monitor.bounds),
        }

    target = None
    if snapshot.target is not None:
        target = {
            "point": _serialize_point(snapshot.target.point),
            "available": snapshot.target.available,
        }

    hover = None
    if snapshot.hover is not None:
        hover = {
            "state": snapshot.hover.state,
            "radius": snapshot.hover.radius,
            "dwell_ms": snapshot.hover.dwell_ms,
            "pending": snapshot.hover.pending,
            "active": snapshot.hover.active,
        }

    ocr = None
    if snapshot.ocr is not None:
        regions = [
            {
                "quad": [_serialize_point(point) for point in region.quad],
                "text": region.text,
                "confidence": region.confidence,
            }
            for region in snapshot.ocr.regions
        ]
        selected = None
        if snapshot.ocr.selected_index is not None:
            selected = regions[snapshot.ocr.selected_index]
        ocr = {
            "regions": regions,
            "selected_index": snapshot.ocr.selected_index,
            "selected": selected,
        }

    morphology = None
    if snapshot.morphology is not None:
        tokens = [
            {
                "token": token.token,
                "offsets": {"start": token.start, "end": token.end},
                "lemma": token.lemma,
            }
            for token in snapshot.morphology.tokens
        ]
        selected = None
        if snapshot.morphology.selected_index is not None:
            selected = tokens[snapshot.morphology.selected_index]
        morphology = {
            "tokens": tokens,
            "selected_index": snapshot.morphology.selected_index,
            "selected": selected,
            "lemma": snapshot.morphology.lemma,
        }

    dictionary = None
    if snapshot.dictionary is not None:
        dictionary = {"key": snapshot.dictionary.key, "status": snapshot.dictionary.status}

    request = None
    if snapshot.request is not None:
        request = {
            "request_id": snapshot.request.request_id,
            "current": snapshot.request.current,
            "stale": snapshot.request.stale,
            "cancelled": snapshot.request.cancelled,
            "latest_wins": snapshot.request.latest_wins,
            "delivery": snapshot.request.delivery,
            "fallback": snapshot.request.fallback,
            "error": snapshot.request.error,
        }

    return {
        "schema_version": 1,
        "cursor": _serialize_point(snapshot.cursor),
        "monitor": monitor,
        "screen": _serialize_rectangle(snapshot.screen),
        "roi": _serialize_rectangle(snapshot.roi),
        "target": target,
        "hover": hover,
        "ocr": ocr,
        "morphology": morphology,
        "dictionary": dictionary,
        "timings": {timing.stage: timing.duration_ms for timing in snapshot.timings},
        "providers": list(snapshot.providers),
        "resources": list(snapshot.resources),
        "request": request,
    }


def _point_from_payload(value: Any) -> PointDiagnostic | None:
    return None if value is None else _coerce_point(value)


def _rectangle_from_payload(value: Any) -> RectangleDiagnostic | None:
    return None if value is None else _coerce_rectangle(value)


def deserialize_diagnostic(payload: Mapping[str, Any]) -> DiagnosticSnapshot:
    """Rebuild a snapshot from :func:`serialize_diagnostic` output."""

    if not isinstance(payload, Mapping):
        raise TypeError("diagnostic payload must be a mapping")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported diagnostic schema version")

    monitor_payload = payload.get("monitor")
    monitor = None
    if monitor_payload is not None:
        monitor = MonitorDiagnostic(
            monitor_payload.get("name"),
            _rectangle_from_payload(monitor_payload.get("bounds")),
        )

    target_payload = payload.get("target")
    target = None
    if target_payload is not None:
        target = TargetDiagnostic(
            _point_from_payload(target_payload.get("point")),
            target_payload.get("available"),
        )

    hover_payload = payload.get("hover")
    hover = None if hover_payload is None else HoverDiagnostic(**hover_payload)

    ocr_payload = payload.get("ocr")
    ocr = None
    if ocr_payload is not None:
        ocr = OCRDiagnostic(
            tuple(
                OCRRegionDiagnostic(
                    tuple(_coerce_point(point) for point in region["quad"]),
                    region.get("text"),
                    region.get("confidence"),
                )
                for region in ocr_payload.get("regions", ())
            ),
            ocr_payload.get("selected_index"),
        )

    morphology_payload = payload.get("morphology")
    morphology = None
    if morphology_payload is not None:
        morphology = MorphologyDiagnostic(
            tuple(
                MorphologyTokenDiagnostic(
                    token.get("token"),
                    (token.get("offsets") or {}).get("start"),
                    (token.get("offsets") or {}).get("end"),
                    token.get("lemma"),
                )
                for token in morphology_payload.get("tokens", ())
            ),
            morphology_payload.get("selected_index"),
            morphology_payload.get("lemma"),
        )

    dictionary_payload = payload.get("dictionary")
    dictionary = None if dictionary_payload is None else DictionaryDiagnostic(**dictionary_payload)

    request_payload = payload.get("request")
    request = None if request_payload is None else RequestDiagnostic(**request_payload)

    return DiagnosticSnapshot(
        cursor=_point_from_payload(payload.get("cursor")),
        monitor=monitor,
        screen=_rectangle_from_payload(payload.get("screen")),
        roi=_rectangle_from_payload(payload.get("roi")),
        target=target,
        hover=hover,
        ocr=ocr,
        morphology=morphology,
        dictionary=dictionary,
        timings=tuple(
            StageTiming(stage, duration)
            for stage, duration in payload.get("timings", {}).items()
        ),
        providers=tuple(payload.get("providers", ())),
        resources=tuple(payload.get("resources", ())),
        request=request,
    )


def write_diagnostic_json(snapshot: DiagnosticSnapshot, destination: str | Path) -> Path:
    """Write a UTF-8 structured snapshot and return its path."""

    path = Path(destination)
    path.write_text(
        json.dumps(
            serialize_diagnostic(snapshot), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def render_diagnostic_html(
    snapshot: DiagnosticSnapshot,
    destination: str | Path | None = None,
) -> str:
    """Render a standalone inspector with all snapshot data embedded inline."""

    payload = json.dumps(
        serialize_diagnostic(snapshot), ensure_ascii=False, indent=2, sort_keys=True
    )
    safe_payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    escaped_text = escape(payload)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hanly Diagnostic Inspector</title>
<style>
  :root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
  body {{ margin: 2rem; background: #11161c; color: #e7edf3; }}
  main {{ max-width: 72rem; margin: auto; }}
  pre {{ padding: 1rem; overflow: auto; border: 1px solid #394653;
    border-radius: .5rem; background: #1c252e; }}
  code {{ color: #a9e6b8; }}
</style>
</head>
<body>
<main>
<h1>Hanly Diagnostic Inspector</h1>
<p>Structured snapshot; null values mean the observed provider did not expose the fact.</p>
<pre id="diagnostic">{escaped_text}</pre>
<script type="application/json" id="diagnostic-data">{safe_payload}</script>
</main>
</body>
</html>
"""
    if destination is not None:
        Path(destination).write_text(html, encoding="utf-8")
    return html


def render_annotated_png(
    source: str | Path | Any,
    destination: str | Path,
    snapshot: DiagnosticSnapshot,
) -> Path:
    """Render target/OCR geometry on a copy of ``source`` without mutating it."""

    try:
        from PIL import Image, ImageDraw
    except ImportError as error:  # pragma: no cover - depends on optional dev extra
        raise RuntimeError("Pillow is required to render diagnostic PNGs") from error

    if isinstance(source, (str, Path)):
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
    else:
        if not hasattr(source, "copy"):
            raise TypeError("source must be a path or Pillow image")
        image = source.copy().convert("RGBA")

    draw = ImageDraw.Draw(image, "RGBA")
    if snapshot.ocr is not None:
        for index, region in enumerate(snapshot.ocr.regions):
            points = [(point.x, point.y) for point in region.quad]
            selected = index == snapshot.ocr.selected_index
            color = (255, 193, 7, 255) if selected else (0, 188, 212, 255)
            width = 4 if selected else 2
            draw.line(points + [points[0]], fill=color, width=width, joint="curve")

    point = snapshot.target.point if snapshot.target is not None else None
    if point is not None:
        x, y = point.x, point.y
        radius = 5
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=(255, 255, 255, 255),
            width=3,
        )
        draw.line((x - 8, y, x + 8, y), fill=(236, 72, 153, 255), width=2)
        draw.line((x, y - 8, x, y + 8), fill=(236, 72, 153, 255), width=2)

    path = Path(destination)
    image.save(path, format="PNG")
    image.close()
    return path


# Short aliases keep the public surface convenient for benchmark scripts.
serialize_snapshot = serialize_diagnostic
deserialize_snapshot = deserialize_diagnostic
write_diagnostic = write_diagnostic_json


__all__ = [
    "DiagnosticSnapshot",
    "DictionaryDiagnostic",
    "HoverDiagnostic",
    "MorphologyDiagnostic",
    "MorphologyTokenDiagnostic",
    "MonitorDiagnostic",
    "OCRDiagnostic",
    "OCRRegionDiagnostic",
    "PointDiagnostic",
    "RectangleDiagnostic",
    "RequestDiagnostic",
    "StageTiming",
    "TargetDiagnostic",
    "deserialize_diagnostic",
    "deserialize_snapshot",
    "render_annotated_png",
    "render_diagnostic_html",
    "serialize_diagnostic",
    "serialize_snapshot",
    "write_diagnostic",
    "write_diagnostic_json",
]
