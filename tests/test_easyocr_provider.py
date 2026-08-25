"""Focused tests for the EasyOCR provider seam."""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest
from hanly import (
    LookupPipeline,
    LookupStatus,
    OCRProvider,
    PixelFormat,
    Point,
    ProviderError,
    Quad,
    ROIImage,
    TokenAnalysis,
)
from hanly.contracts import DictionaryEntry
from hanly.easyocr_provider import (
    EasyOCRConfig,
    EasyOCRProvider,
    EasyOCRProviderError,
    default_cpu_threads,
)
from hanly.errors import LookupCancelled


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


def _box(left: float, top: float, right: float, bottom: float) -> list[list[float]]:
    """One EasyOCR box, clockwise from its top-left corner."""

    return [[left, top], [right, top], [right, bottom], [left, bottom]]


class _FakeReader:
    def __init__(self, output: object, **options: Any) -> None:
        self.output = output
        self.options = options
        self.inputs: list[np.ndarray] = []
        self.readtext_options: dict[str, Any] = {}

    def readtext(self, image: np.ndarray, **options: Any) -> object:
        self.inputs.append(image)
        self.readtext_options = options
        return self.output


def test_provider_satisfies_the_engine_ocr_protocol() -> None:
    provider = EasyOCRProvider(engine=_FakeReader([]))

    assert isinstance(provider, OCRProvider)


def test_default_configuration_requests_korean_only_on_the_cpu() -> None:
    options = EasyOCRConfig().to_reader_kwargs()

    assert options["lang_list"] == ["ko"]
    assert options["gpu"] is False


def test_configuration_forwards_explicit_paths_and_unknown_options() -> None:
    config = EasyOCRConfig(
        languages=("ko", "en"),
        model_storage_directory="/models/easyocr",
        download_enabled=False,
        extra_options={"detect_network": "craft"},
    )

    options = config.to_reader_kwargs()

    assert options["lang_list"] == ["ko", "en"]
    assert options["model_storage_directory"] == "/models/easyocr"
    assert options["download_enabled"] is False
    assert options["detect_network"] == "craft"
    assert "user_network_directory" not in options


@pytest.mark.parametrize(
    ("languages", "cpu_threads"),
    [((), None), (("",), None), (("ko",), 0), (("ko",), True)],
)
def test_invalid_configuration_is_rejected_at_construction(
    languages: tuple[str, ...], cpu_threads: object
) -> None:
    with pytest.raises(ValueError):
        EasyOCRConfig(languages=languages, cpu_threads=cpu_threads)  # type: ignore[arg-type]


def test_engine_and_engine_factory_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError):
        EasyOCRProvider(engine=_FakeReader([]), engine_factory=_FakeReader)


def test_an_engine_without_readtext_is_rejected_before_any_lookup() -> None:
    with pytest.raises(EasyOCRProviderError):
        EasyOCRProvider(engine=object())


def test_engine_factory_receives_the_configured_reader_options() -> None:
    created: list[_FakeReader] = []

    def factory(**options: Any) -> _FakeReader:
        reader = _FakeReader([], **options)
        created.append(reader)
        return reader

    EasyOCRProvider(EasyOCRConfig(languages=("ko",)), engine_factory=factory)

    assert created[0].options["lang_list"] == ["ko"]
    assert created[0].options["gpu"] is False


def test_korean_detection_is_normalized_with_text_confidence_and_geometry() -> None:
    engine = _FakeReader([(_box(4, 2, 60, 30), " 읽습니다. ", 0.87)])
    provider = EasyOCRProvider(engine=engine)

    results = provider.recognize(_roi())

    assert len(results) == 1
    assert results[0].text == "읽습니다."
    assert results[0].confidence == pytest.approx(0.87)
    assert results[0].quad == Quad(
        p1=Point(4.0, 2.0),
        p2=Point(60.0, 2.0),
        p3=Point(60.0, 30.0),
        p4=Point(4.0, 30.0),
    )
    assert results[0].bounding_box.left == 4
    assert results[0].bounding_box.bottom == 30


def test_numpy_geometry_and_confidence_scalars_are_normalized() -> None:
    engine = _FakeReader(
        [(np.array(_box(0, 0, 8, 8), dtype=np.int32), "책", np.float64(0.5))]
    )
    provider = EasyOCRProvider(engine=engine)

    results = provider.recognize(_roi())

    assert results[0].text == "책"
    assert isinstance(results[0].confidence, float)
    assert results[0].quad.p3 == Point(8.0, 8.0)


