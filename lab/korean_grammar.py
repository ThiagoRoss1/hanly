"""Score the language stage against the reviewed Korean grammar corpus.

``python -m lab grammar`` runs Kiwi and KRDICT -- no OCR, no pixels -- on every
case of ``lab/fixtures/korean/grammar.json`` at every syllable of its target,
in the two forms acquisition hands over: the whitespace-delimited word OCR
resolves, and the selection the production direct-text coordinator yields. Expected
headwords and constructions are checked against the dictionary before
anything is scored, so a typo in the corpus cannot pass as a model error.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .identity import LAB_ROOT, REPO_ROOT

CORPUS = REPO_ROOT / "lab" / "fixtures" / "korean" / "grammar.json"
FORMS = ("ocr", "direct")


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    text: str
    target: str
    accept: dict[int, tuple[str, ...]]
    parts: tuple[str, ...] = ()
    construction: str | None = None
    auxiliary: bool = False
    note: str | None = None


@dataclass
class Outcome:
    case: str
    category: str
    form: str
    cursor: int
    status: str
    headword: str | None
    lemma: str | None
    correct: bool
    parts_missing: tuple[str, ...] = ()
    parts_required: bool = False
    construction: str | None = None
    construction_ok: bool | None = None
    auxiliary_ok: bool | None = None
    reasons: list[str] = field(default_factory=list)


def load_corpus(path: Path = CORPUS) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[Case] = []
    seen: set[str] = set()
    for item in raw["cases"]:
        if item["id"] in seen:
            raise ValueError(f"duplicate case id: {item['id']}")
        seen.add(item["id"])
        target = item["target"]
        if target not in item["text"]:
            raise ValueError(f"{item['id']}: target {target!r} is not in its sentence")
        per_cursor = item.get("cursor")
        if isinstance(per_cursor, Mapping):
            accept = {int(index): tuple(values) for index, values in per_cursor.items()}
        else:
            start = int(item.get("cursor_from", 0))
            accept = {
                index: tuple(item["accept"])
                for index in range(start, len(target))
                if _is_hangul(target[index])
            }
        expected_indices = {i for i, char in enumerate(target) if _is_hangul(char)}
        if set(accept) != expected_indices or any(not values for values in accept.values()):
            raise ValueError(f"{item['id']}: every Hangul syllable needs an expected headword")
        cases.append(Case(
            id=item["id"], category=item["category"], text=item["text"], target=target,
            accept=accept, parts=tuple(item.get("parts", ())),
            construction=item.get("construction"), auxiliary=bool(item.get("auxiliary")),
            note=item.get("note"),
        ))
    return cases


def verify_against_dictionary(cases: Sequence[Case], dictionary: Any) -> list[str]:
    """Every expected headword and construction must be a KRDICT entry."""

    problems: list[str] = []
    for case in cases:
        for headwords in case.accept.values():
            for headword in headwords:
                if not dictionary.lookup(headword):
                    problems.append(f"{case.id}: {headword!r} is not a KRDICT headword")
        if case.construction and not dictionary.lookup(case.construction):
            problems.append(f"{case.id}: construction {case.construction!r} is not in KRDICT")
    return sorted(set(problems))


def selection_for(case: Case, form: str, cursor: int) -> Any:
    """The selection acquisition would hand the language stage for this hover."""

    from hanly import TextSelection
    from hanly.language_pipeline import neighbouring_words

    offset = case.text.index(case.target)
    if form == "ocr":
        text, index = case.target, cursor
    else:
        return _direct_selection(case.text, offset + cursor)
    before, after = neighbouring_words(case.text, offset, offset + len(case.target))
    return TextSelection(
        text=text, cursor_index=index, source=form,
        context_before=before, context_after=after,
    )


def _direct_selection(text: str, cursor: int) -> Any:
    """Exercise production selection policy with authored text and synthetic bounds."""

    from hanly import BoundingBox, Point
    from hanly_app.acquisition.direct_text import DirectText, DirectTextCoordinator

    bounds = BoundingBox(left=0, top=0, right=100, bottom=20)
    point = Point(50, 10)

    class Reader:
        def read_at(self, point: Point, *, timeout_ms: int) -> DirectText:
            return DirectText(text=text, cursor_index=cursor, bounds=bounds)

        def refine_bounds(
            self, point: Point, start: int, end: int, *, line: str, timeout_ms: int
        ) -> BoundingBox:
            return bounds

    return DirectTextCoordinator(Reader()).acquire(point).selection


def evaluate(cases: Sequence[Case], pipeline: Any) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        for form in FORMS:
            for cursor, accepted in sorted(case.accept.items()):
                selection = selection_for(case, form, cursor)
                if selection is None:
                    continue
                outcomes.append(_score(case, form, cursor, accepted, pipeline.lookup(selection)))
    return outcomes


def _score(
    case: Case, form: str, cursor: int, accepted: tuple[str, ...], result: Any
) -> Outcome:
    context = result.context
    headword = result.entries[0].headword if result.entries else None
    components = tuple(getattr(context, "components", ()) or ()) if context else ()
    # A word found whole keeps its particles in the analysis the popup reads
    # out, not in components; either place names them to the reader.
    analyses = tuple(getattr(context, "analyses", ()) or ()) if context else ()
    named = {component.lemma for component in components} | {
        _surface(context.text, component) for component in components
        if context is not None and context.text
    } | {token.token for token in analyses} | {token.lemma for token in analyses}
    construction = getattr(context, "construction", None) if context else None
    construction_name = getattr(construction, "headword", None)
    reasons: list[str] = []
    correct = headword in accepted
    if not correct:
        reasons.append(f"answered {headword!r} ({result.status.value})")
    missing = tuple(part for part in case.parts if part not in named)
    if missing:
        reasons.append(f"parts not named: {', '.join(missing)}")
    construction_ok = None
    if case.construction is not None:
        construction_ok = construction_name in _variants(case.construction)
        if not construction_ok:
            reasons.append(f"construction {construction_name!r}, expected {case.construction!r}")
    auxiliary_ok = None
    if case.auxiliary and result.entries:
        auxiliary_ok = (result.entries[0].part_of_speech or "").startswith("보조")
        if not auxiliary_ok:
            reasons.append(f"first sense is {result.entries[0].part_of_speech!r}, not auxiliary")
    return Outcome(
        case=case.id, category=case.category, form=form, cursor=cursor,
        status=result.status.value, headword=headword,
        lemma=context.lemma if context else None, correct=correct,
        parts_missing=missing, parts_required=bool(case.parts), construction=construction_name,
        construction_ok=construction_ok, auxiliary_ok=auxiliary_ok, reasons=reasons,
    )


def summarize(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    by_form: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for outcome in outcomes:
        key = "correct" if outcome.correct else "wrong"
        by_form[outcome.form][key] += 1
        by_category[outcome.category][key] += 1
        for name, value in (
            ("parts_ok", not outcome.parts_missing if outcome.parts_required else None),
            ("construction_ok", outcome.construction_ok),
            ("auxiliary_ok", outcome.auxiliary_ok),
        ):
            if value is not None:
                by_form[outcome.form][f"{name}:{'yes' if value else 'no'}"] += 1
    return {
        "hovers": len(outcomes),
        "by_form": {form: dict(counts) for form, counts in by_form.items()},
        "by_category": {name: dict(counts) for name, counts in sorted(by_category.items())},
        "failures": [
            {"case": o.case, "form": o.form, "cursor": o.cursor, "reasons": o.reasons}
            for o in outcomes
            if o.reasons
        ],
    }


def write_report(summary: Mapping[str, Any], destination: Path) -> Path:
    lines = ["# Korean grammar coverage", "", f"Hovers scored: {summary['hovers']}", ""]
    lines += ["| form | correct headword | wrong | parts named | constructions | auxiliary sense |",
              "|---|---|---|---|---|---|"]
    for form, counts in summary["by_form"].items():
        lines.append(
            f"| {form} | {counts.get('correct', 0)} | {counts.get('wrong', 0)} "
            f"| {_ratio(counts, 'parts_ok')} | {_ratio(counts, 'construction_ok')} "
            f"| {_ratio(counts, 'auxiliary_ok')} |"
        )
    lines += ["", "| category | correct | wrong |", "|---|---|---|"]
    for name, counts in summary["by_category"].items():
        lines.append(f"| {name} | {counts.get('correct', 0)} | {counts.get('wrong', 0)} |")
    lines += ["", "## Failures", ""]
    lines += [
        f"- `{failure['case']}` {failure['form']} @{failure['cursor']}: "
        + "; ".join(failure["reasons"])
        for failure in summary["failures"]
    ] or ["- none"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def run(dictionary_path: Path, output: Path | None = None) -> tuple[dict[str, Any], Path]:
    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider
    from hanly.language_pipeline import LanguagePipeline

    from .metadata import build_metadata, source_identity, write_metadata

    metadata = build_metadata(
        repo_root=REPO_ROOT, kind="grammar",
        config={"scope": "language_stage_only", "ocr": "not_run", "capture": "not_run"},
        scenario={"corpus_sha256": _file_digest(CORPUS),
                  "dictionary_sha256": _file_digest(dictionary_path)},
    )

    dictionary = KRDICTProvider(dictionary_path)
    try:
        cases = load_corpus()
        problems = verify_against_dictionary(cases, dictionary)
        if problems:
            raise ValueError("corpus does not match the dictionary: " + "; ".join(problems))
        summary = summarize(evaluate(cases, LanguagePipeline(KiwiProvider(), dictionary)))
    finally:
        dictionary.close()
    metadata["lab_provenance"]["source_at_end"] = source_identity(REPO_ROOT)
    path = write_report(summary, output or LAB_ROOT / "grammar" / "summary.md")
    write_metadata(path.parent / "metadata.json", metadata)
    path.with_suffix(".json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary, path


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ratio(counts: Mapping[str, int], name: str) -> str:
    yes, no = counts.get(f"{name}:yes", 0), counts.get(f"{name}:no", 0)
    return "n/a" if yes + no == 0 else f"{yes}/{yes + no}"


def _variants(construction: str) -> set[str]:
    """``-아 있다`` and ``-어 있다`` name one construction in two vowel forms."""

    names = {construction}
    for left, right in (("-아", "-어"), ("-어", "-아")):
        if construction.startswith(left):
            names.add(right + construction[len(left):])
    return names


def _surface(text: str, component: Any) -> str:
    return text[component.start: component.end]


def _is_hangul(character: str) -> bool:
    return "가" <= character <= "힣"
