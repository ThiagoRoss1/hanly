"""The grammar corpus harness and the word-selection classifier."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hanly import BoundingBox, OCRResult, Quad

from lab import korean_grammar, word_selection


def test_the_corpus_loads_with_every_target_inside_its_sentence() -> None:
    cases = korean_grammar.load_corpus()

    assert len(cases) >= 100
    assert len({case.id for case in cases}) == len(cases)
    for case in cases:
        assert case.target in case.text
        assert case.accept, case.id
        assert all(0 <= index < len(case.target) for index in case.accept)


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
    assert (direct.text, direct.cursor_index) == ("먹고", 0)
    assert (ocr.context_before, ocr.context_after) == ("지금", "있어요.")
    assert korean_grammar._variants("-아 있다") == {"-아 있다", "-어 있다"}


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
        context=SimpleNamespace(text=surface, selected_ocr=selected),
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
