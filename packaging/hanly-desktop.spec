"""Production onedir definition for Hanly Desktop.

Only application code, Python package data, and native runtime dependencies
are collected here. PaddleOCR model directories and the KRDICT database are
external resource artifacts and must be named by ``--runtime-config``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


# PyInstaller executes a spec in a controlled namespace without ``__file__``;
# ``SPECPATH`` is the directory containing this definition.
ROOT = Path(SPECPATH).resolve().parent
APP_SOURCE = ROOT / "packages" / "hanly-app" / "src"
ENGINE_SOURCE = ROOT / "packages" / "hanly" / "src"
ENTRYPOINT = ROOT / "packaging" / "entrypoint.py"
RUNTIME_HOOK = ROOT / "packaging" / "runtime_hook.py"
APPLICATION_STEM = "hanly-desktop"


def _unique(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Preserve collection order while avoiding duplicate source/dest pairs."""

    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


datas = collect_data_files(
    "hanly_app",
    includes=[
        "assets/control_center/*.html",
        "assets/control_center/*.css",
        "assets/control_center/*.js",
    ],
)
if sys.platform == "win32":
    datas.append((str(ROOT / "packaging" / "hanly.cmd"), "."))
binaries: list[tuple[str, str]] = []
hiddenimports = collect_submodules("hanly") + collect_submodules("hanly_app")

for package_name in ("easyocr", "torch", "torchvision", "paddle", "paddleocr", "paddlex"):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    except Exception:
        continue
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

# The GUI and optional desktop adapters are also lazy. Keep this list explicit
# rather than collecting every Qt module (which adds unrelated Designer,
# Multimedia, and QML stacks and makes local analysis needlessly unbounded).
hiddenimports.extend(
    [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "webview.platforms.qt",
        "mss",
    ]
)
if sys.platform == "win32":
    hiddenimports.extend(
        ["pynput.keyboard._win32", "pynput.mouse._win32", "pystray._win32"]
    )
elif sys.platform == "darwin":
    hiddenimports.extend(
        ["pynput.keyboard._darwin", "pynput.mouse._darwin", "pystray._darwin"]
    )
else:
    hiddenimports.extend(
        ["pynput.keyboard._xorg", "pynput.mouse._xorg", "pystray._xorg"]
    )
binaries.extend(collect_dynamic_libs("PyQt6"))

datas = _unique(datas)
binaries = _unique(binaries)
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(ROOT), str(APP_SOURCE), str(ENGINE_SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    runtime_hooks=[str(RUNTIME_HOOK)],
    excludes=["tests", "test", "spikes"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    name=APPLICATION_STEM,
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    name=APPLICATION_STEM,
)
