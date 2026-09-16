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
from hanly_app.app_inventory import write_xattr
from hanly_app.app_manifest import MATERIAL_XATTR_PREFIXES

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


#: Whether this host answers for the permission bits an update sets and reads
#: back. Windows does not: ``chmod`` there moves a read-only flag and nothing
#: else, so a mode a case asserts would be a mode nothing wrote.
POSIX_MODES = os.name == "posix"

requires_posix_modes = pytest.mark.skipif(
    not POSIX_MODES, reason="only a POSIX host carries the permission bits this is about"
)


def require_posix_tree(platform: str) -> None:
    """Require a host that can hold a macOS or Linux product tree as itself.

    Windows reports neither those permission bits nor the symbolic links a
    framework is built from, so a tree built there would be a different tree -
    and a case reading it back would prove something else.
    """

    if platform != "windows" and not POSIX_MODES:
        pytest.skip("a macOS or Linux tree is only itself on a POSIX host")


def _material_xattrs_available() -> bool:
    """Whether this host can carry the attribute a signed macOS build has.

    Written under the product's own prefix rather than a portable one: Linux
    confines an unprivileged attribute to the ``user.`` namespace and refuses
    every other name, which is the answer this asks for.
    """

    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe"
        probe.write_bytes(b"")
        try:
            write_xattr(probe, f"{MATERIAL_XATTR_PREFIXES[0]}Probe", b"probe")
        except (AttributeError, NotImplementedError, OSError):
            return False
    return True


#: Only macOS carries a build's signature material. Everywhere else a tree is
#: built unsigned, and the cases whose subject is that material do not run.
MATERIAL_XATTRS = _material_xattrs_available()

requires_material_xattrs = pytest.mark.skipif(
    not MATERIAL_XATTRS,
    reason="this host cannot carry a signed build's material attributes",
)


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
    "MATERIAL_XATTRS",
    "POSIX_MODES",
    "REQUIRE_NATIVE",
    "REQUIRE_PACKAGED",
    "require_display",
    "require_modules",
    "require_posix_tree",
    "requires_material_xattrs",
    "requires_posix_modes",
    "requires_symlinks",
    "unavailable",
]
