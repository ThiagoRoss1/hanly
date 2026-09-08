"""Build the Hanly Desktop application with the repository's spec.

Windows and Linux produce a onedir tree; macOS produces ``Hanly.app``, and
every path below follows that difference so callers ask the layout rather than
rebuilding the convention. The command intentionally builds only the
application: the KRDICT database is a resource artifact, not package data, and
the packaged process receives its path through ``--runtime-config``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def run_build(
    layout: PackageLayout,
    *,
    python_executable: Path | str | None = None,
    clean: bool = True,
    noconfirm: bool = True,
) -> int:
    """Run PyInstaller using the selected interpreter and return its status."""

    command = build_command(
        layout, python_executable=python_executable, clean=clean, noconfirm=noconfirm
    )
    completed = subprocess.run(command, cwd=layout.repo_root, check=False)
    if completed.returncode != 0:
        return completed.returncode

    try:
        products = [archive_application(layout)]
        if layout.platform_name == "macos":
            # Two products from one build: the ZIP the updater installs, and
            # the disk image a person downloads.
            products.append(create_disk_image(layout))
    except (OSError, PackagingError) as error:
        print(f"Hanly packaging: could not create application archive: {error}", file=sys.stderr)
        return 1
    for product in products:
        print(f"Hanly packaging: application artifact written to {product}")
    return 0


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
    )


if __name__ == "__main__":
    raise SystemExit(main())
