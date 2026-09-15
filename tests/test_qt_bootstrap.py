"""Qt comes up once, with a program name, and carries nothing heavy with it."""

from __future__ import annotations

import gc
import sys
from pathlib import Path
from typing import Any

import hanly_app.qt_bootstrap as qt_bootstrap
import pytest
from hanly_app.control_center import ControlCenterUnavailable
from hanly_app.diagnostics import DiagnosticLog


class _FakeApplication:
    """Enough of ``QApplication`` for the bootstrap's own contract."""

    instances = 0
    current: _FakeApplication | None = None

    def __init__(self, argv: list[str]) -> None:
        type(self).instances += 1
        type(self).current = self
        self.argv = argv

    @classmethod
    def instance(cls) -> _FakeApplication | None:
        return cls.current

    @classmethod
    def reset(cls) -> None:
        cls.instances = 0
        cls.current = None


@pytest.fixture(autouse=True)
def _isolated_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the real Qt runtime, and never leak a cached application."""

    _FakeApplication.reset()
    monkeypatch.setattr(qt_bootstrap, "_application", None)
    monkeypatch.setattr(qt_bootstrap, "install_qt_message_handler", lambda _log: True)


#: What the shell must never pull in. Qt WebEngine belongs to the Control
#: Center child and the OCR runtime to the lookup child; either one imported
#: here would put hundreds of megabytes back into the process that never exits.
HEAVY_MODULES = ("PyQt6.QtWebEngineWidgets", "easyocr", "torch", "kiwipiepy")


def test_the_shell_bootstrap_imports_neither_web_engine_nor_the_ocr_runtime() -> None:
    source = Path(qt_bootstrap.__file__).read_text(encoding="utf-8")

    assert "preload_ocr_runtime" not in source
    assert "prepare_control_center_qt" not in source


def _install_widgets(
    monkeypatch: pytest.MonkeyPatch, order: list[str] | None = None
) -> type[_FakeApplication]:
    """Substitute the Qt widgets module and return the application class used."""

    import sys
    import types

    class _Recorded(_FakeApplication):
        def __init__(self, argv: list[str]) -> None:
            if order is not None:
                order.append("qapplication")
            super().__init__(argv)

    _Recorded.reset()
    widgets = types.ModuleType("PyQt6.QtWidgets")
    setattr(widgets, "QApplication", _Recorded)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)
    return _Recorded


def test_the_application_always_gets_a_program_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt WebEngine aborts when Chromium has no argument zero, and the Control
    Center child creates its application through this same function."""

    _install_widgets(monkeypatch)

    application = qt_bootstrap.ensure_qt_application([])

    assert application.argv == list(qt_bootstrap.QT_PROGRAM_ARGUMENTS)
    assert application.argv


def test_one_application_survives_its_first_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt registers window classes on construction and never unregisters them,
    so a second application object would re-register classes Qt already owns."""

    application_type = _install_widgets(monkeypatch)

    first = qt_bootstrap.ensure_qt_application()
    del first
    gc.collect()

    second = qt_bootstrap.ensure_qt_application()

    assert application_type.instances == 1
    assert second is qt_bootstrap.qt_application()


def test_a_missing_qt_runtime_is_reported_rather_than_worked_around(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *arguments: Any, **keywords: Any) -> object:
        if name == "PyQt6.QtWidgets":
            raise ImportError("no Qt")
        return real_import(name, *arguments, **keywords)

    monkeypatch.delitem(sys.modules, "PyQt6.QtWidgets", raising=False)
    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(ControlCenterUnavailable, match="Qt6"):
        qt_bootstrap.ensure_qt_application()


def test_qt_messages_are_recorded_when_diagnostics_are_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[DiagnosticLog] = []

    def install(log: DiagnosticLog) -> bool:
        installed.append(log)
        return True

    monkeypatch.setattr(qt_bootstrap, "install_qt_message_handler", install)
    _install_widgets(monkeypatch)
    log = DiagnosticLog()

    qt_bootstrap.ensure_qt_application(diagnostics=log)

    assert installed == [log]


def _linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qt_bootstrap.sys, "platform", "linux")


def _unloadable_plugin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A file with the plugin's name that the dynamic loader will refuse."""

    plugin = tmp_path / qt_bootstrap.XCB_PLUGIN_FILE
    plugin.write_text("not a shared library", encoding="utf-8")
    monkeypatch.setattr(qt_bootstrap, "_xcb_plugin_path", lambda: plugin)
    return plugin


def test_an_unloadable_xcb_plugin_raises_where_qt_would_abort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Qt calls qFatal on a platform plugin it cannot load, and SIGABRT is not
    an exception any caller can catch or any report can survive."""

    _linux(monkeypatch)
    _unloadable_plugin(monkeypatch, tmp_path)

    with pytest.raises(ControlCenterUnavailable, match="libxkbcommon-x11-0"):
        qt_bootstrap.verify_platform_plugin({"DISPLAY": ":0"})


def test_a_linux_session_without_a_display_is_reported_before_qt_sees_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _linux(monkeypatch)

    with pytest.raises(ControlCenterUnavailable, match="DISPLAY"):
        qt_bootstrap.verify_platform_plugin({})


@pytest.mark.parametrize(
    "environment",
    [
        {"QT_QPA_PLATFORM": "offscreen"},
        {"QT_QPA_PLATFORM": "wayland;xcb", "DISPLAY": ":0"},
        {"WAYLAND_DISPLAY": "wayland-0"},
    ],
)
def test_only_the_plugin_qt_will_actually_load_is_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, environment: dict[str, str]
) -> None:
    """The xcb dependencies are irrelevant to a session Qt will not open with
    xcb, and a headless check must not be failed by a display it never wanted."""

    _linux(monkeypatch)
    _unloadable_plugin(monkeypatch, tmp_path)

    qt_bootstrap.verify_platform_plugin(environment)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_no_other_platform_pays_for_the_linux_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    """Windows and macOS link their platform plugin against the operating
    system, so there is nothing outside the bundle for them to be missing."""

    monkeypatch.setattr(qt_bootstrap.sys, "platform", platform)

    def refuse() -> Path:
        raise AssertionError("the platform plugin is only checked on Linux")

    monkeypatch.setattr(qt_bootstrap, "_xcb_plugin_path", refuse)

    qt_bootstrap.verify_platform_plugin({})


def test_the_platform_plugin_is_checked_before_the_application_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After construction the check is worthless: the abort has already
    happened."""

    order: list[str] = []
    _install_widgets(monkeypatch, order)
    monkeypatch.setattr(
        qt_bootstrap, "verify_platform_plugin", lambda: order.append("verify")
    )

    qt_bootstrap.ensure_qt_application()

    assert order == ["verify", "qapplication"]


def test_a_session_with_no_screen_is_reported_rather_than_reached_into() -> None:
    """pywebview reads the primary screen's geometry while creating its window
    and never checks that there is one, so the failure arrives from inside that
    library with Qt's fatal "no screens available" above it."""

    with pytest.raises(ControlCenterUnavailable, match="no usable screen"):
        qt_bootstrap.verify_primary_screen(lambda: None)


def test_an_ordinary_screen_is_accepted_without_comment() -> None:
    qt_bootstrap.verify_primary_screen(lambda: object())
