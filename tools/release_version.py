"""Resolve the product version and prove a release tag agrees with it.

``hanly-app`` is the released product, so its ``[project].version`` is the one
authoritative version and ``hanly`` carries the same value. The version is read
back through installed package metadata rather than by parsing TOML, so this
tool needs no dependency the repository does not already install.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from importlib import metadata

PRODUCT_PACKAGE = "hanly-app"
ENGINE_PACKAGE = "hanly"
TAG_PREFIX = "v"

# V1 releases are plain ``MAJOR.MINOR.PATCH``. Pre-release and local segments
# are deliberately unsupported until a release needs them.
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseVersionError(RuntimeError):
    """Raised when the product version and a release tag do not agree."""


def product_version() -> str:
    """Return the authoritative product version from installed metadata."""

    try:
        version = metadata.version(PRODUCT_PACKAGE)
    except metadata.PackageNotFoundError as error:
        raise ReleaseVersionError(
            f"{PRODUCT_PACKAGE} is not installed; install the repository packages first"
        ) from error

    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseVersionError(
            f"{PRODUCT_PACKAGE} version {version!r} must be MAJOR.MINOR.PATCH"
        )
    return version


def engine_version() -> str:
    """Return the engine version, which must track the product version."""

    try:
        return metadata.version(ENGINE_PACKAGE)
    except metadata.PackageNotFoundError as error:
        raise ReleaseVersionError(f"{ENGINE_PACKAGE} is not installed") from error


def tag_for(version: str) -> str:
    """Return the Git tag that publishes the given version."""

    return f"{TAG_PREFIX}{version}"


def version_for_tag(tag: str) -> str:
    """Return the version a release tag names, rejecting any other shape."""

    candidate = tag.strip()
    if not candidate.startswith(TAG_PREFIX):
        raise ReleaseVersionError(f"release tag {tag!r} must start with {TAG_PREFIX!r}")

    version = candidate[len(TAG_PREFIX) :]
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseVersionError(
            f"release tag {tag!r} must be {TAG_PREFIX}MAJOR.MINOR.PATCH"
        )
    return version


def verify_tag(tag: str) -> str:
    """Return the released version, or explain exactly how the tag disagrees."""

    tagged = version_for_tag(tag)
    current = product_version()
    if tagged != current:
        raise ReleaseVersionError(
            f"release tag {tag!r} does not match the {PRODUCT_PACKAGE} version "
            f"{current!r}; expected {tag_for(current)!r}. Edit the version in "
            f"packages/hanly-app/pyproject.toml or create the matching tag."
        )

    installed_engine = engine_version()
    if installed_engine != current:
        raise ReleaseVersionError(
            f"{ENGINE_PACKAGE} version {installed_engine!r} does not match "
            f"{PRODUCT_PACKAGE} version {current!r}; one product version covers both packages"
        )
    return current


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print or verify the Hanly release version")
    parser.add_argument(
        "--tag",
        help="release tag to verify against the product version (for example v0.1.0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print the product version, verifying it against ``--tag`` when given."""

    args = _parser().parse_args(argv)
    try:
        version = product_version() if args.tag is None else verify_tag(args.tag)
    except ReleaseVersionError as error:
        print(f"error: {error}")
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
