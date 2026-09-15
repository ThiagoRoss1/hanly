"""Record what a packaging host actually is, before a build can lose it.

A frozen build that dies on an illegal instruction is a native library meeting
a CPU that does not implement what it was compiled to use, and the exit status
alone names no suspect. This writes the host's identity as one small JSON
document early in a run, so a later crash still has a machine to describe.

The probes are deliberately narrow: operating system, CPU, core counts, the
build interpreter, and -- in a subprocess of its own -- what Torch believes the
CPU supports. Environment variables and machine-wide process inventories are
never collected. A value the host will not give up is reported as unavailable
with the reason, never as a plausible default.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: The OS metadata files and tools each platform answers with.
OS_RELEASE_PATH = "/etc/os-release"
CPUINFO_PATH = "/proc/cpuinfo"
SW_VERS = "/usr/bin/sw_vers"
SYSCTL = "/usr/sbin/sysctl"
POWERSHELL = "powershell.exe"

#: One CIM query for both facts Windows owns. Two invocations would pay
#: PowerShell's startup cost twice for the same answer.
WINDOWS_QUERY = (
    "$os = Get-CimInstance Win32_OperatingSystem | "
    "Select-Object Caption,Version,BuildNumber,OSArchitecture;"
    "$cpu = @(Get-CimInstance Win32_Processor | "
    "Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors)[0];"
    "ConvertTo-Json -Compress -InputObject @{ os = $os; cpu = $cpu }"
)

#: What the Torch probe answers with. Every field is guarded on its own: a
#: build where one accessor is missing still reports the version.
TORCH_PROBE = """
import json

report = {}
try:
    import torch
except BaseException as error:
    report["unavailable"] = "%s: %s" % (type(error).__name__, error)
else:
    report["version"] = getattr(torch, "__version__", None)
    for name, accessor in (
        ("cpu_capability", lambda: torch.backends.cpu.get_cpu_capability()),
        ("mkldnn", lambda: torch.backends.mkldnn.is_available()),
        ("threads", lambda: torch.get_num_threads()),
    ):
        try:
            report[name] = accessor()
        except BaseException:
            report[name] = None