def test_confidence_marginally_outside_the_unit_range_is_clamped() -> None:
    engine = _FakeReader(
        [
            (_box(0, 0, 4, 4), "책", 1.0000000002),
            (_box(6, 0, 10, 4), "상", -1e-12),
        ]
    )
    provider = EasyOCRProvider(engine=engine)

    results = provider.recognize(_roi())

    assert [result.confidence for result in results] == [1.0, 0.0]


def test_no_text_in_the_roi_is_an_empty_result_rather_than_an_error() -> None:
    provider = EasyOCRProvider(engine=_FakeReader([]))

    assert provider.recognize(_roi()) == ()


def test_latin_text_is_returned_unchanged_for_the_pipeline_to_reject() -> None:
    engine = _FakeReader([(_box(0, 0, 20, 10), "Hello", 0.99)])
    provider = EasyOCRProvider(engine=engine)

    results = provider.recognize(_roi())

    assert [result.text for result in results] == ["Hello"]


def test_a_blank_recognition_is_dropped_instead_of_becoming_a_region() -> None:
    engine = _FakeReader(
        [
            (_box(0, 0, 4, 4), "   ", 0.1),
            (_box(6, 0, 10, 4), "책", 0.9),
        ]
    )
    provider = EasyOCRProvider(engine=engine)

    assert [result.text for result in provider.recognize(_roi())] == ["책"]


def test_results_are_returned_in_reading_order_not_detection_order() -> None:
    engine = _FakeReader(
        [
            (_box(60, 40, 100, 70), "넷", 0.9),
            (_box(10, 40, 50, 70), "셋", 0.9),
            (_box(60, 0, 100, 30), "둘", 0.9),
            (_box(10, 0, 50, 30), "하나", 0.9),
        ]
    )
    provider = EasyOCRProvider(engine=engine)

    results = provider.recognize(_roi())

    assert [result.text for result in results] == ["하나", "둘", "셋", "넷"]


@pytest.mark.parametrize(
    ("pixel_format", "expected_shape"),
    [
        (PixelFormat.GRAYSCALE_8, (1, 2)),
        (PixelFormat.RGB_888, (1, 2, 3)),
        (PixelFormat.BGR_888, (1, 2, 3)),
        (PixelFormat.RGBA_8888, (1, 2, 4)),
    ],
)
def test_every_pixel_format_reaches_easyocr_in_the_layout_it_expects(
    pixel_format: PixelFormat, expected_shape: tuple[int, ...]
) -> None:
    """EasyOCR reads 3 channels as BGR, 4 as RGBA, and 2-D input as grayscale."""

    engine = _FakeReader([])
    EasyOCRProvider(engine=engine).recognize(_roi(pixel_format))

    delivered = engine.inputs[0]
    assert delivered.shape == expected_shape
    assert delivered.dtype == np.uint8
    assert delivered.flags.writeable


def test_rgb_pixels_are_swapped_to_the_bgr_order_easyocr_assumes() -> None:
    engine = _FakeReader([])
    image = ROIImage(1, 1, PixelFormat.RGB_888, bytes((10, 20, 30)))

    EasyOCRProvider(engine=engine).recognize(image)

    assert engine.inputs[0].tolist() == [[[30, 20, 10]]]


def test_bgr_and_rgba_pixels_are_delivered_without_a_channel_swap() -> None:
    bgr_engine = _FakeReader([])
    EasyOCRProvider(engine=bgr_engine).recognize(
        ROIImage(1, 1, PixelFormat.BGR_888, bytes((10, 20, 30)))
    )
    rgba_engine = _FakeReader([])
    EasyOCRProvider(engine=rgba_engine).recognize(
        ROIImage(1, 1, PixelFormat.RGBA_8888, bytes((10, 20, 30, 40)))
    )

    assert bgr_engine.inputs[0].tolist() == [[[10, 20, 30]]]
    assert rgba_engine.inputs[0].tolist() == [[[10, 20, 30, 40]]]


def test_a_non_roi_input_is_a_programming_error_not_a_provider_error() -> None:
    provider = EasyOCRProvider(engine=_FakeReader([]))

    with pytest.raises(TypeError):
        provider.recognize(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "output",
    [
        object(),
        [("not-a-box", "책", 0.9)],
        [(_box(0, 0, 4, 4), "책")],
        [(_box(0, 0, 4, 4), 5, 0.9)],
        [([[0, 0], [4, 0], [4, 4]], "책", 0.9)],
        [(_box(0, 0, 0, 4), "책", 0.9)],
    ],
)
def test_malformed_engine_output_becomes_a_provider_error(output: object) -> None:
    provider = EasyOCRProvider(engine=_FakeReader(output))

    with pytest.raises(EasyOCRProviderError):
        provider.recognize(_roi())


