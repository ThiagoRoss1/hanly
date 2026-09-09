"""The Hanly command.

This is the only entry point. The installed ``hanly`` script, ``python -m
hanly_app``, and the packaged executable all call :func:`main`; there is no
second way to start the desktop.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from .application import (
    DesktopApplicationError,
    report_startup_error,
    resolve_runtime_config,
    run_desktop,
)
from .control_center import ControlCenterUnavailable
from .diagnostics import DiagnosticLog, StartupTimeline, open_diagnostics
from .first_run import FirstRunError
from .ocr_preload import record_preload_timing
from .runtime import RuntimeConfigError
from .self_check import (
    RUNTIME_SELF_CHECK_MODES,
    SELF_CHECK_MODES,
    report_self_check,
)

RuntimeResolver = Callable[[Path | None], Path]
DesktopRunner = Callable[..., int]

#: Written into the configuration's help text, and the default when the
#: packaged executable is launched with no arguments at all.
RUN_COMMAND = "run"


def parse_roi_size(value: str) -> tuple[int, int]:
    """Parse a ``WIDTHxHEIGHT`` capture size from the command line."""

    width, separator, height = value.lower().partition("x")
    if not separator or not width.isdigit() or not height.isdigit():
        raise argparse.ArgumentTypeError("ROI size must look like 200x100")
    if int(width) <= 0 or int(height) <= 0:
        raise argparse.ArgumentTypeError("ROI dimensions must be positive")
    return int(width), int(height)


def build_parser() -> argparse.ArgumentParser:
    """Build the one parser Hanly has."""

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
    parser.add_argument(
        "--runtime-config",
        type=Path,
        help=(
            "runtime/provider/resource JSON configuration "
            "(default: runtime.json beside the executable or in the settings directory)"
        ),
    )
    parser.add_argument(
        "--app-config",
        type=Path,
        help="optional desktop preferences JSON path",
    )
    parser.add_argument(
        "--roi",
        type=parse_roi_size,
        dest="roi_size",
        help="capture ROI as WIDTHxHEIGHT, for comparing detection areas",
    )
    # Internal: the packaging harness drives the real runtime through this one
    # entry point rather than through a second application.
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


def main(argv: Sequence[str] | None = None) -> NoReturn:
    """Run Hanly, reporting a startup failure rather than raising, then leave."""

    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    # Opened before the OCR runtime and Qt so a native initialization failure
    # is already being written somewhere the user can find it.
    diagnostics = open_diagnostics()
    # The packaged runtime hook preloads OCR before this log exists, so its
    # measurement is claimed here rather than measured a second time.
    record_preload_timing(StartupTimeline(diagnostics))
    try:
        status = _start(
            args,
            runtime_resolver=resolve_runtime_config,
            desktop_runner=run_desktop,
            diagnostics=diagnostics,
        )
    except (
        ControlCenterUnavailable,
        DesktopApplicationError,
        FirstRunError,
        RuntimeConfigError,
        OSError,
        ValueError,
    ) as error:
        diagnostics.report("Startup", error)
        # A self-check is machine-driven: reporting it through a modal dialog
        # would leave the process waiting for a click nobody is there to make.
        report_startup_error(error, log_path=diagnostics.path, interactive=not args.self_check)
        status = 2
    _leave(status)


def _leave(status: int) -> NoReturn:
    """End the process now, rather than during interpreter finalization."""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    _terminate_without_unloading(status)
    os._exit(status)


def _terminate_without_unloading(status: int) -> None:
    """End a Windows process without unloading the libraries it has loaded."""

    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    # Untyped, the pseudo-handle is narrowed to 32 bits and the call fails.
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.TerminateProcess(kernel32.GetCurrentProcess(), status)


def run_hanly(
    argv: Sequence[str] | None = None,
    *,
    runtime_resolver: RuntimeResolver = resolve_runtime_config,
    desktop_runner: DesktopRunner = run_desktop,
) -> int:
    """Injectable form of :func:`main` that lets a caller supply the seams."""

    return _start(
        build_parser().parse_args(list(argv or ())),
        runtime_resolver=runtime_resolver,
        desktop_runner=desktop_runner,
    )


def _start(
    args: argparse.Namespace,
    *,
    runtime_resolver: RuntimeResolver,
    desktop_runner: DesktopRunner,
    diagnostics: DiagnosticLog | None = None,
) -> int:
    """Start the desktop, or run the internal diagnostic mode.

    Nothing is asked before the interface opens. Resource resolution and
    provisioning happen inside the desktop, behind an already-visible window,
    so a launch cannot stall on a prompt or a download.
    """

    mode = getattr(args, "self_check", None)
    if mode:
        # The window check opens the shell before any resource exists, exactly
        # as a launch does, so resolving one would provision what it must not.
        return report_self_check(
            runtime_resolver(args.runtime_config)
            if mode in RUNTIME_SELF_CHECK_MODES
            else None,
            mode=mode,
            image=getattr(args, "self_check_image", None),
        )

    return desktop_runner(
        args.runtime_config,
        app_config=args.app_config,
        roi_size=args.roi_size,
        diagnostics=diagnostics,
        runtime_resolver=runtime_resolver,
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main", "parse_roi_size", "run_hanly"]
