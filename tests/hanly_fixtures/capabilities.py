"""What the machine running the tests is actually allowed to do.

A capability the operating system withholds belongs in a skip with a reason,
not in a failure: an unprivileged desktop and a CI runner have to disagree
about what ran, never about what passed.

That holds for an ordinary developer run. It does not hold for the job whose
entire purpose is the capability in question -- a native or packaged gate that
skips everything is a green run proving nothing. Those jobs set the variable
below, and every reason becomes a failure instead.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path
from typing import NoReturn

import pytest

#: Set by the CI jobs that exist to run the native suites, and by the build
#: job that exists to run the packaged suite.
REQUIRE_NATIVE = "HANLY_REQUIRE_NATIVE"
REQUIRE_PACKAGED = "HANLY_REQUIRE_PACKAGED"


def unavailable(
    reason: str, *, required_by: str = REQUIRE_NATIVE, module_level: bool = False
) -> NoReturn:
    """Skip for want of a capability, or fail where that want is the defect.

    ``module_level`` is for a guard that runs while the module is being
    imported, which is where a suite has to decide before it imports the
    runtime it is about to exercise.
    """

    if os.environ.get(required_by) == "1":
        pytest.fail(f"{reason} (required by {required_by})")
    pytest.skip(reason, allow_module_level=module_level)


def require_modules(
    *names: str, required_by: str = REQUIRE_NATIVE, module_level: bool = False
) -> None:
    """Require installed packages without importing them.

    Presence rather than an import: several native tests assert that the
    process running them never loaded the desktop runtime, and importing it to
    decide whether to run would be the thing they rule out.
    """

    missing = [name for name in names if find_spec(name) is None]
    if missing:
        unavailable(
            f"the desktop runtime is not installed: {', '.join(missing)}",
            required_by=required_by,
            module_level=module_level,
        )


def require_display(*, required_by: str = REQUIRE_NATIVE) -> None:
    """Require a session that can actually open a window.

    Only Linux advertises a display it may not have; macOS and Windows answer
    for their own window server, and a session without one fails there rather
    than lying about it.
    """

    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return
    unavailable("this needs a real display session", required_by=required_by)


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

__all__ = [
    "REQUIRE_NATIVE",
    "REQUIRE_PACKAGED",
    "require_display",
    "require_modules",
    "requires_symlinks",
    "unavailable",
]
