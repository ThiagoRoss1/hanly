"""Freezing, the export boundary, and the layers the inspector distinguishes.

The load-bearing test in this file is the privacy one: a session that freezes a
lookup must still write no screen content anywhere. Everything else here is
about a frozen record staying the record it was.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly import PixelFormat, Point, ROIImage
from hanly_app.capture import CapturePlan, CaptureResult, ScreenRect
from hanly_app.lookup_evidence import (
    encode_dictionary_evidence,
    encode_morphology_evidence,
    encode_ocr_evidence,
    encode_resolution_evidence,
)

from benchmarks.dev.frozen_lookup import FrozenLookup, LookupRing
from benchmarks.dev.live_runner import RuntimeTraceAdapter
from benchmarks.dev.live_telemetry import (
    LiveTraceRecorder,
    ScenarioPhaseController,
    SessionPrivacy,
)
from benchmarks.dev.microscope import (
    LAYERS,
    ExportRefused,
    MicroscopeCaptureObserver,
    MicroscopeSink,
    build_ring,
    describe_frozen,
    export_frozen,
    freeze,
    render_frozen_html,
)

_SECRET = "비밀번호 입력"
_REGION = ScreenRect(400, 300, 8, 4)
_ROI = ROIImage(8, 4, PixelFormat.RGB_888, bytes(range(96)))


def _plan() -> CapturePlan:
    return CapturePlan(
        requested_cursor=Point(404.0, 302.0),
        effective_cursor=Point(404.0, 302.0),
        monitor_index=1,
        monitor_name="Primary",
        monitor_bounds=ScreenRect(0, 0, 1920, 1080),
        configured_region=None,
        clip_bounds=ScreenRect(0, 0, 1920, 1080),
        roi_size=(8, 4),
        roi_grid=1,
        ideal_region=_REGION,
        desired_region=_REGION,
        actual_region=_REGION,
        target=Point(4.0, 2.0),
        image_width=8,
        image_height=4,
        pixel_format=PixelFormat.RGB_888,
        image_byte_length=96,
    )


def _capture() -> CaptureResult:
    return CaptureResult(image=_ROI, region=_REGION, target=Point(4.0, 2.0), plan=_plan())


def _resolution_evidence_json() -> str:
    from hanly import BoundingBox, OCRResult, Quad, TargetResolution
    from hanly.word_resolver import CandidateEvidence, ResolutionEvidence

    quad = Quad.from_bounding_box(BoundingBox(0, 0, 8, 4))
    region = OCRResult(text=_SECRET, confidence=0.8, quad=quad)
    return encode_resolution_evidence(
        ResolutionEvidence(
            resolution=TargetResolution(
                region=region, text="입력", cursor_index=0, region_start=5
            ),
            candidates=(
                CandidateEvidence(
                    index=0,
                    text=_SECRET,
                    confidence=0.8,
                    quad=quad,
                    usable=True,
                    unusable_reason=None,
                    contains_target=True,
                ),
            ),
            selected_index=0,
            horizontal_fraction=0.7,
            character_index=5,
            word_span=(5, 7),
            word_bounds=BoundingBox(4, 0, 8, 4),
        )
    )


def _ocr_evidence_json() -> str:
    from hanly import BoundingBox, OCRResult, Quad

    return encode_ocr_evidence(
        [OCRResult(_SECRET, 0.8, Quad.from_bounding_box(BoundingBox(0, 0, 8, 4)))]
    )


def _events(hover_id: int = 7, lookup_id: int = 11) -> list[dict[str, object]]:
    """One complete lookup's worth of raw trace events, secrets included."""

    from hanly import LexicalCandidate, MorphologyAnalysis, TokenAnalysis

    analysis = MorphologyAnalysis(
        tokens=(TokenAnalysis(token="입력", lemma="입력", start=0, length=2),),
        candidates=(LexicalCandidate(lemma="입력", start=0, end=2),),
    )
    return [
        {"event_kind": "hover_stable_fire", "hover_request_id": hover_id},
        {
            "event_kind": "hover_submission",
            "hover_request_id": hover_id,
            "lookup_request_id": lookup_id,
        },
        {
            "event_kind": "lookup_stage_completed",
            "stage": "ocr",
            "lookup_request_id": lookup_id,
            "ocr_text": _SECRET,
            "ocr_evidence": _ocr_evidence_json(),
            "region_count": 1,
            "hangul_region_count": 1,
            "gate_ran": True,
            "gate_passed": True,
            "provider_executed": True,
        },
        {
            "event_kind": "lookup_stage_completed",
            "stage": "token_selection",
            "lookup_request_id": lookup_id,
            "resolution_evidence": _resolution_evidence_json(),
            "cursor_index": 0,
        },
        {
            "event_kind": "lookup_stage_completed",
            "stage": "morphology",
            "lookup_request_id": lookup_id,
            "morphology_evidence": encode_morphology_evidence("입력", analysis),
        },
        {
            "event_kind": "lookup_stage_completed",
            "stage": "dictionary",
            "lookup_request_id": lookup_id,
            "dictionary_evidence": encode_dictionary_evidence("입력", 1),
        },
        {
            "event_kind": "retained_target",
            "lookup_request_id": lookup_id,
            "word_left": 404,
            "word_top": 300,
            "word_width": 4,
            "word_height": 4,
            "protected_left": 400,
            "protected_top": 296,
            "protected_width": 12,
            "protected_height": 12,
            "screen_scale": 1.0,
        },
        {
            "event_kind": "popup_visible",
            "lookup_request_id": lookup_id,
            "result_status": "SUCCESS",
        },
    ]


