"""Native PyQt6 rendering for Hanly's dictionary popup."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, cast

from hanly import BoundingBox, DictionarySense, LookupResult, LookupStatus, Point
from PyQt6.QtCore import QObject, QPoint, QPropertyAnimation, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QCursor,
    QGuiApplication,
    QPainter,
    QPaintEvent,
    QPalette,
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
    QStyle,
    QStyleOption,
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

_PALETTES = {
    "light": {
        "bg": "#FFFFFF",
        "foot": "#F5F4F2",
        "border": "#D3D1CE",
        "line": "#E7E5E3",
        "wash": "#F1F0EE",
        "ink": "#202124",
        "ink2": "#5F6268",
        "ink3": "#85888F",
        "accent": "#E88CA1",
        "accent_ink": "#B75C76",
        "accent_wash": "rgba(232, 140, 161, 41)",
        "accent_hover": "rgba(232, 140, 161, 66)",
        "hover": "#E7E5E3",
        "press": "#DAD8D5",
        "scroll": "rgba(32, 33, 36, 46)",
        "scroll_hover": "rgba(32, 33, 36, 92)",
        "danger": "#A0302A",
    },
    "dark": {
        "bg": "#232428",
        "foot": "#1C1D20",
        "border": "#3A3C41",
        "line": "#2F3135",
        "wash": "#292A2E",
        "ink": "#F2F2F3",
        "ink2": "#B8BAC0",
        "ink3": "#858890",
        "accent": "#F08FA6",
        "accent_ink": "#F4A5B6",
        "accent_wash": "rgba(240, 143, 166, 36)",
        "accent_hover": "rgba(240, 143, 166, 64)",
        "hover": "#32343A",
        "press": "#3A3D44",
        "scroll": "rgba(242, 242, 243, 48)",
        "scroll_hover": "rgba(242, 242, 243, 104)",
        "danger": "#F09086",
    },
}


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
        self._others_open = False
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
        self._content_host = QWidget()
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(18, 15, 18, 14)
        self._content_layout.setSpacing(0)
        self._scroll.setWidget(self._content_host)
        outer.addWidget(self._scroll)

        self._footer = QWidget(self)
        self._footer.setObjectName("hanlyPopupFooter")
        self._footer_layout = QHBoxLayout(self._footer)
        self._footer_layout.setContentsMargins(10, 8, 12, 8)
        self._footer_layout.setSpacing(8)
        outer.addWidget(self._footer)

        self._animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._animation.setDuration(140)
        self._apply_theme()
        self._watch_system_theme()
        self._keep_visible_when_inactive()

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        style = self.style()
        if style is None:
            return
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)

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
        if self._theme is not Theme.SYSTEM:
            return self._theme.value
        app = cast(QGuiApplication | None, QGuiApplication.instance())
        if app is not None:
            scheme = getattr(app.styleHints(), "colorScheme", lambda: None)()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
            if app.palette().color(QPalette.ColorRole.Window).lightness() < 128:
                return "dark"
        return "light"

    def _apply_theme(self) -> None:
        p = _PALETTES[self._resolved_theme()]
        rules = [
            f"QFrame#hanlyPopup {{ background:{p['bg']}; border:1px solid {p['border']}; "
            "border-radius:14px; }",
            f"QWidget {{ color:{p['ink']}; background:transparent; "
            "font-family:'Segoe UI','Malgun Gothic',sans-serif; }",
            "QLabel#hanlyPopupTitle { font-size:27px; font-weight:700; }",
            f"QLabel#hanlyPopupHanja {{ font-size:18px; color:{p['ink2']}; }}",
            "QLabel#hanlyPopupSense { font-size:14px; font-weight:600; }",
            f"QLabel#hanlyPopupSecondary {{ font-size:12px; color:{p['ink2']}; }}",
            f"QLabel#hanlyPopupMuted {{ font-size:11px; color:{p['ink3']}; }}",
            f"QLabel#hanlyPopupAccent {{ color:{p['accent_ink']}; }}",
            f"QLabel#hanlyPopupChip {{ background:{p['accent_wash']}; "
            f"color:{p['accent_ink']}; border-radius:10px; padding:3px 9px; "
            "font-size:11px; font-weight:600; }",
            f"QLabel#hanlyPopupQuietChip {{ background:{p['wash']}; color:{p['ink2']}; "
            "border-radius:10px; padding:3px 9px; font-size:11px; }",
            f"QWidget#hanlyPopupFooter {{ background:{p['foot']}; "
            f"border-top:1px solid {p['line']}; }}",
            # Footer controls read as one family: a filled pill for the primary
            # action, a quiet outline for the secondary, both with the hover and
            # pressed states a control needs to feel real under the pointer.
            f"QPushButton {{ color:{p['ink2']}; border:1px solid transparent; "
            f"background:{p['wash']}; border-radius:13px; padding:5px 13px; "
            "font-size:11px; font-weight:600; }",
            f"QPushButton:hover {{ color:{p['ink']}; background:{p['hover']}; }}",
            f"QPushButton:pressed {{ background:{p['press']}; }}",
            f"QPushButton#hanlyPopupSize {{ color:{p['accent_ink']}; "
            f"background:{p['accent_wash']}; border-color:transparent; }}",
            f"QPushButton#hanlyPopupSize:hover {{ background:{p['accent_hover']}; "
            f"color:{p['accent_ink']}; }}",
            # Pressing the primary action commits to the full accent, which is
            # the one place the saturated brand colour earns its contrast.
            f"QPushButton#hanlyPopupSize:pressed {{ background:{p['accent']}; "
            f"color:{p['bg']}; }}",
            f"QPushButton#hanlyPopupClose {{ background:transparent; "
            f"border-color:{p['line']}; }}",
            f"QPushButton#hanlyPopupClose:hover {{ background:{p['hover']}; "
            f"border-color:{p['border']}; }}",
            f"QScrollArea#hanlyPopupScroll {{ border:0; background:{p['bg']}; }}",
            # An overlay-style bar: no track, inset from the card edge, and a
            # handle that only firms up under the pointer.
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
        self._others_open = False
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
        header = QHBoxLayout()
        title = _label(content.entry.headword, name="hanlyPopupTitle")
        header.addWidget(title, 1, Qt.AlignmentFlag.AlignTop)
        if content.entry.hanja:
            hanja = _label(content.entry.hanja, name="hanlyPopupHanja")
            hanja.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header.addWidget(hanja, 0, Qt.AlignmentFlag.AlignTop)
        self._content_layout.addLayout(header)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        if content.entry.part_of_speech:
            chips.addWidget(_label(content.entry.part_of_speech, name="hanlyPopupChip"))
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
            chips.addWidget(
                _label(metadata, name="hanlyPopupQuietChip")
            )
        chips.addStretch(1)
        self._content_layout.addSpacing(12)
        self._content_layout.addLayout(chips)

        senses = content.entry.senses if self._expanded else content.entry.senses[:2]
        self._content_layout.addSpacing(12)
        for index, sense in enumerate(senses, start=1):
            row = QHBoxLayout()
            number = _label(str(index), name="hanlyPopupAccent")
            number.setFixedWidth(15)
            row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(self._sense_body(sense), 1)
            self._content_layout.addLayout(row)
            self._content_layout.addSpacing(10)

        if content.analysis or (content.surface and content.surface != content.lemma):
            self._content_layout.addWidget(self._divider())
            label = "WORD ANALYSIS" if self._expanded else "READ AS"
            self._content_layout.addWidget(_label(label, name="hanlyPopupMuted"))
            if content.surface and content.lemma and content.surface != content.lemma:
                relation = _label(
                    f"{content.surface}  →  {content.lemma}", name="hanlyPopupSecondary"
                )
                relation.setWordWrap(True)
                self._content_layout.addSpacing(5)
                self._content_layout.addWidget(relation)
            if content.analysis:
                pieces = _label(
                    "  +  ".join(piece.text for piece in content.analysis),
                    name="hanlyPopupSecondary",
                )
                pieces.setWordWrap(True)
                roles = _label(
                    " · ".join(piece.role for piece in content.analysis if piece.role),
                    name="hanlyPopupMuted",
                )
                roles.setWordWrap(True)
                self._content_layout.addSpacing(7)
                self._content_layout.addWidget(pieces)
                self._content_layout.addWidget(roles)

        if content.components:
            self._content_layout.addWidget(self._divider())
            self._content_layout.addWidget(
                _label("HOW THIS FORM IS BUILT", name="hanlyPopupMuted")
            )
            self._content_layout.addSpacing(5)
            for component in content.components:
                self._content_layout.addWidget(self._component_row(component))
                self._content_layout.addSpacing(4)

        if self._expanded and self._others_open:
            self._content_layout.addWidget(self._divider())
            for other in content.other_entries:
                gloss = _entry_gloss(other)
                text = " · ".join(filter(None, (other.headword, other.part_of_speech, gloss)))
                item = _label(text, name="hanlyPopupSecondary")
                item.setWordWrap(True)
                self._content_layout.addWidget(item)
                self._content_layout.addSpacing(6)

        if self._detail_level is TechnicalDetailLevel.FULL and content.technical_lines:
            self._content_layout.addWidget(self._divider())
            technical = _label("\n".join(content.technical_lines), name="hanlyPopupMuted")
            technical.setWordWrap(True)
            self._content_layout.addWidget(technical)

    def _build_non_success(self, content: PopupContent) -> None:
        if content.surface:
            word = _label(content.surface, name="hanlyPopupTitle")
            word.setWordWrap(True)
            self._content_layout.addWidget(word)
            self._content_layout.addSpacing(7)
        title = _label(content.title, name="hanlyPopupSense")
        body = _label(content.body, name="hanlyPopupSecondary")
        tip = _label(content.tip, name="hanlyPopupMuted")
        body.setWordWrap(True)
        tip.setWordWrap(True)
        self._content_layout.addWidget(title)
        self._content_layout.addSpacing(5)
        self._content_layout.addWidget(body)
        self._content_layout.addSpacing(4)
        self._content_layout.addWidget(tip)
        if content.technical_lines:
            self._content_layout.addSpacing(10)
            technical = _label(" · ".join(content.technical_lines), name="hanlyPopupMuted")
            technical.setWordWrap(True)
            self._content_layout.addWidget(technical)

    def _build_footer(self, content: PopupContent) -> None:
        if content.other_entries:
            others = QPushButton(f"Other entries ({len(content.other_entries)})")
            others.setObjectName("hanlyPopupOthers")
            others.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            others.clicked.connect(self._toggle_others)
            self._footer_layout.addWidget(others)
        if (
            self._detail_level is TechnicalDetailLevel.BASIC
            and content.technical_lines
        ):
            self._footer_layout.addWidget(
                _label(" · ".join(content.technical_lines), name="hanlyPopupMuted")
            )
        self._footer_layout.addStretch(1)
        if content.status is LookupStatus.SUCCESS:
            size = QPushButton("Collapse" if self._expanded else "Expand")
            size.setObjectName("hanlyPopupSize")
            size.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            size.clicked.connect(self._toggle_size)
            self._footer_layout.addWidget(size)

        # The window never accepts focus, so it can receive neither a key press
        # nor a click outside itself. A control inside the card is the one
        # dismissal the user can always reach.
        close = QPushButton("Close")
        close.setObjectName("hanlyPopupClose")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self._request_dismiss)
        self._footer_layout.addWidget(close)

    def _component_row(self, component: PopupComponent) -> QLabel:
        """One line of the breakdown: the characters, then what they contribute.

        A grammatical part explains the form rather than naming a word, so a
        missing gloss there is expected; a lexical part without one is a word
        the dictionary does not hold, and saying so is better than inventing it.
        """

        meaning = component.gloss
        if meaning is None:
            meaning = "grammatical" if component.grammatical else "no dictionary entry"
        text = f"{component.surface} · {meaning}"
        if component.selected:
            text = f"▸ {text}"
        name = "hanlyPopupMuted" if component.grammatical else "hanlyPopupSecondary"
        label = _label(text, name=name)
        label.setWordWrap(True)
        return label

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("hanlyPopupDivider")
        line.setStyleSheet("QFrame#hanlyPopupDivider { color: palette(midlight); }")
        return line

    def _toggle_size(self) -> None:
        self._expanded = not self._expanded
        if not self._expanded:
            self._others_open = False
        self._rebuild()
        self._resize_and_notify()

    def _toggle_others(self) -> None:
        if not self._expanded:
            self._expanded = True
        self._others_open = not self._others_open
        self._rebuild()
        self._resize_and_notify()

    @staticmethod
    def _sense_body(sense: DictionarySense) -> QVBoxLayout:
        """Stack a sense's short gloss above its fuller definition.

        A sense without a gloss shows the definition in the primary slot rather
        than an empty row, so nothing is invented and nothing is repeated.
        """

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)

        if sense.gloss:
            gloss = _label(sense.gloss, name="hanlyPopupSense")
            gloss.setWordWrap(True)
            body.addWidget(gloss)

            definition = _label(sense.definition, name="hanlyPopupSecondary")
        else:
            definition = _label(sense.definition, name="hanlyPopupSense")

        definition.setWordWrap(True)
        body.addWidget(definition)
        return body

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
