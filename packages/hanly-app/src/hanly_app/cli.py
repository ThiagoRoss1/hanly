"""The Python command forwards supported Hanly launch arguments to Tauri."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

RUN_COMMAND = "run"
NATIVE_EXECUTABLE_VARIABLE = "HANLY_DESKTOP_EXECUTABLE"
SELF_CHECK_MODES = ("inventory", "ocr", "worker", "ui")

ExecutableResolver = Callable[[], Path]
NativeRunner = Callable[[Path, Sequence[str]], int]


def parse_roi_size(value: str) -> tuple[int, int]:
    """Parse a ``WIDTHxHEIGHT`` capture size from the command line."""

    width, separator, height = value.lower().partition("x")
    if not separator or not width.isdigit() or not height.isdigit():
        raise argparse.ArgumentTypeError("ROI size must look like 200x100")
    if not all(0 < int(dimension) <= 4096 for dimension in (width, height)):
        raise argparse.ArgumentTypeError("ROI dimensions must be between 1 and 4096")
    return int(width), int(height)


def build_parser() -> argparse.ArgumentParser:
    """Build the supported launch argument parser."""

    parser = argparse.ArgumentParser(
        prog="hanly",
        description="Start Hanly: hover over Korean text to see what it means.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default=RUN_COMMAND,
        choices=(RUN_COMMAND,),
        help="start the desktop (the default, so plain `hanly` does the same)",
    )
    parser.add_argument("--runtime-config", type=Path, help="runtime/provider/resource JSON path")
    parser.add_argument("--app-config", type=Path, help="desktop preferences JSON path")
    parser.add_argument(
        "--roi",
        type=parse_roi_size,
        dest="roi_size",
        help="capture ROI as WIDTHxHEIGHT",
    )
    parser.add_argument("--trace", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--update-ready",
        dest="update_ready",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--update-ready-v2",
        dest="update_challenge",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--self-check",
        dest="self_check",
        choices=SELF_CHECK_MODES,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--self-check-image",
        dest="self_check_image",
        type=Path,
        help=argparse.SUPPRESS,
    )
    return parser


def resolve_native_executable() -> Path:
    """Find the existing Tauri executable; never build or fall back to Qt."""

    override = os.environ.get(NATIVE_EXECUTABLE_VARIABLE)
    if override:
        executable = Path(override).expanduser().resolve()
        if executable.is_file():
            return executable
        raise FileNotFoundError(
            f"{NATIVE_EXECUTABLE_VARIABLE} does not name a file: {executable}"
        )

    suffix = ".exe" if sys.platform == "win32" else ""
    repository_root = Path(__file__).resolve().parents[4]
    candidates = [
        repository_root
        / "apps"
        / "desktop"
        / "src-tauri"
        / "target"
        / "debug"
        / f"hanly-desktop{suffix}"
    ]
    installed = shutil.which(f"hanly-desktop{suffix}")
    if installed is not None:
        candidates.append(Path(installed))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "the Tauri executable is unavailable; build apps/desktop/src-tauri in debug "
        f"mode or set {NATIVE_EXECUTABLE_VARIABLE} to an existing native executable"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Forward the single Python command to the native desktop root."""

    multiprocessing.freeze_support()
    try:
        return run_hanly(argv)
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"Hanly: {error}", file=sys.stderr)
        return 2


def run_hanly(
    argv: Sequence[str] | None = None,
    *,
    executable_resolver: ExecutableResolver | None = None,
    native_runner: NativeRunner | None = None,
) -> int:
    """Run the native executable with the parsed, explicitly supported flags."""

    values = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(values)
    executable = (executable_resolver or resolve_native_executable)()
    runner = native_runner or launch_native_desktop
    return runner(executable, _native_arguments(args))


def _native_arguments(args: argparse.Namespace) -> list[str]:
    """Translate parser values into the Rust launcher's narrow argument set."""

    arguments: list[str] = []
    for name in ("runtime_config", "app_config"):
        path = getattr(args, name)
        if path is not None:
            flag = "--runtime-config" if name == "runtime_config" else "--app-config"
            arguments.extend((flag, _absolute(path)))
    roi = args.roi_size
    if roi is not None:
        arguments.extend(("--roi", f"{roi[0]}x{roi[1]}"))
    if args.trace:
        arguments.append("--trace")
    for name, flag in (
        ("update_ready", "--update-ready"),
        ("update_challenge", "--update-ready-v2"),
        ("self_check", "--self-check"),
        ("self_check_image", "--self-check-image"),
    ):
        value = getattr(args, name)
        if value is not None:
            arguments.extend((flag, _absolute(value) if isinstance(value, Path) else value))
    return arguments


def _absolute(path: Path) -> str:
    """Send local paths in the absolute form required by the private bridge."""

    return str(path.expanduser().resolve())


def launch_native_desktop(executable: Path, arguments: Sequence[str]) -> int:
    """Replace this launcher on POSIX and wait for the native root on Windows."""

    command = [str(executable), *arguments]
    if sys.platform == "win32":
        return subprocess.run(command, check=False).returncode
    os.execv(str(executable), command)
    raise AssertionError("execv returned without replacing the process")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "NATIVE_EXECUTABLE_VARIABLE",
    "SELF_CHECK_MODES",
    "build_parser",
    "launch_native_desktop",
    "main",
    "parse_roi_size",
    "resolve_native_executable",
    "run_hanly",
]
