"""Focused tests for the Apple Vision OCR adapter."""

import sys

import pytest
from hanly import OCRProvider, PixelFormat, ROIImage
from hanly.vision_provider import (
    DEFAULT_INPUT_SCALE,
    MAX_INPUT_SCALE,
    VisionConfig,
    VisionProvider,
    VisionProviderError,
)

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="Vision is a macOS framework"
)


def _roi(width: int = 4, height: int = 2) -> ROIImage:
    return ROIImage(width, height, PixelFormat.RGB_888, bytes(width * height * 3))


def test_the_adapter_satisfies_the_engine_ocr_seam() -> None:
    assert isinstance(VisionProvider(), OCRProvider)


def test_availability_is_false_off_darwin_without_raising() -> None:
    if sys.platform == "darwin":
        assert VisionProvider.is_available() is True
    else:
        assert VisionProvider.is_available() is False


def test_a_non_image_argument_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        VisionProvider().recognize("not an image")  # type: ignore[arg-type]


@pytest.mark.skipif(sys.platform == "darwin", reason="covers the non-macOS path")
def test_recognizing_off_darwin_reports_a_provider_error() -> None:
    with pytest.raises(VisionProviderError, match="macOS"):
        VisionProvider().recognize(_roi())


@darwin_only
def test_an_empty_roi_is_a_normal_empty_result_not_an_error() -> None:
    assert VisionProvider().recognize(_roi(32, 16)) == ()


@darwin_only
def test_language_correction_is_off_by_default() -> None:
    """Correction can turn one real word into another, which a dictionary
    lookup must not do silently. It stays opt-in."""

    assert VisionConfig().language_correction is False
    assert VisionConfig().languages == ("ko-KR",)


@darwin_only
def test_recognized_regions_carry_top_left_pixel_geometry() -> None:
    """Vision reports bottom-left normalized coordinates; the seam does not."""

    pillow = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont

    del pillow
    font = ImageFont.truetype(
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc", 40
    )
    canvas = Image.new("RGB", (360, 120), "white")
    ImageDraw.Draw(canvas).text((40, 30), "사과했어요", font=font, fill="black")
    roi = ROIImage(canvas.width, canvas.height, PixelFormat.RGB_888, canvas.tobytes())

    results = VisionProvider().recognize(roi)

    assert results, "Vision should read large rendered Korean"
    region = results[0]
    assert region.text.strip() == "사과했어요"
    assert 0 <= region.quad.p1.x < region.quad.p2.x <= canvas.width
    assert 0 <= region.quad.p1.y < region.quad.p4.y <= canvas.height
    assert 0.0 <= region.confidence <= 1.0


