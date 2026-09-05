"""The tag commit's own package identity, read as data.

Both halves of the release read this, and the publishing half reads it again
after approval, so the parsing has to refuse anything it cannot vouch for
rather than return a plausible-looking value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The tool defers this import for 3.10; the parsing it guards is what is tested.
pytest.importorskip("tomllib")

from tools.tagged_metadata import (  # noqa: E402
    APPLICATION_PROJECT,
    ENGINE_PROJECT,
    TaggedMetadataError,
    main,
    read_metadata,
)

_APPLICATION = """
[project]
name = "hanly-app"
version = "0.1.0"
dependencies = ["hanly==0.1.0", "zstandard>=0.23,<1"]

[project.optional-dependencies]
runtime = ["hanly[concrete]==0.1.0", "PyQt6>=6.7,<7"]
"""

_ENGINE = """
[project]
name = "hanly"
version = "0.1.0"
dependencies = []
"""


def _tagged(tmp_path: Path, *, application: str = _APPLICATION, engine: str = _ENGINE) -> Path:
    for path, text in ((APPLICATION_PROJECT, application), (ENGINE_PROJECT, engine)):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


def test_the_four_values_the_release_tag_has_to_agree_with(tmp_path: Path) -> None:
    metadata = read_metadata(_tagged(tmp_path))

    assert metadata.app_version == "0.1.0"
    assert metadata.engine_version == "0.1.0"
    assert metadata.app_hanly_pin == "hanly==0.1.0"
    assert metadata.app_hanly_concrete_pin == "hanly[concrete]==0.1.0"


def test_the_record_is_tab_separated_for_a_shell_read(tmp_path: Path) -> None:
    line = read_metadata(_tagged(tmp_path)).as_line()

    assert line.split("\t") == ["0.1.0", "0.1.0", "hanly==0.1.0", "hanly[concrete]==0.1.0"]


def test_a_missing_package_file_is_an_error_not_a_default(tmp_path: Path) -> None:
    (tmp_path / APPLICATION_PROJECT).parent.mkdir(parents=True)
    (tmp_path / APPLICATION_PROJECT).write_text(_APPLICATION, encoding="utf-8")

    with pytest.raises(TaggedMetadataError, match="cannot read packages/hanly/pyproject.toml"):
        read_metadata(tmp_path)


def test_unparseable_tagged_metadata_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TaggedMetadataError, match="invalid TOML"):
        read_metadata(_tagged(tmp_path, engine="[project\nname ="))


@pytest.mark.parametrize(
    ("application", "message"),
    [
        ('[project]\nname = "hanly-app"\ndependencies = []\n', "no string project.version"),
        (
            '[project]\nversion = 1\ndependencies = []\n',
            "no string project.version",
        ),
        (
            '[project]\nversion = "0.1.0"\ndependencies = ["hanly==0.1.0", "hanly==0.2.0"]\n'
            '[project.optional-dependencies]\nruntime = ["hanly[concrete]==0.1.0"]\n',
            "exactly one project.dependencies hanly pin",
        ),
        (
            '[project]\nversion = "0.1.0"\ndependencies = ["zstandard"]\n'
            '[project.optional-dependencies]\nruntime = ["hanly[concrete]==0.1.0"]\n',
            "exactly one project.dependencies hanly pin",
        ),
        (
            '[project]\nversion = "0.1.0"\ndependencies = ["hanly==0.1.0"]\n',
            "optional-dependencies.runtime must be a list",
        ),
        (
            '[project]\nversion = "0.1.0"\ndependencies = ["hanly==0.1.0"]\n'
            '[project.optional-dependencies]\nruntime = ["PyQt6"]\n',
            "exactly one optional-dependencies.runtime hanly pin",
        ),
    ],
)
def test_metadata_that_cannot_be_vouched_for_is_refused(
    tmp_path: Path, application: str, message: str
) -> None:
    with pytest.raises(TaggedMetadataError, match=message):
        read_metadata(_tagged(tmp_path, application=application))


def test_a_tab_in_a_value_would_split_the_record_and_is_refused(tmp_path: Path) -> None:
    """The caller splits on tabs, so a value carrying one becomes two values."""

    application = (
        '[project]\nversion = "0.1.0"\ndependencies = ["hanly==0.1.0\\tinjected"]\n'
        '[project.optional-dependencies]\nruntime = ["hanly[concrete]==0.1.0"]\n'
    )

    with pytest.raises(TaggedMetadataError, match="forbidden control character"):
        read_metadata(_tagged(tmp_path, application=application))


def test_the_command_prints_one_record_and_reports_failure_as_an_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(_tagged(tmp_path))]) == 0
    assert capsys.readouterr().out.strip().split("\t")[0] == "0.1.0"

    assert main([str(tmp_path / "absent")]) == 1
    assert "cannot read" in capsys.readouterr().err
