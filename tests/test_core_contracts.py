"""Focused tests for the normalized Hanly engine contracts."""

import math
from dataclasses import FrozenInstanceError, fields, is_dataclass

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
    ProviderError,
    Quad,
    ResourceMetadata,
    ResourceStatus,
    ROIImage,
    TokenAnalysis,
)


def _quad(left: float, top: float, right: float, bottom: float) -> Quad:
    return Quad(
        p1=Point(left, top),
        p2=Point(right, top),
        p3=Point(right, bottom),
        p4=Point(left, bottom),
    )


def test_value_contracts_are_typed_frozen_dataclasses() -> None:
    box = BoundingBox(left=1, top=2, right=101, bottom=202)
    ocr_result = OCRResult(text="한국어", confidence=0.98, quad=Quad.from_bounding_box(box))
    token = TokenAnalysis(
        token="먹어요",
        lemma="먹다",
        part_of_speech="verb",
        morphology="polite-present",
    )
    entry = DictionaryEntry(
        headword="먹다",
        definitions=("to eat", "to consume"),
        part_of_speech="verb",
    )

    for value in (box, ocr_result, token, entry):
        assert is_dataclass(value)
        assert getattr(value, "__dataclass_params__").frozen

    assert ocr_result.bounding_box == box
    assert entry.definitions == ("to eat", "to consume")
    assert isinstance(entry.definitions, tuple)

    with pytest.raises(FrozenInstanceError):
        box.left = 10  # type: ignore[misc]

    assert [field.name for field in fields(BoundingBox)] == [
        "left",
        "top",
        "right",
        "bottom",
    ]


@pytest.mark.parametrize(
    "coordinates",
    [(0, 0, 0, 1), (0, 0, 1, 0), (2, 0, 1, 1), (0, 2, 1, 1)],
)
def test_bounding_box_rejects_inverted_or_empty_coordinates(
    coordinates: tuple[int, int, int, int],
) -> None:
    with pytest.raises(ValueError, match="ordered non-empty"):
        BoundingBox(*coordinates)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, math.inf, -math.inf, math.nan])
def test_ocr_result_rejects_non_finite_or_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        OCRResult(text="한국어", confidence=confidence, quad=_quad(0, 0, 1, 1))


def test_point_rejects_non_finite_coordinates() -> None:
    with pytest.raises(ValueError, match="finite"):
        Point(x=math.inf, y=0.0)

    with pytest.raises(ValueError, match="finite"):
        Point(x=0.0, y=math.nan)


def test_quad_preserves_all_four_float_corners_for_tilted_text() -> None:
    # A tilted line: an axis-aligned rectangle alone would lose the slant.
    quad = Quad(
        p1=Point(10.5, 20.25),
        p2=Point(110.5, 14.75),
        p3=Point(112.0, 44.5),
        p4=Point(12.0, 50.0),
    )

    assert quad.points == (quad.p1, quad.p2, quad.p3, quad.p4)
    assert quad.p1.x == 10.5
    assert quad.p2.y == 14.75
    assert quad.width == 101.5
    assert quad.height == 35.25


def test_quad_derives_an_axis_aligned_box_that_never_clips_the_corners() -> None:
    quad = Quad(
        p1=Point(10.5, 20.25),
        p2=Point(110.5, 14.75),
        p3=Point(112.0, 44.5),
        p4=Point(12.0, 50.0),
    )

    box = quad.bounding_box()

    # Expanded outward: floor for the near edges, ceil for the far ones.
    assert box == BoundingBox(left=10, top=14, right=112, bottom=50)
    for point in quad.points:
        assert box.left <= point.x <= box.right
        assert box.top <= point.y <= box.bottom


def test_quad_round_trips_an_axis_aligned_rectangle() -> None:
    box = BoundingBox(left=-1920, top=0, right=-1820, bottom=40)

    quad = Quad.from_bounding_box(box)

    # Negative coordinates are valid: a monitor left of the primary one.
    assert quad.p1 == Point(-1920.0, 0.0)
    assert quad.p3 == Point(-1820.0, 40.0)
    assert quad.bounding_box() == box


