"""Render Hanly's macOS icon from its Icon Composer source.

Writes the runtime PNG and the bundle ``.icns``. The purple is the source's
``TintedLight`` rendition with Icon Composer's default tint, rendered once into
static bitmaps so every appearance shows it.

    python design/identity/source/macos/build_macos_icon.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).with_name("Hanly-macOS-v2.icon")
RUNTIME_ICON = ROOT / "packages/hanly-app/src/hanly_app/assets/icons/hanly-macos-icon.png"
BUNDLE_ICON = ROOT / "packaging/icons/hanly.icns"

ICTOOL = Path(
    "/Applications/Xcode.app/Contents/Applications/Icon Composer.app/Contents/Executables/ictool"
)

#: Apple's macOS icon grid: an 824 pt shape centered on a 1024 pt canvas.
CANVAS = 1024
SHAPE = 824

#: ``iconutil`` slot names and their pixel sizes.
ICONSET = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def render_shape(output: Path) -> None:
    subprocess.run(
        [
            str(ICTOOL), str(SOURCE), "--export-image", "--output-file", str(output),
            "--platform", "macOS", "--rendition", "TintedLight",
            "--width", str(SHAPE), "--height", str(SHAPE), "--scale", "1",
            "--design-generation", "27",
        ],
        check=True,
        capture_output=True,
    )


def master_from(shape: Path) -> Image.Image:
    master = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    offset = (CANVAS - SHAPE) // 2
    with Image.open(shape) as rendered:
        master.paste(rendered.convert("RGBA"), (offset, offset))
    return master


def write_icns(master: Image.Image, work: Path) -> None:
    iconset = work / "hanly.iconset"
    iconset.mkdir()
    for name, size in ICONSET.items():
        image = master if size == CANVAS else master.resize((size, size), Image.Resampling.LANCZOS)
        image.save(iconset / name)
    subprocess.run(
        ["iconutil", "--convert", "icns", "--output", str(BUNDLE_ICON), str(iconset)],
        check=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        render_shape(work / "shape.png")
        master = master_from(work / "shape.png")
        master.save(RUNTIME_ICON, optimize=True)
        write_icns(master, work)


if __name__ == "__main__":
    main()
