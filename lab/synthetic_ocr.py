"""Generate controlled OCR fixtures, not evidence of real-surface accuracy.

Missing fonts and glyphs are refused rather than substituted. Fixtures whose
fonts cannot be redistributed stay local. Every sample records what decided
its pixels -- face bytes, renderer, layout, colours, transforms and the final
pixel hash -- and what is true about it: whether there is text, whether it is
Korean, what the pointer should select, and whether its regions are fully
annotated.

Two kinds of resampling are kept apart. ``supersample`` draws at N times the
size and reduces once, which is antialiasing. ``scale`` resizes the finished
image, which imitates a display scaling the text after it was rendered.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Bumped whenever the same specification could produce different pixels.
GENERATOR_VERSION = 2

#: What a sample can show. Only ``text`` has glyphs; the rest are negatives.
CONTENTS = ("text", "blank", "icon", "border", "texture")
ICONS = ("circle", "star", "arrow", "check", "bars")
TEXTURES = ("stripes", "checker", "grain", "gradient")


def _font_directories() -> tuple[Path, ...]:
    windows = os.environ.get("WINDIR", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA")
    return (
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / "Library" / "Fonts",
        Path.home() / ".fonts",
        Path.home() / ".local" / "share" / "fonts",
        Path(windows) / "Fonts",
        *((Path(local) / "Microsoft" / "Windows" / "Fonts",) if local else ()),
    )


#: Where a face is looked for when a specification names no explicit path.
DEFAULT_FONT_SEARCH_PATHS = _font_directories()

#: Licences under which a rendered sample may be committed to this repository.
REDISTRIBUTABLE_LICENCES = frozenset({"OFL-1.1", "Apache-2.0", "CC0-1.0"})

#: One probe character per script whose coverage a face must prove.
SCRIPT_PROBES = {"hangul": "한", "latin": "A", "kana": "あ", "han": "中"}


class SyntheticFontError(RuntimeError):
    """Raised when the requested face is unavailable or may not be committed."""


class SyntheticRenderError(RuntimeError):
    """Raised when a sample cannot be rendered legibly."""


@dataclass(frozen=True)
class FontSpec:
    """One named face, the licence it carries, and where to look for it."""

    name: str
    licence: str
    filenames: tuple[str, ...]
    #: An explicit path wins over the search; useful for a vendored face.
    path: Path | None = None
    #: Which face inside a collection file, for ``.ttc``.
    index: int = 0

    @property
    def redistributable(self) -> bool:
        return self.licence in REDISTRIBUTABLE_LICENCES


@dataclass(frozen=True)
class ResolvedFont:
    """A face that really exists on this machine, identified by its bytes."""

    spec: FontSpec
    path: Path
    sha256: str
    byte_count: int

    @property
    def redistributable(self) -> bool:
        return self.spec.redistributable


@dataclass(frozen=True)
class SampleSpec:
    """One image to render, and everything that decides what it looks like."""

    case_id: str
    text: str
    font: FontSpec | None
    font_size: int = 20
    padding: int = 12
    background: int = 255
    foreground: int = 0
    #: Resize of the finished image, imitating display scaling after rendering.
    scale: float = 1.0
    #: JPEG quality applied and undone, to imitate compression artefacts.
    jpeg_quality: int | None = None
    blur_radius: float = 0.0
    tags: tuple[str, ...] = ()
    #: Where the pointer is annotated to sit, as a fraction of the rendered
    #: image. Superseded by ``target_index``, which is exact.
    target_fraction: tuple[float, float] | None = None
    #: The word the pointer is expected to select.
    expected_surface: str | None = None
    #: ``text`` or one of the text-free negatives in ``CONTENTS``.
    content: str = "text"
    #: Draw at this multiple and reduce once: antialiasing, not display scaling.
    supersample: int = 1
    antialias: bool = True
    #: Standard deviation of seeded Gaussian noise, in grey levels.
    noise: float = 0.0
    seed: int = 0
    #: Canvas for text-free content, before ``scale``.
    canvas: tuple[int, int] = (160, 48)
    #: Which icon or texture a text-free sample draws.
    graphic: str | None = None
    #: The character the pointer rests on; its exact position is computed.
    target_index: int | None = None
    #: ``positive``, ``negative`` or ``mixed``, for the corpus.
    family: str | None = None

    def __post_init__(self) -> None:
        if self.content not in CONTENTS:
            raise ValueError(f"content must be one of {CONTENTS}")
        if self.content == "text":
            if not self.text.strip():
                raise ValueError("a synthetic sample needs text")
            if self.font is None:
                raise ValueError("a text sample needs a font")
        elif self.text:
            raise ValueError(f"a {self.content} sample carries no text")
        if self.content in {"icon", "texture"} and self.graphic not in (
            ICONS if self.content == "icon" else TEXTURES
        ):
            raise ValueError(f"unknown {self.content} {self.graphic!r}")
        if self.font_size < 6:
            raise ValueError("font_size must be at least 6")
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        if self.supersample < 1:
            raise ValueError("supersample must be at least 1")
        if self.target_index is not None and not 0 <= self.target_index < len(self.text):
            raise ValueError("target_index must point into the text")


@dataclass(frozen=True)
class RenderedSample:
    """One rendered image plus the metadata that lets it be reproduced."""

    case_id: str
    width: int
    height: int
    mode: str
    data: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveredFace:
    """One face found on this machine and which scripts it can really draw."""

    file: str
    path: Path
    index: int
    family: str
    style: str
    sha256: str
    scripts: tuple[str, ...]

    def spec(self, licence: str = "unknown") -> FontSpec:
        # A discovered face's licence is unknown unless someone states it, so
        # everything rendered from it stays local.
        return FontSpec(self.family, licence, (self.file,), path=self.path, index=self.index)


def resolve_font(
    spec: FontSpec, search_paths: tuple[Path, ...] = DEFAULT_FONT_SEARCH_PATHS
) -> ResolvedFont:
    """Find the exact face named, or fail saying what is missing.

    There is deliberately no fallback. A sample rendered in a substituted face
    still looks like Korean text, so a silent fallback would be discovered only
    as an unexplainable difference between two machines' numbers.
    """

    candidates = (
        [spec.path]
        if spec.path is not None
        else [directory / filename for directory in search_paths for filename in spec.filenames]
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            payload = candidate.read_bytes()
            return ResolvedFont(
                spec=spec,
                path=candidate,
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_count=len(payload),
            )
    raise SyntheticFontError(
        f"the face {spec.name!r} ({spec.licence}) is not installed; looked for "
        f"{list(spec.filenames)}. Install it rather than letting the platform "
        "substitute another face, which would mislabel every sample rendered."
    )


def discover_faces(
    search_paths: Sequence[Path] = DEFAULT_FONT_SEARCH_PATHS,
    *,
    scripts: Sequence[str] = ("hangul",),
) -> list[DiscoveredFace]:
    """Every installed face that proves it can draw all of ``scripts``.

    Nothing is downloaded, installed or substituted; a face is listed only when
    each probe character renders as something other than its missing-glyph box.
    """

    from PIL import Image, ImageFont

    found: list[DiscoveredFace] = []
    seen: set[tuple[str, int]] = set()
    for directory in search_paths:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc", ".otc"} or not path.is_file():
                continue
            digest: str | None = None
            for index in range(16 if path.suffix.lower() in {".ttc", ".otc"} else 1):
                try:
                    face = ImageFont.truetype(str(path), 20, index=index)
                except (OSError, ValueError):
                    break
                try:
                    covered = tuple(
                        name
                        for name, probe in SCRIPT_PROBES.items()
                        if _has_glyph(Image, face, probe)
                    )
                except OSError:
                    # Some system faces (bitmap or colour emoji) cannot rasterize a mask.
                    continue
                if not set(scripts) <= set(covered):
                    continue
                digest = digest or hashlib.sha256(path.read_bytes()).hexdigest()
                if (digest, index) in seen:
                    continue
                seen.add((digest, index))
                family, style = face.getname()
                if str(family).startswith("."):
                    # A platform-private UI face, not one a page can name.
                    continue
                found.append(
                    DiscoveredFace(path.name, path, index, str(family), str(style), digest, covered)
                )
    return found


def render_sample(
    spec: SampleSpec, search_paths: tuple[Path, ...] = DEFAULT_FONT_SEARCH_PATHS
) -> RenderedSample:
    """Render one sample deterministically, refusing an illegible result."""

    from PIL import Image, ImageDraw, ImageFilter

    font: ResolvedFont | None = None
    style: str | None = None
    if spec.font is not None and spec.content == "text":
        font = resolve_font(spec.font, search_paths)
        face = _open_face(font, spec.font_size * spec.supersample)
        style = str(face.getname()[1])
        _require_glyphs(Image, face, spec)
        image, geometry = _draw_text(Image, ImageDraw, face, spec)
    else:
        image, geometry = _draw_graphic(Image, ImageDraw, spec), {}

    image, geometry = _reduce(Image, image, geometry, spec.supersample)
    image, geometry = _apply_scale(Image, image, geometry, spec.scale)
    image = _apply_blur(ImageFilter, image, spec)
    image = _apply_noise(Image, image, spec)
    image = _apply_compression(Image, image, spec)
    if spec.content != "blank":
        _require_legible(image, spec)

    data = image.tobytes()
    return RenderedSample(
        case_id=spec.case_id,
        width=image.width,
        height=image.height,
        mode=image.mode,
        data=data,
        metadata=_metadata(spec, font, style, geometry, image, data),
    )


def write_sample(sample: RenderedSample, destination: Path) -> Path:
    """Write one rendered sample as a PNG."""

    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.frombytes(sample.mode, (sample.width, sample.height), sample.data)
    image.save(destination, format="PNG", optimize=True)
    image.close()
    return destination


def corpus_entry(
    sample: RenderedSample, relative_image: str, *, redistributable: bool
) -> dict[str, Any]:
    """Describe one rendered sample as a corpus manifest case.

    A face that may not be redistributed produces a ``local_synthetic`` case,
    which corpus validation refuses to accept in a committed manifest.
    """

    metadata = sample.metadata
    entry: dict[str, Any] = {
        "id": sample.case_id,
        "image": relative_image,
        "provenance": "committed_synthetic" if redistributable else "local_synthetic",
        "tags": list(metadata.get("tags", ())),
        "expected_text": metadata.get("text") or None,
        "source": {key: value for key, value in metadata.items() if key not in _NOT_SOURCE},
        "truth": metadata["truth"],
        "generation": metadata["generation"],
        "expected_regions": metadata["regions"],
    }
    if metadata.get("family"):
        entry["family"] = metadata["family"]
    point = metadata.get("target_point")
    fraction = metadata.get("target_fraction")
    if point is not None:
        entry["expected_target"] = [round(point[0], 3), round(point[1], 3)]
    elif fraction is not None:
        entry["expected_target"] = [
            round(fraction[0] * sample.width, 3),
            round(fraction[1] * sample.height, 3),
        ]
    if metadata.get("expected_surface") is not None:
        entry["expected_surface"] = metadata["expected_surface"]
    return entry


_NOT_SOURCE = frozenset(
    {
        "text",
        "tags",
        "target_fraction",
        "expected_surface",
        "truth",
        "generation",
        "regions",
        "target_point",
        "family",
    }
)


def load_generator_config(path: str | Path) -> tuple[FontSpec, tuple[SampleSpec, ...]]:
    """Read the declarative generator description."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_font = payload["font"]
    font = FontSpec(
        name=str(raw_font["name"]),
        licence=str(raw_font["licence"]),
        filenames=tuple(str(name) for name in raw_font["filenames"]),
        path=Path(raw_font["path"]) if raw_font.get("path") else None,
        index=int(raw_font.get("index", 0)),
    )
    samples = tuple(_sample_from(entry, font) for entry in payload["samples"])
    return font, samples


