"""Build, validate, and package one KRDICT release asset in a single command.

The three underlying tools stay independently runnable; this only removes the
chance of building with one source identity and packaging with another, which
is the mistake that produces a manifest a release will reject.

Everything lands under one output directory, named the way ``release.yml``
expects, so the result can be attached to a GitHub Release unchanged.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.krdict`` cannot be imported without it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.krdict.build_seed import main as build_seed_main
from tools.krdict.package_resource import main as package_resource_main
from tools.krdict.validate_seed import main as validate_seed_main

#: Every underlying tool exposes the same ``main(argv) -> exit code`` entry.
StepRunner = Callable[[Sequence[str]], int]

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

#: The manifest asset name a release publishes. Producing it here means the
#: file can be uploaded without being renamed by hand.
RELEASE_MANIFEST_NAME = "hanly-resources.json"


class BuildError(RuntimeError):
    """Raised when the requested resource identity cannot be built."""


def _validate_identity(resource_version: str, source_date: str, build_date: str) -> None:
    if not VERSION_PATTERN.fullmatch(resource_version):
        raise BuildError("resource version may contain only letters, digits, dot, dash, underscore")
    for label, value in (("source date", source_date), ("build date", build_date)):
        if not DATE_PATTERN.fullmatch(value):
            raise BuildError(f"{label} must be YYYY-MM-DD")


def _run(step: str, runner: StepRunner, argv: list[str]) -> None:
    code = runner(argv)
    if code != 0:
        raise BuildError(f"{step} failed with exit code {code}")


def build_release_asset(
    archive: Path,
    output_directory: Path,
    *,
    resource_version: str,
    source_date: str,
    build_date: str,
    expect_entries: int | None = None,
    expect_senses: int | None = None,
    expect_sanitized_bytes: int | None = None,
) -> tuple[Path, Path, Path]:
    """Return the compressed asset, release manifest, and validation report."""

    _validate_identity(resource_version, source_date, build_date)
    if not archive.is_file():
        raise BuildError(f"source archive does not exist: {archive}")

    output_directory.mkdir(parents=True, exist_ok=True)
    database = output_directory / "krdict.sqlite3"
    asset = output_directory / f"krdict-{resource_version}.sqlite3.zst"
    manifest = output_directory / RELEASE_MANIFEST_NAME
    report = output_directory / f"validation-{resource_version}.json"

    _run(
        "build",
        build_seed_main,
        [
            str(archive),
            "--output", str(database),
            "--source-date", source_date,
            "--resource-version", resource_version,
            "--build-date", build_date,
        ],
    )

    validate_argv = [str(database), "--source", str(archive), "--report", str(report)]
    for flag, value in (
        ("--expect-entries", expect_entries),
        ("--expect-senses", expect_senses),
        ("--expect-sanitized-bytes", expect_sanitized_bytes),
    ):
        if value is not None:
            validate_argv.extend([flag, str(value)])
    _run("validation", validate_seed_main, validate_argv)

    _run(
        "packaging",
        package_resource_main,
        [
            str(database),
            "--output", str(asset),
            "--resource-version", resource_version,
            "--source-date", source_date,
            "--manifest", str(manifest),
        ],
    )
    return asset, manifest, report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, validate, and package a KRDICT release asset in one step"
    )
    parser.add_argument("source", type=Path, help="the official KRDICT source ZIP")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/generated"),
        help="directory the database, asset, manifest, and report are written to",
    )
    parser.add_argument("--resource-version", required=True, help="for example 20260819-v1")
    parser.add_argument("--source-date", required=True, help="the date the archive was published")
    parser.add_argument(
        "--build-date",
        default=date.today().isoformat(),
        help="pin this to reproduce an existing release byte-for-byte",
    )
    parser.add_argument("--expect-entries", type=int)
    parser.add_argument("--expect-senses", type=int)
    parser.add_argument("--expect-sanitized-bytes", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Produce the two files a release needs from one source archive."""

    args = _parser().parse_args(argv)
    try:
        asset, manifest, report = build_release_asset(
            args.source,
            args.output_dir,
            resource_version=args.resource_version,
            source_date=args.source_date,
            build_date=args.build_date,
            expect_entries=args.expect_entries,
            expect_senses=args.expect_senses,
            expect_sanitized_bytes=args.expect_sanitized_bytes,
        )
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print("\nUpload these two files to the GitHub Release:")
    print(f"  {asset}")
    print(f"  {manifest}")
    print(f"\nValidation report (keep, do not upload): {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
