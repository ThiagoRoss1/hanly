"""The grammar corpus harness and the word-selection classifier."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hanly import BoundingBox, LookupStatus, OCRResult, Quad

from lab import korean_grammar, word_selection


def test_the_corpus_loads_with_every_target_inside_its_sentence() -> None:
    cases = korean_grammar.load_corpus()

    assert len(cases) >= 100
    assert len({case.id for case in cases}) == len(cases)
    for case in cases:
        assert case.target in case.text
        assert case.accept, case.id
        assert all(0 <= index < len(case.target) for index in case.accept)


@pytest.mark.parametrize("duplicate", [False, True])
def test_incomplete_or_duplicate_corpus_cases_are_rejected(tmp_path: Path, duplicate: bool) -> None:
    import json

    cursor = {"0": ["학교"], "1": ["학교"]}
    if duplicate:
        cursor["2"] = ["학교"]
    item = {"id": "x", "category": "test", "text": "학교는", "target": "학교는",
            "cursor": cursor}
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"cases": [item, item] if duplicate else [item]}), "utf-8")

    with pytest.raises(ValueError, match="duplicate|every Hangul"):
        korean_grammar.load_corpus(path)


def test_a_headword_the_dictionary_lacks_is_reported_not_scored() -> None:
    cases = [korean_grammar.Case(
        id="x1", category="test", text="책을 읽어요.", target="책을",
        accept={0: ("책",), 1: ("책",)}, construction="-고 있다",
    )]

    class Empty:
        def lookup(self, lemma: str) -> tuple[()]:
            return ()

    problems = korean_grammar.verify_against_dictionary(cases, Empty())

    assert problems == [
        "x1: '책' is not a KRDICT headword",
        "x1: construction '-고 있다' is not in KRDICT",
    ]


def test_both_acquisition_forms_hand_over_the_right_word() -> None:
    case = korean_grammar.Case(
        id="x2", category="test", text="지금 (먹고) 있어요.", target="(먹고)",
        accept={1: ("먹다",)},
    )

    ocr = korean_grammar.selection_for(case, "ocr", 1)
    direct = korean_grammar.selection_for(case, "direct", 1)

    assert (ocr.text, ocr.cursor_index) == ("(먹고)", 1)
    assert (direct.text, direct.cursor_index) == ("(먹고)", 1)
    assert (ocr.context_before, ocr.context_after) == ("지금", "있어요.")
    assert korean_grammar._variants("-아 있다") == {"-아 있다", "-어 있다"}


def test_attached_grammar_and_bounded_context_agree_across_acquisition_forms() -> None:
    case = korean_grammar.Case(
        id="quoted", category="punctuation", text="지금 '사랑'이라는 말 하나",
        target="'사랑'이라는", accept={4: ("사랑",)},
    )

    ocr = korean_grammar.selection_for(case, "ocr", 4)
    direct = korean_grammar.selection_for(case, "direct", 4)

    assert (ocr.text, ocr.cursor_index, ocr.context_before, ocr.context_after) == (
        "'사랑'이라는", 4, "지금", "말 하나",
    )
    assert (direct.text, direct.cursor_index, direct.context_before, direct.context_after) == (
        ocr.text, ocr.cursor_index, ocr.context_before, ocr.context_after,
    )


def test_a_case_without_required_parts_does_not_count_as_a_parts_pass() -> None:
    outcome = korean_grammar.Outcome(
        case="x", category="test", form="ocr", cursor=0,
        status="SUCCESS", headword="학교", lemma="학교", correct=True,
    )

    counts = korean_grammar.summarize([outcome])["by_form"]["ocr"]

    assert "parts_ok:yes" not in counts


def _hover(
    word: str = "학교에서",
    box: tuple[float, float, float, float] = (100, 0, 160, 20),
    line: str = "학교에서 공부해요",
) -> word_selection.Hover:
    return word_selection.Hover(
        page="p", line=line, word=word, word_index=0, cursor="middle", size=20,
        theme="light", position="normal", point=(130, 10), word_box=box,
        neighbours=tuple(line.split()), accept=("학교",),
    )


def _result(surface: str | None, line: str, headword: str | None = "학교") -> Any:
    quad = Quad.from_bounding_box(BoundingBox(10, 0, 150, 20))
    selected = OCRResult(text=line, confidence=0.9, quad=quad)
    return SimpleNamespace(
        context=SimpleNamespace(text=surface, selected_ocr=selected, word_region=None),
        entries=(SimpleNamespace(headword=headword),) if headword else (),
    )


def test_misses_are_classified_against_ground_truth() -> None:
    inside = (0, 0, 200, 100)

    line = "학교에서 공부해요"
    assert word_selection.classify(_hover(), inside, _result("학교에서", line))[0] == "correct"
    assert word_selection.classify(
        _hover(), inside, _result("학교에서", "학교에서 공부해요", "학")
    )[0] == "lexical"
    assert word_selection.classify(
        _hover(), (120, 0, 320, 100), _result("에서", "에서 공부해요")
    )[0] == "clipped_by_roi"
    spaced = _result("학교", "학교 에서 공부해요")
    assert word_selection.classify(_hover(), inside, spaced)[0] == "ocr_false_space"
    assert word_selection.classify(_hover(), inside, _result("공부해요", line))[0] == (
        "neighbor_word"
    )
    assert word_selection.classify(_hover(), inside, _result(None, ""))[0] == "no_result"
    # A misread of the hovered line is a misread, not another line.
    misread = _result("학교에셔", "학교에셔 공부해요")
    assert word_selection.classify(_hover(), inside, misread)[0] == "ocr_misread"
    other_line = SimpleNamespace(
        context=SimpleNamespace(
            text="사과를", word_region=None,
            selected_ocr=OCRResult(text="사과를 먹어요", confidence=0.9,
                                   quad=Quad.from_bounding_box(BoundingBox(10, 40, 150, 60))),
        ),
        entries=(),
    )
    assert word_selection.classify(_hover(), inside, other_line)[0] == "wrong_line"
    # Narrowed to the Korean under the pointer: 3명이 answered as 명이.
    counted = word_selection.Hover(**{**_hover("3명이", line="3명이 왔어요").__dict__,
                                      "char_index": 1, "accept": ()})
    assert word_selection.classify(counted, inside, _result("명이", "3명이 왔어요"))[0] == (
        "correct"
    )


def test_the_edge_retry_fires_only_when_the_word_reaches_the_crop_side() -> None:
    def resolved(left: int, right: int) -> Any:
        return SimpleNamespace(context=SimpleNamespace(word_region=BoundingBox(left, 0, right, 20)))

    assert word_selection._word_touches_edge(resolved(0, 60), 200)
    assert word_selection._word_touches_edge(resolved(120, 199), 200)
    assert not word_selection._word_touches_edge(resolved(40, 120), 200)
    assert not word_selection._word_touches_edge(SimpleNamespace(context=None), 200)


def test_matching_text_on_another_line_is_not_a_correct_hover() -> None:
    result = _result("학교에서", "학교에서 공부해요")
    result.context.selected_ocr = OCRResult(
        text="학교에서 공부해요", confidence=0.9,
        quad=Quad.from_bounding_box(BoundingBox(10, 40, 150, 60)),
    )

    assert word_selection.classify(_hover(), (0, 0, 200, 100), result)[0] == "wrong_line"


@pytest.mark.parametrize("first_calls", [0, 1])
def test_retry_calls_do_not_turn_a_cached_first_pass_into_fresh_work(first_calls: int) -> None:
    from PIL import Image

    counter = SimpleNamespace(calls=0)
    requests: list[object] = []

    def worker(request: object) -> Any:
        counter.calls += first_calls if not requests else 1
        requests.append(request)
        result = _result("학교에서", "학교에서 공부해요")
        result.status = LookupStatus.SUCCESS
        result.context.word_region = BoundingBox(0, 0, 60, 20)
        return result

    observation = word_selection._observe(
        worker, counter, 1, _hover(), Image.new("RGB", word_selection.PAGE_SIZE), True,
    )
    summary = word_selection.summarize([observation])

    assert observation.ocr_calls == first_calls
    assert observation.retry_ocr_calls == 1
    assert summary["ocr_calls"] == first_calls
    assert summary["fresh_latency_ms"]["n"] == first_calls
    assert summary["edge_retry"]["extra_ocr_calls"] == 1
