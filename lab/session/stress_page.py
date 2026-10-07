"""Lay a stress campaign out on the tour page: cells, story lines, dense blocks.

Everything is painted. Raster cases are rendered by Qt into an image, degraded
(noise, blur, JPEG, a gradient), and painted as a picture, so OCR meets the same
pixels it would meet in a screenshot of a photo or a banner. Icons and
illustrations are shapes with no text at all.
"""

from __future__ import annotations

import io
import math
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QBuffer, QIODevice, QPoint, QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPolygonF,
)

from .page import Page, Placed, TourPage, _Run
from .stress import FACES, StressItem

_THEMES = {
    "light": ("#ffffff", "#1d1f23"),
    "dark": ("#16181c", "#e8e8e8"),
    "sepia": ("#f4ecd8", "#3b2f1e"),
    "gray": ("#d4d4d4", "#5f5f5f"),
}
_MARGIN = 48
_SIDE = 112
_HEADER = 40
_CELL = (300, 150)
#: Families laid out one per cell, in plan order, row by row.
_STORY = "story"
_DENSE = "dense"
_CORPUS = "corpus"
#: Vertical space between corpus images: more than half the capture region,
#: so a capture around one image never reaches the next.
_CORPUS_GAP = 110


@dataclass(frozen=True)
class StressPlaced(Placed):
    """A placed target that remembers the plan item it came from."""

    item: StressItem | None = None
    #: Points the pointer crosses quickly before it settles (``rapid``).
    approach: tuple[QPoint, ...] = ()
    #: The run whose text a ``changing`` hover replaces.
    run_index: int | None = None