def _sample_from(entry: dict[str, Any], font: FontSpec) -> SampleSpec:
    fraction = entry.get("target_fraction")
    return SampleSpec(
        case_id=str(entry["id"]),
        text=str(entry.get("text", "")),
        font=font,
        font_size=int(entry.get("font_size", 20)),
        padding=int(entry.get("padding", 12)),
        background=int(entry.get("background", 255)),
        foreground=int(entry.get("foreground", 0)),
        scale=float(entry.get("scale", 1.0)),
        jpeg_quality=entry.get("jpeg_quality"),
        blur_radius=float(entry.get("blur_radius", 0.0)),
        tags=tuple(entry.get("tags", ())),
        target_fraction=(float(fraction[0]), float(fraction[1])) if fraction else None,
        expected_surface=entry.get("expected_surface"),
        content=str(entry.get("content", "text")),
        supersample=int(entry.get("supersample", 1)),
        antialias=bool(entry.get("antialias", True)),
        noise=float(entry.get("noise", 0.0)),
        seed=int(entry.get("seed", 0)),
        graphic=entry.get("graphic"),
        target_index=entry.get("target_index"),
        family=entry.get("family"),
    )


# -- truth --------------------------------------------------------------------------------


def is_hangul_syllable(character: str) -> bool:
    return "가" <= character <= "힣"


