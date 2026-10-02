"""A text-acquisition stress campaign: a fixed, seeded plan with an answer for every hover.

Every expectation is set here, before anything is hovered, from lab-authored
text: KRDICT headwords sampled with a seed (each its own answer), the minibook's
hand-set forms, and negatives whose only correct outcome is no answer. Nothing
here reads a screen, and nothing is adjusted after seeing what the app said.

A plan is a list of :class:`StressItem`. Where each lands on screen is the
page's business; how the pointer approaches it is the driver's.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from .corpus import TourTarget, story_targets, word_targets

#: Families whose only correct outcome is that no answer is presented.
NEGATIVE = frozenset(
    {
        "blank",
        "number",
        "punctuation",
        "latin",
        "mixed_latin",
        "icon",
        "image_none",
        "after_popup",
        "uia_latin",
    }
)
#: Families scored on presentation rather than on the answer's form.
BEHAVIORAL = frozenset({"leave_early"})
#: Families recorded as evidence, never folded into either side of a score.
INFORMATIONAL = frozenset({"changing", "covered"})

#: Faces a campaign rotates through, where installed: both platforms' Korean
#: sans and serif families, so one plan exercises what each machine offers.
FACES = (
    "Malgun Gothic",
    "Batang",
    "Gulim",
    "Dotum",
    "Gungsuh",
    "Noto Sans KR",
    "Apple SD Gothic Neo",
    "AppleMyungjo",
    "Nanum Gothic",
    "NanumMyeongjo",
)
SIZES = (14, 18, 24, 32, 44)
THEMES = ("light", "dark", "sepia", "gray")
RASTERS = ("noise", "blur", "jpeg", "gradient")

_NUMBERS = (
    "2026", "10:42", "3.14159", "1,250,000", "No. 7", "24/7", "+82 2", "07-15", "99%",
    "1st", "4K", "v2.0.1", "100", "0", "12:00", "2026-10-02", "x2", "#5", "60fps", "3/4",
    "IV", "500ml", "1.5x", "-40", "8:30",
)
_PUNCTUATION = (
    "…", "?!", "—", "※", "( )", "《》", "「」", "·", "~", "!!", "...", "→", "★", "♥",
    "§", "¶", "&", "@", "#", "%",
)
_LATIN = (
    "Dictionary", "update", "Hello", "settings", "Download", "OK", "Cancel", "Menu",
    "Search", "profile", "Event", "Gallery", "Check", "online", "Shop", "News", "Play",
    "Help", "Login", "Home", "Open", "Close", "Save", "Next", "Back",
)
_ICONS = (
    "circle", "star", "arrow", "gear", "heart", "bell", "home", "search", "check",
    "cross", "bars", "dots", "triangle", "square", "blob",
)
#: Latin words shaped like a UI label beside a Korean one: "Model X-2 사전 3.5GHz".
_MIXED_PREFIX = ("Model X-2", "Ver 3.1", "Hanly", "NEW", "Q&A", "Event", "Top 10", "PC")
_MIXED_SUFFIX = ("3.5GHz", "(beta)", "2026", "OK", "x2", "Pro", "Lite", "+")


@dataclass(frozen=True)
class StressItem:
    """One planned hover: what it should say, and how it is put on screen."""

    target: TourTarget
    family: str
    behavior: str = "dwell"
    size: int = 22
    theme: str = "light"
    #: Index into the installed faces; resolved by the page on this machine.
    face_index: int = 0
    raster: str | None = None
    graphic: str | None = None
    #: For ``changing``: what replaces the word under a pointer that stays put.
    replacement: str | None = None
    #: For repeats: the item this one hovers again.
    repeat_of: str | None = None

    @property
    def negative(self) -> bool:
        return self.family in NEGATIVE


def stress_plan(database: Path, *, seed: int = 11) -> list[StressItem]:
    """The whole campaign, in hover order, for one seed and one dictionary."""

    generator = random.Random(seed)
    pool = word_targets(database, 900, seed=seed)
    words = pool[:240]
    multi = [target for target in pool[240:] if len(target.surface) >= 3][:167]
    used = {target.id for target in multi}
    spare = [target for target in pool[240:] if target.id not in used]

    items: list[StressItem] = []
    items += _words(words)
    items += _story()
    items += _cursor_positions(multi[:30])
    items += _dense(multi[30:62])
    items += _mixed(multi[62:87])
    items += _negatives(generator)
    items += _rasters(multi[87:127], generator)
    items += _behaviors(spare, words, generator)
    items += _uia(multi[127:167])
    return items


def summarize_plan(items: list[StressItem]) -> dict[str, int]:
    """Planned hovers per family, which the report states beside what ran."""

    return dict(sorted(Counter(item.family for item in items).items()))


# -- positives ----------------------------------------------------------------------


def _words(words: list[TourTarget]) -> list[StressItem]:
    return [
        StressItem(
            target,
            "word",
            size=SIZES[index % len(SIZES)],
            theme=THEMES[(index // len(SIZES)) % len(THEMES)],
            face_index=index % len(FACES),
        )
        for index, target in enumerate(words)
    ]


def _story() -> list[StressItem]:
    targets = story_targets()
    items = []
    for size, theme, face in ((18, "light", 1), (28, "dark", 0)):
        for target in targets:
            item = replace(target, id=f"{target.id}@{size}")
            items.append(
                StressItem(item, "story", size=size, theme=theme, face_index=face)
            )
    return items


def _cursor_positions(words: list[TourTarget]) -> list[StressItem]:
    items = []
    for index, target in enumerate(words):
        for name, cursor in (
            ("begin", 0),
            ("middle", len(target.surface) // 2),
            ("end", len(target.surface) - 1),
        ):
            moved = replace(target, id=f"c{index + 1:03d}-{name}", cursor=cursor)
            items.append(
                StressItem(moved, "cursor", size=24, face_index=index % len(FACES))
            )
    return items


def _dense(words: list[TourTarget]) -> list[StressItem]:
    """Four lines of eight words, tightly leaded, every word its own target."""

    items = []
    for line_index in range(4):
        members = words[line_index * 8 : line_index * 8 + 8]
        line = " ".join(target.surface for target in members)
        start = 0
        for target in members:
            placed = replace(
                target,
                id=f"d{line_index + 1}-{target.id}",
                line=line,
                start=start,
            )
            items.append(StressItem(placed, "dense", size=16, face_index=line_index))
            start += len(target.surface) + 1
    return items


def _mixed(words: list[TourTarget]) -> list[StressItem]:
    """A UI-label line mixing Latin and Korean, hovered once on each script."""

    items = []
    for index, target in enumerate(words):
        prefix = _MIXED_PREFIX[index % len(_MIXED_PREFIX)]
        suffix = _MIXED_SUFFIX[index % len(_MIXED_SUFFIX)]
        line = f"{prefix} {target.surface} {suffix}"
        korean_start = len(prefix) + 1
        items.append(
            StressItem(
                replace(target, id=f"m{index + 1:03d}-ko", line=line, start=korean_start),
                "mixed_korean",
                size=22,
                face_index=index % len(FACES),
            )
        )
        items.append(
            StressItem(
                TourTarget(
                    id=f"m{index + 1:03d}-latin",
                    source="stress",
                    line=line,
                    start=0,
                    surface=prefix,
                    cursor=0,
                    lemma=None,
                    headword=None,
                    refuse=True,
                ),
                "mixed_latin",
                size=22,
                face_index=index % len(FACES),
            )
        )
    return items


def _rasters(words: list[TourTarget], generator: random.Random) -> list[StressItem]:
    items = [
        StressItem(
            replace(target, id=f"i{index + 1:03d}"),
            "image_text",
            size=SIZES[1 + index % 4],
            raster=RASTERS[index % len(RASTERS)],
            face_index=index % len(FACES),
        )
        for index, target in enumerate(words)
    ]
    for index in range(15):
        items.append(
            StressItem(
                _negative(f"in{index + 1:03d}", ""),
                "image_none",
                raster=RASTERS[index % len(RASTERS)],
                graphic="picture",
                size=generator.choice(SIZES),
            )
        )
    return items


# -- negatives --------------------------------------------------------------------


def _negative(identifier: str, surface: str) -> TourTarget:
    return TourTarget(
        id=identifier,
        source="stress",
        line=surface,
        start=0,
        surface=surface,
        cursor=max(0, len(surface) // 2),
        lemma=None,
        headword=None,
        refuse=True,
    )


def _negatives(generator: random.Random) -> list[StressItem]:
    items = [
        StressItem(_negative(f"b{index + 1:03d}", ""), "blank", theme=THEMES[index % 4])
        for index in range(30)
    ]
    for family, values, prefix in (
        ("number", _NUMBERS, "n"),
        ("punctuation", _PUNCTUATION, "p"),
        ("latin", _LATIN, "l"),
    ):
        for index, value in enumerate(values):
            items.append(
                StressItem(
                    _negative(f"{prefix}{index + 1:03d}", value),
                    family,
                    size=SIZES[index % len(SIZES)],
                    theme=THEMES[index % len(THEMES)],
                    face_index=index % len(FACES),
                )
            )
    for index in range(30):
        items.append(
            StressItem(
                _negative(f"g{index + 1:03d}", ""),
                "icon",
                graphic=_ICONS[index % len(_ICONS)],
                size=generator.choice((24, 32, 44)),
                theme=THEMES[index % len(THEMES)],
            )
        )
    return items


# -- behaviours -------------------------------------------------------------------


def _behaviors(
    spare: list[TourTarget], words: list[TourTarget], generator: random.Random
) -> list[StressItem]:
    items: list[StressItem] = []
    # Hovered again later in the run, so a cached recognition is exercised.
    for index, target in enumerate(generator.sample(words, 60)):
        items.append(
            StressItem(
                replace(target, id=f"r{index + 1:03d}"),
                "repeat",
                size=24,
                face_index=index % len(FACES),
                repeat_of=target.id,
            )
        )
    groups = iter(spare)
    for family, behavior, count in (
        ("rapid", "rapid", 40),
        ("leave_early", "leave_early", 40),
        ("changing", "changing", 15),
        ("covered", "dwell", 20),
    ):
        for index in range(count):
            target = next(groups)
            replacement = next(groups).surface if behavior == "changing" else None
            items.append(
                StressItem(
                    replace(target, id=f"{family[:2]}{index + 1:03d}"),
                    family,
                    behavior=behavior,
                    size=24,
                    face_index=index % len(FACES),
                    replacement=replacement,
                )
            )
    # The spot where the previous answer was shown, which is blank page by then.
    for index in range(30):
        items.append(StressItem(_negative(f"a{index + 1:03d}", ""), "after_popup"))
    return items


def _uia(words: list[TourTarget]) -> list[StressItem]:
    """Lines the helper window shows as real accessible text, read through UIA."""

    items = [
        StressItem(replace(target, id=f"u{index + 1:03d}"), "uia_korean", size=24)
        for index, target in enumerate(words)
    ]
    for index, word in enumerate(_LATIN[:10]):
        items.append(StressItem(_negative(f"ul{index + 1:03d}", word), "uia_latin", size=24))
    return items


__all__ = [
    "BEHAVIORAL",
    "FACES",
    "INFORMATIONAL",
    "NEGATIVE",
    "StressItem",
    "stress_plan",
    "summarize_plan",
]
