"""Hanly's icon, at the sizes it was drawn for.

The mark is pixel art. Each supplied size is its own drawing or an exact integer
scale of one, so a surface is handed the size nearest what it will show rather
than one image stretched by whatever scaler that surface happens to use.
"""

from __future__ import annotations

import base64
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

#: The name every user-facing surface shows.
APPLICATION_NAME = "Hanly"

#: Every PNG the package carries, in pixels.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

#: The status item is drawn at about 22 points on macOS, the tray icon from a
#: larger source on Windows, where the shell picks its own small-icon size.
_TRAY_SIZE = 24 if sys.platform == "darwin" else 64


def icon_path(size: int) -> Path:
    """The packaged PNG of exactly ``size`` pixels."""

    if size not in ICON_SIZES:
        raise ValueError(f"no {size}px icon is packaged")
    return Path(str(_icons().joinpath(f"hanly-icon-{size}.png")))


def favicon_data_uri() -> str:
    """The Control Center's favicon, inline, because its page is one document."""

    data = _icons().joinpath("favicon.ico").read_bytes()
    return "data:image/x-icon;base64," + base64.b64encode(data).decode("ascii")


def qt_icon() -> Any:
    """A ``QIcon`` holding every drawn size, so Qt never has to invent one."""

    from PyQt6.QtGui import QIcon

    icon = QIcon()
    for size in ICON_SIZES:
        icon.addFile(str(icon_path(size)))
    return icon


def tray_image() -> Any:
    """The status-item image, as the Pillow image the tray backend expects."""

    from PIL import Image

    with Image.open(icon_path(_TRAY_SIZE)) as image:
        return image.convert("RGBA")


def _icons() -> Any:
    return files("hanly_app").joinpath("assets").joinpath("icons")


__all__ = [
    "APPLICATION_NAME",
    "ICON_SIZES",
    "favicon_data_uri",
    "icon_path",
    "qt_icon",
    "tray_image",
]
