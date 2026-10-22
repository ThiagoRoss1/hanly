"""Scoring and report privacy for the offline popup-content campaign."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from lab import popup_content


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _case() -> popup_content.Case:
    return replace(
        popup_content.load_corpus()[0],
        id="PC-TEST",
        text="형태",
        target="형태",
        lemma="형태",
        headword="형태",
        part_of_speech="명사",
        hanja=None,
        vocabulary_level="초급",
        gloss_sha256=_digest("fixture gloss"),
        definition_sha256=_digest("fixture definition"),
        analysis=None,
        construction_headword=None,
        construction_definition_sha256=None,
        additional_construction_definition_sha256=None,
        required_sense_definition_sha256=None,
    )


def _row(case: popup_content.Case, *, actual_headword: str) -> dict[str, Any]:
    return {
        "id": case.id,
        "status": "SUCCESS",
        "surface": case.target,
        "source": "krdict",
        "expected_entry_available": True,
        "expected_entry": {
            "headword": case.headword,
            "part_of_speech": case.part_of_speech,
            "hanja": case.hanja,
            "vocabulary_level": case.vocabulary_level,
            "gloss": "fixture gloss",
            "definition": "fixture definition",
        },
        "lemma": actual_headword,
        "headword": actual_headword,
        "part_of_speech": "명사",
        "hanja": None,
        "vocabulary_level": "초급",
        "gloss": "fixture gloss",
        "definition": "fixture definition",
        "analysis": [],
        "construction": None,
    }


def test_source_gold_pass_does_not_hide_a_wrong_popup_entry() -> None:
    case = _case()
    score = popup_content.score_rows([_row(case, actual_headword="다른말")], [case])

    assert score["score"] == "0/1"
    assert score["status"] == "failed"
    record = score["cases"][0]
    assert record["outcome"] == "failed"
    source_check = next(
        check for check in record["checks"] if check["name"] == "source_entry_available"
    )
    assert source_check["passed"] is True
    assert "popup_headword" in record["failure_reasons"]
    assert "fixture definition" not in json.dumps(score, ensure_ascii=False)


def test_compact_report_states_scope_and_keeps_definitions_in_full_results_only(
    tmp_path: Path,
) -> None:
    case = _case()
    row = _row(case, actual_headword="다른말")
    score = popup_content.score_rows([row], [case])
    metadata = {
        "run_id": "run-1",
        "timestamp": "2026-10-22T01:00:00Z",
        "config": {"dictionary_resource_version": "local-build"},
        "scenario": {"corpus_sha256": "a" * 64},
        "lab_provenance": {
            "source": {"commit": "abc123", "state": "dirty"},
            "platform": {"system": "test", "machine": "test-host"},
        },
    }

    popup_content._write_campaign_artifacts(tmp_path, metadata, [row], score)
    rendered = (tmp_path / "summary.md").read_text(encoding="utf-8")
    compact_json = (tmp_path / "summary.json").read_text(encoding="utf-8")
    full_results = (tmp_path / "results.json").read_text(encoding="utf-8")

    assert "language pipeline through the Qt-independent popup presentation model" in rendered
    assert "OCR, capture, native UI and desktop process launch: not run" in rendered
    assert "abc123" in rendered and "dirty at start" in rendered
    assert f"Corpus SHA-256: `{'a' * 64}`" in rendered
    assert "0/1" in rendered and "failed" in rendered
    assert "fixture definition" not in rendered
    assert "fixture definition" not in compact_json
    assert "fixture definition" in full_results
