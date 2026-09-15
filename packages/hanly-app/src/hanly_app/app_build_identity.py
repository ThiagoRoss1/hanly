"""Which build is running, and what the last update left behind about it.

Schema 2 identifies a build by a UUID allocated before it is frozen, not by a
digest of its own contents. On macOS it could not be otherwise: a manifest
written inside ``Hanly.app`` after signing would change the seal it describes,
and one written before signing would describe a tree that no longer exists. So
the identifier goes in ahead of the freeze as ordinary package data, the
manifest is produced outside the application afterwards, and the two are tied
together by a receipt kept per installation in the user's own directory.

That receipt is what an update reads to know it is starting from a build this
updater installed. A build installed by hand has a stamp and no receipt, which
is a different and recoverable situation - not a licence to assume ownership of
whatever happens to be on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import unicodedata
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from .app_manifest import (
    ARCHITECTURES,
    PLATFORMS,
    BuildIdentity,
    ManifestError,
    TreeManifest,
)
from .paths import default_app_config_path

#: Written into the package before the build is frozen, and read back out of
#: it at runtime. Deliberately not checked in: it names one build.
BUILD_STAMP_NAME = "hanly-build.json"
BUILD_STAMP_PACKAGE = "hanly_app.assets"

#: Where this updater keeps what it knows about each installation. Outside the
#: installation, because the installation is what gets replaced.
UPDATES_DIRECTORY_NAME = "updates"
RECEIPT_NAME = "installed-receipt.json"
MANIFEST_DIRECTORY = "manifests"

#: The receipt an update has staged but not yet earned. It becomes the real one
#: when the new build has proved it started; a rollback removes it instead.
PENDING_RECEIPT_NAME = "installed-receipt.pending.json"

#: Where the previous receipt waits while an update is in flight, so a rollback
#: restores what the installation was known to be rather than clearing it.
PREVIOUS_RECEIPT_NAME = "installed-receipt.previous.json"

#: Both documents are small by construction; a larger one is not one to parse.
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_STORED_MANIFEST_BYTES = 8 * 1024 * 1024

#: How much of the digest of an installation path names its directory. Long
#: enough that two installations cannot collide, short enough to read.
_KEY_LENGTH = 32

_HEX = "0123456789abcdef"


class BuildIdentityError(RuntimeError):
    """Raised when a build stamp or an installation receipt is not usable."""


@dataclass(frozen=True, slots=True)
class BuildStamp:
    """What this build was when it was frozen, as it says of itself.

    The identifier is a fresh UUID per freeze rather than a content hash.
    Rebuilding one tag produces a second, distinguishable build, and reusing a
    frozen artifact reuses its identifier, which is what lets a release say
    exactly which bytes a delta starts from.
    """

    product: str
    platform: str
    architecture: str
    version: str
    build_id: str
    source_commit: str
    built_at: str = ""

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise BuildIdentityError(f"{self.platform!r} is not a platform Hanly publishes")
        if self.architecture not in ARCHITECTURES:
            raise BuildIdentityError(f"{self.architecture!r} is not an architecture Hanly builds")
        if len(self.source_commit) != 40 or any(
            character not in _HEX for character in self.source_commit
        ):
            raise BuildIdentityError("a build stamp carries a full commit hash")

    @property
    def identity(self) -> BuildIdentity:
        return BuildIdentity(
            product=self.product,
            platform=self.platform,
            architecture=self.architecture,
            version=self.version,
            build_id=self.build_id,
        )

    @property
    def release_tag(self) -> str:
        return f"v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "platform": self.platform,
            "architecture": self.architecture,
            "version": self.version,
            "build_id": self.build_id,
            "source_commit": self.source_commit,
            "built_at": self.built_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_payload(cls, payload: Any) -> BuildStamp:
        if not isinstance(payload, dict):
            raise BuildIdentityError("a build stamp must be a JSON object")
        try:
            return cls(
                product=_text(payload, "product"),
                platform=_text(payload, "platform"),
                architecture=_text(payload, "architecture"),
                version=_text(payload, "version"),
                build_id=_text(payload, "build_id"),
                source_commit=_text(payload, "source_commit").lower(),
                built_at=str(payload.get("built_at") or ""),
            )
        except ManifestError as error:
            raise BuildIdentityError(f"the build stamp is not usable: {error}") from error

    @classmethod
    def from_json(cls, text: str) -> BuildStamp:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise BuildIdentityError(f"the build stamp is not readable JSON: {error}") from error
        return cls.from_payload(payload)


@dataclass(frozen=True, slots=True)
class InstalledReceipt:
    """What this updater knows about one installation it produced.

    Written only after the new build has verified and acknowledged its own
    start, so a receipt on disk always describes something that ran.
    """

    identity: BuildIdentity
    manifest_sha256: str
    release_tag: str
    source_commit: str
    install_root: str
    installed_at: float = 0.0
    preserved_paths: tuple[str, ...] = ()

    def describes(self, stamp: BuildStamp) -> bool:
        """Whether this receipt is about exactly the build that is running."""

        return self.identity.to_dict() == stamp.identity.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "manifest_sha256": self.manifest_sha256,
            "release_tag": self.release_tag,
            "source_commit": self.source_commit,
            "install_root": self.install_root,
            "installed_at": self.installed_at,
            "preserved_paths": list(self.preserved_paths),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_payload(cls, payload: Any) -> InstalledReceipt:
        if not isinstance(payload, dict):
            raise BuildIdentityError("an installation receipt must be a JSON object")
        preserved = payload.get("preserved_paths") or []
        if not isinstance(preserved, (list, tuple)):
            raise BuildIdentityError("an installation receipt lists preserved paths as an array")
        installed_at = payload.get("installed_at")
        try:
            return cls(
                identity=BuildIdentity.from_payload(payload.get("identity")),
                manifest_sha256=_text(payload, "manifest_sha256").lower(),
                release_tag=_text(payload, "release_tag"),
                source_commit=_text(payload, "source_commit").lower(),
                install_root=_text(payload, "install_root"),
                installed_at=float(installed_at) if isinstance(installed_at, (int, float)) else 0.0,
                preserved_paths=tuple(str(item) for item in preserved),
            )
        except ManifestError as error:
            raise BuildIdentityError(f"the installation receipt is not usable: {error}") from error


class ReceiptStore:
    """The per-installation directory this updater keeps outside the product.

    Keyed by the installation path rather than shared, so two copies of Hanly
    on one machine do not read each other's receipts or overwrite each other's
    recovery pointer.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def receipt_path(self) -> Path:
        return self._directory / RECEIPT_NAME

    @property
    def manifest_root(self) -> Path:
        return self._directory / MANIFEST_DIRECTORY

    @property
    def pending_path(self) -> Path:
        return self._directory / PENDING_RECEIPT_NAME

    @property
    def previous_path(self) -> Path:
        return self._directory / PREVIOUS_RECEIPT_NAME

    def read_receipt(self) -> InstalledReceipt | None:
        """The receipt for this installation, or None when there is none.

        An unreadable or unusable receipt answers None as well: the caller's
        next step is the same either way, and it is never to assume ownership.
        """

        return self._read(self.receipt_path)

    def _read(self, path: Path) -> InstalledReceipt | None:
        text = _read_bounded(path, MAX_RECEIPT_BYTES)
        if text is None:
            return None
        try:
            return InstalledReceipt.from_payload(json.loads(text))
        except (json.JSONDecodeError, BuildIdentityError):
            return None

    def write_receipt(self, receipt: InstalledReceipt) -> Path:
        _write_atomic(self.receipt_path, receipt.to_json())
        return self.receipt_path

    def clear_receipt(self) -> None:
        try:
            self.receipt_path.unlink(missing_ok=True)
        except OSError:
            pass

    def stage_receipt(self, receipt: InstalledReceipt) -> Path:
        """Write the receipt a successful update will be entitled to.

        The previous one is kept beside it at the same time: a rollback has to
        put back what the installation was known to be, and by then the update
        directory is the only place that still knows.
        """

        current = self.read_receipt()
        if current is not None:
            _write_atomic(self.previous_path, current.to_json())
        else:
            _remove(self.previous_path)
        _write_atomic(self.pending_path, receipt.to_json())
        return self.pending_path

    def promote_pending(self, stamp: BuildStamp) -> InstalledReceipt | None:
        """Adopt the staged receipt, but only for the build that is running.

        Called by the new build once it has proved its own identity, which is
        what makes the receipt describe something that actually started.
        """

        pending = self._read(self.pending_path)
        if pending is None or not pending.describes(stamp):
            return None
        _write_atomic(self.receipt_path, pending.to_json())
        _remove(self.pending_path)
        _remove(self.previous_path)
        return pending

    def restore_previous(self) -> None:
        """Put back the receipt from before an update that did not commit.

        A build that never had one is left without one rather than given a
        borrowed identity.
        """

        previous = self._read(self.previous_path)
        if previous is None:
            self.clear_receipt()
        else:
            _write_atomic(self.receipt_path, previous.to_json())
        _remove(self.pending_path)
        _remove(self.previous_path)

    def manifest_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in _HEX for character in digest):
            raise BuildIdentityError("a stored manifest is named by its SHA-256 digest")
        return self.manifest_root / f"{digest}.json"

    def store_manifest(self, manifest: TreeManifest) -> Path:
        """Keep the manifest a receipt refers to, named by its own digest."""

        path = self.manifest_path(manifest.digest())
        _write_atomic(path, manifest.to_json())
        return path

    def read_manifest(self, digest: str) -> TreeManifest | None:
        """Read back a stored manifest, refusing one that is not what it claims."""

        text = _read_bounded(self.manifest_path(digest), MAX_STORED_MANIFEST_BYTES)
        if text is None:
            return None
        # The exact bytes, not the reparsed document: a digest over canonical
        # output would accept a file that had been edited and canonicalized.
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            return None
        try:
            return TreeManifest.from_json(text)
        except ManifestError:
            return None


