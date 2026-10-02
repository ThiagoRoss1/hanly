"""The surface a tour hovers: one full-screen window of lab-authored Korean.

Covering the whole available screen is a privacy property, not decoration: a
tour retains recognized text, so every pixel the pointer can rest on must be
the lab's own. Text is painted, not laid out as widgets, so nothing can be read
through the accessibility API and each hover exercises capture and OCR.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from .corpus import TourTarget

#: Korean faces tried in order; the first few installed are rotated per page.
_FACES = (
    "Apple SD Gothic Neo",
    "AppleMyungjo",
    "Nanum Gothic",
    "NanumMyeongjo",
    "Malgun Gothic",
    "Noto Sans KR",
    "Noto Sans CJK KR",
)
_THEMES = {
    "light": ("#ffffff", "#1d1f23"),
    "dark": ("#16181c", "#e8e8e8"),
    "sepia": ("#f4ecd8", "#3b2f1e"),
}
_MARGIN = 48
#: Wider than half the capture region, so a word at the edge is never read with what lies beyond.
_SIDE = 112
_HEADER = 40


@dataclass(frozen=True)
class Placed:
    """A target as painted: its word rectangle and the point the pointer rests on."""

    target: TourTarget
    word: QRect
    point: QPoint
    font_family: str
    font_px: int
    theme: str


@dataclass
class _Run:
    text: str
    x: int
    y: int
    font: QFont


@dataclass
class Page:
    theme: str
    runs: list[_Run]
    placed: list[Placed]
    #: Where the pointer waits between targets: guaranteed free of text.
    rest: QPoint


class TourPage(QWidget):
    """Shows one page at a time; ``show_page`` is safe to call from any thread."""

    _requested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__(
            None,
            # Not a Tool window: on macOS those hide whenever the shell is
            # deactivated, which the Control Center opening does.
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        screen = QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("no screen is available for a tour")
        self.setGeometry(screen.availableGeometry())
        self.pages: list[Page] = []
        self.status = ""
        self._current: Page | None = None
        self._painted = threading.Event()
        # show_page emits from the driver thread; Qt's automatic connection queues
        # that onto this widget's thread, where painting belongs.
        self._requested.connect(self._show)

    # -- layout ---------------------------------------------------------------

    def lay_out(
        self,
        story: list[TourTarget],
        words: list[TourTarget],
        story_sizes: list[int],
        word_sizes: list[int],
    ) -> None:
        """Story pages first, once per size, then the word grid."""

        faces = [face for face in _FACES if face in set(QFontDatabase.families())] or [
            QFont().family()
        ]
        themes = list(_THEMES)
        pages: list[Page] = []
        for index, size in enumerate(story_sizes):
            pages.extend(
                self._story_pages(story, size, faces[index % len(faces)], themes[index % 3])
            )
        word_pages = self._word_pages(words, word_sizes, faces, themes)
        self.pages = pages + word_pages

    def _story_pages(
        self, targets: list[TourTarget], size: int, face: str, theme: str
    ) -> list[Page]:
        font = QFont(face)
        font.setPixelSize(size)
        metrics = QFontMetrics(font)
        line_height = int(size * 2.6)
        by_line: dict[str, list[TourTarget]] = {}
        for target in targets:
            by_line.setdefault(target.line, []).append(target)
        area = self.rect().adjusted(_SIDE, _MARGIN + _HEADER, -_SIDE, -_MARGIN * 2)
        pages: list[Page] = []
        page = self._blank_page(theme)
        y = area.top()
        for line, members in by_line.items():
            if y + line_height > area.bottom():
                pages.append(page)
                page, y = self._blank_page(theme), area.top()
            baseline = y + metrics.ascent()
            page.runs.append(_Run(line, area.left(), baseline, font))
            for target in members:
                left = area.left() + metrics.horizontalAdvance(line[: target.start])
                width = metrics.horizontalAdvance(target.surface)
                rest_char = line[target.start + target.cursor]
                cursor_x = (
                    area.left()
                    + metrics.horizontalAdvance(line[: target.start + target.cursor])
                    + metrics.horizontalAdvance(rest_char) // 2
                )
                word = QRect(left, y, width, metrics.height())
                page.placed.append(
                    Placed(target, word, QPoint(cursor_x, word.center().y()), face, size, theme)
                )
            y += line_height
        if page.placed:
            pages.append(page)
        return pages

    def _word_pages(
        self, targets: list[TourTarget], sizes: list[int], faces: list[str], themes: list[str]
    ) -> list[Page]:
        area = self.rect().adjusted(_SIDE, _MARGIN + _HEADER, -_SIDE, -_MARGIN * 2)
        # Cells wide and tall enough that a popup over one word rarely covers the next.
        cell_w, cell_h = 300, 150
        columns = max(1, area.width() // cell_w)
        rows = max(1, area.height() // cell_h)
        per_page = columns * rows
        pages: list[Page] = []
        for page_index, offset in enumerate(range(0, len(targets), per_page)):
            theme = themes[page_index % len(themes)]
            page = self._blank_page(theme)
            chunk = targets[offset : offset + per_page]
            # Column-major with a stride, so consecutive targets sit far apart.
            order = sorted(range(len(chunk)), key=lambda i: (i % 2, i))
            for slot, target_index in enumerate(order):
                target = chunk[target_index]
                size = sizes[(offset + target_index) % len(sizes)]
                face = faces[(offset + target_index) % len(faces)]
                font = QFont(face)
                font.setPixelSize(size)
                metrics = QFontMetrics(font)
                column, row = slot % columns, slot // columns
                left = area.left() + column * cell_w + 12
                top = area.top() + row * cell_h + (cell_h - metrics.height()) // 2
                page.runs.append(_Run(target.surface, left, top + metrics.ascent(), font))
                width = metrics.horizontalAdvance(target.surface)
                char = target.surface[target.cursor]
                cursor_x = (
                    left
                    + metrics.horizontalAdvance(target.surface[: target.cursor])
                    + metrics.horizontalAdvance(char) // 2
                )
                word = QRect(left, top, width, metrics.height())
                page.placed.append(
                    Placed(target, word, QPoint(cursor_x, word.center().y()), face, size, theme)
                )
            pages.append(page)
        return pages

    def _blank_page(self, theme: str) -> Page:
        geometry = self.rect()
        return Page(theme, [], [], QPoint(geometry.width() // 2, geometry.height() - _MARGIN // 2))

    # -- showing --------------------------------------------------------------

    def show_page(self, index: int, timeout: float = 5.0) -> bool:
        """Show a page and wait until it has been painted."""

        self._painted.clear()
        self._requested.emit(index)
        return self._painted.wait(timeout)

    def to_global(self, point: QPoint) -> tuple[int, int]:
        origin = self.geometry().topLeft()
        return origin.x() + point.x(), origin.y() + point.y()

    def _show(self, index: int) -> None:
        self._current = self.pages[index]
        self.status = f"Hanly Lab tour - page {index + 1} of {len(self.pages)}"
        if not self.isVisible():
            self.show()
        self.raise_()
        self.repaint()

    def paintEvent(self, _event: Any) -> None:
        page = self._current
        painter = QPainter(self)
        background, ink = _THEMES[page.theme if page is not None else "light"]
        painter.fillRect(self.rect(), QColor(background))
        painter.setPen(QColor(ink))
        header = QFont()
        header.setPixelSize(13)
        painter.setFont(header)
        painter.drawText(_MARGIN, _MARGIN, f"{self.status}   (move the mouse yourself to stop)")
        if page is not None:
            for run in page.runs:
                painter.setFont(run.font)
                painter.drawText(run.x, run.y, run.text)
        painter.end()
        self._painted.set()


__all__ = ["Placed", "TourPage"]
