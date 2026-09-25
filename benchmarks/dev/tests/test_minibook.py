"""The mini book describes its own page, and its judge scores what it claims to."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from hanly import DictionaryEntry, LookupContext, LookupResult, LookupStatus

from benchmarks.dev.minibook import (
    MANIFEST,
    MinibookError,
    judge,
    load_minibook,
    render_html,
    render_rtf,
    summarize,
)


def test_the_page_has_enough_varied_targets() -> None:
    book = load_minibook()
    korean = [target for target in book.targets if not target.refuse]
    latin = [target for target in book.targets if target.refuse]

    assert len(korean) >= 100
    assert {target.topik for target in korean} == {1, 2, 3, 4, 5, 6}
    kinds = Counter(kind for target in korean for kind in target.kinds)
    for kind in ("noun", "verb", "adjective", "adverb", "particle", "compound",
                 "connective", "polite", "punctuation"):
        assert kinds[kind] > 0, kind
    assert any(kind.startswith("irregular") for kind in kinds)
    assert {target.style for target in korean} >= {"regular", "bold", "italic", "serif"}
    assert len(latin) >= 5


def test_a_target_that_does_not_match_its_line_is_refused(tmp_path: Path) -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["targets"][0]["start"] += 1
    broken = tmp_path / "minibook.json"
    broken.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(MinibookError, match="does not match"):
        load_minibook(broken)


def test_both_accessible_forms_carry_every_line_and_the_canvas_form_carries_none() -> None:
    book = load_minibook()
    page = render_html(book)
    canvas = render_html(book, canvas=True)
    rtf = render_rtf(book)

    assert all(f'id="line-{index}"' in page for index in range(len(book.lines)))
    assert "<span style=\"font-weight:700\">따뜻한</span>" in page
    assert "<p id=" not in canvas and "<canvas" in canvas
    assert rtf.startswith("{\\rtf1") and rtf.count("\\par") == len(book.lines)
    assert rtf.isascii()


def _result(text: str, lemma: str, headword: str) -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword=headword, definitions=("gloss",)),),
        context=LookupContext(text=text, lemma=lemma),
    )


def test_the_judge_names_the_first_stage_that_went_wrong() -> None:
    book = load_minibook()
    target = next(t for t in book.targets if t.surface == "추워서")

    right = judge(target, path="language", route="selection",
                  result=_result("추워서", "춥다", "춥다"))
    wrong_word = judge(target, path="ocr", route="capture",
                       result=_result("날씨가", "날씨", "날씨"))
    wrong_lemma = judge(target, path="language", route="selection",
                        result=_result("추워서", "추다", "추다"))
    refused = judge(target, path="direct", route="unsupported", result=None)

    assert right.stage is None and right.dictionary_ok
    assert wrong_word.stage == "target"
    assert wrong_lemma.stage == "morphology"
    assert refused.stage == "acquisition:unsupported"


def test_a_form_listed_verbatim_still_counts_its_dictionary_form() -> None:
    """KRDICT lists ``작은`` itself, so the probe key is the surface."""

    book = load_minibook()
    target = next(t for t in book.targets if t.surface == "작은")

    outcome = judge(target, path="language", route="selection",
                    result=_result("작은", "작은", "작다"))

    assert outcome.lemma_ok and outcome.dictionary_ok and outcome.stage is None


def test_any_korean_answer_on_latin_is_a_false_positive() -> None:
    book = load_minibook()
    latin = next(t for t in book.targets if t.surface == "CLI")

    refused = judge(latin, path="ocr", route="capture",
                    result=LookupResult(status=LookupStatus.UNUSABLE))
    popup = judge(latin, path="ocr", route="capture", result=_result("(니", "니", "니"))
    summary = summarize(book, [refused, popup])

    assert refused.stage is None
    assert popup.stage == "false_positive"
    assert summary["paths"]["ocr"]["latin_false_positives"] == 1
