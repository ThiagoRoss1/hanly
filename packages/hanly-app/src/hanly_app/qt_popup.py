"""Native PyQt6 rendering for Hanly's dictionary popup."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, cast

from hanly import BoundingBox, DictionarySense, LookupResult, LookupStatus, Point
from PyQt6.QtCore import QObject, QPoint, QPropertyAnimation, QRectF, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QScreen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, PopupDefaultSize, TechnicalDetailLevel, Theme
from .popup import (
    LookupStopper,
    PopupComponent,
    PopupContent,
    PopupController,
    PopupEntryContent,
    PopupPosition,
    PopupRuntime,
    PopupSize,
    ScreenGeometry,
    format_lookup_result,
)
from .qt_theme import PALETTES, resolved_mode
from .runtime_trace import RuntimeTraceSink, emit_trace


class _QueuedCallbackBridge(QObject):
    callback_ready = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        connect: Any = self.callback_ready.connect
        connect(self._run, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object)
    def _run(self, callback: object) -> None:
        if callable(callback):
            callback()


class QtResultDispatcher:
    """Post a result callback to the UI thread without blocking its caller."""

    def __init__(self, parent: QObject | None = None) -> None:
        self._bridge = _QueuedCallbackBridge(parent)

    def __call__(self, callback: Callable[[], None]) -> None:
        self._bridge.callback_ready.emit(callback)


POPUP_WINDOW_FLAGS = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)

#: The card's corner radius. Everything inside is clipped to this one shape,
#: so no child background can square off a corner.
_CARD_RADIUS = 14

#: One control shape on every platform: a fixed height and an explicit radius
#: rather than a pill derived from each platform's font metrics.
_BUTTON_HEIGHT = 26
_BUTTON_RADIUS = 7

#: Vertical rhythm, in pixels: within a group, between groups, around a rule.
_TIGHT, _GROUP, _SECTION = 3, 8, 12

_FONT_STACK = (
    "'Segoe UI Variable Text','Segoe UI','SF Pro Text','Helvetica Neue',"
    "'Apple SD Gothic Neo','Malgun Gothic',sans-serif"
)

def _entry_gloss(entry: PopupEntryContent) -> str:
    """The shortest useful label for an alternate entry."""

    for sense in entry.senses:
        if sense.gloss:
            return sense.gloss
    return entry.definitions[0] if entry.definitions else ""


def _label(text: str = "", *, name: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name is not None:
        label.setObjectName(name)
    return label


def _reveal(layout: QLayout) -> None:
    """Show every widget a rebuild just added, before the card is measured.

    ``QBoxLayout`` ignores hidden items, and a widget added to a layout is only
    shown when the event loop next runs. Measuring before that reports the
    height of an almost-empty layout, which is what shrank the card on expand
    and collapse and hid most of the senses.
    """

    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        nested = item.layout()
        if nested is not None:
            _reveal(nested)
        widget = item.widget()
        if widget is not None:
            widget.setVisible(True)


def _clear(layout: QVBoxLayout | QHBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        nested = item.layout()
        if isinstance(nested, (QVBoxLayout, QHBoxLayout)):
            _clear(nested)
        widget = item.widget()
        if widget is not None:
            # Taking a widget out of a layout does not stop it painting, and
            # deletion is deferred to the event loop, so an unhidden child keeps
            # drawing at its old geometry underneath the rebuilt content.
            widget.hide()
            widget.deleteLater()


class QtPopupView(QFrame):
    """Always-on-top, mouse-interactive popup that never accepts focus."""

    def __init__(self, parent: QWidget | None = None, config: AppConfig | None = None) -> None:
        super().__init__(parent, POPUP_WINDOW_FLAGS)
        self.setObjectName("hanlyPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        configured = config or AppConfig()
        self._theme = configured.theme
        self._default_size = configured.popup_default_size
        self._detail_level = configured.technical_details
        self._expanded = self._default_size is PopupDefaultSize.EXPANDED
        self._result: LookupResult | None = None
        self._content: PopupContent | None = None
        self._prepared_result: LookupResult | None = None
        self._resize_handler: Callable[[PopupSize], None] | None = None
        self._dismiss_handler: Callable[[], None] | None = None
        #: The screen this result was placed on. Measurement and placement
        #: must agree on one screen across an interactive resize.
        self._screen: QScreen | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("hanlyPopupScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        viewport = self._scroll.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
        self._content_host = QWidget()
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(18, 16, 18, 14)
        self._content_layout.setSpacing(0)
        self._scroll.setWidget(self._content_host)
        outer.addWidget(self._scroll)

        self._footer = QWidget(self)
        self._footer.setObjectName("hanlyPopupFooter")
        self._footer_layout = QHBoxLayout(self._footer)
        self._footer_layout.setContentsMargins(12, 8, 12, 8)
        self._footer_layout.setSpacing(8)
        outer.addWidget(self._footer)

        self._animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._animation.setDuration(140)
        self._apply_theme()
        self._watch_system_theme()
        self._keep_visible_when_inactive()

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        """Paint the card as one rounded shape, footer band included.

        Children are transparent and the footer band is drawn clipped to the
        same path, which is what keeps every corner round: a child painting
        its own rectangle would square the corner it sits in.
        """

        palette = PALETTES[self._resolved_theme()]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QPainterPath()
        card.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _CARD_RADIUS, _CARD_RADIUS
        )
        painter.fillPath(card, QColor(palette["bg"]))

        painter.save()
        painter.setClipPath(card)
        footer = QRectF(self._footer.geometry())
        painter.fillRect(footer, QColor(palette["foot"]))
        painter.setPen(QPen(QColor(palette["line"]), 1))
        painter.drawLine(footer.topLeft(), footer.topRight())
        painter.restore()

        painter.setPen(QPen(QColor(palette["border"]), 1))
        painter.drawPath(card)

    def _keep_visible_when_inactive(self) -> None:
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return
        from .popup_darwin import keep_visible_when_inactive

        keep_visible_when_inactive(int(self.winId()))

    def _watch_system_theme(self) -> None:
        app = cast(QGuiApplication | None, QGuiApplication.instance())
        if app is None:
            return
        hints = app.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None)
        if signal is not None:
            signal.connect(self._system_theme_changed)

    def _system_theme_changed(self, _scheme: object) -> None:
        if self._theme is Theme.SYSTEM:
            self._apply_theme()

    def _resolved_theme(self) -> str:
        return resolved_mode(self._theme)

    def _apply_theme(self) -> None:
        p = PALETTES[self._resolved_theme()]
        rules = [
            # The card itself is painted in paintEvent; this rule only records
            # the palette so a style read reports the colours in use.
            f"QFrame#hanlyPopup {{ background:{p['bg']}; border:0; }}",
            f"QWidget {{ color:{p['ink']}; background:transparent; "
            f"font-family:{_FONT_STACK}; }}",
            "QLabel#hanlyPopupTitle { font-size:26px; font-weight:600; }",
            f"QLabel#hanlyPopupHanja {{ font-size:16px; color:{p['ink3']}; }}",
            "QLabel#hanlyPopupPrimary { font-size:16px; font-weight:600; }",
            f"QLabel#hanlyPopupPrimaryNote {{ font-size:13px; color:{p['ink2']}; }}",
            "QLabel#hanlyPopupSense { font-size:13px; font-weight:500; }",
            f"QLabel#hanlyPopupSecondary {{ font-size:12px; color:{p['ink2']}; }}",
            f"QLabel#hanlyPopupMuted {{ font-size:11px; color:{p['ink3']}; }}",
            f"QLabel#hanlyPopupNumber {{ font-size:12px; color:{p['ink3']}; }}",
            f"QLabel#hanlyPopupSection {{ font-size:10px; color:{p['ink3']}; "
            "letter-spacing:1px; }",
            f"QLabel#hanlyPopupPart {{ font-size:13px; color:{p['ink']}; }}",
            f"QLabel#hanlyPopupPartSelected {{ font-size:13px; color:{p['accent_ink']}; "
            "font-weight:600; }",
            f"QLabel#hanlyPopupChip {{ background:{p['accent_wash']}; "
            f"color:{p['accent_ink']}; border-radius:9px; padding:2px 8px; "
            "font-size:11px; }",
            f"QLabel#hanlyPopupMeta {{ font-size:11px; color:{p['ink3']}; }}",
            f"QFrame#hanlyPopupDivider {{ background:{p['line']}; border:0; }}",
            "QWidget#hanlyPopupFooter { background:transparent; border:0; }",
            f"QPushButton {{ color:{p['ink2']}; border:1px solid {p['line']}; "
            f"background:transparent; border-radius:{_BUTTON_RADIUS}px; "
            f"min-height:{_BUTTON_HEIGHT - 2}px; max-height:{_BUTTON_HEIGHT - 2}px; "
            "padding:0 12px; font-size:12px; font-weight:500; }",
            f"QPushButton:hover {{ color:{p['ink']}; background:{p['hover']}; "
            f"border-color:{p['border']}; }}",
            f"QPushButton:pressed {{ background:{p['press']}; }}",
            f"QPushButton#hanlyPopupSize {{ color:{p['accent_ink']}; "
            f"background:{p['accent_wash']}; border-color:transparent; }}",
            f"QPushButton#hanlyPopupSize:hover {{ background:{p['accent_hover']}; "
            f"color:{p['accent_ink']}; }}",
            f"QPushButton#hanlyPopupSize:pressed {{ background:{p['accent']}; "
            f"color:{p['bg']}; }}",
            "QScrollArea#hanlyPopupScroll { border:0; background:transparent; }",
            "QScrollBar:vertical { width:10px; background:transparent; "
            "margin:4px 2px 4px 0; }",
            f"QScrollBar::handle:vertical {{ background:{p['scroll']}; "
            "border-radius:3px; min-height:28px; }",
            f"QScrollBar::handle:vertical:hover {{ background:{p['scroll_hover']}; }}",
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }",
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical "
            "{ background:transparent; }",
        ]
        self.setStyleSheet("".join(rules))
        self.update()

    @property
    def popup_size(self) -> PopupSize:
        return PopupSize(max(1, self.width()), max(1, self.height()))

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_resize_handler(self, handler: Callable[[PopupSize], None]) -> None:
        self._resize_handler = handler

    def set_dismiss_handler(self, handler: Callable[[], None]) -> None:
        """Called when the user dismisses this card from inside it."""

        self._dismiss_handler = handler

    def _request_dismiss(self) -> None:
        handler = self._dismiss_handler
        if handler is not None:
            handler()
            return
        # Without a composed handler the view can still take itself off screen,
        # which keeps a standalone view and the benchmark harness usable.
        self.hide()

    def apply_preferences(self, config: AppConfig) -> None:
        """Apply theme/detail live; default density affects the next result."""

        self._theme = config.theme
        self._default_size = config.popup_default_size
        detail_changed = self._detail_level is not config.technical_details
        self._detail_level = config.technical_details
        self._apply_theme()
        if detail_changed and self._result is not None:
            self._content = format_lookup_result(self._result, self._detail_level)
            self._rebuild()
            self._resize_and_notify()

    def prepare_result(self, result: LookupResult) -> PopupSize:
        self._result = result
        self._prepared_result = result
        self._expanded = self._default_size is PopupDefaultSize.EXPANDED
        self._content = format_lookup_result(result, self._detail_level)
        self._rebuild()
        return self._resize_to_content()

    def _rebuild(self) -> None:
        _clear(self._content_layout)
        _clear(self._footer_layout)
        content = self._content
        if content is None:
            return
        if content.status is LookupStatus.SUCCESS:
            self._build_success(content)
        else:
            self._build_non_success(content)
        self._build_footer(content)

    def _build_success(self, content: PopupContent) -> None:
        assert content.entry is not None
        entry = content.entry
        layout = self._content_layout

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(
            _label(entry.headword, name="hanlyPopupTitle"), 1, Qt.AlignmentFlag.AlignBottom
        )
        if entry.hanja:
            hanja = _label(entry.hanja, name="hanlyPopupHanja")
            hanja.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
            header.addWidget(hanja, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(header)
        layout.addSpacing(_TIGHT)
        layout.addLayout(self._metadata_row(content))

        senses = entry.senses if self._expanded else entry.senses[:2]
        if senses:
            layout.addSpacing(_SECTION)
            primary, rest = senses[0], senses[1:]
            layout.addLayout(self._primary_sense(primary))
            for index, sense in enumerate(rest, start=2):
                layout.addSpacing(_GROUP + 2)
                layout.addLayout(self._numbered_sense(index, sense))

        self._build_reading(content)
        self._build_components(content)
        if self._expanded and content.other_entries:
            self._section("OTHER ENTRIES")
            for other in content.other_entries:
                gloss = _entry_gloss(other)
                row = _label(
                    " · ".join(filter(None, (other.headword, other.part_of_speech, gloss))),
                    name="hanlyPopupSecondary",
                )
                row.setWordWrap(True)
                layout.addWidget(row)
                layout.addSpacing(_TIGHT)

        if self._detail_level is TechnicalDetailLevel.FULL and content.technical_lines:
            self._section("DETAILS")
            technical = _label("\n".join(content.technical_lines), name="hanlyPopupMuted")
            technical.setWordWrap(True)
            layout.addWidget(technical)

    def _metadata_row(self, content: PopupContent) -> QHBoxLayout:
        """Part of speech as the one marked chip, then quiet source and level."""

        assert content.entry is not None
        row = QHBoxLayout()
        row.setSpacing(8)
        if content.entry.part_of_speech:
            row.addWidget(_label(content.entry.part_of_speech, name="hanlyPopupChip"))
        metadata = " · ".join(
            filter(
                None,
                (
                    content.source.upper() if content.source else None,
                    content.entry.vocabulary_level,
                ),
            )
        )
        if metadata:
            row.addWidget(_label(metadata, name="hanlyPopupMeta"))
        row.addStretch(1)
        return row

    def _build_reading(self, content: PopupContent) -> None:
        """How the surface on screen reads as the headword above."""

        changed = bool(content.surface and content.lemma and content.surface != content.lemma)
        if not (content.analysis or changed):
            return
        self._section("WORD ANALYSIS" if self._expanded else "READ AS")
        if changed:
            relation = _label(f"{content.surface}  →  {content.lemma}", name="hanlyPopupPart")
            relation.setWordWrap(True)
            self._content_layout.addWidget(relation)
        if content.analysis:
            if changed:
                self._content_layout.addSpacing(_TIGHT + 1)
            pieces = _label(
                "  +  ".join(piece.text for piece in content.analysis),
                name="hanlyPopupSecondary",
            )
            pieces.setWordWrap(True)
            self._content_layout.addWidget(pieces)
            roles = " · ".join(piece.role for piece in content.analysis if piece.role)
            if roles:
                role_label = _label(roles, name="hanlyPopupMuted")
                role_label.setWordWrap(True)
                self._content_layout.addWidget(role_label)

    def _build_components(self, content: PopupContent) -> None:
        if not content.components:
            return
        self._section("HOW THIS FORM IS BUILT")
        for index, component in enumerate(content.components):
            if index:
                self._content_layout.addSpacing(_TIGHT + 1)
            self._content_layout.addLayout(self._component_row(component))

    def _section(self, title: str) -> None:
        """One rule, one small label, one gap: every section starts the same."""

        self._content_layout.addSpacing(_SECTION)
        self._content_layout.addWidget(self._divider())
        self._content_layout.addSpacing(_SECTION - 2)
        self._content_layout.addWidget(_label(title, name="hanlyPopupSection"))
        self._content_layout.addSpacing(_GROUP - 2)

    def _build_non_success(self, content: PopupContent) -> None:
        if content.surface:
            word = _label(content.surface, name="hanlyPopupTitle")
            word.setWordWrap(True)
            self._content_layout.addWidget(word)
            self._content_layout.addSpacing(_GROUP)
        title = _label(content.title, name="hanlyPopupSense")
        body = _label(content.body, name="hanlyPopupSecondary")
        tip = _label(content.tip, name="hanlyPopupMuted")
        body.setWordWrap(True)
        tip.setWordWrap(True)
        self._content_layout.addWidget(title)
        self._content_layout.addSpacing(_TIGHT + 1)
        self._content_layout.addWidget(body)
        self._content_layout.addSpacing(_TIGHT)
        self._content_layout.addWidget(tip)
        if content.technical_lines:
            self._content_layout.addSpacing(_GROUP)
            technical = _label(" · ".join(content.technical_lines), name="hanlyPopupMuted")
            technical.setWordWrap(True)
            self._content_layout.addWidget(technical)

    def _build_footer(self, content: PopupContent) -> None:
        if (
            self._detail_level is TechnicalDetailLevel.BASIC
            and content.technical_lines
        ):
            self._footer_layout.addWidget(
                _label(" · ".join(content.technical_lines), name="hanlyPopupMuted")
            )
        self._footer_layout.addStretch(1)
        if content.status is LookupStatus.SUCCESS and self._can_expand(content):
            # The one disclosure control: expanding also reveals the other
            # entries, so there is no second button competing with it.
            size = self._button(
                "Collapse" if self._expanded else "Expand", "hanlyPopupSize"
            )
            size.clicked.connect(self._toggle_size)
            self._footer_layout.addWidget(size)

        # The window never accepts focus, so it can receive neither a key press
        # nor a click outside itself. A control inside the card is the one
        # dismissal the user can always reach.
        close = self._button("Close", "hanlyPopupClose")
        close.clicked.connect(self._request_dismiss)
        self._footer_layout.addWidget(close)

    def _can_expand(self, content: PopupContent) -> bool:
        """Whether Expand would show anything the compact card does not."""

        if self._expanded:
            return True
        entry = content.entry
        return bool(
            (entry is not None and len(entry.senses) > 2)
            or content.other_entries
            or content.analysis
        )

    @staticmethod
    def _button(text: str, name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setAccessibleName(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(_BUTTON_HEIGHT)
        return button

    def _component_row(self, component: PopupComponent) -> QHBoxLayout:
        """One part of the form: the characters, then what they contribute.

        A grammatical part explains the form rather than naming a word, so a
        missing gloss there is expected; a lexical part without one is a word
        the dictionary does not hold, and saying so is better than inventing it.
        """

        meaning = component.gloss
        if meaning is None:
            meaning = "grammatical" if component.grammatical else "no dictionary entry"
        row = QHBoxLayout()
        row.setSpacing(10)
        part = _label(
            component.surface,
            name="hanlyPopupPartSelected" if component.selected else "hanlyPopupPart",
        )
        part.setMinimumWidth(56)
        row.addWidget(part, 0, Qt.AlignmentFlag.AlignTop)
        gloss = _label(
            meaning, name="hanlyPopupMuted" if component.grammatical else "hanlyPopupSecondary"
        )
        gloss.setWordWrap(True)
        row.addWidget(gloss, 1, Qt.AlignmentFlag.AlignTop)
        return row

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("hanlyPopupDivider")
        line.setFixedHeight(1)
        return line

    def _toggle_size(self) -> None:
        self._expanded = not self._expanded
        self._rebuild()
        self._resize_and_notify()

    @staticmethod
    def _primary_sense(sense: DictionarySense) -> QVBoxLayout:
        """The first sense leads: its translation is the answer to the lookup."""

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(_TIGHT)
        lead = _label(sense.gloss or sense.definition, name="hanlyPopupPrimary")
        lead.setWordWrap(True)
        body.addWidget(lead)
        if sense.gloss:
            note = _label(sense.definition, name="hanlyPopupPrimaryNote")
            note.setWordWrap(True)
            body.addWidget(note)
        return body

    @staticmethod
    def _numbered_sense(index: int, sense: DictionarySense) -> QHBoxLayout:
        """A further sense, numbered, with its gloss above its fuller definition.

        A sense without a gloss shows the definition in the primary slot rather
        than an empty row, so nothing is invented and nothing is repeated.
        """

        row = QHBoxLayout()
        row.setSpacing(6)
        number = _label(str(index), name="hanlyPopupNumber")
        number.setFixedWidth(14)
        row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)
        lead = _label(sense.gloss or sense.definition, name="hanlyPopupSense")
        lead.setWordWrap(True)
        body.addWidget(lead)
        if sense.gloss:
            note = _label(sense.definition, name="hanlyPopupSecondary")
            note.setWordWrap(True)
            body.addWidget(note)
        row.addLayout(body, 1)
        return row

    def _resize_to_content(self) -> PopupSize:
        width = 386 if self._expanded else 340
        _reveal(self._footer_layout)
        footer_height = self._footer.sizeHint().height()
        max_height = self._available_height()

        desired = self._measure_content(width - 2) + footer_height + 2
        scrolls = desired > max_height
        if scrolls:
            # A visible scrollbar takes width from the text, which makes it wrap
            # taller. One further pass at the real content width settles it.
            scrollbar = self._scroll.verticalScrollBar()
            bar = scrollbar.sizeHint().width() if scrollbar is not None else 0
            desired = self._measure_content(width - 2 - bar) + footer_height + 2

        height = max(96, min(desired, max_height))
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if scrolls
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setFixedSize(width, height)
        return PopupSize(width, height)

    def _measure_content(self, width: int) -> int:
        """The height the rebuilt content actually needs at ``width``.

        Word-wrapped text has no single natural height, so the wrapped height
        must be asked for at the width the content will occupy. Reading
        ``sizeHint()`` straight after a rebuild reports the height of a layout
        that has not been arranged yet, which is what shrank the card on every
        expand and collapse.
        """

        host = self._content_host
        host.setFixedWidth(width)
        host.ensurePolished()

        layout = self._content_layout
        _reveal(layout)
        layout.activate()
        wrapped = layout.heightForWidth(width)
        return wrapped if wrapped > 0 else layout.sizeHint().height()

    def _available_height(self) -> int:
        """Usable height on the screen this popup is being measured for.

        Measurement and placement must agree on one screen. Asking for the
        screen under the cursor during an interactive resize can pick a
        different monitor than the one the result was placed on.
        """

        screen = self._screen or QApplication.screenAt(QCursor.pos())
        screen = screen or QApplication.primaryScreen()
        if screen is None:
            return 2 ** 15
        return screen.availableGeometry().height() - 24

    def _resize_and_notify(self) -> None:
        size = self._resize_to_content()
        if self._resize_handler is not None:
            self._resize_handler(size)

    def _render_if_needed(self, result: LookupResult) -> None:
        if result is not self._prepared_result:
            self.prepare_result(result)

    def _show_at(self, result: LookupResult, position: PopupPosition) -> None:
        self._screen = QApplication.screenAt(QPoint(position.x, position.y))
        self._render_if_needed(result)
        self.move(position.x, position.y)
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._animation.stop()
            self._animation.setStartValue(0.0)
            self._animation.setEndValue(1.0)
            self._animation.start()
        else:
            self.show()

    def show_result(self, result: LookupResult, position: PopupPosition) -> None:
        self._show_at(result, position)

    def update_result(self, result: LookupResult, position: PopupPosition) -> None:
        self._show_at(result, position)

    def reposition(self, position: PopupPosition) -> None:
        self.move(position.x, position.y)


class QtPopupTrigger:
    """Open a popup result at the current cursor and available screen."""

    def __init__(
        self,
        popup: PopupController,
        *,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> None:
        self._popup = popup
        self._trace_sink = trace_sink

    def open(
        self,
        result: LookupResult,
        *,
        lookup_request_id: int | None = None,
        anchor: BoundingBox | None = None,
    ) -> PopupPosition:
        cursor = QCursor.pos()
        # The popup belongs on the screen of the word it describes, which the
        # cursor may already have left.
        where = (
            QPoint(int(anchor.left), int(anchor.top)) if anchor is not None else cursor
        )
        screen = QApplication.screenAt(where) or QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("no Qt screen is available for popup placement")
        geometry = screen.availableGeometry()
        try:
            position = self._popup.open(
                result,
                Point(float(cursor.x()), float(cursor.y())),
                ScreenGeometry(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                anchor=anchor,
            )
        except BaseException as error:
            emit_trace(
                self._trace_sink,
                "popup_visibility_error",
                stage="popup_visible",
                lookup_request_id=lookup_request_id,
                error_type=type(error).__name__,
            )
            raise
        emit_trace(
            self._trace_sink,
            "popup_visible",
            stage="popup_visible",
            lookup_request_id=lookup_request_id,
            result_status=result.status.value,
        )
        return position


class QtPopupRuntime:
    def __init__(
        self,
        lookup_controller: LookupStopper,
        *,
        trace_sink: RuntimeTraceSink | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self.dispatcher = QtResultDispatcher()
        self.view = QtPopupView(config=config)
        self.popup = PopupController(self.view, popup_size=self.view.popup_size)
        self.trigger = QtPopupTrigger(self.popup, trace_sink=trace_sink)
        self._runtime = PopupRuntime(self.popup, lookup_controller)

    def open(self, result: LookupResult) -> PopupPosition:
        return self.trigger.open(result)

    def shutdown(self) -> None:
        self._runtime.shutdown()


__all__ = [
    "QtPopupRuntime",
    "QtPopupTrigger",
    "QtPopupView",
    "QtResultDispatcher",
]
