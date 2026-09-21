"""Resolver, morphology, and dictionary evidence, and how it is encoded.

The evidence exists so a wrong popup can be attributed to a named stage. Its
one hard requirement is that it comes from the computation it describes, so a
resolver explanation can never disagree with the resolution it explains.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LexicalCandidate,
    MorphologyAnalysis,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TokenAnalysis,
)
from hanly.word_resolver import WordResolver
from hanly_app.composition import LookupWorker
from hanly_app.lookup_controller import LookupRequest
from hanly_app.lookup_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    decode_evidence,
    encode_morphology_evidence,
)

_IMAGE = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x00")


def _region(text: str, box: BoundingBox, confidence: float = 0.9) -> OCRResult:
    return OCRResult(text=text, confidence=confidence, quad=Quad.from_bounding_box(box))


# --- The resolver explains its own answer -----------------------------------


def test_evidence_and_the_ordinary_api_return_the_same_selection() -> None:
    regions = (_region("책상 위에", BoundingBox(0, 0, 60, 10)),)
    target = Point(15, 5)

    evidence = WordResolver.resolve_target_evidence(regions, target)
    detail = WordResolver.resolve_target_detail(regions, target)
    pair = WordResolver.resolve_target(regions, target)

    assert evidence.resolution == detail
    assert detail is not None and pair == (detail.region, detail.text)
    assert evidence.reason is None


def test_evidence_records_every_candidate_and_whether_it_holds_the_target() -> None:
    regions = (
        _region("먼저", BoundingBox(0, 0, 20, 10)),
        _region("책", BoundingBox(30, 0, 50, 10)),
        _region("   ", BoundingBox(60, 0, 80, 10)),
    )

    evidence = WordResolver.resolve_target_evidence(regions, Point(40, 5))

    assert [candidate.index for candidate in evidence.candidates] == [0, 1, 2]
    assert [candidate.contains_target for candidate in evidence.candidates] == [
        False,
        True,
        False,
    ]
    assert evidence.candidates[2].usable is False
    assert evidence.candidates[2].unusable_reason == "blank_text"
    assert evidence.selected_index == 1


def test_overlapping_lines_record_the_scores_that_broke_the_tie() -> None:
    """Scores are recorded only where several candidates actually competed."""

    regions = (
        _region("위의 줄", BoundingBox(0, 0, 40, 22)),
        _region("아래 줄", BoundingBox(0, 18, 40, 40)),
    )

    evidence = WordResolver.resolve_target_evidence(regions, Point(10, 20))

    margins = [candidate.vertical_margin for candidate in evidence.candidates]
    areas = [candidate.area for candidate in evidence.candidates]
    assert all(margin is not None for margin in margins)
    assert all(area is not None for area in areas)
    selected = evidence.selected_index
    assert selected is not None
    assert margins[selected] == max(margin for margin in margins if margin is not None)


def test_a_single_hit_records_no_tie_break_it_never_needed() -> None:
    regions = (_region("책", BoundingBox(0, 0, 20, 10)),)

    evidence = WordResolver.resolve_target_evidence(regions, Point(10, 5))

    assert evidence.candidates[0].vertical_margin is None
    assert evidence.candidates[0].area is None


def test_mixed_script_advance_weights_are_exact_and_cumulative() -> None:
    regions = (_region("책 ab", BoundingBox(0, 0, 40, 10)),)

    evidence = WordResolver.resolve_target_evidence(regions, Point(35, 5))

    assert evidence.advance_weights == (1.0, 0.35, 0.55, 0.55)
    assert evidence.cumulative_advances == pytest.approx((1.0, 1.35, 1.9, 2.45))
    assert evidence.horizontal_fraction is not None
    assert evidence.character_index is not None


def test_the_word_span_region_start_and_cursor_offset_agree() -> None:
    regions = (_region("나는 책상", BoundingBox(0, 0, 50, 10)),)

    evidence = WordResolver.resolve_target_evidence(regions, Point(46, 5))
    resolution = evidence.resolution

    assert resolution is not None
    assert evidence.word_span == (3, 5)
    assert resolution.region_start == 3
    assert evidence.character_index == resolution.region_start + resolution.cursor_index
    assert resolution.text == "책상"
    assert evidence.word_bounds is not None


def test_a_target_on_whitespace_says_so_instead_of_resolving() -> None:
    regions = (_region("책 상", BoundingBox(0, 0, 30, 10)),)

    evidence = WordResolver.resolve_target_evidence(regions, Point(14, 5))

    assert evidence.resolution is None
    assert evidence.reason == "target_on_whitespace"
    assert evidence.character_index == 1
    assert evidence.selected_index == 0


def test_a_target_inside_nothing_names_that_reason() -> None:
    regions = (_region("책", BoundingBox(0, 0, 10, 10)),)

    evidence = WordResolver.resolve_target_evidence(regions, Point(500, 500))

    assert evidence.resolution is None
    assert evidence.reason == "no_candidate_contains_target"
    assert evidence.selected_index is None
    assert evidence.candidates[0].contains_target is False


def test_a_missing_target_and_missing_results_are_distinguishable() -> None:
    assert WordResolver.resolve_target_evidence((), None).reason == "no_target"
    assert WordResolver.resolve_target_evidence(None, Point(1, 1)).reason == "no_ocr_results"


def test_a_tilted_quad_still_reports_its_text_axis() -> None:
    quad = Quad(
        p1=Point(0.0, 2.0), p2=Point(40.0, 0.0), p3=Point(40.0, 12.0), p4=Point(0.0, 14.0)
    )
    regions = (OCRResult(text="책상", confidence=0.9, quad=quad),)

    evidence = WordResolver.resolve_target_evidence(regions, Point(30, 6))

    assert evidence.text_axis is not None
    start, end = evidence.text_axis
    assert start.x < end.x
    assert evidence.resolution is not None


# --- Evidence reaches a trace sink, unchanged -------------------------------


class _EvidenceSink:
    """A sink that asks for the private structures, as the microscope does."""

    retain_evidence = True

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: Mapping[str, object]) -> None:
        self.events.append(dict(event))


class _PlainSink(_EvidenceSink):
    retain_evidence = False


class _SentenceOCR:
    def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
        return (_region("나는 책상", BoundingBox(0, 0, 50, 10)),)


class _KiwiLikeMorphology:
    def analyze(self, text: str) -> MorphologyAnalysis:
        assert text == "책상"
        return MorphologyAnalysis(
            tokens=(
                TokenAnalysis(token="책", lemma="책", part_of_speech="NNG", start=0, length=1),
                TokenAnalysis(token="상", lemma="상", part_of_speech="NNG", start=1, length=1),
            ),
            candidates=(
                LexicalCandidate(lemma="책", start=0, end=1, part_of_speech="NNG"),
                LexicalCandidate(lemma="상", start=1, end=2, part_of_speech="NNG"),
            ),
        )


class _Dictionary:
    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        return (DictionaryEntry(headword=lemma, definitions=("a definition",)),)


def _run(sink: _EvidenceSink) -> None:
    worker = LookupWorker(
        _SentenceOCR, _KiwiLikeMorphology, _Dictionary, trace_sink=sink
    )
    worker(LookupRequest(1, _IMAGE, Point(46, 5)))
    worker.close()


def _stage(sink: _EvidenceSink, stage: str) -> dict[str, object]:
    for event in sink.events:
        if event.get("event_kind") == "lookup_stage_completed" and event.get("stage") == stage:
            return event
    raise AssertionError(f"no {stage} stage event was emitted")


def test_the_traced_resolution_evidence_describes_the_lookup_that_happened() -> None:
    sink = _EvidenceSink()
    _run(sink)

    event = _stage(sink, "token_selection")
    assert event["resolved"] is True
    assert event["selected_region_index"] == 0
    assert event["resolution_reason"] is None
    payload = decode_evidence(event["resolution_evidence"])
    assert payload is not None
    assert payload["kind"] == "resolution"
    assert payload["resolution"]["text"] == "책상"
    assert payload["resolution"]["region_text"] == "나는 책상"
    assert payload["resolution"]["cursor_index"] == event["cursor_index"]
    assert payload["word_span"] == [3, 5]
    assert len(payload["candidates"]) == 1


def test_the_kiwi_analysis_and_the_krdict_query_are_both_recorded() -> None:
    sink = _EvidenceSink()
    _run(sink)

    morphology = decode_evidence(_stage(sink, "morphology")["morphology_evidence"])
    assert morphology is not None
    assert morphology["analyzed_text"] == "책상"
    assert [token["lemma"] for token in morphology["tokens"]] == ["책", "상"]
    assert [candidate["lemma"] for candidate in morphology["candidates"]] == ["책", "상"]
    assert morphology["candidates_available"] is True

    dictionary = decode_evidence(_stage(sink, "dictionary")["dictionary_evidence"])
    assert dictionary is not None
    # The pointer is on the second syllable, so the query is the unit there.
    assert dictionary["query"] == "상"
    assert dictionary["entry_count"] == 1
    assert dictionary["found"] is True


def test_normalized_live_ocr_output_is_recorded_in_provider_order() -> None:
    sink = _EvidenceSink()
    _run(sink)

    payload = decode_evidence(_stage(sink, "ocr")["ocr_evidence"])
    assert payload is not None
    assert [region["text"] for region in payload["regions"]] == ["나는 책상"]
    assert payload["regions"][0]["index"] == 0
    assert len(payload["regions"][0]["quad"]) == 4


def test_a_sink_that_did_not_ask_for_evidence_receives_none_of_it() -> None:
    sink = _PlainSink()
    _run(sink)

    for stage in ("ocr", "token_selection", "morphology", "dictionary"):
        event = _stage(sink, stage)
        assert not any(key.endswith("_evidence") for key in event)


def test_evidence_collection_does_not_change_the_result() -> None:
    def run(sink: _EvidenceSink) -> object:
        worker = LookupWorker(
            _SentenceOCR, _KiwiLikeMorphology, _Dictionary, trace_sink=sink
        )
        try:
            return worker(LookupRequest(1, _IMAGE, Point(46, 5)))
        finally:
            worker.close()

    assert run(_EvidenceSink()) == run(_PlainSink())


# --- Encoding -----------------------------------------------------------


def test_a_sequence_only_morphology_provider_reports_no_candidates_available() -> None:
    tokens: Sequence[TokenAnalysis] = (TokenAnalysis(token="책", lemma="책"),)

    payload = json.loads(encode_morphology_evidence("책", tokens))

    assert payload["candidates"] == []
    assert payload["candidates_available"] is False
    assert payload["tokens"][0]["lemma"] == "책"


def test_unreadable_or_foreign_evidence_decodes_to_nothing() -> None:
    assert decode_evidence(None) is None
    assert decode_evidence("not json") is None
    assert decode_evidence("[]") is None
    assert decode_evidence(json.dumps({"schema_version": EVIDENCE_SCHEMA_VERSION + 1})) is None


# --- The recognizer that actually read the pixels ---------------------------


def test_the_ocr_stage_names_the_backend_that_produced_it() -> None:
    """``auto`` resolves per machine, so the backend must travel with the
    result rather than be inferred later from configuration."""

    sink = _EvidenceSink()
    worker = LookupWorker(
        _SentenceOCR,
        _KiwiLikeMorphology,
        _Dictionary,
        trace_sink=sink,
        ocr_backend="vision",
    )
    worker(LookupRequest(1, _IMAGE, Point(46, 5)))
    worker.close()

    assert _stage(sink, "ocr")["ocr_backend"] == "vision"


def test_a_worker_told_no_backend_records_none_rather_than_guessing() -> None:
    sink = _EvidenceSink()
    worker = LookupWorker(_SentenceOCR, _KiwiLikeMorphology, _Dictionary, trace_sink=sink)
    worker(LookupRequest(1, _IMAGE, Point(46, 5)))
    worker.close()

    assert _stage(sink, "ocr")["ocr_backend"] is None