class StressPage(TourPage):
    """The tour page, laid out from a campaign plan instead of a word list."""

    _swap = pyqtSignal(int, int, str)
    _visibility = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._settled = threading.Event()
        #: Plan items the page could not show, with why.
        self.omitted: list[dict[str, str]] = []
        self._swap.connect(self._apply_swap)
        self._visibility.connect(self._apply_visibility)

    def lay_out_plan(self, items: list[StressItem], seed: int) -> None:
        """Pages in plan order: story lines, dense blocks, then cells."""

        installed = set(QFontDatabase.families())
        faces = [face for face in FACES if face in installed] or [QFont().family()]
        generator = random.Random(seed)
        pages: list[Page] = []
        story = [item for item in items if item.family == _STORY]
        dense = [item for item in items if item.family == _DENSE]
        cells = [
            item
            for item in items
            if item.family
            not in {_STORY, _DENSE, _CORPUS, "uia_korean", "uia_latin", "covered"}
        ]
        covered = [item for item in items if item.family == "covered"]
        for size in sorted({item.size for item in story}):
            group = [item for item in story if item.size == size]
            pages += self._story_lines(group, faces)
        pages += self._dense_block(dense, faces)
        pages += self._corpus_rows([item for item in items if item.family == _CORPUS])
        pages += self._cells(cells, faces, generator)
        self.covered_page = len(pages)
        pages += self._cells(covered, faces, generator)
        self.pages = pages

    # -- layouts --------------------------------------------------------------------

    def _area(self) -> QRect:
        return self.rect().adjusted(_SIDE, _MARGIN + _HEADER, -_SIDE, -_MARGIN * 2)

    def _story_lines(self, items: list[StressItem], faces: list[str]) -> list[Page]:
        first = items[0]
        font = _font(faces, first.face_index, first.size)
        metrics = QFontMetrics(font)
        line_height = int(first.size * 2.6)
        area = self._area()
        by_line: dict[str, list[StressItem]] = {}
        for item in items:
            by_line.setdefault(item.target.line, []).append(item)
        pages: list[Page] = []
        page, y = self._blank_page(first.theme), area.top()
        for line, members in by_line.items():
            if y + line_height > area.bottom():
                pages.append(page)
                page, y = self._blank_page(first.theme), area.top()
            page.runs.append(_Run(line, area.left(), y + metrics.ascent(), font))
            for item in members:
                page.placed.append(
                    self._placed_in_line(item, line, area.left(), y, font, face=font.family())
                )
            y += line_height
        if page.placed:
            pages.append(page)
        return pages

    def _dense_block(self, items: list[StressItem], faces: list[str]) -> list[Page]:
        if not items:
            return []
        area = self._area()
        page = self._blank_page("light")
        y = area.top()
        lines: dict[str, list[StressItem]] = {}
        for item in items:
            lines.setdefault(item.target.line, []).append(item)
        for line, members in lines.items():
            font = _font(faces, members[0].face_index, members[0].size)
            metrics = QFontMetrics(font)
            page.runs.append(_Run(line, area.left(), y + metrics.ascent(), font))
            for item in members:
                page.placed.append(
                    self._placed_in_line(item, line, area.left(), y, font, face=font.family())
                )
            # Tight leading: the next line starts a quarter line below this one.
            y += int(metrics.height() * 1.25)
        return [page]

    def _cells(
        self, items: list[StressItem], faces: list[str], generator: random.Random
    ) -> list[Page]:
        area = self._area()
        columns = max(1, area.width() // _CELL[0])
        rows = max(1, area.height() // _CELL[1])
        per_page = columns * rows
        pages: list[Page] = []
        for offset in range(0, len(items), per_page):
            chunk = items[offset : offset + per_page]
            # A page takes the theme of its first cell; each cell paints its own.
            page = self._blank_page("light")
            centres: list[QPoint] = []
            for slot, item in enumerate(chunk):
                column, row = slot % columns, slot // columns
                cell = QRect(
                    area.left() + column * _CELL[0],
                    area.top() + row * _CELL[1],
                    _CELL[0],
                    _CELL[1],
                )
                placed = self._cell(page, item, cell, faces, generator, centres)
                centres.append(placed.point)
                page.placed.append(placed)
            pages.append(page)
        return pages

    def _corpus_rows(self, items: list[StressItem]) -> list[Page]:
        """One controlled image per row, painted pixel for pixel on the physical screen.

        The image is not rescaled: its device pixel ratio is the screen's, so
        each image pixel is one screen pixel and the annotated pointer lands
        where the corpus says. An image wider or taller than the page is
        skipped and listed in ``omitted``.
        """

        if not items:
            return []
        ratio = self.devicePixelRatioF()
        area = self._area()
        pages: list[Page] = []
        page, y = self._blank_page("light"), area.top()
        for item in items:
            image = QImage(str(item.image))
            image.setDevicePixelRatio(ratio)
            width, height = image.width() / ratio, image.height() / ratio
            if image.isNull() or width > area.width() or height > area.height():
                self.omitted.append({"target": item.target.id, "reason": "image does not fit"})
                continue
            if y + height > area.bottom():
                pages.append(page)
                page, y = self._blank_page("light"), area.top()
            origin = QPoint(area.left(), y)
            page.extras.append(_image(image, origin))
            x, py = item.image_target or (0.0, 0.0)
            point = QPoint(round(origin.x() + x / ratio), round(origin.y() + py / ratio))
            word = QRect(origin.x(), origin.y(), math.ceil(width), math.ceil(height))
            page.placed.append(
                StressPlaced(item.target, word, point, "corpus", 0, "corpus", item=item)
            )
            y += math.ceil(height) + _CORPUS_GAP
        if page.placed:
            pages.append(page)
        return pages

    def _cell(
        self,
        page: Page,
        item: StressItem,
        cell: QRect,
        faces: list[str],
        generator: random.Random,
        centres: list[QPoint],
    ) -> StressPlaced:
        background, ink = _THEMES[item.theme]
        page.extras.append(_fill(cell.adjusted(4, 4, -4, -4), background))
        font = _font(faces, item.face_index, item.size)
        metrics = QFontMetrics(font)
        text = item.target.surface
        left = cell.left() + 16
        top = cell.top() + (cell.height() - metrics.height()) // 2
        approach = tuple(centres[-3:]) if item.behavior == "rapid" else ()
        face, size, theme = font.family(), item.size, item.theme

        if item.family in {"blank", "after_popup"}:
            point = cell.center()
            word = QRect(point.x() - 1, point.y() - 1, 2, 2)
            return StressPlaced(item.target, word, point, face, size, theme, item=item)
        if item.family == "icon" or (item.graphic == "picture" and not text):
            size = item.size * 2
            box = QRect(cell.center().x() - size // 2, cell.center().y() - size // 2, size, size)
            if item.graphic == "picture":
                page.extras.append(_picture(box.adjusted(-40, -10, 40, 10), item, generator))
            else:
                page.extras.append(_icon(box, item.graphic or "circle", ink))
            return StressPlaced(item.target, box, box.center(), face, size, theme, item=item)
        if item.raster is not None:
            image = _raster_word(text, font, item.raster, generator)
            origin = QPoint(left, cell.center().y() - image.height() // 2)
            page.extras.append(_image(image, origin))
            ascent_offset = (image.height() - metrics.height()) // 2
            x = origin.x() + 10 + _advance(metrics, text, item.target.cursor)
            word = QRect(origin, image.size())
            point = QPoint(x, origin.y() + ascent_offset + metrics.height() // 2)
            return StressPlaced(item.target, word, point, face, size, theme, item=item)

        line = item.target.line or text
        start = item.target.start
        run_index = len(page.runs)
        page.runs.append(_Run(line, left, top + metrics.ascent(), font, ink))
        line_left = left + metrics.horizontalAdvance(line[:start])
        x = line_left + _advance(metrics, text, item.target.cursor)
        word = QRect(line_left, top, metrics.horizontalAdvance(text), metrics.height())
        return StressPlaced(
            item.target,
            word,
            QPoint(x, word.center().y()),
            face,
            size,
            theme,
            item=item,
            approach=approach,
            run_index=run_index if item.behavior == "changing" else None,
        )

    def _placed_in_line(
        self, item: StressItem, line: str, left: int, top: int, font: QFont, *, face: str
    ) -> StressPlaced:
        metrics = QFontMetrics(font)
        target = item.target
        start_x = left + metrics.horizontalAdvance(line[: target.start])
        width = metrics.horizontalAdvance(target.surface)
        character = line[target.start + target.cursor]
        x = (
            left
            + metrics.horizontalAdvance(line[: target.start + target.cursor])
            + metrics.horizontalAdvance(character) // 2
        )
        word = QRect(start_x, top, width, metrics.height())
        return StressPlaced(
            target,
            word,
            QPoint(x, word.center().y()),
            face,
            item.size,
            item.theme,
            item=item,
        )

    # -- visibility and changing content -------------------------------------------

    def set_shown(self, shown: bool) -> None:
        """Hide or show the page from any thread, and wait until it has happened."""

        self._settled.clear()
        self._visibility.emit(shown)
        self._settled.wait(5)

    def _apply_visibility(self, shown: bool) -> None:
        if shown:
            self.show()
            self.raise_()
        else:
            self.hide()
        self._settled.set()

    def swap(self, page: int, run: int, text: str) -> None:
        """Replace one run's text, from any thread, and repaint."""

        self._swap.emit(page, run, text)

    def _apply_swap(self, page: int, run: int, text: str) -> None:
        target = self.pages[page].runs[run]
        self.pages[page].runs[run] = _Run(text, target.x, target.y, target.font, target.ink)
        self.repaint()


# -- painting helpers ------------------------------------------------------------------


def _font(faces: list[str], index: int, size: int) -> QFont:
    font = QFont(faces[index % len(faces)])
    font.setPixelSize(size)
    return font


def _advance(metrics: QFontMetrics, text: str, cursor: int) -> int:
    if not text:
        return 0
    cursor = max(0, min(cursor, len(text) - 1))
    return metrics.horizontalAdvance(text[:cursor]) + metrics.horizontalAdvance(text[cursor]) // 2


def _fill(rect: QRect, color: str) -> Callable[[QPainter], None]:
    def paint(painter: QPainter) -> None:
        painter.fillRect(rect, QColor(color))

    return paint


def _image(image: QImage, origin: QPoint) -> Callable[[QPainter], None]:
    def paint(painter: QPainter) -> None:
        painter.drawImage(origin, image)

    return paint


def _icon(box: QRect, kind: str, ink: str) -> Callable[[QPainter], None]:
    """A text-free glyph of the kind a toolbar or a navigation bar carries."""

    def paint(painter: QPainter) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(ink)
        painter.setPen(color)
        painter.setBrush(color)
        c = QPointF(box.center())
        r = box.width() / 2
        if kind == "circle":
            painter.drawEllipse(c, r * 0.8, r * 0.8)
        elif kind in {"star", "heart", "bell", "blob"}:
            path = QPainterPath()
            points = 10 if kind == "star" else 24
            for step in range(points):
                angle = math.tau * step / points - math.pi / 2
                radius = r * (0.9 if step % 2 == 0 else 0.45) if kind == "star" else r * (
                    0.7 + 0.2 * math.sin(3 * angle)
                )
                point = QPointF(c.x() + radius * math.cos(angle), c.y() + radius * math.sin(angle))
                path.moveTo(point) if step == 0 else path.lineTo(point)
            path.closeSubpath()
            painter.drawPath(path)
        elif kind in {"arrow", "triangle"}:
            corners = [
                QPointF(c.x() - r * 0.7, c.y() - r * 0.6),
                QPointF(c.x() + r * 0.8, c.y()),
                QPointF(c.x() - r * 0.7, c.y() + r * 0.6),
            ]
            painter.drawPolygon(QPolygonF(corners))
        elif kind in {"square", "home"}:
            painter.drawRect(QRect(box.adjusted(box.width() // 5, box.height() // 4,
                                                -box.width() // 5, -box.height() // 6)))
        elif kind in {"bars", "search", "gear"}:
            for index in range(3):
                painter.drawRect(
                    QRect(box.left() + 6, box.top() + 8 + index * box.height() // 3,
                          box.width() - 12, max(3, box.height() // 8))
                )
        else:  # check, cross, dots
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = painter.pen()
            pen.setWidth(max(3, box.width() // 10))
            painter.setPen(pen)
            painter.drawLine(box.topLeft() + QPoint(6, 6), box.bottomRight() - QPoint(6, 6))
            if kind != "check":
                painter.drawLine(box.topRight() + QPoint(-6, 6), box.bottomLeft() + QPoint(6, -6))
        painter.restore()

    return paint


def _picture(box: QRect, item: StressItem, generator: random.Random) -> Callable[[QPainter], None]:
    """An illustration with no text: gradients and soft shapes, like a banner photo."""

    blobs = [
        (generator.random(), generator.random(), generator.uniform(0.15, 0.4),
         QColor.fromHsv(generator.randrange(360), 120, 200))
        for _ in range(6)
    ]
    # Drawn now, not at paint time, so every repaint is the same picture.
    start = QColor.fromHsv(generator.randrange(360), 60, 230)
    end = QColor.fromHsv(generator.randrange(360), 90, 120)

    def paint(painter: QPainter) -> None:
        painter.save()
        gradient = QLinearGradient(QPointF(box.topLeft()), QPointF(box.bottomRight()))
        gradient.setColorAt(0, start)
        gradient.setColorAt(1, end)
        painter.fillRect(box, gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        for fx, fy, fr, color in blobs:
            painter.setBrush(color)
            painter.drawEllipse(
                QPointF(box.left() + fx * box.width(), box.top() + fy * box.height()),
                fr * box.height(),
                fr * box.height(),
            )
        painter.restore()

    return paint


def _raster_word(text: str, font: QFont, kind: str, generator: random.Random) -> QImage:
    """The word as a degraded picture: what OCR meets in a banner or a photo."""

    metrics = QFontMetrics(font)
    image = QImage(
        metrics.horizontalAdvance(text) + 20, metrics.height() + 16, QImage.Format.Format_RGB32
    )
    image.fill(QColor("#f2f2f2"))
    painter = QPainter(image)
    if kind == "gradient":
        gradient = QLinearGradient(0, 0, image.width(), image.height())
        gradient.setColorAt(0, QColor("#fde8c8"))
        gradient.setColorAt(1, QColor("#8fb8de"))
        painter.fillRect(image.rect(), gradient)
    painter.setFont(font)
    painter.setPen(QColor("#202020"))
    painter.drawText(10, 8 + metrics.ascent(), text)
    painter.end()
    return _degrade(image, kind, generator)


def _degrade(image: QImage, kind: str, generator: random.Random) -> QImage:
    from PIL import Image, ImageFilter

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    picture = Image.open(io.BytesIO(buffer.data().data())).convert("RGB")
    if kind == "blur":
        picture = picture.filter(ImageFilter.GaussianBlur(1.1))
    elif kind in {"noise", "gradient"}:
        import numpy

        rng = numpy.random.default_rng(generator.randrange(1 << 30))
        pixels = numpy.asarray(picture, dtype=numpy.float32)
        spread = 40.0 if kind == "noise" else 20.0
        noisy = pixels + rng.normal(0.0, spread, pixels.shape[:2])[..., None]
        picture = Image.fromarray(numpy.clip(noisy, 0, 255).astype(numpy.uint8))
    out = io.BytesIO()
    if kind == "jpeg":
        picture.save(out, "JPEG", quality=22)
    else:
        picture.save(out, "PNG")
    degraded = QImage()
    degraded.loadFromData(out.getvalue())
    return degraded


__all__ = ["StressPage", "StressPlaced"]
