"""Hanly's Qt palette, shared by every window the shell draws itself.

The popup and Hanly's dialogs read the same tokens, so a palette change is made
here once. The Control Center is a web page with tokens of its own, kept to the
same values by hand.
"""

from __future__ import annotations

from typing import cast

from .config import Theme

PALETTES = {
    "light": {
        "bg": "#FFFFFF",
        "foot": "#F5F4F2",
        "border": "#D3D1CE",
        "line": "#E7E5E3",
        "wash": "#F1F0EE",
        "ink": "#202124",
        "ink2": "#5F6268",
        "ink3": "#85888F",
        "accent": "#E88CA1",
        "accent_ink": "#B75C76",
        "on_accent": "#202124",
        "accent_wash": "rgba(232, 140, 161, 41)",
        "accent_hover": "rgba(232, 140, 161, 66)",
        "hover": "#E7E5E3",
        "press": "#DAD8D5",
        "scroll": "rgba(32, 33, 36, 46)",
        "scroll_hover": "rgba(32, 33, 36, 92)",
        "danger": "#A0302A",
    },
    "dark": {
        "bg": "#232428",
        "foot": "#1C1D20",
        "border": "#3A3C41",
        "line": "#2F3135",
        "wash": "#292A2E",
        "ink": "#F2F2F3",
        "ink2": "#B8BAC0",
        "ink3": "#858890",
        "accent": "#F08FA6",
        "accent_ink": "#F4A5B6",
        "on_accent": "#171719",
        "accent_wash": "rgba(240, 143, 166, 36)",
        "accent_hover": "rgba(240, 143, 166, 64)",
        "hover": "#32343A",
        "press": "#3A3D44",
        "scroll": "rgba(242, 242, 243, 48)",
        "scroll_hover": "rgba(242, 242, 243, 104)",
        "danger": "#F09086",
    },
}


def resolved_mode(theme: Theme) -> str:
    """``"light"`` or ``"dark"``: a stored ``system`` preference, resolved now."""

    if theme is not Theme.SYSTEM:
        return theme.value

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication, QPalette

    app = cast(QGuiApplication | None, QGuiApplication.instance())
    if app is not None:
        scheme = getattr(app.styleHints(), "colorScheme", lambda: None)()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
        if app.palette().color(QPalette.ColorRole.Window).lightness() < 128:
            return "dark"
    return "light"


__all__ = ["PALETTES", "resolved_mode"]
