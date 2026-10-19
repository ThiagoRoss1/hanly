"""Hanly's name and icon, on every surface that shows them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TAURI_CONFIG = ROOT / "apps/desktop/src-tauri/tauri.conf.json"
ICONS = ROOT / "packages/hanly-app/src/hanly_app/assets/icons"


@pytest.mark.parametrize("size", (16, 24, 32, 48, 64, 128, 256, 512))
def test_every_application_icon_is_the_size_its_name_says(size: int) -> None:
    from PIL import Image

    with Image.open(ICONS / f"hanly-icon-{size}.png") as image:
        assert image.size == (size, size)
        assert image.mode == "RGBA"


def test_the_macos_icon_is_the_bundles_artwork_on_apples_icon_grid() -> None:
    """The native root embeds this image as the Dock icon at compile time."""

    from PIL import Image

    with Image.open(ICONS / "hanly-macos-icon.png") as image:
        assert image.size == (1024, 1024)
        assert image.mode == "RGBA"
        runtime = image.copy()
    with Image.open(ROOT / "packaging/icons/hanly.icns") as bundle:
        artwork = bundle.convert("RGBA")

    assert runtime.size == artwork.size
    assert runtime.tobytes() == artwork.tobytes()
    # The 824 px shape centered on the 1024 px canvas, with nothing outside it.
    assert runtime.getchannel("A").getbbox() == (100, 100, 924, 924)


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


def test_the_native_root_carries_the_official_icons() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    icons = [ROOT / "apps/desktop/src-tauri" / path for path in config["bundle"]["icon"]]

    assert {"hanly.ico", "hanly.icns", "hanly-icon-128.png"} <= {path.name for path in icons}
    assert all(path.is_file() for path in icons)
