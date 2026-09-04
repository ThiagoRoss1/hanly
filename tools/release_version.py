"""Resolve Hanly release versions in two explicit modes.

The default mode reads installed package metadata. Supplying all four metadata
options enables inert supplied-metadata mode: values already read by the caller
are verified against the tag without inspecting installed packages or parsing
TOML.
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


def verify_tag_metadata(
    tag: str,
    *,
    engine_version: str,
    app_version: str,
    app_hanly_pin: str,
    app_hanly_concrete_pin: str,
) -> str:
    """Verify a tag against project metadata supplied as inert values.

    This keeps tag-tree parsing outside the version authority: callers can read
    metadata as data and pass the resulting values here without installing or
    executing that tree.
    """

    tagged = version_for_tag(tag)
    expected_pin = f"{ENGINE_PACKAGE}=={tagged}"
    expected_concrete_pin = f"{ENGINE_PACKAGE}[concrete]=={tagged}"

    values = (
        ("engine version", engine_version, tagged),
        ("app version", app_version, tagged),
        ("app hanly pin", app_hanly_pin, expected_pin),
        ("app hanly concrete pin", app_hanly_concrete_pin, expected_concrete_pin),
    )
    for label, actual, expected in values:
        if actual != expected:
            raise ReleaseVersionError(
                f"{label} {actual!r} does not match release tag {tag!r}; "
                f"expected {expected!r}"
            )
    return tagged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Print or verify the Hanly release version. By default, use installed "
            "package metadata; with all four metadata options, verify supplied "
            "inert values without reading installed metadata."
        )
    )
    parser.add_argument(
        "--tag",
        help=(
            "release tag to verify (for example v0.1.0); default mode uses installed "
            "metadata, while metadata mode uses supplied inert values"
        ),
    )
    parser.add_argument(
        "--engine-version",
        help="inert engine project version for data-oriented tag verification",
    )
    parser.add_argument(
        "--app-version",
        help="inert app project version for data-oriented tag verification",
    )
    parser.add_argument(
        "--app-hanly-pin",
        help="inert app dependency pin (for example hanly==0.1.0)",
    )
    parser.add_argument(
        "--app-hanly-concrete-pin",
        help="inert app runtime pin (for example hanly[concrete]==0.1.0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print or verify a version using installed or supplied inert metadata."""

    args = _parser().parse_args(argv)
    try:
        metadata_values = {
            "--engine-version": args.engine_version,
            "--app-version": args.app_version,
            "--app-hanly-pin": args.app_hanly_pin,
            "--app-hanly-concrete-pin": args.app_hanly_concrete_pin,
        }
        if any(value is not None for value in metadata_values.values()):
            if args.tag is None:
                raise ReleaseVersionError("--tag is required with metadata mode")
            missing = [name for name, value in metadata_values.items() if value is None]
            if missing:
                raise ReleaseVersionError(
                    "metadata mode requires " + ", ".join(missing)
                )
            version = verify_tag_metadata(
                args.tag,
                engine_version=args.engine_version,
                app_version=args.app_version,
                app_hanly_pin=args.app_hanly_pin,
                app_hanly_concrete_pin=args.app_hanly_concrete_pin,
            )
        else:
            version = product_version() if args.tag is None else verify_tag(args.tag)
    except ReleaseVersionError as error:
        print(f"error: {error}")
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
