"""What the machine running the tests is actually allowed to do.

A capability the operating system withholds belongs in a skip with a reason,
not in a failure: an unprivileged desktop and a CI runner have to disagree
about what ran, never about what passed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _symlinks_available() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        try:
            (root / "link").symlink_to(root / "target", target_is_directory=True)
        except (NotImplementedError, OSError):
            return False
    return True


#: Windows creates a symbolic link only for an elevated or developer-mode
#: session. Everything the matrix runs on POSIX always can.
requires_symlinks = pytest.mark.skipif(
    not _symlinks_available(),
    reason="creating a symbolic link needs a privilege this session does not have",
)

__all__ = ["requires_symlinks"]