def _session(ring: LookupRing, events_path: Path) -> tuple[MicroscopeSink, LiveTraceRecorder]:
    """The real composition: the tee over the adapter that writes the trace."""

    recorder = LiveTraceRecorder(events_path)
    adapter = RuntimeTraceAdapter(
        recorder, ScenarioPhaseController(), SessionPrivacy(key=b"session")
    )
    return MicroscopeSink(ring, adapter), recorder


def _filled_ring(hover_id: int = 7, lookup_id: int = 11) -> LookupRing:
    ring = build_ring()
    ring.observe_capture(_capture(), "digest-abc", 100, hover_request_id=hover_id)
    for index, event in enumerate(_events(hover_id, lookup_id)):
        ring.observe_event(event, 200 + index)
    return ring


# --- Correlation and freezing -----------------------------------------------


def test_a_capture_joins_its_lookup_through_the_hover_submission_event() -> None:
    frozen = _filled_ring().freeze()

    assert frozen is not None
    assert frozen.hover_request_id == 7
    assert frozen.lookup_request_id == 11
    assert frozen.capture is not None
    assert frozen.capture.roi is _ROI
    assert frozen.capture.roi_digest == "digest-abc"


def test_a_frozen_lookup_is_immutable_against_everything_that_follows() -> None:
    ring = _filled_ring()
    frozen = ring.freeze()
    assert frozen is not None

    ring.observe_event(
        {
            "event_kind": "lookup_stage_completed",
            "stage": "dictionary",
            "lookup_request_id": 11,
            "dictionary_evidence": encode_dictionary_evidence("다른", 0),
        },
        999,
    )
    ring.observe_capture(
        CaptureResult(
            image=ROIImage(8, 4, PixelFormat.RGB_888, bytes(96)),
            region=_REGION,
            target=Point(4.0, 2.0),
        ),
        "digest-xyz",
        1000,
        hover_request_id=7,
    )

    assert frozen.capture is not None and frozen.capture.roi_digest == "digest-abc"
    assert frozen.stages["dictionary"]["query"] == "입력"
    assert len(frozen.events) == len(_events())


def test_a_lookup_still_in_flight_is_not_frozen() -> None:
    ring = build_ring()
    ring.observe_capture(_capture(), "digest", 1, hover_request_id=7)
    ring.observe_event(
        {"event_kind": "hover_stable_fire", "hover_request_id": 7}, 2
    )

    report = freeze(ring)

    assert report.frozen is None
    assert "no completed lookup" in (report.reason or "")


