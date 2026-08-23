"""Local resource discovery and validation for the Hanly engine.

``ResourceManager`` deliberately stops at understanding resources already
present on disk.  It does not download, update, or construct providers.  A
small manifest made of :class:`ResourceSpec` values gives composition code a
portable way to describe model, dictionary, and asset resources and tests a
portable way to point those resources at temporary files.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .contracts import ResourceMetadata, ResourceStatus
from .errors import HanlyError
from .krdict_build import (
    KRDICT_SCHEMA_MARKER,
    KRDICT_SCHEMA_NAME,
    KRDICT_SCHEMA_VERSION,
)


class ResourceManagerError(HanlyError):
    """Base error for resource-manager API failures."""


class ResourceUnavailableError(ResourceManagerError):
    """Raised when composition asks for a resource that is not valid."""


@dataclass(frozen=True)
class SchemaSpec:
    """The local schema contract expected for a SQLite resource.

    ``metadata`` describes rows in a conventional ``metadata(key, value)``
    table.  A schema name or marker also requires that table so the identity
    can be checked rather than inferred from the filename.
    """

    name: str
    version: int | str
    marker: str | None = None
    required_tables: tuple[str, ...] = ()
    required_columns: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    required_indexes: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    user_version: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("schema name must not be empty")
        if not str(self.version).strip():
            raise ValueError("schema version must not be empty")
        object.__setattr__(self, "required_tables", tuple(self.required_tables))
        object.__setattr__(self, "required_indexes", tuple(self.required_indexes))
        object.__setattr__(
            self,
            "required_columns",
            MappingProxyType(
                {table: tuple(columns) for table, columns in self.required_columns.items()}
            ),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


KRDICT_SCHEMA = SchemaSpec(
    name=KRDICT_SCHEMA_NAME,
    version=KRDICT_SCHEMA_VERSION,
    marker=KRDICT_SCHEMA_MARKER,
    required_tables=("metadata", "entries", "definitions"),
    required_columns={
        "metadata": ("key", "value"),
        "entries": ("id", "headword", "part_of_speech"),
        "definitions": ("entry_id", "ordinal", "definition"),
    },
    required_indexes=("idx_entries_headword",),
    metadata={
        "schema_name": KRDICT_SCHEMA_NAME,
        "schema_version": str(KRDICT_SCHEMA_VERSION),
        "schema_marker": KRDICT_SCHEMA_MARKER,
        "source_language": "ko",
        "target_language": "en",
    },
    user_version=KRDICT_SCHEMA_VERSION,
)


@dataclass(frozen=True)
class ResourceSpec:
    """Manifest entry describing one local resource.

    ``version`` is the expected version.  A resource can provide its installed
    version through ``installed_version`` (useful for an application manifest),
    a small text ``version_file``, or a schema's metadata.  If none is given,
    the expected version is treated as the installed version because ordinary
    opaque files have no universal embedded-version format.

    ``compatible_with`` and ``requires`` map another resource id to the
    version it must expose.  ``requires`` is an alias useful to callers that
    think in dependency terms; both mappings are checked.
    """

    resource_id: str
    path: str | os.PathLike[str]
    version: str | None = None
    checksum: str | None = None
    schema: SchemaSpec | None = None
    version_file: str | os.PathLike[str] | None = None
    installed_version: str | None = None
    expected_version: str | None = None
    kind: str = "file"
    configuration: Mapping[str, Any] = field(default_factory=dict)
    compatible_with: Mapping[str, str] = field(default_factory=dict)
    requires: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValueError("resource id must not be empty")
        if self.kind not in {"file", "directory", "sqlite", "krdict"}:
            raise ValueError("resource kind must be file, directory, sqlite, or krdict")
        if self.kind == "krdict" and self.schema is None:
            object.__setattr__(self, "schema", KRDICT_SCHEMA)
        object.__setattr__(self, "path", Path(self.path).expanduser())
        if self.version_file is not None:
            object.__setattr__(self, "version_file", Path(self.version_file).expanduser())
        object.__setattr__(self, "configuration", MappingProxyType(dict(self.configuration)))
        object.__setattr__(self, "compatible_with", MappingProxyType(dict(self.compatible_with)))
        object.__setattr__(self, "requires", MappingProxyType(dict(self.requires)))

    @property
    def required_version(self) -> str | None:
        """Return the expected version, honoring the explicit alias."""

        return self.expected_version if self.expected_version is not None else self.version


class ResourceManifest:
    """An immutable, id-indexed collection of resource specifications."""

    def __init__(self, specs: Iterable[ResourceSpec] | Mapping[str, ResourceSpec]) -> None:
        values = tuple(specs.values()) if isinstance(specs, Mapping) else tuple(specs)
        by_id: dict[str, ResourceSpec] = {}
        for spec in values:
            if not isinstance(spec, ResourceSpec):
                raise TypeError("resource manifest entries must be ResourceSpec values")
            if spec.resource_id in by_id:
                raise ValueError(f"duplicate resource id: {spec.resource_id}")
            by_id[spec.resource_id] = spec
        self._specs = values
        self._by_id = MappingProxyType(by_id)

    @property
    def specs(self) -> tuple[ResourceSpec, ...]:
        return self._specs

    def __iter__(self) -> Iterator[ResourceSpec]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __getitem__(self, resource_id: str) -> ResourceSpec:
        return self._by_id[resource_id]


@dataclass(frozen=True)
class ValidatedResource:
    """Composition-facing details for a valid resource."""

    metadata: ResourceMetadata
    path: Path
    configuration: Mapping[str, Any]
    diagnostics: tuple[str, ...] = ()


class ResourceManager:
    """Locate and validate resources from a local manifest.

    Validation is explicit and repeatable: ``validate`` performs a fresh local
    scan and returns a resource-id keyed copy of normalized metadata.  Paths
    and configuration are exposed only through accessors that require
    ``ResourceStatus.VALID``.
    """

    def __init__(
        self,
        manifest: ResourceManifest | Iterable[ResourceSpec],
        *,
        base_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.manifest = (
            manifest if isinstance(manifest, ResourceManifest) else ResourceManifest(manifest)
        )
        self._base_path = Path(base_path).expanduser().resolve() if base_path is not None else None
        self._reject_unresolvable_paths()
        self._metadata: dict[str, ResourceMetadata] = {}
        self._validated: dict[str, ValidatedResource] = {}
        self._diagnostics: dict[str, tuple[str, ...]] = {}

    @property
    def base_path(self) -> Path | None:
        """Return the absolute base used to resolve relative manifest paths."""

        return self._base_path

    def _reject_unresolvable_paths(self) -> None:
        """Fail fast on relative manifest paths that have no base to resolve from.

        Checked here rather than during ``validate`` so the manifest is either
        well formed or refused outright, and a single bad entry cannot abort the
        scan of every other resource.
        """

        if self._base_path is not None:
            return
        offenders: list[str] = []
        for spec in self.manifest:
            fields = [("resource path", spec.path)]
            if spec.version_file is not None:
                fields.append(("version_file", spec.version_file))
            offenders.extend(
                f"{spec.resource_id} {field_name} {Path(value)}"
                for field_name, value in fields
                if not Path(value).is_absolute()
            )
        if offenders:
            raise ResourceManagerError(
                "relative manifest paths require a ResourceManager base_path: "
                + "; ".join(offenders)
            )

    def validate(self) -> dict[str, ResourceMetadata]:
        """Validate all manifest entries and return normalized metadata.

        Every resource problem is reported as status and diagnostics; this does
        not raise for resource conditions.  A manifest that cannot be resolved
        at all is refused when the manager is constructed instead.
        """

        metadata: dict[str, ResourceMetadata] = {}
        diagnostics: dict[str, tuple[str, ...]] = {}
        observed_versions: dict[str, str] = {}
        resolved_paths: dict[str, Path] = {}

        for spec in self.manifest:
            (
                resource_metadata,
                resource_diagnostics,
                observed_version,
                resolved_path,
            ) = self._validate_spec(spec)
            metadata[spec.resource_id] = resource_metadata
            diagnostics[spec.resource_id] = resource_diagnostics
            resolved_paths[spec.resource_id] = resolved_path
            if observed_version is not None:
                observed_versions[spec.resource_id] = observed_version

        # Compatibility is checked after each resource has been inspected so a
        # dictionary can depend on a model that appears later in the manifest.
        for spec in self.manifest:
            if metadata[spec.resource_id].status is ResourceStatus.MISSING:
                continue
            requirements = dict(spec.compatible_with)
            requirements.update(spec.requires)
            failures = [
                f"requires {dependency} version {required_version}"
                for dependency, required_version in requirements.items()
                if dependency not in metadata
                or metadata[dependency].status is not ResourceStatus.VALID
                or observed_versions.get(dependency, metadata[dependency].version)
                != required_version
            ]
            if failures:
                current = metadata[spec.resource_id]
                metadata[spec.resource_id] = ResourceMetadata(
                    resource_id=current.resource_id,
                    version=current.version,
                    status=ResourceStatus.INCOMPATIBLE,
                    compatible=False,
                    checksum=current.checksum,
                )
                diagnostics[spec.resource_id] = diagnostics[spec.resource_id] + tuple(failures)

        self._metadata = metadata
        self._diagnostics = diagnostics
        self._validated = {
            spec.resource_id: ValidatedResource(
                metadata=metadata[spec.resource_id],
                path=resolved_paths[spec.resource_id],
                configuration=spec.configuration,
                diagnostics=diagnostics[spec.resource_id],
            )
            for spec in self.manifest
            if metadata[spec.resource_id].status is ResourceStatus.VALID
        }
        return dict(metadata)

    @property
    def statuses(self) -> Mapping[str, ResourceMetadata]:
        """Return the latest normalized metadata snapshot."""

        return MappingProxyType(dict(self._metadata))

    @property
    def all_valid(self) -> bool:
        """Whether the latest validation found every manifest resource valid."""

        return bool(self._metadata) and all(
            metadata.status is ResourceStatus.VALID for metadata in self._metadata.values()
        )

    def metadata(
        self, resource_id: str | None = None
    ) -> Mapping[str, ResourceMetadata] | ResourceMetadata:
        """Return all metadata or one resource's metadata from the latest scan.

        The union return is honest about this accessor's two shapes. Callers
        that want one record without narrowing should use
        :meth:`get_metadata`.
        """

        self._require_validated_snapshot()
        if resource_id is None:
            return self.statuses
        return self._metadata_for(resource_id)

    def get_metadata(self, resource_id: str) -> ResourceMetadata:
        """Explicit alias for retrieving one resource's metadata."""

        self._require_validated_snapshot()
        return self._metadata_for(resource_id)

    def _metadata_for(self, resource_id: str) -> ResourceMetadata:
        try:
            return self._metadata[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource id: {resource_id}") from exc

    def validated_path(self, resource_id: str) -> Path:
        """Return a valid resource path for composition/provider wiring."""

        return self._validated_resource(resource_id).path

    def get_validated_path(self, resource_id: str) -> Path:
        """Explicit alias for :meth:`validated_path`."""

        return self.validated_path(resource_id)

    @property
    def validated_resources(self) -> Mapping[str, ValidatedResource]:
        """Return the latest valid resources for composition wiring."""

        self._require_validated_snapshot()
        return MappingProxyType(dict(self._validated))

    def validated_resource(self, resource_id: str) -> ValidatedResource:
        """Return path, metadata, and configuration for one valid resource."""

        return self._validated_resource(resource_id)

    def configuration(self, resource_id: str) -> Mapping[str, Any]:
        """Return a copy of configuration for a valid resource."""

        return dict(self._validated_resource(resource_id).configuration)

    def get_configuration(self, resource_id: str) -> Mapping[str, Any]:
        """Explicit alias for :meth:`configuration`."""

        return self.configuration(resource_id)

    def diagnostics(self, resource_id: str) -> tuple[str, ...]:
        """Return validation diagnostics for a resource."""

        self._require_validated_snapshot()
        try:
            return self._diagnostics[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource id: {resource_id}") from exc

    def _require_validated_snapshot(self) -> None:
        if not self._metadata:
            raise ResourceManagerError("validate() must be called before reading resource state")

    def _validated_resource(self, resource_id: str) -> ValidatedResource:
        self._require_validated_snapshot()
        try:
            return self._validated[resource_id]
        except KeyError as exc:
            if resource_id not in self._metadata:
                raise KeyError(f"unknown resource id: {resource_id}") from exc
            raise ResourceUnavailableError(
                f"resource is not valid: {resource_id} "
                f"({self._metadata[resource_id].status.value.lower()})"
            ) from exc

    def _validate_spec(
        self, spec: ResourceSpec
    ) -> tuple[ResourceMetadata, tuple[str, ...], str | None, Path]:
        path = self._resolve_manifest_path(spec.path, field_name="resource path")
        version_path = (
            self._resolve_manifest_path(spec.version_file, field_name="version_file")
            if spec.version_file is not None
            else None
        )
        expected_version = spec.required_version
        fallback_version = spec.installed_version or expected_version or ""
        if not path.exists():
            return (
                ResourceMetadata(
                    resource_id=spec.resource_id,
                    version=fallback_version,
                    status=ResourceStatus.MISSING,
                    compatible=False,
                ),
                (f"resource path does not exist: {path}",),
                None,
                path,
            )

        diagnostics: list[str] = []
        observed_version = spec.installed_version
        actual_checksum: str | None = None

        if spec.kind == "directory" and not path.is_dir():
            diagnostics.append("resource is not a directory")
        elif spec.kind in {"file", "sqlite", "krdict"} and not path.is_file():
            diagnostics.append("resource is not a file")

        if not diagnostics:
            try:
                self._assert_readable(path)
            except OSError as exc:
                diagnostics.append(f"resource is unreadable: {exc}")

        if not diagnostics and spec.version_file is not None:
            assert version_path is not None
            try:
                observed_version = version_path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as exc:
                diagnostics.append(f"version metadata is unreadable: {exc}")

        if not diagnostics and spec.schema is not None:
            try:
                schema_version = self._validate_schema(path, spec.schema)
                if observed_version is None:
                    observed_version = schema_version
            except (OSError, UnicodeError, sqlite3.Error, ValueError) as exc:
                diagnostics.append(f"schema is incompatible: {exc}")

        if not diagnostics and (spec.kind in {"sqlite", "krdict"} or spec.schema is not None):
            try:
                self._validate_integrity(path)
            except (OSError, sqlite3.Error, ValueError) as exc:
                diagnostics.append(f"SQLite integrity check failed: {exc}")

        if not diagnostics and spec.checksum is not None:
            try:
                algorithm, expected_digest = _parse_checksum(spec.checksum)
                actual_digest = _digest(path, algorithm)
                actual_checksum = f"{algorithm}:{actual_digest}"
                if actual_digest != expected_digest:
                    diagnostics.append("checksum does not match the manifest")
            except (OSError, ValueError) as exc:
                diagnostics.append(f"checksum is invalid: {exc}")
        elif not diagnostics:
            # Hashing is useful metadata even when the manifest does not pin an
            # expected checksum. Directory hashes are intentionally omitted;
            # callers that need a directory hash can provide one explicitly.
            try:
                actual_checksum = (
                    f"sha256:{_digest(path, 'sha256')}" if path.is_file() else None
                )
            except OSError as exc:
                diagnostics.append(f"resource could not be hashed: {exc}")

        if observed_version is None:
            observed_version = fallback_version
        if expected_version is not None and observed_version != expected_version:
            version_status = ResourceStatus.OUTDATED
        else:
            version_status = ResourceStatus.VALID

        status = ResourceStatus.INCOMPATIBLE if diagnostics else version_status
        compatible = status is ResourceStatus.VALID
        metadata = ResourceMetadata(
            resource_id=spec.resource_id,
            version=observed_version,
            status=status,
            compatible=compatible,
            checksum=actual_checksum,
        )
        return metadata, tuple(diagnostics), observed_version, path

    def _resolve_manifest_path(
        self,
        value: str | os.PathLike[str],
        *,
        field_name: str,
    ) -> Path:
        """Resolve a manifest path without falling back to process CWD."""

        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        if self._base_path is None:
            # Construction already refused this manifest; this guard only keeps
            # the CWD fallback from reappearing if that check is ever bypassed.
            raise ResourceManagerError(
                f"relative {field_name} is not allowed without ResourceManager base_path: {path}"
            )
        return (self._base_path / path).resolve()

    @staticmethod
    def _assert_readable(path: Path) -> None:
        if not os.access(path, os.R_OK):
            raise OSError("read permission denied")
        if path.is_file():
            with path.open("rb") as stream:
                stream.read(1)
            return
        # Walk directories without loading resource contents into memory. 
        # A one-byte read catches unreadable model/asset files portably on POSIX;
        # os.access remains the best available signal on Windows.
        with os.scandir(path) as entries:
            for entry in entries:
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    ResourceManager._assert_readable(child)
                elif entry.is_file(follow_symlinks=False):
                    with child.open("rb") as stream:
                        stream.read(1)

    @staticmethod
    def _validate_schema(path: Path, schema: SchemaSpec) -> str:
        if not path.is_file():
            raise ValueError("SQLite schema validation requires a file")
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing_tables = set(schema.required_tables) - tables
            if missing_tables:
                raise ValueError(f"missing tables: {', '.join(sorted(missing_tables))}")

            for table, required_columns in schema.required_columns.items():
                if table not in tables:
                    raise ValueError(f"missing table: {table}")
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
                }
                missing_columns = set(required_columns) - columns
                if missing_columns:
                    raise ValueError(
                        f"missing columns in {table}: {', '.join(sorted(missing_columns))}"
                    )

            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
            missing_indexes = set(schema.required_indexes) - indexes
            if missing_indexes:
                raise ValueError(f"missing indexes: {', '.join(sorted(missing_indexes))}")

            metadata: dict[str, str] = {}
            if (
                schema.metadata
                or schema.name
                or schema.marker is not None
                or "metadata" in schema.required_tables
            ):
                metadata = {
                    str(row[0]): str(row[1])
                    for row in connection.execute("SELECT key, value FROM metadata")
                }
            if metadata.get("schema_name") != schema.name:
                raise ValueError("metadata schema_name does not match the schema contract")
            if schema.marker is not None and metadata.get("schema_marker") != schema.marker:
                raise ValueError("metadata schema_marker does not match the schema contract")
            for key, expected in schema.metadata.items():
                if metadata.get(key) != expected:
                    raise ValueError(f"metadata {key!r} does not match the schema contract")
            if "schema_version" in metadata and metadata["schema_version"] != str(schema.version):
                raise ValueError("metadata schema_version does not match the schema contract")

            if schema.user_version is not None:
                user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if user_version != schema.user_version:
                    raise ValueError("SQLite user_version does not match the schema contract")
            return metadata.get("schema_version", str(schema.version))
        finally:
            connection.close()

    @staticmethod
    def _validate_integrity(path: Path) -> None:
        """Validate SQLite contents after the schema contract has passed.

        ``quick_check`` is the inexpensive startup check. Its normal result is
        exactly one ``ok`` row; any other result is treated as a failed or
        ambiguous check and escalated to ``integrity_check`` for a definitive
        diagnostic before the resource is rejected.
        """

        if not path.is_file():
            raise ValueError("SQLite integrity validation requires a file")

        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            quick_error: str | None = None
            try:
                quick_rows = tuple(
                    str(row[0]).strip() for row in connection.execute("PRAGMA quick_check")
                )
            except sqlite3.Error as exc:
                quick_rows = ()
                quick_error = str(exc)

            if quick_error is None and quick_rows == ("ok",):
                return

            integrity_error: str | None = None
            try:
                integrity_rows = tuple(
                    str(row[0]).strip()
                    for row in connection.execute("PRAGMA integrity_check")
                )
            except sqlite3.Error as exc:
                integrity_rows = ()
                integrity_error = str(exc)

            quick_result = quick_error or _format_integrity_rows(quick_rows)
            integrity_result = integrity_error or _format_integrity_rows(integrity_rows)
            raise ValueError(
                f"PRAGMA quick_check returned {quick_result}; "
                f"PRAGMA integrity_check returned {integrity_result}"
            )
        finally:
            connection.close()


def _format_integrity_rows(rows: tuple[str, ...]) -> str:
    """Render SQLite pragma output without dropping diagnostic rows."""

    if not rows:
        return "no result"
    return "; ".join(rows)


def _quote(identifier: str) -> str:
    """Quote a SQLite identifier without allowing manifest text as SQL."""

    return '"' + identifier.replace('"', '""') + '"'


def _parse_checksum(value: str) -> tuple[str, str]:
    normalized = value.strip().lower()
    if ":" in normalized:
        algorithm, digest = normalized.split(":", 1)
    else:
        algorithm, digest = "sha256", normalized
    if algorithm not in hashlib.algorithms_available:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}")
    if not digest or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("checksum must be hexadecimal")
    expected_length = hashlib.new(algorithm).digest_size * 2
    if len(digest) != expected_length:
        raise ValueError(f"{algorithm} checksum must contain {expected_length} hex characters")
    return algorithm, digest


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    if path.is_file():
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    for child in sorted(
        path.rglob("*"), key=lambda candidate: candidate.relative_to(path).as_posix()
    ):
        if child.is_file():
            relative = child.relative_to(path).as_posix().encode("utf-8")
            digest.update(relative)
            digest.update(b"\0")
            with child.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "KRDICT_SCHEMA",
    "ResourceManifest",
    "ResourceManager",
    "ResourceManagerError",
    "ResourceMetadata",
    "ResourceSpec",
    "ResourceStatus",
    "ResourceUnavailableError",
    "SchemaSpec",
    "ValidatedResource",
]
