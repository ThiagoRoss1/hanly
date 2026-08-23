"""Build the Hanly Desktop onedir application with the repository's spec.

The command intentionally builds only the executable application. OCR model
directories and the KRDICT database are resource artifacts, not package data;
the packaged process receives their paths through ``--runtime-config``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

APPLICATION_STEM = "hanly-desktop"
RESOURCE_ARCHIVE_STEM = "hanly-resources"
SUPPORTED_PLATFORMS = ("windows", "macos", "linux")


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
    def application_directory(self) -> Path:
        return self.dist_root / APPLICATION_STEM

    @property
    def executable(self) -> Path:
        suffix = ".exe" if self.platform_name == "windows" else ""
        return self.application_directory / f"{APPLICATION_STEM}{suffix}"

    @property
    def application_archive(self) -> Path:
        """The archive path reserved for HAN-29 release metadata."""

        extension = ".zip" if self.platform_name == "windows" else ".tar.gz"
        return self.repo_root / "dist" / f"{APPLICATION_STEM}-{self.platform_name}{extension}"

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


def archive_application(layout: PackageLayout) -> Path:
    """Archive a successful onedir output using the platform handoff format."""

    if not layout.application_directory.is_dir():
        raise FileNotFoundError(
            f"PyInstaller output directory does not exist: {layout.application_directory}"
        )

    archive_path = layout.application_archive
    archive_format = "zip" if layout.platform_name == "windows" else "gztar"
    archive_base = archive_path.parent / f"{APPLICATION_STEM}-{layout.platform_name}"
    created = Path(
        shutil.make_archive(
            str(archive_base),
            archive_format,
            root_dir=layout.dist_root,
            base_dir=APPLICATION_STEM,
        )
    )
    return created.resolve()


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
        archive = archive_application(layout)
    except OSError as error:
        print(f"Hanly packaging: could not create application archive: {error}", file=sys.stderr)
        return 1
    print(f"Hanly packaging: application archive written to {archive}")
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
