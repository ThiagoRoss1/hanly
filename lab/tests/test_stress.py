"""The stress campaign's plan, its rule, and the report rebuilt from a recording."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from lab.report.campaign import build_campaign
from lab.session.driver import _Observation, observe
from lab.session.stress import NEGATIVE, stress_plan, summarize_plan
from lab.session.stress_scoring import failing_stage, stress_verdict, summarize


def _dictionary(path: Path, count: int = 1200) -> Path:
    syllables = [chr(0xAC00 + 28 * index) for index in range(60)]
    forms = []
    for index in range(count):
        # Base-60 digits of the index, so every form is distinct.
        digits = [index % 60, (index // 60) % 60, index // 3600]
        length = 2 + index % 4
        forms.append("".join(syllables[(digits + [7, 11, 13])[step]] for step in range(length)))
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE entries (id INTEGER PRIMARY KEY, vocabulary_level TEXT,
                                  part_of_speech TEXT);
            CREATE TABLE lemmas (id INTEGER PRIMARY KEY, entry_id INTEGER, written_form TEXT,
                                 is_primary INTEGER);
            CREATE TABLE senses (id INTEGER PRIMARY KEY, entry_id INTEGER);
            CREATE TABLE translations (id INTEGER PRIMARY KEY, sense_id INTEGER, language TEXT);
            """
        )
        for index, form in enumerate(dict.fromkeys(forms), 1):
            connection.execute("INSERT INTO entries VALUES (?, '초급', '명사')", (index,))
            connection.execute("INSERT INTO lemmas VALUES (?, ?, ?, 1)", (index, index, form))
            connection.execute("INSERT INTO senses VALUES (?, ?)", (index, index))
            connection.execute("INSERT INTO translations VALUES (?, ?, 'en')", (index, index))
    return path


@pytest.fixture(scope="module")
def plan(tmp_path_factory: pytest.TempPathFactory) -> list[Any]:
    return stress_plan(_dictionary(tmp_path_factory.mktemp("db") / "krdict.sqlite3"), seed=11)


def test_a_plan_is_fixed_by_its_seed_and_answers_every_hover(
    plan: list[Any], tmp_path: Path
) -> None:
    again = stress_plan(_dictionary(tmp_path / "krdict.sqlite3"), seed=11)

    assert [item.target.id for item in plan] == [item.target.id for item in again]
    assert len({item.target.id for item in plan}) == len(plan)
    assert len(plan) >= 1000
    for item in plan:
        if item.family in NEGATIVE:
            assert item.target.refuse and item.target.headword is None
        elif item.family != "story":
            assert item.target.headword and not item.target.refuse


def test_a_plan_covers_every_family_it_reports(plan: list[Any]) -> None:
    counts = summarize_plan(plan)

    assert counts["word"] == 240 and counts["cursor"] == 90 and counts["repeat"] == 60
    for family in (
        "blank", "number", "punctuation", "latin", "mixed_latin", "icon", "image_none",
        "after_popup", "uia_latin", "image_text", "dense", "rapid", "leave_early",
        "changing", "covered", "uia_korean", "mixed_korean", "story",
    ):
        assert counts.get(family), family
    repeated = {item.repeat_of for item in plan if item.family == "repeat"}
    assert repeated <= {item.target.id for item in plan if item.family == "word"}


def _record(family: str, **fields: Any) -> dict[str, Any]:
    return {"family": family, "lookup_ids": [1], "hover_ids": [1], **fields}


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        ({"status": "EMPTY", "popup": "EMPTY"}, "quiet"),
        ({"status": None, "lookup_ids": [], "hover_ids": []}, "quiet"),
        ({"status": "SUCCESS", "popup": "SUCCESS"}, "false_answer"),
        ({"status": None, "timed_out": True}, "timed_out"),
        ({"status": "EMPTY", "foreign_popups": 1}, "stale_popup"),
        ({"error": "OCRError"}, "error"),
    ],
)
def test_a_negative_passes_only_when_nothing_is_presented(
    fields: dict[str, Any], verdict: str
) -> None:
    assert stress_verdict(_record("latin", refuse=True, **fields)) == verdict


