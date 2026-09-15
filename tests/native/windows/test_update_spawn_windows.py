"""Starting the update helper at all, which is not a thing a mock can prove.

``spawn_detached`` has one job and two ways to fail it silently: the process
does not start, or it starts and does nothing. Both leave the application
closed, the update staged, and no error anywhere, so the only useful test runs
a real PowerShell and reads what it wrote.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

from hanly_app.app_update_handoff import spawn_detached


def _await(path: Path, timeout: float = 30.0) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if path.is_file():
            return True
        sleep(0.2)
    return False


def test_a_spawned_helper_actually_runs_its_script(tmp_path: Path) -> None:
    """``DETACHED_PROCESS`` gives the child no console, and a PowerShell with
    no console exits zero having run none of its body. The swap would then
    never happen, with nothing anywhere to say why."""

    marker = tmp_path / "ran.txt"

    spawn_detached(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"Set-Content -LiteralPath '{marker}' -Value ran",
        ],
        tmp_path,
    )

    assert _await(marker), "the spawned helper never ran its script"


def test_a_spawned_helper_outlives_the_process_that_started_it(tmp_path: Path) -> None:
    """It is started precisely to wait for that process to exit."""

    marker = tmp_path / "outlived.txt"
    script = tmp_path / "parent.py"
    # The path reaches the child as an argument rather than as text rendered
    # into its source, for the same reason the real handoff does it that way.
    script.write_text(
        "\n".join(
            (
                "import sys",
                "from pathlib import Path",
                "from hanly_app.app_update_handoff import spawn_detached",
                "marker = sys.argv[1]",
                "spawn_detached(",
                "    [",
                "        'powershell.exe', '-NoProfile', '-NonInteractive',",
                "        '-ExecutionPolicy', 'Bypass', '-Command',",
                "        'Start-Sleep -Seconds 3; Set-Content -LiteralPath'",
                "        + chr(32) + chr(39) + marker + chr(39) + ' -Value outlived',",
                "    ],",
                "    Path(marker).parent,",
                ")",
            )
        ),
        encoding="utf-8",
    )

    subprocess.run([sys.executable, str(script), str(marker)], check=True, timeout=60)

    assert _await(marker), "the helper died with the process that started it"
