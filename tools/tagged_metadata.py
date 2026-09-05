"""Read the product identity out of a tag commit's own package metadata.

The release lane fetches the two ``pyproject.toml`` files belonging to the exact
tag commit and reads them here, as data. Both halves of the release do this: the
staging half before it creates a draft, and the publishing half again after
approval, because nothing staged earlier is trusted by the half that publishes.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APPLICATION_PROJECT = "packages/hanly-app/pyproject.toml"
ENGINE_PROJECT = "packages/hanly/pyproject.toml"
PROJECTS = (APPLICATION_PROJECT, ENGINE_PROJECT)


class TaggedMetadataError(RuntimeError):
    """Raised when a tag commit's package metadata is not readable or canonical."""


@dataclass(frozen=True)
class TaggedMetadata:
    """The four values a release tag has to agree with."""

    app_version: str
    engine_version: str
    app_hanly_pin: str
    app_hanly_concrete_pin: str

    def as_line(self) -> str:
        """Render the values for a shell ``read``, which splits on tabs."""

        return "\t".join(
            (
                self.app_version,
                self.engine_version,
                self.app_hanly_pin,
                self.app_hanly_concrete_pin,
            )
        )


def _read_project(root: Path, path: str) -> dict[str, Any]:
    # ``tomllib`` arrived in 3.11 and the repository still targets 3.10. The
    # release runner is 3.13, so the import is deferred rather than the whole
    # module being unimportable on the oldest supported interpreter.
    if sys.version_info < (3, 11):  # pragma: no cover - the release lane pins Python 3.13
        raise TaggedMetadataError("reading tagged metadata needs Python 3.11 or newer")
    loads = getattr(importlib.import_module("tomllib"), "loads")

    try:
        text = (root / path).read_text(encoding="utf-8")
    except OSError as error:
        raise TaggedMetadataError(
            f"cannot read {path} from the exact tag commit: {error}"
        ) from error
    try:
        payload = loads(text)
    except ValueError as error:
        raise TaggedMetadataError(f"invalid TOML in {path}: {error}") from error
    if not isinstance(payload, dict):
        raise TaggedMetadataError(f"{path} did not contain a TOML table")
    return payload


def _project_version(payload: dict[str, Any], path: str) -> str:
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise TaggedMetadataError(f"{path} has no string project.version")
    return project["version"]


def _single_hanly_pin(values: Any, label: str) -> str:
    if not isinstance(values, list):
        raise TaggedMetadataError(f"{label} must be a list")
    pins = [value for value in values if isinstance(value, str) and value.startswith("hanly")]
    if len(pins) != 1:
        raise TaggedMetadataError(f"the tagged app must contain exactly one {label} hanly pin")
    return pins[0]


def read_metadata(root: Path) -> TaggedMetadata:
    """Return the tagged identity from package files already fetched into ``root``."""

    app = _read_project(root, APPLICATION_PROJECT)
    engine = _read_project(root, ENGINE_PROJECT)
    project = app["project"]
    optional = project.get("optional-dependencies")

    metadata = TaggedMetadata(
        app_version=_project_version(app, APPLICATION_PROJECT),
        engine_version=_project_version(engine, ENGINE_PROJECT),
        app_hanly_pin=_single_hanly_pin(project.get("dependencies", []), "project.dependencies"),
        app_hanly_concrete_pin=_single_hanly_pin(
            optional.get("runtime") if isinstance(optional, dict) else None,
            "optional-dependencies.runtime",
        ),
    )

    # The caller splits these on tabs; a value carrying one would silently
    # become two, and a newline would end the record early.
    for value in (
        metadata.app_version,
        metadata.engine_version,
        metadata.app_hanly_pin,
        metadata.app_hanly_concrete_pin,
    ):
        if "\t" in value or "\n" in value:
            raise TaggedMetadataError("tagged metadata contains a forbidden control character")
    return metadata


def main(argv: Sequence[str] | None = None) -> int:
    """Print the four tagged values as one tab-separated record."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="directory holding the fetched package files")
    args = parser.parse_args(argv)

    try:
        print(read_metadata(args.root).as_line())
    except TaggedMetadataError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APPLICATION_PROJECT",
    "ENGINE_PROJECT",
    "PROJECTS",
    "TaggedMetadata",
    "TaggedMetadataError",
    "main",
    "read_metadata",
]
