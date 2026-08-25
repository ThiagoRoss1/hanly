"""UI-independent remote resource delivery for Hanly Desktop.

The application obtains remote artifacts here; :class:`hanly.ResourceManager`
remains the authority for local resource compatibility. Downloads are staged
beside their destination and are not activated until the manager accepts the
staged path. The module deliberately uses synchronous operations so a caller
can choose the worker, executor, or event-loop integration appropriate for its
client.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hanly.resource_manager import (
    ResourceManager,
    ResourceManifest,
    ResourceMetadata,
    ResourceSpec,
)


class UpdateServiceError(RuntimeError):
    """Base error for remote resource delivery failures."""


class RemoteManifestError(UpdateServiceError):
    """Raised when a remote manifest cannot be normalized."""


class ResourceUpdateError(UpdateServiceError):
    """Raised when a resource cannot be downloaded, validated, or activated."""


@dataclass(frozen=True)
class RemoteResource:
    """One resource advertised by a remote manifest or release."""

    resource_id: str
    version: str
    url: str | None = None
    checksum: str | None = None
    kind: str = "file"
    asset_name: str | None = None

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValueError("remote resource id must not be empty")
        if not self.version.strip():
            raise ValueError("remote resource version must not be empty")
        if not (self.url or self.asset_name):
            raise ValueError("remote resource requires a URL or release asset name")
        if self.url is not None:
            _require_https(self.url)
        if self.kind not in {"file", "directory", "sqlite", "krdict"}:
            raise ValueError("remote resource kind must be file, directory, sqlite, or krdict")


@dataclass(frozen=True)
class RemoteManifest:
    """Immutable, id-indexed remote resource metadata."""

    resources: tuple[RemoteResource, ...]
    release: str | None = None

    def __post_init__(self) -> None:
        values = tuple(self.resources)
        if len({resource.resource_id for resource in values}) != len(values):
            raise ValueError("remote manifest contains duplicate resource ids")
        object.__setattr__(self, "resources", values)

    def __iter__(self) -> Iterator[RemoteResource]:
        return iter(self.resources)

    def __getitem__(self, resource_id: str) -> RemoteResource:
        for resource in self.resources:
            if resource.resource_id == resource_id:
                return resource
        raise KeyError(resource_id)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RemoteManifest:
        """Normalize the small JSON manifest accepted by the delivery seam."""

        raw_resources = payload.get("resources")
        if isinstance(raw_resources, Mapping):
            entries = [dict(value, id=resource_id) for resource_id, value in raw_resources.items()]
        elif isinstance(raw_resources, Sequence) and not isinstance(raw_resources, (str, bytes)):
            entries = list(raw_resources)
        else:
            raise RemoteManifestError("manifest resources must be an object or array")

        resources: list[RemoteResource] = []
        for index, raw in enumerate(entries):
            if not isinstance(raw, Mapping):
                raise RemoteManifestError(f"manifest resource {index} must be an object")
            resource_id = raw.get("resource_id", raw.get("id"))
            version = raw.get("version")
            url = raw.get("url", raw.get("download_url"))
            asset_name = raw.get("asset_name", raw.get("asset"))
            if not isinstance(resource_id, str) or not isinstance(version, str):
                raise RemoteManifestError(f"manifest resource {index} requires id and version")
            if url is not None and not isinstance(url, str):
                raise RemoteManifestError(f"manifest resource {resource_id} url must be a string")
            if asset_name is not None and not isinstance(asset_name, str):
                raise RemoteManifestError(
                    f"manifest resource {resource_id} asset_name must be a string"
                )
            checksum = raw.get("checksum")
            if checksum is not None and not isinstance(checksum, str):
                raise RemoteManifestError(
                    f"manifest resource {resource_id} checksum must be a string"
                )
            kind = raw.get("kind", "file")
            if not isinstance(kind, str):
                raise RemoteManifestError(f"manifest resource {resource_id} kind must be a string")
            try:
                resources.append(
                    RemoteResource(
                        resource_id=resource_id,
                        version=version,
                        url=url,
                        checksum=checksum,
                        kind=kind,
                        asset_name=asset_name,
                    )
                )
            except ValueError as exc:
                raise RemoteManifestError(str(exc)) from exc
        release = payload.get("release", payload.get("tag_name"))
        return cls(
            resources=tuple(resources), release=release if isinstance(release, str) else None
        )


@dataclass(frozen=True)
class DownloadProgress:
    """Normalized progress event emitted by a fetch and update operation."""

    resource_id: str
    phase: str
    completed: int = 0
    total: int | None = None

    @property
    def fraction(self) -> float | None:
        if self.total is None or self.total <= 0:
            return None
        return min(1.0, self.completed / self.total)


@dataclass(frozen=True)
class UpdateAvailability:
    """A local/remote version comparison without making compatibility decisions."""

    resource: RemoteResource
    current_version: str | None
    available: bool


@dataclass(frozen=True)
class UpdateResult:
    """Successful activation details returned to an application coordinator."""

    resource: RemoteResource
    path: Path
    validation: ResourceMetadata
    backup_path: Path | None


ProgressCallback = Callable[[DownloadProgress], None]
Opener = Callable[..., Any]


@runtime_checkable
class ResourceFetcher(Protocol):
    """Remote adapter contract consumed by :class:`UpdateService`."""

    def fetch_manifest(self) -> RemoteManifest:
        """Return normalized remote availability metadata."""

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Write one remote artifact to the supplied staging destination."""


