"""Build local grammar fixtures without redistributing the licensed dictionary."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hanly import MorphologyAnalysis
from hanly.kiwi_provider import KiwiProvider

from .korean_grammar import load_corpus

_WORD = re.compile(r"[가-힣]+")
_FINALS = str.maketrans({"ㄴ": "ᆫ", "ㄹ": "ᆯ", "ㅁ": "ᆷ", "ㅂ": "ᆸ"})


@dataclass(frozen=True)
class GrammarTarget:
    id: str
    kind: str
    form: str
    text: str
    target: str
    start: int
    provenance: str
    expected_headwords: tuple[str, ...] = ()
    reference: str | None = None
    cursor_headwords: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GrammarInventory:
    targets: list[GrammarTarget] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)
    omissions: list[dict[str, Any]] = field(default_factory=list)

    def coverage(self) -> dict[str, Any]:
        planned = Counter(unit["kind"] for unit in self.units)
        covered = Counter(unit["kind"] for unit in self.units if unit["case_id"])
        return {
            "authored_cases": sum(t.provenance == "lab_authored" for t in self.targets),
            "dictionary_entries": dict(planned),
            "entries_with_examples": dict(covered),
            "unique_forms": len({(u["kind"], u["form"]) for u in self.units}),
            "omissions": len(self.omissions),
            "semantic_status": (
                "Dictionary examples establish surface targets, "
                "not independently reviewed lemma answers."
            ),
        }


def authored_targets() -> list[GrammarTarget]:
    targets = []
    for case in load_corpus():
        words = {word for choices in case.accept.values() for word in choices}
        form = (
            "-(으)ㄹ 거예요" if case.category == "future construction"
            else case.construction or case.category
        )
        targets.append(GrammarTarget(
            id=case.id, kind=case.category, form=form, text=case.text,
            target=case.target, start=case.text.index(case.target),
            provenance="lab_authored", expected_headwords=tuple(sorted(words)),
            cursor_headwords=dict(case.accept),
        ))
    return targets


def match_form(text: str, form: str) -> tuple[str, int] | None:
    """Locate an explicit attached surface, including contracted final jamo."""

    needle = unicodedata.normalize("NFD", form.strip("-").translate(_FINALS))
    if not needle:
        return None
    prefinal = form.endswith("-")
    for match in _WORD.finditer(text):
        surface = match.group()
        decomposed = unicodedata.normalize("NFD", surface)
        position = decomposed.find(needle) if prefinal else len(decomposed) - len(needle)
        if position > 0 and decomposed[position:position + len(needle)] == needle:
            return surface, match.start()
    return None


def dictionary_inventory(
    database: Path, *, analyze: Callable[[str], MorphologyAnalysis] | None = None,
) -> GrammarInventory:
    """Enumerate every particle/ending entry and retain one source example when locatable."""

    inventory = GrammarInventory(targets=authored_targets())
    analyze = KiwiProvider().analyze if analyze is None else analyze
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        units = connection.execute(
            "SELECT e.id, e.source_id, e.part_of_speech, l.written_form "
            "FROM entries e JOIN lemmas l ON l.entry_id=e.id "
            "WHERE l.is_primary=1 AND e.part_of_speech IN ('조사','어미') "
            "ORDER BY e.part_of_speech, l.written_form, e.id"
        ).fetchall()
        for entry, source_id, part, form in units:
            kind = "particle" if part == "조사" else "ending"
            reference = f"https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo={source_id}"
            unit: dict[str, Any] = {
                "entry_id": entry, "source_id": source_id, "kind": kind,
                "form": form, "reference": reference, "case_id": None,
            }
            inventory.units.append(unit)
            candidates = connection.execute(
                "SELECT DISTINCT x.text FROM examples x JOIN senses s ON s.id=x.sense_id "
                "WHERE s.entry_id=? ORDER BY LENGTH(x.text), x.text", (entry,),
            )
            for (text,) in candidates:
                found = _grammar_surface(text, form, kind, analyze(text))
                if found is None:
                    continue
                surface, start = found
                case_id = f"krdict-{entry}"
                unit["case_id"] = case_id
                inventory.targets.append(GrammarTarget(
                    id=case_id, kind=kind, form=form, text=text, target=surface,
                    start=start, provenance="local_licensed_krdict", reference=reference,
                ))
                break
            if unit["case_id"] is None:
                inventory.omissions.append({
                    "entry_id": entry, "kind": kind, "form": form,
                    "reason": "No attached example surface matched; manual curation required.",
                })
    return inventory


def _grammar_surface(
    text: str, form: str, kind: str, analysis: MorphologyAnalysis,
) -> tuple[str, int] | None:
    """Prefer an actual grammatical token over the same letters inside a noun.

    This is a fixture-location aid, not independent validation of Kiwi. The
    source sentence and dictionary entry remain available for human review.
    """

    normalized = unicodedata.normalize("NFD", form.strip("-").translate(_FINALS))
    variants = {normalized}
    if form.startswith("-여") or form.startswith("-였"):
        variants.add(unicodedata.normalize(
            "NFD", form.strip("-").replace("여", "어", 1).replace("였", "었", 1),
        ))
    prefix = "J" if kind == "particle" else "E"
    for token in analysis.tokens:
        if not (token.part_of_speech or "").startswith(prefix):
            continue
        if unicodedata.normalize("NFD", token.token.translate(_FINALS)) not in variants:
            continue
        if token.start is None:
            continue
        for word in _WORD.finditer(text):
            if word.start() <= token.start < word.end():
                return word.group(), word.start()
    return match_form(text, form)
