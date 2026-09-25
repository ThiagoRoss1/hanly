"""The mini book: an original Korean page read end to end, target by target.

``benchmarks/fixtures/minibook/minibook.json`` holds a short synthetic story and
the words in it a reader might hover, each with the dictionary form it should
answer to. This module renders that page in the forms Hanly meets text in --
accessible text (HTML for a browser, RTF for a native text view) and pixels
(an HTML canvas, or an in-memory raster) -- and judges each acquisition path
separately, naming the first stage where a target went wrong.

It is developer tooling. Nothing in ``packages/`` imports it, and the page is
synthetic, so its reports carry no private screen or text content.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "minibook" / "minibook.json"

#: Where each rendered form is laid out, in pixels. One layout for every form,
#: so a target sits in the same place in the raster and on the canvas page.
LEFT = 40
TOP = 40
FONT_SIZE = 22
LINE_HEIGHT = 44
PAGE_WIDTH = 1180

#: The capture a hover takes around the pointer, as the desktop configures it.
ROI_SIZE = (200, 100)
ROI_GRID = 32


class MinibookError(ValueError):
    """Raised when the manifest does not describe its own page."""


@dataclass(frozen=True)
class Target:
    id: str
    line: int
    start: int
    surface: str
    cursor: int
    lemma: str | None
    headword: str | None
    topik: int | None
    kinds: tuple[str, ...]
    style: str
    refuse: bool

    @property
    def end(self) -> int:
        return self.start + len(self.surface)

    @property
    def character(self) -> int:
        """The character the pointer rests on, as an offset into its line."""

        return self.start + self.cursor


@dataclass(frozen=True)
class Minibook:
    title: str
    lines: tuple[str, ...]
    targets: tuple[Target, ...]

    def styled(self, line: int) -> list[tuple[str, str]]:
        """A line as ``(text, style)`` runs, the styled targets split out."""

        runs: list[tuple[str, str]] = []
        text = self.lines[line]
        position = 0
        for target in sorted(
            (t for t in self.targets if t.line == line and t.style != "regular"),
            key=lambda t: t.start,
        ):
            if target.start > position:
                runs.append((text[position : target.start], "regular"))
            runs.append((target.surface, target.style))
            position = target.end
        if position < len(text):
            runs.append((text[position:], "regular"))
        return runs


def load_minibook(path: Path = MANIFEST) -> Minibook:
    """Read the manifest and prove every target names text on its own page."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    lines = tuple(raw["lines"])
    targets: list[Target] = []
    for entry in raw["targets"]:
        expected = entry.get("expected") or {}
        target = Target(
            id=entry["id"],
            line=int(entry["line"]),
            start=int(entry["start"]),
            surface=entry["surface"],
            cursor=int(entry["cursor"]),
            lemma=expected.get("lemma"),
            headword=expected.get("headword"),
            topik=entry.get("topik"),
            kinds=tuple(entry.get("kinds", ())),
            style=entry.get("style", "regular"),
            refuse=bool(entry.get("refuse", False)),
        )
        _require_consistent(target, lines)
        targets.append(target)
    if len({target.id for target in targets}) != len(targets):
        raise MinibookError("target ids must be unique")
    return Minibook(title=raw["title"], lines=lines, targets=tuple(targets))


def _require_consistent(target: Target, lines: Sequence[str]) -> None:
    if not 0 <= target.line < len(lines):
        raise MinibookError(f"{target.id} names line {target.line}, which does not exist")
    if lines[target.line][target.start : target.end] != target.surface:
        raise MinibookError(f"{target.id} does not match its line at {target.start}")
    if not 0 <= target.cursor < len(target.surface):
        raise MinibookError(f"{target.id} points outside its surface")
    pointed = target.surface[target.cursor]
    if target.refuse:
        if not pointed.isascii():
            raise MinibookError(f"{target.id} is a refusal target not resting on Latin")
    elif not _is_hangul(pointed) or not target.headword:
        raise MinibookError(f"{target.id} must rest on Hangul and name its headword")


# --- rendering ------------------------------------------------------------------


_CSS_STYLES = {
    "regular": "",
    "bold": "font-weight:700",
    "italic": "font-style:italic",
    "serif": "font-family:'AppleMyungjo','Batang','Noto Serif KR',serif",
}


