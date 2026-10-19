"""Freeze the private Hanly Python service and its lookup runtime.

The native Tauri application owns every window and the user-facing lifecycle.
This is a console-capable child so the Rust supervisor can use bounded private
stdin/stdout JSONL pipes; Windows launch flags hide the console window.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.building.build_main import COLLECT, EXE, PYZ, Analysis
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

_spec_path = globals().get("SPECPATH")
if not isinstance(_spec_path, str):
    raise RuntimeError("PyInstaller did not provide SPECPATH")

ROOT = Path(_spec_path).resolve().parent
APP_SOURCE = ROOT / "packages" / "hanly-app" / "src"
ENGINE_SOURCE = ROOT / "packages" / "hanly" / "src"
ENTRYPOINT = ROOT / "packaging" / "service_entrypoint.py"
RUNTIME_HOOK = ROOT / "packaging" / "runtime_hook.py"
APP_SOURCE_PACKAGE = APP_SOURCE / "hanly_app"
MODEL_DIRECTORY = APP_SOURCE_PACKAGE / "assets" / "easyocr_models"
MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")
MANDATORY_PACKAGES = ("kiwipiepy", "kiwipiepy_model")
MANDATORY_EXTENSION_MODULES = ("_kiwipiepy",)

EXCLUDED_MODULES = (
    "tests",
    "test",
    "pkg_resources",
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt5",
    "PySide2",
    "PySide6",
    "webview",
    "pywebview",
    "pystray",
)


def _unique(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Preserve collection order while removing duplicate source/dest pairs."""

    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


missing_models = [name for name in MODEL_FILES if not (MODEL_DIRECTORY / name).is_file()]
if missing_models:
    raise SystemExit(
        "Hanly packaging: missing EasyOCR weights "
        + ", ".join(missing_models)
        + f" in {MODEL_DIRECTORY}. Run: python tools/prepare_easyocr_models.py"
    )

datas = collect_data_files(
    "hanly_app",
    includes=[
        "assets/easyocr_models/*.pth",
        "assets/hanly-build.json",
    ],
)
datas.extend(collect_data_files("certifi"))

for distribution in ("hanly-app", "hanly", "easyocr"):
    datas.extend(copy_metadata(distribution))

binaries: list[tuple[str, str]] = []
hiddenimports = collect_submodules("hanly")
hiddenimports.extend(collect_submodules("hanly_app.service"))
hiddenimports.extend(collect_submodules("hanly_app.lookup"))
hiddenimports.extend(collect_submodules("hanly_app.acquisition"))
hiddenimports.extend(collect_submodules("hanly_app.updates"))

# EasyOCR loads its own optional backends dynamically. Its hook filters the
# language data to the assets that match the bundled Korean model.
for package_name in ("easyocr", "torchvision"):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    except Exception:
        if package_name == "easyocr":
            raise
        continue
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

for package_name in MANDATORY_PACKAGES:
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
hiddenimports.extend(MANDATORY_EXTENSION_MODULES)
hiddenimports.extend(["mss"])

# Only the mouse observer uses pynput, but its package __init__ imports the
# keyboard module too, which resolves a platform backend at import time.
if sys.platform == "win32":
    hiddenimports.extend(["pynput.keyboard._win32", "pynput.mouse._win32"])
elif sys.platform == "darwin":
    hiddenimports.extend(["pynput.mouse._darwin", "Quartz", "AppKit", "objc"])
else:
    hiddenimports.extend(["pynput.keyboard._xorg", "pynput.mouse._xorg"])

datas = _unique(datas)
binaries = _unique(binaries)
hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(ROOT), str(APP_SOURCE), str(ENGINE_SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hooksconfig={"easyocr": {"lang_codes": ["ko", "en"]}},
    runtime_hooks=[str(RUNTIME_HOOK)],
    excludes=list(EXCLUDED_MODULES),
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    name="hanly-service",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    contents_directory="_internal",
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    name="hanly-service",
)
