"""Standard-library-only normalized data contracts for the Hanly engine."""

from dataclasses import dataclass
from enum import Enum
from math import ceil, floor, isfinite

from .errors import HanlyError


class PixelFormat(Enum):
    """Byte layout of a normalized ROI image."""

    GRAYSCALE_8 = "GRAYSCALE_8"
    RGB_888 = "RGB_888"
    BGR_888 = "BGR_888"
    RGBA_8888 = "RGBA_8888"


_BYTES_PER_PIXEL = {
    PixelFormat.GRAYSCALE_8: 1,
    PixelFormat.RGB_888: 3,
    PixelFormat.BGR_888: 3,
    PixelFormat.RGBA_8888: 4,
}


@dataclass(frozen=True)
class ROIImage:
    """A normalized image or region of interest handed to an `OCRProvider`.

    This is a plain value type rather than a protocol on purpose. A structural
    protocol describing `width` / `height` / pixel access would be satisfied by
    `PIL.Image`, a NumPy array, or a Qt pixmap, which would let library objects
    cross the provider seam and break `CA-INV-09`. Requiring raw bytes plus an
    explicit format forces the caller to normalize first and keeps the engine
    free of any imaging dependency.
    """

    width: int
    height: int
    pixel_format: PixelFormat
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.pixel_format, PixelFormat):
            # Without this, a caller passing "RGB_888" would surface an obscure
            # KeyError from an internal table instead of a clear contract error.
            raise TypeError("pixel_format must be a PixelFormat")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ROI image dimensions must be positive")
        expected = self.width * self.height * _BYTES_PER_PIXEL[self.pixel_format]
        if len(self.data) != expected:
            raise ValueError(
                f"ROI image data must hold {expected} bytes for "
                f"{self.width}x{self.height} {self.pixel_format.value}, "
                f"got {len(self.data)}"
            )

    @property
    def bytes_per_pixel(self) -> int:
        """Bytes each pixel occupies in `data`."""

        return _BYTES_PER_PIXEL[self.pixel_format]


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned pixel rectangle.

    Retained as the derived convenience representation; `Quad` is the
    non-lossy geometry an OCR provider reports. Negative coordinates are valid:
    a monitor placed left of the primary one has a negative virtual-desktop
    origin.
    """

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("bounding box coordinates must be ordered non-empty")


@dataclass(frozen=True)
class Point:
    """A single normalized image coordinate."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("point coordinates must be finite")


@dataclass(frozen=True)
class Quad:
    """The four detected corners of a recognized text region.

    OCR detectors report quadrilaterals, not rectangles. Keeping all four
    float corners preserves tilted and rotated text so `WordResolver` can hit
    test against the real shape instead of an inflated rectangle. Corners are
    kept in the order the provider reported them, conventionally clockwise.
    """

    p1: Point
    p2: Point
    p3: Point
    p4: Point

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("quad must have extent on both axes")

    @property
    def points(self) -> tuple[Point, Point, Point, Point]:
        """The four corners in provider-reported order."""

        return (self.p1, self.p2, self.p3, self.p4)

    @property
    def width(self) -> float:
        """Horizontal extent of the enclosing axis-aligned rectangle."""

        xs = [point.x for point in self.points]
        return max(xs) - min(xs)

    @property
    def height(self) -> float:
        """Vertical extent of the enclosing axis-aligned rectangle."""

        ys = [point.y for point in self.points]
        return max(ys) - min(ys)

    def bounding_box(self) -> BoundingBox:
        """Derive the smallest axis-aligned rectangle covering every corner.

        Bounds are expanded outward so the rectangle never clips the quad.
        """

        xs = [point.x for point in self.points]
        ys = [point.y for point in self.points]
        return BoundingBox(
            left=floor(min(xs)),
            top=floor(min(ys)),
            right=ceil(max(xs)),
            bottom=ceil(max(ys)),
        )

    @classmethod
    def from_bounding_box(cls, box: BoundingBox) -> "Quad":
        """Build an axis-aligned quad from a rectangle, clockwise from top-left."""

        left, top = float(box.left), float(box.top)
        right, bottom = float(box.right), float(box.bottom)
        return cls(
            p1=Point(left, top),
            p2=Point(right, top),
            p3=Point(right, bottom),
            p4=Point(left, bottom),
        )


@dataclass(frozen=True)
class OCRResult:
    """One normalized recognized region returned by an OCR provider.

    Confidence belongs here, on the OCR evidence itself; it is deliberately not
    aggregated onto `LookupResult`.
    """

    text: str
    confidence: float
    quad: Quad

    def __post_init__(self) -> None:
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("OCR confidence must be finite and between 0 and 1")

    @property
    def bounding_box(self) -> BoundingBox:
        """Axis-aligned rectangle derived from `quad`."""

        return self.quad.bounding_box()


@dataclass(frozen=True)
class LookupContext:
    """Optional normalized engine context retained with a lookup outcome."""

    text: str | None = None
    lemma: str | None = None
    ocr_results: tuple[OCRResult, ...] = ()


@dataclass(frozen=True)
class TokenAnalysis:
    """Normalized morphology information for one analyzed token."""

    token: str
    lemma: str
    part_of_speech: str | None = None
    morphology: str | None = None


@dataclass(frozen=True)
class DictionaryEntry:
    """Normalized dictionary information for one headword."""

    headword: str
    definitions: tuple[str, ...]
    part_of_speech: str | None = None

    def __post_init__(self) -> None:
        if not self.headword:
            raise ValueError("dictionary entries require a headword")
        if not self.definitions:
            raise ValueError("dictionary entries require at least one definition")


class LookupStatus(Enum):
    """Discriminator for successful, normal non-success, and error outcomes."""

    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    NOT_FOUND = "NOT_FOUND"
    UNUSABLE = "UNUSABLE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class LookupResult:
    """UI-independent lookup outcome with optional partial and diagnostic data.

    There is no aggregate confidence field: OCR confidence lives on each
    `OCRResult`, and a pipeline that judges recognition too weak reports
    `UNUSABLE` while preserving the evidence in `context`.
    """

    status: LookupStatus
    entries: tuple[DictionaryEntry, ...] = ()
    diagnostics: tuple[str, ...] = ()
    error: HanlyError | None = None
    context: LookupContext | None = None

    def __post_init__(self) -> None:
        if self.status is LookupStatus.SUCCESS:
            if not self.entries:
                raise ValueError("SUCCESS lookup results require at least one entry")
            if self.error is not None:
                raise ValueError("SUCCESS lookup results cannot carry an error")
        elif self.entries:
            # A not-found or unusable outcome that still carries dictionary
            # entries is contradictory; partial information belongs in
            # diagnostics or context.
            raise ValueError("only SUCCESS lookup results may carry entries")
        if self.status is LookupStatus.ERROR and self.error is None:
            raise ValueError("ERROR lookup results require an error")


class ResourceStatus(Enum):
    """Validation state for a local engine resource."""

    VALID = "VALID"
    MISSING = "MISSING"
    OUTDATED = "OUTDATED"
    INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True)
class ResourceMetadata:
    """Identity and compatibility information for a local engine resource."""

    resource_id: str
    version: str
    status: ResourceStatus
    compatible: bool
    checksum: str | None = None

    def __post_init__(self) -> None:
        if self.status in (ResourceStatus.MISSING, ResourceStatus.INCOMPATIBLE) and self.compatible:
            raise ValueError("missing or incompatible resources cannot be compatible")
        if self.status is ResourceStatus.VALID and not self.compatible:
            # INCOMPATIBLE exists for that state; VALID must not contradict it.
            raise ValueError("valid resources cannot be marked incompatible")