def render_html(book: Minibook, *, canvas: bool = False) -> str:
    """The page as HTML: selectable text, or the same layout drawn on a canvas.

    The canvas form draws every glyph as pixels, which is what makes a browser
    hand the pointer to OCR rather than to its accessibility tree.
    """

    title = html.escape(book.title)
    head = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        f"<title>Hanly mini book — {title}</title><style>"
        "body{margin:0;background:#fff;color:#111;"
        "font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}"
        f"p{{position:absolute;left:{LEFT}px;margin:0;font-size:{FONT_SIZE}px;"
        f"line-height:{LINE_HEIGHT}px;white-space:nowrap}}"
        "</style></head><body>"
    )
    if canvas:
        payload = json.dumps(
            [book.styled(index) for index in range(len(book.lines))], ensure_ascii=False
        )
        height = TOP * 2 + LINE_HEIGHT * len(book.lines)
        body = (
            f"<canvas id=\"page\" width=\"{PAGE_WIDTH}\" height=\"{height}\"></canvas><script>"
            f"const LINES={payload};"
            "const FONTS={regular:'',bold:'700 ',italic:'italic ',serif:''};"
            "const c=document.getElementById('page').getContext('2d');"
            "c.fillStyle='#fff';c.fillRect(0,0,c.canvas.width,c.canvas.height);"
            "c.fillStyle='#111';c.textBaseline='middle';"
            "LINES.forEach(function(runs,i){let x=" + str(LEFT) + ";"
            "runs.forEach(function(run){const family=run[1]==='serif'?"
            "\"'AppleMyungjo','Batang',serif\":"
            "\"'Apple SD Gothic Neo','Malgun Gothic',sans-serif\";"
            f"c.font=FONTS[run[1]]+'{FONT_SIZE}px '+family;"
            f"c.fillText(run[0],x,{TOP}+i*{LINE_HEIGHT}+{LINE_HEIGHT // 2});"
            "x+=c.measureText(run[0]).width;});});</script>"
        )
    else:
        paragraphs = []
        for index in range(len(book.lines)):
            spans = "".join(
                html.escape(text)
                if style == "regular"
                else f"<span style=\"{_CSS_STYLES[style]}\">{html.escape(text)}</span>"
                for text, style in book.styled(index)
            )
            paragraphs.append(
                f"<p id=\"line-{index}\" style=\"top:{TOP + index * LINE_HEIGHT}px\">{spans}</p>"
            )
        body = "".join(paragraphs)
    return head + body + "</body></html>"


def render_rtf(book: Minibook) -> str:
    """The page as RTF, for a native text view such as TextEdit or WordPad."""

    def escape(text: str) -> str:
        out = []
        for unit in memoryview(text.encode("utf-16-le")).cast("H"):
            character = chr(unit)
            if character in "\\{}":
                out.append("\\" + character)
            elif unit < 128:
                out.append(character)
            else:
                out.append(f"\\u{unit - 65536 if unit > 32767 else unit}?")
        return "".join(out)

    codes = {"regular": "", "bold": "\\b ", "italic": "\\i ", "serif": "\\f1 "}
    closers = {"regular": "", "bold": "\\b0 ", "italic": "\\i0 ", "serif": "\\f0 "}
    paragraphs = []
    for index in range(len(book.lines)):
        paragraphs.append(
            "".join(
                codes[style] + escape(text) + closers[style]
                for text, style in book.styled(index)
            )
        )
    return (
        "{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\fnil Apple SD Gothic Neo;}"
        "{\\f1\\froman AppleMyungjo;}}\\f0\\fs36 "
        + "\\par\n".join(paragraphs)
        + "\\par\n}"
    )


@dataclass(frozen=True)
class RasterFonts:
    """The faces the raster form draws with. Local only; never committed."""

    regular: tuple[str, int]
    bold: tuple[str, int]
    serif: tuple[str, int]

    @classmethod
    def macos(cls) -> RasterFonts:
        gothic = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
        return cls(
            regular=(gothic, 0),
            bold=(gothic, 6),
            serif=("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf", 0),
        )


@dataclass(frozen=True)
class Raster:
    """The page as pixels, and where the pointer rests for each target."""

    image: Any
    points: dict[str, tuple[float, float]]


