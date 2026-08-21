"""Focused tests for the official development lookup harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    HanlyError,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
)

from tools.dev_lookup import (
    DevLookupTimeout,
    load_roi_image,
    run_dev_lookup,
    serialize_lookup_result,
)


def _success_result() -> LookupResult:
    ocr = OCRResult(
        text="책",
        confidence=0.97,
        quad=Quad.from_bounding_box(BoundingBox(0, 0, 12, 12)),
    )
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="책", definitions=("book",)),),
        diagnostics=("recognized one region",),
        context=LookupContext(text="책", lemma="책", ocr_results=(ocr,)),
    )


class _Controller:
    def __init__(self, callback, result: LookupResult | None = None) -> None:
        self.callback = callback
        self.result = result or _success_result()
        self.started = False
        self.stopped = False
        self.stopped_waiting: bool | None = None
        self.submitted: tuple[ROIImage, Point] | None = None

    def start(self) -> None:
        self.started = True

    def submit(self, image: ROIImage, target: Point) -> None:
        self.submitted = (image, target)
        self.callback(self.result)

    def stop(self, *, wait: bool = True) -> None:
        self.stopped = True
        self.stopped_waiting = wait


def test_load_roi_image_normalizes_pillow_pixels(tmp_path: Path) -> None:
    pillow = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "roi.png"
    pillow.new("RGB", (2, 1), (10, 20, 30)).save(image_path)

    image = load_roi_image(image_path)

    assert image.width == 2
    assert image.height == 1
    assert image.pixel_format is PixelFormat.RGB_888
    assert image.data == bytes((10, 20, 30, 10, 20, 30))


def test_run_development_lookup_uses_controller_lifecycle_and_serializes_result(
    tmp_path: Path,
) -> None:
    pillow = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "roi.png"
    pillow.new("RGB", (1, 1), (1, 2, 3)).save(image_path)
    config_path = tmp_path / "runtime-config.json"
    config_path.write_text("{}", encoding="utf-8")
    created: list[_Controller] = []

    def factory(*, config_path: Path, on_result):
        controller = _Controller(on_result)
        created.append(controller)
        assert config_path == tmp_path / "runtime-config.json"
        return controller

    target = Point(0.5, 0.5)
    payload = run_dev_lookup(
        image_path,
        config_path,
        target=target,
        controller_factory=factory,
        timeout_seconds=0.5,
    )

    controller = created[0]
    assert controller.started
    assert controller.stopped
    assert controller.stopped_waiting is True
    assert controller.submitted is not None
    submitted_image, submitted_target = controller.submitted
    assert submitted_image.width == 1
    assert submitted_target == target
    assert payload == {
        "status": "SUCCESS",
        "entries": [{"headword": "책", "definitions": ["book"], "part_of_speech": None}],
        "diagnostics": ["recognized one region"],
        "context": {
            "text": "책",
            "lemma": "책",
            "ocr_results": [
                {
                    "text": "책",
                    "confidence": 0.97,
                    "quad": [
                        {"x": 0.0, "y": 0.0},
                        {"x": 12.0, "y": 0.0},
                        {"x": 12.0, "y": 12.0},
                        {"x": 0.0, "y": 12.0},
                    ],
                }
            ],
        },
        "error": None,
    }


def test_serialize_lookup_result_includes_error_diagnostics() -> None:
    result = LookupResult(
        status=LookupStatus.ERROR,
        diagnostics=("provider unavailable",),
        error=HanlyError("native runtime missing"),
    )

    payload = serialize_lookup_result(result)

    assert payload["status"] == "ERROR"
    assert payload["diagnostics"] == ["provider unavailable"]
    assert payload["error"] == {
        "type": "HanlyError",
        "message": "native runtime missing",
    }


def test_run_development_lookup_stops_controller_when_timeout_expires(tmp_path: Path) -> None:
    pillow = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "roi.png"
    pillow.new("RGB", (1, 1), (1, 2, 3)).save(image_path)
    config_path = tmp_path / "runtime-config.json"
    config_path.write_text("{}", encoding="utf-8")
    controller = _NeverController(lambda _result: None)

    with pytest.raises(DevLookupTimeout):
        run_dev_lookup(
            image_path,
            config_path,
            target=Point(0, 0),
            controller_factory=lambda **_kwargs: controller,
            timeout_seconds=0.001,
        )

    assert controller.stopped
    # A timed-out lookup means the worker is still inside an unfinished stage,
    # so the harness must not join it: waiting there would make the bounded
    # timeout unbounded.
    assert controller.stopped_waiting is False


class _NeverController(_Controller):
    def submit(self, image: ROIImage, target: Point) -> None:
        self.submitted = (image, target)