def read_build_stamp(package: str = BUILD_STAMP_PACKAGE) -> BuildStamp | None:
    """The stamp this build carries, or None for a checkout that has none."""

    try:
        resource = resources.files(package).joinpath(BUILD_STAMP_NAME)
        if not resource.is_file():
            return None
        text = resource.read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError, FileNotFoundError):
        return None
    try:
        return BuildStamp.from_json(text)
    except BuildIdentityError:
        return None


def updates_root(environment: Any = None) -> Path:
    """Where every installation's update state lives, per user."""

    return default_app_config_path(environment).parent / UPDATES_DIRECTORY_NAME


def install_key(install_root: Path | str) -> str:
    """Name one installation by its canonical path, not by its contents.

    Windows and macOS reach one directory through several spellings, so the
    path is folded before it is hashed; Linux keeps the spelling it was given,
    where two differently cased paths really are two installations.
    """

    canonical = str(Path(install_root).expanduser().resolve())
    if sys.platform.startswith(("win32", "darwin")):
        canonical = os.path.normcase(canonical).casefold()
    if sys.platform.startswith("darwin"):
        canonical = unicodedata.normalize("NFC", canonical)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def receipt_store(install_root: Path | str, environment: Any = None) -> ReceiptStore:
    """The store belonging to one installation."""

    return ReceiptStore(updates_root(environment) / install_key(install_root))


