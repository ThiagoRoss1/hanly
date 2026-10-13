"""Launch and observe the native Hanly desktop as a Lab-owned child."""

from __future__ import annotations

import json
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

import psutil

MAX_TRACE_LINE_BYTES = 1_048_576
_MACOS_LAUNCHER_DIRECTORY: tempfile.TemporaryDirectory[str] | None = None


class DesktopRecorder(Protocol):
    """The subset of recorder behavior needed by the native process owner."""

    def lab(self, event: str, /, **fields: Any) -> object: ...

    def emit(self, event: Mapping[str, Any]) -> object: ...


def desktop_executable(explicit: Path | None, repo_root: Path) -> Path:
    """Resolve a debug binary or explicit packaged app without invoking a shell."""

    if explicit is not None:
        path = explicit.expanduser().resolve()
        if path.is_dir():
            candidates = _bundle_candidates(path)
            if path.suffix != ".app" and sys.platform == "win32":
                candidates.insert(0, path / "hanly-desktop.exe")
            elif path.suffix != ".app":
                candidates.insert(0, path / _binary_name())
            for candidate in candidates:
                if candidate.is_file():
                    return candidate.resolve()
            raise FileNotFoundError("the selected Hanly app has no desktop executable")
        if not path.is_file():
            raise FileNotFoundError("the selected Hanly desktop executable does not exist")
        return path

    target = repo_root / "apps" / "desktop" / "src-tauri" / "target"
    candidates = [
        target / "debug" / _binary_name(),
        target
        / "debug"
        / "bundle"
        / "macos"
        / "Hanly.app"
        / "Contents"
        / "MacOS"
        / "hanly-desktop",
        target
        / "release"
        / "bundle"
        / "macos"
        / "Hanly.app"
        / "Contents"
        / "MacOS"
        / "hanly-desktop",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "the Tauri desktop binary is missing; build apps/desktop/src-tauri first or pass --desktop"
    )


def is_debug_executable(executable: Path, repo_root: Path) -> bool:
    """Whether the chosen desktop belongs to this checkout's Cargo debug tree."""

    try:
        executable.resolve().relative_to(
            (repo_root / "apps" / "desktop" / "src-tauri" / "target" / "debug").resolve()
        )
        return True
    except ValueError:
        return False


