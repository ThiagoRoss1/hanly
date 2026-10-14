"""Launch and observe the native Hanly desktop as a Lab-owned child."""

from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, BinaryIO, Protocol

import psutil

MAX_TRACE_LINE_BYTES = 1_048_576
_MACOS_ROOT_DISCOVERY_SECONDS = 15.0
_MACOS_CHILD_ENVIRONMENT = {
    "HOME",
    "PATH",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "USER",
    "LOGNAME",
    "SHELL",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "LOCALAPPDATA",
    "APPDATA",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
}
_MACOS_LAB_ENVIRONMENT = _MACOS_CHILD_ENVIRONMENT - {
    "HOME",
    "PATH",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "USER",
    "LOGNAME",
    "SHELL",
}


class DesktopRecorder(Protocol):
    """The subset of recorder behavior needed by the native process owner."""

    def lab(self, event: str, /, **fields: Any) -> object: ...

    def emit(self, event: Mapping[str, Any]) -> object: ...


class _DesktopProcess(Protocol):
    """Process operations shared by direct children and LaunchServices roots."""

    pid: int
    stdout: BinaryIO | None

    @property
    def returncode(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def poll(self) -> int | None: ...

    def send_signal(self, signal_number: int) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class _LaunchServicesProcess:
    """Expose the adopted app PID while ``open -W`` owns the launch lifetime."""

    def __init__(
        self,
        root: psutil.Process,
        launcher: subprocess.Popen[bytes],
    ) -> None:
        self._root = root
        self._launcher = launcher
        self.pid = root.pid
        self.stdout: BinaryIO | None = None

    @property
    def returncode(self) -> int | None:
        result = self._launcher.returncode
        return None if self.root_is_running() else result

    def wait(self, timeout: float | None = None) -> int:
        result = self._launcher.wait(timeout=timeout)
        if self.root_is_running():
            raise subprocess.TimeoutExpired(
                self._launcher.args, timeout if timeout is not None else 0
            )
        return result

    def poll(self) -> int | None:
        result = self._launcher.poll()
        return None if self.root_is_running() else result

    def root_is_running(self) -> bool:
        try:
            return self._root.is_running()
        except psutil.NoSuchProcess:
            return False
        except psutil.Error:
            return True

    def send_signal(self, signal_number: int) -> None:
        if self.root_is_running():
            self._root.send_signal(signal_number)

    def terminate(self) -> None:
        if self.root_is_running():
            self._root.terminate()

    def kill(self) -> None:
        if self.root_is_running():
            self._root.kill()

    def descendants(self) -> list[psutil.Process]:
        try:
            return self._root.children(recursive=True)
        except (psutil.Error, OSError):
            return []

    def stop_launcher(self) -> None:
        """Stop the owned ``open -W`` waiter after the adopted root is gone."""

        if self._launcher.poll() is None:
            self._launcher.terminate()
            try:
                self._launcher.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._launcher.kill()
                self._launcher.wait(timeout=2)


def desktop_executable(explicit: Path | None, repo_root: Path) -> Path:
    """Resolve a debug binary or explicit packaged app without invoking a shell."""

    if explicit is not None:
        path = explicit.expanduser().resolve()
        if path.is_dir():
            bundle_candidates = _bundle_candidates(path)
            if path.suffix != ".app" and sys.platform == "win32":
                bundle_candidates.insert(0, path / "hanly-desktop.exe")
            elif path.suffix != ".app":
                bundle_candidates.insert(0, path / _binary_name())
            for candidate in bundle_candidates:
                if candidate.is_file():
                    return candidate.resolve()
            raise FileNotFoundError("the selected Hanly app has no desktop executable")
        if not path.is_file():
            raise FileNotFoundError("the selected Hanly desktop executable does not exist")
        if sys.platform == "darwin" and _app_bundle_for_executable(path) is None:
            bundled = _debug_bundle_executable(path)
            if bundled is not None:
                return bundled
        return path

    target = repo_root / "apps" / "desktop" / "src-tauri" / "target"
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(
            target
            / "debug"
            / "bundle"
            / "macos"
            / "Hanly.app"
            / "Contents"
            / "MacOS"
            / "hanly-desktop"
        )
    candidates.extend(
        [
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
    )
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
        self.process: _DesktopProcess | None = None
        self._launcher: subprocess.Popen[bytes] | None = None
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
        self._trace_fifo: Path | None = None

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
            self._start_with_launch_services(command)
        else:
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
            self._reader = threading.Thread(
                target=self._read_trace,
                name="lab-desktop-trace",
                daemon=True,
            )
            self._reader.start()

        process = self.process
        if process is None:
            raise RuntimeError("the native desktop process was not adopted")
        self.sampler.register_process(process.pid, "shell")
        self.recorder.lab(
            "desktop_started",
            pid=process.pid,
            build="debug" if is_debug_executable(self.executable, self.repo_root) else "packaged",
            trace_enabled=True,
            evidence_enabled=retain_evidence,
            geometry_enabled=retain_geometry,
            process_attribution=self.responsibility_attribution,
        )

    def _start_with_launch_services(self, command: list[str]) -> None:
        bundle = _app_bundle_for_executable(self.executable)
        if bundle is None:
            raise RuntimeError(
                "macOS Lab runs require a built Hanly.app bundle so LaunchServices "
                "can grant the normal desktop identity"
            )

        self._launcher_directory = tempfile.TemporaryDirectory(
            prefix="hanly-lab-launch-"
        )
        fifo = Path(self._launcher_directory.name) / "trace.fifo"
        os.mkfifo(fifo, mode=0o600)
        self._trace_fifo = fifo
        self._reader = threading.Thread(
            target=self._read_trace,
            name="lab-desktop-trace",
            daemon=True,
        )
        self._reader.start()

        try:
            app_arguments = command[1:]
            known_pids = set(
                _matching_bundle_processes(self.executable, app_arguments)
            )
            launch_command = _macos_launch_command(
                bundle, app_arguments, fifo, self.environment
            )
            launcher = subprocess.Popen(
                launch_command,
                cwd=self.repo_root,
                env=_macos_child_environment(self.environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._launcher = launcher
            root = _adopt_macos_process(
                self.executable,
                app_arguments,
                known_pids,
                launcher,
                timeout=_MACOS_ROOT_DISCOVERY_SECONDS,
            )
        except BaseException:
            if self._launcher is not None:
                _stop_launcher(self._launcher)
            self._release_trace_reader()
            self._remove_launcher_directory()
            self._launcher = None
            raise

        self.process = _LaunchServicesProcess(root, launcher)
        self.responsibility_attribution = _macos_process_attribution(root.pid)

    def _release_trace_reader(self) -> None:
        """Pair a blocked FIFO reader with a writer when LaunchServices fails."""

        fifo = self._trace_fifo
        reader = self._reader
        if fifo is None or reader is None or not reader.is_alive():
            return
        deadline = time.monotonic() + 2
        while reader.is_alive():
            try:
                descriptor = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno != errno.ENXIO or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            else:
                os.close(descriptor)
                break
        reader.join(timeout=2)

    def _remove_launcher_directory(self) -> None:
        if self._launcher_directory is not None:
            self._launcher_directory.cleanup()
            self._launcher_directory = None
            self._trace_fifo = None

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
        if process is None:
            return
        if isinstance(process, _LaunchServicesProcess):
            if not process.root_is_running():
                return
        elif process.poll() is not None:
            return
        self.recorder.lab("desktop_stop_requested")
        try:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGINT)
        except (OSError, ValueError, psutil.Error):
            process.terminate()

    def cleanup(self) -> dict[str, int]:
        """Stop the root and any surviving owned descendants before returning."""

        process = self.process
        if process is None:
            launcher = self._launcher
            if launcher is not None:
                _stop_launcher(launcher)
            self._release_trace_reader()
            self._remove_launcher_directory()
            return {"survivors": 0, "forced": 0}
        descendants = (
            process.descendants()
            if isinstance(process, _LaunchServicesProcess)
            else _descendants(process.pid)
        )
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
                    if isinstance(process, _LaunchServicesProcess):
                        process.stop_launcher()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        if isinstance(process, _LaunchServicesProcess):
                            process.stop_launcher()

        survivors, forced = _stop_descendants(descendants)
        self.sampler.unregister_process(process.pid)
        reader = self._reader
        if reader is not None:
            reader.join(timeout=2)
        self._remove_launcher_directory()
        self._launcher = None
        self.recorder.lab(
            "desktop_stopped",
            exit_code=process.returncode,
            surviving_children=survivors,
            forced_children=forced,
        )
        return {"survivors": survivors, "forced": forced}

    def _read_trace(self) -> None:
        fifo = self._trace_fifo
        if fifo is not None:
            try:
                with fifo.open("rb", buffering=0) as fifo_stream:
                    self._consume_trace(fifo_stream)
            except OSError:
                return
            return

        process = self.process
        stdout_stream = None if process is None else process.stdout
        if stdout_stream is None:
            return
        self._consume_trace(stdout_stream)

    def _consume_trace(self, stream: BinaryIO) -> None:
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


def _app_bundle_for_executable(executable: Path) -> Path | None:
    for parent in executable.resolve().parents:
        if parent.suffix == ".app" and parent.is_dir():
            return parent
    return None


def _debug_bundle_executable(executable: Path) -> Path | None:
    if executable.name != "hanly-desktop" or executable.parent.name != "debug":
        return None
    bundle = executable.parent / "bundle" / "macos" / "Hanly.app"
    return next(
        (candidate.resolve() for candidate in _bundle_candidates(bundle) if candidate.is_file()),
        None,
    )


def _matching_bundle_processes(
    executable: Path, app_arguments: Sequence[str]
) -> dict[int, psutil.Process]:
    expected_executable = executable.resolve()
    expected_arguments = list(app_arguments)
    matches: dict[int, psutil.Process] = {}
    try:
        processes = psutil.process_iter(attrs=["exe"])
        for process in processes:
            try:
                process_executable = process.info.get("exe")
                if process_executable is None:
                    continue
                if Path(process_executable).resolve() != expected_executable:
                    continue
                command_line = process.cmdline()
                if not _contains_arguments(command_line[1:], expected_arguments):
                    continue
                matches[process.pid] = process
            except (OSError, psutil.Error, TypeError, ValueError):
                continue
    except (OSError, psutil.Error):
        return matches
    return matches


def _contains_arguments(command_line: Sequence[str], expected: Sequence[str]) -> bool:
    """Match Lab's argv in order while allowing LaunchServices metadata args."""

    position = 0
    for argument in expected:
        try:
            position = command_line.index(argument, position) + 1
        except ValueError:
            return False
    return True


def _adopt_macos_process(
    executable: Path,
    app_arguments: Sequence[str],
    known_pids: set[int],
    launcher: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> psutil.Process:
    """Adopt only the fresh app whose executable and per-run argv both match."""

    deadline = time.monotonic() + timeout
    while True:
        candidates = [
            process
            for pid, process in _matching_bundle_processes(executable, app_arguments).items()
            if pid not in known_pids
        ]
        if candidates:
            return min(candidates, key=lambda process: process.create_time())
        if launcher.poll() is not None:
            raise RuntimeError("LaunchServices exited before the Hanly app could be adopted")
        if time.monotonic() >= deadline:
            raise TimeoutError("LaunchServices did not expose the Hanly app PID in time")
        time.sleep(0.05)


def _macos_process_attribution(root_pid: int) -> str:
    """Report whether macOS can attribute non-child helpers to the app root."""

    try:
        from .macos_responsibility import responsible_pid

        if responsible_pid(root_pid) == root_pid:
            return "launch_services_process_tree+macos_responsibility"
    except (OSError, psutil.Error):
        pass
    return "launch_services_process_tree+helper_attribution_incomplete"


def _macos_child_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environment.items()
        if name in _MACOS_CHILD_ENVIRONMENT or name.startswith("HANLY_")
    }


def _macos_launch_command(
    bundle: Path,
    app_arguments: Sequence[str],
    stdout_fifo: Path,
    environment: Mapping[str, str],
) -> list[str]:
    """Launch a fresh app through public LaunchServices with private trace IPC."""

    if bundle.suffix != ".app" or not bundle.is_dir():
        raise ValueError("LaunchServices requires a Hanly.app bundle")
    open_command = Path("/usr/bin/open")
    if not open_command.is_file():
        raise FileNotFoundError("/usr/bin/open is required for a macOS Lab session")

    command = [
        str(open_command),
        "-n",
        "-W",
        "--stdin",
        "/dev/null",
        "--stdout",
        str(stdout_fifo),
        "--stderr",
        "/dev/null",
    ]
    for name, value in sorted(environment.items()):
        if name.startswith("HANLY_") or name in _MACOS_LAB_ENVIRONMENT:
            command.extend(("--env", f"{name}={value}"))
    command.extend(("-a", str(bundle), "--args", *app_arguments))
    return command


def _stop_launcher(launcher: subprocess.Popen[bytes]) -> None:
    if launcher.poll() is None:
        launcher.terminate()
        try:
            launcher.wait(timeout=2)
        except subprocess.TimeoutExpired:
            launcher.kill()
            launcher.wait(timeout=2)


__all__ = ["DesktopProcess", "desktop_executable", "is_debug_executable"]
