"""Raster-only, lab-authored pages for native desktop tours."""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from .corpus import TourTarget
from .raster_fonts import RasterFont, available_fonts, load_font
from .raster_ui import ImageWindow, Point, Rect, UIHost

_FACES = (
    "Apple SD Gothic Neo",
    "AppleMyungjo",
    "Nanum Gothic",
    "NanumMyeongjo",
    "Malgun Gothic",
    "Batang",
    "Gulim",
    "Dotum",
    "Gungsuh",
    "Noto Sans KR",
    "Noto Sans CJK KR",
)
_THEMES = {
    "light": ("#ffffff", "#1d1f23"),
    "dark": ("#16181c", "#e8e8e8"),
    "sepia": ("#f4ecd8", "#3b2f1e"),
}
_MARGIN = 48
_SIDE = 112
_HEADER = 40


@dataclass(frozen=True)
class Placed:
    """A target as rasterized and the logical point where the pointer rests."""

    target: TourTarget
    word: Rect
    point: Point
    font_family: str
    font_px: int
    theme: str


@dataclass
class _Run:
    text: str
    x: float
    baseline: float
    face: RasterFont
    size: int
    ink: str | None = None


@dataclass(frozen=True)
class RasterExtra:
    image: Image.Image
    origin: Point
    #: Corpus files are already in physical pixels and must remain 1:1.
    physical: bool = False


@dataclass
class Page:
    theme: str
    runs: list[_Run]
    placed: list[Placed]
    rest: Point
    extras: list[RasterExtra] = field(default_factory=list)


