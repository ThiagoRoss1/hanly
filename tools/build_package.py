"""Build the Hanly Desktop application with the repository's spec.

Windows and Linux produce a onedir tree; macOS produces ``Hanly.app``, and
every path below follows that difference so callers ask the layout rather than
rebuilding the convention. The command intentionally builds only the
application: the KRDICT database is a resource artifact, not package data, and
the packaged process receives its path through ``--runtime-config``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.update_artifacts`` cannot be imported.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hanly_app.app_build_identity import BuildStamp
from hanly_app.app_manifest import TreeLayout, TreeManifest

from tools.update_artifacts import (
    ArtifactError,
    ReleaseProducts,
    build_platform_release,
    build_release_products,
    generate_manifest,
    host_architecture,
    load_base_package_manifest,
    write_build_stamp,
)

APPLICATION_STEM = "hanly-desktop"
RESOURCE_ARCHIVE_STEM = "hanly-resources"
SUPPORTED_PLATFORMS = ("windows", "macos", "linux")

#: The macOS product directory, and the executable inside it.
BUNDLE_NAME = "Hanly.app"
BUNDLE_EXECUTABLE_PARTS = ("Contents", "MacOS", APPLICATION_STEM)

#: What a mounted Hanly disk image is called.
BUNDLE_VOLUME_NAME = "Hanly"

#: macOS's own tools: ``ditto`` carries an application's symlinks and
#: permissions through a ZIP, ``hdiutil`` makes a disk image. Neither modifies
#: the built application.
DITTO = "/usr/bin/ditto"
HDIUTIL = "/usr/bin/hdiutil"

#: The native updater, and how it is built. Warnings are errors: it runs when
#: the application it is repairing cannot, so a compiler diagnostic in it is
#: not something to notice later.
NATIVE_HELPER_NAME = "hanly-update-posix"
NATIVE_HELPER_SOURCE = Path("packaging") / "updater" / f"{NATIVE_HELPER_NAME}.c"
NATIVE_HELPER_FLAGS = ("-std=c11", "-Wall", "-Wextra", "-Werror", "-O2")

#: What each platform publishes its whole product as, in the update package.
FULL_FORMATS = {"windows": "zip", "macos": "dmg", "linux": "tar.gz"}

CommandRunner = Callable[..., Any]


class PackagingError(RuntimeError):
    """Raised when a native packaging tool could not produce its artifact."""


def host_platform(platform_name: str | None = None) -> str:
    """Return the packaging platform name used by artifact handoff tooling."""

    value = sys.platform if platform_name is None else platform_name
    normalized = value.strip().lower()
    if normalized in {"win32", "windows", "cygwin", "msys"}:
        return "windows"
    if normalized in {"darwin", "macos", "osx"}:
        return "macos"
    if normalized.startswith("linux"):
        return "linux"
    raise ValueError(
        f"unsupported packaging platform {value!r}; "
        f"choose one of {', '.join(SUPPORTED_PLATFORMS)}"
    )


@dataclass(frozen=True, slots=True)
class PackageLayout:
    """Paths shared by local packaging and later release handoff work.

    Both fields are already normalized; build one with :meth:`for_platform`
    rather than normalizing a repository root and platform name at each site.
    """

    repo_root: Path
    platform_name: str

    @classmethod
    def for_platform(
        cls, repo_root: Path | str, platform_name: str | None = None
    ) -> PackageLayout:
        """Resolve a repository root and platform selection into a layout."""

        return cls(Path(repo_root).resolve(), host_platform(platform_name))

    @property
    def dist_root(self) -> Path:
        return self.repo_root / "dist" / self.platform_name

    @property
    def payload_name(self) -> str:
        """What PyInstaller writes into ``dist_root``: an app, or a onedir."""

        return BUNDLE_NAME if self.platform_name == "macos" else APPLICATION_STEM

    @property
    def application_directory(self) -> Path:
        return self.dist_root / self.payload_name

    @property
    def executable(self) -> Path:
        if self.platform_name == "macos":
            return self.application_directory.joinpath(*BUNDLE_EXECUTABLE_PARTS)
        suffix = ".exe" if self.platform_name == "windows" else ""
        return self.application_directory / f"{APPLICATION_STEM}{suffix}"

    @property
    def application_archive(self) -> Path:
        """The archive a release publishes, and the updater downloads.

        macOS ships a ZIP for the same reason Windows does: it is the format
        that survives a bundle's symlinks and is cheap to verify. The DMG
        beside it is for people, never for the updater.
        """

        extension = ".tar.gz" if self.platform_name == "linux" else ".zip"
        return self.repo_root / "dist" / f"{APPLICATION_STEM}-{self.platform_name}{extension}"

    @property
    def application_dmg(self) -> Path:
        """The macOS download a person opens; not an update input."""

        if self.platform_name != "macos":
            raise ValueError("a disk image is a macOS product only")
        return self.repo_root / "dist" / f"{APPLICATION_STEM}-macos.dmg"

    @property
    def update_metadata_directory(self) -> Path:
        """Where the manifest, delta, and update metadata are written.

        Beside the archives, because they are release assets published with
        them rather than anything the application tree contains.
        """

        return self.repo_root / "dist"

    @property
    def update_product(self) -> Path:
        """The whole product a HUP client downloads when it needs one.

        macOS is the disk image: it and the ZIP come from the same finished
        bundle, and the image is what a person already downloads.
        """

        return self.application_dmg if self.platform_name == "macos" else self.application_archive

    @property
    def platform_release_directory(self) -> Path:
        """Where this platform's manifest, delta, and descriptor are written."""

        return self.repo_root / "dist" / "release" / self.platform_name

    @property
    def native_helper(self) -> Path:
        """Where the POSIX update helper is compiled before the build runs."""

        return self.repo_root / "dist" / ".native" / self.platform_name / NATIVE_HELPER_NAME

    @property
    def work_root(self) -> Path:
        return self.repo_root / "dist" / ".pyinstaller" / self.platform_name

    @property
    def spec_path(self) -> Path:
        return self.repo_root / "packaging" / "hanly-desktop.spec"


