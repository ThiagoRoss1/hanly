"""Development rig: run one real Hanly lookup and print the result as JSON.

Exercises the real ``image -> PaddleOCR -> Kiwi -> KRDICT -> LookupResult``
path through the actual ``LookupController``, without the desktop UI. Setup and
usage live in ``tools/README.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from hanly import LookupContext, LookupResult, PixelFormat, Point, ROIImage
from hanly_app.lookup_controller import LookupController


class DevLookupError(RuntimeError):
    """Raised when the development rig cannot complete a lookup."""


class DevLookupTimeout(DevLookupError):
    """Raised when the bounded lookup wait expires."""


class ControllerLike(Protocol):
    """The small lifecycle/input surface consumed by this rig."""

    def start(self) -> None:
        ...

    def submit(self, image: ROIImage, target: Point) -> object:
        ...

    def stop(self, *, wait: bool = True) -> None:
        ...


ControllerFactory = Callable[..., ControllerLike]


def load_roi_image(path: str | Path) -> ROIImage:
    """Load one image with Pillow and normalize it to RGB ``ROIImage`` bytes."""

    image_path = Path(path)
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise DevLookupError(
            "Pillow is required by tools/dev_lookup.py; install the hanly-app "
            "dev extra first"
        ) from exc

    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
            return ROIImage(
                width=image.width,
                height=image.height,
                pixel_format=PixelFormat.RGB_888,
                data=image.tobytes(),
            )
    except (OSError, ValueError) as exc:
        raise DevLookupError(f"could not load image: {image_path}") from exc


def serialize_lookup_result(result: LookupResult) -> dict[str, Any]:
    """Serialize a normalized lookup result into stable JSON-compatible data."""

    if not isinstance(result, LookupResult):
        raise TypeError("result must be a LookupResult")

    context = _serialize_context(result.context)
    error = None
    if result.error is not None:
        error = {
            "type": type(result.error).__name__,
            "message": str(result.error),
        }
    return {
        "status": result.status.value,
        "entries": [
            {
                "headword": entry.headword,
                "definitions": list(entry.definitions),
                "part_of_speech": entry.part_of_speech,
            }
            for entry in result.entries
        ],
        "diagnostics": list(result.diagnostics),
        "context": context,
        "error": error,
    }


def run_dev_lookup(
    image_path: str | Path,
    config_path: str | Path,
    *,
    target: Point,
    timeout_seconds: float = 30.0,
    controller_factory: ControllerFactory | None = None,
) -> dict[str, Any]:
    """Run one real lookup through ``LookupController``.

    ``controller_factory`` is an intentional test seam. Normal callers omit it
    and the rig lazily resolves the public factory in
    :mod:`hanly_app.runtime`. The controller still owns worker construction
    and pipeline stage orchestration in both cases.
    """

    if not isinstance(target, Point):
        raise TypeError("target must be a Point")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    image = load_roi_image(image_path)
    runtime_config = Path(config_path)
    completed = threading.Event()
    result: LookupResult | None = None
    callback_error: BaseException | None = None

    def receive(value: LookupResult) -> None:
        nonlocal result, callback_error
        if isinstance(value, LookupResult):
            result = value
        else:
            callback_error = TypeError("concrete controller returned a non-normalized result")
        completed.set()

    factory = controller_factory or _default_controller_factory
    controller = factory(config_path=runtime_config, on_result=receive)
    started = False
    timed_out = False
    try:
        controller.start()
        started = True
        controller.submit(image, target)
        if not completed.wait(timeout_seconds):
            timed_out = True
            raise DevLookupTimeout(
                f"lookup did not complete within {timeout_seconds:.3g} seconds"
            )
        if callback_error is not None:
            raise DevLookupError(str(callback_error)) from callback_error
        if result is None:
            raise DevLookupError("controller completed without a result")
        return serialize_lookup_result(result)
    finally:
        if started:
            # Joining a timed-out worker would make the bounded wait unbounded:
            # it is still inside the stage that did not finish.
            controller.stop(wait=not timed_out)


def _default_controller_factory(
    *, config_path: Path, on_result: Callable[[LookupResult], None]
) -> LookupController:
    """Resolve the composition factory only for a real run."""

    try:
        from hanly_app.runtime import create_lookup_controller_from_config
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise DevLookupError(
            "the provider runtime is unavailable; install the hanly-app runtime extra"
        ) from exc
    return create_lookup_controller_from_config(
        config_path=config_path,
        on_result=on_result,
    )


def _serialize_context(context: LookupContext | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "text": context.text,
        "lemma": context.lemma,
        "ocr_results": [
            {
                "text": ocr.text,
                "confidence": ocr.confidence,
                "quad": [{"x": point.x, "y": point.y} for point in ocr.quad.points],
            }
            for ocr in context.ocr_results
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="path to one Korean ROI image")
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        dest="config_path",
        help="path to the JSON runtime configuration file",
    )
    parser.add_argument("--target-x", type=float, default=0.0)
    parser.add_argument("--target-y", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=30.0, dest="timeout_seconds")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for one bounded development lookup."""

    args = _build_parser().parse_args(argv)
    payload = run_dev_lookup(
        args.image,
        args.config_path,
        target=Point(args.target_x, args.target_y),
        timeout_seconds=args.timeout_seconds,
    )
    output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    # The supported development path includes Windows, whose inherited console
    # encoding may otherwise be cp1252 and reject normalized Korean output.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``python -m``
    raise SystemExit(main())


__all__ = [
    "ControllerFactory",
    "ControllerLike",
    "DevLookupError",
    "DevLookupTimeout",
    "load_roi_image",
    "main",
    "run_dev_lookup",
    "serialize_lookup_result",
]