class GitHubReleaseFetcher:
    """Small GitHub Releases adapter with no dependency on GitHub Actions."""

    def __init__(
        self,
        owner: str,
        repository: str,
        *,
        tag: str = "latest",
        manifest_asset: str = "hanly-resources.json",
        timeout: float = 30.0,
        opener: Opener | None = None,
    ) -> None:
        if not owner.strip() or not repository.strip():
            raise ValueError("GitHub owner and repository must not be empty")
        self._api_url = f"https://api.github.com/repos/{owner}/{repository}/releases"
        self._release_url = (
            f"{self._api_url}/latest" if tag == "latest" else f"{self._api_url}/tags/{tag}"
        )
        self._manifest_asset = manifest_asset
        self._timeout = timeout
        self._opener = opener or _https_opener()
        self._release_payload: Mapping[str, Any] | None = None

    def fetch_manifest(self) -> RemoteManifest:
        payload = self._json(self._release_url)
        self._release_payload = payload

        inline = payload.get("hanly_manifest", payload.get("manifest"))
        if isinstance(inline, Mapping):
            manifest_payload = inline
        else:
            asset = self._asset(payload, self._manifest_asset)
            if asset is None:
                raise RemoteManifestError(
                    f"GitHub release has no {self._manifest_asset!r} manifest asset"
                )
            manifest_payload = self._json(self._asset_url(asset))
        return RemoteManifest.from_payload(manifest_payload)

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        url = resource.url
        if url is None:
            payload = self._release_payload
            if payload is None:
                payload = self._json(self._release_url)
                self._release_payload = payload
            asset = self._asset(payload, resource.asset_name or "")
            if asset is None:
                raise ResourceUpdateError(
                    f"GitHub release has no asset for resource {resource.resource_id}"
                )
            url = self._asset_url(asset)
        self._download_url(resource.resource_id, url, destination, on_progress)

    def _json(self, url: str) -> Mapping[str, Any]:
        try:
            with closing(self._open(url)) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteManifestError(f"could not read remote metadata: {exc}") from exc
        if not isinstance(value, Mapping):
            raise RemoteManifestError("remote metadata must be a JSON object")
        return value

    def _download_url(
        self,
        resource_id: str,
        url: str,
        destination: Path,
        on_progress: ProgressCallback | None,
    ) -> None:
        try:
            response = self._open(url)
            with closing(response), destination.open("wb") as output:
                headers = getattr(response, "headers", None)
                raw_total = headers.get("Content-Length") if headers is not None else None
                total = int(raw_total) if raw_total and str(raw_total).isdigit() else None
                completed = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    completed += len(chunk)
                    if on_progress is not None:
                        on_progress(DownloadProgress(resource_id, "downloading", completed, total))
        except (OSError, ValueError) as exc:
            raise ResourceUpdateError(f"could not download {resource_id}: {exc}") from exc

    def _open(self, url: str) -> Any:
        _require_https(url)
        try:
            return self._opener(url, timeout=self._timeout)
        except TypeError:
            # Tiny test doubles often accept only the URL; the production
            # opener still receives the bounded timeout above.
            return self._opener(url)

    @staticmethod
    def _asset(payload: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
        assets = payload.get("assets")
        if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)):
            return None
        for asset in assets:
            if isinstance(asset, Mapping) and asset.get("name") == name:
                return asset
        return None

    @staticmethod
    def _asset_url(asset: Mapping[str, Any]) -> str:
        url = asset.get("browser_download_url", asset.get("url"))
        if not isinstance(url, str) or not url:
            raise RemoteManifestError("GitHub release asset has no download URL")
        return url


