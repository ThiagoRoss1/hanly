"""First-run acquisition of the production runtime resources.

The desktop keeps resource validation in :class:`hanly.ResourceManager` and
remote delivery in :class:`hanly_app.UpdateService`. This module only joins
those two existing seams at the process-start boundary: it writes a small
per-user runtime manifest, asks the configured public release channel for
missing artifacts, and leaves activation/validation to ``UpdateService``.

The generated manifest intentionally contains no model or dictionary bytes.
Those artifacts remain independently released resources and can be replaced
atomically by the update service without modifying application code.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hanly.resource_manager import ResourceManager, ResourceMetadata, ResourceStatus

from .runtime import (
    OCRBackend,
    RuntimeConfigError,
    load_resource_manager,
    read_ocr_backend,
)
from .update_service import (
    GitHubReleaseFetcher,
    RemoteResource,
    ResourceFetcher,
    UpdateService,
    UpdateServiceError,
)

PUBLIC_REPOSITORY_OWNER = "ThiagoRoss1"
PUBLIC_REPOSITORY_NAME = "hanly"
PUBLIC_MANIFEST_ASSET = "hanly-resources.json"
PUBLIC_RELEASE_CHANNEL = f"{PUBLIC_REPOSITORY_OWNER}/{PUBLIC_REPOSITORY_NAME}"
#: Every resource a runtime may declare, with the kind it must have.
RESOURCE_KINDS = {
    "paddle_detection_model": "directory",
    "paddle_recognition_model": "directory",
    "krdict": "krdict",
}

#: What each backend must have provisioned before the desktop can start.
#: EasyOCR resolves its own models through its storage directory, so it
#: declares no managed model resource.
REQUIRED_RESOURCE_IDS = {
    OCRBackend.PADDLE: (
        "paddle_detection_model",
        "paddle_recognition_model",
        "krdict",
    ),
    OCRBackend.EASYOCR: ("krdict",),
}


class RuntimeBootstrapError(RuntimeError):
    """Raised when first-run runtime resources cannot be made usable."""


def bootstrap_runtime_config(
    config_path: str | Path,
    *,
    fetcher: ResourceFetcher | None = None,
) -> Path:
    """Create and provision a production runtime configuration.

    Existing configuration bytes are never replaced. A valid local manifest
    returns immediately without constructing a fetcher or contacting GitHub;
    otherwise each invalid resource is staged and activated through the
    existing ``UpdateService``. A failed download leaves the last valid local
    artifact untouched and leaves the manifest available for a later retry.
    """

    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        _write_default_config(path)

    required = REQUIRED_RESOURCE_IDS[read_ocr_backend(path)]
    manager = _load_manager(path, context="cannot prepare runtime configuration")
    metadata = manager.validate()
    missing = [
        resource_id
        for resource_id in required
        if metadata[resource_id].status is not ResourceStatus.VALID
    ]
    if not missing:
        # An invalid resource outside the required three is still fatal:
        # ``load_runtime`` applies the same all-valid rule at startup, so
        # succeeding here would only move the failure past the point of repair.
        if not manager.all_valid:
            raise RuntimeBootstrapError(
                _invalid_resources_message(manager, metadata, "runtime resources are invalid")
            )
        return path

    service = UpdateService(manager, fetcher or _public_release_fetcher())
    _install_resources(service, path, missing)

    # The live manager intentionally stays immutable during an update. Rebuild
    # it from the persisted manifest so final validation and the next update
    # check observe the installed release identities.
    manager = _load_manager(
        path, context="could not reload runtime configuration after provisioning"
    )
    final_metadata = manager.validate()
    if not manager.all_valid:
        raise RuntimeBootstrapError(
            _invalid_resources_message(
                manager, final_metadata, "runtime resources remain invalid after provisioning"
            )
        )
    return path


def _install_resources(
    service: UpdateService,
    config_path: Path,
    resource_ids: list[str],
) -> None:
    """Obtain and activate each named resource, recording what was installed."""

    try:
        availability = service.check_for_updates()
    except UpdateServiceError as error:
        # Reaching the release channel is only how a launch with no
        # configuration of its own obtains resources. Say so, because the
        # failure otherwise reads as a broken application to anyone running
        # from a checkout before any release exists.
        raise RuntimeBootstrapError(
            f"could not obtain required resources from {PUBLIC_RELEASE_CHANNEL}: "
            f"{error}. Start with --runtime-config pointing at an existing "
            f"configuration to use local resources instead."
        ) from error

    remote = {item.resource.resource_id: item.resource for item in availability}
    _require_deliverable_resources(remote, resource_ids)

    for resource_id in resource_ids:
        try:
            service.install(resource_id)
        except UpdateServiceError as error:
            raise RuntimeBootstrapError(
                f"could not install {resource_id} from {PUBLIC_RELEASE_CHANNEL}: {error}"
            ) from error
        # Record each activation before the next artifact starts. A later
        # download may fail, but already activated resources must still retain
        # their release identities for the next launch/update check.
        _persist_resource_version(config_path, resource_id, remote[resource_id].version)


def _require_deliverable_resources(
    remote: Mapping[str, RemoteResource],
    resource_ids: list[str],
) -> None:
    """Reject a release manifest that cannot satisfy the required resources."""

    absent = [resource_id for resource_id in resource_ids if resource_id not in remote]
    if absent:
        raise RuntimeBootstrapError(
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
        raise RuntimeBootstrapError(
            f"release manifest from {PUBLIC_RELEASE_CHANNEL} has incompatible "
            f"resource kind(s): {', '.join(mismatched)}"
        )


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
        raise RuntimeBootstrapError(f"{context} {path}: {error}") from error


def _persist_resource_version(path: Path, resource_id: str, version: str) -> None:
    """Record one release version without replacing unrelated runtime options."""

    payload = _runtime_payload_for_update(path)
    resources = dict(payload["resources"])
    entry = resources.get(resource_id)
    if isinstance(entry, Mapping):
        updated_entry = dict(entry)
    elif isinstance(entry, str):
        updated_entry = {"path": entry}
    else:
        raise RuntimeBootstrapError(
            f"could not record installed resource versions in {path}: "
            f"resources.{resource_id} must be an object or path"
        )

    # ``version`` is the operator's expected-version pin, which ResourceManager
    # compares the observed version against; writing a release identity over it
    # would report the freshly installed artifact as OUTDATED.
    if updated_entry.get("version") is not None:
        return

    # ``installed_version`` is deliberately separate from ``version``: KRDICT's
    # version is the embedded SQLite schema contract, while the release version
    # identifies the independently delivered database.
    updated_entry["installed_version"] = version
    resources[resource_id] = updated_entry
    payload["resources"] = resources
    _write_json_atomically(path, payload)


def _runtime_payload_for_update(path: Path) -> dict[str, Any]:
    """Reread the manifest so unrelated user fields survive a version write."""

    try:
        payload_value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeBootstrapError(
            f"could not record installed resource versions in {path}: {error}"
        ) from error
    if not isinstance(payload_value, Mapping):
        raise RuntimeBootstrapError(
            f"could not record installed resource versions in {path}: "
            "runtime config must contain a JSON object"
        )
    if not isinstance(payload_value.get("resources"), Mapping):
        raise RuntimeBootstrapError(
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
        raise RuntimeBootstrapError(f"could not create runtime config {path}: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _default_runtime_payload() -> dict[str, Any]:
    """Return the configuration a first launch writes.

    EasyOCR declares no managed model resource: it resolves its own models
    through its storage directory, so a first run provisions only KRDICT. The
    PaddleOCR adapter remains available to a configuration that names it.
    """

    return {
        "manifest_version": 1,
        "ocr_backend": OCRBackend.EASYOCR.value,
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
    "PUBLIC_MANIFEST_ASSET",
    "PUBLIC_RELEASE_CHANNEL",
    "PUBLIC_REPOSITORY_NAME",
    "PUBLIC_REPOSITORY_OWNER",
    "REQUIRED_RESOURCE_IDS",
    "RESOURCE_KINDS",
    "RuntimeBootstrapError",
    "bootstrap_runtime_config",
]