def render_raster(book: Minibook, fonts: RasterFonts | None = None) -> Raster:
    """Draw the page into memory, italic as a sheared face, and locate targets."""

    from PIL import Image, ImageDraw, ImageFont

    chosen = fonts or RasterFonts.macos()
    faces = {
        "regular": ImageFont.truetype(chosen.regular[0], FONT_SIZE, index=chosen.regular[1]),
        "bold": ImageFont.truetype(chosen.bold[0], FONT_SIZE, index=chosen.bold[1]),
        "serif": ImageFont.truetype(chosen.serif[0], FONT_SIZE, index=chosen.serif[1]),
    }
    faces["italic"] = faces["regular"]
    height = TOP * 2 + LINE_HEIGHT * len(book.lines)
    page = Image.new("RGB", (PAGE_WIDTH, height), "white")
    points: dict[str, tuple[float, float]] = {}
    for index in range(len(book.lines)):
        middle = TOP + index * LINE_HEIGHT + LINE_HEIGHT / 2
        x = float(LEFT)
        offset = 0
        for text, style in book.styled(index):
            face = faces[style]
            width = face.getlength(text)
            run = Image.new("RGB", (int(width) + 12, LINE_HEIGHT), "white")
            ImageDraw.Draw(run).text(
                (2, LINE_HEIGHT / 2), text, font=face, fill="#111", anchor="lm"
            )
            if style == "italic":
                run = run.transform(
                    run.size, Image.Transform.AFFINE, (1, 0.2, -0.2 * LINE_HEIGHT / 2, 0, 1, 0),
                    fillcolor="white",
                )
            page.paste(run, (int(x) - 2, int(middle - LINE_HEIGHT / 2)))
            for target in book.targets:
                if target.line == index and offset <= target.character < offset + len(text):
                    within = target.character - offset
                    left = x + face.getlength(text[:within])
                    right = x + face.getlength(text[: within + 1])
                    points[target.id] = ((left + right) / 2, middle)
            x += width
            offset += len(text)
    return Raster(image=page, points=points)


# --- judging --------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What one path did with one target, and the first stage that went wrong."""

    target: str
    path: str
    route: str
    selected: str | None
    lemma: str | None
    headword: str | None
    status: str | None
    target_ok: bool
    lemma_ok: bool
    dictionary_ok: bool
    stage: str | None
    stable: bool | None = None
    evidence: str | None = None


def judge(
    target: Target,
    *,
    path: str,
    route: str,
    result: Any,
    stable: bool | None = None,
    evidence: str | None = None,
) -> Outcome:
    """Compare a lookup result with what the target should have answered."""

    status = None if result is None else result.status.value
    context = None if result is None else result.context
    selected = None if context is None else context.text
    lemma = None if context is None else context.lemma
    entries = () if result is None else result.entries
    headword = entries[0].headword if entries else None

    if target.refuse:
        refused = status != "SUCCESS"
        return Outcome(
            target.id, path, route, selected, lemma, headword, status,
            refused, refused, refused, None if refused else "false_positive", stable, evidence,
        )

    # A whitespace word for OCR, the unbroken Hangul under the pointer for
    # direct text: ``않았다"고`` is read as ``않았다`` by a control.
    target_ok = selected is not None and _core(selected) in (
        _core(target.surface), _hangul_run(target.surface, target.cursor)
    )
    # KRDICT lists many inflected forms verbatim, and a form found that way is
    # probed under its surface; the dictionary form is then the entry's.
    lemma_ok = target.lemma in (lemma, headword)
    dictionary_ok = status == "SUCCESS" and headword == target.headword
    if result is None:
        stage: str | None = f"acquisition:{route}"
    elif not target_ok:
        # OCR that read text the pointer was in, but no word chosen from it,
        # is a resolution miss; no text at all is recognition's.
        read = bool(selected) or bool(context is not None and context.ocr_results)
        stage = "target" if read or path != "ocr" else "ocr"
    elif not lemma_ok:
        stage = "morphology"
    elif not dictionary_ok:
        stage = "dictionary"
    else:
        stage = None
    return Outcome(
        target.id, path, route, selected, lemma, headword, status,
        target_ok, lemma_ok, dictionary_ok, stage, stable, evidence,
    )


def evaluate_language(book: Minibook, language: Any) -> list[Outcome]:
    """Hand each target's exact surface and cursor to the language stage.

    No acquisition is involved, so a miss here belongs to morphology or the
    dictionary, and would be a miss on every acquisition path too.
    """

    from hanly import TextSelection

    outcomes = []
    for target in book.targets:
        result = language.lookup(TextSelection(target.surface, target.cursor, source="ocr"))
        outcomes.append(judge(target, path="language", route="selection", result=result))
    return outcomes


