"""Read one process's resource use from outside it.

Every value the operating system cannot provide stays ``None`` with a reason;
a missing metric is never reported as zero. GPU memory has no portable reader
and is always unavailable.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from dataclasses import asdict, dataclass
from typing import Any

import psutil

#: Why each metric can be absent, recorded once per experiment.
UNAVAILABLE_REASONS = {
    "footprint": "physical footprint is read through macOS proc_pid_rusage only",
    "lifetime_peak_footprint": "lifetime peak footprint is read through macOS proc_pid_rusage only",
    "uss": "unique set size needs psutil memory_full_info, which this platform refused",
    "read_bytes": "this platform reports no per-process disk I/O",
    "write_bytes": "this platform reports no per-process disk I/O",
    "gpu": "no portable per-process GPU memory reader exists; never estimated",
}


@dataclass(frozen=True)
class Snapshot:
    """One reading of one process. ``None`` means unavailable, not zero."""

    rss: int | None
    footprint: int | None
    lifetime_peak_footprint: int | None
    uss: int | None
    cpu_user: float | None
    cpu_system: float | None
    threads: int | None
    read_bytes: int | None
    write_bytes: int | None
    gpu: None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _RusageInfoV4(ctypes.Structure):
    """``struct rusage_info_v4`` from ``<sys/resource.h>``, in declaration order."""

    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        *[
            (name, ctypes.c_uint64)
            for name in (
                "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups",
                "ri_interrupt_wkups", "ri_pageins", "ri_wired_size",
                "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime",
                "ri_proc_exit_abstime", "ri_child_user_time", "ri_child_system_time",
                "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups",
                "ri_child_pageins", "ri_child_elapsed_abstime",
                "ri_diskio_bytesread", "ri_diskio_byteswritten",
                "ri_cpu_time_qos_default", "ri_cpu_time_qos_maintenance",
                "ri_cpu_time_qos_background", "ri_cpu_time_qos_utility",
                "ri_cpu_time_qos_legacy", "ri_cpu_time_qos_user_initiated",
                "ri_cpu_time_qos_user_interactive", "ri_billed_system_time",
                "ri_serviced_system_time", "ri_logical_writes",
                "ri_lifetime_max_phys_footprint", "ri_instructions", "ri_cycles",
                "ri_billed_energy", "ri_serviced_energy",
                "ri_interval_max_phys_footprint", "ri_runnable_time",
            )
        ],
    ]


_RUSAGE_INFO_V4 = 4
_libproc: ctypes.CDLL | None = None


def _darwin_rusage(pid: int) -> _RusageInfoV4 | None:
    global _libproc
    if sys.platform != "darwin":
        return None
    if _libproc is None:
        path = ctypes.util.find_library("proc")
        if path is None:
            return None
        _libproc = ctypes.CDLL(path, use_errno=True)
        _libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        _libproc.proc_pid_rusage.restype = ctypes.c_int
    info = _RusageInfoV4()
    if _libproc.proc_pid_rusage(pid, _RUSAGE_INFO_V4, ctypes.byref(info)) != 0:
        return None
    return info


def snapshot(pid: int, *, full: bool = True) -> Snapshot | None:
    """Read ``pid`` now; ``None`` when the process is gone or unreadable.

    ``full`` adds the unique set size, which walks the whole address space and
    is too slow for continuous sampling; stage boundaries take it, the peak
    sampler does not.
    """

    try:
        process = psutil.Process(pid)
        with process.oneshot():
            memory = process.memory_info()
            times = process.cpu_times()
            threads = process.num_threads()
            io = _io_counters(process)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None

    uss: int | None = None
    if full:
        try:
            uss = int(process.memory_full_info().uss)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, AttributeError):
            uss = None

    rusage = _darwin_rusage(pid)
    read_bytes, write_bytes = io
    if rusage is not None:
        # macOS has no psutil io_counters; its own accounting is exact.
        read_bytes = int(rusage.ri_diskio_bytesread)
        write_bytes = int(rusage.ri_diskio_byteswritten)
    return Snapshot(
        rss=int(memory.rss),
        footprint=int(rusage.ri_phys_footprint) if rusage is not None else None,
        lifetime_peak_footprint=(
            int(rusage.ri_lifetime_max_phys_footprint) if rusage is not None else None
        ),
        uss=uss,
        cpu_user=float(times.user),
        cpu_system=float(times.system),
        threads=int(threads),
        read_bytes=read_bytes,
        write_bytes=write_bytes,
    )


def _io_counters(process: psutil.Process) -> tuple[int | None, int | None]:
    reader = getattr(process, "io_counters", None)
    if reader is None:
        return None, None
    try:
        counters = reader()
    except (psutil.AccessDenied, NotImplementedError):
        return None, None
    return int(counters.read_bytes), int(counters.write_bytes)


def primary_memory(reading: Snapshot | dict[str, Any] | None) -> int | None:
    """The memory figure attribution uses: footprint where it exists, else RSS.

    Footprint counts compressed and swapped private pages and excludes clean
    shared library pages, so it follows what a process holds better than RSS.
    """

    if reading is None:
        return None
    values = reading.as_dict() if isinstance(reading, Snapshot) else reading
    footprint = values.get("footprint")
    return int(footprint) if footprint is not None else values.get("rss")


def primary_memory_name() -> str:
    return "footprint" if sys.platform == "darwin" else "rss"
