"""The synthetic generator, and the two things it refuses to do.

Both refusals matter more than the rendering. A substituted face produces
samples that look right and measure something else, and a face whose licence
forbids redistribution must never end up in a committed manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.dev.corpus import SCHEMA_VERSION, CorpusError, build_corpus
from benchmarks.dev.synthetic_ocr import (
    FontSpec,
    SampleSpec,
    SyntheticFontError,
    corpus_entry,
    load_generator_config,
    render_sample,
    resolve_font,
    write_sample,
)

#: A face that exists on this machine. Its licence forbids redistribution,
#: which is exactly what half of these tests are about.
_LOCAL_FACE = FontSpec(
    name="Apple SD Gothic Neo",
    licence="Apple-Proprietary",
    filenames=("AppleSDGothicNeo.ttc",),
)
_OPEN_FACE = FontSpec(
    name="Noto Sans KR", licence="OFL-1.1", filenames=("NotoSansKR-Regular.ttf",)
)


def _available(spec: FontSpec) -> bool:
    try:
        resolve_font(spec)
    except SyntheticFontError:
        return False
    return True


def _requires_local_face() -> FontSpec:
    if not _available(_LOCAL_FACE):
        pytest.skip("no Korean-capable face is installed on this machine")
    return _LOCAL_FACE


def _sample(**overrides: object) -> SampleSpec:
    defaults: dict[str, object] = {
        "case_id": "sample",
        "text": "책을 읽습니다.",
        "font": _requires_local_face(),
        "font_size": 20,
    }
    defaults.update(overrides)
    return SampleSpec(**defaults)  # type: ignore[arg-type]


# --- Refusals ---------------------------------------------------------------


def test_a_face_that_is_not_installed_is_never_substituted() -> None:
    """A silent fallback would mislabel every sample rendered from it."""

    missing = FontSpec(
        name="Nonexistent Korean", licence="OFL-1.1", filenames=("NoSuchFace-Regular.ttf",)
    )

    with pytest.raises(SyntheticFontError, match="is not installed"):
        resolve_font(missing)


def test_the_refusal_names_the_face_and_what_it_looked_for() -> None:
    missing = FontSpec(name="Absent", licence="OFL-1.1", filenames=("Absent.ttf",))

    with pytest.raises(SyntheticFontError) as caught:
        resolve_font(missing)

    message = str(caught.value)
    assert "'Absent'" in message and "OFL-1.1" in message and "Absent.ttf" in message


def test_a_face_without_the_glyphs_cannot_render_the_text() -> None:
    latin_only = FontSpec(
        name="Noto Sans Gothic",
        licence="OFL-1.1",
        filenames=("NotoSansGothic-Regular.ttf",),
    )
    if not _available(latin_only):
        pytest.skip("the Gothic script face is not installed")

    with pytest.raises(SyntheticFontError, match="no glyph for"):
        render_sample(_sample(font=latin_only))


def test_a_non_redistributable_face_produces_only_local_cases() -> None:
    face = _requires_local_face()
    resolved = resolve_font(face)
    rendered = render_sample(_sample(font=face))

    assert resolved.redistributable is False
    entry = corpus_entry(rendered, "generated/a.png", redistributable=False)
    assert entry["provenance"] == "local_synthetic"


def test_such_a_case_is_then_refused_by_a_committed_manifest() -> None:
    """The two halves of the rule meet here: generation labels, corpus enforces."""

    face = _requires_local_face()
    rendered = render_sample(_sample(font=face))
    entry = corpus_entry(rendered, "generated/a.png", redistributable=False)

    with pytest.raises(CorpusError, match="cannot appear in a committed manifest"):
        build_corpus(
            {"schema_version": SCHEMA_VERSION, "distribution": "committed", "cases": [entry]},
            Path("manifest.json"),
            require_assets=False,
        )


def test_an_open_licensed_face_would_produce_a_committed_case() -> None:
    face = _requires_local_face()
    rendered = render_sample(_sample(font=face))

    entry = corpus_entry(rendered, "generated/a.png", redistributable=True)

    assert entry["provenance"] == "committed_synthetic"
    assert _OPEN_FACE.redistributable is True


# --- Rendering --------------------------------------------------------------


def test_a_rendered_sample_is_deterministic() -> None:
    first = render_sample(_sample())
    second = render_sample(_sample())

    assert (first.width, first.height) == (second.width, second.height)
    assert first.data == second.data


def test_the_sample_records_the_exact_font_bytes_it_used() -> None:
    face = _requires_local_face()
    resolved = resolve_font(face)

    rendered = render_sample(_sample(font=face))

    assert rendered.metadata["font_sha256"] == resolved.sha256
    assert rendered.metadata["font_path"] == str(resolved.path)
    assert rendered.metadata["font_redistributable"] is False
    assert rendered.metadata["pillow_version"]


def test_the_expected_text_travels_with_the_image() -> None:
    rendered = render_sample(_sample(text="떨어뜨렸어요"))

    entry = corpus_entry(rendered, "generated/a.png", redistributable=False)
    assert entry["expected_text"] == "떨어뜨렸어요"


def test_a_larger_font_renders_a_larger_image() -> None:
    small = render_sample(_sample(case_id="s", font_size=12))
    large = render_sample(_sample(case_id="l", font_size=34))

    assert large.width > small.width and large.height > small.height


def test_a_dark_sample_really_is_inverted() -> None:
    light = render_sample(_sample(case_id="light", background=255, foreground=0))
    dark = render_sample(_sample(case_id="dark", background=24, foreground=235))

    assert light.data != dark.data
    # The corner pixel is background in both, so it names which is which.
    assert light.data[0] == 255 and dark.data[0] == 24


def test_scaling_down_produces_a_smaller_image() -> None:
    full = render_sample(_sample(case_id="full", font_size=28))
    halved = render_sample(_sample(case_id="half", font_size=28, scale=0.5))

    assert halved.width == round(full.width * 0.5)


def test_compression_and_blur_change_the_pixels_without_changing_the_size() -> None:
    plain = render_sample(_sample(case_id="plain"))
    compressed = render_sample(_sample(case_id="jpeg", jpeg_quality=30))
    blurred = render_sample(_sample(case_id="blur", blur_radius=1.0))

    assert (compressed.width, compressed.height) == (plain.width, plain.height)
    assert (blurred.width, blurred.height) == (plain.width, plain.height)
    assert compressed.data != plain.data
    assert blurred.data != plain.data


# --- Annotations ------------------------------------------------------------


def test_an_annotated_target_lands_inside_the_rendered_image() -> None:
    rendered = render_sample(_sample(target_fraction=(0.72, 0.5), expected_surface="읽습니다."))

    entry = corpus_entry(rendered, "generated/a.png", redistributable=False)
    x, y = entry["expected_target"]
    assert 0 <= x < rendered.width and 0 <= y < rendered.height
    assert entry["expected_surface"] == "읽습니다."


def test_an_unannotated_sample_carries_no_target_at_all() -> None:
    entry = corpus_entry(render_sample(_sample()), "generated/a.png", redistributable=False)

    assert "expected_target" not in entry
    assert "expected_surface" not in entry


# --- Configuration ----------------------------------------------------------


def test_the_committed_generator_config_names_an_open_licensed_face() -> None:
    font, samples = load_generator_config("benchmarks/fixtures/ocr/generator.json")

    assert font.redistributable is True
    assert font.licence == "OFL-1.1"
    assert len(samples) >= 5
    assert all(sample.font is font for sample in samples)


def test_a_generator_config_round_trips_its_parameters(tmp_path: Path) -> None:
    path = tmp_path / "generator.json"
    path.write_text(
        json.dumps(
            {
                "font": {
                    "name": "Some Face",
                    "licence": "OFL-1.1",
                    "filenames": ["SomeFace.ttf"],
                    "index": 2,
                },
                "samples": [
                    {
                        "id": "one",
                        "text": "책",
                        "font_size": 18,
                        "scale": 0.75,
                        "jpeg_quality": 40,
                        "blur_radius": 1.5,
                        "tags": ["synthetic", "light"],
                        "target_fraction": [0.4, 0.5],
                        "expected_surface": "책",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    font, samples = load_generator_config(path)

    assert font.index == 2
    (sample,) = samples
    assert (sample.font_size, sample.scale, sample.jpeg_quality) == (18, 0.75, 40)
    assert sample.blur_radius == 1.5
    assert sample.target_fraction == (0.4, 0.5)
    assert sample.expected_surface == "책"


def test_a_sample_without_text_is_refused() -> None:
    with pytest.raises(ValueError, match="needs text"):
        SampleSpec(case_id="empty", text="   ", font=_OPEN_FACE)


def test_writing_a_sample_produces_a_readable_png(tmp_path: Path) -> None:
    from PIL import Image

    rendered = render_sample(_sample())
    written = write_sample(rendered, tmp_path / "generated" / "a.png")

    with Image.open(written) as image:
        assert image.size == (rendered.width, rendered.height)
        assert image.mode == "L"
