"""Production application definition for Hanly Desktop.

Windows and Linux collect a onedir tree; macOS wraps the same collection in a
``Hanly.app`` bundle, which is the unit macOS installs, signs, and updates.

Only application code, Python package data, and native runtime dependencies
are collected here, plus the two files a frozen build cannot fetch for itself:
the certifi trust store and the EasyOCR weights. The KRDICT database is an
external resource artifact and must be named by ``--runtime-config``.
"""

from __future__ import annotations

import sys
from importlib.metadata import version
from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.building.osx import BUNDLE
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)


# PyInstaller executes a spec in a controlled namespace without ``__file__``;
# ``SPECPATH`` is the directory containing this definition.
ROOT = Path(SPECPATH).resolve().parent
APP_SOURCE = ROOT / "packages" / "hanly-app" / "src"
ENGINE_SOURCE = ROOT / "packages" / "hanly" / "src"
ENTRYPOINT = ROOT / "packaging" / "entrypoint.py"
RUNTIME_HOOK = ROOT / "packaging" / "runtime_hook.py"
APPLICATION_STEM = "hanly-desktop"

#: The macOS product. The executable inside it keeps the cross-platform stem,
#: so ``Hanly.app/Contents/MacOS/hanly-desktop`` is the one program everywhere.
BUNDLE_NAME = "Hanly.app"
BUNDLE_DISPLAY_NAME = "Hanly"
BUNDLE_IDENTIFIER = "io.github.thiagoross1.hanly"

#: The weights a frozen build loads; it cannot download them.
MODEL_DIRECTORY = APP_SOURCE / "hanly_app" / "assets" / "easyocr_models"
MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")

MANDATORY_PACKAGES = ("kiwipiepy", "kiwipiepy_model")

MANDATORY_EXTENSION_MODULES = ("_kiwipiepy",)

EXCLUDED_MODULES = ("tests", "test", "pkg_resources")

#: QtWebEngine ships one Chromium string catalogue per locale, and its hook
#: collects the whole directory. The Control Center is app-authored HTML, so
#: the only Qt-supplied text a user can reach is Chromium's own - context menus
#: and error pages - and Hanly presents that in English or Korean.
WEBENGINE_LOCALE_DIRECTORY = "qtwebengine_locales"
KEPT_WEBENGINE_LOCALES = ("en-US.pak", "ko.pak")


def _unique(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Preserve collection order while avoiding duplicate source/dest pairs."""

    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _without_unused_webengine_locales(
    collected: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Keep only the Chromium string catalogues Hanly can actually present.

    Applied to the analysis result rather than the inputs above, because the
    locales are collected by QtWebEngine's own hook while it runs.
    """

    return [
        entry
        for entry in collected
        if WEBENGINE_LOCALE_DIRECTORY not in Path(entry[0]).parts
        or Path(entry[0]).name in KEPT_WEBENGINE_LOCALES
    ]


def _without_qt_translation_catalogues(
    collected: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Drop the ``.qm`` catalogues, which nothing in this application loads.

    Qt translates only through a ``QTranslator`` the application installs, and
    neither Hanly nor pywebview nor pystray installs one, so every Qt-supplied
    string already renders untranslated. This removes the files, not a
    behaviour. Matching the suffix leaves ``qtwebengine_locales`` alone, which
    on Windows and Linux sits inside the same ``translations`` directory.
    """

    return [entry for entry in collected if not entry[0].endswith(".qm")]


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
        "assets/control_center/*.html",
        "assets/control_center/*.css",
        "assets/control_center/*.js",
        "assets/easyocr_models/*.pth",
    ],
)

datas.extend(collect_data_files("certifi"))

for distribution in ("hanly-app", "hanly", "easyocr"):
    datas.extend(copy_metadata(distribution))

for distribution in ("PyQt6", "PyQt6-WebEngine", "pywebview", "pystray"):
    try:
        datas.extend(copy_metadata(distribution))
    except Exception:
        continue

binaries: list[tuple[str, str]] = []
hiddenimports = collect_submodules("hanly") + collect_submodules("hanly_app")

# EasyOCR is left to its own hook, constrained below to the languages Hanly's
# recognition model accepts; the app supplies the two model weights explicitly
# above. torchvision is still collected whole: a measured removal dropped its
# native modules for about a megabyte of download.
for package_name in ("torchvision",):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    except Exception:
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

# The GUI and optional desktop adapters are also lazy. Keep this list explicit
# rather than collecting every Qt module: naming them is what keeps unrelated
# Qt bindings out and local analysis bounded. It does not keep the QML and
# multimedia trees out - QtWebEngine's own hook brings those in regardless.
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
    # Carbon owns keyboard shortcuts on macOS; pynput remains only for hover.
    hiddenimports.extend(["pynput.mouse._darwin", "pystray._darwin"])
else:
    hiddenimports.extend(
        ["pynput.keyboard._xorg", "pynput.mouse._xorg", "pystray._xorg"]
    )

datas = _unique(datas)
binaries = _unique(binaries)
hiddenimports = sorted(set(hiddenimports))


APPLICATION_VERSION = version("hanly-app")

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(ROOT), str(APP_SOURCE), str(ENGINE_SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # EasyOCR's hook otherwise collects character data for every language it
    # supports. ``korean_g2`` accepts Korean and English, and ``easyocr``
    # configuration may name either, so both stay and the other 99 do not.
    hooksconfig={"easyocr": {"lang_codes": ["ko", "en"]}},
    runtime_hooks=[str(RUNTIME_HOOK)],
    excludes=list(EXCLUDED_MODULES),
    noarchive=False,
)
a.datas = _without_unused_webengine_locales(a.datas)
a.datas = _without_qt_translation_catalogues(a.datas)

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
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    name=APPLICATION_STEM,
)
if sys.platform == "darwin":
    BUNDLE(
        coll,
        name=BUNDLE_NAME,
        bundle_identifier=BUNDLE_IDENTIFIER,
        version=APPLICATION_VERSION,
        info_plist={
            "CFBundleName": BUNDLE_DISPLAY_NAME,
            "CFBundleDisplayName": BUNDLE_DISPLAY_NAME,
            "CFBundleShortVersionString": APPLICATION_VERSION,
            "CFBundleVersion": APPLICATION_VERSION,
            "NSHighResolutionCapable": True,
            "LSBackgroundOnly": False,
        },
    )
