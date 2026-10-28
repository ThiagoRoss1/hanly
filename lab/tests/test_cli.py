"""Non-interactive contracts for the benchmark command line parser."""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest
from hanly.easyocr_provider import EasyOCRConfig

from lab.cli import _benchmark_ocr_config, _ocr_provider_factory, _parser


@pytest.mark.parametrize("threads", [None, 2])
def test_ocr_campaign_constructs_the_product_adapter_once(
    monkeypatch: pytest.MonkeyPatch, threads: int | None,
) -> None:
    constructed: list[EasyOCRConfig] = []
    engine = object()

    class Provider:
        def __init__(self, config: EasyOCRConfig) -> None:
            constructed.append(config)
            self._engine = engine

    monkeypatch.setattr("lab.cli.EasyOCRProvider", Provider)
    arguments = ["ocr-campaign", "--backend", "easyocr"]
    if threads is not None:
        arguments.extend(["--cpu-threads", str(threads)])
    backend, factory, reader = _ocr_provider_factory(_parser().parse_args(arguments))

    assert backend == "easyocr"
    assert reader is not None
    assert reader() is engine
    assert factory() is factory()
    assert len(constructed) == 1
    assert constructed[0].cpu_threads == threads
    assert constructed[0].to_reader_kwargs()["gpu"] is False


def test_live_hover_parser_has_safe_defaults_and_does_not_import_runner() -> None:
    parser = _parser()

    args = parser.parse_args(
        ["live-hover", "--config", "resources/dev/runtime-local.json"]
    )

    assert args.config == Path("resources/dev/runtime-local.json")
    assert args.desktop is None
    assert args.app_config is None
    assert args.duration == 300
    assert args.output_root == Path("artifacts/lab/runs")
    assert args.marker_hotkey == "Ctrl+Alt+Shift+B"
    assert args.freeze_hotkey == "Ctrl+Alt+Shift+F"
    assert args.export_hotkey == "Ctrl+Alt+Shift+E"
    assert args.dwell_ms == 150.0
    assert args.cpu_threads is None


def test_live_hover_parser_accepts_explicit_session_and_microscope_options() -> None:
    args = _parser().parse_args(
        [
            "live-hover",
            "--config",
            "runtime.json",
            "--desktop",
            "native/hanly-desktop",
            "--app-config",
            "preferences.json",
            "--duration",
            "120",
            "--output-root",
            "evidence",
            "--marker-hotkey",
            "Ctrl+Alt+M",
            "--freeze-hotkey",
            "Ctrl+Alt+P",
            "--export-hotkey",
            "Ctrl+Alt+X",
            "--dwell-ms",
            "175",
            "--cpu-threads",
            "4",
        ]
    )

    assert args.duration == 120
    assert args.desktop == Path("native/hanly-desktop")
    assert args.app_config == Path("preferences.json")
    assert args.output_root == Path("evidence")
    assert args.marker_hotkey == "Ctrl+Alt+M"
    assert args.freeze_hotkey == "Ctrl+Alt+P"
    assert args.export_hotkey == "Ctrl+Alt+X"
    assert args.dwell_ms == 175.0
    assert args.cpu_threads == 4


def test_the_live_session_no_longer_offers_a_raw_text_retention_flag() -> None:
    """Raw text reaches disk through an explicit export, not through tracing."""

    with pytest.raises(SystemExit):
        _parser().parse_args(["live-hover", "--config", "runtime.json", "--retain-text"])


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


def test_package_parser_accepts_an_archive_to_measure_beside_the_tree() -> None:
    args = _parser().parse_args(
        [
            "package",
            "--root",
            "dist/app",
            "--output",
            "report.json",
            "--archive",
            "dist/app.zip",
        ]
    )

    assert args.archive == Path("dist/app.zip")


def test_popup_content_command_is_bounded_to_the_language_presentation_scope() -> None:
    args = _parser().parse_args(["popup-content"])

    assert args.dictionary == Path("data/generated/krdict.sqlite3")
    assert args.output_root == Path("artifacts/lab/runs")
    assert "popup-content" in _parser().format_help()


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
        if name == "lab.live_runner":
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


def test_the_lab_commands_lead_the_help() -> None:
    """They are what a developer reaches for; `run --hud` superseded `dev-hud` there."""

    import argparse

    parser = _parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))

    assert list(action.choices)[:3] == ["run", "tour", "report"]
    assert "dev-hud" in action.choices


def test_the_desktop_service_accepts_a_trace_sink_without_importing_the_harness() -> None:
    """Tracing is an opt-in service seam; the product must not import Lab."""

    import inspect

    import hanly_app.service.application as application

    parameters = inspect.signature(application.DesktopService.__init__).parameters

    assert parameters["trace_sink"].default is None
    assert "lab." not in inspect.getsource(application)
