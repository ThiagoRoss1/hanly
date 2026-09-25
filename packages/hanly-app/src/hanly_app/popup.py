"""Qt-independent popup presentation, placement, and lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import floor
from typing import Protocol

from hanly import (
    BoundingBox,
    DictionaryEntry,
    DictionarySense,
    LookupContext,
    LookupResult,
    LookupStatus,
    Point,
    TokenAnalysis,
)

from .config import TechnicalDetailLevel


@dataclass(frozen=True)
class ScreenGeometry:
    """Available screen rectangle in virtual-desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen geometry dimensions must be positive")

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class PopupSize:
    """Measured popup frame size used by pure placement logic."""

    width: int = 340
    height: int = 180

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("popup size dimensions must be positive")


@dataclass(frozen=True)
class PopupPosition:
    """Top-left popup position in virtual-desktop coordinates."""

    x: int
    y: int


@dataclass(frozen=True)
class PopupEntryContent:
    """One dictionary entry without provider-specific storage details."""

    headword: str
    definitions: tuple[str, ...]
    part_of_speech: str | None = None
    hanja: str | None = None
    vocabulary_level: str | None = None
    senses: tuple[DictionarySense, ...] = ()


@dataclass(frozen=True)
class PopupAnalysisPiece:
    """One learner-facing piece of normalized morphology."""

    text: str
    role: str


@dataclass(frozen=True)
class PopupComponent:
    """One part of the hovered form, as the panel shows it."""

    surface: str
    lemma: str
    gloss: str | None = None
    grammatical: bool = False
    #: The part the pointer is on, which the popup marks so a reader can see
    #: which piece of the form the headword above is about.
    selected: bool = False


@dataclass(frozen=True)
class PopupContent:
    """Typed, provider-independent presentation data for one popup."""

    status: LookupStatus
    title: str
    body: str = ""
    tip: str = ""
    entry: PopupEntryContent | None = None
    surface: str | None = None
    lemma: str | None = None
    analysis: tuple[PopupAnalysisPiece, ...] = ()
    components: tuple[PopupComponent, ...] = ()
    other_entries: tuple[PopupEntryContent, ...] = ()
    confidence: float | None = None
    source: str | None = None
    technical_lines: tuple[str, ...] = ()


class PopupView(Protocol):
    """Minimal concrete-view lifecycle required by :class:`PopupController`."""

    def show_result(self, result: LookupResult, position: PopupPosition) -> None: ...

    def update_result(self, result: LookupResult, position: PopupPosition) -> None: ...

    def hide(self) -> None: ...

    def close(self) -> bool | None: ...


class LookupStopper(Protocol):
    def stop(self, *, wait: bool) -> None: ...


#: A popup appears for a Korean word that was read and looked up, and for a
#: genuine fault. Everything else is silence by design: an empty crop, a
#: picture, English text, or a word the dictionary does not carry are all
#: "nothing to hover", and a card for each of those turns ordinary pointer
#: movement into a stream of dismissable noise.
_PRESENTED_STATUSES = frozenset({LookupStatus.SUCCESS, LookupStatus.ERROR})


def should_present(result: LookupResult) -> bool:
    """Whether this outcome is worth putting on screen at all."""

    return isinstance(result, LookupResult) and result.status in _PRESENTED_STATUSES


def _entry_content(entry: DictionaryEntry) -> PopupEntryContent:
    return PopupEntryContent(
        headword=entry.headword,
        definitions=entry.definitions,
        part_of_speech=entry.part_of_speech,
        hanja=entry.hanja,
        vocabulary_level=entry.vocabulary_level,
        senses=entry.senses,
    )


