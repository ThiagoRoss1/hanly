"""Start the human-testable Hanly desktop alpha.

The launcher prepares only local development resources, sets the offline
PaddleX source-check flag, and delegates to the shared manual/automatic desktop
composition. It does not construct providers itself.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path
from typing import Protocol

# Running this rig as ``python tools/dev_alpha.py`` puts ``tools/`` on the path
# rather than the repository root, so the sibling module has to be made
# importable before it is imported.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_resources import (  # noqa: E402
    DevResourceError,
    default_dev_config_path,
    prepare_dev_resources,
)


class DevAlphaError(RuntimeError):
    """Raised when the desktop alpha cannot be launched."""


class PreparedResources(Protocol):
    """Small preparation seam consumed by :func:`run_dev_alpha`."""

    config_path: Path

    def cleanup(self) -> None:
        """Release any disposable preparation artifacts."""


ResourcePreparer = Callable[[str | Path | None], PreparedResources]


ManualAlphaRunner = Callable[..., int | None]


def run_dev_alpha(
    config_path: str | Path | None = None,
    *,
    resource_preparer: ResourcePreparer | None = None,
    alpha_runner: ManualAlphaRunner | None = None,
    environment: MutableMapping[str, str] | None = None,
) -> int:
    """Prepare local resources and run the public desktop alpha.

    ``resource_preparer`` and ``alpha_runner`` are injectable so startup
    ordering and cleanup can be tested without opening a real Qt application.
    """

    preparer = resource_preparer or prepare_dev_resources
    resources = preparer(config_path)
    env = os.environ if environment is None else environment
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    runner = alpha_runner or _default_alpha_runner
    try:
        result = runner(config_path=resources.config_path)
    finally:
        resources.cleanup()

    if result is None:
        return 0
    if isinstance(result, bool) or not isinstance(result, int):
        raise DevAlphaError("desktop alpha runner must return an integer exit code")
    return result


def _default_alpha_runner(*, config_path: Path) -> int | None:
    """Run the desktop composition after local resources are ready.

    The desktop imports stay inside the function so this rig can be imported
    and its startup ordering tested without the runtime extra installed. The
    OCR runtime is imported before any of them, because Qt changes the process
    DLL search path that PaddleOCR's native libraries need.
    """

    _preload_ocr_runtime()

    try:
        from hanly_app.capture import CaptureService
        from hanly_app.config import ConfigManager
        from hanly_app.control_center import (
            ControlCenterBridge,
            ControlCenterHost,
            ControlCenterUnavailable,
            prepare_control_center_qt,
        )
        from hanly_app.manual_lookup import create_qt_manual_lookup
        from hanly_app.runtime import load_runtime
        from PyQt6.QtWidgets import QApplication
    except ImportError as error:
        raise DevAlphaError(
            "the desktop alpha requires the hanly-app runtime extra "
            "(PyQt6, mss, and pynput)"
        ) from error

    try:
        prepare_control_center_qt()
    except ControlCenterUnavailable as error:
        raise DevAlphaError(f"could not prepare the Control Center runtime: {error}") from error

    application = QApplication.instance() or QApplication(sys.argv)
    runtime = load_runtime(config_path)
    settings = ConfigManager(_dev_app_config_path())
    settings.load()
    capture = CaptureService()
    try:
        manual = create_qt_manual_lookup(
            runtime,
            capture,
            app_config=settings.config,
            hover_on_error=_report_hover_error,
        )
    except Exception:
        capture.close()
        raise

    # start() closes what it acquired if registration fails, and shutdown() is
    # idempotent, so both exit routes may request it unconditionally.
    application.aboutToQuit.connect(manual.shutdown)
    try:
        manual.start()
        print(
            "Hanly dev alpha ready. Keep the cursor stable over Korean text "
            "for automatic lookup, or press Ctrl+Shift+Space for manual lookup.",
            flush=True,
        )
        _open_dev_control_center(
            ControlCenterHost(
                ControlCenterBridge(
                    config_manager=settings,
                    capture_service=capture,
                    runtime=runtime,
                    desktop_controller=manual,
                )
            )
        )
        return application.exec()
    finally:
        manual.shutdown()


def _preload_ocr_runtime() -> None:
    """Import the OCR library before Qt claims the process DLL search path.

    PaddleOCR pulls in native libraries whose dependencies fail to load on
    Windows once PyQt6 has been imported first, and provider construction
    happens later on the worker thread. Importing it here keeps that ordering
    correct. A missing library is not fatal: the provider reports it.
    """

    try:
        import paddleocr  # noqa: F401
    except Exception as error:
        print(f"Hanly dev alpha: OCR preload skipped: {error}", file=sys.stderr, flush=True)


def _report_hover_error(stage: str, error: BaseException) -> None:
    """Make an automatic-hover failure visible in the developer console."""

    print(f"Hanly dev alpha: {stage}: {error}", file=sys.stderr, flush=True)


def _dev_app_config_path() -> Path:
    """Keep developer preferences beside the other local dev resources."""

    return default_dev_config_path().parent / "app-config.json"


def _open_dev_control_center(host: object) -> None:
    """Show the Control Center so the developer alpha can exercise it.

    Opening it here is deliberately a development affordance: it runs the same
    Qt event loop, so hover and the manual hotkey stay live while it is open,
    and closing it returns to the ordinary alpha loop. The real application
    lifecycle owns how this window is opened for end users.
    """

    open_window = getattr(host, "open", None)
    if not callable(open_window):
        return
    try:
        open_window()
    except Exception as error:
        print(f"Hanly dev alpha: Control Center unavailable: {error}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=default_dev_config_path(),
        help="optional local runtime JSON; defaults to resources/dev/runtime.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the developer alpha command and report actionable startup errors."""

    args = _build_parser().parse_args(argv)
    try:
        return run_dev_alpha(args.config)
    except (DevAlphaError, DevResourceError) as error:
        print(f"Hanly dev alpha: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover - exercised through ``python``
    raise SystemExit(main())


__all__ = [
    "DevAlphaError",
    "ManualAlphaRunner",
    "ResourcePreparer",
    "main",
    "run_dev_alpha",
]
