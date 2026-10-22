"""Real-provider checks for learner-facing dictionary popup content."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from lab import popup_content

DATABASE = Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3"
CASES = popup_content.load_corpus()
KNOWN_CONTEXTUAL_MISRESOLUTIONS = {"PC-003a"}


def _database() -> Path:
    if DATABASE.is_file():
        return DATABASE
    if os.environ.get("HANLY_REQUIRE_REAL_KRDICT") == "1":
        pytest.fail(f"required production KRDICT database is missing: {DATABASE}")
    pytest.skip("production KRDICT database is a local generated artifact")


@pytest.fixture(scope="module")
def popup_rows() -> dict[str, dict[str, Any]]:
    pytest.importorskip("kiwipiepy")
    rows = popup_content.run(_database())
    return {str(row["id"]): row for row in rows}


def _assert_source_gold(row: dict[str, Any], case: popup_content.Case) -> None:
    assert row["status"] == "SUCCESS", case.id
    assert row["surface"] == case.target, case.id
    assert row["source"] == "krdict", case.id
    assert row["expected_entry_available"] is True, case.id
    gold = row["expected_entry"]
    assert isinstance(gold, dict), case.id
    assert gold["headword"] == case.headword, case.id
    assert gold["part_of_speech"] == case.part_of_speech, case.id
    assert gold["hanja"] == case.hanja, case.id
    assert gold["vocabulary_level"] == case.vocabulary_level, case.id
    assert hashlib.sha256(str(gold["gloss"]).encode("utf-8")).hexdigest() == (
        case.gloss_sha256
    ), case.id
    assert hashlib.sha256(str(gold["definition"]).encode("utf-8")).hexdigest() == (
        case.definition_sha256
    ), case.id

    if case.required_sense_definition_sha256 is not None:
        senses = row["senses"]
        assert isinstance(senses, list), case.id
        assert any(
            hashlib.sha256(str(sense["definition"]).encode("utf-8")).hexdigest()
            == case.required_sense_definition_sha256
            for sense in senses
        ), case.id


def _assert_popup_content(row: dict[str, Any], case: popup_content.Case) -> None:
    assert row["lemma"] == case.lemma, case.id
    assert row["headword"] == case.headword, case.id
    assert row["part_of_speech"] == case.part_of_speech, case.id
    assert row["hanja"] == case.hanja, case.id
    assert row["vocabulary_level"] == case.vocabulary_level, case.id
    assert hashlib.sha256(str(row["gloss"]).encode("utf-8")).hexdigest() == (
        case.gloss_sha256
    ), case.id
    assert hashlib.sha256(str(row["definition"]).encode("utf-8")).hexdigest() == (
        case.definition_sha256
    ), case.id

    if case.analysis is not None:
        assert [tuple(item) for item in row["analysis"]] == list(case.analysis), case.id

    construction = row["construction"]
    if case.construction_headword is None:
        assert construction is None, case.id
        return

    assert isinstance(construction, dict), case.id
    assert construction["headword"] == case.construction_headword, case.id
    assert hashlib.sha256(str(construction["definition"]).encode("utf-8")).hexdigest() == (
        case.construction_definition_sha256
    ), case.id
    if case.additional_construction_definition_sha256 is not None:
        senses = construction["senses"]
        assert isinstance(senses, list), case.id
        assert any(
            hashlib.sha256(str(sense["definition"]).encode("utf-8")).hexdigest()
            == case.additional_construction_definition_sha256
            for sense in senses
        ), case.id


def test_popup_content_corpus_is_unique_and_targets_its_authored_sentence() -> None:
    assert len(CASES) == 12
    assert len({case.id for case in CASES}) == len(CASES)
    for case in CASES:
        assert case.target in case.text
        assert 0 <= case.cursor < len(case.target)
        assert popup_content.selection_for(case).text == case.target


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case.id not in KNOWN_CONTEXTUAL_MISRESOLUTIONS],
    ids=lambda case: case.id,
)
def test_real_popup_matches_source_gold_for_adjudicated_cases(
    popup_rows: dict[str, dict[str, Any]], case: popup_content.Case
) -> None:
    row = popup_rows[case.id]
    _assert_source_gold(row, case)
    assert row["entry_matches_expected"] is True, case.id
    _assert_popup_content(row, case)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known clear-context misresolution: PC-003a ‘먹지를 깔고 써요’ should resolve "
        "to KRDICT noun 먹지 (carbon paper), POS 명사; current lookup selects 먹다/동사. "
        "Remove this marker when the resolver returns the source-supported noun."
    ),
)
def test_carbon_paper_context_resolves_to_noun_entry(
    popup_rows: dict[str, dict[str, Any]],
) -> None:
    case = next(case for case in CASES if case.id == "PC-003a")
    row = popup_rows[case.id]
    _assert_source_gold(row, case)
    assert row["entry_matches_expected"] is True
    assert (row["headword"], row["part_of_speech"]) == ("먹지", "명사")


def test_expected_content_is_source_pinned_to_the_installed_krdict_build() -> None:
    with sqlite3.connect(_database()) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM resource_metadata"))

    assert metadata["source"] == "krdict"
    assert metadata["resource_version"] == "20260819-v1"
    assert popup_content.CORPUS.exists()
