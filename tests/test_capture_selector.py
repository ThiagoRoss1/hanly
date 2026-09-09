"""Focused tests for the session-scoped capture-area selector contract."""

from __future__ import annotations

import argparse
import builtins
import subprocess
import sys
from pathlib import Path

import hanly_app.capture_selector as capture_selector
import pytest
from hanly_app.capture import ScreenRect
from hanly_app.capture_selector import CaptureSelection, CaptureSelectorError
from hanly_app.cli import build_parser, parse_roi_size, run_hanly
from hanly_app.config import CaptureMode
from hanly_app.control_center import ControlCenterUnavailable
from hanly_app.first_run import FirstRunError
from hanly_app.runtime import RuntimeConfigError


def test_capture_selection_distinguishes_whole_monitor_and_dragged_region() -> None:
    whole = CaptureSelection.whole_monitor()
    region = CaptureSelection.for_region(ScreenRect(-100, 20, 80, 60))

    assert whole.capture_mode is CaptureMode.FULL_MONITOR
    assert whole.region is None
    assert region.capture_mode is CaptureMode.REGION
    assert region.region == ScreenRect(-100, 20, 80, 60)

    with pytest.raises(ValueError, match="region"):
        CaptureSelection(CaptureMode.REGION, None)


def test_hanly_run_starts_the_desktop_without_asking_anything_first() -> None:
    """Launch opens the interface; resources are resolved behind it."""

    runtime_path = Path("runtime.json")
    resolver_calls: list[Path | None] = []
    calls: list[tuple[object, dict[str, object]]] = []

    def resolve(explicit: Path | None) -> Path:
        resolver_calls.append(explicit)
        return runtime_path

    def desktop_runner(runtime: object, **kwargs: object) -> int:
        calls.append((runtime, kwargs))
        return 7

    result = run_hanly(
        ["--runtime-config", str(runtime_path)],
        runtime_resolver=resolve,
        desktop_runner=desktop_runner,
    )

    assert result == 7
    # The desktop, not the command, decides when to resolve and provision.
    assert resolver_calls == []
    runtime, options = calls[0]
    assert runtime == runtime_path
    assert options["app_config"] is None
    assert options["roi_size"] is None
    assert options["runtime_resolver"] is resolve


def test_launching_with_no_arguments_is_the_same_as_run() -> None:
    """The packaged executable is launched by double-clicking it, with no
    arguments at all. That must be the one command, not a second path."""

    args = build_parser().parse_args([])

    assert args.command == "run"
    assert (args.runtime_config, args.app_config, args.roi_size) == (None, None, None)
    assert build_parser().parse_args(["run"]).command == "run"


def test_there_is_no_second_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["desktop"])


