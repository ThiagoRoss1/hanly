from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from lab.report.model import process_profile
from lab.session.desktop_process import DesktopProcess, desktop_executable, is_debug_executable
from lab.session.recorder import LabRecorder
from lab.session.runner import SessionOptions, _desktop_environment


class _Sampler:
    def register_process(self, _pid: int, _role: str) -> None:
        return None

    def unregister_process(self, _pid: int) -> None:
        return None


def _desktop(tmp_path: Path, recorder: LabRecorder) -> DesktopProcess:
    executable = tmp_path / "hanly-desktop"
    executable.touch()
    return DesktopProcess(
        executable,
        runtime_config=tmp_path / "runtime.json",
        app_config=tmp_path / "profile.json",
        environment={},
        recorder=recorder,
        sampler=_Sampler(),
        repo_root=tmp_path,
    )


def test_trace_reader_forwards_private_evidence_in_memory_only(tmp_path: Path) -> None:
    output = tmp_path / "events.jsonl"
    recorder = LabRecorder(output, retain_evidence=True, retain_geometry=True)
    seen: list[dict[str, Any]] = []
    recorder.subscribe(lambda _name, _stamp, fields: seen.append(dict(fields)))
    desktop = _desktop(tmp_path, recorder)
    secret = "LAB-ONLY-READING-센티널"
    frame = {
        "type": "trace",
        "payload": {
            "event_kind": "lookup_stage_completed",
            "timestamp_ns": 42,
            "stage": "ocr",
            "ocr_evidence": secret,
        },
    }
    desktop.process = cast(
        Any, SimpleNamespace(stdout=io.BytesIO(json.dumps(frame).encode() + b"\n"))
    )

    desktop._read_trace()
    recorder.close()

    assert desktop.trace_lines == 1
    assert seen[0]["ocr_evidence"] == secret
    assert secret not in output.read_text(encoding="utf-8")


def test_trace_reader_keeps_opt_in_capture_frames_separate_from_trace(
    tmp_path: Path,
) -> None:
    recorder = LabRecorder(
        tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False
    )
    traces: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    desktop = _desktop(tmp_path, recorder)
    desktop.trace_consumer = lambda event: traces.append(dict(event))
    desktop.capture_consumer = lambda event: captures.append(dict(event))
    frames = [
        {"type": "trace", "payload": {"event_kind": "popup_visible"}},
        {"type": "lab_capture", "payload": {"image": {"data_base64": "opaque"}}},
    ]
    output = b"".join(json.dumps(frame).encode() + b"\n" for frame in frames)
    desktop.process = cast(Any, SimpleNamespace(stdout=io.BytesIO(output)))

    desktop._read_trace()
    recorder.close()

    assert desktop.trace_lines == 1
    assert desktop.capture_lines == 1
    assert traces == [{"event_kind": "popup_visible"}]
    assert captures == [{"image": {"data_base64": "opaque"}}]


def test_trace_reader_discards_unexpected_and_oversized_output(tmp_path: Path) -> None:
    output = tmp_path / "events.jsonl"
    recorder = LabRecorder(output, retain_evidence=False, retain_geometry=False)
    desktop = _desktop(tmp_path, recorder)
    secret = b"SENTINEL-OUTPUT-MUST-NOT-BE-RECORDED"
    unexpected = json.dumps({"type": "debug", "payload": secret.decode()}).encode() + b"\n"
    oversized = b"{" + b"x" * (1024 * 1024) + secret + b"}\n"
    valid = json.dumps(
        {"type": "trace", "payload": {"event_kind": "hover_started"}}
    ).encode() + b"\n"
    desktop.process = cast(
        Any, SimpleNamespace(stdout=io.BytesIO(unexpected + oversized + valid))
    )

    desktop._read_trace()
    recorder.close()
    contents = output.read_text(encoding="utf-8")

    assert desktop.ignored_output_lines == 1
    assert desktop.invalid_trace_lines == 1
    assert desktop.trace_lines == 1
    assert secret.decode() not in contents