class DesktopProcess:
    """A bounded trace reader and lifecycle owner for one native desktop process."""

    def __init__(
        self,
        executable: Path,
        *,
        runtime_config: Path,
        app_config: Path,
        environment: dict[str, str],
        recorder: DesktopRecorder,
        sampler: Any,
        repo_root: Path,
        roi_size: tuple[int, int] | None = None,
        trace_consumer: Callable[[Mapping[str, Any]], object] | None = None,
        capture_consumer: Callable[[Mapping[str, Any]], object] | None = None,
    ) -> None:
        self.executable = executable
        self.runtime_config = runtime_config
        self.app_config = app_config
        self.environment = dict(environment)
        self.recorder = recorder
        self.sampler = sampler
        self.repo_root = repo_root
        self.roi_size = roi_size
        self.trace_consumer = trace_consumer
        self.capture_consumer = capture_consumer
        self.process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stop_lock = threading.Lock()
        self._stop_requested = False
        self.trace_lines = 0
        self.capture_lines = 0
        self.invalid_trace_lines = 0
        self.invalid_capture_lines = 0
        self.ignored_output_lines = 0
        self.responsibility_attribution = "process_tree"
        self._launcher_directory: tempfile.TemporaryDirectory[str] | None = None

    def start(self, *, retain_evidence: bool, retain_geometry: bool) -> None:
        """Start Hanly with explicit per-run configuration and text-free tracing."""

        command = [
            str(self.executable),
            "--runtime-config",
            str(self.runtime_config),
            "--app-config",
            str(self.app_config),
            "--trace",
        ]
        if self.roi_size is not None:
            width, height = self.roi_size
            if not 1 <= width <= 4096 or not 1 <= height <= 4096:
                raise ValueError("ROI dimensions must be between 1 and 4096 pixels")
            command.extend(("--roi", f"{width}x{height}"))
        if sys.platform == "darwin":
            command, self.responsibility_attribution, self._launcher_directory = (
                _macos_launch_command(command)
            )

        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if sys.platform == "win32"
            else 0
        )
        self.process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
            creationflags=creationflags,
        )
        self.sampler.register_process(self.process.pid, "shell")
        self.recorder.lab(
            "desktop_started",
            pid=self.process.pid,
            build="debug" if is_debug_executable(self.executable, self.repo_root) else "packaged",
            trace_enabled=True,
            evidence_enabled=retain_evidence,
            geometry_enabled=retain_geometry,
            process_attribution=self.responsibility_attribution,
        )
        self._reader = threading.Thread(
            target=self._read_trace,
            name="lab-desktop-trace",
            daemon=True,
        )
        self._reader.start()

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the app to exit, then let its trace pipe drain."""

        process = self.process
        if process is None:
            raise RuntimeError("desktop process has not started")
        try:
            result = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise
        reader = self._reader
        if reader is not None:
            reader.join(timeout=2)
        return result

    def poll(self) -> int | None:
        """Return the child exit code, if it has stopped."""

        process = self.process
        return None if process is None else process.poll()

    def request_stop(self) -> None:
        """Ask the native lifecycle to shut down, escalating only after a deadline."""

        with self._stop_lock:
            if self._stop_requested:
                return
            self._stop_requested = True
        process = self.process
        if process is None or process.poll() is not None:
            return
        self.recorder.lab("desktop_stop_requested")
        try:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            process.terminate()

    def cleanup(self) -> dict[str, int]:
        """Stop the root and any surviving owned descendants before returning."""

        process = self.process
        if process is None:
            return {"survivors": 0, "forced": 0}
        descendants = _descendants(process.pid)
        if process.poll() is None:
            self.request_stop()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

        survivors, forced = _stop_descendants(descendants)
        self.sampler.unregister_process(process.pid)
        reader = self._reader
        if reader is not None:
            reader.join(timeout=2)
        if self._launcher_directory is not None:
            self._launcher_directory.cleanup()
        self.recorder.lab(
            "desktop_stopped",
            exit_code=process.returncode,
            surviving_children=survivors,
            forced_children=forced,
        )
        return {"survivors": survivors, "forced": forced}

    def _read_trace(self) -> None:
        process = self.process
        stream = None if process is None else process.stdout
        if stream is None:
            return
        while True:
            line = stream.readline(MAX_TRACE_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_TRACE_LINE_BYTES or not line.endswith(b"\n"):
                _drain_line(stream)
                self.invalid_trace_lines += 1
                self.recorder.lab("desktop_trace_rejected", reason="frame_too_large")
                continue
            try:
                envelope = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.ignored_output_lines += 1
                self.recorder.lab("desktop_output_ignored", reason="invalid_json")
                continue
            if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
                self.ignored_output_lines += 1
                self.recorder.lab("desktop_output_ignored", reason="unexpected_frame")
                continue
            event = envelope["payload"]
            if envelope.get("type") == "lab_capture":
                if self.capture_consumer is None:
                    self.ignored_output_lines += 1
                    self.recorder.lab("desktop_output_ignored", reason="capture_not_enabled")
                    continue
                try:
                    self.capture_consumer(event)
                except Exception:
                    self.invalid_capture_lines += 1
                    self.recorder.lab("desktop_capture_rejected", reason="invalid_payload")
                    continue
                self.capture_lines += 1
                continue
            if envelope.get("type") != "trace":
                self.ignored_output_lines += 1
                self.recorder.lab("desktop_output_ignored", reason="unexpected_frame")
                continue
            if not isinstance(event.get("event_kind", event.get("event")), str):
                self.invalid_trace_lines += 1
                self.recorder.lab("desktop_trace_rejected", reason="event_name_missing")
                continue
            self.trace_lines += 1
            if self.trace_consumer is None:
                self.recorder.emit(event)
            else:
                self.trace_consumer(event)


def _drain_line(stream: Any) -> None:
    """Discard the rest of one oversized frame without retaining its contents."""

    while True:
        remainder = stream.readline(4096)
        if not remainder or remainder.endswith(b"\n"):
            return


def _descendants(root_pid: int) -> list[psutil.Process]:
    """Snapshot the owned process tree before its root can be reparented."""

    try:
        return psutil.Process(root_pid).children(recursive=True)
    except (psutil.Error, OSError):
        return []


def _stop_descendants(children: list[psutil.Process]) -> tuple[int, int]:
    """Reap children the native shell failed to stop during its shutdown."""

    survivors = len(children)
    if not children:
        return 0, 0
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(children, timeout=2)
    forced = 0
    for child in alive:
        try:
            child.kill()
            forced += 1
        except psutil.Error:
            continue
    if alive:
        psutil.wait_procs(alive, timeout=2)
    return survivors, forced


def _binary_name() -> str:
    return "hanly-desktop.exe" if sys.platform == "win32" else "hanly-desktop"


def _bundle_candidates(path: Path) -> list[Path]:
    if path.suffix != ".app":
        return []
    return [
        path / "Contents" / "MacOS" / "hanly-desktop",
        path / "Contents" / "MacOS" / "Hanly",
    ]


def _macos_launch_command(
    command: list[str],
) -> tuple[list[str], str, tempfile.TemporaryDirectory[str] | None]:
    """Use a Lab-only responsibility boundary so macOS WebKit helpers are attributable."""

    global _MACOS_LAUNCHER_DIRECTORY
    source = Path(__file__).with_name("macos-launcher.c")
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None or not source.is_file():
        return command, "process_tree_only", None
    try:
        _MACOS_LAUNCHER_DIRECTORY = tempfile.TemporaryDirectory(prefix="hanly-lab-launcher-")
        binary = Path(_MACOS_LAUNCHER_DIRECTORY.name) / "macos-launcher"
        result = subprocess.run(
            [compiler, "-Wall", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            _MACOS_LAUNCHER_DIRECTORY.cleanup()
            _MACOS_LAUNCHER_DIRECTORY = None
            return command, "process_tree_only", None
        probe = subprocess.run(
            [str(binary), "--lab-probe"], capture_output=True, timeout=3, check=False
        )
        if probe.returncode != 0:
            _MACOS_LAUNCHER_DIRECTORY.cleanup()
            _MACOS_LAUNCHER_DIRECTORY = None
            return command, "process_tree_only", None
        return [str(binary), *command], "macos_responsibility", _MACOS_LAUNCHER_DIRECTORY
    except (OSError, subprocess.SubprocessError):
        if _MACOS_LAUNCHER_DIRECTORY is not None:
            _MACOS_LAUNCHER_DIRECTORY.cleanup()
        _MACOS_LAUNCHER_DIRECTORY = None
        return command, "process_tree_only", None


__all__ = ["DesktopProcess", "desktop_executable", "is_debug_executable"]