def test_pinning_vision_where_it_does_not_exist_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Failing once at load beats failing identically on every lookup."""

    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime, RuntimeConfigError

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(lambda: False))
    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=object(),  # type: ignore[arg-type]
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.VISION,
    )

    with pytest.raises(RuntimeConfigError, match="does not provide"):
        runtime._ocr_factory()


def test_auto_falls_back_instead_of_refusing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(lambda: False))
    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=object(),  # type: ignore[arg-type]
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.AUTO,
        easyocr_config=EasyOCRConfig(),
    )

    assert runtime._ocr_factory() is not None


def test_the_lookup_child_builds_the_recognizer_it_was_told_to(tmp_path) -> None:
    """The child never reads the runtime config.

    The recognizer choice has to travel with the spawn settings; while it did
    not, the parent resolved Vision and every actual lookup still ran EasyOCR.
    """

    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.lookup_process import LookupSettings, _ocr_provider_factory

    def settings(backend: OCRBackend) -> LookupSettings:
        return LookupSettings(
            krdict_path=tmp_path / "krdict.sqlite3",
            easyocr=EasyOCRConfig(),
            ocr_backend=backend,
        )

    # The factory is inspected rather than called: constructing the EasyOCR
    # provider would load Torch and its weights for an assertion about which
    # branch was taken.
    assert _ocr_provider_factory(settings(OCRBackend.VISION)) is VisionProvider
    assert _ocr_provider_factory(settings(OCRBackend.EASYOCR)) is not VisionProvider
    # ``auto`` never reaches the child; a stored one behaves as the historical
    # default rather than probing for a framework from a spawned process.
    assert _ocr_provider_factory(settings(OCRBackend.AUTO)) is not VisionProvider


def test_the_runtime_sends_its_backend_to_the_child(tmp_path) -> None:
    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime

    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=object(),  # type: ignore[arg-type]
        krdict_path=tmp_path / "krdict.sqlite3",
        easyocr_config=EasyOCRConfig(),
        ocr_backend=OCRBackend.EASYOCR,
    )

    assert runtime.lookup_settings().ocr_backend is OCRBackend.EASYOCR
    # ``auto`` is resolved in the shell, so the child is never asked to decide.
    assert runtime.resolved_ocr_backend() is OCRBackend.EASYOCR
    assert (
        HanlyRuntime(
            config_path=tmp_path / "runtime.json",
            resource_manager=object(),  # type: ignore[arg-type]
            krdict_path=tmp_path / "krdict.sqlite3",
            easyocr_config=EasyOCRConfig(),
            ocr_backend=OCRBackend.AUTO,
        ).lookup_settings().ocr_backend
        is not OCRBackend.AUTO
    )


# --- Model input scale (Wave 3) ---------------------------------------------
#
# Vision silently omitted whole proportional lines -- Korean and Latin alike --
# at the sizes Hanly captures, while reading the same pixels correctly once
# enlarged. Only the encoded payload grows; the ROI and its coordinate space do
# not, which is the part worth guarding.


def test_the_recognizer_is_given_a_doubled_image_by_default() -> None:
    assert VisionConfig().input_scale == DEFAULT_INPUT_SCALE == 2


@pytest.mark.parametrize("scale", [0, -1, -100, 1.5, 2.0, True, False, "2", None])
def test_a_nonsensical_input_scale_is_refused(scale: object) -> None:
    with pytest.raises(ValueError, match="input_scale"):
        VisionConfig(input_scale=scale)  # type: ignore[arg-type]


@pytest.mark.parametrize("scale", [MAX_INPUT_SCALE + 1, 64, 10**9])
def test_an_unreasonable_input_scale_is_refused(scale: int) -> None:
    """Scale grows the decoded image quadratically, so an unbounded value turns
    a configuration slip into an allocation the machine cannot satisfy."""

    with pytest.raises(ValueError, match="between 1 and"):
        VisionConfig(input_scale=scale)


def test_the_whole_permitted_range_is_constructible() -> None:
    for scale in range(1, MAX_INPUT_SCALE + 1):
        assert VisionConfig(input_scale=scale).input_scale == scale


def test_scaling_replicates_pixels_exactly_and_invents_no_detail() -> None:
    """Nearest-neighbour keeps this a presentation change: every output pixel
    is an input pixel, so the recognizer reads nothing that was not captured."""

    pytest.importorskip("PIL")
    from io import BytesIO

    from hanly.vision_provider import _png_bytes
    from PIL import Image

    source = Image.new("RGB", (3, 2))
    source.putpixel((0, 0), (255, 0, 0))
    source.putpixel((2, 1), (0, 0, 255))
    roi = ROIImage(3, 2, PixelFormat.RGB_888, source.tobytes())

    with Image.open(BytesIO(_png_bytes(roi, 2))) as doubled:
        assert doubled.size == (6, 4)
        # The red corner pixel became an exact 2x2 block of itself.
        assert {doubled.getpixel((x, y)) for x in (0, 1) for y in (0, 1)} == {(255, 0, 0)}
        assert {doubled.getpixel((x, y)) for x in (4, 5) for y in (2, 3)} == {(0, 0, 255)}
        # Only the counts change; no new colour is introduced.
        assert {colour for _count, colour in doubled.getcolors() or []} == {
            colour for _count, colour in source.getcolors() or []
        }

    with Image.open(BytesIO(_png_bytes(roi, 1))) as plain:
        assert plain.size == (3, 2)


@darwin_only
def test_geometry_comes_back_in_the_captured_coordinate_space() -> None:
    """Only the payload is enlarged. A quad outside the ROI would send the
    resolver looking for a word that is not where it says it is."""

    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (240, 60), "white")
    ImageDraw.Draw(canvas).text((12, 16), "Hanly", fill="black")
    roi = ROIImage(240, 60, PixelFormat.RGB_888, canvas.tobytes())

    results = VisionProvider().recognize(roi)

    assert results, "the fixture must produce at least one region"
    for result in results:
        for point in result.quad.points:
            assert 0 <= point.x <= roi.width
            assert 0 <= point.y <= roi.height


@darwin_only
def test_doubling_does_not_change_where_a_region_is_reported() -> None:
    """Same pixels, same place, whatever size the recognizer was handed."""

    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (240, 60), "white")
    ImageDraw.Draw(canvas).text((12, 16), "Hanly", fill="black")
    roi = ROIImage(240, 60, PixelFormat.RGB_888, canvas.tobytes())

    plain = VisionProvider(VisionConfig(input_scale=1)).recognize(roi)
    doubled = VisionProvider(VisionConfig(input_scale=2)).recognize(roi)

    if not plain or not doubled:
        pytest.skip("this machine's Vision did not read the control fixture")
    # Geometry agrees to within a pixel of the enlarged sampling grid.
    assert abs(plain[0].quad.p1.x - doubled[0].quad.p1.x) <= 2
    assert abs(plain[0].quad.p1.y - doubled[0].quad.p1.y) <= 2