@pytest.mark.parametrize(
    ("observed", "late", "verdict"),
    [
        ({"submitted": True, "answered_before_leaving": False}, 0, "withheld"),
        ({"submitted": True, "answered_before_leaving": False}, 1, "late_popup"),
        ({"submitted": True, "answered_before_leaving": True}, 0, "answered_before_leaving"),
        ({"submitted": False}, 0, "not_submitted"),
    ],
)
def test_an_answer_that_arrives_after_leaving_must_not_be_shown(
    observed: dict[str, Any], late: int, verdict: str
) -> None:
    record = _record("leave_early", observed=observed, late_popups=late)
    assert stress_verdict(record) == verdict


def test_a_failure_names_the_stage_it_points_at() -> None:
    facts = {"has_recognized_text": True}
    assert failing_stage(_record("latin", verdict="false_answer", facts=facts)) == "ocr_false_text"
    assert failing_stage(_record("word", verdict="no_text", gate="rejected")) == "presence_gate"
    assert failing_stage(_record("word", verdict="misread")) == "ocr_misread"
    assert failing_stage(_record("word", verdict="wrong_lemma")) == "morphology_dictionary"
    uia = _record("uia_korean", verdict="wrong_word", acquisition="accessibility")
    assert failing_stage(uia) == "uia"
    assert failing_stage(_record("word", verdict="correct")) is None


def test_after_leaving_new_hovers_bind_to_nobody_and_late_answers_are_counted() -> None:
    observation = _Observation()
    observe(observation, "hover_stable_fire", 1, {"hover_request_id": 7})
    observe(observation, "lookup_submit", 2, {"hover_request_id": 7, "lookup_request_id": 3})
    observation.departed_ns = 5
    observe(observation, "hover_stable_fire", 6, {"hover_request_id": 8})
    observe(observation, "popup_visible", 9, {"lookup_request_id": 3, "result_status": "SUCCESS"})
    observe(observation, "popup_visible", 10, {"lookup_request_id": 99, "result_status": "SUCCESS"})

    assert observation.hover_ids == {7}
    assert observation.late_popups == 1
    assert observation.foreign_popups == 1


def test_a_campaign_rebuilds_from_its_recording(tmp_path: Path) -> None:
    run = tmp_path / "20261002-120000-stress"
    run.mkdir()
    (run / "metadata.json").write_text(
        json.dumps({"commit": "abc", "dirty": False, "plan": {"word": 2, "latin": 1}}),
        encoding="utf-8",
    )
    rows = [
        {"event": "stress_result", "target": "w1", "family": "word", "status": "SUCCESS",
         "popup": "SUCCESS", "facts": {"answer_matches_expected": True}, "lookup_ids": [1],
         "hover_to_popup_ms": 120.0, "verdict": "correct"},
        {"event": "stress_result", "target": "w2", "family": "word", "status": "SUCCESS",
         "popup": "SUCCESS", "facts": {"has_selection": True, "has_recognized_text": True},
         "lookup_ids": [2], "hover_to_popup_ms": 130.0, "verdict": "misread"},
        {"event": "stress_result", "target": "l1", "family": "latin", "refuse": True,
         "status": "SUCCESS", "popup": "SUCCESS", "lookup_ids": [3],
         "facts": {"has_recognized_text": True}, "verdict": "false_answer"},
        {"event": "tour_finished"},
    ]
    (run / "events.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )

    model = build_campaign(run)

    assert model["summary"]["executed"] == 3 and model["planned_total"] == 3
    assert model["summary"]["false_positives"] == 1
    assert model["summary"]["missing_answers"] == 1
    assert model["ended"] == "finished"
    assert {(row["target"], row["stage"]) for row in model["failures"]} == {
        ("w2", "ocr_misread"),
        ("l1", "ocr_false_text"),
    }
    assert (run / "campaign.html").is_file() and (run / "campaign.md").is_file()


def test_summary_keeps_unscored_and_evidence_out_of_the_score() -> None:
    summary = summarize(
        [
            {"family": "word", "verdict": "correct"},
            {"family": "covered", "verdict": "obscured"},
            {"family": "changing", "verdict": "observed"},
        ]
    )
    assert (summary["scored"], summary["unscored"], summary["passed"]) == (1, 2, 1)
