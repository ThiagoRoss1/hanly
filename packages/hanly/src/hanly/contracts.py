"""Standard-library-only normalized data contracts for the Hanly engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from math import ceil, floor, isfinite
from typing import overload

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
    def from_bounding_box(cls, box: BoundingBox) -> Quad:
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
    #: The exact OCR region selected for this lookup. Clients must not guess
    #: confidence by matching text against ``ocr_results``.
    selected_ocr: OCRResult | None = None
    #: Provider-normalized morphology retained for clients that explain how a
    #: surface form relates to the dictionary lemma.
    analyses: tuple[TokenAnalysis, ...] = ()
    #: Where the resolved word sits in the image the lookup was given, which is
    #: not the whole recognized line. A client that protects the word the user
    #: is reading needs the word, not the sentence around it.
    word_region: BoundingBox | None = None
    #: The lexical unit the pointer selected, when the morphology provider
    #: reported spans. It names which part of ``text`` the answer is about.
    candidate: LexicalCandidate | None = None
    #: How ``text`` decomposes, with a gloss for each part the dictionary knows.
    #: Empty when the surface does not decompose, so a client showing a
    #: breakdown has nothing to show for a simple word.
    components: tuple[LexicalComponent, ...] = ()


@dataclass(frozen=True)
class TokenAnalysis:
    """Normalized morphology information for one analyzed token.

    ``start`` and ``length`` locate the token in the analyzed text when the
    provider reports them. Korean contractions make spans overlap — in
    ``예뻤어요`` the stem covers ``(0, 2)`` while the past marker covers
    ``(1, 1)`` — so consumers must never require them to be disjoint, nor
    rebuild the source text by concatenating token forms.
    """

    token: str
    lemma: str
    part_of_speech: str | None = None
    morphology: str | None = None
    start: int | None = None
    length: int | None = None




@dataclass(frozen=True)
class TargetResolution:
    """Where a pointer landed inside one recognized OCR region.

    ``cursor_index`` is an estimate: the OCR contract exposes a line quad
    rather than per-character boxes, so the position is derived from per-script
    advance weights. It is accurate enough to choose a word and must not be
    treated as ground truth.
    """

    region: OCRResult
    text: str
    cursor_index: int
    region_start: int

@dataclass(frozen=True)
class TextSelection:
    """One surface word and where inside it the reader is pointing.

    This is the whole input the language stage needs, and deliberately the
    whole of it. Pixels arrive at it through OCR and target resolution; a
    future accessibility or DOM reader would arrive at it from an API that
    already knows the word. Neither is visible here.

    Nothing about *where on a screen* the text was may be added to this value.
    Rectangles, window handles, element references, and desktop lifecycle stay
    in the client that owns them: an engine that knew about them could no
    longer be consumed by a caller that has none.

    ``cursor_index`` is an offset into ``text``, counted in characters. It
    selects which lexical unit of a compound the answer is about -- Korean
    writes them without spaces, so ``초대받았어요`` is one surface word holding
    more than one addressable unit.

    ``source`` is a free-form label naming what produced the selection, for
    diagnostics only. The pipeline never reads it, so no behaviour can come to
    depend on which acquisition a caller used.
    """

    text: str
    cursor_index: int = 0
    source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("selection text must be a string")
        if isinstance(self.cursor_index, bool) or not isinstance(self.cursor_index, int):
            raise TypeError("cursor_index must be an integer")
        if self.cursor_index < 0:
            raise ValueError("cursor_index must not be negative")
        if self.source is not None and not isinstance(self.source, str):
            raise TypeError("source must be a string or None")


@dataclass(frozen=True)
class LexicalCandidate:
    """One dictionary-addressable unit inside an analyzed text.

    ``start`` and ``end`` are Python string offsets covering the unit *and* the
    endings or particles attached to it, so a cursor anywhere in ``사과했어요``
    selects ``사과하다`` and a cursor on ``을`` in ``책을`` still selects ``책``.
    """

    lemma: str
    start: int
    end: int
    part_of_speech: str | None = None
    token_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.lemma:
            raise ValueError("lexical candidates require a lemma")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("lexical candidates require a non-empty forward span")

    def contains(self, index: int) -> bool:
        return self.start <= index < self.end

    def distance_to(self, index: int) -> int:
        """How far ``index`` sits outside this span; zero when inside."""

        if self.contains(index):
            return 0
        return self.start - index if index < self.start else index - self.end + 1


@dataclass(frozen=True)
class LexicalComponent:
    """One part of an analyzed surface, with the gloss naming it.

    ``start`` and ``end`` are character offsets into the analyzed text, so the
    surface is ``text[start:end]`` and is deliberately not duplicated here.
    Components may overlap: Korean contractions make a stem and the ending that
    fuses with it cover the same characters, and both are real.
    """

    lemma: str
    start: int
    end: int
    gloss: str | None = None
    part_of_speech: str | None = None
    #: A grammatical ending explains the form rather than naming a dictionary
    #: entry, which is why a missing gloss here means something different from
    #: a lexical component the dictionary simply does not hold.
    grammatical: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.lemma, str) or not self.lemma:
            raise ValueError("lexical components require a lemma")
        if isinstance(self.start, bool) or isinstance(self.end, bool):
            raise TypeError("component offsets must be integers")
        if not isinstance(self.start, int) or not isinstance(self.end, int):
            raise TypeError("component offsets must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("lexical components require a non-empty forward span")
        if self.gloss is not None and not isinstance(self.gloss, str):
            raise TypeError("component gloss must be a string or None")
        if not isinstance(self.grammatical, bool):
            raise TypeError("grammatical must be a bool")


@dataclass(frozen=True)
class MorphologyAnalysis(Sequence[TokenAnalysis]):
    """Raw morphemes plus the lexical units a lookup may address.

    The type is a sequence of its own ``tokens`` so that every consumer written
    against the older ``Sequence[TokenAnalysis]`` contract keeps working, while
    a caller that knows about lexical selection reads ``candidates``.
    """

    tokens: tuple[TokenAnalysis, ...] = ()
    candidates: tuple[LexicalCandidate, ...] = ()

    def __len__(self) -> int:
        return len(self.tokens)

    @overload
    def __getitem__(self, index: int) -> TokenAnalysis: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[TokenAnalysis]: ...

    def __getitem__(self, index: int | slice) -> TokenAnalysis | Sequence[TokenAnalysis]:
        return self.tokens[index]

    def candidate_at(self, index: int) -> LexicalCandidate | None:
        """The candidate owning ``index``, or the nearest one when none does.

        Punctuation is never a candidate, so a cursor resting on a quotation
        mark falls outside every span. Choosing the nearest unit answers with
        the word the reader is plainly pointing at instead of refusing.
        """

        if not self.candidates:
            return None
        return min(
            self.candidates,
            key=lambda candidate: (candidate.distance_to(index), candidate.start),
        )

@dataclass(frozen=True)
class DictionarySense:
    """One sense of an entry: its definition and the short gloss naming it."""

    definition: str
    gloss: str | None = None
    #: Provider-local row identity, for telling senses apart in a client. It is
    #: a build artifact rather than dictionary content, so two senses with the
    #: same gloss and definition stay equal across a database rebuild.
    sense_id: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.definition:
            raise ValueError("dictionary senses require a definition")


@dataclass(frozen=True)
class DictionaryEntry:
    """Normalized dictionary information for one headword.

    ``senses`` carries the full content; ``definitions`` is the flat view that
    providers and clients without a short gloss still use. A caller supplies
    either one and the other is derived, so the two representations cannot
    drift apart.
    """

    headword: str
    definitions: tuple[str, ...] = ()
    part_of_speech: str | None = None
    source: str | None = None
    hanja: str | None = None
    vocabulary_level: str | None = None
    senses: tuple[DictionarySense, ...] = ()
    entry_id: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.headword:
            raise ValueError("dictionary entries require a headword")
        if not self.senses and not self.definitions:
            raise ValueError("dictionary entries require at least one definition")

        if self.senses:
            object.__setattr__(self, "definitions", self._definitions_from_senses())
        else:
            object.__setattr__(self, "senses", self._senses_from_definitions())

    def _definitions_from_senses(self) -> tuple[str, ...]:
        derived = tuple(sense.definition for sense in self.senses)
        if self.definitions and tuple(self.definitions) != derived:
            raise ValueError(
                "dictionary entries cannot carry senses and definitions that disagree"
            )
        return derived

    def _senses_from_definitions(self) -> tuple[DictionarySense, ...]:
        return tuple(DictionarySense(definition=text) for text in self.definitions)


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
    #: Cheap identity of the bytes that passed deep validation, so a caller can
    #: record it and let the next validation skip a full-file integrity scan.
    integrity_identity: str | None = None

    def __post_init__(self) -> None:
        if self.status in (ResourceStatus.MISSING, ResourceStatus.INCOMPATIBLE) and self.compatible:
            raise ValueError("missing or incompatible resources cannot be compatible")
        if self.status is ResourceStatus.VALID and not self.compatible:
            # INCOMPATIBLE exists for that state; VALID must not contradict it.
            raise ValueError("valid resources cannot be marked incompatible")