def truth(spec: SampleSpec) -> dict[str, Any]:
    """What is true of the sample, decided by its specification, never by OCR."""

    text_present = spec.content == "text"
    korean_present = text_present and any(is_hangul_syllable(ch) for ch in spec.text)
    if spec.target_index is not None:
        on_korean = is_hangul_syllable(spec.text[spec.target_index])
        target = "surface" if on_korean else "no_korean"
    elif spec.target_fraction is not None and spec.expected_surface:
        target = "surface"
    elif not korean_present:
        # Wherever the pointer rests, there is no Korean to select.
        target = "no_korean"
    else:
        target = "none"
    return {
        "text_present": text_present,
        "korean_present": korean_present,
        "target": target,
        # One line is one region and text-free content has none: both complete.
        "regions": "complete",
    }


def target_surface(spec: SampleSpec) -> str | None:
    """The Hangul run around the pointer, as the tour's own scoring reads it."""

    if spec.expected_surface is not None:
        return spec.expected_surface
    if spec.target_index is None or not is_hangul_syllable(spec.text[spec.target_index]):
        return None
    start = end = spec.target_index
    while start > 0 and is_hangul_syllable(spec.text[start - 1]):
        start -= 1
    while end < len(spec.text) and is_hangul_syllable(spec.text[end]):
        end += 1
    return spec.text[start:end]


