"""The controlled-image corpus: stated truth, generation identity, profiles and budgets."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lab.corpus import CorpusError, build_corpus, fingerprint, load_corpus
from lab.synthetic_ocr import (
    DiscoveredFace,
    SampleSpec,
    corpus_entry,
    discover_faces,
    render_sample,
    truth,
)
from lab.synthetic_profiles import generate, golden, seeded


@pytest.fixture(scope="module")
def korean() -> DiscoveredFace:
    faces = discover_faces(scripts=("hangul",))
    if not faces:
        pytest.skip("no installed face can draw Hangul")
    return faces[0]


def _text(face: DiscoveredFace, **overrides: Any) -> SampleSpec:
    base = SampleSpec(
        case_id="t", text="오늘 책을 읽어요", font=face.spec(), target_index=3, seed=1
    )
    return replace(base, **overrides)


# -- truth and identity ---------------------------------------------------------------------


def test_truth_is_stated_from_the_specification(korean: DiscoveredFace) -> None:
    assert truth(_text(korean)) == {
        "text_present": True,
        "korean_present": True,
        "target": "surface",
        "regions": "complete",
    }
    latin = _text(korean, text="Model X 사전", target_index=1)
    assert truth(latin)["target"] == "no_korean" and truth(latin)["korean_present"] is True
    blank = SampleSpec(case_id="b", text="", font=None, content="blank")
    assert truth(blank) == {
        "text_present": False,
        "korean_present": False,
        "target": "no_korean",
        "regions": "complete",
    }


def test_the_same_specification_always_gives_the_same_pixels(korean: DiscoveredFace) -> None:
    spec = _text(korean, noise=10.0, supersample=3, jpeg_quality=50)

    first, second = render_sample(spec), render_sample(spec)

    assert first.data == second.data
    assert first.metadata["generation"] == second.metadata["generation"]
    generation = first.metadata["generation"]
    assert generation["font"]["sha256"] == korean.sha256
    assert generation["rendering"] == {
        "supersample": 3,
        "antialias": True,
        "post_render_scale": 1.0,
        "blur_radius": 0.0,
        "jpeg_quality": 50,
        "noise": 10.0,
    }
    assert generation["image"]["pixel_sha256"]
    other_seed = render_sample(replace(spec, seed=2))
    assert other_seed.data != first.data


@pytest.mark.parametrize("change", [{}, {"supersample": 3}, {"scale": 0.5}, {"scale": 1.5}])
def test_the_target_stays_on_its_word_after_every_transform(
    korean: DiscoveredFace, change: dict[str, Any]
) -> None:
    rendered = render_sample(_text(korean, **change))
    entry = corpus_entry(rendered, "a.png", redistributable=False)

    x, y = entry["expected_target"]
    (region,) = entry["expected_regions"]
    assert region["left"] <= x <= region["right"] and region["top"] <= y <= region["bottom"]
    # The pointer is on 책, the fourth character: a little right of a quarter of the line.
    relative = (x - region["left"]) / (region["right"] - region["left"])
    assert 0.25 < relative < 0.55
    assert entry["expected_surface"] == "책을"


def test_supersampling_and_display_scaling_are_recorded_apart(korean: DiscoveredFace) -> None:
    supersampled = render_sample(_text(korean, supersample=3))
    scaled = render_sample(_text(korean, scale=0.5))
    plain = render_sample(_text(korean))

    assert abs(supersampled.width - plain.width) <= 2
    assert scaled.width == round(plain.width * 0.5)
    assert supersampled.metadata["generation"]["rendering"]["supersample"] == 3
    assert scaled.metadata["generation"]["rendering"]["post_render_scale"] == 0.5


@pytest.mark.parametrize(
    ("content", "graphic"),
    [("blank", None), ("icon", "star"), ("border", None), ("texture", "grain")],
)
def test_text_free_images_have_no_text_and_complete_empty_regions(
    content: str, graphic: str | None
) -> None:
    spec = SampleSpec(
        case_id=content,
        text="",
        font=None,
        content=content,
        graphic=graphic,
        target_fraction=(0.5, 0.5),
        family="negative",
    )

    entry = corpus_entry(render_sample(spec), "a.png", redistributable=False)

    assert entry["expected_text"] is None and entry["expected_regions"] == []
    assert entry["truth"]["text_present"] is False and entry["truth"]["target"] == "no_korean"
    assert "expected_surface" not in entry


def test_a_text_free_sample_cannot_carry_text() -> None:
    with pytest.raises(ValueError, match="carries no text"):
        SampleSpec(case_id="x", text="가", font=None, content="blank")


# -- manifests ------------------------------------------------------------------------------


def _manifest(cases: list[dict[str, Any]], schema: int = 2) -> dict[str, Any]:
    return {"schema_version": schema, "distribution": "local", "cases": cases}


def _case(**fields: Any) -> dict[str, Any]:
    return {"id": "c", "image": "c.png", "provenance": "local_synthetic", **fields}


def test_a_schema_one_manifest_still_loads_without_stated_truth() -> None:
    corpus = build_corpus(
        _manifest([_case(expected_text="가")], 1), Path("m.json"), require_assets=False
    )

    assert corpus.schema_version == 1 and corpus.cases[0].truth is None
    with pytest.raises(CorpusError, match="schema_version 2"):
        build_corpus(_manifest([_case(truth={})], 1), Path("m.json"), require_assets=False)
    with pytest.raises(CorpusError, match="unsupported"):
        build_corpus(_manifest([], 3), Path("m.json"), require_assets=False)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {
                "expected_text": "가",
                "truth": {
                    "text_present": False,
                    "korean_present": False,
                    "target": "none",
                    "regions": "complete",
                },
            },
            "without text",
        ),
        (
            {
                "truth": {
                    "text_present": True,
                    "korean_present": True,
                    "target": "surface",
                    "regions": "missing",
                }
            },
            "surface target needs",
        ),
        (
            {
                "truth": {
                    "text_present": True,
                    "korean_present": False,
                    "target": "none",
                    "regions": "complete",
                }
            },
            "needs the regions",
        ),
        ({"truth": {"text_present": True}}, "exactly"),
        ({"family": "maybe"}, "family"),
    ],
)
def test_inconsistent_truth_is_refused(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(CorpusError, match=message):
        build_corpus(_manifest([_case(**fields)]), Path("m.json"), require_assets=False)


# -- profiles -------------------------------------------------------------------------------


def test_golden_covers_every_family_and_condition_once() -> None:
    recipes = golden()

    assert {recipe.family for recipe in recipes} == {"positive", "negative", "mixed"}
    assert {recipe.content for recipe in recipes} == {"text", "blank", "icon", "border", "texture"}
    assert len(recipes) < 30


def test_seeded_profiles_are_deterministic_and_balanced() -> None:
    first, second = seeded("balanced", 4, 60), seeded("balanced", 4, 60)

    assert first == second and seeded("balanced", 5, 60) != first
    families = [recipe.family for recipe in first]
    assert {families.count(name) for name in ("positive", "negative", "mixed")} <= set(
        range(18, 23)
    )
    assert all(recipe.condition.size <= 16 for recipe in seeded("difficult", 1, 30))


def test_a_profile_renders_loads_and_reproduces(korean: DiscoveredFace, tmp_path: Path) -> None:
    one = generate("golden", tmp_path / "one", faces=[korean])
    two = generate("golden", tmp_path / "two", faces=[korean])

    corpus = load_corpus(tmp_path / "one" / "manifest.json")
    assert len(corpus.cases) == len(one.manifest["cases"]) > 15
    assert all(case.truth is not None and case.generation for case in corpus.cases)
    assert all(case.provenance == "local_synthetic" for case in corpus.cases)
    assert fingerprint(corpus) == fingerprint(load_corpus(tmp_path / "two" / "manifest.json"))
    assert [c["generation"] for c in one.manifest["cases"]] == [
        c["generation"] for c in two.manifest["cases"]
    ]
    recorded = json.loads((tmp_path / "one" / "generation.json").read_text("utf-8"))
    assert recorded["profile"] == "golden" and len(recorded["recipes"]) == len(corpus.cases)


def test_a_missing_script_is_omitted_never_substituted(
    korean: DiscoveredFace, tmp_path: Path
) -> None:
    hangul_only = replace(korean, scripts=("hangul", "latin"))

    result = generate("golden", tmp_path / "out", faces=[hangul_only])

    reasons = [item["reason"] for item in result.omitted]
    assert any("kana" in reason for reason in reasons)
    assert any("han glyphs" in reason for reason in reasons)
    assert not any("kana" in case["tags"] for case in result.manifest["cases"])


def test_no_korean_face_means_no_corpus(tmp_path: Path) -> None:
    result = generate("smoke", tmp_path / "out", faces=[])

    assert result.manifest["cases"] == []
    assert result.omitted == [{"case": "*", "reason": "no installed face can draw Hangul"}]


def test_budgets_bound_the_output(korean: DiscoveredFace, tmp_path: Path) -> None:
    by_cases = generate("balanced", tmp_path / "a", faces=[korean], max_cases=5)
    by_bytes = generate("balanced", tmp_path / "b", faces=[korean], max_cases=50, max_bytes=1)

    assert len(by_cases.manifest["cases"]) == 5
    assert len(by_bytes.manifest["cases"]) == 1
    assert sum("byte budget" in item["reason"] for item in by_bytes.omitted) == 49


def test_a_changed_image_changes_the_fingerprint(korean: DiscoveredFace, tmp_path: Path) -> None:
    generate("smoke", tmp_path / "c", faces=[korean], max_cases=3)
    manifest = tmp_path / "c" / "manifest.json"
    before = fingerprint(load_corpus(manifest))

    image = next((tmp_path / "c" / "images").iterdir())
    image.write_bytes(image.read_bytes() + b"\0")

    assert fingerprint(load_corpus(manifest)) != before