def build_command(
    layout: PackageLayout,
    *,
    python_executable: Path | str | None = None,
    clean: bool = True,
    noconfirm: bool = True,
) -> list[str]:
    """Build the deterministic PyInstaller command without executing it."""

    interpreter = sys.executable if python_executable is None else str(python_executable)
    command = [interpreter, "-m", "PyInstaller"]
    if noconfirm:
        command.append("--noconfirm")
    if clean:
        command.append("--clean")
    command.extend(
        [
            "--distpath",
            str(layout.dist_root),
            "--workpath",
            str(layout.work_root),
            str(layout.spec_path),
        ]
    )
    return command


def archive_application(
    layout: PackageLayout,
    *,
    runner: CommandRunner = subprocess.run,
) -> Path:
    """Archive a successful build using the platform handoff format.

    The macOS application is archived with ``ditto`` rather than ``zipfile``:
    a Python-written ZIP loses the bundle's symlinks and permission bits, and
    what unpacks from it is no longer an application that launches or verifies.
    """

    if not layout.application_directory.is_dir():
        raise FileNotFoundError(
            f"PyInstaller output directory does not exist: {layout.application_directory}"
        )

    if layout.platform_name == "macos":
        return _archive_bundle(layout, runner)

    archive_path = layout.application_archive
    archive_format = "gztar" if layout.platform_name == "linux" else "zip"
    archive_base = archive_path.parent / f"{APPLICATION_STEM}-{layout.platform_name}"
    created = Path(
        shutil.make_archive(
            str(archive_base),
            archive_format,
            root_dir=layout.dist_root,
            base_dir=layout.payload_name,
        )
    )
    return created.resolve()


def _archive_bundle(layout: PackageLayout, runner: CommandRunner) -> Path:
    """Write the ZIP the updater consumes, from the application as built."""

    archive = layout.application_archive
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    _run_native(
        runner,
        [
            DITTO,
            "-c",
            "-k",
            "--sequesterRsrc",
            # The archive holds ``Hanly.app/...`` so what unpacks from it is the
            # application itself, which is what the updater installs.
            "--keepParent",
            str(layout.application_directory),
            str(archive),
        ],
        "could not archive the application bundle",
    )
    return archive.resolve()


def create_disk_image(
    layout: PackageLayout,
    *,
    runner: CommandRunner = subprocess.run,
) -> Path:
    """Build the disk image a person downloads, from the same application.

    The DMG is never an update input: it is a container a human mounts and
    drags out of. The signed application is read, not modified.
    """

    if not layout.application_directory.is_dir():
        raise FileNotFoundError(
            f"PyInstaller output directory does not exist: {layout.application_directory}"
        )

    image = layout.application_dmg
    image.parent.mkdir(parents=True, exist_ok=True)
    image.unlink(missing_ok=True)
    _run_native(
        runner,
        [
            HDIUTIL,
            "create",
            "-volname",
            BUNDLE_VOLUME_NAME,
            "-srcfolder",
            str(layout.application_directory),
            "-ov",
            "-format",
            "UDZO",
            str(image),
        ],
        "could not create the application disk image",
    )
    return image.resolve()


