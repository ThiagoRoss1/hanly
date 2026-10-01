"""Sample memory, CPU and threads of the shell and every process it owns.

The lab hosts the shell in its own process, so child identity is exact: the
names ``hanly-lookup`` and ``hanly-control-center`` come from
``multiprocessing.active_children()``, not from guessing at command lines.
Grandchildren (Qt WebEngine helpers) are attributed to the child that owns them.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
from pathlib import Path
from typing import Any

import psutil

_ROLES = {"hanly-lookup": "lookup", "hanly-control-center": "control_center"}


class ProcessSampler:
    """Write one JSON line per sample to ``processes.jsonl`` on a daemon thread."""

    def __init__(self, path: Path, origin_ns: int, *, interval: float = 0.25) -> None:
        self._path = path
        self._origin_ns = origin_ns
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lab-sampler", daemon=True)
        self._handles: dict[int, psutil.Process] = {}
        self.samples = 0
        self.denied = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        with self._path.open("a", encoding="utf-8") as stream:
            while not self._stop.is_set():
                started = time.perf_counter_ns()
                rows = self._sample()
                stream.write(
                    json.dumps(
                        {"t_ms": (started - self._origin_ns) / 1e6, "processes": rows},
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                stream.flush()
                self.samples += 1
                self._stop.wait(self._interval)

    def _sample(self) -> list[dict[str, Any]]:
        owned: dict[int, str] = {os.getpid(): "shell"}
        for child in multiprocessing.active_children():
            if child.pid is not None:
                owned[child.pid] = _ROLES.get(child.name, child.name)
        rows = []
        for pid, role in list(owned.items()):
            process = self._handle(pid)
            if process is None:
                continue
            rows.append(self._row(process, role))
            try:
                descendants = process.children(recursive=True)
            except psutil.Error:
                continue
            for descendant in descendants:
                if descendant.pid in owned:
                    continue
                handle = self._handle(descendant.pid, descendant)
                if handle is not None:
                    rows.append(self._row(handle, f"{role}.helper", detail=_name(handle)))
        live = {row["pid"] for row in rows}
        for stale in set(self._handles) - live:
            del self._handles[stale]
        return rows

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


def _name(process: psutil.Process) -> str:
    try:
        return process.name()
    except psutil.Error:
        return "unknown"


__all__ = ["ProcessSampler"]
