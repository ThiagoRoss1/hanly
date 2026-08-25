"""Focused tests for the PaddleOCR provider seam."""

from collections.abc import Mapping

import numpy as np
import pytest
from hanly import OCRProvider, PixelFormat, ProviderError, ROIImage
from hanly.paddleocr_provider import (
    PaddleOCRConfig,
    PaddleOCRProvider,
    PaddleOCRProviderError,
    PaddleTextRecognitionProvider,
)


def _roi(pixel_format: PixelFormat = PixelFormat.RGB_888) -> ROIImage:
    """A 2x1 ROI whose byte count matches the requested format."""

    channels = {
        PixelFormat.GRAYSCALE_8: 1,
        PixelFormat.RGB_888: 3,
        PixelFormat.BGR_888: 3,
        PixelFormat.RGBA_8888: 4,
    }[pixel_format]
    return ROIImage(
        width=2,
        height=1,
        pixel_format=pixel_format,
        data=bytes(range(1, 2 * channels + 1)),
    )


class _FakeEngine:
    def __init__(self, output: object) -> None:
        self.output = output
        self.inputs: list[np.ndarray] = []

    def predict(self, image: np.ndarray) -> object:
        self.inputs.append(image)
        return self.output


@pytest.mark.parametrize(
    ("pixel_format", "expected_channels"),
    [
        (PixelFormat.GRAYSCALE_8, 3),
        (PixelFormat.RGB_888, 3),
        (PixelFormat.RGBA_8888, 3),
    ],
)
def test_every_pixel_format_reaches_paddle_as_three_channel_bgr(
    pixel_format: PixelFormat, expected_channels: int
) -> None:
    """PaddleX unpacks height, width, and channels from the array it receives.

    A two-dimensional grayscale ROI therefore fails before inference, so every
    supported format must arrive with three channels.
    """

    engine = _FakeEngine([{"rec_texts": [], "rec_scores": [], "rec_polys": []}])

    PaddleOCRProvider(engine=engine).recognize(_roi(pixel_format))

    array = engine.inputs[0]
    assert array.ndim == 3
    assert array.shape == (1, 2, expected_channels)
    assert array.dtype == np.uint8


def test_grayscale_channels_are_replicated_without_altering_pixel_values() -> None:
    engine = _FakeEngine([{"rec_texts": [], "rec_scores": [], "rec_polys": []}])

    PaddleOCRProvider(engine=engine).recognize(_roi(PixelFormat.GRAYSCALE_8))

    array = engine.inputs[0]
    assert array[0, 0].tolist() == [1, 1, 1]
    assert array[0, 1].tolist() == [2, 2, 2]


def test_provider_is_protocol_conformant_and_normalizes_paddle_v3_results() -> None:
    engine = _FakeEngine(
        [
            {
                "rec_texts": ["한글", "책"],
                "rec_scores": [0.91, 0.82],
                "rec_polys": [
                    [[1.5, 2.0], [10.25, 2.0], [10.0, 8.5], [1.5, 8.5]],
                    [[12.0, 2.0], [20.0, 2.0], [20.0, 8.0], [12.0, 8.0]],
                ],
            }
        ]
    )

    provider = PaddleOCRProvider(engine=engine)

    assert isinstance(provider, OCRProvider)
    results = provider.recognize(_roi())

    assert [result.text for result in results] == ["한글", "책"]
    assert [result.confidence for result in results] == [0.91, 0.82]
    assert results[0].quad.points[0].x == 1.5
    assert results[0].quad.points[2].y == 8.5
    assert np.array_equal(engine.inputs[0], np.array([[[3, 2, 1], [6, 5, 4]]], dtype=np.uint8))


def test_provider_returns_empty_tuple_when_paddle_reports_no_regions() -> None:
    engine = _FakeEngine([{"rec_texts": [], "rec_scores": [], "rec_polys": []}])

    assert PaddleOCRProvider(engine=engine).recognize(_roi()) == ()


def test_provider_wraps_engine_failures_as_provider_errors() -> None:
    class FailingEngine:
        def predict(self, image: np.ndarray) -> object:
            del image
            raise RuntimeError("model execution failed")

    with pytest.raises(PaddleOCRProviderError, match="recognition failed") as raised:
        PaddleOCRProvider(engine=FailingEngine()).recognize(_roi())

    assert isinstance(raised.value, ProviderError)
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_provider_wraps_malformed_engine_results_as_provider_errors() -> None:
    engine = _FakeEngine(
        [{"rec_texts": ["한글"], "rec_scores": [0.9], "rec_polys": []}]
    )

    with pytest.raises(PaddleOCRProviderError, match="malformed"):
        PaddleOCRProvider(engine=engine).recognize(_roi())


def test_config_passes_explicit_model_names_and_paths_to_engine_factory() -> None:
    calls: list[Mapping[str, object]] = []

    def factory(**kwargs: object) -> _FakeEngine:
        calls.append(kwargs)
        return _FakeEngine([{"rec_texts": [], "rec_scores": [], "rec_polys": []}])

    config = PaddleOCRConfig(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_detection_model_dir="models/det",
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        text_recognition_model_dir="models/rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    PaddleOCRProvider(config=config, engine_factory=factory)

    assert calls == [
        {
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_detection_model_dir": "models/det",
            "text_recognition_model_name": "korean_PP-OCRv5_mobile_rec",
            "text_recognition_model_dir": "models/rec",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
    ]


def test_text_recognition_provider_uses_the_bounded_public_module_options() -> None:
    calls: list[Mapping[str, object]] = []
    engines: list[_FakeEngine] = []

    def factory(**kwargs: object) -> _FakeEngine:
        calls.append(kwargs)
        engine = _FakeEngine([{"rec_text": "책", "rec_score": 0.97}])
        engines.append(engine)
        return engine

    config = PaddleOCRConfig(
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        text_recognition_model_dir="models/rec",
    )
    provider = PaddleTextRecognitionProvider(config=config, engine_factory=factory)

    result = provider.recognize_text(_roi())

    assert calls == [
        {
            "model_name": "korean_PP-OCRv5_mobile_rec",
            "model_dir": "models/rec",
            "input_shape": [3, 48, 160],
            "cpu_threads": 2,
            "enable_mkldnn": False,
        }
    ]
    assert result is not None
    assert result.text == "책"
    assert result.confidence == 0.97
    engine_input = engines[0].inputs[0]
    assert engine_input.shape == (1, 2, 3)
    assert engine_input.dtype == np.uint8


def test_text_recognition_provider_rejects_malformed_or_multiple_results() -> None:
    malformed = PaddleTextRecognitionProvider(
        engine=_FakeEngine([{"rec_text": ("책",), "rec_score": 0.9}])
    )
    multiple = PaddleTextRecognitionProvider(
        engine=_FakeEngine(
            [
                {"rec_text": "책", "rec_score": 0.9},
                {"rec_text": "학교", "rec_score": 0.9},
            ]
        )
    )

    with pytest.raises(PaddleOCRProviderError, match="malformed"):
        malformed.recognize_text(_roi())
    with pytest.raises(PaddleOCRProviderError, match="exactly one"):
        multiple.recognize_text(_roi())


def test_text_recognition_prewarm_runs_real_inference_once() -> None:
    engine = _FakeEngine([{"rec_text": "", "rec_score": 0.0}])
    provider = PaddleTextRecognitionProvider(engine=engine)

    provider.prewarm()
    provider.prewarm()

    assert len(engine.inputs) == 1
    assert engine.inputs[0].shape == (32, 96, 3)
    assert engine.inputs[0].dtype == np.uint8