# -- drawing ------------------------------------------------------------------------------


def _open_face(font: ResolvedFont, size: int) -> Any:
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(font.path), size, index=font.spec.index)
    except OSError as error:
        raise SyntheticFontError(
            f"{font.path.name} could not be opened at index {font.spec.index}: {error}"
        ) from error


def _require_glyphs(image_module: Any, face: Any, spec: SampleSpec) -> None:
    """Refuse text the chosen face cannot actually draw.

    Pillow draws a missing glyph as the font's ``.notdef`` box rather than
    failing, and that box has perfectly ordinary dimensions, so a face without
    Hangul coverage would silently produce a row of identical boxes labelled as
    Korean. Comparing each glyph against the box a guaranteed-absent codepoint
    produces is what actually distinguishes them.
    """

    missing = [
        character
        for character in dict.fromkeys(spec.text)
        if not character.isspace() and not _has_glyph(image_module, face, character)
    ]
    if missing:
        name = spec.font.name if spec.font is not None else "?"
        raise SyntheticFontError(
            f"the face {name!r} has no glyph for {missing}; it cannot render {spec.case_id!r}"
        )


def _has_glyph(image_module: Any, face: Any, character: str) -> bool:
    return _glyph_bytes(image_module, face, character) != _glyph_bytes(image_module, face, "\uffff")


