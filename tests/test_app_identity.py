"""Hanly's name and icon, on every surface that shows them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app import app_icon

ROOT = Path(__file__).parents[1]
TAURI_CONFIG = ROOT / "apps/desktop/src-tauri/tauri.conf.json"


@pytest.mark.parametrize("size", app_icon.ICON_SIZES)
def test_every_packaged_icon_is_the_size_its_name_says(size: int) -> None:
    from PIL import Image

    with Image.open(app_icon.icon_path(size)) as image:
        assert image.size == (size, size)
        assert image.mode == "RGBA"


@pytest.mark.parametrize("size", app_icon.WINDOW_FACE_SIZES)
def test_every_packaged_window_face_is_the_size_its_name_says(size: int) -> None:
    from PIL import Image

    with Image.open(app_icon.window_face_path(size)) as image:
        assert image.size == (size, size)
        assert image.mode == "RGBA"


def test_the_macos_icon_is_the_bundles_artwork_on_apples_icon_grid() -> None:
    from PIL import Image

    with Image.open(app_icon.macos_icon_path()) as image:
        assert image.size == (app_icon.MACOS_ICON_SIZE, app_icon.MACOS_ICON_SIZE)
        assert image.mode == "RGBA"
        runtime = image.copy()
    with Image.open(ROOT / "packaging/icons/hanly.icns") as bundle:
        artwork = bundle.convert("RGBA")

    assert runtime.size == artwork.size
    assert runtime.tobytes() == artwork.tobytes()
    # The 824 px shape centered on the 1024 px canvas, with nothing outside it.
    assert runtime.getchannel("A").getbbox() == (100, 100, 924, 924)


def test_an_unpackaged_size_is_refused_rather_than_scaled() -> None:
    with pytest.raises(ValueError):
        app_icon.icon_path(20)
    with pytest.raises(ValueError):
        app_icon.window_face_path(32)


def test_the_tray_gets_a_drawn_size_not_a_resampled_one() -> None:
    from PIL import Image

    image = app_icon.tray_image()

    size = getattr(image, "size")[0]
    assert size in app_icon.ICON_SIZES
    with Image.open(app_icon.icon_path(size)) as application_icon:
        assert image.tobytes() == application_icon.convert("RGBA").tobytes()


def test_the_native_webview_document_is_titled_hanly_with_its_icon() -> None:
    document = (ROOT / "apps/desktop/index.html").read_text(encoding="utf-8")

    assert "<title>Hanly</title>" in document
    assert 'href="/src/assets/icons/hanly-icon-32.png"' in document


def test_the_native_windows_keep_the_hanly_identity() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))

    assert config["productName"] == "Hanly"
    assert config["version"] == "1.1.0"
    assert config["identifier"] == "io.github.thiagoross1.hanly"
    assert [window["label"] for window in config["app"]["windows"]] == [
        "control-center",
        "popup",
        "region-selector",
    ]
    assert all(window["title"].startswith("Hanly") for window in config["app"]["windows"])


def test_native_and_service_builds_carry_the_official_icons() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    icons = {Path(path).name for path in config["bundle"]["icon"]}
    manifest = (ROOT / "packages/hanly-app/pyproject.toml").read_text(encoding="utf-8")

    assert {"hanly.ico", "hanly.icns"} <= icons
    assert '"assets/icons/*.png"' in manifest
    assert (ROOT / "packaging/icons/hanly.ico").is_file()
    assert (ROOT / "packaging/icons/hanly.icns").is_file()


def test_the_packaged_inventory_requires_the_icons() -> None:
    from tools.smoke_packaged_runtime import REQUIRED_DATA_FILES

    for size in app_icon.ICON_SIZES:
        assert f"hanly_app/assets/icons/hanly-icon-{size}.png" in REQUIRED_DATA_FILES
    for size in app_icon.WINDOW_FACE_SIZES:
        assert f"hanly_app/assets/icons/window-face-{size}.png" in REQUIRED_DATA_FILES
    assert "hanly_app/assets/icons/hanly-macos-icon.png" in REQUIRED_DATA_FILES
    assert "hanly_app/assets/icons/favicon.ico" in REQUIRED_DATA_FILES
