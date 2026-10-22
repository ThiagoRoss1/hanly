"""Real-provider checks for learner-facing dictionary popup content."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from hanly.contracts import DictionaryEntry, DictionarySense

from lab import popup_content

DATABASE = Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3"
CASES = popup_content.load_corpus()
KNOWN_CONTEXTUAL_MISRESOLUTIONS = {"PC-003a"}
DIAGNOSTIC_ONLY_CASES = {case.id for case in CASES if case.diagnostic_only}


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
    assert len(CASES) == 18
    assert len({case.id for case in CASES}) == len(CASES)
    for case in CASES:
        assert case.target in case.text
        assert 0 <= case.cursor < len(case.target)
        assert popup_content.selection_for(case).text == case.target


@pytest.mark.parametrize(
    "case",
    [
        case for case in CASES
        if case.id not in KNOWN_CONTEXTUAL_MISRESOLUTIONS | DIAGNOSTIC_ONLY_CASES
    ],
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


def test_diagnostic_cases_record_actual_morphology_and_dictionary_probes(
    popup_rows: dict[str, dict[str, Any]],
) -> None:
    for case in CASES:
        if not case.diagnostic_only:
            continue

        row = popup_rows[case.id]
        assert row["expected_entry_available"] is True, case.id
        assert isinstance(row["expected_entry_probe"]["queried"], bool), case.id
        assert isinstance(row["expected_entry_probe"]["matching_entry_returned"], bool), case.id
        assert isinstance(row["morphology_calls"], list) and row["morphology_calls"], case.id
        assert all(
            isinstance(call["input"], str)
            and isinstance(call["tokens"], list)
            and isinstance(call["candidates"], list)
            for call in row["morphology_calls"]
        ), case.id
        assert isinstance(row["dictionary_probes"], list), case.id
        assert all(
            isinstance(probe["query"], str)
            and isinstance(probe["entries"], list)
            and all(
                set(entry) == {
                        "headword", "part_of_speech", "hanja", "vocabulary_level",
                        "entry_id", "first_sense_sha256",
                }
                for entry in probe["entries"]
            )
            for probe in row["dictionary_probes"]
        ), case.id
        assert "selected_candidate" in row, case.id
        assert row["expected_entry_present_but_not_selected"] == bool(
            row["expected_entry_available"] and not row["entry_matches_expected"]
        ), case.id

    assert popup_rows["PC-203"]["selection"]["text"] == "나는"
    assert popup_rows["PC-204"]["selection"]["text"] == "나는"
    assert popup_rows["PC-201"]["headword"] == "가지"
    assert popup_rows["PC-201"]["part_of_speech"] == "명사"
    assert popup_rows["PC-202"]["headword"] == "가다"
    assert popup_rows["PC-202"]["part_of_speech"] == "동사"
    assert popup_rows["PC-003a"]["expected_entry_available"] is True
    assert popup_rows["PC-003a"]["expected_entry_probe"] == {
        "queried": True,
        "matching_entry_returned": True,
        "query": "먹지",
    }
    assert popup_rows["PC-003a"]["expected_entry_present_but_not_selected"] is True
    assert popup_rows["PC-204"]["expected_entry_available"] is True
    assert popup_rows["PC-204"]["expected_entry_present_but_not_selected"] is True
    assert popup_rows["PC-201"]["expected_entry_present_but_not_selected"] is True
    assert popup_rows["PC-201"]["expected_entry_probe"]["matching_entry_returned"] is True


def test_entry_identity_distinguishes_same_headword_and_pos_by_sense() -> None:
    branch = DictionaryEntry(
        headword="가지",
        part_of_speech="명사",
        senses=(DictionarySense(
            definition="A small twig.", gloss="branch", sense_id="branch"
        ),),
        entry_id="branch-entry",
    )
    eggplant = DictionaryEntry(
        headword="가지",
        part_of_speech="명사",
        senses=(DictionarySense(
            definition="A long purple fruit.", gloss="eggplant", sense_id="eggplant"
        ),),
        entry_id="eggplant-entry",
    )
    probe = {
        "headword": eggplant.headword,
        "part_of_speech": eggplant.part_of_speech,
        "hanja": eggplant.hanja,
        "vocabulary_level": eggplant.vocabulary_level,
        "entry_id": eggplant.entry_id,
        "first_sense_sha256": popup_content._digest(eggplant.senses[0].definition),
    }

    assert not popup_content._same_entry_identity(eggplant, branch)
    assert not popup_content._same_entry_identity(None, branch)
    assert not popup_content._probe_entry_matches(probe, branch)
    assert popup_content._expected_entry_unselected(eggplant, branch)
    assert popup_content._expected_entry_unselected(None, branch)


def test_expected_content_is_source_pinned_to_the_installed_krdict_build() -> None:
    with sqlite3.connect(_database()) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM resource_metadata"))

    assert metadata["source"] == "krdict"
    assert metadata["resource_version"] == "20260819-v1"
    assert popup_content.CORPUS.exists()