def _glyph_bytes(image_module: Any, face: Any, character: str) -> bytes:
    mask = face.getmask(character, mode="L")
    return image_module.frombytes("L", mask.size, bytes(mask)).tobytes()


def _draw_text(
    image_module: Any, draw_module: Any, face: Any, spec: SampleSpec
) -> tuple[Any, dict[str, Any]]:
    padding = spec.padding * spec.supersample
    left, top, right, bottom = face.getbbox(spec.text)
    image = image_module.new(
        "L", (right - left + padding * 2, bottom - top + padding * 2), spec.background
    )
    origin_x, origin_y = padding - left, padding - top
    draw = draw_module.Draw(image)
    if not spec.antialias:
        draw.fontmode = "1"
    draw.text((origin_x, origin_y), spec.text, font=face, fill=spec.foreground)

    # The face's own box can include empty ascent or descent; the drawn ink is the
    # truth, so the canvas is trimmed to it plus the padding on every side.
    ink = image.point(lambda value: 255 if value != spec.background else 0).getbbox()
    if ink is not None:
        crop = (ink[0] - padding, ink[1] - padding, ink[2] + padding, ink[3] + padding)
        canvas = image_module.new("L", (crop[2] - crop[0], crop[3] - crop[1]), spec.background)
        # Pasting the whole drawing at an offset keeps the background outside it,
        # where ``crop`` would fill anything beyond the original edge with black.
        canvas.paste(image, (-crop[0], -crop[1]))
        image, origin_x, origin_y = canvas, origin_x - crop[0], origin_y - crop[1]
        line = (padding, padding, padding + ink[2] - ink[0], padding + ink[3] - ink[1])
    else:
        line = (padding, padding, padding + right - left, padding + bottom - top)
    geometry: dict[str, Any] = {"line_box": line}
    if spec.target_index is not None:
        index = spec.target_index
        x0 = origin_x + face.getlength(spec.text[:index])
        x1 = origin_x + face.getlength(spec.text[: index + 1])
        geometry["target_point"] = ((x0 + x1) / 2, (line[1] + line[3]) / 2)
    return image, geometry


