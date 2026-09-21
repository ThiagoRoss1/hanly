"""The corpus manifest contract, and the privacy boundary it enforces.

The rule worth being strict about: a manifest in Git must not name, path, or
quote anything that came off somebody's screen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.dev.corpus import (
    SCHEMA_VERSION,
    Corpus,
    CorpusError,
    ExpectedRegion,
    build_corpus,
    inventory,
    load_corpus,
    validate_case_geometry,
)

REPO_MANIFEST = Path("benchmarks/fixtures/ocr/manifest.json")


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "case-a",
        "image": "generated/a.png",
        "provenance": "committed_synthetic",
        "tags": ["synthetic", "light"],
        "expected_text": "책을 읽습니다.",
        "source": {"font_name": "Noto Sans KR", "font_licence": "OFL-1.1"},
    }
    case.update(overrides)
    return case


def _manifest(*cases: dict[str, Any], distribution: str = "committed") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "distribution": distribution,
        "cases": list(cases),
    }


def _write(tmp_path: Path, payload: dict[str, Any], *, images: tuple[str, ...] = ()) -> Path:
    for relative in images:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"not really a png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def _load(tmp_path: Path, payload: dict[str, Any], **kwargs: Any) -> Corpus:
    return build_corpus(payload, tmp_path / "manifest.json", require_assets=False, **kwargs)


# --- Schema -----------------------------------------------------------------


def test_the_committed_manifest_in_this_repository_is_valid() -> None:
    corpus = load_corpus(REPO_MANIFEST)

    assert corpus.distribution == "committed"
    assert corpus.schema_version == SCHEMA_VERSION


def test_an_unsupported_schema_version_is_refused() -> None:
    with pytest.raises(CorpusError, match="unsupported corpus schema_version"):
        _load(Path("."), {**_manifest(), "schema_version": 99})


def test_a_manifest_must_declare_which_kind_it_is() -> None:
    payload = _manifest()
    del payload["distribution"]

    with pytest.raises(CorpusError, match="distribution must be one of"):
        _load(Path("."), payload)


def test_an_unknown_manifest_field_is_refused() -> None:
    with pytest.raises(CorpusError, match=r"manifest carries unknown field\(s\) \['metrics'\]"):
        _load(Path("."), {**_manifest(), "metrics": {"cer": 0.0}})


def test_an_unknown_case_field_is_refused() -> None:
    """A misspelled expectation would otherwise be silently ignored."""

    with pytest.raises(CorpusError, match=r"case carries unknown field\(s\) \['expected_lemma'\]"):
        _load(Path("."), _manifest(_case(expected_lemma="읽다")))


def test_duplicate_case_ids_are_refused() -> None:
    with pytest.raises(CorpusError, match="duplicate corpus case id 'case-a'"):
        _load(Path("."), _manifest(_case(), _case(image="generated/b.png")))


def test_cases_are_ordered_by_identifier_whatever_the_file_lists_first() -> None:
    corpus = _load(
        Path("."),
        _manifest(
            _case(id="zeta", image="z.png"),
            _case(id="alpha", image="a.png"),
            _case(id="mu", image="m.png"),
        ),
    )

    assert [case.case_id for case in corpus.cases] == ["alpha", "mu", "zeta"]


def test_an_unknown_tag_is_refused() -> None:
    with pytest.raises(CorpusError, match="unknown tag"):
        _load(Path("."), _manifest(_case(tags=["synthetic", "ligth"])))


def test_a_committed_case_must_record_where_it_came_from() -> None:
    with pytest.raises(CorpusError, match="must record where it came from"):
        _load(Path("."), _manifest(_case(source={})))


# --- Assets -----------------------------------------------------------------


def test_a_missing_image_is_refused(tmp_path: Path) -> None:
    manifest = _write(tmp_path, _manifest(_case()))

    with pytest.raises(CorpusError, match="references a missing image"):
        load_corpus(manifest)


def test_image_paths_resolve_against_the_manifest_not_the_process(tmp_path: Path) -> None:
    manifest = _write(tmp_path, _manifest(_case()), images=("generated/a.png",))

    corpus = load_corpus(manifest)

    assert corpus.cases[0].image == tmp_path / "generated" / "a.png"
    assert corpus.cases[0].relative_image == "generated/a.png"


# --- The privacy boundary ---------------------------------------------------


def test_a_committed_manifest_cannot_reference_a_private_case() -> None:
    with pytest.raises(CorpusError, match="cannot appear in a committed manifest"):
        _load(Path("."), _manifest(_case(provenance="local_private")))


def test_a_committed_manifest_cannot_reference_a_local_synthetic_case() -> None:
    with pytest.raises(CorpusError, match="cannot appear in a committed manifest"):
        _load(Path("."), _manifest(_case(provenance="local_synthetic")))


def test_a_committed_manifest_cannot_carry_a_machine_specific_path() -> None:
    with pytest.raises(CorpusError, match="must stay machine-independent"):
        _load(Path("."), _manifest(_case(image="/Users/someone/screenshots/a.png")))


def test_a_local_manifest_may_hold_private_cases_and_absolute_paths() -> None:
    corpus = _load(
        Path("."),
        _manifest(
            _case(
                id="private-1",
                image="/Users/someone/artifacts/frozen/input.png",
                provenance="local_private",
                source={},
            ),
            distribution="local",
        ),
    )

    assert corpus.cases[0].is_private is True
    assert corpus.cases[0].is_committed is False


# --- Geometry ---------------------------------------------------------------


def test_a_negative_target_is_refused() -> None:
    with pytest.raises(CorpusError, match="must lie inside the image"):
        _load(Path("."), _manifest(_case(expected_target=[-1, 4])))


def test_a_malformed_target_is_refused() -> None:
    with pytest.raises(CorpusError, match=r"expected_target must be \[x, y\]"):
        _load(Path("."), _manifest(_case(expected_target=[1, 2, 3])))


def test_a_region_without_extent_is_refused() -> None:
    with pytest.raises(CorpusError, match="has no positive extent"):
        _load(
            Path("."),
            _manifest(
                _case(
                    expected_regions=[
                        {"text": "책", "left": 10, "top": 4, "right": 10, "bottom": 20}
                    ]
                )
            ),
        )


def test_a_region_missing_a_bound_is_refused() -> None:
    with pytest.raises(CorpusError, match="region is missing 'bottom'"):
        _load(
            Path("."),
            _manifest(
                _case(expected_regions=[{"text": "책", "left": 0, "top": 0, "right": 10}])
            ),
        )


def test_annotations_are_checked_against_the_image_they_describe() -> None:
    corpus = _load(
        Path("."),
        _manifest(
            _case(
                expected_target=[400, 4],
                expected_regions=[
                    {"text": "책", "left": 0, "top": 0, "right": 10, "bottom": 20}
                ],
            )
        ),
    )

    validate_case_geometry(corpus.cases[0], 500, 40)
    with pytest.raises(CorpusError, match="expected_target"):
        validate_case_geometry(corpus.cases[0], 100, 40)


def test_a_region_outside_its_image_is_refused_at_geometry_time() -> None:
    corpus = _load(
        Path("."),
        _manifest(
            _case(
                expected_regions=[
                    {"text": "책", "left": 0, "top": 0, "right": 400, "bottom": 20}
                ]
            )
        ),
    )

    with pytest.raises(CorpusError, match="lies outside its 100x40 image"):
        validate_case_geometry(corpus.cases[0], 100, 40)


# --- Selection and inventory ------------------------------------------------


def test_cases_can_be_selected_by_every_tag_they_carry() -> None:
    corpus = _load(
        Path("."),
        _manifest(
            _case(id="a", tags=["synthetic", "light", "small_text"]),
            _case(id="b", image="b.png", tags=["synthetic", "dark"]),
        ),
    )

    assert [case.case_id for case in corpus.tagged("synthetic")] == ["a", "b"]
    assert [case.case_id for case in corpus.tagged("synthetic", "light")] == ["a"]
    assert corpus.tagged("browser") == ()


def test_the_inventory_counts_without_naming_any_content() -> None:
    corpus = _load(
        Path("."),
        _manifest(
            _case(id="a", tags=["synthetic", "light"]),
            _case(id="b", image="b.png", tags=["synthetic", "dark"], expected_text=None),
        ),
    )

    summary = inventory(corpus)

    assert summary["case_count"] == 2
    assert summary["by_provenance"] == {"committed_synthetic": 2}
    assert summary["by_tag"] == {"synthetic": 2, "light": 1, "dark": 1}
    assert summary["annotated_text"] == 1
    encoded = json.dumps(summary, ensure_ascii=False)
    assert "책" not in encoded


def test_a_case_can_be_fetched_by_identifier() -> None:
    corpus = _load(Path("."), _manifest(_case(id="wanted")))

    assert corpus.case("wanted").case_id == "wanted"
    with pytest.raises(KeyError):
        corpus.case("absent")


def test_a_region_is_an_ordinary_value() -> None:
    region = ExpectedRegion(text="책", left=1, top=2, right=3, bottom=4)

    assert (region.left, region.bottom) == (1, 4)


# --- A committed manifest stays inside its own fixture tree -----------------


def test_a_committed_case_cannot_traverse_out_to_a_private_capture(
    tmp_path: Path,
) -> None:
    """The committed/local split exists to stop exactly this reference."""

    fixtures = tmp_path / "benchmarks" / "fixtures" / "ocr"
    fixtures.mkdir(parents=True)
    private = tmp_path / "artifacts" / "benchmarks" / "runs" / "run-1"
    private.mkdir(parents=True)
    (private / "input.png").write_bytes(b"private screen content")

    with pytest.raises(CorpusError, match="resolves outside the manifest's own directory"):
        build_corpus(
            _manifest(_case(image="../../../artifacts/benchmarks/runs/run-1/input.png")),
            fixtures / "manifest.json",
        )


@pytest.mark.parametrize(
    "image",
    [
        r"C:\Users\someone\shot.png",
        r"\\server\share\shot.png",
        "~/screenshots/a.png",
        "~someone/screenshots/a.png",
    ],
)
def test_a_committed_case_cannot_name_one_machine(image: str) -> None:
    """``Path.is_absolute`` answers for the host, so a Windows path reads as
    relative on POSIX -- and those are the paths carrying a user name."""

    with pytest.raises(CorpusError, match="machine-independent"):
        _load(Path("."), _manifest(_case(image=image)))


def test_a_local_manifest_may_still_point_wherever_it_needs_to(
    tmp_path: Path,
) -> None:
    """Containment is a committed-manifest rule; private evidence lives outside."""

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    elsewhere = tmp_path / "artifacts" / "run-1"
    elsewhere.mkdir(parents=True)
    (elsewhere / "input.png").write_bytes(b"private")

    corpus = build_corpus(
        _manifest(
            _case(
                image="../artifacts/run-1/input.png",
                provenance="local_private",
                source={},
            ),
            distribution="local",
        ),
        fixtures / "manifest.json",
    )

    assert corpus.cases[0].is_private is True