def test_quad_rejects_geometry_without_extent() -> None:
    with pytest.raises(ValueError, match="extent"):
        Quad(
            p1=Point(0.0, 0.0),
            p2=Point(10.0, 0.0),
            p3=Point(10.0, 0.0),
            p4=Point(0.0, 0.0),
        )


def test_ocr_result_exposes_the_derived_bounding_box() -> None:
    result = OCRResult(text="한국어", confidence=0.9, quad=_quad(4.2, 8.9, 40.1, 22.4))

    assert result.bounding_box == BoundingBox(left=4, top=8, right=41, bottom=23)


def test_roi_image_is_a_normalized_library_independent_input() -> None:
    image = ROIImage(
        width=2,
        height=2,
        pixel_format=PixelFormat.GRAYSCALE_8,
        data=bytes([0, 64, 128, 255]),
    )

    assert image.bytes_per_pixel == 1
    assert image.width == 2
    assert isinstance(image.data, bytes)


@pytest.mark.parametrize(
    ("width", "height", "pixel_format", "size"),
    [
        (0, 2, PixelFormat.GRAYSCALE_8, 0),
        (2, 0, PixelFormat.GRAYSCALE_8, 0),
    ],
)
def test_roi_image_rejects_non_positive_dimensions(
    width: int, height: int, pixel_format: PixelFormat, size: int
) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        ROIImage(width=width, height=height, pixel_format=pixel_format, data=bytes(size))


def test_roi_image_rejects_a_non_pixel_format_value() -> None:
    """A public boundary must report misuse clearly, not leak a KeyError."""

    with pytest.raises(TypeError, match="pixel_format must be a PixelFormat"):
        ROIImage(
            width=1,
            height=1,
            pixel_format="RGB_888",  # type: ignore[arg-type]
            data=bytes(3),
        )


@pytest.mark.parametrize(
    "pixel_format",
    [PixelFormat.GRAYSCALE_8, PixelFormat.RGB_888, PixelFormat.BGR_888, PixelFormat.RGBA_8888],
)
def test_roi_image_requires_data_matching_its_declared_format(
    pixel_format: PixelFormat,
) -> None:
    with pytest.raises(ValueError, match="bytes"):
        ROIImage(width=2, height=2, pixel_format=pixel_format, data=b"\x00")


def test_lookup_statuses_cover_success_and_normal_non_success() -> None:
    required_statuses = {
        "SUCCESS",
        "EMPTY",
        "NOT_FOUND",
        "UNUSABLE",
        "ERROR",
    }
    assert required_statuses <= LookupStatus.__members__.keys()


@pytest.mark.parametrize(
    "status",
    [
        LookupStatus.EMPTY,
        LookupStatus.NOT_FOUND,
        LookupStatus.UNUSABLE,
        LookupStatus.ERROR,
    ],
)
def test_non_success_results_keep_diagnostics_and_error_without_entries(
    status: LookupStatus,
) -> None:
    error = HanlyError("provider unavailable") if status is LookupStatus.ERROR else None
    result = LookupResult(
        status=status,
        diagnostics=("partial result",),
        error=error,
    )

    assert result.status is status
    assert result.entries == ()
    assert result.diagnostics == ("partial result",)
    assert result.error is error
    assert isinstance(result.diagnostics, tuple)


def test_successful_result_keeps_entries_diagnostics_and_context() -> None:
    entry = DictionaryEntry(headword="먹다", definitions=("to eat",), part_of_speech="verb")
    result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(entry,),
        diagnostics=("low-confidence recognition",),
    )

    assert result.entries == (entry,)
    assert result.diagnostics == ("low-confidence recognition",)
    assert result.error is None
    assert isinstance(result.entries, tuple)


@pytest.mark.parametrize(
    "status",
    [
        LookupStatus.EMPTY,
        LookupStatus.NOT_FOUND,
        LookupStatus.UNUSABLE,
    ],
)
def test_non_success_results_cannot_carry_dictionary_entries(
    status: LookupStatus,
) -> None:
    entry = DictionaryEntry(headword="먹다", definitions=("to eat",))

    with pytest.raises(ValueError, match="only SUCCESS"):
        LookupResult(status=status, entries=(entry,))


