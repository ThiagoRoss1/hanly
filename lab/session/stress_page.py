"""Pillow layouts for controlled raster, text, and image stress cases."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .page import Page, Placed, RasterExtra, TourPage, _Run
from .raster_fonts import RasterFont, available_fonts, load_font
from .raster_ui import Point, Rect, UIHost
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
_STORY = "story"
_DENSE = "dense"
_CORPUS = "corpus"
_CORPUS_GAP = 110


@dataclass(frozen=True)
class StressPlaced(Placed):
    """A target tied to its stress-plan item and optional approach behavior."""

    item: StressItem | None = None
    approach: tuple[Point, ...] = ()
    run_index: int | None = None


class StressPage(TourPage):
    """A tour surface laid out from a seeded stress campaign."""

    def __init__(self, ui: UIHost) -> None:
        super().__init__(ui)
        self.omitted: list[dict[str, str]] = []
        self.covered_page = -1

    def lay_out_plan(self, items: list[StressItem], seed: int) -> None:
        """Lay out story, dense text, corpus images, then isolated test cells."""

        self._fonts = available_fonts(FACES)
        generator = random.Random(seed)
        pages: list[Page] = []
        story = [item for item in items if item.family == _STORY]
        dense = [item for item in items if item.family == _DENSE]
        cells = [
            item
            for item in items
            if item.family not in {_STORY, _DENSE, _CORPUS, "uia_korean", "uia_latin", "covered"}
        ]
        covered = [item for item in items if item.family == "covered"]
        for size in sorted({item.size for item in story}):
            pages.extend(self._story_lines([item for item in story if item.size == size]))
        pages.extend(self._dense_block(dense))
        pages.extend(self._corpus_rows([item for item in items if item.family == _CORPUS]))
        pages.extend(self._cells(cells, generator))
        self.covered_page = len(pages)
        pages.extend(self._cells(covered, generator))
        self.pages = pages

    def _area(self) -> Rect:
        return self.rect().inset(_SIDE, _MARGIN + _HEADER, _SIDE, _MARGIN * 2)

    def _story_lines(self, items: list[StressItem]) -> list[Page]:
        if not items:
            return []
        first = items[0]
        face = self._face(first.face_index)
        font = load_font(face, self._font_pixels(first.size))
        ascent, descent = font.getmetrics()
        line_height = int(first.size * 2.6)
        area = self._area()
        by_line: dict[str, list[StressItem]] = {}
        for item in items:
            by_line.setdefault(item.target.line, []).append(item)
        pages: list[Page] = []
        page, y = self._blank_page(first.theme), area.top
        for line, members in by_line.items():
            if y + line_height > area.bottom:
                if page.placed:
                    pages.append(page)
                page, y = self._blank_page(first.theme), area.top
            page.runs.append(
                _Run(line, area.left, y + ascent / self.display_scale, face, first.size)
            )
            for item in members:
                page.placed.append(self._placed_in_line(item, line, area.left, y, face))
            y += line_height
        if page.placed:
            pages.append(page)
        return pages

    def _dense_block(self, items: list[StressItem]) -> list[Page]:
        if not items:
            return []
        area = self._area()
        page = self._blank_page("light")
        y = area.top
        lines: dict[str, list[StressItem]] = {}
        for item in items:
            lines.setdefault(item.target.line, []).append(item)
        for line, members in lines.items():
            first = members[0]
            face = self._face(first.face_index)
            font = load_font(face, self._font_pixels(first.size))
            ascent, descent = font.getmetrics()
            page.runs.append(
                _Run(line, area.left, y + ascent / self.display_scale, face, first.size)
            )
            for item in members:
                page.placed.append(self._placed_in_line(item, line, area.left, y, face))
            y += int((ascent + descent) / self.display_scale * 1.25)
        return [page]

    def _cells(self, items: list[StressItem], generator: random.Random) -> list[Page]:
        if not items:
            return []
        area = self._area()
        columns = max(1, int(area.width // _CELL[0]))
        rows = max(1, int(area.height // _CELL[1]))
        per_page = columns * rows
        pages: list[Page] = []
        for offset in range(0, len(items), per_page):
            page = self._blank_page("light")
            centres: list[Point] = []
            for slot, item in enumerate(items[offset : offset + per_page]):
                column, row = slot % columns, slot // columns
                cell = Rect(
                    area.left + column * _CELL[0],
                    area.top + row * _CELL[1],
                    _CELL[0],
                    _CELL[1],
                )
                placed = self._cell(page, item, cell, generator, centres)
                centres.append(placed.point)
                page.placed.append(placed)
            pages.append(page)
        return pages

    def _corpus_rows(self, items: list[StressItem]) -> list[Page]:
        """Place controlled source images at their annotated physical pixels."""

        if not items:
            return []
        area = self._area()
        pages: list[Page] = []
        page, y = self._blank_page("light"), area.top
        scale = self.display_scale
        for item in items:
            try:
                with Image.open(str(item.image)) as opened:
                    image = opened.convert("RGB")
            except (OSError, ValueError):
                self.omitted.append(
                    {"target": item.target.id, "reason": "image could not be loaded"}
                )
                continue
            width, height = image.width / scale, image.height / scale
            if width > area.width or height > area.height:
                self.omitted.append({"target": item.target.id, "reason": "image does not fit"})
                continue
            if y + height > area.bottom:
                if page.placed:
                    pages.append(page)
                page, y = self._blank_page("light"), area.top
            origin = Point(area.left, y)
            page.extras.append(RasterExtra(image, origin, physical=True))
            x, py = item.image_target or (0.0, 0.0)
            point = Point(origin.x + x / scale, origin.y + py / scale)
            word = Rect(origin.x, origin.y, width, height)
            page.placed.append(
                StressPlaced(item.target, word, point, "corpus", 0, "corpus", item=item)
            )
            y += height + _CORPUS_GAP
        if page.placed:
            pages.append(page)
        return pages

    def _cell(
        self,
        page: Page,
        item: StressItem,
        cell: Rect,
        generator: random.Random,
        centres: list[Point],
    ) -> StressPlaced:
        background, ink = _THEMES[item.theme]
        page.extras.append(
            RasterExtra(
                _solid(cell.width - 8, cell.height - 8, background), Point(cell.x + 4, cell.y + 4)
            )
        )
        face = self._face(item.face_index)
        font = load_font(face, self._font_pixels(item.size))
        ascent, descent = font.getmetrics()
        text = item.target.surface
        left = cell.left + 16
        height = (ascent + descent) / self.display_scale
        top = cell.top + (cell.height - height) / 2
        approach = tuple(centres[-3:]) if item.behavior == "rapid" else ()

        if item.family in {"blank", "after_popup"}:
            point = cell.center
            return StressPlaced(
                item.target,
                Rect(point.x - 1, point.y - 1, 2, 2),
                point,
                face.family,
                item.size,
                item.theme,
                item=item,
                approach=approach,
            )
        if item.family == "icon" or (item.graphic == "picture" and not text):
            size = item.size * 2
            box = Rect(cell.center.x - size / 2, cell.center.y - size / 2, size, size)
            graphic = (
                _picture(box, generator)
                if item.graphic == "picture"
                else _icon(box, item.graphic or "circle", ink)
            )
            page.extras.append(RasterExtra(graphic, Point(box.x, box.y)))
            return StressPlaced(
                item.target,
                box,
                box.center,
                face.family,
                size,
                item.theme,
                item=item,
                approach=approach,
            )
        if item.raster is not None:
            image = _raster_word(text, face, item.size, self.display_scale, item.raster, generator)
            origin = Point(left, cell.center.y - image.height / self.display_scale / 2)
            page.extras.append(RasterExtra(image, origin))
            x = origin.x + 10 + _advance(font, text[: item.target.cursor], self.display_scale)
            x += _advance(font, text[item.target.cursor], self.display_scale) / 2
            word = Rect(origin.x, origin.y, image.width, image.height)
            point = Point(x, origin.y + word.height / 2)
            return StressPlaced(
                item.target,
                word,
                point,
                face.family,
                item.size,
                item.theme,
                item=item,
                approach=approach,
            )

        line = item.target.line or text
        start = item.target.start
        run_index = len(page.runs)
        page.runs.append(_Run(line, left, top + ascent / self.display_scale, face, item.size, ink))
        line_left = left + _advance(font, line[:start], self.display_scale)
        x = line_left + _advance(font, text[: item.target.cursor], self.display_scale)
        x += _advance(font, text[item.target.cursor], self.display_scale) / 2
        word = Rect(
            line_left,
            top,
            _advance(font, text, self.display_scale),
            height,
        )
        return StressPlaced(
            item.target,
            word,
            Point(x, word.center.y),
            face.family,
            item.size,
            item.theme,
            item=item,
            approach=approach,
            run_index=run_index if item.behavior == "changing" else None,
        )

    def _placed_in_line(
        self, item: StressItem, line: str, left: float, top: float, face: RasterFont
    ) -> StressPlaced:
        target = item.target
        font = load_font(face, self._font_pixels(item.size))
        ascent, descent = font.getmetrics()
        start_x = left + _advance(font, line[: target.start], self.display_scale)
        width = _advance(font, target.surface, self.display_scale)
        cursor_x = left + _advance(font, line[: target.start + target.cursor], self.display_scale)
        cursor_x += _advance(font, target.surface[target.cursor], self.display_scale) / 2
        word = Rect(
            start_x,
            top,
            width,
            (ascent + descent) / self.display_scale,
        )
        return StressPlaced(
            target,
            word,
            Point(cursor_x, word.center.y),
            face.family,
            item.size,
            item.theme,
            item=item,
        )

    def _face(self, index: int) -> RasterFont:
        return self._fonts[index % len(self._fonts)]


def _advance(font: ImageFont.FreeTypeFont, text: str, scale: float) -> float:
    return float(font.getlength(text)) / scale


def _solid(width: float, height: float, color: str) -> Image.Image:
    return Image.new("RGB", (max(1, round(width)), max(1, round(height))), color)


def _icon(box: Rect, kind: str, ink: str) -> Image.Image:
    size = (max(1, round(box.width)), max(1, round(box.height)))
    image = Image.new("RGB", size, _THEMES["light"][0])
    draw = ImageDraw.Draw(image)
    cx, cy = box.width / 2, box.height / 2
    radius = min(box.width, box.height) / 2
    bounds = (cx - radius * 0.8, cy - radius * 0.8, cx + radius * 0.8, cy + radius * 0.8)
    if kind == "circle":
        draw.ellipse(bounds, fill=ink)
    elif kind == "star":
        draw.polygon(_star_points(cx, cy, radius, 10), fill=ink)
    elif kind in {"heart", "bell", "blob"}:
        points = [
            (
                cx + radius * (0.7 + 0.2 * math.sin(3 * angle)) * math.cos(angle),
                cy + radius * (0.7 + 0.2 * math.sin(3 * angle)) * math.sin(angle),
            )
            for angle in (math.tau * step / 24 - math.pi / 2 for step in range(24))
        ]
        draw.polygon(points, fill=ink)
    elif kind in {"arrow", "triangle"}:
        draw.polygon(
            [
                (cx - radius * 0.7, cy - radius * 0.6),
                (cx + radius * 0.8, cy),
                (cx - radius * 0.7, cy + radius * 0.6),
            ],
            fill=ink,
        )
    elif kind in {"square", "home"}:
        draw.rectangle(
            (radius * 0.2, radius * 0.25, box.width - radius * 0.2, box.height - radius * 0.2),
            fill=ink,
        )
    elif kind in {"bars", "search", "gear"}:
        for index in range(3):
            top = 8 + index * box.height / 3
            draw.rectangle((6, top, box.width - 6, top + max(3, box.height / 8)), fill=ink)
    else:
        width = max(3, round(box.width / 10))
        draw.line((6, 6, box.width - 6, box.height - 6), fill=ink, width=width)
        if kind != "check":
            draw.line((box.width - 6, 6, 6, box.height - 6), fill=ink, width=width)
    return image


def _star_points(cx: float, cy: float, radius: float, count: int) -> list[tuple[float, float]]:
    return [
        (
            cx
            + radius
            * (0.9 if step % 2 == 0 else 0.45)
            * math.cos(math.tau * step / count - math.pi / 2),
            cy
            + radius
            * (0.9 if step % 2 == 0 else 0.45)
            * math.sin(math.tau * step / count - math.pi / 2),
        )
        for step in range(count)
    ]


def _picture(box: Rect, generator: random.Random) -> Image.Image:
    width, height = max(1, round(box.width)), max(1, round(box.height))
    start = generator.randrange(30, 220)
    end = generator.randrange(30, 220)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / max(1, height - 1)
        color = tuple(round(start * (1 - blend) + end * blend) for _ in range(3))
        draw.line((0, y, width, y), fill=color)
    colors = ["#ef7386", "#f0c84b", "#57c6b0", "#718de5", "#bd74dd", "#f28d42"]
    for _ in range(6):
        radius = generator.uniform(0.15, 0.4) * height
        cx, cy = generator.random() * width, generator.random() * height
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius), fill=generator.choice(colors)
        )
    return image


def _raster_word(
    text: str,
    face: RasterFont,
    size: int,
    scale: float,
    kind: str,
    generator: random.Random,
) -> Image.Image:
    """Render and degrade a word as a controlled raster banner."""

    font = load_font(face, max(1, round(size * scale)))
    ascent, descent = font.getmetrics()
    width = math.ceil(float(font.getlength(text))) + round(20 * scale)
    height = ascent + descent + round(16 * scale)
    image = Image.new("RGB", (max(1, width), max(1, height)), "#f2f2f2")
    draw = ImageDraw.Draw(image)
    if kind == "gradient":
        start, end = (253, 232, 200), (143, 184, 222)
        for y in range(image.height):
            ratio = y / max(1, image.height - 1)
            draw.line(
                (0, y, image.width, y),
                fill=tuple(round(a * (1 - ratio) + b * ratio) for a, b in zip(start, end)),
            )
    draw.text((round(10 * scale), round(8 * scale)), text, font=font, fill="#202020", anchor="lt")
    if kind == "blur":
        image = image.filter(ImageFilter.GaussianBlur(max(0.1, 1.1 * scale)))
    elif kind in {"noise", "gradient"}:
        import numpy

        random_pixels = numpy.random.default_rng(generator.randrange(1 << 30))
        pixels = numpy.asarray(image, dtype=numpy.float32)
        spread = (40.0 if kind == "noise" else 20.0) * scale
        noisy = pixels + random_pixels.normal(0.0, spread, pixels.shape[:2])[..., None]
        image = Image.fromarray(numpy.clip(noisy, 0, 255).astype(numpy.uint8))
    if kind == "jpeg":
        import io

        output = io.BytesIO()
        image.save(output, "JPEG", quality=22)
        output.seek(0)
        image = Image.open(output).convert("RGB")
    return image


__all__ = ["StressPage", "StressPlaced"]
