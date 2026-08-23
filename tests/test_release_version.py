"""Validation for the single product version and the tag that publishes it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.release_version import (
    ENGINE_PACKAGE,
    PRODUCT_PACKAGE,
    ReleaseVersionError,
    engine_version,
    main,
    product_version,
    tag_for,
    verify_tag,
    version_for_tag,
)

PACKAGES = Path(__file__).parents[1] / "packages"

#: `[project] version = "..."` without requiring a TOML parser on Python 3.10.
_DECLARED_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _declared_version(package: str) -> str:
    text = (PACKAGES / package / "pyproject.toml").read_text(encoding="utf-8")
    match = _DECLARED_VERSION.search(text)
    assert match is not None, f"{package} declares no version"
    return match.group(1)


def test_one_product_version_covers_both_packages() -> None:
    assert _declared_version("hanly") == _declared_version("hanly-app")
    assert product_version() == engine_version()


def test_installed_metadata_matches_the_declared_source_of_truth() -> None:
    """A stale editable install would let the release gate read the wrong version."""

    declared = _declared_version("hanly-app")
    assert product_version() == declared, (
        f"{PRODUCT_PACKAGE} metadata reports {product_version()} but "
        f"pyproject.toml declares {declared}; reinstall the editable packages"
    )


def test_the_application_pins_the_engine_to_the_same_version() -> None:
    app = (PACKAGES / "hanly-app" / "pyproject.toml").read_text(encoding="utf-8")
    version = _declared_version("hanly-app")

    assert f'"{ENGINE_PACKAGE}=={version}"' in app
    assert f'"{ENGINE_PACKAGE}[concrete]=={version}"' in app


def test_a_tag_matching_the_product_version_is_accepted() -> None:
    version = product_version()

    assert tag_for(version) == f"v{version}"
    assert verify_tag(f"v{version}") == version
    assert version_for_tag(f"v{version}") == version


def test_a_tag_naming_a_different_version_is_rejected() -> None:
    major, minor, patch = product_version().split(".")
    other = f"v{major}.{minor}.{int(patch) + 1}"

    with pytest.raises(ReleaseVersionError, match="does not match"):
        verify_tag(other)


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0.1", "release-0.1.0", "v0.1.0rc1", "v"])
def test_only_a_plain_v_major_minor_patch_tag_is_a_release_tag(tag: str) -> None:
    with pytest.raises(ReleaseVersionError):
        version_for_tag(tag)


def test_the_cli_prints_the_version_and_fails_loudly_on_a_mismatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    version = product_version()

    assert main([]) == 0
    assert capsys.readouterr().out.strip() == version

    assert main(["--tag", f"v{version}"]) == 0
    assert capsys.readouterr().out.strip() == version

    assert main(["--tag", "v99.99.99"]) == 1
    assert "does not match" in capsys.readouterr().out
