"""Filesystem fixtures that mean the same thing on POSIX and Windows."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

#: Windows also gets a junction: the link it creates without a privilege, and
#: one ``Path.is_symlink`` does not report.
LINK_KINDS = ("symlink", "junction") if sys.platform == "win32" else ("symlink",)
_ERROR_PRIVILEGE_NOT_HELD = 1314


@pytest.fixture(params=LINK_KINDS)
def link_directory(request: pytest.FixtureRequest) -> Callable[[Path, Path], None]:
    """Make ``link`` a directory link of this case's kind pointing at ``target``."""

    kind = request.param

    def create(link: Path, target: Path) -> None:
        if kind == "junction":
            _junction(link, target)
            return
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            if getattr(error, "winerror", None) == _ERROR_PRIVILEGE_NOT_HELD:
                pytest.skip("a symbolic link needs Developer Mode or elevation on Windows")
            raise

    return create


@pytest.fixture
def unreadable() -> Callable[[Path], AbstractContextManager[None]]:
    """A context in which this user cannot list ``path``.

    ``chmod(0)`` only sets the read-only attribute on Windows, so there the
    listing right is denied through the folder's access control list instead.
    """

    @contextmanager
    def deny(path: Path) -> Iterator[None]:
        if sys.platform == "win32":
            user = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
            _icacls(path, "/deny", f"{user}:(OI)(CI)(RD)")
            try:
                yield
            finally:
                _icacls(path, "/remove:d", user)
        else:
            path.chmod(0)
            try:
                yield
            finally:
                path.chmod(0o755)

    return deny


def _junction(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def _icacls(path: Path, *arguments: str) -> None:
    subprocess.run(["icacls", str(path), *arguments], check=True, capture_output=True)