def test_the_newest_completed_lookup_wins() -> None:
    ring = _filled_ring(hover_id=1, lookup_id=2)
    for index, event in enumerate(_events(hover_id=3, lookup_id=4)):
        ring.observe_event(event, 5000 + index)

    frozen = ring.freeze()

    assert frozen is not None and frozen.lookup_request_id == 4


def test_the_ring_evicts_the_oldest_lookups() -> None:
    ring = LookupRing(size=2)
    for identifier in (1, 2, 3):
        ring.observe_event(
            {"event_kind": "popup_visible", "lookup_request_id": identifier}, identifier
        )

    assert ring.records() == 2
    frozen = ring.freeze()
    assert frozen is not None and frozen.lookup_request_id == 3


def test_an_incomplete_record_names_every_gap_with_a_reason() -> None:
    ring = build_ring()
    ring.observe_event(
        {
            "event_kind": "popup_suppressed",
            "lookup_request_id": 5,
            "result_status": "EMPTY",
        },
        1,
    )

    frozen = ring.freeze()

    assert frozen is not None
    assert frozen.complete is False
    assert frozen.result_status == "EMPTY"
    stages = {entry.split(":", 1)[0] for entry in frozen.missing}
    assert stages == {"capture", "ocr", "token_selection", "morphology", "dictionary"}


# --- Freeze writes nothing --------------------------------------------------


def test_freezing_creates_no_file_and_persists_no_screen_content(
    tmp_path: Path,
) -> None:
    """The load-bearing privacy test: a frozen session still writes nothing."""

    events_path = tmp_path / "live-events.jsonl"
    ring = build_ring()
    sink, recorder = _session(ring, events_path)
    observer = MicroscopeCaptureObserver(ring, SessionPrivacy(key=b"session"))

    observer.observe(_capture(), hover_request_id=7)
    for event in _events():
        sink.emit(event)
    observer.close()
    report = freeze(ring)
    recorder.close()

    assert report.frozen is not None
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["live-events.jsonl"]
    persisted = events_path.read_text(encoding="utf-8")
    assert _SECRET not in persisted
    assert "입력" not in persisted
    assert "resolution_evidence" not in persisted
    assert "morphology_evidence" not in persisted
    assert "ocr_evidence" not in persisted
    assert "dictionary_evidence" not in persisted


def test_the_frozen_record_keeps_the_text_the_trace_file_does_not(
    tmp_path: Path,
) -> None:
    ring = build_ring()
    sink, recorder = _session(ring, tmp_path / "live-events.jsonl")
    ring.observe_capture(_capture(), "digest", 1, hover_request_id=7)
    for event in _events():
        sink.emit(event)
    recorder.close()

    frozen = ring.freeze()

    assert frozen is not None
    assert frozen.stages["ocr"]["regions"][0]["text"] == _SECRET
    assert frozen.stages["dictionary"]["query"] == "입력"


def test_a_privacy_minimized_field_still_reaches_the_trace_file(
    tmp_path: Path,
) -> None:
    """Redaction removes screen content, not the measurements beside it."""

    events_path = tmp_path / "live-events.jsonl"
    sink, recorder = _session(build_ring(), events_path)
    for event in _events():
        sink.emit(event)
    recorder.close()

    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    ocr = next(row for row in rows if row.get("stage") == "ocr")
    assert ocr["gate_passed"] is True
    assert ocr["provider_executed"] is True
    assert ocr["has_hangul"] is True
    assert ocr["char_count"] == len(_SECRET)


# --- Export is separate and bounded -----------------------------------------


def _frozen() -> FrozenLookup:
    frozen = _filled_ring().freeze()
    assert frozen is not None
    return frozen


def test_export_writes_the_private_evidence_only_when_asked(tmp_path: Path) -> None:
    root = tmp_path / "artifacts" / "benchmarks" / "runs"
    destination = root / "run-1"

    exported = export_frozen(_frozen(), destination, artifact_root=root)

    names = sorted(path.name for path in exported.directory.iterdir())
    assert names == [
        "diagnostic.html",
        "diagnostic.json",
        "events.jsonl",
        "input.png",
        "metadata.json",
    ]
    diagnostic = json.loads((exported.directory / "diagnostic.json").read_text("utf-8"))
    assert diagnostic["stages"]["ocr"]["regions"][0]["text"] == _SECRET
    assert (exported.directory / "input.png").stat().st_size > 0


