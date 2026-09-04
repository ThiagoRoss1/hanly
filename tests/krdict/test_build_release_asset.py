"""The single command that produces one release asset from one source identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.krdict.build_release_asset import (
    RELEASE_MANIFEST_NAME,
    BuildError,
    build_release_asset,
    main,
)


def test_the_manifest_is_written_under_the_name_a_release_publishes() -> None:
    assert RELEASE_MANIFEST_NAME == "hanly-resources.json"


def test_a_missing_source_archive_fails_before_any_output_is_written(tmp_path: Path) -> None:
    output = tmp_path / "out"

    with pytest.raises(BuildError, match="does not exist"):
        build_release_asset(
            tmp_path / "absent.zip",
            output,
            resource_version="20260819-v1",
            source_date="2026-08-19",
            build_date="2026-08-25",
        )

    assert not output.exists()


@pytest.mark.parametrize("version", ["has space", "semi;colon", "../escape", ""])
def test_an_unsafe_resource_version_is_refused(tmp_path: Path, version: str) -> None:
    with pytest.raises(BuildError, match="resource version"):
        build_release_asset(
            tmp_path / "source.zip",
            tmp_path / "out",
            resource_version=version,
            source_date="2026-08-19",
            build_date="2026-08-25",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_date", "19-08-2026"), ("build_date", "2026-8-25"), ("source_date", "today")],
)
def test_a_malformed_date_is_refused_before_building(
    tmp_path: Path, field: str, value: str
) -> None:
    dates = {"source_date": "2026-08-19", "build_date": "2026-08-25", field: value}

    with pytest.raises(BuildError, match="must be YYYY-MM-DD"):
        build_release_asset(
            tmp_path / "source.zip",
            tmp_path / "out",
            resource_version="20260819-v1",
            source_date=dates["source_date"],
            build_date=dates["build_date"],
        )


def test_identity_is_validated_ahead_of_the_archive_check(tmp_path: Path) -> None:
    """A bad identity and a missing archive both apply; the identity is the one
    the operator can fix without re-reading the error twice."""

    with pytest.raises(BuildError, match="resource version"):
        build_release_asset(
            tmp_path / "absent.zip",
            tmp_path / "out",
            resource_version="bad version",
            source_date="2026-08-19",
            build_date="2026-08-25",
        )


def test_the_command_reports_a_failure_as_a_nonzero_exit(tmp_path: Path) -> None:
    code = main(
        [
            str(tmp_path / "absent.zip"),
            "--output-dir", str(tmp_path / "out"),
            "--resource-version", "20260819-v1",
            "--source-date", "2026-08-19",
        ]
    )

    assert code == 1


def test_the_build_date_defaults_to_today_so_a_new_build_needs_three_arguments() -> None:
    from tools.krdict.build_release_asset import _parser

    args = _parser().parse_args(
        ["archive.zip", "--resource-version", "20260819-v1", "--source-date", "2026-08-19"]
    )

    assert len(args.build_date) == 10
    assert args.output_dir == Path("data/generated")
