"""Render reproducible Korean UI-like samples, or refuse to.

Synthetic text is useful for isolating one variable — size, weight, contrast,
scale — in a way real captures never allow. It is not evidence about how any
real application renders Korean, and a good score here is not a product
accuracy claim.

Two refusals keep it honest. A face that is not installed is never quietly
replaced by whatever the platform would substitute, because a mislabelled font
turns every measurement into a measurement of something else. And a face whose
licence does not permit redistribution can only produce local samples, never
ones committed to Git.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Where a face is looked for when a specification names no explicit path.
DEFAULT_FONT_SEARCH_PATHS = (
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / "Library" / "Fonts",
    Path.home() / ".fonts",
    Path.home() / ".local" / "share" / "fonts",
)

#: Licences under which a rendered sample may be committed to this repository.
REDISTRIBUTABLE_LICENCES = frozenset({"OFL-1.1", "Apache-2.0", "CC0-1.0"})


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
    font: FontSpec
    font_size: int = 20
    padding: int = 12
    background: int = 255
    foreground: int = 0
    #: Rendered at this multiple and resampled down, to imitate UI scaling.
    scale: float = 1.0
    #: JPEG quality applied and undone, to imitate compression artefacts.
    jpeg_quality: int | None = None
    blur_radius: float = 0.0
    tags: tuple[str, ...] = ()
    #: Where the pointer is annotated to sit, as a fraction of the rendered
    #: image. A fraction rather than a pixel because the rendered size depends
    #: on the face, and an annotation has to survive re-rendering.
    target_fraction: tuple[float, float] | None = None
    #: The word the pointer at ``target_fraction`` is expected to select.
    expected_surface: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a synthetic sample needs text")
        if self.font_size < 6:
            raise ValueError("font_size must be at least 6")
        if self.scale <= 0:
            raise ValueError("scale must be positive")


@dataclass(frozen=True)
class RenderedSample:
    """One rendered image plus the metadata that lets it be reproduced."""

    case_id: str
    width: int
    height: int
    mode: str
    data: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


def resolve_font(
    spec: FontSpec, search_paths: tuple[Path, ...] = DEFAULT_FONT_SEARCH_PATHS
) -> ResolvedFont:
    """Find the exact face named, or fail saying what is missing.

    There is deliberately no fallback. A sample rendered in a substituted face
    still looks like Korean text, so a silent fallback would be discovered only
    as an unexplainable difference between two machines' numbers.
    """

    candidates = [spec.path] if spec.path is not None else [
        directory / filename
        for directory in search_paths
        for filename in spec.filenames
    ]
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


def render_sample(
    spec: SampleSpec, search_paths: tuple[Path, ...] = DEFAULT_FONT_SEARCH_PATHS
) -> RenderedSample:
    """Render one sample deterministically, refusing an illegible result."""

    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    font = resolve_font(spec.font, search_paths)
    try:
        face = ImageFont.truetype(str(font.path), spec.font_size, index=spec.font.index)
    except OSError as error:
        raise SyntheticFontError(
            f"{font.path} could not be opened at index {spec.font.index}: {error}"
        ) from error

    _require_glyphs(Image, face, spec)
    image = _draw(Image, ImageDraw, face, spec)
    image = _apply_scale(Image, image, spec)
    image = _apply_blur(ImageFilter, image, spec)
    image = _apply_compression(Image, image, spec)
    _require_legible(image, spec)

    return RenderedSample(
        case_id=spec.case_id,
        width=image.width,
        height=image.height,
        mode=image.mode,
        data=image.tobytes(),
        metadata=_metadata(spec, font, Image),
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

    entry: dict[str, Any] = {
        "id": sample.case_id,
        "image": relative_image,
        "provenance": "committed_synthetic" if redistributable else "local_synthetic",
        "tags": list(sample.metadata.get("tags", ())),
        "expected_text": sample.metadata.get("text"),
        "source": {
            key: value
            for key, value in sample.metadata.items()
            if key not in {"text", "tags", "target_fraction", "expected_surface"}
        },
    }
    fraction = sample.metadata.get("target_fraction")
    if fraction is not None:
        entry["expected_target"] = [
            round(fraction[0] * sample.width, 3),
            round(fraction[1] * sample.height, 3),
        ]
    if sample.metadata.get("expected_surface") is not None:
        entry["expected_surface"] = sample.metadata["expected_surface"]
    return entry


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
    samples = tuple(
        SampleSpec(
            case_id=str(entry["id"]),
            text=str(entry["text"]),
            font=font,
            font_size=int(entry.get("font_size", 20)),
            padding=int(entry.get("padding", 12)),
            background=int(entry.get("background", 255)),
            foreground=int(entry.get("foreground", 0)),
            scale=float(entry.get("scale", 1.0)),
            jpeg_quality=entry.get("jpeg_quality"),
            blur_radius=float(entry.get("blur_radius", 0.0)),
            tags=tuple(entry.get("tags", ())),
            target_fraction=(
                tuple(float(value) for value in entry["target_fraction"])  # type: ignore[arg-type]
                if entry.get("target_fraction")
                else None
            ),
            expected_surface=entry.get("expected_surface"),
        )
        for entry in payload["samples"]
    )
    return font, samples


def _require_glyphs(image_module: Any, face: Any, spec: SampleSpec) -> None:
    """Refuse text the chosen face cannot actually draw.

    Pillow draws a missing glyph as the font's ``.notdef`` box rather than
    failing, and that box has perfectly ordinary dimensions, so a face without
    Hangul coverage would silently produce a row of identical boxes labelled as
    Korean. Comparing each glyph against the box a guaranteed-absent codepoint
    produces is what actually distinguishes them.
    """

    notdef = _glyph_bytes(image_module, face, "\uffff")
    missing = [
        character
        for character in dict.fromkeys(spec.text)
        if not character.isspace()
        and _glyph_bytes(image_module, face, character) == notdef
    ]
    if missing:
        raise SyntheticFontError(
            f"the face {spec.font.name!r} has no glyph for {missing}; it cannot "
            f"render {spec.case_id!r}"
        )


def _glyph_bytes(image_module: Any, face: Any, character: str) -> bytes:
    mask = face.getmask(character, mode="L")
    return image_module.frombytes("L", mask.size, bytes(mask)).tobytes()


def _draw(image_module: Any, draw_module: Any, face: Any, spec: SampleSpec) -> Any:
    left, top, right, bottom = face.getbbox(spec.text)
    width = right - left + spec.padding * 2
    height = bottom - top + spec.padding * 2
    image = image_module.new("L", (width, height), spec.background)
    draw_module.Draw(image).text(
        (spec.padding - left, spec.padding - top),
        spec.text,
        font=face,
        fill=spec.foreground,
    )
    return image


def _apply_scale(image_module: Any, image: Any, spec: SampleSpec) -> Any:
    if spec.scale == 1.0:
        return image
    size = (max(1, round(image.width * spec.scale)), max(1, round(image.height * spec.scale)))
    return image.resize(size, image_module.LANCZOS)


def _apply_blur(filter_module: Any, image: Any, spec: SampleSpec) -> Any:
    if spec.blur_radius <= 0:
        return image
    return image.filter(filter_module.GaussianBlur(spec.blur_radius))


def _apply_compression(image_module: Any, image: Any, spec: SampleSpec) -> Any:
    """Round-trip through JPEG so the sample carries real compression artefacts."""

    if spec.jpeg_quality is None:
        return image
    import io

    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="JPEG", quality=int(spec.jpeg_quality))
    buffer.seek(0)
    with image_module.open(buffer) as compressed:
        return compressed.convert("L").copy()


def _require_legible(image: Any, spec: SampleSpec) -> None:
    extrema = image.getextrema()
    if extrema[0] == extrema[1]:
        raise SyntheticRenderError(
            f"{spec.case_id!r} rendered as a flat image; nothing was drawn"
        )


def _metadata(spec: SampleSpec, font: ResolvedFont, image_module: Any) -> dict[str, Any]:
    return {
        "text": spec.text,
        "tags": list(spec.tags),
        "target_fraction": list(spec.target_fraction) if spec.target_fraction else None,
        "expected_surface": spec.expected_surface,
        "generator": "benchmarks.dev.synthetic_ocr",
        "generator_schema": 1,
        "font_name": font.spec.name,
        "font_licence": font.spec.licence,
        "font_redistributable": font.redistributable,
        "font_path": str(font.path),
        "font_sha256": font.sha256,
        "font_index": font.spec.index,
        "font_size": spec.font_size,
        "padding": spec.padding,
        "background": spec.background,
        "foreground": spec.foreground,
        "scale": spec.scale,
        "blur_radius": spec.blur_radius,
        "jpeg_quality": spec.jpeg_quality,
        "pillow_version": getattr(image_module, "__version__", "unknown"),
    }


__all__ = [
    "DEFAULT_FONT_SEARCH_PATHS",
    "REDISTRIBUTABLE_LICENCES",
    "FontSpec",
    "RenderedSample",
    "ResolvedFont",
    "SampleSpec",
    "SyntheticFontError",
    "SyntheticRenderError",
    "corpus_entry",
    "load_generator_config",
    "render_sample",
    "resolve_font",
    "write_sample",
]