def _run_native(runner: CommandRunner, command: list[str], failure: str) -> None:
    """Run one macOS packaging tool, reporting what it said when it fails."""

    completed = runner(command, check=False, capture_output=True)
    if getattr(completed, "returncode", 1) != 0:
        detail = getattr(completed, "stderr", b"") or b""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        raise PackagingError(f"{failure}: {detail.strip() or command[0]}")


def build_native_helper(
    repo_root: Path,
    destination: Path,
    *,
    compiler: str | None = None,
    runner: CommandRunner = subprocess.run,
) -> Path:
    """Compile the POSIX update helper into a finished build.

    It goes beside the executable so it is inside the macOS bundle before that
    bundle is signed: a binary added afterwards would break the seal. Windows
    has its own helper and needs none of this.
    """

    source = Path(repo_root) / NATIVE_HELPER_SOURCE
    if not source.is_file():
        raise PackagingError(f"the update helper source is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run_native(
        runner,
        [compiler or "cc", *NATIVE_HELPER_FLAGS, "-o", str(destination), str(source)],
        "could not build the update helper",
    )
    destination.chmod(0o755)
    return destination


def product_version() -> str:
    """The version the build carries, read the way the application reads it."""

    return metadata.version("hanly-app")


def write_update_artifacts(layout: PackageLayout) -> ReleaseProducts:
    """Produce the schema-1 documents an older Windows client still reads.

    Full-only from the HUP era on: a client that understands these has always
    supported the whole-archive branch, and publishing a second, legacy-only
    delta to save one bootstrap download would add a second thing to keep
    correct for the rest of that generation's life.
    """

    return build_release_products(
        layout.application_directory,
        layout.application_archive,
        product_version(),
        layout.update_metadata_directory,
        delta_reason=(
            "this release publishes its differential updates through its update package"
        ),
    )


def run_build(
    layout: PackageLayout,
    *,
    python_executable: Path | str | None = None,
    clean: bool = True,
    noconfirm: bool = True,
    source_commit: str | None = None,
    architecture: str | None = None,
    base_package: Path | None = None,
    base_checksums: Path | None = None,
) -> int:
    """Freeze the application and produce everything its release publishes.

    The order matters and is the same everywhere: the build's identity goes in
    before it is frozen, the compatibility inventory goes in before the archive
    that carries it, and the manifest a release publishes is read from the
    finished, signed tree afterwards. The one update package is assembled from
    every platform's products by a later job, never here.
    """

    stamp = _stamp_build(layout, source_commit, architecture)
    environment = dict(os.environ)
    windows = layout.platform_name == "windows"
    if not windows:
        # Before PyInstaller, not after: macOS signs the bundle as it builds
        # it, and a binary added to a sealed bundle is one that no longer
        # verifies. Windows has its own helper and needs none of this.
        try:
            environment["HANLY_UPDATE_HELPER"] = str(
                build_native_helper(layout.repo_root, layout.native_helper)
            )
        except (OSError, PackagingError) as error:
            print(f"Hanly packaging: {error}", file=sys.stderr)
            return 1

    command = build_command(
        layout, python_executable=python_executable, clean=clean, noconfirm=noconfirm
    )
    completed = subprocess.run(command, cwd=layout.repo_root, check=False, env=environment)
    if completed.returncode != 0:
        return completed.returncode

    try:
        products = _release_products(layout, stamp, base_package, base_checksums)
    except (OSError, PackagingError, ArtifactError) as error:
        print(f"Hanly packaging: could not produce the release artifacts: {error}", file=sys.stderr)
        return 1
    for product in products:
        print(f"Hanly packaging: application artifact written to {product}")
    return 0


def _stamp_build(
    layout: PackageLayout, source_commit: str | None, architecture: str | None
) -> BuildStamp:
    """Give this freeze an identity, before there is anything to identify."""

    return write_build_stamp(
        layout.repo_root / "packages" / "hanly-app" / "src" / "hanly_app",
        platform_name=layout.platform_name,
        architecture=architecture or host_architecture(),
        version=product_version(),
        source_commit=source_commit or _source_commit(layout.repo_root),
    )


def _source_commit(repo_root: Path) -> str:
    """The commit this build is being made from, for a local build with none."""

    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or len(commit) != 40:
        raise PackagingError(
            "this build has no source commit; pass --source-commit for a build outside a checkout"
        )
    return commit


