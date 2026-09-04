"""First-run acquisition of the production runtime resources.

The desktop keeps resource validation in :class:`hanly.ResourceManager` and
delivery in :class:`hanly_app.UpdateService`. This module only joins those two
existing seams at the process-start boundary: it writes a small per-user
runtime manifest and asks for whatever that manifest declares but does not yet
have, leaving staging, validation, and activation to ``UpdateService``.

A missing artifact comes from an already-built local database when there is one
(see ``LOCAL_KRDICT_VARIABLE``), otherwise from the public release channel.
Both travel the same install path, so a developer launch exercises what a real
download does.

The generated manifest intentionally contains no dictionary bytes. Resources
remain independently released and can be replaced atomically by the update
service without modifying application code.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hanly.krdict_schema import KRDICTSchemaError, validate_krdict_connection
from hanly.resource_manager import ResourceManager, ResourceMetadata, ResourceStatus

from .runtime import (
    KRDICT_RESOURCE_ID,
    RuntimeConfigError,
    load_resource_manager,
)
from .update_service import (
    DownloadProgress,
    GitHubReleaseFetcher,
    ProgressCallback,
    RemoteManifest,
    RemoteResource,
    ResourceFetcher,
    UpdateService,
    UpdateServiceError,
)

PUBLIC_REPOSITORY_OWNER = "ThiagoRoss1"
PUBLIC_REPOSITORY_NAME = "hanly"
PUBLIC_MANIFEST_ASSET = "hanly-resources.json"
PUBLIC_RELEASE_CHANNEL = f"{PUBLIC_REPOSITORY_OWNER}/{PUBLIC_REPOSITORY_NAME}"
#: EasyOCR resolves its own models through its storage directory, so KRDICT
#: is the only resource a first run must provision.
RESOURCE_KINDS = {KRDICT_RESOURCE_ID: "krdict"}
REQUIRED_RESOURCE_IDS = (KRDICT_RESOURCE_ID,)

#: Points first-run provisioning at an already-built local KRDICT database
#: instead of the release channel. A source checkout is detected the same
#: way, so a developer build needs no environment variable at all.
LOCAL_KRDICT_VARIABLE = "HANLY_KRDICT_DB"
_CHECKOUT_KRDICT_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "generated" / "krdict.sqlite3"
)


class FirstRunError(RuntimeError):
    """Raised when first-run runtime resources cannot be made usable."""


def provision_runtime_config(
    config_path: str | Path,
    *,
    fetcher: ResourceFetcher | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Path:
    """Create and provision a production runtime configuration.

    Existing configuration bytes are never replaced. A valid local manifest
    returns immediately without constructing a fetcher or contacting GitHub;
    otherwise each invalid resource is staged and activated through the
    existing ``UpdateService``. A failed download leaves the last valid local
    artifact untouched and leaves the manifest available for a later retry.
    """

    path = Path(config_path).expanduser().resolve()
    _status(on_status, "Preparing Hanly...")
    if not path.exists():
        _write_default_config(path)

    _status(on_status, "Checking resources...")
    manager = _load_manager(path, context="cannot prepare runtime configuration")
    metadata = manager.validate()
    missing = [
        resource_id
        for resource_id in REQUIRED_RESOURCE_IDS
        if metadata[resource_id].status is not ResourceStatus.VALID
    ]
    invalid_extras = [
        resource_id
        for resource_id, resource_metadata in metadata.items()
        if resource_id not in REQUIRED_RESOURCE_IDS
        and resource_metadata.status is not ResourceStatus.VALID
    ]
    if invalid_extras:
        raise FirstRunError(
            _invalid_resources_message(manager, metadata, "runtime resources are invalid")
        )
    if not missing:
        # An unrequired-but-declared resource is still fatal: ``load_runtime``
        # applies the same all-valid rule at startup, so succeeding here would
        # only move the failure past the point of repair.
        if not manager.all_valid:
            raise FirstRunError(
                _invalid_resources_message(manager, metadata, "runtime resources are invalid")
            )
        persist_verified_identities(path, metadata)
        _status(on_status, "Ready")
        return path

    service = UpdateService(manager, fetcher or _local_seed_fetcher() or _public_release_fetcher())
    _install_resources(service, path, missing, on_status=on_status)

    # The live manager intentionally stays immutable during an update. Rebuild
    # it from the persisted manifest so final validation and the next update
    # check observe the installed release identities.
    manager = _load_manager(
        path, context="could not reload runtime configuration after provisioning"
    )
    final_metadata = manager.validate()
    if not manager.all_valid:
        raise FirstRunError(
            _invalid_resources_message(
                manager, final_metadata, "runtime resources remain invalid after provisioning"
            )
        )
    persist_verified_identities(path, final_metadata)
    _status(on_status, "Ready")
    return path


def _install_resources(
    service: UpdateService,
    config_path: Path,
    resource_ids: list[str],
    *,
    on_status: Callable[[str], None] | None = None,
) -> None:
    """Obtain and activate each named resource, recording what was installed."""

    try:
        availability = service.check_for_updates()
    except UpdateServiceError as error:
        # Reaching the release channel is only how a launch with no
        # configuration of its own obtains resources. Say so, because the
        # failure otherwise reads as a broken application to anyone running
        # from a checkout before any release exists.
        raise FirstRunError(
            f"Hanly needs its Korean dictionary and could not reach "
            f"{PUBLIC_RELEASE_CHANNEL} to get it: {error}. Check the network "
            f"connection and open Hanly again, or point "
            f"{LOCAL_KRDICT_VARIABLE} at an already-built krdict.sqlite3 (see "
            f"data/README.md). This is only needed once; later launches start "
            f"offline."
        ) from error

    remote = {item.resource.resource_id: item.resource for item in availability}
    _require_deliverable_resources(remote, resource_ids)

    for resource_id in resource_ids:
        _status(
            on_status,
            "Downloading Korean dictionary..."
            if resource_id == "krdict"
            else f"Downloading {resource_id}...",
        )

        def progress(event: DownloadProgress) -> None:
            if event.phase == "verifying":
                _status(on_status, "Verifying...")
            elif event.phase == "installing":
                _status(on_status, "Installing...")

        try:
            result = service.install(resource_id, on_progress=progress)
        except UpdateServiceError as error:
            raise FirstRunError(
                f"could not install {resource_id} from {PUBLIC_RELEASE_CHANNEL}: {error}"
            ) from error
        # Record each activation before the next artifact starts. A later
        # download may fail, but already activated resources must still retain
        # their release identities for the next launch/update check.
        persist_installed_resource(
            config_path,
            resource_id,
            remote[resource_id].version,
            result.validation.integrity_identity,
        )


def _status(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _require_deliverable_resources(
    remote: Mapping[str, RemoteResource],
    resource_ids: list[str],
) -> None:
    """Reject a release manifest that cannot satisfy the required resources."""

    absent = [resource_id for resource_id in resource_ids if resource_id not in remote]
    if absent:
        raise FirstRunError(
            f"release manifest from {PUBLIC_RELEASE_CHANNEL} is missing required "
            f"resource(s): {', '.join(absent)}"
        )

    mismatched = [
        f"{resource_id} (expected {RESOURCE_KINDS[resource_id]}, "
        f"got {remote[resource_id].kind})"
        for resource_id in resource_ids
        if remote[resource_id].kind != RESOURCE_KINDS[resource_id]
    ]
    if mismatched:
        raise FirstRunError(
            f"release manifest from {PUBLIC_RELEASE_CHANNEL} has incompatible "
            f"resource kind(s): {', '.join(mismatched)}"
        )


class _LocalSeedFetcher:
    """Serve one already-built KRDICT database as if it were a release asset.

    This is the whole of the local-install path: staging, checksum
    verification, schema validation, atomic activation, and version recording
    stay in ``UpdateService``, exactly as they run for a real download.
    """

    def __init__(self, seed: Path) -> None:
        self._seed = seed

    def fetch_manifest(self) -> RemoteManifest:
        try:
            connection = sqlite3.connect(f"{self._seed.resolve().as_uri()}?mode=ro", uri=True)
            try:
                metadata = validate_krdict_connection(connection)
            finally:
                connection.close()
            digest = _sha256(self._seed)
        except (OSError, sqlite3.Error, KRDICTSchemaError) as error:
            raise FirstRunError(
                f"local KRDICT database is unusable: {self._seed}: {error}"
            ) from error
        return RemoteManifest(
            (
                RemoteResource(
                    KRDICT_RESOURCE_ID,
                    metadata["resource_version"],
                    checksum=f"sha256:{digest}",
                    kind="krdict",
                    asset_name=self._seed.name,
                    expected_entry_count=int(metadata["entry_count"]),
                    source_date=metadata["source_date"],
                ),
            )
        )

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        try:
            shutil.copyfile(self._seed, destination)
        except OSError as error:
            raise FirstRunError(
                f"could not copy the local KRDICT database {self._seed}: {error}"
            ) from error
        if on_progress is not None:
            size = destination.stat().st_size
            on_progress(DownloadProgress(resource.resource_id, "downloading", size, size))


def _local_krdict_seed() -> Path | None:
    """Return an already-built KRDICT database to install, if there is one."""

    configured = os.environ.get(LOCAL_KRDICT_VARIABLE)
    if configured:
        seed = Path(configured).expanduser()
        if not seed.is_file():
            raise FirstRunError(
                f"{LOCAL_KRDICT_VARIABLE} does not name a file: {seed}"
            )
        return seed
    return _CHECKOUT_KRDICT_PATH if _CHECKOUT_KRDICT_PATH.is_file() else None


def _local_seed_fetcher() -> ResourceFetcher | None:
    seed = _local_krdict_seed()
    return _LocalSeedFetcher(seed) if seed is not None else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_release_fetcher() -> ResourceFetcher:
    return GitHubReleaseFetcher(
        PUBLIC_REPOSITORY_OWNER,
        PUBLIC_REPOSITORY_NAME,
        tag="latest",
        manifest_asset=PUBLIC_MANIFEST_ASSET,
    )


def _load_manager(path: Path, *, context: str) -> ResourceManager:
    try:
        return load_resource_manager(path)
    except RuntimeConfigError as error:
        raise FirstRunError(f"{context} {path}: {error}") from error


def persist_installed_resource(
    path: Path,
    resource_id: str,
    version: str,
    integrity_identity: str | None = None,
) -> None:
    """Record what one activation installed: its release version and its identity.

    Both facts describe the same bytes, so they are written in a single atomic
    replace. Recording them separately would let a crash between the two leave
    an identity standing against a version it does not belong to, and the next
    launch would skip the integrity check on an artifact nothing verified.
    """

    payload = _runtime_payload_for_update(path)
    resources = dict(payload["resources"])
    entry = _resource_entry(resources, resource_id)
    if entry is None:
        raise FirstRunError(
            f"could not record installed resource versions in {path}: "
            f"resources.{resource_id} must be an object or path"
        )

    updated_entry = dict(entry)
    # ``version`` is the operator's expected-version pin, which ResourceManager
    # compares the observed version against; writing a release identity over it
    # would report the freshly installed artifact as OUTDATED.
    #
    # ``installed_version`` is deliberately separate: KRDICT's version is the
    # embedded SQLite schema contract, while the release version identifies the
    # independently delivered database.
    if updated_entry.get("version") is None:
        updated_entry["installed_version"] = version
    if integrity_identity is not None:
        updated_entry["verified_identity"] = integrity_identity

    if updated_entry == entry:
        return
    resources[resource_id] = updated_entry
    payload["resources"] = resources
    _write_json_atomically(path, payload)


def persist_verified_identities(path: Path, metadata: Mapping[str, ResourceMetadata]) -> None:
    """Record which validated bytes already passed deep integrity validation.

    Writing this back is what makes the next launch cheap: ResourceManager skips
    a full-file scan while the recorded identity still describes the file. Only
    changed entries are written, so an ordinary launch touches no disk.
    """

    payload = _runtime_payload_for_update(path)
    resources = dict(payload["resources"])
    changed = False
    for resource_id, resource_metadata in metadata.items():
        identity = resource_metadata.integrity_identity
        if identity is None:
            continue
        updated_entry = _resource_entry(resources, resource_id)
        if updated_entry is None:
            continue
        if updated_entry.get("verified_identity") == identity:
            continue
        updated_entry["verified_identity"] = identity
        resources[resource_id] = updated_entry
        changed = True

    if not changed:
        return
    payload["resources"] = resources
    _write_json_atomically(path, payload)


def _resource_entry(resources: Mapping[str, Any], resource_id: str) -> dict[str, Any] | None:
    """Return a writable copy of one manifest entry, or None if it has no shape."""

    entry = resources.get(resource_id)
    if isinstance(entry, Mapping):
        return dict(entry)
    if isinstance(entry, str):
        return {"path": entry}
    return None


def _runtime_payload_for_update(path: Path) -> dict[str, Any]:
    """Reread the manifest so unrelated user fields survive a version write."""

    try:
        payload_value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FirstRunError(
            f"could not record installed resource versions in {path}: {error}"
        ) from error
    if not isinstance(payload_value, Mapping):
        raise FirstRunError(
            f"could not record installed resource versions in {path}: "
            "runtime config must contain a JSON object"
        )
    if not isinstance(payload_value.get("resources"), Mapping):
        raise FirstRunError(
            f"could not record installed resource versions in {path}: "
            "resources must be a JSON object"
        )
    return dict(payload_value)


def _write_default_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _default_runtime_payload()
    _write_json_atomically(path, payload)


def _write_json_atomically(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError) as error:
        raise FirstRunError(f"could not create runtime config {path}: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _default_runtime_payload() -> dict[str, Any]:
    """Return the configuration a first launch writes.

    EasyOCR resolves its own models through its storage directory, so a first
    run provisions only KRDICT.
    """

    return {
        "manifest_version": 1,
        "skip_flat_rois": True,
        "resources": {
            "krdict": {
                "kind": "krdict",
                "path": "resources/krdict/krdict.sqlite3",
            },
        },
        "easyocr": {
            "languages": ["ko"],
        },
        "updates": {
            "github": {
                "owner": PUBLIC_REPOSITORY_OWNER,
                "repository": PUBLIC_REPOSITORY_NAME,
                "tag": "latest",
                "manifest_asset": PUBLIC_MANIFEST_ASSET,
            }
        },
    }


def _invalid_resources_message(
    manager: ResourceManager,
    metadata: Mapping[str, ResourceMetadata],
    summary: str,
) -> str:
    invalid: list[str] = []
    for resource_id, resource_metadata in metadata.items():
        if resource_metadata.status is ResourceStatus.VALID:
            continue
        diagnostics = "; ".join(manager.diagnostics(resource_id))
        invalid.append(
            f"{resource_id} is {resource_metadata.status.value.lower()}"
            + (f": {diagnostics}" if diagnostics else "")
        )
    return f"{summary}: " + "; ".join(invalid)


__all__ = [
    "LOCAL_KRDICT_VARIABLE",
    "PUBLIC_MANIFEST_ASSET",
    "PUBLIC_RELEASE_CHANNEL",
    "PUBLIC_REPOSITORY_NAME",
    "PUBLIC_REPOSITORY_OWNER",
    "REQUIRED_RESOURCE_IDS",
    "RESOURCE_KINDS",
    "FirstRunError",
    "persist_installed_resource",
    "persist_verified_identities",
    "provision_runtime_config",
]
