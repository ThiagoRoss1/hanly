"""The application-wide window icon, as a real Qt resolves each size of it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hanly_app import app_icon

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication


def _expected_sources() -> dict[int, Path]:
    faces = {size: app_icon.window_face_path(size) for size in app_icon.WINDOW_FACE_SIZES}
    application = {size: app_icon.icon_path(size) for size in app_icon.ICON_SIZES if size >= 32}
    return {**faces, **application}


def test_the_window_icon_is_the_face_below_32_px_and_the_application_icon_above(
    qt_application: QApplication,
) -> None:
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QImage

    icon = app_icon.qt_icon()
    expected = _expected_sources()

    assert sorted(size.width() for size in icon.availableSizes()) == sorted(expected)
    # A pixmap holds premultiplied alpha, so compare both sides in that form.
    premultiplied = QImage.Format.Format_ARGB32_Premultiplied
    for size, source in expected.items():
        drawn = icon.pixmap(QSize(size, size), 1.0).toImage().convertToFormat(premultiplied)
        assert drawn == QImage(str(source)).convertToFormat(premultiplied), size