print(json.dumps(report))
"""

#: Torch imports a large native stack that can abort rather than raise, which
#: is the very failure this fingerprint exists to describe. It is bounded so a
#: hung or crashed import costs the run a field, not the document.
TORCH_TIMEOUT_SECONDS = 120.0

#: How long any single OS probe may take. These are local queries; a probe
#: that does not answer in this is not going to.
PROBE_TIMEOUT_SECONDS = 30.0

TextRunner = Callable[[Sequence[str]], str]
TextReader = Callable[[str], str]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class ProbeError(RuntimeError):
    """Raised when a host will not answer for one optional fact."""


@dataclass
class Facts:
    """Values one probe group produced, and the reason for each it could not."""

    values: dict[str, object] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)

    def record(self, name: str, probe: Callable[[], object]) -> None:
        """Store what the probe answered, or why it could not answer."""

        try:
            self.values[name] = probe()
        except ProbeError as error:
            self.values[name] = None
            self.unavailable[name] = str(error)

    def to_dict(self) -> dict[str, object]:
        return {**self.values, "unavailable": dict(self.unavailable)}


def collect_fingerprint(
    context: str,
    *,
    platform_name: str = sys.platform,
    run: TextRunner | None = None,
    read: TextReader | None = None,
    torch: dict[str, object] | None = None,
) -> dict[str, object]:
    """Describe the host, naming the moment in the run it was described at."""

    operating_system, cpu = _host_facts(
        platform_name,
        _run_text if run is None else run,
        _read_text if read is None else read,
    )
    document: dict[str, object] = {
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "context": context,
        "os": operating_system.to_dict(),
        "cpu": cpu.to_dict(),
        "build_interpreter": _build_interpreter(),
    }
    if torch is not None:
        document["torch"] = torch
    return document


def probe_torch(
    *,
    interpreter: str | Path | None = None,
    timeout: float = TORCH_TIMEOUT_SECONDS,
    runner: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """Ask Torch what the CPU supports, from a process that may not survive it.

    Torch is imported in a child precisely because importing it is one of the
    things that kills a packaging run, and a base fingerprint that dies with it
    is worth nothing.
    """

    command = [str(interpreter or sys.executable), "-c", TORCH_PROBE]
    try:
        completed = runner(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return {"unavailable": f"the Torch probe did not answer within {timeout:g}s"}
    except OSError as error:
        return {"unavailable": f"could not start the Torch probe: {error}"}

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return {
            "unavailable": (
                f"the Torch probe exited with status {completed.returncode}: "
                + (detail[-1] if detail else "no output")
            )
        }
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"unavailable": "the Torch probe printed no report"}
    return report if isinstance(report, dict) else {"unavailable": "unexpected Torch report"}


def _host_facts(
    platform_name: str, run: TextRunner, read: TextReader
) -> tuple[Facts, Facts]:
    """Route to the probes the host in question actually answers."""

    if platform_name == "darwin":
        return darwin_facts(run)
    if platform_name.startswith("linux"):
        return linux_facts(read)
    if platform_name == "win32":
        return windows_facts(run)
    return _portable_os(), _portable_cpu()


def darwin_facts(run: TextRunner) -> tuple[Facts, Facts]:
    """Read macOS's own answers for the product build and the CPU brand."""

    operating_system = _portable_os()
    operating_system.record("name", lambda: run([SW_VERS, "-productName"]))
    operating_system.record("product_version", lambda: run([SW_VERS, "-productVersion"]))
    operating_system.record("build", lambda: run([SW_VERS, "-buildVersion"]))

    cpu = _portable_cpu()
    cpu.record("model", lambda: run([SYSCTL, "-n", "machdep.cpu.brand_string"]))
    cpu.record("vendor", lambda: run([SYSCTL, "-n", "machdep.cpu.vendor"]))
    cpu.record("physical_cores", lambda: _as_count(run([SYSCTL, "-n", "hw.physicalcpu"])))
    return operating_system, cpu


def linux_facts(read: TextReader) -> tuple[Facts, Facts]:
    """Read the two files a Linux host describes itself with."""

    operating_system = _portable_os()
    operating_system.record("name", lambda: _os_release_field(read, "PRETTY_NAME"))

    cpu = _portable_cpu()
    cpu.record("model", lambda: _cpuinfo_field(read, "model name"))
    cpu.record("vendor", lambda: _cpuinfo_field(read, "vendor_id"))
    cpu.record("physical_cores", lambda: _as_count(_cpuinfo_field(read, "cpu cores")))
    return operating_system, cpu


def windows_facts(run: TextRunner) -> tuple[Facts, Facts]:
    """Read one CIM query covering both the operating system and the CPU."""

    records: dict[str, dict[str, object]] | None = None
    reason = ""
    try:
        records = _windows_records(run)
    except ProbeError as error:
        reason = str(error)

    def field_of(group: str, name: str) -> Callable[[], object]:
        def probe() -> object:
            if records is None:
                raise ProbeError(reason)
            value = records.get(group, {}).get(name)
            if value in (None, ""):
                raise ProbeError(f"the CIM query returned no {group} {name}")
            return value

        return probe

    operating_system = _portable_os()
    operating_system.record("name", field_of("os", "Caption"))
    operating_system.record("product_version", field_of("os", "Version"))
    operating_system.record("build", field_of("os", "BuildNumber"))
    # The operating system's own bitness, which is not the processor's:
    # ``cpu.architecture`` answers that one.
    operating_system.record("architecture", field_of("os", "OSArchitecture"))

    cpu = _portable_cpu()
    cpu.record("model", field_of("cpu", "Name"))
    cpu.record("vendor", field_of("cpu", "Manufacturer"))
    cpu.record("physical_cores", field_of("cpu", "NumberOfCores"))
    return operating_system, cpu


