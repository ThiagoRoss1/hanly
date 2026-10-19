"""Sample the native desktop and every process it owns from a separate process."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any

import psutil

_ROLES = {"hanly-lookup": "lookup"}
_MAX_ANCESTORS = 256


class ProcessSampler:
    """Write one JSON line per sample to ``processes.jsonl`` from a separate process."""

    def __init__(
        self,
        path: Path,
        origin_ns: int,
        *,
        interval: float = 0.25,
        sample_parent: bool = True,
    ) -> None:
        self._path = path
        self._origin_ns = origin_ns
        self._interval = interval
        self._sample_parent = sample_parent
        self._roles_path = path.with_name("processes.roles.json")
        self._summary_path = path.with_name("processes.summary.json")
        self._stop = threading.Event()
        self._roles_lock = Lock()
        self._write_lock = Lock()
        self._registered: dict[int, str] = {}
        self._publisher = threading.Thread(target=self._publish, name="lab-roles", daemon=True)
        self._process: subprocess.Popen[bytes] | None = None
        self.samples = 0
        self.denied = 0

    def start(self) -> None:
        self._write_roles()
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lab.session.sampler",
                str(os.getpid()),
                str(self._path),
                str(self._roles_path),
                str(self._summary_path),
                str(self._origin_ns),
                str(self._interval),
                "1" if self._sample_parent else "0",
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
            stdin=subprocess.PIPE,
        )
        self._publisher.start()

    def stop(self) -> None:
        self._stop.set()
        self._publisher.join(timeout=5)
        process = self._process
        if process is not None:
            # Closing its input is the stop signal; it writes its summary and exits.
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(3)
        try:
            summary = json.loads(self._summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}
        self.samples = int(summary.get("samples", 0))
        self.denied = int(summary.get("denied", 0))
        for path in (self._roles_path, self._roles_path.with_suffix(".tmp"), self._summary_path):
            path.unlink(missing_ok=True)

    def _publish(self) -> None:
        while not self._stop.wait(self._interval):
            self._write_roles()

    def register_process(self, pid: int, role: str) -> None:
        """Add a directly launched process to the observed Hanly family."""

        if pid <= 0 or not role or not role.replace("_", "").isalnum():
            raise ValueError("a positive PID and simple process role are required")
        with self._roles_lock:
            self._registered[pid] = role
        self._write_roles()

    def unregister_process(self, pid: int) -> None:
        """Stop treating a Lab-launched process as a product root."""

        with self._roles_lock:
            self._registered.pop(pid, None)
        self._write_roles()

    def _write_roles(self) -> None:
        with self._roles_lock:
            roles = {str(pid): role for pid, role in self._registered.items()}
        if self._sample_parent:
            roles[str(os.getpid())] = "shell"
        for child in multiprocessing.active_children():
            if child.pid is not None:
                roles[str(child.pid)] = _ROLES.get(child.name, child.name)
        with self._write_lock:
            temporary = self._roles_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(roles), encoding="utf-8")
            try:
                os.replace(temporary, self._roles_path)
            except PermissionError:
                # Windows refuses while the sampler is reading it; the next tick retries.
                pass


class _Sampling:
    """The sampler process's state: cached handles, so cpu_percent has a baseline."""

    def __init__(self, own_pid: int, shell_pid: int) -> None:
        self._own = _sampler_chain(own_pid, shell_pid)
        self._handles: dict[int, psutil.Process] = {}
        self.samples = 0
        self.denied = 0

    def sample(self, owned: Mapping[int, str]) -> list[dict[str, Any]]:
        rows = []
        for pid, role in list(owned.items()):
            process = self._handle(pid)
            if process is None:
                continue
            rows.append(self._row(process, role))
            try:
                descendants = process.children(recursive=True)
            except (psutil.Error, OSError):
                # The registered root still gives a useful sample when process
                # enumeration is restricted by the host or test sandbox.
                continue
            for descendant in descendants:
                if descendant.pid in self._own or descendant.pid in owned:
                    continue
                # Recursion from the shell also reaches its children's helpers.
                if nearest_owner(descendant, owned) != pid:
                    continue
                handle = self._handle(descendant.pid, descendant)
                if handle is not None:
                    rows.append(self._row(handle, f"{role}.helper", detail=_name(handle)))
        live = {row["pid"] for row in rows}
        if sys.platform == "darwin":
            self._responsible_helpers(owned, rows, live)
            live = {row["pid"] for row in rows}
        for stale in set(self._handles) - live:
            del self._handles[stale]
        return rows

    def _responsible_helpers(
        self, owned: Mapping[int, str], rows: list[dict[str, Any]], live: set[int]
    ) -> None:
        """Include WebKit helpers assigned to the launched app by macOS."""

        from .macos_responsibility import responsible_pid

        roots = {
            pid
            for pid, role in owned.items()
            if role == "shell" and responsible_pid(pid) == pid
        }
        if not roots:
            return
        try:
            processes = psutil.process_iter()
            for process in processes:
                if process.pid in live or process.pid in self._own:
                    continue
                if responsible_pid(process.pid) not in roots:
                    continue
                handle = self._handle(process.pid, process)
                if handle is not None:
                    rows.append(self._row(handle, "shell.helper", detail=_name(handle)))
        except (psutil.Error, OSError):
            return

    def _handle(self, pid: int, known: psutil.Process | None = None) -> psutil.Process | None:
        # A cached handle keeps cpu_percent's baseline and survives PID reuse checks.
        handle = self._handles.get(pid)
        if handle is not None and handle.is_running():
            return handle
        try:
            handle = known or psutil.Process(pid)
            handle.cpu_percent(None)
        except psutil.Error:
            return None
        self._handles[pid] = handle
        return handle

    def _row(self, process: psutil.Process, role: str, detail: str | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {"pid": process.pid, "role": role}
        if detail:
            row["detail"] = detail
        try:
            with process.oneshot():
                row["rss"] = process.memory_info().rss
                row["cpu"] = round(process.cpu_percent(None), 1)
                row["threads"] = process.num_threads()
        except psutil.AccessDenied:
            self.denied += 1
            row["denied"] = True
        except psutil.Error:
            row["gone"] = True
        return row


def nearest_owner(process: Any, owned: Mapping[int, str]) -> int | None:
    """The closest ancestor of ``process`` that is a sampled Hanly process."""

    try:
        parent_pid = int(process.ppid())
        for _ in range(_MAX_ANCESTORS):
            if parent_pid <= 0:
                break
            if parent_pid in owned:
                return parent_pid
            parent_pid = int(psutil.Process(parent_pid).ppid())
    except (psutil.Error, OSError):
        return None
    return None


def _name(process: psutil.Process) -> str:
    try:
        return process.name()
    except psutil.Error:
        return "unknown"


def _sampler_chain(own_pid: int, shell_pid: int) -> frozenset[int]:
    """This process and any launcher between it and the shell (a venv's python.exe)."""

    chain = {own_pid}
    try:
        parent_pid = int(psutil.Process(own_pid).ppid())
        for _ in range(_MAX_ANCESTORS):
            if parent_pid <= 0 or parent_pid == shell_pid:
                break
            chain.add(parent_pid)
            parent_pid = int(psutil.Process(parent_pid).ppid())
    except (psutil.Error, OSError):
        pass
    return frozenset(chain)


def _roles(path: Path) -> dict[int, str] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {int(pid): str(role) for pid, role in raw.items()}


def main(argv: list[str]) -> None:
    """Sample until the shell closes this process's input, then write a summary."""

    # A terminal's Ctrl+C reaches this process too; ending the run is the shell's
    # decision, and it closes our input once it has made it.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    shell, out, roles_path, summary, origin, interval, *optional = argv
    shell_pid, origin_ns, period = int(shell), int(origin), float(interval)
    sample_parent = not optional or optional[0] != "0"
    stopped = threading.Event()

    def watch_input() -> None:
        sys.stdin.read()
        stopped.set()

    threading.Thread(target=watch_input, daemon=True).start()
    sampling = _Sampling(os.getpid(), shell_pid)
    owned = {shell_pid: "shell"} if sample_parent else {}
    with Path(out).open("a", encoding="utf-8") as stream:
        while not stopped.is_set():
            started = time.perf_counter_ns()
            # A read that races the shell's replace keeps the last roles it saw.
            published = _roles(Path(roles_path))
            if published is not None:
                owned = published
            rows = sampling.sample(owned)
            stream.write(
                json.dumps(
                    {"t_ms": (started - origin_ns) / 1e6, "processes": rows},
                    separators=(",", ":"),
                )
                + "\n"
            )
            stream.flush()
            sampling.samples += 1
            stopped.wait(period)
    Path(summary).write_text(
        json.dumps({"samples": sampling.samples, "denied": sampling.denied}), encoding="utf-8"
    )


if __name__ == "__main__":
    main(sys.argv[1:])


__all__ = ["ProcessSampler", "nearest_owner"]
