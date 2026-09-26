"""Hanly's name and icon, on every surface that shows them."""

from __future__ import annotations

from pathlib import Path

import pytest
from hanly_app import app_icon
from hanly_app.control_center import control_center_document
from hanly_app.control_center_host import ControlCenterHost
from hanly_app.window_frame_win32 import FRAME_COLOURS, colorref

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("size", app_icon.ICON_SIZES)
def test_every_packaged_icon_is_the_size_its_name_says(size: int) -> None:
    from PIL import Image

    with Image.open(app_icon.icon_path(size)) as image:
        assert image.size == (size, size)
        assert image.mode == "RGBA"


def test_an_unpackaged_size_is_refused_rather_than_scaled() -> None:
    with pytest.raises(ValueError):
        app_icon.icon_path(20)


def test_the_tray_gets_a_drawn_size_not_a_resampled_one() -> None:
    image = app_icon.tray_image()

    assert getattr(image, "size")[0] in app_icon.ICON_SIZES


def test_the_control_center_is_titled_hanly_with_an_inline_favicon() -> None:
    document = control_center_document()

    assert "<title>Hanly</title>" in document
    assert '<link rel="icon" href="data:image/x-icon;base64,' in document
    assert 'href="favicon.ico"' not in document


def test_the_control_center_window_is_named_hanly() -> None:
    host = ControlCenterHost(object())

    assert getattr(host, "_title") == "Hanly"


def test_windows_colours_are_written_blue_green_red() -> None:
    assert colorref("#1C1D20") == 0x201D1C
    assert colorref("#FAFAF9") == 0xF9FAFA


def test_the_frame_matches_the_pages_own_surface_tokens() -> None:
    css = (
        ROOT / "packages/hanly-app/src/hanly_app/assets/control_center/control_center.css"
    ).read_text(encoding="utf-8")

    assert f"--surface: {FRAME_COLOURS['light'][0]};" in css
    assert f"--surface: {FRAME_COLOURS['dark'][0]};" in css


@pytest.mark.parametrize("mode", [None, "", "sepia", 3, "DARK"])
def test_the_frame_accepts_only_a_rendered_mode(mode: object) -> None:
    assert ControlCenterHost(object()).frame_theme(mode) is False


def test_builds_carry_the_icons_they_are_given() -> None:
    spec = (ROOT / "packaging/hanly-desktop.spec").read_text(encoding="utf-8")
    manifest = (ROOT / "packages/hanly-app/pyproject.toml").read_text(encoding="utf-8")

    assert 'icon=str(ICON_DIRECTORY / "hanly.ico")' in spec
    assert 'icon=str(ICON_DIRECTORY / "hanly.icns")' in spec
    assert '"assets/icons/*.png"' in spec and '"assets/icons/*.png"' in manifest
    assert (ROOT / "packaging/icons/hanly.ico").is_file()
    assert (ROOT / "packaging/icons/hanly.icns").is_file()


def test_the_packaged_inventory_requires_the_icons() -> None:
    from tools.smoke_packaged_runtime import REQUIRED_DATA_FILES

    for size in app_icon.ICON_SIZES:
        assert f"hanly_app/assets/icons/hanly-icon-{size}.png" in REQUIRED_DATA_FILES
    assert "hanly_app/assets/icons/favicon.ico" in REQUIRED_DATA_FILES