def _windows_records(run: TextRunner) -> dict[str, dict[str, object]]:
    """Parse the one JSON document the CIM query prints."""

    payload = run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_QUERY])
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProbeError(f"the CIM query printed no JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ProbeError("the CIM query printed an unexpected document")
    records: dict[str, dict[str, object]] = {}
    for group in ("os", "cpu"):
        found = parsed.get(group)
        records[group] = found if isinstance(found, dict) else {}
    return records


def _portable_os() -> Facts:
    """What every host reports without being asked anything platform-specific."""

    return Facts(
        values={
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "platform": platform.platform(),
        }
    )


def _portable_cpu() -> Facts:
    """Architecture and logical cores, which the standard library always knows."""

    facts = Facts(values={"architecture": platform.machine()})
    facts.record("logical_cores", _logical_cores)
    return facts


def _logical_cores() -> int:
    count = os.cpu_count()
    if count is None:
        raise ProbeError("os.cpu_count() reported no answer")
    return count


def _build_interpreter() -> dict[str, object]:
    """Describe the interpreter that runs the build, never the frozen one.

    A frozen bundle reports its own embedded versions through the self-check;
    conflating the two is how a report ends up describing the wrong Python.
    """

    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        # Always false in a packaging job, and stated rather than assumed: the
        # frozen side of the comparison is the self-check's own report.
        "frozen": bool(getattr(sys, "frozen", False)),
    }


def _os_release_field(read: TextReader, key: str) -> str:
    for line in _lines(read, OS_RELEASE_PATH):
        name, separator, value = line.partition("=")
        if separator and name.strip() == key:
            return value.strip().strip('"')
    raise ProbeError(f"{OS_RELEASE_PATH} carries no {key}")


def _cpuinfo_field(read: TextReader, key: str) -> str:
    for line in _lines(read, CPUINFO_PATH):
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip()
    raise ProbeError(f"{CPUINFO_PATH} carries no {key}")


def _lines(read: TextReader, path: str) -> list[str]:
    try:
        return read(path).splitlines()
    except OSError as error:
        raise ProbeError(f"could not read {path}: {error}") from error


def _as_count(value: object) -> int:
    try:
        return int(str(value).strip())
    except ValueError as error:
        raise ProbeError(f"{value!r} is not a core count") from error


def _run_text(command: Sequence[str]) -> str:
    """Run one bounded local probe and return what it said, or why it did not."""

    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ProbeError(f"{command[0]} did not answer in time") from error
    except OSError as error:
        raise ProbeError(f"could not run {command[0]}: {error}") from error

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        raise ProbeError(
            f"{command[0]} exited with status {completed.returncode}: "
            + (detail[-1] if detail else "no output")
        )
    answer = completed.stdout.strip()
    if not answer:
        raise ProbeError(f"{command[0]} answered with nothing")
    return answer


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Describe the host a packaging run is happening on"
    )
    parser.add_argument(
        "--context",
        default="unspecified",
        help="what point of the run this fingerprint was taken at",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the document here, for a run that retains diagnostics",
    )
    parser.add_argument(
        "--with-torch",
        action="store_true",
        help="add what Torch reports about the CPU, from a subprocess of its own",
    )
    parser.add_argument(
        "--torch-timeout",
        type=float,
        default=TORCH_TIMEOUT_SECONDS,
        help="seconds to allow the Torch probe",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print the fingerprint, and write it beside the run's other evidence."""

    args = _build_parser().parse_args(None if argv is None else list(argv))
    torch = probe_torch(timeout=args.torch_timeout) if args.with_torch else None
    document = collect_fingerprint(args.context, torch=torch)

    rendered = json.dumps(document, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CPUINFO_PATH",
    "OS_RELEASE_PATH",
    "PROBE_TIMEOUT_SECONDS",
    "TORCH_PROBE",
    "TORCH_TIMEOUT_SECONDS",
    "WINDOWS_QUERY",
    "Facts",
    "ProbeError",
    "collect_fingerprint",
    "darwin_facts",
    "linux_facts",
    "main",
    "probe_torch",
    "windows_facts",
]
