"""Focused tests for clipping-only capture recovery."""

from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
)
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.capture_recovery import (
    EDGE_TOLERANCE_PIXELS,
    ClippedEdges,
    clipped_edges,
    recovery_target,
    widened_region,
)

_MONITOR = ScreenRect(0, 0, 1920, 1080)


def _result(left: float, right: float) -> LookupResult:
    region = OCRResult(
        text="사과했어요",
        confidence=0.9,
        quad=Quad.from_bounding_box(
            BoundingBox(left=int(left), top=10, right=int(right), bottom=40)
        ),
    )
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry("사과하다", ("to apologize",)),),
        context=LookupContext(text="사과했어요", selected_ocr=region),
    )


def _capture(left: int = 500) -> CaptureResult:
    region = ScreenRect(left, 300, 200, 100)
    return CaptureResult(
        image=ROIImage(
            region.width,
            region.height,
            PixelFormat.GRAYSCALE_8,
            bytes(region.width * region.height),
        ),
        region=region,
        target=Point(100, 50),
    )


def test_a_region_reaching_an_roi_edge_is_reported_as_clipped() -> None:
    assert clipped_edges(_result(0, 150), 200) == ClippedEdges(left=True, right=False)
    assert clipped_edges(_result(50, 200), 200) == ClippedEdges(left=False, right=True)
    assert clipped_edges(_result(0, 200), 200) == ClippedEdges(left=True, right=True)


def test_a_region_comfortably_inside_the_roi_is_not_clipped() -> None:
    """The measured gap between the clipped and clear clusters is 5 to 19 px."""

    assert not clipped_edges(_result(19, 181), 200)
    assert not clipped_edges(_result(EDGE_TOLERANCE_PIXELS + 1, 150), 200)


def test_the_tolerance_sits_between_the_measured_clusters() -> None:
    assert clipped_edges(_result(5, 150), 200).left is True
    assert clipped_edges(_result(EDGE_TOLERANCE_PIXELS, 150), 200).left is True


def test_a_result_without_a_selected_region_is_never_clipped() -> None:
    """Misrecognition of fully visible text must not trigger a recapture."""

    assert not clipped_edges(LookupResult(status=LookupStatus.EMPTY), 200)
    assert not clipped_edges(
        LookupResult(
            status=LookupStatus.NOT_FOUND, context=LookupContext(text="예벗어요")
        ),
        200,
    )


def test_a_widened_region_grows_only_on_the_clipped_side() -> None:
    widened = widened_region(_capture().region, ClippedEdges(left=False, right=True), _MONITOR)

    assert widened == ScreenRect(500, 300, 300, 100)


def test_a_widened_region_never_leaves_the_capture_monitor() -> None:
    against_edge = _capture(left=0)

    widened = widened_region(against_edge.region, ClippedEdges(True, True), _MONITOR)

    assert widened is not None
    assert widened.left == 0
    assert widened.left + widened.width <= _MONITOR.width


def test_no_widening_is_offered_when_the_crop_cannot_grow() -> None:
    narrow = ScreenRect(0, 0, 200, 1080)

    assert widened_region(_capture(left=0).region, ClippedEdges(True, True), narrow) is None
    assert widened_region(_capture().region, ClippedEdges(False, False), _MONITOR) is None


def test_the_cursor_keeps_pointing_at_the_same_pixel_after_widening() -> None:
    capture = _capture()
    widened = widened_region(
        capture.region, ClippedEdges(left=True, right=False), _MONITOR
    )
    assert widened is not None

    target = recovery_target(capture.region, capture.target, widened)

    assert widened.left + target.x == capture.region.left + capture.target.x
    assert widened.top + target.y == capture.region.top + capture.target.y
