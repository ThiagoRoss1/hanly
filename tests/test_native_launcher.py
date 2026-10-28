"""Pure capture-selection data and the supported native launcher contract."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from hanly_app.acquisition.capture import ScreenRect
from hanly_app.acquisition.selection import CaptureSelection
from hanly_app.cli import (
    build_parser,
    launch_native_desktop,
    main,
    parse_roi_size,
    run_hanly,
)
from hanly_app.config import CaptureMode


def test_capture_selection_distinguishes_whole_monitor_and_dragged_region() -> None:
    whole = CaptureSelection.whole_monitor()
    region = CaptureSelection.for_region(ScreenRect(-100, 20, 80, 60))

    assert whole.capture_mode is CaptureMode.FULL_MONITOR
    assert whole.region is None
    assert region.capture_mode is CaptureMode.REGION
    assert region.region == ScreenRect(-100, 20, 80, 60)

    with pytest.raises(ValueError, match="region"):
        CaptureSelection(CaptureMode.REGION, None)


def test_launcher_forwards_supported_config_and_roi_arguments() -> None:
    executable = Path("/opt/hanly/hanly-desktop")
    calls: list[tuple[Path, list[str]]] = []

    def native_runner(path: Path, arguments: Sequence[str]) -> int:
        calls.append((path, list(arguments)))
        return 7

    result = run_hanly(
        ["--runtime-config", "runtime.json", "--roi", "260x64"],
        executable_resolver=lambda: executable,
        native_runner=native_runner,
    )

    assert result == 7
    assert calls == [
        (
            executable,
            ["--runtime-config", str(Path("runtime.json").resolve()), "--roi", "260x64"],
        )
    ]


def test_an_update_relaunch_reaches_the_native_root_through_the_one_entry_point() -> None:
    calls: list[list[str]] = []

    def native_runner(_executable: Path, arguments: Sequence[str]) -> int:
        calls.append(list(arguments))
        return 0

    run_hanly(
        ["--update-ready", "/tmp/transaction/ready", "--update-ready-v2", "/tmp/tx.json"],
        executable_resolver=lambda: Path("/opt/hanly/hanly-desktop"),
        native_runner=native_runner,
    )

    assert calls[0] == [
        "--update-ready",
        str(Path("/tmp/transaction/ready").resolve()),
        "--update-ready-v2",
        str(Path("/tmp/tx.json").resolve()),
    ]
    assert build_parser().parse_args([]).update_ready is None


def test_launching_without_arguments_is_the_only_command() -> None:
    args = build_parser().parse_args([])

    assert args.command == "run"
    assert (args.runtime_config, args.app_config, args.roi_size) == (None, None, None)
    assert build_parser().parse_args(["run"]).command == "run"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["desktop"])


@pytest.mark.parametrize("value", ["200", "200x", "x100", "0x100", "200*100", "abc"])
def test_malformed_capture_roi_size_is_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_roi_size(value)


@pytest.mark.parametrize("mode", ("inventory", "ocr", "worker", "ui"))
def test_self_check_modes_are_forwarded_to_the_native_root(mode: str) -> None:
    calls: list[list[str]] = []

    def native_runner(_path: Path, arguments: Sequence[str]) -> int:
        calls.append(list(arguments))
        return 0

    run_hanly(
        ["--self-check", mode, "--self-check-image", "sample.png"],
        executable_resolver=lambda: Path("/opt/hanly/hanly-desktop"),
        native_runner=native_runner,
    )

    assert calls == [
        ["--self-check", mode, "--self-check-image", str(Path("sample.png").resolve())]
    ]


def test_launcher_uses_an_existing_native_executable_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hanly_app.cli as cli

    executable = tmp_path / "hanly-desktop"
    executable.write_bytes(b"native binary")
    monkeypatch.setenv(cli.NATIVE_EXECUTABLE_VARIABLE, str(executable))

    assert cli.resolve_native_executable() == executable


def test_launcher_rejects_a_missing_native_executable_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hanly_app.cli as cli

    monkeypatch.setenv(cli.NATIVE_EXECUTABLE_VARIABLE, str(tmp_path / "missing"))

    with pytest.raises(FileNotFoundError, match=cli.NATIVE_EXECUTABLE_VARIABLE):
        cli.resolve_native_executable()


def test_source_launcher_resolves_the_existing_tauri_debug_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hanly_app.cli as cli

    source = tmp_path / "packages" / "hanly-app" / "src" / "hanly_app" / "cli.py"
    source.parent.mkdir(parents=True)
    source.write_text("", encoding="utf-8")
    native_name = "hanly-desktop.exe" if cli.sys.platform == "win32" else "hanly-desktop"
    executable = (
        tmp_path
        / "apps"
        / "desktop"
        / "src-tauri"
        / "target"
        / "debug"
        / native_name
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native binary")
    monkeypatch.setattr(cli, "__file__", str(source))
    monkeypatch.delenv(cli.NATIVE_EXECUTABLE_VARIABLE, raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)

    assert cli.resolve_native_executable() == executable


def test_posix_launcher_replaces_itself_with_the_native_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hanly_app.cli as cli

    calls: list[tuple[str, list[str]]] = []

    class ExecCalled(Exception):
        pass

    def execv(path: str, argv: list[str]) -> None:
        calls.append((path, argv))
        raise ExecCalled

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.os, "execv", execv)
    executable = Path("/Applications/Hanly.app/Contents/MacOS/hanly-desktop")

    with pytest.raises(ExecCalled):
        launch_native_desktop(executable, ["--self-check", "ui"])

    assert calls == [(str(executable), [str(executable), "--self-check", "ui"])]


def test_windows_launcher_waits_for_and_returns_native_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hanly_app.cli as cli

    calls: list[list[str]] = []

    def run(command: list[str], *, check: bool) -> object:
        assert check is False
        calls.append(command)
        return type("Completed", (), {"returncode": 9})()

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.subprocess, "run", run)
    executable = Path("C:/Hanly/hanly-desktop.exe")

    assert launch_native_desktop(executable, ["--self-check", "ui"]) == 9
    assert calls == [[str(executable), "--self-check", "ui"]]


def test_ctrl_c_exits_without_printing_a_keyboard_interrupt_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import hanly_app.cli as cli

    calls: list[str] = []

    def interrupt(_argv: Sequence[str] | None = None) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.multiprocessing, "freeze_support", lambda: calls.append("freeze"))
    monkeypatch.setattr(cli, "run_hanly", interrupt)

    assert main([]) == 130
    assert calls == ["freeze"]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("module", ["hanly_app", "hanly_app.cli"])
def test_every_module_entry_point_is_the_same_command(module: str, tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("usage: hanly ")


def test_cli_import_does_not_load_qt_or_the_legacy_application() -> None:
    script = (
        "import sys, hanly_app.cli; "
        "assert not any(name.startswith(('PyQt6', 'PySide6')) for name in sys.modules); "
        "assert 'hanly_app.application' not in sys.modules; "
        "assert 'hanly_app.control_center.bridge' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
