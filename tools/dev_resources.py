"""Local-only resource preparation for the developer alpha.

This rig is repository tooling and does not ship: every path it resolves is
relative to this checkout. The development path owns one generated artifact,
the gitignored mini KRDICT SQLite database built from the committed XML
fixture; reusable database construction stays in ``hanly.krdict_build``. OCR
model directories remain user-provided resources, so this module validates
their presence and never tries to acquire them.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hanly.krdict_build import build_krdict_database


class DevResourceError(RuntimeError):
    """Raised when local developer resources cannot be prepared."""


DatabaseBuilder = Callable[[Path, Path], Path]


@dataclass(frozen=True, slots=True)
class DevResourcePreparation:
    """Paths used by the prepared development runtime."""

    config_path: Path
    source_config_path: Path
    krdict_source: Path
    krdict_database: Path
    krdict_built: bool
    generated_config_path: Path | None = None

    def cleanup(self) -> None:
        """Remove an ephemeral fallback config, if model discovery created one."""

        if self.generated_config_path is not None:
            self.generated_config_path.unlink(missing_ok=True)


def default_dev_config_path() -> Path:
    """Return the repository-owned development runtime configuration path."""

    return _repository_root() / "resources" / "dev" / "runtime.json"


def prepare_dev_resources(
    config_path: str | Path | None = None,
    *,
    source_path: str | Path | None = None,
    database_builder: DatabaseBuilder = build_krdict_database,
) -> DevResourcePreparation:
    """Prepare the mini dictionary and locate local OCR model directories.

    A missing configured KRDICT database is generated from the committed XML
    source. A config whose model directories are empty or missing may use model
    files already present in the standard PaddleX cache; no remote acquisition
    is attempted and no caller-owned config is edited.
    """

    path = Path(config_path) if config_path is not None else default_dev_config_path()
    path = path.expanduser().resolve()
    raw = _load_config(path)
    resources = _mapping_value(raw, "resources")

    krdict_path = _resource_path(resources.get("krdict"), path.parent, "krdict")
    configured_source = (
        Path(source_path).expanduser().resolve()
        if source_path is not None
        else _default_source_path(path)
    )
    built = _ensure_krdict_database(krdict_path, configured_source, database_builder)

    model_paths = (
        _find_model_directory(
            resources.get("paddle_detection_model"), raw, path.parent, "detection"
        ),
        _find_model_directory(
            resources.get("paddle_recognition_model"), raw, path.parent, "recognition"
        ),
    )

    effective_config_path = path
    generated_config_path: Path | None = None
    configured_paths = (
        _resource_path(resources.get("paddle_detection_model"), path.parent, "detection"),
        _resource_path(resources.get("paddle_recognition_model"), path.parent, "recognition"),
    )
    if configured_paths != model_paths:
        effective_config_path = _write_effective_config(
            raw, path, model_paths[0], model_paths[1], krdict_path
        )
        generated_config_path = effective_config_path

    return DevResourcePreparation(
        config_path=effective_config_path,
        source_config_path=path,
        krdict_source=configured_source,
        krdict_database=krdict_path,
        krdict_built=built,
        generated_config_path=generated_config_path,
    )


def _ensure_krdict_database(
    database_path: Path,
    source_path: Path,
    database_builder: DatabaseBuilder,
) -> bool:
    if database_path.exists() and not database_path.is_file():
        raise DevResourceError(f"development KRDICT path is not a file: {database_path}")
    if database_path.is_file():
        return False
    if not source_path.is_file():
        raise DevResourceError(
            "development KRDICT database is missing and its in-repository "
            f"XML source was not found: {source_path}"
        )

    try:
        database_builder(source_path, database_path)
    except Exception as error:
        raise DevResourceError(
            f"could not build development KRDICT database at {database_path}: {error}"
        ) from error
    if not database_path.is_file():
        raise DevResourceError(
            f"KRDICT builder returned without creating its database: {database_path}"
        )
    return True


def _find_model_directory(
    value: object,
    config: Mapping[str, Any],
    root: Path,
    kind: str,
) -> Path:
    configured_path = _resource_path(value, root, f"paddle_{kind}_model")
    if _has_model_contents(configured_path):
        return configured_path

    model_name = _paddle_model_name(config, kind)
    candidates = _standard_model_directories(model_name)
    for candidate in candidates:
        if _has_model_contents(candidate):
            return candidate

    searched = ", ".join(str(candidate) for candidate in (configured_path, *candidates))
    raise DevResourceError(
        f"PaddleOCR {kind} model directory is unavailable: {configured_path}. "
        f"No local model files were found in: {searched}. "
        "Install or copy the named PaddleOCR model locally; dev startup does "
        "not download models."
    )


def _has_model_contents(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _paddle_model_name(config: Mapping[str, Any], kind: str) -> str:
    paddle = _mapping_value(config, "paddle")
    field = f"text_{kind}_model_name"
    value = paddle.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DevResourceError(f"development runtime config requires paddle.{field}")
    return value


def _standard_model_directories(model_name: str) -> tuple[Path, ...]:
    roots: list[Path] = []
    configured_home = os.environ.get("PADDLEX_HOME")
    if configured_home:
        home = Path(configured_home).expanduser()
        roots.extend((home / "official_models", home))
    roots.append(Path.home() / ".paddlex" / "official_models")

    candidates: list[Path] = []
    for root in roots:
        candidate = (root / model_name).resolve()
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _write_effective_config(
    raw: Mapping[str, Any],
    source_path: Path,
    detection_path: Path,
    recognition_path: Path,
    krdict_path: Path,
) -> Path:
    """Write a disposable config so model discovery never edits user files."""

    payload = json.loads(json.dumps(raw))
    resources = cast(dict[str, Any], payload["resources"])
    paddle = cast(dict[str, Any], payload["paddle"])
    detection = _effective_resource(resources, "paddle_detection_model")
    recognition = _effective_resource(resources, "paddle_recognition_model")
    krdict = _effective_resource(resources, "krdict")
    detection["path"] = str(detection_path)
    recognition["path"] = str(recognition_path)
    krdict["path"] = str(krdict_path)
    paddle["text_detection_model_dir"] = str(detection_path)
    paddle["text_recognition_model_dir"] = str(recognition_path)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix="hanly-dev-runtime-", suffix=".json"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (OSError, TypeError, ValueError) as error:
        if descriptor != -1:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise DevResourceError(
            f"could not create disposable runtime config for {source_path}: {error}"
        ) from error
    return temporary_path


def _effective_resource(resources: dict[str, Any], resource_id: str) -> dict[str, Any]:
    value = resources.get(resource_id)
    if isinstance(value, str):
        normalized = {"path": value}
        resources[resource_id] = normalized
        return normalized
    if isinstance(value, dict):
        return value
    raise DevResourceError(
        f"development runtime config requires resources.{resource_id} to be an object"
    )


def _repository_root() -> Path:
    """Resolve the repository root that owns this developer rig."""

    return Path(__file__).resolve().parents[1]


def _default_source_path(config_path: Path) -> Path:
    repository_source = (
        _repository_root() / "resources" / "dev" / "krdict" / "krdict-mini.xml"
    )
    if repository_source.is_file():
        return repository_source
    return config_path.parent / "krdict" / "krdict-mini.xml"


def _load_config(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevResourceError(
            f"could not load development runtime config {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise DevResourceError(f"development runtime config must be a JSON object: {path}")
    return value


def _mapping_value(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    field = value.get(field_name)
    if not isinstance(field, Mapping):
        raise DevResourceError(
            f"development runtime config requires an object at {field_name}"
        )
    return field


def _resource_path(value: object, root: Path, resource_id: str) -> Path:
    raw_path: object
    if isinstance(value, str):
        raw_path = value
    elif isinstance(value, Mapping):
        raw_path = value.get("path")
    else:
        raw_path = None
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise DevResourceError(
            f"development runtime config requires resources.{resource_id}.path"
        )
    path = Path(raw_path).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


__all__ = [
    "DatabaseBuilder",
    "DevResourceError",
    "DevResourcePreparation",
    "default_dev_config_path",
    "prepare_dev_resources",
]
