"""Terminal workflows for launching the Hanly desktop."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from . import application as desktop_application
from .application import DesktopApplicationError, parse_roi_size, run_desktop
from .bootstrap import DEFAULT_OCR_RUNTIME_MODULE
from .capture_selector import CaptureSelection, CaptureSelectorError, select_capture_area
from .resource_bootstrap import RuntimeBootstrapError
from .runtime import RuntimeConfigError, read_ocr_backend

Selector = Callable[[str], CaptureSelection | None]
RuntimeResolver = Callable[[Path | None], Path]
DesktopRunner = Callable[..., int]


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--app-config", type=Path)
    parser.add_argument("--roi", type=parse_roi_size, dest="roi_size")
    return parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hanly", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run",
        parents=[_run_parser()],
        help="choose a capture area and start the Hanly desktop",
    )
    run.set_defaults(handler="run")
    return parser


def run_selected_desktop(
    argv: Sequence[str] | None = None,
    *,
    selector: Selector = select_capture_area,
    runtime_resolver: RuntimeResolver = desktop_application._resolve_runtime_config,
    desktop_runner: DesktopRunner = run_desktop,
) -> int:
    """Select one session area, then start the normal desktop composition."""

    args = _run_parser().parse_args(argv)
    selection = selector(_configured_ocr_module(args.runtime_config))
    if selection is None:
        return 0
    runtime_config = runtime_resolver(args.runtime_config)
    return desktop_runner(
        runtime_config,
        app_config=args.app_config,
        initial_capture_mode=selection.capture_mode,
        initial_capture_region=selection.region,
        roi_size=args.roi_size,
    )


def _configured_ocr_module(explicit: Path | None) -> str:
    """Return the backend module to prepare before Qt, without provisioning.

    Deliberately not the resolver used for startup: that one provisions a
    normal launch's configuration and resources, which must not happen for
    someone who is about to cancel the area chooser. Only an already-present
    configuration is read here.

    Preparing the OCR stack before Qt is an ordering optimization, not a
    validation step, so any problem reading the configuration falls back to the
    default backend and surfaces later from the normal startup path with its
    own message.
    """

    try:
        path = (
            explicit
            if explicit is not None
            else desktop_application.discover_runtime_config()
        )
        if path is None:
            return DEFAULT_OCR_RUNTIME_MODULE
        return read_ocr_backend(path).runtime_module
    except (RuntimeConfigError, OSError, ValueError):
        return DEFAULT_OCR_RUNTIME_MODULE


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.handler == "run":
            forwarded: list[str] = []
            if args.runtime_config is not None:
                forwarded.extend(("--runtime-config", str(args.runtime_config)))
            if args.app_config is not None:
                forwarded.extend(("--app-config", str(args.app_config)))
            if args.roi_size is not None:
                forwarded.extend(("--roi", "x".join(map(str, args.roi_size))))
            return run_selected_desktop(forwarded)
        raise AssertionError(f"unhandled command: {args.handler}")
    except (
        CaptureSelectorError,
        DesktopApplicationError,
        RuntimeBootstrapError,
        RuntimeConfigError,
        OSError,
        ValueError,
    ) as error:
        desktop_application._report_startup_error(error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_selected_desktop"]
