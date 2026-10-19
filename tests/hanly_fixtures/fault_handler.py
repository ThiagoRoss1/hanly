"""Temporarily silence handled native exceptions without losing crash diagnostics."""

from __future__ import annotations

import faulthandler
import sys
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def quiet_fault_handler() -> Iterator[None]:
    """Suspend fault reporting and restore its enabled state on the original stderr."""

    enabled = faulthandler.is_enabled()
    stderr = sys.__stderr__
    faulthandler.disable()
    try:
        yield
    finally:
        if enabled:
            # pytest's tee-sys stderr has no fileno; the original stream does.
            assert stderr is not None, "fault reporting requires the original stderr"
            faulthandler.enable(file=stderr)
