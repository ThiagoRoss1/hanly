"""Non-interactive contracts for the benchmark command line parser."""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest
from hanly.easyocr_provider import EasyOCRConfig

from benchmarks.dev.cli import _benchmark_ocr_config, _parser


def test_live_hover_parser_has_safe_defaults_and_does_not_import_runner() -> None:
    parser = _parser()

    args = parser.parse_args(
        ["live-hover", "--config", "resources/dev/runtime-local.json"]
    )

    assert args.config == Path("resources/dev/runtime-local.json")
    assert args.duration == 300
    assert args.output_root == Path("artifacts/benchmarks/runs")
    assert args.marker_hotkey == "Ctrl+Alt+Shift+B"
    assert args.retain_text is False
    assert args.dwell_ms == 150.0
    assert args.cpu_threads is None


def test_live_hover_parser_accepts_explicit_privacy_and_session_options() -> None:
    args = _parser().parse_args(
        [
            "live-hover",
            "--config",
            "runtime.json",
            "--duration",
            "120",
            "--output-root",
            "evidence",
            "--marker-hotkey",
            "Ctrl+Alt+M",
            "--retain-text",
            "--dwell-ms",
            "175",
            "--cpu-threads",
            "4",
        ]
    )

    assert args.duration == 120
    assert args.output_root == Path("evidence")
    assert args.marker_hotkey == "Ctrl+Alt+M"
    assert args.retain_text is True
    assert args.dwell_ms == 175.0
    assert args.cpu_threads == 4


def test_benchmark_cpu_thread_override_leaves_other_ocr_options_untouched() -> None:
    args = _parser().parse_args(
        [
            "real-lookup",
            "--image",
            "roi.png",
            "--config",
            "runtime.json",
            "--target-x",
            "1",
            "--target-y",
            "2",
            "--cpu-threads",
            "4",
        ]
    )

    configured = EasyOCRConfig(languages=("ko",), extra_options={"custom": "retained"})
    overridden = _benchmark_ocr_config(configured, args)

    assert overridden.cpu_threads == 4
    assert overridden.languages == ("ko",)
    assert overridden.extra_options == {"custom": "retained"}
    assert configured.cpu_threads is None


@pytest.mark.parametrize("value", ["0", "65", "not-a-number"])
def test_live_hover_parser_rejects_invalid_cpu_thread_limit(value: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["live-hover", "--config", "runtime.json", "--cpu-threads", value]
        )


@pytest.mark.parametrize("duration", ["0", "119", "301", "not-a-duration"])
def test_live_hover_parser_rejects_unbounded_or_invalid_duration(duration: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["live-hover", "--config", "runtime.json", "--duration", duration]
        )


def test_live_hover_help_does_not_import_live_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def reject_live_runner(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "benchmarks.dev.live_runner":
            raise AssertionError("live runner must remain lazy during parser help")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_live_runner)
    with pytest.raises(SystemExit) as result:
        _parser().parse_args(["live-hover", "--help"])
    assert result.value.code == 0


def test_dev_hud_defaults_to_the_normal_configuration_and_shows_the_roi() -> None:
    """`dev-hud` with no flags is the ordinary desktop plus the panel, so it
    must resolve the same per-user configuration `hanly` does."""

    args = _parser().parse_args(["dev-hud"])

    assert args.config is None
    assert args.app_config is None
    assert args.roi_size is None
    assert args.no_roi is False
    assert args.dwell_ms == 80


def test_dev_hud_is_the_first_command_offered() -> None:
    """It is the one a developer reaches for, so it leads the help output."""

    help_text = _parser().format_help()
    commands = help_text[help_text.index("{") + 1 : help_text.index("}")].split(",")

    assert commands[0] == "dev-hud"


def test_the_desktop_accepts_a_trace_sink_without_importing_the_harness() -> None:
    """The HUD attaches through `run_desktop`'s optional sink parameter. The
    application must not know the harness exists."""

    import inspect

    from hanly_app import application

    parameters = inspect.signature(application.run_desktop).parameters

    assert parameters["trace_sink"].default is None
    assert "benchmarks" not in inspect.getsource(application)