def receipt_for(
    install_root: Path | str,
    manifest: TreeManifest,
    *,
    release_tag: str,
    source_commit: str,
    preserved_paths: tuple[str, ...] = (),
    now: float | None = None,
) -> InstalledReceipt:
    """Describe an installation this updater has just verified."""

    return InstalledReceipt(
        identity=manifest.identity,
        manifest_sha256=manifest.digest(),
        release_tag=release_tag,
        source_commit=source_commit,
        install_root=str(Path(install_root)),
        installed_at=time.time() if now is None else now,
        preserved_paths=preserved_paths,
    )


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BuildIdentityError(f"{key} must be a non-empty string")
    return value


def _read_bounded(path: Path, limit: int) -> str | None:
    """Read a small document, or None when it is absent, unreadable, or big."""

    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _write_atomic(path: Path, text: str) -> None:
    """Write a whole document or none of it, and make it durable."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.partial")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise BuildIdentityError(f"could not write {path}: {error}") from error


__all__ = [
    "BUILD_STAMP_NAME",
    "BUILD_STAMP_PACKAGE",
    "MANIFEST_DIRECTORY",
    "PENDING_RECEIPT_NAME",
    "PREVIOUS_RECEIPT_NAME",
    "RECEIPT_NAME",
    "UPDATES_DIRECTORY_NAME",
    "BuildIdentityError",
    "BuildStamp",
    "InstalledReceipt",
    "ReceiptStore",
    "install_key",
    "read_build_stamp",
    "receipt_for",
    "receipt_store",
    "updates_root",
]