def _analysis_role(analysis: TokenAnalysis) -> str:
    tag = (analysis.part_of_speech or "").split("-", 1)[0].upper()
    roles = {
        "NNG": "noun",
        "NNP": "proper noun",
        "NNB": "dependent noun",
        "NR": "number",
        "NP": "pronoun",
        "VV": "verb stem",
        "VA": "adjective stem",
        "JKO": "object particle",
        "JKS": "subject particle",
        "JKG": "possessive particle",
        "JKB": "particle",
        "JKC": "complement particle",
        "JC": "connecting particle",
        "EC": "connecting ending",
        "ETM": "modifier ending",
        "ETN": "nominalizing ending",
    }
    if tag == "JX" and analysis.token in {"은", "는"}:
        return "topic particle"
    if tag == "JX":
        return "auxiliary particle"
    if tag == "EP" and any(marker in analysis.token for marker in ("었", "았", "였")):
        return "past"
    if tag == "EP":
        return "prefinal ending"
    if tag == "EF" and any(marker in analysis.token for marker in ("습니다", "ㅂ니다")):
        return "formal polite"
    if tag == "EF":
        return "ending"
    return roles.get(tag) or analysis.morphology or analysis.part_of_speech or ""


def _analysis_text(analysis: TokenAnalysis) -> str:
    tag = (analysis.part_of_speech or "").split("-", 1)[0].upper()
    if tag in {"VV", "VA"}:
        return f"{analysis.token}-"
    if tag == "EP":
        return f"-{analysis.token}-"
    if tag.startswith("E"):
        return f"-{analysis.token}"
    return analysis.token


def _popup_components(context: LookupContext | None) -> tuple[PopupComponent, ...]:
    """Render the engine's decomposition, without recomputing any of it.

    The surface of each part is a slice of the text the engine analyzed, so the
    panel cannot disagree with the answer above it. A decomposition of one part
    explains nothing, so it is dropped rather than shown as a single row.
    """

    if context is None or not context.components or not context.text:
        return ()

    text = context.text
    selected = context.candidate
    pieces = tuple(
        PopupComponent(
            surface=text[component.start : component.end],
            lemma=component.lemma,
            gloss=component.gloss,
            grammatical=component.grammatical,
            # Where a lexical and a grammatical part cover the same characters,
            # only the lexical one is what the reader picked.
            selected=(
                not component.grammatical
                and selected is not None
                and component.lemma == selected.lemma
            ),
        )
        for component in context.components
    )
    return pieces if len(pieces) > 1 else ()


def _technical_lines(
    result: LookupResult,
    detail_level: TechnicalDetailLevel,
    confidence: float | None,
    source: str | None,
) -> tuple[str, ...]:
    if detail_level is TechnicalDetailLevel.OFF:
        return ()

    lines: list[str] = []
    if confidence is not None:
        lines.append(f"OCR {confidence:.0%}")
    if source:
        lines.append(source.upper())
    if detail_level is TechnicalDetailLevel.FULL:
        lines.append(result.status.value)
        lines.extend(result.diagnostics)
        if result.error is not None:
            lines.append(type(result.error).__name__)
    return tuple(dict.fromkeys(line for line in lines if line))


def format_lookup_result(
    result: LookupResult,
    detail_level: TechnicalDetailLevel = TechnicalDetailLevel.OFF,
) -> PopupContent:
    """Build the popup's testable presentation model from normalized data."""

    if not isinstance(result, LookupResult):
        raise TypeError("result must be a LookupResult")
    if not isinstance(detail_level, TechnicalDetailLevel):
        raise TypeError("detail_level must be a TechnicalDetailLevel")

    context = result.context
    confidence = (
        context.selected_ocr.confidence
        if context is not None and context.selected_ocr is not None
        else None
    )
    source = result.entries[0].source if result.entries else None
    technical = _technical_lines(result, detail_level, confidence, source)

    if result.status is LookupStatus.SUCCESS:
        entry = _entry_content(result.entries[0])
        analyses = context.analyses if context is not None else ()
        analysis = tuple(
            PopupAnalysisPiece(_analysis_text(item), _analysis_role(item))
            for item in analyses
            if item.token
        )
        return PopupContent(
            status=result.status,
            title=entry.headword,
            entry=entry,
            components=_popup_components(context),
            surface=context.text if context is not None else None,
            lemma=context.lemma if context is not None else entry.headword,
            analysis=analysis,
            other_entries=tuple(_entry_content(item) for item in result.entries[1:]),
            confidence=confidence,
            source=source,
            technical_lines=technical,
        )

    messages = {
        LookupStatus.EMPTY: (
            "Nothing to read there",
            "No text was recognized in that region.",
            "Hover a little closer to the characters.",
        ),
        LookupStatus.NOT_FOUND: (
            "Not in the dictionary",
            "The text was read, but no dictionary entry matched.",
            "It may be slang, a name, or an unsupported spelling.",
        ),
        LookupStatus.UNUSABLE: (
            "Too unclear to look up",
            "Hanly could not identify a safe Korean dictionary lookup.",
            "Try hovering closer or enlarging the source text.",
        ),
        LookupStatus.ERROR: (
            "Lookup failed",
            "Hanly could not finish this lookup.",
            "Open the Control Center to check resources and logs.",
        ),
    }
    title, body, tip = messages[result.status]
    return PopupContent(
        status=result.status,
        title=title,
        body=body,
        tip=tip,
        surface=context.text if context is not None else None,
        lemma=context.lemma if context is not None else None,
        confidence=confidence,
        technical_lines=technical,
    )


