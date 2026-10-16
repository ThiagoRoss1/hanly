"""Reproduce hover word selection over OCR and say why each miss happened.

``python -m lab word-selection`` renders Lab-authored Korean pages, hovers the
first, middle and last syllable of every word on a page's middle line, crops
exactly as the desktop does (``_centered_region`` with the shipped ROI and
grid, clipped to the page as to a display) and runs the real lookup worker.
Glyph geometry is known exactly, so each miss is classified against ground
truth rather than guessed:

``clipped_by_roi``      the word extends past the captured crop
``ocr_false_space``     the recognized line splits the word with a space
``ocr_misread``         the line lacks or alters the word's characters
``neighbor_word``       the line holds the word, but another one was selected
``wrong_line``          a different line was selected
``no_result``           nothing usable came back
``lexical``             the right surface, a headword the corpus does not accept

Pixels and recognized text stay in this process; the report keeps counts,
categories, geometry and digests.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

#: The desktop's ROI and grid, as ``hanly_app.service`` composes capture.
ROI_SIZE = (200, 100)
PAGE_SIZE = (1280, 360)
SIZES = (14, 20, 28)
THEMES = {"light": (255, 0), "dark": (24, 235)}
#: ``edge`` starts the line two pixels from the display's left edge.
POSITIONS = {"normal": 220, "edge": 2}
CURSORS = ("first", "middle", "last")
#: A recognized region within this many pixels of the crop edge may be cut.
EDGE_MARGIN = 2.0


@dataclass(frozen=True)
class Hover:
    page: str
    line: str
    word: str
    word_index: int
    cursor: str
    size: int
    theme: str
    position: str
    point: tuple[float, float]
    word_box: tuple[float, float, float, float]
    neighbours: tuple[str, ...]
    accept: tuple[str, ...] = ()


@dataclass
class Observation:
    hover: Hover
    category: str
    surface: str | None
    headword: str | None
    status: str
    clipped: bool
    edge_touch: bool
    ocr_calls: int
    latency_ms: float
    #: The edge-retry candidate: whether it fired, and what it changed.
    retried: bool = False
    retry_category: str | None = None
    retry_ocr_calls: int = 0
    retry_latency_ms: float = 0.0


def sentences() -> list[tuple[str, dict[str, tuple[str, ...]]]]:
    """Lab-authored lines with the headwords a target word should give."""

    from .korean_grammar import load_corpus
    from .minibook import load_minibook

    lines: dict[str, dict[str, tuple[str, ...]]] = {}
    for case in load_corpus():
        accepted = next(iter(case.accept.values()), ())
        lines.setdefault(case.text, {})[case.target] = accepted
    book = load_minibook()
    for target in book.targets:
        line = book.lines[target.line]
        if target.refuse or target.lemma is None:
            continue
        surface = line[target.start: target.start + len(target.surface)]
        word = _word_containing(line, target.start)
        if word and surface:
            lines.setdefault(line, {}).setdefault(word, (target.headword or target.lemma,))
    return [(text, accepted) for text, accepted in lines.items() if " " in text or len(text) > 2]


def hovers(
    face: Any, limit: int | None = None, stride: int = 1
) -> Iterator[tuple[Hover, Any]]:
    """Every planned hover with the page image it is made over.

    ``stride`` keeps every n-th line, a deterministic subset of the same plan.
    """

    from PIL import Image, ImageDraw

    texts = sentences()[::stride]
    produced = 0
    for size in SIZES:
        font = face.font(size)
        for theme, (background, foreground) in THEMES.items():
            for position, left in POSITIONS.items():
                for number, (line, accepted) in enumerate(texts):
                    above = texts[(number + 1) % len(texts)][0]
                    below = texts[(number + 2) % len(texts)][0]
                    page = Image.new("RGB", PAGE_SIZE, (background,) * 3)
                    draw = ImageDraw.Draw(page)
                    height = int(size * 1.6)
                    middle_top = PAGE_SIZE[1] // 2 - height // 2
                    for text, top in ((above, middle_top - height), (line, middle_top),
                                      (below, middle_top + height)):
                        draw.text((left, top), text, font=font, fill=(foreground,) * 3)
                    words = _words(line)
                    for index, (word, start) in enumerate(words):
                        box = _span_box(font, line, left, middle_top, start, start + len(word))
                        hangul = [i for i, ch in enumerate(word) if "가" <= ch <= "힣"]
                        if not hangul:
                            continue
                        picks = {"first": hangul[0], "middle": hangul[len(hangul) // 2],
                                 "last": hangul[-1]}
                        for cursor in CURSORS:
                            char = start + picks[cursor]
                            x0, _, x1, _ = _span_box(font, line, left, middle_top, char, char + 1)
                            point = ((x0 + x1) / 2, (box[1] + box[3]) / 2)
                            yield Hover(
                                page=hashlib.sha256(page.tobytes()).hexdigest()[:12],
                                line=line, word=word, word_index=index, cursor=cursor,
                                size=size, theme=theme, position=position, point=point,
                                word_box=box,
                                neighbours=tuple(w for w, _ in words),
                                accept=accepted.get(word, ()),
                            ), page
                            produced += 1
                            if limit is not None and produced >= limit:
                                return


def crop(
    page: Any, point: tuple[float, float], width: int = ROI_SIZE[0]
) -> tuple[Any, tuple[int, int, int, int], Any]:
    """The ROI the desktop would capture, clipped to the page as to a display."""

    from hanly import PixelFormat, Point, ROIImage
    from hanly_app.acquisition.capture import DEFAULT_ROI_GRID, _centered_region

    region = _centered_region(Point(*point), width, ROI_SIZE[1], DEFAULT_ROI_GRID)
    left = max(0, region.left)
    top = max(0, region.top)
    right = min(PAGE_SIZE[0], region.left + region.width)
    bottom = min(PAGE_SIZE[1], region.top + region.height)
    image = page.crop((left, top, right, bottom))
    roi = ROIImage(width=image.width, height=image.height,
                   pixel_format=PixelFormat.RGB_888, data=image.tobytes())
    return roi, (left, top, right, bottom), Point(point[0] - left, point[1] - top)


def classify(
    hover: Hover, roi_box: tuple[int, int, int, int], result: Any
) -> tuple[str, bool, bool]:
    """(category, word clipped by the crop, selected line touches the crop edge)."""

    left, _, right, _ = roi_box
    clipped = hover.word_box[0] < left or hover.word_box[2] > right
    context = result.context
    surface = _clean(context.text) if context is not None and context.text else None
    selected = context.selected_ocr if context is not None else None
    edge = False
    if selected is not None:
        box = selected.quad.bounding_box()
        edge = box.left <= EDGE_MARGIN or box.right >= (right - left) - EDGE_MARGIN
    expected = _clean(hover.word)
    headword = result.entries[0].headword if result.entries else None
    if surface == expected:
        if hover.accept and headword not in hover.accept:
            return "lexical", clipped, edge
        return "correct", clipped, edge
    if surface is None:
        return ("clipped_by_roi" if clipped else "no_result"), clipped, edge
    line = selected.text if selected is not None else ""
    if clipped and surface in expected:
        return "clipped_by_roi", clipped, edge
    if expected in line.replace(" ", "") and expected not in line.split():
        return "ocr_false_space", clipped, edge
    others = {_clean(word) for word in hover.neighbours} - {expected}
    if surface in others:
        in_line = expected in [_clean(word) for word in line.split()]
        return ("neighbor_word" if in_line else "ocr_misread"), clipped, edge
    if expected not in line:
        # The selected line may simply be another line of the page.
        return ("wrong_line" if _clean(surface) not in hover.line else "ocr_misread"), clipped, edge
    return "neighbor_word", clipped, edge


def run(
    runtime_config: Path,
    backend: str,
    *,
    limit: int | None,
    stride: int,
    output_root: Path,
    edge_retry: bool = False,
) -> Path:
    from dataclasses import replace

    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider
    from hanly_app.composition import create_lookup_worker_factory
    from hanly_app.config import OCRBackend
    from hanly_app.lookup.controller import LookupRequest
    from hanly_app.lookup.process import _ocr_provider_factory
    from hanly_app.runtime import load_runtime

    from .resources.child import _CountingOCR

    settings = replace(load_runtime(runtime_config).lookup_settings(),
                       ocr_backend=OCRBackend(backend))
    ocr = _CountingOCR(_ocr_provider_factory(settings)())
    worker = create_lookup_worker_factory(
        lambda: ocr, KiwiProvider, lambda: KRDICTProvider(settings.krdict_path),
        confidence_threshold=settings.confidence_threshold,
        skip_flat_rois=settings.skip_flat_rois, ocr_backend=backend,
    )()
    face = _Face.discover()
    observations: list[Observation] = []
    try:
        for number, (hover, page) in enumerate(hovers(face, limit, stride), start=1):
            roi, box, target = crop(page, hover.point)
            before = ocr.calls
            started = time.perf_counter()
            result = worker(LookupRequest(number, roi, target))
            latency = (time.perf_counter() - started) * 1000
            category, clipped, edge = classify(hover, box, result)
            retry: dict[str, Any] = {}
            if edge_retry and _word_touches_edge(result, roi.width):
                # Candidate: one wider capture around the same pointer, only
                # when the resolved word reaches the crop's side.
                wide, wide_box, wide_target = crop(page, hover.point, ROI_SIZE[0] * 2)
                before_retry = ocr.calls
                started = time.perf_counter()
                second = worker(LookupRequest(number + 1_000_000, wide, wide_target))
                retry = {
                    "retried": True,
                    "retry_category": classify(hover, wide_box, second)[0],
                    "retry_ocr_calls": ocr.calls - before_retry,
                    "retry_latency_ms": (time.perf_counter() - started) * 1000,
                }
            observations.append(Observation(
                hover=hover, category=category,
                surface=_digest(result.context.text) if result.context and result.context.text
                else None,
                headword=result.entries[0].headword if result.entries else None,
                status=result.status.value, clipped=clipped, edge_touch=edge,
                ocr_calls=ocr.calls - before, latency_ms=latency, **retry,
            ))
    finally:
        worker.close()
    return _write(observations, backend, face.name, output_root, stride, edge_retry)


def _word_touches_edge(result: Any, width: int) -> bool:
    """The resolved word's box reaches the crop's left or right side."""

    region = result.context.word_region if result.context is not None else None
    if region is None:
        return False
    return region.left <= EDGE_MARGIN or region.right >= width - EDGE_MARGIN


def summarize(observations: Sequence[Observation]) -> dict[str, Any]:
    total: Counter[str] = Counter(o.category for o in observations)
    groups: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for o in observations:
        for name, value in (("size", o.hover.size), ("theme", o.hover.theme),
                            ("position", o.hover.position), ("cursor", o.hover.cursor)):
            groups[name][str(value)][o.category] += 1
    edge_misses = sum(1 for o in observations if o.edge_touch and o.category != "correct")
    edge_total = sum(1 for o in observations if o.edge_touch)
    latencies = sorted(o.latency_ms for o in observations if o.ocr_calls)
    retried = [o for o in observations if o.retried]
    retry = {
        "fired": len(retried),
        "recovered": sum(1 for o in retried
                         if o.category != "correct" and o.retry_category == "correct"),
        "disturbed": sum(1 for o in retried
                         if o.category == "correct" and o.retry_category != "correct"),
        "extra_ocr_calls": sum(o.retry_ocr_calls for o in retried),
        "extra_latency_ms": {
            "p50": _rank(sorted(o.retry_latency_ms for o in retried), 0.5),
            "p95": _rank(sorted(o.retry_latency_ms for o in retried), 0.95),
        },
    }
    return {
        "hovers": len(observations),
        "categories": dict(total.most_common()),
        "groups": {name: {key: dict(c) for key, c in sorted(values.items())}
                   for name, values in groups.items()},
        "edge_signal": {
            "touching": edge_total, "touching_and_wrong": edge_misses,
            "wrong_total": sum(1 for o in observations if o.category != "correct"),
        },
        "ocr_calls": sum(o.ocr_calls for o in observations),
        "edge_retry": retry,
        "fresh_latency_ms": {
            "p50": _rank(latencies, 0.5), "p95": _rank(latencies, 0.95), "n": len(latencies),
        },
    }


def _write(
    observations: Sequence[Observation], backend: str, face: str, root: Path, stride: int,
    edge_retry: bool = False,
) -> Path:
    from datetime import datetime

    from .metadata import build_metadata

    run_dir = root / f"{datetime.now():%Y%m%d-%H%M%S}-word-selection-{backend}"
    run_dir.mkdir(parents=True, exist_ok=False)
    summary = summarize(observations)
    metadata = build_metadata(
        run_id=run_dir.name, kind="word_selection", repo_root=Path.cwd(),
        config={"backend": backend, "face": face, "roi": ROI_SIZE, "sizes": SIZES,
                "stride": stride, "edge_retry": edge_retry,
                "themes": list(THEMES), "positions": list(POSITIONS)},
        scenario={"name": "word_selection"},
    )
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", "utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    with (run_dir / "observations.jsonl").open("w", encoding="utf-8") as stream:
        for o in observations:
            record = asdict(o)
            hover = record.pop("hover")
            # Lab-authored text: the line is kept as a digest, the word in clear
            # only as its corpus id would be, so the file stays reviewable.
            record.update(
                line=_digest(hover["line"]), word=hover["word"], cursor=hover["cursor"],
                size=hover["size"], theme=hover["theme"], position=hover["position"],
            )
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    lines = [f"# Word selection over OCR (`{backend}`, {face})", "",
             f"Hovers: {summary['hovers']}; genuine OCR calls: {summary['ocr_calls']}; "
             f"fresh lookup p50 {summary['fresh_latency_ms']['p50']:.0f} ms, "
             f"p95 {summary['fresh_latency_ms']['p95']:.0f} ms", "",
             "| category | hovers |", "|---|---|"]
    lines += [f"| {name} | {count} |" for name, count in summary["categories"].items()]
    for group, values in summary["groups"].items():
        names = sorted({c for counts in values.values() for c in counts})
        lines += ["", f"## By {group}", "", "| " + group + " | " + " | ".join(names) + " |",
                  "|" + "---|" * (len(names) + 1)]
        for key, counts in values.items():
            lines.append(f"| {key} | " + " | ".join(str(counts.get(n, 0)) for n in names) + " |")
    edge = summary["edge_signal"]
    lines += ["", "## Crop-edge signal", "",
              f"- Selected line touching the crop edge: {edge['touching']} hovers, "
              f"{edge['touching_and_wrong']} of them wrong (of {edge['wrong_total']} wrong)."]
    if edge_retry:
        r = summary["edge_retry"]
        lines += ["", "## Edge-retry candidate (not shipped)", "",
                  f"- Fired on {r['fired']} hovers: recovered {r['recovered']} misses, "
                  f"disturbed {r['disturbed']} correct answers, "
                  f"{r['extra_ocr_calls']} extra genuine OCR calls; added latency p50 "
                  f"{r['extra_latency_ms']['p50']:.0f} ms, "
                  f"p95 {r['extra_latency_ms']['p95']:.0f} ms."]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", "utf-8")
    return run_dir


class _Face:
    def __init__(self, path: Path, index: int, name: str) -> None:
        self.path, self.index, self.name = path, index, name

    @classmethod
    def discover(cls) -> _Face:
        """The first installed Hangul face, or the one ``HANLY_LAB_FACE`` names.

        A named face that is not installed is an error: substituting another
        would make two machines' results look comparable when they are not.
        """

        import os

        from .synthetic_ocr import discover_faces

        faces = discover_faces()
        if not faces:
            raise RuntimeError("no installed face draws Hangul")
        wanted = os.environ.get("HANLY_LAB_FACE", "").strip().lower()
        if wanted:
            matching = [face for face in faces if wanted in face.family.lower()]
            if not matching:
                names = sorted({face.family for face in faces})
                raise RuntimeError(f"HANLY_LAB_FACE={wanted!r} is not installed; found {names}")
            faces = matching
        face = faces[0]
        return cls(face.path, face.index, f"{face.family}#{face.index}")

    def font(self, size: int) -> Any:
        from PIL import ImageFont

        return ImageFont.truetype(str(self.path), size, index=self.index)


def _words(line: str) -> list[tuple[str, int]]:
    words: list[tuple[str, int]] = []
    index = 0
    for word in line.split(" "):
        if word:
            words.append((word, index))
        index += len(word) + 1
    return words


def _word_containing(line: str, index: int) -> str | None:
    for word, start in _words(line):
        if start <= index < start + len(word):
            return word
    return None


def _span_box(font: Any, line: str, left: int, top: int, start: int, end: int
              ) -> tuple[float, float, float, float]:
    x0 = left + font.getlength(line[:start])
    x1 = left + font.getlength(line[:end])
    _, ascent_top, _, descent_bottom = font.getbbox(line)
    return (x0, top + ascent_top, x1, top + descent_bottom)


def _clean(word: str) -> str:
    return word.strip().strip(".,!?;:'\"()[]")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _rank(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    return values[max(0, min(len(values) - 1, int(round(q * len(values) + 0.5)) - 1))]


def load_summary(run_dir: Path) -> Mapping[str, Any]:
    return dict(json.loads((run_dir / "summary.json").read_text("utf-8")))