def _draw_graphic(image_module: Any, draw_module: Any, spec: SampleSpec) -> Any:
    width, height = (side * spec.supersample for side in spec.canvas)
    image = image_module.new("L", (width, height), spec.background)
    draw = draw_module.Draw(image)
    ink = spec.foreground
    stroke = max(1, 2 * spec.supersample)
    if spec.content == "border":
        inset = 4 * spec.supersample
        draw.rectangle(
            (inset, inset, width - inset - 1, height - inset - 1), outline=ink, width=stroke
        )
        draw.line((inset, height // 2, width - inset, height // 2), fill=ink, width=stroke)
    elif spec.content == "icon":
        _draw_icon(draw, str(spec.graphic), width, height, ink, stroke)
    elif spec.content == "texture":
        image = _texture(image_module, str(spec.graphic), width, height, spec)
    return image


def _draw_icon(draw: Any, name: str, width: int, height: int, ink: int, stroke: int) -> None:
    size = min(width, height) * 0.7
    cx, cy = width / 2, height / 2
    box = (cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    if name == "circle":
        draw.ellipse(box, outline=ink, width=stroke)
    elif name == "star":
        points = [
            (
                cx + (size / 2 if i % 2 == 0 else size / 5) * math.sin(i * math.pi / 5),
                cy - (size / 2 if i % 2 == 0 else size / 5) * math.cos(i * math.pi / 5),
            )
            for i in range(10)
        ]
        draw.polygon(points, fill=ink)
    elif name == "arrow":
        draw.line((box[0], cy, box[2], cy), fill=ink, width=stroke)
        draw.polygon(
            [(box[2], cy), (box[2] - size / 3, box[1]), (box[2] - size / 3, box[3])], fill=ink
        )
    elif name == "check":
        draw.line(
            [(box[0], cy), (cx - size / 8, box[3]), (box[2], box[1])], fill=ink, width=stroke * 2
        )
    else:
        for row in range(3):
            y = box[1] + row * size / 2.5
            draw.rectangle((box[0], y, box[2], y + size / 8), fill=ink)


def _texture(image_module: Any, name: str, width: int, height: int, spec: SampleSpec) -> Any:
    generator = random.Random(spec.seed)
    low, high = sorted((spec.background, spec.foreground))
    pixels = bytearray(width * height)
    period = max(2, 6 * spec.supersample)
    for y in range(height):
        for x in range(width):
            if name == "stripes":
                value = high if (x + y) // period % 2 else low
            elif name == "checker":
                value = high if (x // period + y // period) % 2 else low
            elif name == "gradient":
                value = round(low + (high - low) * x / max(1, width - 1))
            else:
                value = generator.randint(low, high)
            pixels[y * width + x] = value
    return image_module.frombytes("L", (width, height), bytes(pixels))


# -- transforms ---------------------------------------------------------------------------


def _reduce(
    image_module: Any, image: Any, geometry: dict[str, Any], factor: int
) -> tuple[Any, dict[str, Any]]:
    if factor == 1:
        return image, geometry
    size = (max(1, round(image.width / factor)), max(1, round(image.height / factor)))
    return image.resize(size, image_module.LANCZOS), _scaled(geometry, 1 / factor)


def _apply_scale(
    image_module: Any, image: Any, geometry: dict[str, Any], scale: float
) -> tuple[Any, dict[str, Any]]:
    if scale == 1.0:
        return image, geometry
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, image_module.LANCZOS), _scaled(geometry, scale)


def _scaled(geometry: dict[str, Any], factor: float) -> dict[str, Any]:
    return {key: tuple(value * factor for value in values) for key, values in geometry.items()}


def _apply_blur(filter_module: Any, image: Any, spec: SampleSpec) -> Any:
    if spec.blur_radius <= 0:
        return image
    return image.filter(filter_module.GaussianBlur(spec.blur_radius))


def _apply_noise(image_module: Any, image: Any, spec: SampleSpec) -> Any:
    """Seeded Gaussian noise: the same seed always adds the same grain."""

    if spec.noise <= 0:
        return image
    generator = random.Random(spec.seed)
    pixels = bytes(
        min(255, max(0, round(value + generator.gauss(0, spec.noise)))) for value in image.tobytes()
    )
    return image_module.frombytes("L", image.size, pixels)


def _apply_compression(image_module: Any, image: Any, spec: SampleSpec) -> Any:
    """Round-trip through JPEG so the sample carries real compression artefacts."""

    if spec.jpeg_quality is None:
        return image
    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="JPEG", quality=int(spec.jpeg_quality))
    buffer.seek(0)
    with image_module.open(buffer) as compressed:
        return compressed.convert("L").copy()


def _require_legible(image: Any, spec: SampleSpec) -> None:
    extrema = image.getextrema()
    if extrema[0] == extrema[1]:
        raise SyntheticRenderError(f"{spec.case_id!r} rendered as a flat image; nothing was drawn")


# -- identity -----------------------------------------------------------------------------


def _metadata(
    spec: SampleSpec,
    font: ResolvedFont | None,
    style: str | None,
    geometry: dict[str, Any],
    image: Any,
    data: bytes,
) -> dict[str, Any]:
    from PIL import __version__ as pillow_version
    from PIL import features

    pixel_hash = hashlib.sha256(
        f"{image.mode}:{image.width}x{image.height}:".encode() + data
    ).hexdigest()
    line = geometry.get("line_box")
    regions = (
        [{"text": spec.text, **_box(line, image.width, image.height)}]
        if spec.content == "text" and line is not None
        else []
    )
    surface = target_surface(spec)
    metadata: dict[str, Any] = {
        "text": spec.text,
        "tags": list(spec.tags),
        "target_fraction": list(spec.target_fraction) if spec.target_fraction else None,
        "expected_surface": surface,
        "family": spec.family,
        "truth": truth(spec),
        "regions": regions,
        "target_point": list(geometry["target_point"]) if "target_point" in geometry else None,
        "generator": "lab.synthetic_ocr",
        "generator_schema": GENERATOR_VERSION,
        "font_size": spec.font_size,
        "padding": spec.padding,
        "background": spec.background,
        "foreground": spec.foreground,
        "scale": spec.scale,
        "blur_radius": spec.blur_radius,
        "jpeg_quality": spec.jpeg_quality,
        "pillow_version": pillow_version,
    }
    if font is not None:
        metadata.update(
            {
                "font_name": font.spec.name,
                "font_licence": font.spec.licence,
                "font_redistributable": font.redistributable,
                # The file name and hash identify the face; a full path would
                # carry a home directory into any manifest built from it.
                "font_file": font.path.name,
                "font_sha256": font.sha256,
                "font_index": font.spec.index,
            }
        )
    metadata["generation"] = {
        "generator_version": GENERATOR_VERSION,
        "seed": spec.seed,
        "content": spec.content,
        "graphic": spec.graphic,
        "text": spec.text,
        "font": None
        if font is None
        else {
            "name": font.spec.name,
            "style": style,
            "file": font.path.name,
            "sha256": font.sha256,
            "index": font.spec.index,
            "licence": font.spec.licence,
        },
        "renderer": {
            "name": "Pillow",
            "version": pillow_version,
            "freetype": features.version("freetype2"),
            "platform": sys.platform,
        },
        "layout": {
            "font_size": spec.font_size,
            "padding": spec.padding,
            "canvas": list(spec.canvas) if spec.content != "text" else None,
            "line_box": [round(value, 3) for value in line] if line else None,
            "target_index": spec.target_index,
        },
        "colors": {"background": spec.background, "foreground": spec.foreground},
        "rendering": {
            "supersample": spec.supersample,
            "antialias": spec.antialias,
            "post_render_scale": spec.scale,
            "blur_radius": spec.blur_radius,
            "jpeg_quality": spec.jpeg_quality,
            "noise": spec.noise,
        },
        "image": {
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "pixel_sha256": pixel_hash,
        },
    }
    return metadata


def _box(line: Sequence[float], width: int, height: int) -> dict[str, int]:
    return {
        "left": max(0, math.floor(line[0])),
        "top": max(0, math.floor(line[1])),
        "right": min(width, math.ceil(line[2])),
        "bottom": min(height, math.ceil(line[3])),
    }


__all__ = [
    "CONTENTS",
    "DEFAULT_FONT_SEARCH_PATHS",
    "GENERATOR_VERSION",
    "ICONS",
    "REDISTRIBUTABLE_LICENCES",
    "SCRIPT_PROBES",
    "TEXTURES",
    "DiscoveredFace",
    "FontSpec",
    "RenderedSample",
    "ResolvedFont",
    "SampleSpec",
    "SyntheticFontError",
    "SyntheticRenderError",
    "corpus_entry",
    "discover_faces",
    "is_hangul_syllable",
    "load_generator_config",
    "render_sample",
    "resolve_font",
    "target_surface",
    "truth",
    "write_sample",
]
