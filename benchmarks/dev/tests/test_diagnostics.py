"""Focused tests for the developer diagnostics surface."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.dev.diagnostics import (
    DiagnosticSnapshot,
    DictionaryDiagnostic,
    HoverDiagnostic,
    MonitorDiagnostic,
    MorphologyDiagnostic,
    MorphologyTokenDiagnostic,
    OCRDiagnostic,
    OCRRegionDiagnostic,
    PointDiagnostic,
    RectangleDiagnostic,
    RequestDiagnostic,
    StageTiming,
    TargetDiagnostic,
    deserialize_diagnostic,
    render_annotated_png,
    render_diagnostic_html,
    serialize_diagnostic,
    write_diagnostic_json,
)


def _snapshot() -> DiagnosticSnapshot:
    quad = (
        PointDiagnostic(5, 5),
        PointDiagnostic(35, 5),
        PointDiagnostic(35, 20),
        PointDiagnostic(5, 20),
    )
    return DiagnosticSnapshot(
        cursor=PointDiagnostic(20, 12),
        monitor=MonitorDiagnostic("Monitor 1", RectangleDiagnostic(0, 0, 100, 80)),
        screen=RectangleDiagnostic(-100, 0, 100, 80),
        roi=RectangleDiagnostic(0, 0, 50, 30),
        target=TargetDiagnostic(PointDiagnostic(20, 12), available=True),
        hover=HoverDiagnostic(
            state="active",
            radius=8.0,
            dwell_ms=125.0,
            pending=False,
            active=True,
        ),
        ocr=OCRDiagnostic(
            regions=(
                OCRRegionDiagnostic(
                    quad=quad,
                    text="읽습니다.",
                    confidence=0.98,
                ),
            ),
            selected_index=0,
        ),
        morphology=MorphologyDiagnostic(
            tokens=(
                MorphologyTokenDiagnostic("읽습니다.", 0, 5, "읽다"),
            ),
            selected_index=0,
            lemma="읽다",
        ),
        dictionary=DictionaryDiagnostic(key="읽다", status="found"),
        timings=(StageTiming("capture", 1.25), StageTiming("ocr", 12.5)),
        providers=("EasyOCR", "Kiwi", "KRDICT"),
        resources=("ocr-model:valid", "krdict:valid"),
        request=RequestDiagnostic(
            request_id=7,
            current=True,
            stale=False,
            cancelled=False,
            latest_wins=True,
            delivery="current",
            fallback=None,
            error=None,
        ),
    )


def test_diagnostic_serialization_round_trips_all_observed_evidence() -> None:
    payload = serialize_diagnostic(_snapshot())

    assert payload["schema_version"] == 1
    assert payload["cursor"] == {"x": 20, "y": 12}
    assert payload["monitor"]["name"] == "Monitor 1"
    assert payload["screen"] == {"left": -100, "top": 0, "right": 100, "bottom": 80}
    assert payload["roi"]["right"] == 50
    assert payload["target"] == {"point": {"x": 20, "y": 12}, "available": True}
    assert payload["hover"]["dwell_ms"] == 125.0
    assert payload["ocr"]["regions"][0]["quad"][0] == {"x": 5, "y": 5}
    assert payload["ocr"]["regions"][0]["text"] == "읽습니다."
    assert payload["ocr"]["selected_index"] == 0
    assert payload["morphology"]["tokens"][0]["offsets"] == {"start": 0, "end": 5}
    assert payload["morphology"]["lemma"] == "읽다"
    assert payload["dictionary"] == {"key": "읽다", "status": "found"}
    assert payload["timings"] == {"capture": 1.25, "ocr": 12.5}
    assert payload["providers"] == ["EasyOCR", "Kiwi", "KRDICT"]
    assert payload["request"]["request_id"] == 7

    restored = deserialize_diagnostic(payload)
    assert serialize_diagnostic(restored) == payload


def test_missing_facts_are_serialized_as_null_not_guessed_values() -> None:
    payload = serialize_diagnostic(DiagnosticSnapshot())

    assert payload["cursor"] is None
    assert payload["monitor"] is None
    assert payload["screen"] is None
    assert payload["roi"] is None
    assert payload["target"] is None
    assert payload["hover"] is None
    assert payload["ocr"] is None
    assert payload["morphology"] is None
    assert payload["dictionary"] is None
    assert payload["request"] is None
    assert payload["providers"] == []
    assert payload["resources"] == []


def test_renderers_keep_source_unchanged_and_distinguish_target_and_selected_ocr(
    tmp_path: Path,
) -> None:
    image = __import__("PIL.Image", fromlist=["Image"]).new("RGB", (50, 30), "white")
    before = image.tobytes()
    output = tmp_path / "diagnostic.png"

    render_annotated_png(image, output, _snapshot())

    assert image.tobytes() == before
    rendered = __import__("PIL.Image", fromlist=["Image"]).open(output).convert("RGB")
    assert rendered.tobytes() != image.tobytes()
    # Selected OCR is yellow and target is magenta; both must be visible.
    pixels = {
        rendered.getpixel((x, y))
        for x in range(rendered.width)
        for y in range(rendered.height)
    }
    assert any(red > 200 and green > 150 and blue < 100 for red, green, blue in pixels)
    assert any(red > 180 and blue > 120 and green < 120 for red, green, blue in pixels)


def test_html_and_json_artifacts_are_self_contained(tmp_path: Path) -> None:
    snapshot = _snapshot()
    html = render_diagnostic_html(snapshot)
    assert "EasyOCR" in html
    assert "application/json" in html
    assert "https://" not in html

    html_path = tmp_path / "diagnostic.html"
    json_path = tmp_path / "diagnostic.json"
    render_diagnostic_html(snapshot, html_path)
    write_diagnostic_json(snapshot, json_path)
    assert html_path.read_text(encoding="utf-8") == html
    assert json.loads(json_path.read_text(encoding="utf-8"))["request"]["current"] is True
