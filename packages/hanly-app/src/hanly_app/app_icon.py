"""Hanly's icons, at the sizes they were drawn for.

Two marks: the application icon, which the executable, Dock, taskbar, Alt+Tab
and tray show, and the mascot's face, which window title bars and the Control
Center favicon show. Both are pixel art, handed out at the size nearest what a
surface will show rather than stretched by whatever scaler that surface uses.
"""

from __future__ import annotations

import base64
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

#: The name every user-facing surface shows.
APPLICATION_NAME = "Hanly"

#: Every application-icon PNG the package carries, in pixels.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

#: Every face PNG the package carries: the title-bar sizes below 32 px. 20 and
#: 24 are area-averaged reductions of the 16 px drawing's exact 16x scale.
WINDOW_FACE_SIZES = (16, 20, 24)

#: Where the window icon stops being the face and becomes the application icon.
_APPLICATION_ICON_FROM = 32

#: The Dock and Cmd+Tab artwork, the same 1024 px image the bundle's icon holds:
#: an 824 px shape on Apple's icon grid, so it sits beside other applications.
MACOS_ICON_SIZE = 1024

#: The status item is drawn at about 22 points on macOS, the tray icon from a
#: larger source on Windows, where the shell picks its own small-icon size.
_TRAY_SIZE = 24 if sys.platform == "darwin" else 64


def icon_path(size: int) -> Path:
    """The packaged PNG of exactly ``size`` pixels."""

    if size not in ICON_SIZES:
        raise ValueError(f"no {size}px icon is packaged")
    return Path(str(_icons().joinpath(f"hanly-icon-{size}.png")))


def window_face_path(size: int) -> Path:
    """The packaged face PNG of exactly ``size`` pixels."""

    if size not in WINDOW_FACE_SIZES:
        raise ValueError(f"no {size}px window face is packaged")
    return Path(str(_icons().joinpath(f"window-face-{size}.png")))


def macos_icon_path() -> Path:
    """The packaged macOS application icon, square treatment included."""

    return Path(str(_icons().joinpath("hanly-macos-icon.png")))


def favicon_data_uri() -> str:
    """The Control Center's favicon, inline, because its page is one document."""

    data = _icons().joinpath("favicon.ico").read_bytes()
    return "data:image/x-icon;base64," + base64.b64encode(data).decode("ascii")


def qt_icon(platform: str = sys.platform) -> Any:
    """The application-wide ``QIcon`` for ``platform``.

    macOS shows it only in the Dock and Cmd+Tab, which expect the square
    treatment the bundle carries. Elsewhere it is the face below 32 px for title
    bars and the application icon from 32 px up for the taskbar and Alt+Tab; at
    200% scaling a title bar asks for 32 physical pixels and so shows the latter.
    """

    from PyQt6.QtGui import QIcon

    icon = QIcon()
    if platform == "darwin":
        icon.addFile(str(macos_icon_path()))
        return icon
    for size in WINDOW_FACE_SIZES:
        icon.addFile(str(window_face_path(size)))
    for size in ICON_SIZES:
        if size >= _APPLICATION_ICON_FROM:
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
    "MACOS_ICON_SIZE",
    "WINDOW_FACE_SIZES",
    "favicon_data_uri",
    "icon_path",
    "macos_icon_path",
    "qt_icon",
    "tray_image",
    "window_face_path",
]