def test_a_failing_engine_is_reported_as_a_provider_error() -> None:
    class _BrokenReader:
        def readtext(self, image: np.ndarray) -> object:
            raise RuntimeError("torch exploded")

    provider = EasyOCRProvider(engine=_BrokenReader())

    with pytest.raises(EasyOCRProviderError) as error:
        provider.recognize(_roi())
    assert isinstance(error.value, ProviderError)


def test_prewarm_runs_one_real_inference_and_stays_idempotent() -> None:
    engine = _FakeReader([])
    provider = EasyOCRProvider(engine=engine)

    provider.prewarm()
    provider.prewarm()

    assert len(engine.inputs) == 1
    assert engine.inputs[0].shape == (32, 96)


class _FakeMorphology:
    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        assert text == "읽습니다."
        return (TokenAnalysis(token="읽습니다", lemma="읽다"),)


class _FakeDictionary:
    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        assert lemma == "읽다"
        return (DictionaryEntry(headword="읽다", definitions=("to read",)),)


def test_the_provider_drives_an_unchanged_lookup_pipeline_to_success() -> None:
    engine = _FakeReader([(_box(0, 0, 100, 40), "읽습니다.", 0.87)])
    pipeline = LookupPipeline(
        ocr_provider=EasyOCRProvider(engine=engine),
        morphology_provider=_FakeMorphology(),
        dictionary_provider=_FakeDictionary(),
    )

    result = pipeline.lookup(_roi(), Point(50.0, 20.0))

    assert result.status is LookupStatus.SUCCESS
    assert result.entries[0].headword == "읽다"
    assert result.context is not None
    assert result.context.ocr_results[0].confidence == pytest.approx(0.87)


def test_a_low_confidence_region_still_produces_the_normal_unusable_outcome() -> None:
    engine = _FakeReader([(_box(0, 0, 100, 40), "읽습니다.", 0.3)])
    pipeline = LookupPipeline(
        ocr_provider=EasyOCRProvider(engine=engine),
        morphology_provider=_FakeMorphology(),
        dictionary_provider=_FakeDictionary(),
        confidence_threshold=0.5,
    )

    result = pipeline.lookup(_roi(), Point(50.0, 20.0))

    assert result.status is LookupStatus.UNUSABLE


def test_a_request_cancelled_before_ocr_never_reaches_the_provider() -> None:
    engine = _FakeReader([(_box(0, 0, 100, 40), "읽습니다.", 0.87)])
    pipeline = LookupPipeline(
        ocr_provider=EasyOCRProvider(engine=engine),
        morphology_provider=_FakeMorphology(),
        dictionary_provider=_FakeDictionary(),
    )

    with pytest.raises(LookupCancelled):
        pipeline.lookup(_roi(), Point(50.0, 20.0), cancelled=lambda: True)
    assert engine.inputs == []


@pytest.mark.parametrize(
    ("cores", "expected"),
    [(1, 1), (2, 1), (3, 2), (5, 4), (8, 4), (32, 4), (0, 1)],
)
def test_default_cpu_threads_leaves_a_core_for_the_desktop(
    cores: int, expected: int
) -> None:
    """Torch otherwise claims every core, starving the Qt UI thread on exactly
    the small machines the EasyOCR backend exists to serve."""

    assert default_cpu_threads(cores) == expected


def test_default_cpu_threads_reads_the_host_when_no_count_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hanly.easyocr_provider.os.cpu_count", lambda: 2)

    assert default_cpu_threads() == 1


def test_the_sensitive_variant_shares_the_engine_and_reads_more_keenly() -> None:
    """A second Reader would load both models again for a retry most lookups
    never need, so the variant reuses this provider's engine."""

    engine = _FakeReader([])
    provider = EasyOCRProvider(engine=engine)
    variant = provider.sensitive_variant()

    assert variant is not None
    variant.recognize(_roi())

    assert engine.readtext_options == {"mag_ratio": 2.0, "min_size": 4}


def test_the_ordinary_pass_sends_no_extra_readtext_options() -> None:
    engine = _FakeReader([])

    EasyOCRProvider(engine=engine).recognize(_roi())

    assert engine.readtext_options == {}


def test_configured_readtext_options_reach_the_engine() -> None:
    engine = _FakeReader([])
    config = EasyOCRConfig(readtext_options={"mag_ratio": 1.5})

    EasyOCRProvider(config, engine=engine).recognize(_roi())

    assert engine.readtext_options == {"mag_ratio": 1.5}


def test_empty_sensitive_options_disable_the_retry_variant() -> None:
    provider = EasyOCRProvider(
        EasyOCRConfig(sensitive_readtext_options={}), engine=_FakeReader([])
    )

    assert provider.sensitive_variant() is None
