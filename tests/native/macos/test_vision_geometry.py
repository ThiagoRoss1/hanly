"""Live Vision recognition and Retina coordinate contracts."""

import pytest
from hanly import PixelFormat, ROIImage
from hanly.vision_provider import VisionConfig, VisionProvider


def _roi(width: int = 4, height: int = 2) -> ROIImage:
    return ROIImage(width, height, PixelFormat.RGB_888, bytes(width * height * 3))


def test_native_vision_is_available() -> None:
    assert VisionProvider.is_available() is True


def test_an_empty_roi_is_a_normal_empty_result_not_an_error() -> None:
    assert VisionProvider().recognize(_roi(32, 16)) == ()


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

