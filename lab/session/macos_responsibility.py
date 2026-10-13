"""Read macOS process responsibility for opt-in Lab attribution only."""

from __future__ import annotations

import ctypes
import sys
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _query() -> Any:
    if sys.platform != "darwin":
        return None
    try:
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        function = library.responsibility_get_pid_responsible_for_pid
    except (OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_int32]
    function.restype = ctypes.c_int32
    return function


def responsible_pid(pid: int) -> int | None:
    """Return the owning app PID, or unknown when the diagnostic SPI is absent."""

    query = _query()
    if query is None or pid <= 0:
        return None
    result = int(query(pid))
    return result if result > 0 else None


__all__ = ["responsible_pid"]
