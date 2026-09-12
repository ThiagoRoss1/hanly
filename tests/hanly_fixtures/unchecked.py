"""One named way to hand a public boundary a value its type forbids.

A boundary that raises on the wrong type is part of its contract, so proving
it needs a call the type checker would otherwise reject. Naming that moment
keeps the violation greppable and self-explaining, where a suppression comment
only names the error code -- and goes quietly dead when the code changes.
"""

from __future__ import annotations

from typing import Any


def unchecked(value: object) -> Any:
    """Return ``value`` as an unchecked type, for a deliberate misuse test."""

    return value


__all__ = ["unchecked"]