def test_default_binary_resolution_and_debug_identity(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    binary = root / "apps/desktop/src-tauri/target/debug/hanly-desktop"
    binary.parent.mkdir(parents=True)
    binary.touch()

    assert desktop_executable(None, root) == binary.resolve()
    assert is_debug_executable(binary, root)
    assert not is_debug_executable(tmp_path / "release/hanly-desktop", root)


def test_session_environment_isolated_and_lab_opt_in_is_narrow(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "repo"
    binary = root / "apps/desktop/src-tauri/target/debug/hanly-desktop"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setenv("HANLY_DESKTOP_SERVICE_MODULE", "unexpected.module")
    monkeypatch.setenv("HANLY_LAB_RETAIN_EVIDENCE", "1")
    original = dict(os.environ)

    environment = _desktop_environment(
        tmp_path / "isolated-profile", SessionOptions(mode="run"), binary
    )

    assert environment["XDG_CONFIG_HOME"] == str(tmp_path / "isolated-profile")
    assert environment["XDG_DATA_HOME"] == str(tmp_path / "isolated-profile/data")
    assert "HANLY_DESKTOP_SERVICE_MODULE" not in environment
    assert "HANLY_LAB_RETAIN_EVIDENCE" not in environment
    assert os.environ["HANLY_DESKTOP_SERVICE_MODULE"] == original["HANLY_DESKTOP_SERVICE_MODULE"]


def test_tour_environment_opts_into_evidence_only_for_verified_driver(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "repo"
    binary = root / "apps/desktop/src-tauri/target/debug/hanly-desktop"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.delenv("HANLY_DESKTOP_SERVICE_MODULE", raising=False)
    from lab.session import runner

    monkeypatch.setattr(runner, "REPO_ROOT", root)
    environment = _desktop_environment(
        tmp_path / "profile", SessionOptions(mode="tour"), binary
    )

    assert environment["HANLY_DESKTOP_SERVICE_MODULE"] == "lab.service_observer"
    assert environment["HANLY_LAB_RETAIN_EVIDENCE"] == "1"
    assert environment["HANLY_LAB_RETAIN_GEOMETRY"] == "1"


def test_process_sampler_registers_native_root_without_sampling_lab(
    tmp_path: Path,
) -> None:
    from lab.session.sampler import ProcessSampler

    output = tmp_path / "processes.jsonl"
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    sampler = ProcessSampler(output, time.perf_counter_ns(), interval=0.05, sample_parent=False)
    try:
        sampler.start()
        sampler.register_process(child.pid, "shell")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            rows = (
                [json.loads(line) for line in output.read_text().splitlines()]
                if output.exists()
                else []
            )
            if any(
                row.get("pid") == child.pid and row.get("role") == "shell"
                for sample in rows
                for row in sample["processes"]
            ):
                break
            time.sleep(0.05)
    finally:
        sampler.unregister_process(child.pid)
        sampler.stop()
        child.terminate()
        child.wait(timeout=3)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    product_pids = {row["pid"] for sample in rows for row in sample["processes"]}
    assert child.pid in product_pids
    assert os.getpid() not in product_pids


def test_lab_runtime_marker_uses_actual_service_status_without_text(
    monkeypatch: Any,
) -> None:
    import types

    from lab import service_observer

    class TraceSink:
        events: list[dict[str, object]] = []

        def emit(self, event: dict[str, object]) -> None:
            self.events.append(event)

    class Status:
        ready = True
        failed = False

    class Service:
        def __init__(self) -> None:
            self._status = types.SimpleNamespace(status=Status())
            self._trace_sink = TraceSink()
            self._lab_readiness_reported = False

        def _publish_status(self) -> None:
            return None

    server = types.SimpleNamespace(DesktopService=Service, _ProtocolTraceSink=None)
    application = types.SimpleNamespace(DesktopService=Service)
    protocol = types.SimpleNamespace(EVENT_NAMES=frozenset({"state", "trace"}))
    service_package = types.SimpleNamespace(
        application=application, protocol=protocol, server=server
    )

    def emit_trace(sink: TraceSink, name: str) -> None:
        sink.emit({"event_kind": name})

    monkeypatch.setitem(
        sys.modules,
        "hanly_app.runtime_trace",
        types.SimpleNamespace(emit_trace=emit_trace),
    )
    monkeypatch.setitem(sys.modules, "hanly_app.service", service_package)
    monkeypatch.setitem(sys.modules, "hanly_app.service.application", application)
    monkeypatch.setitem(sys.modules, "hanly_app.service.protocol", protocol)
    monkeypatch.setitem(sys.modules, "hanly_app.service.server", server)

    service_observer._instrument_service()
    observed = server.DesktopService()
    observed._publish_status()
    observed._publish_status()

    assert [event["event_kind"] for event in observed._trace_sink.events] == [
        "lab_runtime_ready"
    ]
    assert "lab_capture" in protocol.EVENT_NAMES


def test_macos_responsibility_launcher_compiles_and_probes_on_macos() -> None:
    if sys.platform != "darwin":
        pytest.skip("the responsibility launcher is a macOS-only adapter")

    from lab.session import desktop_process

    command, attribution, directory = desktop_process._macos_launch_command(
        ["/bin/true"]
    )
    if attribution != "macos_responsibility" or directory is None:
        pytest.skip("the compiler or macOS responsibility interface is unavailable")

    try:
        probe = subprocess.run(
            [command[0], "--lab-probe"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
        assert probe.returncode == 0
        assert probe.stdout.strip() == "available"
        assert command[1:] == ["/bin/true"]
    finally:
        directory.cleanup()
        desktop_process._MACOS_LAUNCHER_DIRECTORY = None


def test_process_profile_aggregates_native_host_and_helper_tree() -> None:
    samples = [
        {
            "t_ms": 100,
            "processes": [
                {"pid": 10, "role": "shell", "rss": 10 * 2**20, "cpu": 3, "threads": 2},
                {
                    "pid": 11,
                    "role": "shell.helper",
                    "rss": 20 * 2**20,
                    "cpu": 7,
                    "threads": 4,
                },
                {"pid": 12, "role": "foreign", "rss": 99 * 2**20, "cpu": 99, "threads": 99},
            ],
        }
    ]

    profile = process_profile(samples, [])

    assert profile["summary"]["desktop family"]["rss_mib"] == 30
    assert profile["summary"]["desktop family"]["mean_cpu"] == 10
    assert profile["summary"]["desktop family"]["processes"] == 2
