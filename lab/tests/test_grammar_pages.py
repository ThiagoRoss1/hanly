"""Fixture coverage and acquisition separation without a native window server."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from hanly import MorphologyAnalysis, TokenAnalysis

from lab import grammar_pages
from lab.grammar_inventory import (
    GrammarInventory,
    GrammarTarget,
    _grammar_surface,
    authored_targets,
    dictionary_inventory,
    match_form,
)
from lab.grammar_pages import CURSORS, FONTS, build_pages


@pytest.mark.parametrize(("text", "form", "expected"), [
    ("학교에서 공부해요", "에서", ("학교에서", 0)),
    ("곧 갈 거예요", "-ㄹ", ("갈", 2)),
    ("책을 읽었어요", "-었-", ("읽었어요", 3)),
    ("에서 봤어요", "에서", None),
    ("학교에서는 공부해요", "에서", None),
])
def test_form_matching_requires_an_explicit_attached_surface(
    text: str, form: str, expected: tuple[str, int] | None,
) -> None:
    assert match_form(text, form) == expected


def test_grammatical_token_location_does_not_pick_a_noun_with_the_same_final_jamo() -> None:
    analysis = MorphologyAnalysis(tokens=(
        TokenAnalysis("내일", "내일", part_of_speech="MAG", start=0, length=2),
        TokenAnalysis("ᆯ", "ᆯ", part_of_speech="ETM", start=3, length=1),
    ))
    assert _grammar_surface("내일 갈 거예요", "-ㄹ", "ending", analysis) == ("갈", 3)


def test_compound_fixture_preserves_different_answers_at_different_syllables() -> None:
    target = next(target for target in authored_targets() if target.id == "g106")
    assert target.cursor_headwords[0] == ("컴퓨터",)
    assert target.cursor_headwords[3] == ("공학",)


def test_inventory_reports_missing_examples_instead_of_claiming_complete_coverage(
    tmp_path: Path,
) -> None:
    database = tmp_path / "dictionary.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE entries(id INTEGER, source_id INTEGER, part_of_speech TEXT);
            CREATE TABLE lemmas(entry_id INTEGER, written_form TEXT, is_primary INTEGER);
            CREATE TABLE senses(id INTEGER, entry_id INTEGER);
            CREATE TABLE examples(sense_id INTEGER, text TEXT);
            INSERT INTO entries VALUES (1, 21, '조사'), (2, 22, '어미');
            INSERT INTO lemmas VALUES (1, '에서', 1), (2, '-구만', 1);
            INSERT INTO senses VALUES (10, 1);
            INSERT INTO examples VALUES (10, '학교에서 공부해요');
        """)

    inventory = dictionary_inventory(database, analyze=lambda _text: MorphologyAnalysis(tokens=(
        TokenAnalysis("에서", "에서", part_of_speech="JKB", start=2, length=2),
    )))
    assert inventory.coverage()["dictionary_entries"] == {"particle": 1, "ending": 1}
    assert inventory.coverage()["entries_with_examples"] == {"particle": 1}
    assert inventory.omissions[0]["entry_id"] == 2
    source_case = next(t for t in inventory.targets if t.id == "krdict-1")
    assert source_case.target == "학교에서"
    assert not source_case.expected_headwords


def test_paired_pages_keep_ocr_ground_truth_out_of_the_accessible_surface(tmp_path: Path) -> None:
    target = GrammarTarget("g-test", "particle", "에서", "학교에서 공부해요", "학교에서", 0,
                           "lab_authored", ("학교",))
    build_pages(tmp_path, GrammarInventory(targets=[target]), stress_cases=0)

    text = (tmp_path / "text.html").read_text("utf-8")
    ocr = (tmp_path / "ocr.html").read_text("utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert target.text in text
    assert target.text not in ocr and target.target not in ocr
    assert 'alt=""' in ocr and 'draggable="true"' in ocr
    assert {"zoom-in", "zoom-out", "text", "grab"}.issubset(CURSORS)
    assert manifest["cases"][0]["expected_surface"] == target.target
    assert manifest["cases"][0]["expected_target"]
    assert "untested" in manifest["status"]
    from lab.corpus import load_corpus

    corpus = load_corpus(tmp_path / "corpus.json")
    assert len(corpus.cases) == 1
    assert corpus.cases[0].expected_surface == target.target
    with pytest.raises(ValueError, match="empty"):
        build_pages(tmp_path, GrammarInventory(targets=[target]))


def test_missing_glyph_is_an_explicit_image_omission(tmp_path: Path) -> None:
    target = GrammarTarget("emoji", "mixed", "emoji", "😀학교", "학교", 1, "lab_authored")
    build_pages(tmp_path, GrammarInventory(targets=[target]), stress_cases=0)
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["cases"] == []
    assert manifest["render_omissions"][0]["case_id"] == "emoji"
    assert target.text in (tmp_path / "text.html").read_text("utf-8")


def test_ocr_token_truth_keeps_punctuation_without_changing_the_grammar_target(
    tmp_path: Path,
) -> None:
    target = GrammarTarget("punctuation", "past", "-었-", "밥을 먹었어요.", "먹었어요", 3,
                           "lab_authored", ("먹다",))
    build_pages(tmp_path, GrammarInventory(targets=[target]), stress_cases=0)
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["cases"][0]["expected_surface"] == "먹었어요."
    assert manifest["targets"][0]["target"] == "먹었어요"
    assert manifest["targets"][0]["expected_headwords"] == ["먹다"]


def test_vendored_faces_have_pinned_bytes_and_redistribution_licenses() -> None:
    manifest = json.loads((FONTS / "manifest.json").read_text("utf-8"))
    assert {face["kind"] for face in manifest["faces"]} == {
        "normal", "pixel", "display", "comic-handwriting",
    }
    for face in manifest["faces"]:
        assert hashlib.sha256((FONTS / face["file"]).read_bytes()).hexdigest() == face["sha256"]
        assert "SIL OPEN FONT LICENSE" in (FONTS / face["license_file"]).read_text("utf-8")


def test_prebuilt_inventory_can_render_without_the_optional_morphology_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(grammar_pages, "version", unavailable)
    target = GrammarTarget("portable", "noun", "학교", "학교", "학교", 0, "lab_authored")
    build_pages(tmp_path, GrammarInventory(targets=[target]), stress_cases=0)
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["versions"]["kiwipiepy"] == "unavailable"