GeometryChanged = Callable[[PopupPosition, PopupSize], None]

#: Space between a retained word and its popup. Small, so the crossing from the
#: word to the popup is short and nothing else fits between them.
_WORD_GAP_PIXELS = 6


class PopupController:
    """Own measured popup placement and lifecycle for completed results."""

    def __init__(
        self,
        view: PopupView,
        *,
        popup_size: PopupSize | None = None,
        offset: int = 16,
        on_geometry_changed: GeometryChanged | None = None,
    ) -> None:
        if offset < 0:
            raise ValueError("popup offset must not be negative")
        self._view = view
        self._popup_size = popup_size or PopupSize()
        self._offset = offset
        self._on_geometry_changed = on_geometry_changed
        self._visible = False
        self._result: LookupResult | None = None
        self._position: PopupPosition | None = None
        self._cursor: Point | None = None
        self._screen: ScreenGeometry | None = None
        self._anchor: BoundingBox | None = None
        self._above: bool | None = None

        self._on_dismissed: Callable[[], None] | None = None

        resize_handler = getattr(view, "set_resize_handler", None)
        if callable(resize_handler):
            resize_handler(self._handle_resize)
        dismiss_handler = getattr(view, "set_dismiss_handler", None)
        if callable(dismiss_handler):
            dismiss_handler(self._handle_dismiss)

    def set_dismissed_handler(self, handler: Callable[[], None] | None) -> None:
        """Called after the user dismisses a card from inside it.

        Composition uses it to tell the hover runtime to forget the answer, so
        a dismissed card cannot be resurrected by geometry for a stale target.
        """

        self._on_dismissed = handler

    def _handle_dismiss(self) -> None:
        self.clear()
        if self._on_dismissed is not None:
            self._on_dismissed()

    @property
    def popup_size(self) -> PopupSize:
        return self._popup_size

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def result(self) -> LookupResult | None:
        return self._result

    @property
    def position(self) -> PopupPosition | None:
        return self._position

    def set_geometry_handler(self, handler: GeometryChanged | None) -> None:
        self._on_geometry_changed = handler

    def position_for(
        self,
        cursor: Point,
        screen: ScreenGeometry,
        size: PopupSize | None = None,
        *,
        anchor: BoundingBox | None = None,
    ) -> PopupPosition:
        """Where a popup of ``size`` goes for this cursor or retained word."""

        return self._place(cursor, screen, size or self._popup_size, anchor, None)[0]

    def _place(
        self,
        cursor: Point,
        screen: ScreenGeometry,
        size: PopupSize,
        anchor: BoundingBox | None,
        above: bool | None,
    ) -> tuple[PopupPosition, bool]:
        """Place the popup, keeping a side already chosen when ``above`` is set.

        Anchored to a word it sits just below it, aligned with its left edge,
        and goes above only when the screen has no room below. Without a word
        the cursor is the anchor, as before. A side already chosen is kept, so a
        resize never throws the popup to the other side of the word -- the
        pointer on its Expand control would be left over empty screen.
        """

        if not isinstance(cursor, Point):
            raise TypeError("cursor must be a Point")
        if not isinstance(screen, ScreenGeometry):
            raise TypeError("screen must be a ScreenGeometry")

        width, height = size.width, size.height
        if anchor is None:
            gap = self._offset
            x = floor(cursor.x + gap)
            if x + width > screen.right:
                x = floor(cursor.x - gap - width)
            top_edge = bottom_edge = cursor.y
        else:
            gap = _WORD_GAP_PIXELS
            x = floor(anchor.left)
            top_edge, bottom_edge = anchor.top, anchor.bottom

        below_y = floor(bottom_edge + gap)
        if above is None:
            above = below_y + height > screen.bottom
        y = floor(top_edge - gap - height) if above else below_y
        x = min(max(x, screen.left), max(screen.left, screen.right - width))
        y = min(max(y, screen.top), max(screen.top, screen.bottom - height))
        return PopupPosition(x, y), above

    def open(
        self,
        result: LookupResult,
        cursor: Point,
        screen: ScreenGeometry,
        *,
        anchor: BoundingBox | None = None,
    ) -> PopupPosition:
        """Measure, place, and show every normalized lookup outcome."""

        if not isinstance(result, LookupResult):
            raise TypeError("result must be a LookupResult")
        if self._visible and self._position is not None and result == self._result:
            # The same answer again: its content is already on screen and is
            # not rebuilt. It moves only if what it is anchored to moved.
            if anchor == self._anchor and (anchor is not None or cursor == self._cursor):
                return self._position
            return self._move(cursor, screen, anchor)

        self._cursor, self._screen, self._anchor = cursor, screen, anchor
        prepare = getattr(self._view, "prepare_result", None)
        if callable(prepare):
            measured = prepare(result)
            if isinstance(measured, PopupSize):
                self._popup_size = measured
        position, self._above = self._place(
            cursor, screen, self._popup_size, anchor, None
        )

        if self._visible:
            self._view.update_result(result, position)
        else:
            self._view.show_result(result, position)
            self._visible = True
        self._result = result
        self._position = position
        self._notify_geometry()
        return position

    def update(
        self,
        result: LookupResult,
        cursor: Point,
        screen: ScreenGeometry,
        *,
        anchor: BoundingBox | None = None,
    ) -> PopupPosition:
        return self.open(result, cursor, screen, anchor=anchor)

    def _move(
        self, cursor: Point, screen: ScreenGeometry, anchor: BoundingBox | None
    ) -> PopupPosition:
        self._cursor, self._screen, self._anchor = cursor, screen, anchor
        position, self._above = self._place(
            cursor, screen, self._popup_size, anchor, None
        )
        reposition = getattr(self._view, "reposition", None)
        if callable(reposition):
            reposition(position)
        self._position = position
        self._notify_geometry()
        return position

    def _handle_resize(self, size: PopupSize) -> None:
        if not isinstance(size, PopupSize):
            return
        self._popup_size = size
        if not self._visible or self._cursor is None or self._screen is None:
            return
        position, self._above = self._place(
            self._cursor, self._screen, size, self._anchor, self._above
        )
        reposition = getattr(self._view, "reposition", None)
        if callable(reposition):
            reposition(position)
        self._position = position
        self._notify_geometry()

    def _notify_geometry(self) -> None:
        if self._on_geometry_changed is not None and self._position is not None:
            self._on_geometry_changed(self._position, self._popup_size)

    def hide(self) -> None:
        if not self._visible:
            return
        self._view.hide()
        self._visible = False

    def clear(self) -> None:
        self.hide()
        self._result = None
        self._position = None
        self._cursor = None
        self._screen = None
        self._anchor = None
        self._above = None

    def close(self) -> None:
        self.hide()
        self._view.close()

    def shutdown(self, lookup_controller: LookupStopper) -> None:
        self.close()
        lookup_controller.stop(wait=False)


class PopupRuntime:
    def __init__(self, popup: PopupController, lookup_controller: LookupStopper) -> None:
        self._popup = popup
        self._lookup_controller = lookup_controller

    def shutdown(self) -> None:
        self._popup.shutdown(self._lookup_controller)


__all__ = [
    "LookupStopper",
    "PopupAnalysisPiece",
    "PopupContent",
    "PopupController",
    "PopupEntryContent",
    "PopupPosition",
    "PopupRuntime",
    "PopupSize",
    "PopupView",
    "ScreenGeometry",
    "format_lookup_result",
]
