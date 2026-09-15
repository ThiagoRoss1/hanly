"""What the native smokes are told when the host will not answer.

An empty process list and a refused ``ps`` look identical to a caller that
does not distinguish them, and they mean opposite things: one says the child
was retired, the other says nobody looked. A sandbox that denied ``/bin/ps``
is what made this worth stating.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

import pytest

from tests.hanly_fixtures.process_probe import (
    IGNORED_COMMANDS,
    PROBE_UNAVAILABLE,
    PROCESS_ROWS_PROGRAM,
    PS_FORMAT,
)


def _probe() -> dict[str, Any]:
    """Load the inventory the way the smoke children do: as source, not import."""

    namespace: dict[str, Any] = {}
    exec(PROCESS_ROWS_PROGRAM, namespace)  # noqa: S102 - this is the fixture's contract
    return namespace


def test_this_host_lists_the_process_asking_the_question() -> None:
    rows = _probe()["process_rows"]()

    pids = {int(row.split(None, 1)[0]) for row in rows if row.split()}
    assert os.getpid() in pids


def test_a_probe_tool_that_is_not_there_is_never_an_empty_inventory() -> None:
    namespace = _probe()

    with pytest.raises(namespace[PROBE_UNAVAILABLE], match="is not on this host"):
        namespace["_rows_from"](["hanly-no-such-probe"], list)


def test_a_probe_that_refuses_is_never_an_empty_inventory() -> None:
    namespace = _probe()

    with pytest.raises(namespace[PROBE_UNAVAILABLE], match="status 3"):
        namespace["_rows_from"]([sys.executable, "-c", "raise SystemExit(3)"], list)


def test_the_inventory_reports_a_command_too_long_for_a_terminal() -> None:
    """``ps`` truncates to 80 columns when stdout is a pipe, which cut
    multiprocessing's resource tracker down to "python -c from multi" and made
    a process every caller ignores read as a leaked window.

    Asserted on every platform though only ``ps`` ever truncated: a caller
    identifies what it may ignore by what is in the command, so a detail that
    is not the whole command is the defect wherever it comes from.
    """

    marker = "hanly_truncation_probe_" + "x" * 90
    program = f"# {marker}\nimport time\n\ntime.sleep(30)\n"
    child = subprocess.Popen([sys.executable, "-c", program])
    try:
        rows = [row for row in _probe()["process_rows"]() if str(child.pid) in row]
        assert rows, "the probe did not report the child it was given"
        assert any(marker in row for row in rows), f"command truncated: {rows}"
    finally:
        child.kill()
        child.wait(timeout=30)


def test_every_caller_recognizes_the_rows_it_is_meant_to_ignore() -> None:
    """The markers live beside the command they filter. A hand-written copy in
    each child is how one of them kept matching ``ps -axo`` after the flags
    changed."""

    namespace = _probe()

    assert namespace["IGNORED_COMMANDS"] == IGNORED_COMMANDS
    assert PS_FORMAT in IGNORED_COMMANDS
    assert PS_FORMAT in PROCESS_ROWS_PROGRAM