def test_hanly_run_forwards_an_explicit_capture_roi_size() -> None:
    calls: list[dict[str, object]] = []

    def desktop_runner(_runtime: object, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    run_hanly(
        ["--roi", "260x64"],
        runtime_resolver=lambda _explicit: Path("runtime.json"),
        desktop_runner=desktop_runner,
    )

    assert calls[0]["roi_size"] == (260, 64)


@pytest.mark.parametrize("value", ["200", "200x", "x100", "0x100", "200*100", "abc"])
def test_a_malformed_capture_roi_size_is_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_roi_size(value)


def test_the_selector_uses_the_one_shared_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selection never builds its own application, before or after startup."""

    order: list[str] = []

    class _FakeApplication:
        def quitOnLastWindowClosed(self) -> bool:
            return True

        def setQuitOnLastWindowClosed(self, _value: bool) -> None:
            return None

    class _FakeMessageBox:
        class ButtonRole:
            AcceptRole = object()
            ActionRole = object()

        class StandardButton:
            Cancel = object()

        def __init__(self) -> None:
            order.append("prompt")
            self.clicked: object = None

        def setWindowTitle(self, _title: str) -> None:
            return None

        def setText(self, _text: str) -> None:
            return None

        def addButton(self, *_arguments: object) -> object:
            self.clicked = object()
            return self.clicked

        def exec(self) -> int:
            return 0

        def clickedButton(self) -> object:
            return self.clicked

    def import_qt_widgets() -> tuple[object, object]:
        order.append("qt_widgets")
        return object(), _FakeMessageBox

    def shared_application(_factory: object) -> _FakeApplication:
        order.append("shared_application")
        return _FakeApplication()

    monkeypatch.setattr(capture_selector, "_import_qt_widgets", import_qt_widgets)
    monkeypatch.setattr(capture_selector, "_shared_application", shared_application)

    assert capture_selector.select_capture_area() is None
    assert order == ["qt_widgets", "shared_application", "prompt"]


def test_a_missing_qt_runtime_during_bootstrap_is_a_selector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely missing Qt runtime is Hanly's error, not a raw RuntimeError."""

    import hanly_app.qt_bootstrap as qt_bootstrap

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise ControlCenterUnavailable("no Qt WebEngine")

    monkeypatch.setattr(qt_bootstrap, "ensure_qt_application", unavailable)

    with pytest.raises(CaptureSelectorError, match="Qt runtime"):
        capture_selector._shared_application(object)


def test_a_missing_qt_runtime_is_a_startup_condition_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt is an optional runtime extra, so its absence must surface as Hanly's
    own error rather than an ImportError from deep inside selection."""

    def missing(_name: str, *_args: object, **_kwargs: object) -> object:
        raise ImportError("No module named 'PyQt6'")

    monkeypatch.setattr(builtins, "__import__", missing)

    with pytest.raises(CaptureSelectorError, match="Qt runtime"):
        capture_selector._import_qt_widgets()


@pytest.mark.parametrize("module", ["hanly_app", "hanly_app.cli"])
def test_every_module_entry_point_is_the_same_command(module: str, tmp_path: Path) -> None:
    """`hanly`, `python -m hanly_app`, and the packaged executable all call one
    function. Each module guard is exercised here so a second entry point
    cannot reappear unnoticed."""

    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("usage: hanly ")


def test_selection_restores_the_application_quit_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaving it off would strand a running desktop with no window."""

    class _FakeApplication:
        def __init__(self) -> None:
            self.quit_on_last = True

        def quitOnLastWindowClosed(self) -> bool:
            return self.quit_on_last

        def setQuitOnLastWindowClosed(self, value: bool) -> None:
            self.quit_on_last = value

    application = _FakeApplication()
    seen: list[bool] = []

    def choose(_application: object, _message_box: object) -> None:
        seen.append(application.quit_on_last)
        return None

    monkeypatch.setattr(
        capture_selector, "_import_qt_widgets", lambda: (object(), object())
    )
    monkeypatch.setattr(capture_selector, "_shared_application", lambda _type: application)
    monkeypatch.setattr(capture_selector, "_choose", choose)

    assert capture_selector.select_capture_area() is None
    assert seen == [False]
    assert application.quit_on_last is True


def test_the_window_self_check_opens_the_shell_without_provisioning_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window opens before resources exist; checking it must not change that."""

    import hanly_app.cli as cli

    resolved: list[Path | None] = []
    checked: list[tuple[object, str]] = []

    def resolve(explicit: Path | None) -> Path:
        resolved.append(explicit)
        return Path("runtime.json")

    def report(runtime_config: object, *, mode: str, image: object = None) -> int:
        checked.append((runtime_config, mode))
        return 0

    monkeypatch.setattr(cli, "report_self_check", report)

    assert (
        run_hanly(
            ["--self-check", "ui"],
            runtime_resolver=resolve,
            desktop_runner=lambda *_args, **_kwargs: 99,
        )
        == 0
    )

    assert resolved == []
    assert checked == [(None, "ui")]


def test_the_worker_self_check_still_gets_a_resolved_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hanly_app.cli as cli

    checked: list[tuple[object, str]] = []

    def report(runtime_config: object, *, mode: str, image: object = None) -> int:
        checked.append((runtime_config, mode))
        return 0

    monkeypatch.setattr(cli, "report_self_check", report)

    run_hanly(
        ["--self-check", "worker"],
        runtime_resolver=lambda _explicit: Path("resolved.json"),
        desktop_runner=lambda *_args, **_kwargs: 99,
    )

    assert checked == [(Path("resolved.json"), "worker")]


def test_the_entry_point_ends_the_process_rather_than_unwinding_into_qt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A desktop the user quit must not be kept alive by WebEngine teardown."""

    import hanly_app.cli as cli

    left: list[int] = []

    def fake_exit(status: int) -> None:
        left.append(status)

    monkeypatch.setattr(cli, "_terminate_without_unloading", lambda _status: None)
    monkeypatch.setattr(cli.os, "_exit", fake_exit)
    monkeypatch.setattr(cli, "run_desktop", lambda *_a, **_k: 7)
    monkeypatch.setattr(cli, "resolve_runtime_config", lambda explicit: Path("runtime.json"))

    cli.main([])

    assert left == [7]


def test_a_startup_failure_still_leaves_with_its_own_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hanly_app.cli as cli

    left: list[int] = []

    def failing(*_args: object, **_kwargs: object) -> int:
        raise RuntimeConfigError("no runtime configuration")

    monkeypatch.setattr(cli, "_terminate_without_unloading", lambda _status: None)
    monkeypatch.setattr(cli.os, "_exit", lambda status: left.append(status))
    monkeypatch.setattr(cli, "run_desktop", failing)
    monkeypatch.setattr(cli, "report_startup_error", lambda *_a, **_k: None)

    cli.main([])

    assert left == [2]


def test_a_failed_self_check_reports_without_waiting_for_anyone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The packaged smoke drives --self-check with nobody at the machine. A
    modal report there held the frozen process open until the harness's
    deadline, turning a two-second failure into a forty-minute one."""

    import hanly_app.cli as cli

    left: list[int] = []
    reported: list[bool] = []

    def failing(*_args: object, **_kwargs: object) -> int:
        raise FirstRunError("Hanly needs its Korean dictionary")

    monkeypatch.setattr(cli, "_terminate_without_unloading", lambda _status: None)
    monkeypatch.setattr(cli.os, "_exit", lambda status: left.append(status))
    monkeypatch.setattr(cli, "resolve_runtime_config", failing)
    monkeypatch.setattr(
        cli,
        "report_startup_error",
        lambda *_a, interactive=True, **_k: reported.append(interactive),
    )

    cli.main(["--self-check", "worker"])

    assert left == [2]
    assert reported == [False]


def test_leaving_terminates_before_it_falls_back_to_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ExitProcess`` runs Chromium's detach handlers; terminating does not."""

    import hanly_app.cli as cli

    order: list[str] = []
    monkeypatch.setattr(
        cli, "_terminate_without_unloading", lambda status: order.append(f"terminate {status}")
    )
    monkeypatch.setattr(cli.os, "_exit", lambda status: order.append(f"exit {status}"))

    cli._leave(3)

    assert order == ["terminate 3", "exit 3"]


def test_only_a_windows_process_is_terminated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every other platform leaves through ``os._exit``, which is enough there."""

    import hanly_app.cli as cli

    monkeypatch.setattr(cli.sys, "platform", "linux")

    cli._terminate_without_unloading(0)
