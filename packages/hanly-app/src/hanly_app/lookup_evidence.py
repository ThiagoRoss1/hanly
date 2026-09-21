"""Encode private diagnostic structures as one JSON string per trace event.

The lookup worker runs in a spawned child process (see
:mod:`hanly_app.lookup_process`), and only JSON-safe primitives cross that pipe.
A structure like a resolver explanation is not a primitive, so it travels as one
encoded string on an ordinary trace event rather than as a new message kind.

Encoding happens only for a sink that asked for it. Recognized text is screen
content, so the field names here are the ones the benchmark's privacy layer
redacts before anything is written to disk; persistence is an explicit export.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from hanly import (
    BoundingBox,
    LexicalCandidate,
    MorphologyAnalysis,
    OCRResult,
    Point,
    Quad,
    TokenAnalysis,
)
from hanly.word_resolver import CandidateEvidence, ResolutionEvidence

#: Bumped when a consumer would read an existing field differently.
EVIDENCE_SCHEMA_VERSION = 1

#: Trace fields holding encoded private evidence. The benchmark strips these
#: before persisting, and pins them in memory only for a frozen lookup.
EVIDENCE_FIELDS = (
    "ocr_evidence",
    "resolution_evidence",
    "morphology_evidence",
    "dictionary_evidence",
)


def encode_resolution_evidence(evidence: ResolutionEvidence) -> str:
    """Describe one target resolution, including why it did not resolve."""

    resolution = evidence.resolution
    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": "resolution",
        "reason": evidence.reason,
        "selected_index": evidence.selected_index,
        "candidates": [_candidate(candidate) for candidate in evidence.candidates],
        "text_axis": _axis(evidence.text_axis),
        "horizontal_fraction": evidence.horizontal_fraction,
        "advance_weights": list(evidence.advance_weights),
        "cumulative_advances": list(evidence.cumulative_advances),
        "character_index": evidence.character_index,
        "word_span": list(evidence.word_span) if evidence.word_span else None,
        "word_bounds": _box(evidence.word_bounds),
        "resolution": None
        if resolution is None
        else {
            "text": resolution.text,
            "cursor_index": resolution.cursor_index,
            "region_start": resolution.region_start,
            "region_text": resolution.region.text,
            "region_confidence": resolution.region.confidence,
            "region_quad": _quad(resolution.region.quad),
        },
    }
    return _dump(payload)


def encode_morphology_evidence(text: str, analysis: object) -> str:
    """Describe one provider's analysis of a surface word, exactly as returned.

    The lexical unit the pointer selects is decided later, by the pipeline, and
    is reported on ``LookupResult.context.candidate``. Choosing one here would
    be a second guess at a decision this stage does not make.
    """

    tokens: Sequence[TokenAnalysis]
    candidates: Sequence[LexicalCandidate]
    if isinstance(analysis, MorphologyAnalysis):
        tokens, candidates = analysis.tokens, analysis.candidates
        candidates_available = True
    else:
        sequence = analysis if isinstance(analysis, Sequence) else ()
        tokens = [item for item in sequence if isinstance(item, TokenAnalysis)]
        candidates = ()
        candidates_available = False

    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": "morphology",
        "analyzed_text": text,
        "tokens": [
            {
                "token": token.token,
                "lemma": token.lemma,
                "part_of_speech": token.part_of_speech,
                "morphology": token.morphology,
                "start": token.start,
                "length": token.length,
            }
            for token in tokens
        ],
        "candidates": [_lexical(candidate) for candidate in candidates],
        # A provider written against the older sequence contract reports no
        # spans, so "no candidates" and "candidates unavailable" stay distinct.
        "candidates_available": candidates_available,
    }
    return _dump(payload)


def encode_dictionary_evidence(lemma: str, entry_count: int) -> str:
    """Describe the query a dictionary provider was actually given."""

    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": "dictionary",
        "query": lemma,
        "entry_count": entry_count,
        "found": entry_count > 0,
    }
    return _dump(payload)


def encode_ocr_evidence(results: Sequence[OCRResult]) -> str:
    """Describe normalized OCR output in the order the provider reported it."""

    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": "ocr",
        "regions": [
            {
                "index": index,
                "text": result.text,
                "confidence": result.confidence,
                "quad": _quad(result.quad),
            }
            for index, result in enumerate(results)
            if isinstance(result, OCRResult)
        ],
    }
    return _dump(payload)


def decode_evidence(encoded: object) -> dict[str, Any] | None:
    """Return a decoded payload, or ``None`` for anything unreadable.

    Evidence is best-effort developer detail: a truncated or absent field must
    leave the rest of a frozen lookup inspectable.
    """

    if not isinstance(encoded, str):
        return None
    try:
        payload = json.loads(encoded)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload if payload.get("schema_version") == EVIDENCE_SCHEMA_VERSION else None


def _candidate(candidate: CandidateEvidence) -> dict[str, Any]:
    return {
        "index": candidate.index,
        "text": candidate.text,
        "confidence": candidate.confidence,
        "quad": _quad(candidate.quad),
        "usable": candidate.usable,
        "unusable_reason": candidate.unusable_reason,
        "contains_target": candidate.contains_target,
        "vertical_margin": candidate.vertical_margin,
        "area": candidate.area,
    }


def _lexical(candidate: LexicalCandidate) -> dict[str, Any]:
    return {
        "lemma": candidate.lemma,
        "start": candidate.start,
        "end": candidate.end,
        "part_of_speech": candidate.part_of_speech,
        "token_indices": list(candidate.token_indices),
    }


def _quad(quad: Quad) -> list[dict[str, float]]:
    return [{"x": point.x, "y": point.y} for point in quad.points]


def _axis(axis: tuple[Point, Point] | None) -> list[dict[str, float]] | None:
    if axis is None:
        return None
    return [{"x": point.x, "y": point.y} for point in axis]


def _box(box: BoundingBox | None) -> dict[str, int] | None:
    if box is None:
        return None
    return {
        "left": box.left,
        "top": box.top,
        "right": box.right,
        "bottom": box.bottom,
    }


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "EVIDENCE_FIELDS",
    "EVIDENCE_SCHEMA_VERSION",
    "decode_evidence",
    "encode_dictionary_evidence",
    "encode_morphology_evidence",
    "encode_ocr_evidence",
    "encode_resolution_evidence",
]
