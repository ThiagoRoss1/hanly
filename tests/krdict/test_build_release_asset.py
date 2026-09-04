"""The single command that produces one release asset from one source identity."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from tests.hanly_fixtures.krdict import FIXTURE_XML
from tools.krdict.build_release_asset import (
    RELEASE_MANIFEST_NAME,
    BuildError,
    build_release_asset,
    main,
)


def _source_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "krdict-source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fixture.xml", FIXTURE_XML)
    return archive


def test_one_command_builds_validates_and_packages_under_one_identity(tmp_path: Path) -> None:
    """The three tools stay independently runnable, so what this command adds is
    a single identity across all of them and a manifest named the way a release
    publishes it -- neither of which a constant on its own would show."""

    output = tmp_path / "out"

    asset, manifest, report = build_release_asset(
        _source_archive(tmp_path),
        output,
        resource_version="20260819-v1",
        source_date="2026-08-19",
        build_date="2026-08-25",
    )

    assert manifest == output / RELEASE_MANIFEST_NAME == output / "hanly-resources.json"
    assert asset == output / "krdict-20260819-v1.sqlite3.zst"
    assert asset.is_file() and report.is_file()

    published = json.loads(manifest.read_text(encoding="utf-8"))
    validation = json.loads(report.read_text(encoding="utf-8"))

    krdict = published["resources"]["krdict"]

    assert validation["source_entry_count"] == 3
    assert krdict["asset_name"] == asset.name
    assert krdict["version"] == "20260819-v1"
    assert krdict["source_date"] == "2026-08-19"
    assert krdict["expected_entry_count"] == 3


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