def test_export_refuses_a_destination_outside_the_artifact_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts" / "benchmarks" / "runs"
    root.mkdir(parents=True)

    with pytest.raises(ExportRefused, match="outside the benchmark artifact root"):
        export_frozen(_frozen(), tmp_path / "elsewhere", artifact_root=root)

    assert not (tmp_path / "elsewhere").exists()


def test_an_exported_metadata_file_says_it_holds_private_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"

    exported = export_frozen(_frozen(), root / "run-1", artifact_root=root)

    metadata = json.loads((exported.directory / "metadata.json").read_text("utf-8"))
    assert metadata["exported"] is True
    assert metadata["contains_private_screen_content"] is True


def test_an_exported_inspector_opens_on_its_own(tmp_path: Path) -> None:
    root = tmp_path / "runs"

    exported = export_frozen(_frozen(), root / "run-1", artifact_root=root)
    html = (exported.directory / "diagnostic.html").read_text("utf-8")

    assert "<!doctype html>" in html
    # The page refers to the exact exported ROI rather than an illustration.
    assert 'src="input.png"' in html
    assert (exported.directory / "input.png").exists()
    assert "frozen-data" in html


# --- Layers -----------------------------------------------------------------


def test_every_layer_is_named_and_says_whether_it_is_available() -> None:
    described = describe_frozen(_frozen())

    assert set(described["layers"]) == set(LAYERS)
    for name, layer in described["layers"].items():
        assert "available" in layer, name
        if not layer["available"]:
            assert layer["reason"], name


def test_the_layers_separate_roi_local_geometry_from_screen_geometry() -> None:
    layers = describe_frozen(_frozen())["layers"]

    assert layers["selected_ocr_region"]["space"] == "roi_local"
    assert layers["estimated_surface_bounds"]["space"] == "roi_local"
    assert layers["retained_bounds"]["space"] == "screen"
    assert layers["retained_bounds"]["rect"]["left"] == 404
    assert layers["retained_bounds"]["protected"]["left"] == 400


def test_a_lookup_without_a_staged_run_claims_no_detector_boxes() -> None:
    """Vision has no detector boxes, and readtext does not surface EasyOCR's."""

    layers = describe_frozen(_frozen())["layers"]

    assert layers["raw_detector_regions"]["available"] is False
    assert "staged" in layers["raw_detector_regions"]["reason"]
    assert describe_frozen(_frozen())["staged_ocr"] is None


def test_the_html_names_the_unavailable_evidence_rather_than_hiding_it() -> None:
    ring = build_ring()
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 3, "result_status": "SUCCESS"},
        1,
    )
    frozen = ring.freeze()
    assert frozen is not None

    html = render_frozen_html(frozen)

    assert "Unavailable evidence" in html
    assert "no ROI was observed" in html


def test_an_evidence_field_added_later_is_excluded_by_default(tmp_path: Path) -> None:
    """Privacy is a naming rule, not a list someone has to remember to extend."""

    events_path = tmp_path / "live-events.jsonl"
    sink, recorder = _session(build_ring(), events_path)

    sink.emit(
        {
            "event_kind": "lookup_stage_completed",
            "stage": "future",
            "lookup_request_id": 1,
            "some_future_evidence": json.dumps({"text": _SECRET}),
            "region_count": 3,
        }
    )
    recorder.close()

    persisted = events_path.read_text(encoding="utf-8")
    assert _SECRET not in persisted
    assert "some_future_evidence" not in persisted
    assert '"region_count":3' in persisted


