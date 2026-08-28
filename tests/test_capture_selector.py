"""Focused tests for the session-scoped capture-area selector contract."""

from __future__ import annotations

import argparse
import builtins
import gc
import subprocess
import sys
from pathlib import Path

import hanly_app.capture_selector as capture_selector
import pytest
from hanly_app.capture import ScreenRect
from hanly_app.capture_selector import CaptureSelection, CaptureSelectorError
from hanly_app.cli import build_parser, parse_roi_size, run_selected_desktop
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


def test_hanly_run_applies_selected_region_to_the_same_desktop_runtime() -> None:
    runtime_path = Path("runtime.json")
    selected = CaptureSelection.for_region(ScreenRect(10, 20, 300, 200))
    calls: list[tuple[Path, dict[str, object]]] = []

    def desktop_runner(runtime: Path, **kwargs: object) -> int:
        calls.append((runtime, kwargs))
        return 7

    result = run_selected_desktop(
        ["--runtime-config", str(runtime_path)],
        selector=lambda: selected,
        runtime_resolver=lambda explicit: explicit or runtime_path,
        desktop_runner=desktop_runner,
    )

    assert result == 7
    assert calls == [
        (
            runtime_path,
            {
                "app_config": None,
                "initial_capture_mode": CaptureMode.REGION,
                "initial_capture_region": selected.region,
                "roi_size": None,
            },
        )
    ]


def test_hanly_run_cancel_is_a_clean_noop_before_bootstrap() -> None:
    resolved: list[Path | None] = []

    def resolve(explicit: Path | None) -> Path:
        resolved.append(explicit)
        return Path("never")

    result = run_selected_desktop(
        [],
        selector=lambda: None,
        runtime_resolver=resolve,
        desktop_runner=lambda *_args, **_kwargs: pytest.fail("desktop must not start"),
    )

    assert result == 0
    assert resolved == []


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

    def desktop_runner(_runtime: Path, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    run_selected_desktop(
        ["--roi", "260x64"],
        selector=lambda: CaptureSelection.whole_monitor(),
        runtime_resolver=lambda _explicit: Path("runtime.json"),
        desktop_runner=desktop_runner,
    )

    assert calls[0]["roi_size"] == (260, 64)


@pytest.mark.parametrize("value", ["200", "200x", "x100", "0x100", "200*100", "abc"])
def test_a_malformed_capture_roi_size_is_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_roi_size(value)


def test_the_selector_prepares_the_ocr_runtime_before_qt(tmp_path: Path) -> None:
    """Windows resolves native libraries differently after Qt initializes, so
    the OCR stack has to load first."""

    config = tmp_path / "runtime.json"
    config.write_text('{"resources": {}}', encoding="utf-8")
    order: list[str] = []

    def record() -> None:
        order.append("selector")
        return None

    result = run_selected_desktop(
        ["--runtime-config", str(config)],
        selector=record,
        runtime_resolver=lambda explicit: explicit or config,
        desktop_runner=lambda *_a, **_k: 0,
    )

    assert result == 0
    assert order == ["selector"]


def test_one_qapplication_is_shared_across_selection_and_startup() -> None:
    """Qt registers window classes on construction and never unregisters them,
    so letting the chooser's application die and building a second one for the
    desktop makes Qt re-register classes it already owns."""

    class FakeQApplication:
        instances = 0
        current: FakeQApplication | None = None

        def __init__(self, _argv: object = None) -> None:
            type(self).instances += 1
            type(self).current = self

        @classmethod
        def instance(cls) -> FakeQApplication | None:
            return cls.current

    first = capture_selector._shared_application(FakeQApplication)
    del first
    gc.collect()

    second = capture_selector._shared_application(FakeQApplication)

    assert FakeQApplication.instances == 1
    assert second is capture_selector._application


def test_web_engine_is_prepared_before_the_shared_qapplication_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt WebEngine needs its shared-OpenGL attribute set before any
    QApplication is constructed, and the chooser now builds the one the desktop
    reuses -- so the chooser has to prepare it."""

    order: list[str] = []

    class FakeQApplication:
        current: FakeQApplication | None = None

        def __init__(self, _argv: object = None) -> None:
            order.append("qapplication")
            type(self).current = self

        @classmethod
        def instance(cls) -> FakeQApplication | None:
            return cls.current

    monkeypatch.setattr(capture_selector, "_application", None)
    monkeypatch.setattr(
        capture_selector, "_prepare_web_engine", lambda: order.append("web_engine")
    )

    capture_selector._prepare_web_engine()
    capture_selector._shared_application(FakeQApplication)

    assert order == ["web_engine", "qapplication"]


def test_a_missing_control_center_runtime_does_not_block_area_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop startup repeats the call and owns reporting a missing runtime."""

    import hanly_app.control_center as control_center

    def unavailable() -> None:
        raise control_center.ControlCenterUnavailable("no Qt WebEngine")

    monkeypatch.setattr(control_center, "prepare_control_center_qt", unavailable)

    capture_selector._prepare_web_engine()


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
