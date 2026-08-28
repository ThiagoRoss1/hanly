"""Developer tooling for the production KRDICT resource."""

from __future__ import annotations

import sys


def configure_utf8_output() -> None:
    """Keep Korean CLI output readable when a console defaults to a legacy codepage."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
