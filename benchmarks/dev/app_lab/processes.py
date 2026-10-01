"""Bounded subprocess output and observation of the scenario's own process tree."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psutil

_TAIL_BYTES = 64 * 1024
_EVENT_LIMIT = 1000
_COUNTS = re.compile(r"\b(\d+) (passed|failed|skipped|error|errors|xfailed|xpassed)\b")


@dataclass(frozen=True)
class Execution:
    """Safe observations; raw child output never leaves the bounded reader."""

    exit_code: int
    timed_out: bool
    counts: dict[str, int]
    peak_rss_bytes: int | None
    processes: tuple[dict[str, object], ...]
    sampling_interval_seconds: float
    dropped_events: int
    identity_samples: int = 0
    surviving_children: int = 0
    process_observation_available: bool = True
    output_complete: bool = True
    children_requiring_cleanup: int = 0


def parse_test_counts(output: str) -> dict[str, int]:
    """Read pytest's final summary without retaining assertion output."""

    lines = [line for line in output.splitlines() if _COUNTS.search(line)]
    return {key: int(value) for value, key in _COUNTS.findall(lines[-1])} if lines else {}


def _role(command: Sequence[str]) -> str:
    joined = " ".join(command)
    if "QtWebEngineProcess" in joined:
        return "webengine"
    if "startup_child.py" in joined:
        return "desktop_shell"
    if "--multiprocessing-fork" in joined or "spawn_main" in joined:
        return "spawned_python"
    if "hanly-update" in joined:
        return "update_helper"
    if "hanly-desktop" in joined:
        return "packaged_app"
    return "scenario_child"


def macos_registrations(pids: set[int]) -> dict[int, str] | None:
    """Read activation types only for owned PIDs, discarding the global listing."""

    if sys.platform != "darwin" or not pids:
        return None
    try:
        listing = subprocess.run(
            ["/usr/bin/lsappinfo", "list"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listing.returncode:
        return None
    output = listing.stdout
    result = {}
    for block in output.split("ASN:"):
        match = re.search(r"pid = (\d+)", block)
        kind = re.search(r'type="([^"]+)"', block)
        if match and int(match.group(1)) in pids and kind:
            value = kind.group(1)
            result[int(match.group(1))] = (
                value
                if value
                in {
                    "Foreground",
                    "UIElement",
                    "BackgroundOnly",
                }
                else "unknown"
            )
    return result


class _ProcessObserver:
    def __init__(self, pid: int, observe_identity: bool) -> None:
        self.pid = pid
        self.observe_identity = observe_identity
        self.owned: dict[int, Any] = {}
        self.events: list[dict[str, object]] = []
        self.states: dict[int, tuple[str, str]] = {}
        self.peak_rss: int | None = None
        self.dropped = 0
        self.identity_samples = 0
        self.available = True
        self.cleanup_count = 0
        self.started = time.monotonic()

    def sample(self) -> None:
        try:
            root = psutil.Process(self.pid)
            processes = [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            return
        except (psutil.Error, OSError):
            self.available = False
            return
        kinds = macos_registrations({p.pid for p in processes}) if self.observe_identity else None
        if kinds is not None:
            self.identity_samples += 1
        live = {process.pid for process in processes}
        for pid in self.states.keys() - live:
            role, _ = self.states.pop(pid)
            self._event(pid, role, "exited")
        rss = 0
        for process in processes:
            try:
                self.owned[process.pid] = process
                rss += process.memory_info().rss
                role = "scenario_runner" if process.pid == self.pid else _role(process.cmdline())
                state = role, (kinds or {}).get(process.pid, "not_observed")
                if self.states.get(process.pid) != state:
                    self.states[process.pid] = state
                    self._event(process.pid, *state)
            except psutil.NoSuchProcess:
                continue
            except (psutil.Error, OSError):
                self.available = False
                continue
        self.peak_rss = max(self.peak_rss or 0, rss)

    def _event(self, pid: int, role: str, activation: str) -> None:
        if len(self.events) >= _EVENT_LIMIT:
            self.dropped += 1
            return
        self.events.append(
            {
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 1),
                "pid": pid,
                "role": role,
                "activation": activation,
            }
        )

    def close(self) -> int:
        children = [p for pid, p in self.owned.items() if pid != self.pid]
        _, alive = psutil.wait_procs(children, timeout=0.5)
        self.cleanup_count = len(alive)
        for process in reversed(alive):
            try:
                process.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(alive, timeout=3)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:
                pass
        _, survivors = psutil.wait_procs(alive, timeout=3)
        return len(survivors)


def execute(
    command: Sequence[str],
    *,
    cwd: str,
    environment: Mapping[str, str],
    timeout_seconds: float,
    observe_identity: bool = False,
) -> Execution:
    """Run one process group, discard raw output and stop owned children on exit."""

    child = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name == "posix",
    )
    tail = bytearray()
    tail_lock = threading.Lock()

    def drain() -> None:
        assert child.stdout is not None
        while chunk := child.stdout.read(4096):
            with tail_lock:
                tail.extend(chunk)
                del tail[:-_TAIL_BYTES]

    reader = threading.Thread(target=drain, daemon=True, name="app-lab-output")
    reader.start()
    observer = _ProcessObserver(child.pid, observe_identity)
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    try:
        while child.poll() is None:
            observer.sample()
            if time.monotonic() >= deadline:
                timed_out = True
                if os.name == "posix":
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    child.terminate()
                break
            time.sleep(0.1)
        if timed_out:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
        status = child.wait(timeout=5)
    finally:
        if child.poll() is None:
            if os.name == "posix":
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                child.kill()
            child.wait(timeout=5)
        survivors = observer.close()
        reader.join(timeout=3)
        if child.stdout is not None and not reader.is_alive():
            child.stdout.close()
    with tail_lock:
        counts = parse_test_counts(tail.decode("utf-8", "replace"))
    return Execution(
        status,
        timed_out,
        counts,
        observer.peak_rss,
        tuple(observer.events),
        0.1,
        observer.dropped,
        observer.identity_samples,
        survivors,
        observer.available,
        not reader.is_alive(),
        observer.cleanup_count,
    )