def test_a_lookup_that_ended_at_empty_ocr_says_the_rest_was_not_reached() -> None:
    """An empty OCR pass answers for every stage after it; that is not a gap."""

    ring = build_ring()
    ring.observe_capture(_capture(), "digest", 1, hover_request_id=7)
    ring.observe_event(
        {
            "event_kind": "lookup_stage_completed",
            "stage": "ocr",
            "hover_request_id": 7,
            "lookup_request_id": 11,
            "region_count": 0,
            "ocr_evidence": encode_ocr_evidence([]),
            "gate_ran": True,
            "gate_passed": True,
        },
        2,
    )
    ring.observe_event(
        {"event_kind": "popup_suppressed", "lookup_request_id": 11, "result_status": "EMPTY"},
        3,
    )

    frozen = ring.freeze()

    assert frozen is not None
    assert frozen.stages["ocr"]["regions"] == []
    reasons = dict(entry.split(":", 1) for entry in frozen.missing)
    assert reasons == {
        "token_selection": "not reached; the lookup ended earlier",
        "morphology": "not reached; the lookup ended earlier",
        "dictionary": "not reached; the lookup ended earlier",
    }


def test_a_cache_hit_reports_ocr_as_skipped_rather_than_absent() -> None:
    """A cache hit answered the question; it did not fail to answer it."""

    ring = build_ring()
    ring.observe_capture(_capture(), "digest", 1, hover_request_id=7)
    ring.observe_event(
        {
            "event_kind": "lookup_cache_hit",
            "lookup_request_id": 11,
            "hover_request_id": 7,
            "ocr_stage_skipped": True,
        },
        2,
    )
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 11, "result_status": "SUCCESS"},
        3,
    )

    frozen = ring.freeze()

    assert frozen is not None
    reasons = dict(entry.split(":", 1) for entry in frozen.missing)
    assert reasons["ocr"] == "skipped; an earlier answer was reused"


def test_a_silently_delivered_result_still_reports_its_outcome() -> None:
    """Only a presented result names its status; the pipeline always does."""

    ring = build_ring()
    ring.observe_event(
        {
            "event_kind": "lookup_stage_completed",
            "stage": "total_pipeline",
            "lookup_request_id": 4,
            "outcome": "SUCCESS",
        },
        1,
    )
    ring.observe_event({"event_kind": "lookup_current_delivered", "lookup_request_id": 4}, 2)

    frozen = ring.freeze()

    assert frozen is not None
    assert frozen.result_status == "SUCCESS"


def test_a_presented_status_wins_over_the_pipeline_outcome() -> None:
    ring = build_ring()
    ring.observe_event(
        {
            "event_kind": "lookup_stage_completed",
            "stage": "total_pipeline",
            "lookup_request_id": 4,
            "outcome": "SUCCESS",
        },
        1,
    )
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 4, "result_status": "SUCCESS"},
        2,
    )

    frozen = ring.freeze()

    assert frozen is not None and frozen.result_status == "SUCCESS"


def test_evicting_an_orphan_does_not_unregister_the_live_record() -> None:
    """Two records can claim one lookup id; only one of them owns the index.

    A lookup-only event arriving before the hover record that later adopts the
    same lookup id leaves the first one orphaned. Evicting that orphan must not
    unregister the live record, or the next lookup-only event starts a third
    record holding nothing but a terminal event — a frozen lookup that reads as
    a capture failure that never happened.
    """

    ring = LookupRing(size=8)
    ring.observe_event({"event_kind": "lookup_error", "lookup_request_id": 1}, 1)
    ring.observe_event({"event_kind": "hover_stable_fire", "hover_request_id": 1}, 2)
    ring.observe_event(
        {"event_kind": "hover_submission", "hover_request_id": 1, "lookup_request_id": 1},
        3,
    )
    ring.observe_capture(_capture(), "digest", 4, hover_request_id=1)

    for identifier in range(10, 17):
        ring.observe_event(
            {"event_kind": "hover_stable_fire", "hover_request_id": identifier},
            10 + identifier,
        )
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 1, "result_status": "SUCCESS"},
        99,
    )

    frozen = ring.freeze()

    assert frozen is not None
    assert frozen.lookup_request_id == 1
    assert frozen.hover_request_id == 1
    # The terminal event landed on the record that holds the rest of the story.
    assert [event.get("event_kind") for event in frozen.events] == [
        "hover_stable_fire",
        "hover_submission",
        "popup_visible",
    ]
    assert frozen.capture is not None