class UpdateService:
    """Obtain, validate, and safely activate remote resources."""

    def __init__(self, resource_manager: ResourceManager, fetcher: ResourceFetcher) -> None:
        self._resource_manager = resource_manager
        self._fetcher = fetcher
        self._manifest: RemoteManifest | None = None

    def check_for_updates(self) -> tuple[UpdateAvailability, ...]:
        """Report release resources this installation actually uses.

        A release serves every backend, so its manifest can advertise
        resources the local configuration never declared, and an EasyOCR install
        has no use for PaddleOCR model files. Offering those would also offer
        something that cannot be acted on: ``install`` resolves a destination
        from the local manifest and refuses an id that is not in it.
        """

        manifest = self._fetcher.fetch_manifest()
        self._manifest = manifest
        current = self._current_states()
        # The manifest iterates specs, not ids, so membership is taken from
        # the ids themselves rather than from the manifest directly.
        declared = {spec.resource_id for spec in self._resource_manager.manifest}
        return tuple(
            UpdateAvailability(
                resource=resource,
                current_version=current.get(resource.resource_id, (None, None))[0],
                available=(
                    current.get(resource.resource_id, (None, None))[1] != "VALID"
                    or current.get(resource.resource_id, (None, None))[0] != resource.version
                ),
            )
            for resource in manifest
            if resource.resource_id in declared
        )

    def install(
        self,
        resource_id: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> UpdateResult:
        manifest = self._manifest or self._fetcher.fetch_manifest()
        self._manifest = manifest
        try:
            resource = manifest[resource_id]
        except KeyError as exc:
            raise ResourceUpdateError(f"remote manifest has no resource {resource_id}") from exc

        spec = self._spec(resource_id)
        if resource.checksum is None:
            # Directory deliveries carry the OCR models the engine later loads
            # and executes, so no resource kind may activate on transport
            # integrity alone.
            raise ResourceUpdateError(
                f"remote manifest must provide a checksum for resource {resource_id}"
            )
        destination = self._destination(spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage_file = _temporary_file(
            prefix=f".{destination.name}.", suffix=".download", directory=destination.parent
        )
        stage_path: Path = stage_file
        validation: ResourceMetadata | None = None
        backup_path: Path | None = None
        activated = False
        try:
            _emit(on_progress, DownloadProgress(resource_id, "downloading"))
            self._fetcher.download(resource, stage_file, on_progress)
            # Always verify the delivered bytes before anything unpacks or
            # activates them; for a directory this covers the whole archive.
            _verify_checksum(stage_file, resource.checksum)

            if resource.kind == "directory":
                stage_path = _extract_directory(stage_file, destination.parent, resource_id)

            _emit(on_progress, DownloadProgress(resource_id, "validating"))
            validation = self._validate_staged(
                resource_id,
                stage_path,
                spec,
                expected_version=resource.version,
                expected_checksum=(resource.checksum if resource.kind != "directory" else None),
            )
            backup_path = _activate(stage_path, destination)
            activated = True
            _emit(on_progress, DownloadProgress(resource_id, "complete", 1, 1))
            return UpdateResult(resource, destination.resolve(), validation, backup_path)
        except Exception as exc:
            if isinstance(exc, UpdateServiceError):
                raise
            raise ResourceUpdateError(f"update failed for {resource_id}: {exc}") from exc
        finally:
            _remove_path(stage_file)
            if stage_path != stage_file:
                _remove_path(stage_path)
            if not activated and backup_path is not None:
                _remove_path(backup_path)

    def rollback(self, resource_id: str) -> Path:
        """Restore the last-known-good copy, discarding the rejected artifact.

        The backup is copied rather than moved, so the known-good artifact
        stays the known-good one.  A rejected version never becomes the new
        backup, and repeated rollbacks are idempotent.
        """

        spec = self._spec(resource_id)
        destination = self._destination(spec)
        backup = _backup_path(destination)
        if not backup.exists():
            raise ResourceUpdateError(f"no last-known-good backup for {resource_id}")

        restored = _temporary_path(
            prefix=f".{destination.name}.", suffix=".restore", directory=destination.parent
        )
        rejected = _temporary_path(
            prefix=f".{destination.name}.", suffix=".rejected", directory=destination.parent
        )
        try:
            _copy_path(backup, restored)
            if destination.exists():
                os.replace(destination, rejected)
            try:
                os.replace(restored, destination)
            except Exception:
                if rejected.exists() and not destination.exists():
                    os.replace(rejected, destination)
                raise
            return destination.resolve()
        except Exception as exc:
            raise ResourceUpdateError(f"rollback failed for {resource_id}: {exc}") from exc
        finally:
            _remove_path(restored)
            _remove_path(rejected)

    def _current_states(self) -> Mapping[str, tuple[str | None, str]]:
        self._resource_manager.validate()
        return {
            resource_id: (metadata.version, metadata.status.value.upper())
            for resource_id, metadata in self._resource_manager.statuses.items()
        }

    def _spec(self, resource_id: str) -> ResourceSpec:
        try:
            return self._resource_manager.manifest[resource_id]
        except KeyError as exc:
            raise ResourceUpdateError(f"local manifest has no resource {resource_id}") from exc

    def _destination(self, spec: ResourceSpec) -> Path:
        """Resolve where a resource lives, using only local trusted metadata.

        The destination comes from the local manifest, never from the remote
        one, so remote metadata cannot redirect a write outside the configured
        resource locations.
        """

        path = Path(spec.path).expanduser()
        if not path.is_absolute():
            base = self._resource_manager.base_path
            path = (Path(base) / path) if base is not None else path.resolve()
        return path.resolve()

    def _validate_staged(
        self,
        resource_id: str,
        path: Path,
        spec: ResourceSpec,
        *,
        expected_version: str,
        expected_checksum: str | None,
    ) -> ResourceMetadata:
        # Validate through a fresh engine manager whose manifest points at the
        # staged artifact. This preserves the engine/app boundary without
        # mutating the live manager or inventing a remote-policy API on it.
        candidates = [
            replace(
                candidate,
                path=path,
                version=expected_version,
                expected_version=None,
                installed_version=expected_version,
                version_file=None,
                checksum=expected_checksum or spec.checksum,
            )
            if candidate.resource_id == resource_id
            else candidate
            for candidate in self._resource_manager.manifest
        ]

        try:
            candidate_manager = ResourceManager(
                ResourceManifest(candidates),
                base_path=self._resource_manager.base_path,
            )
            result = candidate_manager.validate().get(resource_id)
        except Exception as exc:
            raise ResourceUpdateError(f"staged resource validation failed: {exc}") from exc

        if result is None:
            raise ResourceUpdateError(f"staged resource validation omitted {resource_id}")
        if result.status.value.upper() != "VALID":
            raise ResourceUpdateError(f"staged resource is not valid: {result.status.value}")
        return result


class _HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep the HTTPS policy across redirects.

    ``urllib`` blocks a redirect to ``file:`` but still follows ``http:`` and
    ``ftp:``, so validating only the first URL would let a redirect silently
    downgrade the transport.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _https_opener() -> Callable[..., Any]:
    """Build the default opener used for every remote read."""

    return urllib.request.build_opener(_HTTPSOnlyRedirectHandler).open


def _require_https(url: str) -> str:
    """Reject any remote acquisition scheme other than HTTPS.

    Remote manifests are the least trusted input this module reads, so a
    manifest cannot redirect delivery to a local file, a plaintext transport,
    or another protocol handler that ``urllib`` happens to support.
    """

    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme != "https":
        raise ResourceUpdateError(
            f"remote resources must be delivered over https, not {scheme or 'a relative URL'!s}"
        )
    return url


def _emit(callback: ProgressCallback | None, progress: DownloadProgress) -> None:
    if callback is not None:
        callback(progress)


def _verify_checksum(path: Path, expected: str) -> None:
    normalized = expected.strip().lower()
    algorithm, separator, digest = normalized.partition(":")
    if not separator:
        algorithm, digest = "sha256", normalized
    if algorithm not in hashlib.algorithms_available:
        raise ResourceUpdateError(f"unsupported artifact checksum algorithm: {algorithm}")
    try:
        hasher = hashlib.new(algorithm)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        actual = hasher.hexdigest()
    except (OSError, ValueError) as exc:
        raise ResourceUpdateError(f"could not hash staged artifact: {exc}") from exc
    if not hmac.compare_digest(actual, digest):
        raise ResourceUpdateError("downloaded artifact checksum does not match the manifest")


def _extract_directory(archive: Path, parent: Path, resource_id: str) -> Path:
    target = Path(tempfile.mkdtemp(prefix=f".{resource_id}.", dir=parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            root = target.resolve()
            for member in bundle.infolist():
                candidate = (target / member.filename).resolve()
                if candidate != root and root not in candidate.parents:
                    raise ResourceUpdateError("resource archive contains an unsafe path")
            bundle.extractall(target)
        return target
    except (OSError, zipfile.BadZipFile) as exc:
        _remove_path(target)
        raise ResourceUpdateError(f"could not unpack directory resource: {exc}") from exc


def _activate(stage: Path, destination: Path) -> Path | None:
    backup = _backup_path(destination) if destination.exists() else None
    if backup is not None:
        _remove_path(backup)
        if destination.is_dir():
            shutil.copytree(destination, backup)
        else:
            shutil.copy2(destination, backup)
    try:
        if destination.exists() and destination.is_dir():
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
            )
            _remove_path(temporary)
            os.replace(destination, temporary)
            try:
                os.replace(stage, destination)
            except Exception:
                os.replace(temporary, destination)
                raise
            _remove_path(temporary)
        else:
            os.replace(stage, destination)
    except Exception:
        if backup is not None and not destination.exists():
            if backup.is_dir():
                shutil.copytree(backup, destination)
            else:
                shutil.copy2(backup, destination)
        raise
    return backup


def _copy_path(source: Path, target: Path) -> None:
    """Copy a file or directory resource to a not-yet-existing target."""

    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _backup_path(destination: Path) -> Path:
    return destination.with_name(destination.name + ".last-known-good")


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass


def _temporary_path(*, prefix: str, suffix: str, directory: Path) -> Path:
    """Reserve a unique sibling name without leaving a file or directory."""

    path = _temporary_file(prefix=prefix, suffix=suffix, directory=directory)
    _remove_path(path)
    return path


def _temporary_file(*, prefix: str, suffix: str, directory: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(descriptor)
    return Path(name)


__all__ = [
    "DownloadProgress",
    "GitHubReleaseFetcher",
    "RemoteManifest",
    "RemoteManifestError",
    "RemoteResource",
    "ResourceFetcher",
    "ResourceUpdateError",
    "UpdateAvailability",
    "UpdateResult",
    "UpdateService",
    "UpdateServiceError",
]
