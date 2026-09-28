"""The application-wide icon, as a real Qt resolves it on each platform."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hanly_app import app_icon

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication


def _mixed_sources() -> dict[int, Path]:
    faces = {size: app_icon.window_face_path(size) for size in app_icon.WINDOW_FACE_SIZES}
    application = {size: app_icon.icon_path(size) for size in app_icon.ICON_SIZES if size >= 32}
    return {**faces, **application}


def _assert_resolves(icon: QIcon, expected: dict[int, Path]) -> None:
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QImage

    assert sorted(size.width() for size in icon.availableSizes()) == sorted(expected)
    # A pixmap holds premultiplied alpha, so compare both sides in that form.
    premultiplied = QImage.Format.Format_ARGB32_Premultiplied
    for size, source in expected.items():
        drawn = icon.pixmap(QSize(size, size), 1.0).toImage().convertToFormat(premultiplied)
        assert drawn == QImage(str(source)).convertToFormat(premultiplied), size


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_window_icon_is_the_face_below_32_px_and_the_application_icon_above(
    qt_application: QApplication, platform: str
) -> None:
    _assert_resolves(app_icon.qt_icon(platform), _mixed_sources())


def test_macos_is_given_only_its_square_application_icon(
    qt_application: QApplication,
) -> None:
    _assert_resolves(
        app_icon.qt_icon("darwin"), {app_icon.MACOS_ICON_SIZE: app_icon.macos_icon_path()}
    )
