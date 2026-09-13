"""What the packaging host fingerprint records, and what it refuses to invent."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest

from tools.native_host_fingerprint import (
    CPUINFO_PATH,
    OS_RELEASE_PATH,
    TORCH_PROBE,
    ProbeError,
    collect_fingerprint,
    darwin_facts,
    linux_facts,
    probe_torch,
    windows_facts,
)

CPUINFO = """\
processor\t: 0
vendor_id\t: GenuineIntel
model name\t: Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz
cpu cores\t: 2
"""

OS_RELEASE = """\
NAME="Ubuntu"
PRETTY_NAME="Ubuntu 24.04.3 LTS"
VERSION_ID="24.04"
"""

WINDOWS_RECORDS = {
    "os": {
        "Caption": "Microsoft Windows Server 2022 Datacenter",
        "Version": "10.0.20348",
        "BuildNumber": "20348",
    },
    "cpu": {
        "Name": "AMD EPYC 7763 64-Core Processor",
        "Manufacturer": "AuthenticAMD",
        "NumberOfCores": 2,
        "NumberOfLogicalProcessors": 4,
    },
}


def _answers(replies: dict[str, str]):
    """A probe runner that answers by command name, and refuses anything else."""

    def run(command: Sequence[str]) -> str:
        key = " ".join(command[1:]) if len(command) > 1 else command[0]
        if key not in replies:
            raise ProbeError(f"{command[0]} has no {key}")
        return replies[key]

    return run


def _reader(files: dict[str, str]):
    def read(path: str) -> str:
        if path not in files:
            raise OSError(2, "No such file or directory")
        return files[path]

    return read


def test_macos_reports_the_product_build_and_the_cpu_brand() -> None:
    operating_system, cpu = darwin_facts(
        _answers(
            {
                "-productName": "macOS",
                "-productVersion": "15.6",
                "-buildVersion": "24G84",
                "-n machdep.cpu.brand_string": "Apple M1 Pro",
                "-n hw.physicalcpu": "8",
            }
        )
    )

    assert operating_system.values["build"] == "24G84"
    assert cpu.values["model"] == "Apple M1 Pro"
    assert cpu.values["physical_cores"] == 8


def test_a_field_the_host_withholds_carries_its_reason_not_a_default() -> None:
    """Apple silicon has no ``machdep.cpu.vendor``, and "unknown" would read as
    a fact. The reason is what tells the next reader the probe was even tried."""

    _, cpu = darwin_facts(_answers({"-n machdep.cpu.brand_string": "Apple M1 Pro"}))

    assert cpu.values["vendor"] is None
    assert "machdep.cpu.vendor" in cpu.unavailable["vendor"]
    assert cpu.values["physical_cores"] is None
    assert "hw.physicalcpu" in cpu.unavailable["physical_cores"]


def test_linux_reads_the_two_files_a_host_describes_itself_with() -> None:
    operating_system, cpu = linux_facts(
        _reader({OS_RELEASE_PATH: OS_RELEASE, CPUINFO_PATH: CPUINFO})
    )

    assert operating_system.values["name"] == "Ubuntu 24.04.3 LTS"
    assert cpu.values["vendor"] == "GenuineIntel"
    assert str(cpu.values["model"]).startswith("Intel(R) Xeon(R)")
    assert cpu.values["physical_cores"] == 2


def test_a_linux_host_without_the_metadata_files_says_so() -> None:
    operating_system, cpu = linux_facts(_reader({}))

    assert OS_RELEASE_PATH in operating_system.unavailable["name"]
    assert CPUINFO_PATH in cpu.unavailable["model"]


def test_windows_reads_one_cim_query_for_both_groups() -> None:
    operating_system, cpu = windows_facts(lambda _: json.dumps(WINDOWS_RECORDS))

    assert operating_system.values["build"] == "20348"
    assert cpu.values["model"] == "AMD EPYC 7763 64-Core Processor"
    assert cpu.values["vendor"] == "AuthenticAMD"
    assert cpu.values["physical_cores"] == 2


def test_a_failed_cim_query_leaves_every_field_with_the_same_reason() -> None:
    def refuse(_: Sequence[str]) -> str:
        raise ProbeError("powershell.exe exited with status 1: access denied")

    operating_system, cpu = windows_facts(refuse)

    assert "access denied" in operating_system.unavailable["name"]
    assert "access denied" in cpu.unavailable["model"]
    # The portable facts still stand; one refused query is not the whole host.
    assert cpu.values["architecture"]


def test_a_cim_query_that_is_not_json_is_not_read_as_data() -> None:
    operating_system, _ = windows_facts(lambda _: "Get-CimInstance : not recognized")

    assert "no JSON" in operating_system.unavailable["name"]


def _completed(
    returncode: int, stdout: str = "", stderr: str = ""
) -> Callable[..., subprocess.CompletedProcess[str]]:
    process = subprocess.CompletedProcess(["python"], returncode, stdout, stderr)
    return lambda *_, **__: process


def test_the_torch_probe_reports_what_the_cpu_supports() -> None:
    answer = {"version": "2.4.1", "cpu_capability": "AVX2", "mkldnn": True}

    assert probe_torch(runner=_completed(0, json.dumps(answer))) == answer


@pytest.mark.parametrize(
    ("runner", "expected"),
    [
        (_completed(1, stderr="Illegal instruction"), "Illegal instruction"),
        (_completed(0), "no report"),
    ],
)
def test_a_torch_probe_that_fails_costs_a_field_not_the_document(
    runner: Callable[..., subprocess.CompletedProcess[str]], expected: str
) -> None:
    assert expected in str(probe_torch(runner=runner)["unavailable"])


def test_a_hanging_torch_probe_is_bounded() -> None:
    def runner(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    assert "did not answer within" in str(probe_torch(runner=runner)["unavailable"])


def test_the_torch_probe_runs_in_a_child_that_may_not_survive_it() -> None:
    """Importing Torch is one of the things that ends a packaging run, so the
    base fingerprint must already be complete when it is attempted."""

    source = (Path(__file__).parents[1] / "tools" / "native_host_fingerprint.py").read_text(
        encoding="utf-8"
    )

    assert "import torch" not in source.replace(TORCH_PROBE, "")
    assert "-c" in source


def test_this_host_reports_the_fields_a_crash_report_needs() -> None:
    document = collect_fingerprint("test")

    def group(name: str) -> dict[str, object]:
        return cast("dict[str, object]", document[name])

    assert document["context"] == "test"
    assert group("os")["system"]
    assert group("cpu")["architecture"]
    assert group("cpu")["logical_cores"]
    # The build interpreter is labelled as such: a frozen bundle reports its
    # own embedded versions through the self-check, and the two are not one.
    assert group("build_interpreter")["version"] == ".".join(
        str(part) for part in sys.version_info[:3]
    )
    assert "torch" not in document


def test_the_fingerprint_collects_no_environment_or_process_inventory() -> None:
    """A diagnostic that dumps the environment is a secret leak, and a process
    inventory describes everything on the machine except the build."""

    assert "environ" not in json.dumps(collect_fingerprint("test"))

    source = (Path(__file__).parents[1] / "tools" / "native_host_fingerprint.py").read_text(
        encoding="utf-8"
    )
    assert "os.environ" not in source
    assert set(re.findall(r"Win32_\w+", source)) == {"Win32_OperatingSystem", "Win32_Processor"}
