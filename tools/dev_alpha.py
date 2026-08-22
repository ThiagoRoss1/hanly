"""Start the first human-testable Hanly desktop alpha.

The launcher prepares only local development resources, sets the offline
PaddleX source-check flag, and delegates the desktop composition to the public
manual-lookup runner. It does not construct providers itself.
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
    """Prepare local resources and run the public manual desktop alpha.

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
        raise DevAlphaError("manual alpha runner must return an integer exit code")
    return result


def _default_alpha_runner(*, config_path: Path) -> int | None:
    """Run the desktop composition after local resources are ready.

    The desktop imports stay inside the function so this rig can be imported
    and its startup ordering tested without the runtime extra installed.
    """

    try:
        from hanly_app.capture import CaptureService
        from hanly_app.manual_lookup import create_qt_manual_lookup
        from hanly_app.runtime import load_runtime
        from PyQt6.QtWidgets import QApplication
    except ImportError as error:
        raise DevAlphaError(
            "the desktop alpha requires the hanly-app runtime extra "
            "(PyQt6, mss, and pynput)"
        ) from error

    application = QApplication.instance() or QApplication(sys.argv)
    runtime = load_runtime(config_path)
    capture = CaptureService()
    try:
        manual = create_qt_manual_lookup(runtime, capture)
    except Exception:
        capture.close()
        raise

    # start() closes what it acquired if registration fails, and shutdown() is
    # idempotent, so both exit routes may request it unconditionally.
    application.aboutToQuit.connect(manual.shutdown)
    try:
        manual.start()
        print(
            "Hanly dev alpha ready. Point at Korean text and press "
            "Ctrl+Shift+Space.",
            flush=True,
        )
        return application.exec()
    finally:
        manual.shutdown()


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
