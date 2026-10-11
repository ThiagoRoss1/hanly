"""What a tour hovers: lab-authored Korean with a known answer for every target.

Two sources, both free of anyone's screen content:

- ``story``: the minibook, prose with hand-set dictionary forms, conjugations,
  particles and Latin words that must be refused.
- ``words``: KRDICT headwords sampled with a fixed seed, each its own answer.
  Scales to thousands of hovers. Only headwords with an English translation are
  eligible: the dictionary provider answers in English, so an entry without
  one (often a cross-reference such as 애기 → 아기) has no answer to expect.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..minibook import load_minibook


@dataclass(frozen=True)
class TourTarget:
    """One hover: where the pointer rests and what the popup should say."""

    id: str
    source: str
    #: The whole line the target sits in, as painted.
    line: str
    start: int
    surface: str
    #: Offset into ``surface`` of the character the pointer rests on.
    cursor: int
    lemma: str | None
    headword: str | None
    refuse: bool = False
    kinds: tuple[str, ...] = ()
    level: str | None = None


def story_targets() -> list[TourTarget]:
    book = load_minibook()
    return [
        TourTarget(
            id=target.id,
            source="story",
            line=book.lines[target.line],
            start=target.start,
            surface=target.surface,
            cursor=target.cursor,
            lemma=target.lemma,
            headword=target.headword,
            refuse=target.refuse,
            kinds=target.kinds,
            level=None if target.topik is None else f"topik{target.topik}",
        )
        for target in book.targets
    ]


def word_targets(database: Path, count: int, *, seed: int = 7) -> list[TourTarget]:
    """Sample distinct, plain-Hangul headwords of two to five syllables.

    The shuffle runs over the same pool as before eligibility existed, so a seed
    keeps choosing the same words; an ineligible one is skipped, not replaced
    in place.
    """

    if count <= 0:
        return []
    uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT lemmas.written_form, entries.vocabulary_level,
                   entries.part_of_speech
            FROM lemmas JOIN entries ON entries.id = lemmas.entry_id
            WHERE lemmas.is_primary = 1
              AND length(lemmas.written_form) BETWEEN 2 AND 5
            ORDER BY lemmas.written_form
            """
        ).fetchall()
        answerable = {
            form
            for (form,) in connection.execute(
                """
                SELECT DISTINCT lemmas.written_form
                FROM lemmas
                JOIN senses ON senses.entry_id = lemmas.entry_id
                JOIN translations ON translations.sense_id = senses.id
                WHERE translations.language = 'en'
                """
            )
        }
    usable = [row for row in rows if all("가" <= ch <= "힣" for ch in row[0])]
    # Prefer the vocabulary a learner actually meets, then fill from the rest.
    common = [row for row in usable if row[1] in {"초급", "중급"}]
    rest = [row for row in usable if row[1] not in {"초급", "중급"}]
    generator = random.Random(seed)
    generator.shuffle(common)
    generator.shuffle(rest)
    seen: set[str] = set()
    targets: list[TourTarget] = []
    for form, level, part in common + rest:
        if len(targets) == count:
            break
        if form in seen or form not in answerable:
            continue
        seen.add(form)
        targets.append(
            TourTarget(
                id=f"w{len(targets) + 1:05d}",
                source="words",
                line=form,
                start=0,
                surface=form,
                cursor=len(form) // 2,
                lemma=form,
                headword=form,
                kinds=(part,) if part else (),
                level=level or None,
            )
        )
    return targets


__all__ = ["TourTarget", "story_targets", "word_targets"]