def evaluate_ocr(
    book: Minibook, raster: Raster, pipeline: Any, *, repeats: int = 3
) -> list[Outcome]:
    """Capture the ROI a hover would, run the production pixel pipeline on it.

    Each target is looked up ``repeats`` times from identical pixels and an
    identical target point; any difference between those answers is reported.
    """

    from hanly import PixelFormat, Point, ROIImage
    from hanly_app.capture import _centered_region

    width, height = ROI_SIZE
    outcomes = []
    for target in book.targets:
        x, y = raster.points[target.id]
        region = _centered_region(Point(x, y), width, height, ROI_GRID)
        crop = raster.image.crop(
            (region.left, region.top, region.left + width, region.top + height)
        )
        image = ROIImage(width, height, PixelFormat.RGB_888, crop.tobytes())
        point = Point(x - region.left, y - region.top)
        results = [pipeline.lookup(image, point) for _ in range(max(1, repeats))]
        answers = {_answer(result) for result in results}
        ocr_text = " | ".join(
            region.text for region in (results[0].context.ocr_results if results[0].context else ())
        )
        outcomes.append(
            judge(
                target, path="ocr", route="capture", result=results[0],
                stable=len(answers) == 1, evidence=ocr_text,
            )
        )
    return outcomes


def evaluate_direct(
    book: Minibook,
    points: dict[str, tuple[float, float]],
    coordinator: Any,
    language: Any,
    *,
    repeats: int = 3,
) -> list[Outcome]:
    """Read each target through the platform's accessibility, as a hover does.

    A refusal is recorded as a miss of this path, by reason; in the product the
    same hover would continue to OCR unless the refusal is ``not_korean``.
    """

    from hanly import Point

    outcomes = []
    for target in book.targets:
        point = points.get(target.id)
        if point is None:
            outcomes.append(judge(target, path="direct", route="unlocated", result=None))
            continue
        acquisitions = [coordinator.acquire(Point(*point)) for _ in range(max(1, repeats))]
        first = acquisitions[0]
        seen = {
            (a.outcome.value, a.selection.text if a.selection else None, a.selection.cursor_index
             if a.selection else None)
            for a in acquisitions
        }
        if first.selection is None:
            outcomes.append(
                judge(target, path="direct", route=first.outcome.value, result=None,
                      stable=len(seen) == 1)
            )
            continue
        result = language.lookup(first.selection)
        outcomes.append(
            judge(target, path="direct", route=first.outcome.value, result=result,
                  stable=len(seen) == 1)
        )
    return outcomes


def textedit_points(book: Minibook) -> dict[str, tuple[float, float]]:
    """Where each target's character is on screen in TextEdit, from raw AX calls.

    The reference comes straight from ``AXBoundsForRange`` on the document's
    text area. It never uses Hanly's adapter, whose answer is what is judged.
    """

    import ApplicationServices as AX
    from AppKit import NSRunningApplication

    running = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.TextEdit")
    if not running:
        raise MinibookError("open the RTF form in TextEdit first")
    application = AX.AXUIElementCreateApplication(running[0].processIdentifier())
    area = _find_role(application, "AXTextArea")
    if area is None:
        raise MinibookError("TextEdit exposes no text area")

    starts = []
    position = 0
    for line in book.lines:
        starts.append(position)
        position += len(line.encode("utf-16-le")) // 2 + 1

    points = {}
    for target in book.targets:
        prefix = book.lines[target.line][: target.character]
        index = starts[target.line] + len(prefix.encode("utf-16-le")) // 2
        span = AX.AXValueCreate(AX.kAXValueCFRangeType, (index, 1))
        error, value = AX.AXUIElementCopyParameterizedAttributeValue(
            area, "AXBoundsForRange", span, None
        )
        if error != 0 or value is None:
            continue
        ok, rect = AX.AXValueGetValue(value, AX.kAXValueCGRectType, None)
        if ok:
            points[target.id] = (
                rect.origin.x + rect.size.width / 2,
                rect.origin.y + rect.size.height / 2,
            )
    return points


def _find_role(element: Any, role: str, depth: int = 0) -> Any:
    import ApplicationServices as AX

    error, value = AX.AXUIElementCopyAttributeValue(element, "AXRole", None)
    if error == 0 and value == role:
        return element
    if depth > 8:
        return None
    error, children = AX.AXUIElementCopyAttributeValue(element, "AXChildren", None)
    for child in children or () if error == 0 else ():
        found = _find_role(child, role, depth + 1)
        if found is not None:
            return found
    return None


# --- reporting ------------------------------------------------------------------