def _release_products(
    layout: PackageLayout,
    stamp: BuildStamp,
    base_package: Path | None,
    base_checksums: Path | None,
) -> list[Path]:
    """Everything the finished tree yields, in the order its parts depend on."""

    windows = layout.platform_name == "windows"
    if windows:
        # Before archiving: the compatibility inventory belongs inside the
        # build, so a fresh installation carries what an older client reads.
        generate_manifest(layout.application_directory, product_version())

    products = [archive_application(layout)]
    if layout.platform_name == "macos":
        # Two products from one build: the disk image a person downloads and
        # a HUP client installs, and the ZIP an older client still needs.
        products.append(create_disk_image(layout))

    products.extend(write_platform_release(layout, stamp, base_package, base_checksums))
    if windows:
        products.extend(write_update_artifacts(layout).paths())
    return products


def write_platform_release(
    layout: PackageLayout,
    stamp: BuildStamp,
    base_package: Path | None = None,
    base_checksums: Path | None = None,
) -> tuple[Path, ...]:
    """Produce this platform's schema-2 manifest, delta, and descriptor."""

    base, reason = _base_manifest(stamp, base_package, base_checksums)
    release = build_platform_release(
        layout.application_directory,
        stamp,
        _tree_layout(layout),
        layout.update_product,
        layout.platform_release_directory,
        full_format=FULL_FORMATS[layout.platform_name],
        base=base,
        base_reason=reason,
    )
    written = [release.manifest_path, release.descriptor_path]
    if release.delta is not None:
        written.append(layout.platform_release_directory / release.delta.payload.name)
    return tuple(written)


def _base_manifest(
    stamp: BuildStamp, base_package: Path | None, base_checksums: Path | None
) -> tuple[TreeManifest | None, str]:
    """Read the predecessor this platform diffs against, or say why it cannot.

    A missing or unusable predecessor never fails a build: the first HUP-aware
    release has none by definition, and a release that stopped because it could
    not diff would be worse than one that ships the whole product.
    """

    if base_package is None:
        return None, "no previous published update package was supplied"
    try:
        return (
            load_base_package_manifest(
                base_package,
                base_checksums,
                platform_name=stamp.platform,
                architecture=stamp.architecture,
            ),
            "",
        )
    except ArtifactError as error:
        return None, str(error)


def _tree_layout(layout: PackageLayout) -> TreeLayout:
    """What an installation of this platform's product is called and runs."""

    executable = layout.executable.relative_to(layout.application_directory).as_posix()
    mode = None if layout.platform_name == "windows" else 0o755
    return TreeLayout(root=layout.payload_name, executable=executable, mode=mode)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Hanly Desktop onedir application with PyInstaller"
    )
    parser.add_argument(
        "--platform",
        dest="platform_name",
        choices=SUPPORTED_PLATFORMS,
        help="artifact platform (defaults to the current host)",
    )
    parser.add_argument(
        "--python-executable",
        type=Path,
        help="Python interpreter that provides PyInstaller (defaults to this interpreter)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="keep PyInstaller's analysis cache",
    )
    parser.add_argument(
        "--no-noconfirm",
        action="store_true",
        help="allow PyInstaller to ask before replacing an existing artifact",
    )
    parser.add_argument(
        "--source-commit",
        help="the commit this build is made from (defaults to the checkout's HEAD)",
    )
    parser.add_argument(
        "--architecture",
        help="the machine this build targets (defaults to the host's)",
    )
    parser.add_argument(
        "--base-package",
        type=Path,
        help="the previous release's published update package, to diff against",
    )
    parser.add_argument(
        "--base-checksums",
        type=Path,
        help="that release's SHA256SUMS, which proves the package is its own",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the platform-aware command without running PyInstaller",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python tools/build_package.py``."""

    args = _build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    layout = PackageLayout.for_platform(root, args.platform_name)

    if args.dry_run:
        command = build_command(
            layout,
            python_executable=args.python_executable,
            clean=not args.no_clean,
            noconfirm=not args.no_noconfirm,
        )
        print(subprocess.list2cmdline(command))
        return 0

    return run_build(
        layout,
        python_executable=args.python_executable,
        clean=not args.no_clean,
        noconfirm=not args.no_noconfirm,
        source_commit=args.source_commit,
        architecture=args.architecture,
        base_package=args.base_package,
        base_checksums=args.base_checksums,
    )


if __name__ == "__main__":
    raise SystemExit(main())
