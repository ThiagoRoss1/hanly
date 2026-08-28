"""The Hanly command.

This is the only entry point. The installed ``hanly`` script, ``python -m
hanly_app``, and the packaged executable all call :func:`main`; there is no
second way to start the desktop.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .application import (
    DesktopApplicationError,
    report_startup_error,
    resolve_runtime_config,
    run_desktop,
)
from .capture_selector import CaptureSelection, CaptureSelectorError, select_capture_area
from .first_run import FirstRunError
from .runtime import RuntimeConfigError

Selector = Callable[[], CaptureSelection | None]
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run Hanly, reporting a startup failure rather than raising."""

    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    try:
        return _start(
            args,
            selector=select_capture_area,
            runtime_resolver=resolve_runtime_config,
            desktop_runner=run_desktop,
        )
    except (
        CaptureSelectorError,
        DesktopApplicationError,
        FirstRunError,
        RuntimeConfigError,
        OSError,
        ValueError,
    ) as error:
        report_startup_error(error)
        return 2


def run_selected_desktop(
    argv: Sequence[str] | None = None,
    *,
    selector: Selector = select_capture_area,
    runtime_resolver: RuntimeResolver = resolve_runtime_config,
    desktop_runner: DesktopRunner = run_desktop,
) -> int:
    """Injectable form of :func:`main` that lets a caller supply the seams."""

    return _start(
        build_parser().parse_args(list(argv or ())),
        selector=selector,
        runtime_resolver=runtime_resolver,
        desktop_runner=desktop_runner,
    )


def _start(
    args: argparse.Namespace,
    *,
    selector: Selector,
    runtime_resolver: RuntimeResolver,
    desktop_runner: DesktopRunner,
) -> int:
    """Ask which area to watch, then start the desktop on that choice.

    Cancelling returns before the runtime configuration is resolved, so it
    never provisions resources or contacts the release channel.
    """

    selection = selector()
    if selection is None:
        return 0
    return desktop_runner(
        runtime_resolver(args.runtime_config),
        app_config=args.app_config,
        initial_capture_mode=selection.capture_mode,
        initial_capture_region=selection.region,
        roi_size=args.roi_size,
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main", "parse_roi_size", "run_selected_desktop"]
