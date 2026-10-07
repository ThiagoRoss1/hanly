"""Named, bounded recipes for the controlled-image corpus.

A profile turns installed faces and a seed into a list of sample
specifications, never an unrestricted product of every condition:

- ``golden``: a small fixed recipe set, one of each family and condition;
- ``smoke``: a few seeded cases per family, for a quick check;
- ``balanced``: seeded cases split evenly across positive, negative and mixed;
- ``difficult``: seeded cases drawn only from targeted hard combinations
  (small, low-contrast, blurred, compressed, noisy, scaled text).

Korean text comes from the minibook (lab-authored lines with hand-set target
words). Faces come from :func:`lab.synthetic_ocr.discover_faces`; a recipe that
needs a script no installed face proves it can draw is listed as omitted with
its reason, never rendered in another face. Output stays under the gitignored
``artifacts/lab/corpus`` by default and stops at the case and byte budgets.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .identity import LAB_ROOT
from .minibook import load_minibook
from .synthetic_ocr import (
    ICONS,
    TEXTURES,
    DiscoveredFace,
    SampleSpec,
    SyntheticFontError,
    SyntheticRenderError,
    corpus_entry,
    discover_faces,
    render_sample,
    write_sample,
)

PROFILES = ("golden", "smoke", "balanced", "difficult")
DEFAULT_CASES = {"golden": 64, "smoke": 24, "balanced": 240, "difficult": 120}
DEFAULT_MAX_BYTES = 64 * 2**20
OUTPUT_ROOT = LAB_ROOT / "corpus"

#: (background, foreground) per named theme, in grey levels.
THEMES = {"light": (255, 0), "dark": (24, 235), "low_contrast": (200, 125), "gray": (128, 250)}
SIZES = (12, 16, 20, 28, 40)
LATIN = ("Dictionary", "Settings", "Download now", "OK Cancel", "Hello world", "Next Back")
NUMBERS = ("2026-10-07", "3.14159", "1,250,000", "10:42", "v2.0.1", "99%")
PUNCTUATION = ("…?!", "《》「」", "※ ★ →", "( ) [ ]", "· · ·")
MIXED_AFFIXES = (("Model X-2", "3.5GHz"), ("Ver 3.1", "(beta)"), ("NEW", "Pro"), ("Q&A", "2026"))
KANA = ("ひらがな", "カタカナ")
HAN = ("漢字", "中文")


@dataclass(frozen=True)
class Condition:
    """How a sample is rendered, apart from what it shows."""

    size: int = 20
    theme: str = "light"
    supersample: int = 1
    scale: float = 1.0
    blur: float = 0.0
    jpeg: int | None = None
    noise: float = 0.0
    antialias: bool = True

    def tags(self) -> list[str]:
        tags = ["light" if self.theme in {"light", "low_contrast"} else "dark"]
        tags.append(
            "small_text" if self.size <= 14 else "large_text" if self.size >= 28 else "medium_text"
        )
        for flag, tag in (
            (self.scale != 1.0, "scaled"),
            (self.blur > 0, "blurred"),
            (self.jpeg is not None, "compressed"),
            (self.noise > 0, "noise"),
            (self.supersample > 1, "supersampled"),
            (self.theme == "low_contrast", "low_contrast"),
        ):
            if flag:
                tags.append(tag)
        return tags


@dataclass(frozen=True)
class Recipe:
    """One planned case: what it shows, how, and in which face."""

    family: str
    content: str
    text: str = ""
    target_index: int | None = None
    expected_surface: str | None = None
    graphic: str | None = None
    needs: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    condition: Condition = field(default_factory=Condition)


@dataclass
class Generated:
    manifest: dict[str, Any]
    omitted: list[dict[str, str]]
    recipes: list[dict[str, Any]]
    bytes_written: int = 0


# -- recipes ------------------------------------------------------------------------------


def korean_lines() -> list[tuple[str, int, str]]:
    """(line, index of the pointer, target surface) for each minibook Korean target."""

    book = load_minibook()
    return [
        (book.lines[target.line], target.start + target.cursor, target.surface)
        for target in book.targets
        if not target.refuse and all("가" <= ch <= "힣" for ch in target.surface)
    ]


def positive(rng: random.Random, condition: Condition) -> Recipe:
    line, index, surface = rng.choice(korean_lines())
    return Recipe("positive", "text", line, index, surface, condition=condition)


def mixed(rng: random.Random, condition: Condition, *, on_korean: bool | None = None) -> Recipe:
    line, _, surface = rng.choice(korean_lines())
    prefix, suffix = rng.choice(MIXED_AFFIXES)
    text = f"{prefix} {surface} {suffix}"
    korean = rng.random() < 0.5 if on_korean is None else on_korean
    index = len(prefix) + 1 + len(surface) // 2 if korean else len(prefix) // 2
    return Recipe(
        "mixed",
        "text",
        text,
        index,
        surface if korean else None,
        tags=("mixed_script",),
        condition=condition,
    )


def negative(rng: random.Random, condition: Condition, kind: str | None = None) -> Recipe:
    kind = kind or rng.choice(
        ("blank", "latin", "number", "punctuation", "icon", "border", "texture")
    )
    if kind in {"latin", "number", "punctuation"}:
        pool = {"latin": LATIN, "number": NUMBERS, "punctuation": PUNCTUATION}[kind]
        text = rng.choice(pool)
        return Recipe("negative", "text", text, len(text) // 2, tags=(kind,), condition=condition)
    graphic = (
        rng.choice(ICONS if kind == "icon" else TEXTURES) if kind in {"icon", "texture"} else None
    )
    return Recipe("negative", kind, graphic=graphic, tags=(kind,), condition=condition)


def other_script(rng: random.Random, condition: Condition, script: str) -> Recipe:
    text = rng.choice(KANA if script == "kana" else HAN)
    return Recipe(
        "negative",
        "text",
        text,
        len(text) // 2,
        needs=(script,),
        tags=(script,),
        condition=condition,
    )


def golden() -> list[Recipe]:
    """A fixed recipe set: one of each family, content and rendering condition."""

    rng = random.Random(0)
    plain = Condition()
    recipes = [
        positive(rng, plain),
        positive(rng, Condition(theme="dark")),
        positive(rng, Condition(size=12)),
        positive(rng, Condition(size=40)),
        positive(rng, Condition(supersample=3)),
        positive(rng, Condition(size=28, scale=0.5)),
        positive(rng, Condition(jpeg=40)),
        positive(rng, Condition(blur=0.8)),
        positive(rng, Condition(noise=12.0)),
        positive(rng, Condition(theme="low_contrast")),
        positive(rng, Condition(antialias=False)),
        mixed(rng, plain, on_korean=True),
        mixed(rng, plain, on_korean=False),
    ]
    recipes += [
        negative(rng, plain, kind)
        for kind in ("blank", "latin", "number", "punctuation", "icon", "border", "texture")
    ]
    recipes += [other_script(rng, plain, "kana"), other_script(rng, plain, "han")]
    return recipes


def seeded(profile: str, seed: int, count: int) -> list[Recipe]:
    """Balanced or targeted recipes, deterministic for one seed."""

    rng = random.Random(f"{profile}:{seed}")
    Builder = Callable[[random.Random, Condition], Recipe]
    builders: list[Builder] = [positive, negative, mixed]
    if profile == "difficult":
        builders = [mixed, positive, positive]
    recipes = []
    for index in range(count):
        condition = _difficult(rng) if profile == "difficult" else _condition(rng)
        builder = builders[index % len(builders)]
        recipes.append(builder(rng, condition))
        if profile == "balanced" and index % 40 == 39:
            recipes.append(other_script(rng, condition, "kana" if index % 80 == 39 else "han"))
    return recipes[:count]


def _condition(rng: random.Random) -> Condition:
    return Condition(
        size=rng.choice(SIZES),
        theme=rng.choice(tuple(THEMES)),
        supersample=rng.choice((1, 1, 3)),
        scale=rng.choice((1.0, 1.0, 0.75, 1.5)),
        blur=rng.choice((0.0, 0.0, 0.6)),
        jpeg=rng.choice((None, None, 50)),
        noise=rng.choice((0.0, 0.0, 8.0)),
    )


def _difficult(rng: random.Random) -> Condition:
    """Only combinations known to be hard: small or scaled-down, plus a degradation."""

    return Condition(
        size=rng.choice((12, 14, 16)),
        theme=rng.choice(("low_contrast", "dark", "light")),
        scale=rng.choice((1.0, 0.75)),
        blur=rng.choice((0.0, 0.8)),
        jpeg=rng.choice((None, 35)),
        noise=rng.choice((0.0, 10.0)),
        antialias=rng.choice((True, False)),
    )


# -- generation ---------------------------------------------------------------------------


def generate(
    profile: str,
    destination: Path,
    *,
    seed: int = 0,
    max_cases: int | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    faces: Sequence[DiscoveredFace] | None = None,
) -> Generated:
    """Render one profile into ``destination``; report every recipe it could not render."""

    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; one of {PROFILES}")
    limit = DEFAULT_CASES[profile] if max_cases is None else max_cases
    available = list(faces) if faces is not None else discover_faces(scripts=("hangul",))
    by_script = {
        script: [face for face in available if script in face.scripts]
        for script in ("hangul", "kana", "han")
    }
    recipes = golden() if profile == "golden" else seeded(profile, seed, limit)
    result = Generated(
        manifest={
            "schema_version": 2,
            "distribution": "local",
            "description": f"Generated {profile} corpus, seed {seed}. Local: face licences "
            "are unknown unless stated.",
            "cases": [],
        },
        omitted=[],
        recipes=[],
    )
    if not by_script["hangul"]:
        result.omitted.append({"case": "*", "reason": "no installed face can draw Hangul"})
        return result

    for index, recipe in enumerate(recipes):
        case_id = f"{profile}-{seed}-{index:04d}-{recipe.family}-{recipe.content}"
        if len(result.manifest["cases"]) >= limit:
            result.omitted.append({"case": case_id, "reason": f"case budget {limit} reached"})
            continue
        if result.bytes_written >= max_bytes:
            result.omitted.append({"case": case_id, "reason": f"byte budget {max_bytes} reached"})
            continue
        pool = by_script[recipe.needs[0]] if recipe.needs else by_script["hangul"]
        if not pool:
            result.omitted.append(
                {"case": case_id, "reason": f"no installed face proves {recipe.needs[0]} glyphs"}
            )
            continue
        face = pool[index % len(pool)]
        spec = _spec(case_id, recipe, face, profile, seed + index)
        try:
            rendered = render_sample(spec)
        except (SyntheticFontError, SyntheticRenderError) as error:
            result.omitted.append({"case": case_id, "reason": str(error)})
            continue
        relative = f"images/{case_id}.png"
        path = write_sample(rendered, destination / relative)
        result.bytes_written += path.stat().st_size
        result.manifest["cases"].append(corpus_entry(rendered, relative, redistributable=False))
        result.recipes.append({"case": case_id, "face": face.family, **_recipe_dict(recipe)})

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(
        json.dumps(result.manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (destination / "generation.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "seed": seed,
                "max_cases": limit,
                "max_bytes": max_bytes,
                "bytes_written": result.bytes_written,
                "recipes": result.recipes,
                "omitted": result.omitted,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def _spec(
    case_id: str, recipe: Recipe, face: DiscoveredFace, profile: str, seed: int
) -> SampleSpec:
    condition = recipe.condition
    background, foreground = THEMES[condition.theme]
    tags = ["synthetic", "seeded" if profile in {"smoke", "balanced"} else profile]
    tags += condition.tags() + list(recipe.tags) + ["horizontal"]
    base = SampleSpec(
        case_id=case_id,
        text=recipe.text,
        font=face.spec() if recipe.content == "text" else None,
        font_size=condition.size,
        background=background,
        foreground=foreground,
        scale=condition.scale,
        jpeg_quality=condition.jpeg,
        blur_radius=condition.blur,
        tags=tuple(sorted(set(tags))),
        content=recipe.content,
        supersample=condition.supersample,
        antialias=condition.antialias,
        noise=condition.noise,
        seed=seed,
        graphic=recipe.graphic,
        target_index=recipe.target_index,
        expected_surface=recipe.expected_surface,
        family=recipe.family,
    )
    if recipe.content != "text":
        # Text-free: the pointer rests mid-image, where nothing Korean can be.
        return replace(base, target_fraction=(0.5, 0.5))
    return base


def _recipe_dict(recipe: Recipe) -> dict[str, Any]:
    return {
        "family": recipe.family,
        "content": recipe.content,
        "graphic": recipe.graphic,
        "condition": recipe.condition.__dict__,
    }


__all__ = [
    "DEFAULT_CASES",
    "DEFAULT_MAX_BYTES",
    "OUTPUT_ROOT",
    "PROFILES",
    "Condition",
    "Generated",
    "Recipe",
    "generate",
    "golden",
    "seeded",
]
