"""What the native smokes are told when the host will not answer.

An empty process list and a refused ``ps`` look identical to a caller that
does not distinguish them, and they mean opposite things: one says the child
was retired, the other says nobody looked. A sandbox that denied ``/bin/ps``
is what made this worth stating.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

from tests.hanly_fixtures.process_probe import PROBE_UNAVAILABLE, PROCESS_ROWS_PROGRAM


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