def test_lookup_result_defaults_to_empty_collections_without_an_exception() -> None:
    result = LookupResult(status=LookupStatus.EMPTY)

    assert result.entries == ()
    assert result.diagnostics == ()
    assert result.error is None


def test_lookup_result_requires_entries_for_success() -> None:
    with pytest.raises(ValueError, match="SUCCESS"):
        LookupResult(status=LookupStatus.SUCCESS)


def test_lookup_result_success_cannot_carry_an_error() -> None:
    entry = DictionaryEntry(headword="먹다", definitions=("to eat",))

    with pytest.raises(ValueError, match="SUCCESS"):
        LookupResult(
            status=LookupStatus.SUCCESS,
            entries=(entry,),
            error=HanlyError("unexpected processing error"),
        )


def test_lookup_result_requires_error_for_processing_error() -> None:
    with pytest.raises(ValueError, match="ERROR"):
        LookupResult(status=LookupStatus.ERROR)


def test_lookup_result_is_frozen() -> None:
    result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="먹다", definitions=("to eat",)),),
    )

    with pytest.raises(FrozenInstanceError):
        result.status = LookupStatus.EMPTY  # type: ignore[misc]


def test_lookup_context_carries_only_normalized_optional_engine_inputs() -> None:
    ocr_result = OCRResult(text="한국어", confidence=0.9, quad=_quad(0, 0, 10, 10))
    context = LookupContext(text="한국어", lemma="한국어", ocr_results=(ocr_result,))
    result = LookupResult(status=LookupStatus.EMPTY, context=context)

    assert is_dataclass(context)
    assert getattr(context, "__dataclass_params__").frozen
    assert [field.name for field in fields(LookupContext)] == ["text", "lemma", "ocr_results"]
    assert result.context == context
    assert result.context.ocr_results == (ocr_result,)
    assert isinstance(result.context.ocr_results, tuple)


def test_resource_metadata_carries_state_and_compatibility() -> None:
    required_statuses = {
        "VALID",
        "MISSING",
        "OUTDATED",
        "INCOMPATIBLE",
    }
    assert required_statuses <= ResourceStatus.__members__.keys()

    metadata = ResourceMetadata(
        resource_id="krdict",
        version="2026.08",
        status=ResourceStatus.VALID,
        compatible=True,
        checksum="sha256:abc123",
    )

    assert is_dataclass(metadata)
    assert getattr(metadata, "__dataclass_params__").frozen
    assert metadata.resource_id == "krdict"
    assert metadata.status is ResourceStatus.VALID
    assert metadata.compatible is True
    assert metadata.checksum == "sha256:abc123"


@pytest.mark.parametrize("status", [ResourceStatus.MISSING, ResourceStatus.INCOMPATIBLE])
def test_missing_or_incompatible_resource_cannot_be_marked_compatible(
    status: ResourceStatus,
) -> None:
    with pytest.raises(ValueError, match="compatible"):
        ResourceMetadata(
            resource_id="krdict",
            version="2026.08",
            status=status,
            compatible=True,
        )


def test_dictionary_entry_requires_a_headword_and_a_definition() -> None:
    with pytest.raises(ValueError, match="headword"):
        DictionaryEntry(headword="", definitions=("to eat",))

    with pytest.raises(ValueError, match="definition"):
        DictionaryEntry(headword="먹다", definitions=())


def test_valid_resource_cannot_be_marked_incompatible() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        ResourceMetadata(
            resource_id="krdict",
            version="2026.08",
            status=ResourceStatus.VALID,
            compatible=False,
        )


def test_generic_provider_error_is_a_hanly_error() -> None:
    error = ProviderError("OCR provider failed")

    assert isinstance(error, HanlyError)
    assert isinstance(error, Exception)


def test_public_export_surface_is_explicit() -> None:
    import hanly

    expected = {
        "BoundingBox",
        "DictionaryEntry",
        "DictionaryProvider",
        "HanlyError",
        "LookupContext",
        "LookupResult",
        "LookupStatus",
        "MorphologyProvider",
        "OCRProvider",
        "OCRResult",
        "PixelFormat",
        "Point",
        "ProviderError",
        "Quad",
        "ROIImage",
        "ResourceMetadata",
        "ResourceStatus",
        "TokenAnalysis",
    }

    assert set(hanly.__all__) == expected
