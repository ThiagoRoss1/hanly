"""Resolve installed Korean raster fonts without requiring a widget toolkit."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont


@dataclass(frozen=True)
class RasterFont:
    """A portable font face that Pillow can load at a requested pixel size."""

    family: str
    path: str
    index: int = 0


def available_fonts(preferences: tuple[str, ...]) -> list[RasterFont]:
    """Return installed preferred Korean faces, preserving preference order."""

    resolved: list[RasterFont] = []
    seen: set[tuple[str, int]] = set()
    for family in preferences:
        face = _resolve(family)
        if face is not None and (face.path, face.index) not in seen:
            resolved.append(face)
            seen.add((face.path, face.index))
    if not resolved:
        fallback = _fontconfig("sans:lang=ko")
        if fallback is not None:
            resolved.append(fallback)
    if not resolved:
        raise RuntimeError(
            "Lab raster pages need a Korean font. Install Apple SD Gothic Neo on macOS, "
            "Malgun Gothic on Windows, or a Korean Noto/Nanum font on Linux."
        )
    return resolved


def load_font(face: RasterFont, pixel_size: int) -> ImageFont.FreeTypeFont:
    """Load a resolved face at its rendered pixel size."""

    return ImageFont.truetype(face.path, max(1, pixel_size), index=face.index)


def _resolve(family: str) -> RasterFont | None:
    if sys.platform == "darwin":
        known = {
            "Apple SD Gothic Neo": ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 0),
            "AppleMyungjo": ("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf", 0),
        }
        candidate = known.get(family)
        if candidate and Path(candidate[0]).is_file():
            return RasterFont(family, *candidate)
        return _fontconfig(family)

    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        known = {
            "Malgun Gothic": ("malgun.ttf", 0),
            "Batang": ("batang.ttc", 0),
            "Gulim": ("gulim.ttc", 0),
            "Dotum": ("dotum.ttc", 0),
            "Gungsuh": ("Gungsuh.ttf", 0),
        }
        candidate = known.get(family)
        if candidate and (fonts / candidate[0]).is_file():
            return RasterFont(family, str(fonts / candidate[0]), candidate[1])
        return None

    return _fontconfig(family)


def _fontconfig(family: str) -> RasterFont | None:
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}\\t%{family}", family],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path, _separator, matched = result.stdout.partition("\t")
    path = path.strip()
    matched = matched.casefold()
    if not path or not Path(path).is_file():
        return None
    # Fontconfig can silently return its generic default for an absent family.
    if "lang=ko" not in family and family.casefold() not in matched:
        return None
    return RasterFont(matched or "Korean fallback", path)


__all__ = ["RasterFont", "available_fonts", "load_font"]