class TourPage:
    """Own the full-desktop fixture image and expose a small raster layout API."""

    def __init__(self, ui: UIHost) -> None:
        self.ui = ui
        self.geometry = ui.geometry
        self.display_scale = ui.geometry.display_scale
        self._width = int(round(ui.geometry.bounds.width))
        self._height = int(round(ui.geometry.bounds.height))
        if self._width <= 0 or self._height <= 0:
            raise RuntimeError("the Lab fixture has no usable desktop bounds")
        self._window: ImageWindow = ui.create_window(ui.geometry.bounds, ignore_mouse=True)
        self._fonts = available_fonts(_FACES)
        self.pages: list[Page] = []
        self.status = ""
        self._current: Page | None = None

    def rect(self) -> Rect:
        """The local logical area covered by the fixture."""

        return Rect(0, 0, self._width, self._height)

    def to_global(self, point: Point) -> tuple[int, int]:
        return self.geometry.to_pointer(point)

    def lay_out(
        self,
        story: list[TourTarget],
        words: list[TourTarget],
        story_sizes: list[int],
        word_sizes: list[int],
    ) -> None:
        """Story pages first, once per size, followed by the word grid."""

        themes = list(_THEMES)
        pages: list[Page] = []
        for index, size in enumerate(story_sizes):
            pages.extend(
                self._story_pages(
                    story, size, self._fonts[index % len(self._fonts)], themes[index % 3]
                )
            )
        pages.extend(self._word_pages(words, word_sizes, themes))
        self.pages = pages

    def _story_pages(
        self, targets: list[TourTarget], size: int, face: RasterFont, theme: str
    ) -> list[Page]:
        font = load_font(face, self._font_pixels(size))
        ascent, descent = font.getmetrics()
        line_height = size * 2.6
        by_line: dict[str, list[TourTarget]] = {}
        for target in targets:
            by_line.setdefault(target.line, []).append(target)
        area = self.rect().inset(_SIDE, _MARGIN + _HEADER, _SIDE, _MARGIN * 2)
        pages: list[Page] = []
        page = self._blank_page(theme)
        y = area.top
        for line, members in by_line.items():
            if y + line_height > area.bottom:
                if page.placed:
                    pages.append(page)
                page, y = self._blank_page(theme), area.top
            baseline = y + ascent / self.display_scale
            page.runs.append(_Run(line, area.left, baseline, face, size))
            for target in members:
                left = area.left + _advance(font, line[: target.start], self.display_scale)
                width = _advance(font, target.surface, self.display_scale)
                cursor_x = (
                    area.left
                    + _advance(font, line[: target.start + target.cursor], self.display_scale)
                    + _advance(
                        font,
                        line[target.start + target.cursor],
                        self.display_scale,
                    )
                    / 2
                )
                word = Rect(left, y, width, (ascent + descent) / self.display_scale)
                page.placed.append(
                    Placed(
                        target,
                        word,
                        Point(cursor_x, word.center.y),
                        face.family,
                        size,
                        theme,
                    )
                )
            y += line_height
        if page.placed:
            pages.append(page)
        return pages

    def _word_pages(
        self, targets: list[TourTarget], sizes: list[int], themes: list[str]
    ) -> list[Page]:
        if not targets:
            return []
        area = self.rect().inset(_SIDE, _MARGIN + _HEADER, _SIDE, _MARGIN * 2)
        cell_w, cell_h = 300, 150
        columns = max(1, int(area.width // cell_w))
        rows = max(1, int(area.height // cell_h))
        per_page = columns * rows
        pages: list[Page] = []
        for page_index, offset in enumerate(range(0, len(targets), per_page)):
            theme = themes[page_index % len(themes)]
            page = self._blank_page(theme)
            chunk = targets[offset : offset + per_page]
            order = sorted(range(len(chunk)), key=lambda i: (i % 2, i))
            for slot, target_index in enumerate(order):
                target = chunk[target_index]
                size = sizes[(offset + target_index) % len(sizes)]
                face = self._fonts[(offset + target_index) % len(self._fonts)]
                font = load_font(face, self._font_pixels(size))
                ascent, descent = font.getmetrics()
                height = (ascent + descent) / self.display_scale
                column, row = slot % columns, slot // columns
                left = area.left + column * cell_w + 12
                top = area.top + row * cell_h + (cell_h - height) / 2
                page.runs.append(
                    _Run(target.surface, left, top + ascent / self.display_scale, face, size)
                )
                width = _advance(font, target.surface, self.display_scale)
                cursor_x = (
                    left
                    + _advance(font, target.surface[: target.cursor], self.display_scale)
                    + _advance(font, target.surface[target.cursor], self.display_scale) / 2
                )
                word = Rect(left, top, width, height)
                page.placed.append(
                    Placed(target, word, Point(cursor_x, word.center.y), face.family, size, theme)
                )
            pages.append(page)
        return pages

    def _blank_page(self, theme: str) -> Page:
        return Page(
            theme,
            [],
            [],
            Point(self._width / 2, self._height - _MARGIN / 2),
        )

    def show_page(self, index: int, timeout: float = 5.0) -> bool:
        """Render and show a page before the driver begins a hover."""

        del timeout
        page = self.pages[index]
        self._current = page
        self.status = f"Hanly Lab tour - page {index + 1} of {len(self.pages)}"
        self._window.set_image(self._render(page))
        self._window.show()
        return True

    def set_shown(self, shown: bool) -> None:
        if shown and self._current is not None:
            self._window.show()
        elif not shown:
            self._window.hide()

    def swap(self, page_index: int, run_index: int, text: str) -> None:
        """Replace one run and synchronously refresh its raster."""

        page = self.pages[page_index]
        target = page.runs[run_index]
        page.runs[run_index] = _Run(
            text, target.x, target.baseline, target.face, target.size, target.ink
        )
        if self._current is page:
            self._window.set_image(self._render(page))

    def close(self) -> None:
        self._window.close()

    def _render(self, page: Page) -> Image.Image:
        scale = self.display_scale
        image = Image.new(
            "RGB",
            (max(1, round(self._width * scale)), max(1, round(self._height * scale))),
            _THEMES[page.theme][0],
        )
        draw = ImageDraw.Draw(image)
        _background, ink = _THEMES[page.theme]
        draw.text(
            (round(_MARGIN * scale), round(_MARGIN * scale)),
            self.status,
            font=load_font(self._fonts[0], round(13 * scale)),
            fill=ink,
            anchor="lt",
        )
        for extra in page.extras:
            if extra.physical:
                position = (round(extra.origin.x * scale), round(extra.origin.y * scale))
                image.paste(extra.image.convert("RGB"), position)
            else:
                layer = extra.image.convert("RGB")
                if layer.size != (round(layer.width * scale), round(layer.height * scale)):
                    layer = layer.resize(
                        (max(1, round(layer.width * scale)), max(1, round(layer.height * scale))),
                        Image.Resampling.LANCZOS,
                    )
                image.paste(layer, (round(extra.origin.x * scale), round(extra.origin.y * scale)))
        for run in page.runs:
            draw.text(
                (round(run.x * scale), round(run.baseline * scale)),
                run.text,
                font=load_font(run.face, round(run.size * scale)),
                fill=run.ink or ink,
                anchor="ls",
            )
        return image

    def _font_pixels(self, logical_size: int) -> int:
        return max(1, round(logical_size * self.display_scale))


def _advance(font: ImageFont.FreeTypeFont, text: str, scale: float) -> float:
    return float(font.getlength(text)) / scale


__all__ = ["Page", "Placed", "RasterExtra", "TourPage", "_Run"]
