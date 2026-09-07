"""Qt comes up once, in one order, with a program name."""

from __future__ import annotations

import gc

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
    widgets.QApplication = _Recorded  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)
    return _Recorded


def test_the_ocr_runtime_and_web_engine_load_before_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows resolves native libraries differently once Qt has initialized."""

    order: list[str] = []
    monkeypatch.setattr(
        qt_bootstrap, "preload_ocr_runtime", lambda **_kwargs: order.append("ocr")
    )
    monkeypatch.setattr(
        qt_bootstrap, "prepare_control_center_qt", lambda: order.append("web_engine")
    )
    _install_widgets(monkeypatch, order)

    qt_bootstrap.ensure_qt_application()

    assert order == ["ocr", "web_engine", "qapplication"]


def test_the_application_always_gets_a_program_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt WebEngine aborts when Chromium has no argument zero."""

    monkeypatch.setattr(qt_bootstrap, "preload_ocr_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(qt_bootstrap, "prepare_control_center_qt", lambda: None)
    _install_widgets(monkeypatch)

    application = qt_bootstrap.ensure_qt_application([])

    assert application.argv == list(qt_bootstrap.QT_PROGRAM_ARGUMENTS)
    assert application.argv


def test_one_application_survives_its_first_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt registers window classes on construction and never unregisters them,
    so a second application object would re-register classes Qt already owns."""

    monkeypatch.setattr(qt_bootstrap, "preload_ocr_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(qt_bootstrap, "prepare_control_center_qt", lambda: None)
    application_type = _install_widgets(monkeypatch)

    first = qt_bootstrap.ensure_qt_application()
    del first
    gc.collect()

    second = qt_bootstrap.ensure_qt_application()

    assert application_type.instances == 1
    assert second is qt_bootstrap.qt_application()


def test_a_missing_web_engine_is_reported_rather_than_worked_around(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> None:
        raise ControlCenterUnavailable("no Qt WebEngine")

    monkeypatch.setattr(qt_bootstrap, "preload_ocr_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(qt_bootstrap, "prepare_control_center_qt", unavailable)

    with pytest.raises(ControlCenterUnavailable, match="WebEngine"):
        qt_bootstrap.ensure_qt_application()


def test_qt_messages_are_recorded_when_diagnostics_are_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[DiagnosticLog] = []
    monkeypatch.setattr(qt_bootstrap, "preload_ocr_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(qt_bootstrap, "prepare_control_center_qt", lambda: None)
    def install(log: DiagnosticLog) -> bool:
        installed.append(log)
        return True

    monkeypatch.setattr(qt_bootstrap, "install_qt_message_handler", install)
    _install_widgets(monkeypatch)
    log = DiagnosticLog()

    qt_bootstrap.ensure_qt_application(diagnostics=log)

    assert installed == [log]