def summarize(book: Minibook, outcomes: Iterable[Outcome]) -> dict[str, Any]:
    """Rates per path, Latin false positives, stability, and every failure."""

    by_path: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        by_path.setdefault(outcome.path, []).append(outcome)
    targets = {target.id: target for target in book.targets}
    summary: dict[str, Any] = {"korean_targets": sum(not t.refuse for t in book.targets),
                               "latin_targets": sum(t.refuse for t in book.targets), "paths": {}}
    for path, items in by_path.items():
        korean = [item for item in items if not targets[item.target].refuse]
        latin = [item for item in items if targets[item.target].refuse]
        stability = [item.stable for item in items if item.stable is not None]
        summary["paths"][path] = {
            "targets": len(korean),
            "target_rate": _rate(item.target_ok for item in korean),
            "lemma_rate": _rate(item.lemma_ok for item in korean),
            "dictionary_rate": _rate(item.dictionary_ok for item in korean),
            "latin_false_positives": sum(not item.target_ok for item in latin),
            "stable": f"{sum(stability)}/{len(stability)}" if stability else None,
            "failure_stages": dict(Counter(item.stage for item in korean if item.stage)),
            "failures": [asdict(item) for item in items if item.stage],
        }
    return summary


def _rate(values: Iterable[bool]) -> str:
    items = list(values)
    return f"{sum(items)}/{len(items)}"


def _answer(result: Any) -> tuple[Any, ...]:
    context = result.context
    return (
        result.status.value,
        None if context is None else context.text,
        None if context is None else context.lemma,
        result.entries[0].headword if result.entries else None,
    )


def _core(text: str) -> str:
    """A word without the punctuation and quotes that cling to it on a page."""

    return text.strip().strip("\"'“”‘’.,!?()[]")


def _hangul_run(text: str, index: int) -> str:
    start = index
    while start > 0 and _is_hangul(text[start - 1]):
        start -= 1
    end = index + 1
    while end < len(text) and _is_hangul(text[end]):
        end += 1
    return text[start:end]


def _is_hangul(character: str) -> bool:
    return "가" <= character <= "힣"


# --- command line ---------------------------------------------------------------


def _language(database: Path) -> Any:
    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider
    from hanly.language_pipeline import LanguagePipeline

    return LanguagePipeline(KiwiProvider(), KRDICTProvider(database))


def _pixel_pipeline(database: Path, backend: str) -> Any:
    from hanly import LookupPipeline
    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider

    ocr: Any
    if backend == "vision":
        from hanly.vision_provider import VisionProvider

        ocr = VisionProvider()
    else:
        from hanly.easyocr_provider import EasyOCRConfig, EasyOCRProvider

        ocr = EasyOCRProvider(EasyOCRConfig(download_enabled=False))
    prewarm: Callable[[], None] | None = getattr(ocr, "prewarm", None)
    if prewarm is not None:
        prewarm()
    return LookupPipeline(ocr, KiwiProvider(), KRDICTProvider(database))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minibook", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="write the HTML, canvas and RTF forms")
    render.add_argument("--out", type=Path, required=True)
    evaluate = commands.add_parser("evaluate", help="judge acquisition paths")
    evaluate.add_argument("--paths", default="language,ocr")
    evaluate.add_argument("--database", type=Path, default=Path("data/generated/krdict.sqlite3"))
    evaluate.add_argument("--backend", choices=("vision", "easyocr"), default="vision")
    evaluate.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    book = load_minibook()
    if args.command == "render":
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "minibook.html").write_text(render_html(book), encoding="utf-8")
        (args.out / "minibook-canvas.html").write_text(render_html(book, canvas=True), "utf-8")
        (args.out / "minibook.rtf").write_text(render_rtf(book), encoding="ascii")
        print(args.out)
        return 0

    outcomes: list[Outcome] = []
    paths = set(args.paths.split(","))
    language = _language(args.database)
    if "language" in paths:
        outcomes += evaluate_language(book, language)
    if "ocr" in paths:
        outcomes += evaluate_ocr(
            book, render_raster(book), _pixel_pipeline(args.database, args.backend)
        )
    if "direct" in paths:
        from hanly_app.text_acquisition import DirectTextCoordinator
        from hanly_app.text_acquisition_ax import AccessibilityTextProvider

        coordinator = DirectTextCoordinator(AccessibilityTextProvider(), timeout_ms=200)
        outcomes += evaluate_direct(book, textedit_points(book), coordinator, language)
    report = summarize(book, outcomes)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.report is not None:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
