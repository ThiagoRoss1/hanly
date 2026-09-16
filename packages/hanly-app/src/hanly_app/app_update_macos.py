"""The parts of a macOS update only macOS can do.

A ``.app`` is sealed. Its signature covers the executable, every nested binary,
and a hash of every resource, so an update that rebuilt any of that locally
would produce a bundle Gatekeeper refuses - and an updater that re-signed it
would be asserting an identity it does not have. So the published signature
material travels as ordinary file content and extended attributes, and the only
thing done here is to check that what was reassembled still verifies.

The full fallback is the disk image a person downloads, read the way a program
must read one: attached read-only at a private mount point nobody browsed into,
copied out with ``ditto`` so links and permissions survive, and detached again
whatever happens. Nothing is ever launched from a mounted image.

Ad-hoc signing is what this product carries today. ``codesign --verify`` proves
the bundle is internally consistent and unmodified; it does not establish that
Thiago published it, and nothing here says otherwise.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_manifest import TreeManifest
from .app_update_tree import BuiltCandidate, CandidateError, discard_candidate

#: macOS's own tools. Absolute paths: a tool found on ``PATH`` is whatever the
#: user's shell configuration put there.
DITTO = "/usr/bin/ditto"
HDIUTIL = "/usr/bin/hdiutil"
CODESIGN = "/usr/bin/codesign"
FIND = "/usr/bin/find"

#: What the bundle's own plist has to say about itself.
BUNDLE_IDENTIFIER = "io.github.thiagoross1.hanly"
INFO_PLIST = "Contents/Info.plist"
CODE_SIGNATURE = "Contents/_CodeSignature/CodeResources"

#: How long each native tool is given, and how much of its output is read. A
#: hung ``hdiutil`` must not hold an update open forever.
COMMAND_TIMEOUT_SECONDS = 300.0
MAX_OUTPUT_BYTES = 64 * 1024

#: The largest plist this reads. ``hdiutil``'s attach output lists a handful of
#: entities; an ``Info.plist`` is a few kilobytes.
MAX_PLIST_BYTES = 1024 * 1024

CommandRunner = Callable[..., Any]


class BundleError(CandidateError):
    """Raised when a macOS bundle or disk image is not what it must be."""


@dataclass(frozen=True, slots=True)
class AttachedImage:
    """One disk image this process attached, and is responsible for detaching."""

    device: str
    mount_point: Path


def acquire_disk_image(
    destination: Path,
    image: Path,
    manifest: TreeManifest,
    *,
    runner: CommandRunner = subprocess.run,
) -> BuiltCandidate:
    """Copy the published bundle out of its disk image into the candidate.

    The image has already been proved against the release's digest; what is
    checked here is shape. It carries exactly one volume, that volume holds
    exactly the expected application, and what comes out is compared against
    the same manifest a reconstructed candidate is.
    """

    with mounted_image(image, runner=runner) as mount_point:
        bundle = mount_point / manifest.layout.root
        if bundle.is_symlink() or not bundle.is_dir():
            raise BundleError(f"the disk image does not contain {manifest.layout.root}")
        copy_bundle(bundle, destination, runner=runner)
    return BuiltCandidate(
        root=Path(destination), manifest=manifest, payload_bytes=manifest.total_size
    )


@contextmanager
def mounted_image(
    image: Path, *, runner: CommandRunner = subprocess.run
) -> Iterator[Path]:
    """Attach one image read-only where nothing else will find it, then detach.

    ``-nobrowse`` keeps it out of Finder and ``-mountrandom`` into a directory
    this process made, so the mount is not a volume a person can wander into
    and not one another program can be holding open. Detaching names the exact
    device this attach produced: unmounting by path would be unmounting
    whatever is at that path now.
    """

    holder = Path(tempfile.mkdtemp(prefix="hanly-update-image."))
    attached: AttachedImage | None = None
    try:
        attached = _attach(image, holder, runner)
        yield attached.mount_point
    finally:
        if attached is not None:
            _detach(attached, runner)
        _discard(holder)


def copy_bundle(
    source: Path, destination: Path, *, runner: CommandRunner = subprocess.run
) -> Path:
    """Copy one application with ``ditto``, which is what keeps it an application.

    A copy written by Python loses the bundle's symlinks, its permission bits,
    and its extended attributes, and what is left no longer launches or
    verifies.
    """

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise BundleError(f"{target} already exists")
    try:
        _run(runner, [DITTO, str(source), str(target)], "could not copy the application")
    except BundleError:
        discard_candidate(target)
        raise
    return target


def require_bundle_identity(
    bundle: Path, *, version: str, executable: str, identifier: str = BUNDLE_IDENTIFIER
) -> None:
    """Refuse a bundle that is not this application, at this version.

    Both version keys are read, not one: a bundle whose short string says the
    new version and whose build version says the old one is a packaging defect
    that would otherwise install silently.
    """

    if not (bundle / CODE_SIGNATURE).is_file():
        raise BundleError("the new application carries no signature")
    information = _read_plist(bundle / INFO_PLIST, "the application's Info.plist")

    if information.get("CFBundleIdentifier") != identifier:
        raise BundleError("the new application is not Hanly")
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        if str(information.get(key) or "") != version:
            raise BundleError(f"the new application's {key} is not {version}")
    if not bundle.joinpath(*executable.split("/")).is_file():
        raise BundleError(f"the new application has no program at {executable}")


def require_valid_signature(
    bundle: Path, *, runner: CommandRunner = subprocess.run
) -> None:
    """Prove the bundle verifies as a whole, nested code included.

    ``--deep --strict`` is what reaches the frameworks and helpers inside, so a
    resource that travelled wrongly fails here rather than at launch. This says
    the bundle is intact and self-consistent; with an ad-hoc signature it says
    nothing at all about who produced it.
    """

    _run(
        runner,
        [CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(bundle)],
        "the new application did not pass macOS signature verification",
    )


def require_no_unsupported_metadata(
    root: Path, *, runner: CommandRunner = subprocess.run
) -> None:
    """Refuse a tree carrying access-control metadata a manifest cannot describe.

    A clean build has none. One that acquired an ACL would be reproduced
    without it, so the producer stops rather than publishing a manifest that
    does not describe what it claims to.
    """

    completed = _run(
        runner,
        [FIND, str(root), "-acl"],
        "could not check the application for access-control metadata",
    )
    listed = _output(completed).strip()
    if listed:
        first = listed.splitlines()[0]
        raise BundleError(f"{first} carries an access-control list this update cannot reproduce")


def _attach(image: Path, holder: Path, runner: CommandRunner) -> AttachedImage:
    """Attach the image and read back exactly which device and path resulted."""

    completed = _run(
        runner,
        [
            HDIUTIL,
            "attach",
            str(image),
            "-readonly",
            "-nobrowse",
            "-noautoopen",
            "-noverify",
            "-mountrandom",
            str(holder),
            "-plist",
        ],
        "could not open the downloaded disk image",
    )
    entities = _mounted_entities(_output_bytes(completed))
    if len(entities) != 1:
        _detach_all(entities, runner)
        raise BundleError("the downloaded disk image does not hold exactly one volume")
    return entities[0]


def _mounted_entities(payload: bytes) -> list[AttachedImage]:
    """Read ``hdiutil``'s own report of what it attached, and where."""

    if len(payload) > MAX_PLIST_BYTES:
        raise BundleError("the disk image reported more than this build reads")
    try:
        parsed = plistlib.loads(payload)
    except (ValueError, plistlib.InvalidFileException) as error:
        raise BundleError(f"the disk image could not be read: {error}") from error

    entities = parsed.get("system-entities") if isinstance(parsed, dict) else None
    if not isinstance(entities, list):
        raise BundleError("the disk image reported nothing that could be mounted")
    found: list[AttachedImage] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        device = entity.get("dev-entry")
        mount_point = entity.get("mount-point")
        if isinstance(device, str) and isinstance(mount_point, str) and mount_point:
            found.append(AttachedImage(device=device, mount_point=Path(mount_point)))
    return found