@pytest.mark.parametrize("index", [-1, -5, True, "0", 2.0])
def test_a_corrupted_selected_index_selects_nothing(index: object) -> None:
    """Decoded evidence is untrusted; a negative index must not wrap."""

    ring = build_ring()
    ring.observe_event(
        {
            "event_kind": "lookup_stage_completed",
            "stage": "token_selection",
            "lookup_request_id": 1,
            "resolution_evidence": json.dumps(
                {
                    "schema_version": 1,
                    "kind": "resolution",
                    "selected_index": index,
                    "candidates": [{"quad": [], "text": "첫"}, {"quad": [], "text": "둘"}],
                    "reason": None,
                }
            ),
        },
        1,
    )
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 1, "result_status": "SUCCESS"},
        2,
    )
    frozen = ring.freeze()
    assert frozen is not None

    layer = describe_frozen(frozen)["layers"]["selected_ocr_region"]

    assert layer["available"] is False
    assert "text" not in layer


# --- Backend attribution ----------------------------------------------------


def _ring_with_backend(backend: str | None) -> LookupRing:
    ring = build_ring()
    ring.observe_capture(_capture(), "digest-abc", 100, hover_request_id=7)
    ocr_event = {
        "event_kind": "lookup_stage_completed",
        "stage": "ocr",
        "hover_request_id": 7,
        "lookup_request_id": 11,
        "ocr_evidence": _ocr_evidence_json(),
        "region_count": 1,
    }
    if backend is not None:
        ocr_event["ocr_backend"] = backend
    ring.observe_event(ocr_event, 200)
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 11, "result_status": "SUCCESS"},
        201,
    )
    return ring


def test_the_backend_survives_freeze_and_reaches_the_export(tmp_path: Path) -> None:
    frozen = _ring_with_backend("vision").freeze()
    assert frozen is not None

    assert frozen.backend == "vision"
    assert describe_frozen(frozen)["live_ocr_backend"] == "vision"

    root = tmp_path / "runs"
    exported = export_frozen(frozen, root / "run-1", artifact_root=root)
    metadata = json.loads((exported.directory / "metadata.json").read_text("utf-8"))
    diagnostic = json.loads((exported.directory / "diagnostic.json").read_text("utf-8"))

    assert metadata["live_ocr_backend"] == "vision"
    assert diagnostic["live_ocr_backend"] == "vision"
    assert "vision" in (exported.directory / "diagnostic.html").read_text("utf-8")


def test_an_unrecorded_backend_reads_as_unrecorded_not_as_a_default() -> None:
    frozen = _ring_with_backend(None).freeze()
    assert frozen is not None

    assert frozen.backend is None
    assert describe_frozen(frozen)["live_ocr_backend"] is None
    assert "unrecorded" in render_frozen_html(frozen)


def test_a_staged_replay_cannot_be_mistaken_for_the_live_backend() -> None:
    """The replay is EasyOCR by construction; the live pass was Vision."""

    from dataclasses import replace as _replace

    from benchmarks.dev.easyocr_stages import COMPARISON_REPLAY, StagedRun, StageImage

    frozen = _ring_with_backend("vision").freeze()
    assert frozen is not None
    staged = StagedRun(
        evidence_class=COMPARISON_REPLAY,
        easyocr_version="1.7.2",
        detector_options={},
        recognizer_options={},
        source=StageImage(8, 4, "BGR", bytes(96)),
        grayscale=StageImage(8, 4, "L", bytes(32)),
    )
    described = describe_frozen(_replace(frozen, staged=staged))

    assert described["live_ocr_backend"] == "vision"
    assert described["staged_ocr"]["evidence_class"] == COMPARISON_REPLAY
    assert described["staged_ocr"]["is_replay"] is True
    # The two never collapse into one field.
    assert described["staged_ocr"].get("live_ocr_backend") is None