def _detach(attached: AttachedImage, runner: CommandRunner) -> None:
    """Detach the exact device this process attached, and say so if it will not.

    A failure is recorded rather than escalated: forcing an unmount would be
    acting on a volume this update may no longer be the only user of.
    """

    try:
        _run(
            runner,
            [HDIUTIL, "detach", attached.device],
            "could not close the downloaded disk image",
        )
    except BundleError:
        raise BundleError(
            f"the downloaded disk image is still attached at {attached.mount_point}. "
            f"Eject it from Finder, or run: hdiutil detach {attached.device}"
        ) from None


def _detach_all(entities: list[AttachedImage], runner: CommandRunner) -> None:
    for entity in entities:
        try:
            _run(runner, [HDIUTIL, "detach", entity.device], "detach")
        except BundleError:
            continue


def _read_plist(path: Path, what: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise BundleError(f"{what} is missing")
        if path.stat().st_size > MAX_PLIST_BYTES:
            raise BundleError(f"{what} is larger than this build reads")
        parsed = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise BundleError(f"{what} could not be read: {error}") from error
    if not isinstance(parsed, dict):
        raise BundleError(f"{what} is not a property list")
    return parsed


def _run(runner: CommandRunner, command: list[str], failure: str) -> Any:
    """Run one macOS tool with a bound on how long and how much it may say."""

    try:
        completed = runner(
            command, check=False, capture_output=True, timeout=COMMAND_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BundleError(f"{failure}: {error}") from error
    if getattr(completed, "returncode", 1) != 0:
        detail = _output(completed, stream="stderr").strip()
        raise BundleError(f"{failure}: {detail or command[0]}")
    return completed


def _output(completed: Any, stream: str = "stdout") -> str:
    return _output_bytes(completed, stream).decode("utf-8", "replace")


def _output_bytes(completed: Any, stream: str = "stdout") -> bytes:
    value = getattr(completed, stream, b"") or b""
    if isinstance(value, str):
        value = value.encode("utf-8", "replace")
    return value[:MAX_OUTPUT_BYTES]


def _discard(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


__all__ = [
    "BUNDLE_IDENTIFIER",
    "CODESIGN",
    "COMMAND_TIMEOUT_SECONDS",
    "DITTO",
    "HDIUTIL",
    "AttachedImage",
    "BundleError",
    "acquire_disk_image",
    "copy_bundle",
    "mounted_image",
    "require_bundle_identity",
    "require_no_unsupported_metadata",
    "require_valid_signature",
]
