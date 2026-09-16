"""Extended attributes on macOS, which CPython does not expose.

``os.listxattr`` and its neighbours are Linux-only, and macOS is the platform
that actually needs them: a signed bundle can keep a detached signature in
``com.apple.cs.*``, and a copy reassembled without those attributes no longer
verifies. So the four calls are bound here directly.

Every call passes ``XATTR_NOFOLLOW``. An updater that read attributes through a
link would describe whatever the link points at, and one that wrote through a
link would write outside the tree it is assembling.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from pathlib import Path
from threading import Lock

#: Operate on the link itself rather than on what it points at.
XATTR_NOFOLLOW = 0x0001

#: The name list and one value are both bounded: an attribute Hanly carries is
#: a few kilobytes, and a hostile one is not something to allocate for.
MAX_NAME_BYTES = 64 * 1024
MAX_VALUE_BYTES = 1024 * 1024

_lock = Lock()
_library: _ExtendedAttributes | None = None


class _ExtendedAttributes:
    """The four libc entry points, typed once rather than at each call."""

    def __init__(self, libc: ctypes.CDLL) -> None:
        libc.listxattr.restype = ctypes.c_ssize_t
        libc.listxattr.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        libc.getxattr.restype = ctypes.c_ssize_t
        libc.getxattr.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        libc.setxattr.restype = ctypes.c_int
        libc.setxattr.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        libc.removexattr.restype = ctypes.c_int
        libc.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._libc = libc

    def names(self, path: bytes) -> tuple[str, ...]:
        size = self._libc.listxattr(path, None, 0, XATTR_NOFOLLOW)
        _require_success(size, path)
        if size == 0:
            return ()
        if size > MAX_NAME_BYTES:
            raise OSError(f"{path!r} lists more extended attributes than this build reads")
        buffer = ctypes.create_string_buffer(size)
        written = self._libc.listxattr(path, buffer, size, XATTR_NOFOLLOW)
        _require_success(written, path)
        raw = buffer.raw[:written]
        return tuple(name.decode("utf-8") for name in raw.split(b"\0") if name)

    def value(self, path: bytes, name: bytes) -> bytes:
        size = self._libc.getxattr(path, name, None, 0, 0, XATTR_NOFOLLOW)
        _require_success(size, path)
        if size == 0:
            return b""
        if size > MAX_VALUE_BYTES:
            raise OSError(f"{name!r} is larger than an attribute this build reads")
        buffer = ctypes.create_string_buffer(size)
        written = self._libc.getxattr(path, name, buffer, size, 0, XATTR_NOFOLLOW)
        _require_success(written, path)
        return buffer.raw[:written]

    def write(self, path: bytes, name: bytes, value: bytes) -> None:
        if len(value) > MAX_VALUE_BYTES:
            raise OSError(f"{name!r} is larger than an attribute this build writes")
        status = self._libc.setxattr(path, name, value, len(value), 0, XATTR_NOFOLLOW)
        _require_success(status, path)

    def remove(self, path: bytes, name: bytes) -> None:
        _require_success(self._libc.removexattr(path, name, XATTR_NOFOLLOW), path)


def list_names(path: Path) -> tuple[str, ...]:
    """Every extended attribute on one file, link, or directory."""

    return _attributes().names(_encode(path))


def read_value(path: Path, name: str) -> bytes:
    """One attribute's exact bytes."""

    return _attributes().value(_encode(path), name.encode("utf-8"))


def write_value(path: Path, name: str, value: bytes) -> None:
    """Set one attribute, replacing whatever it held."""

    _attributes().write(_encode(path), name.encode("utf-8"), value)


def remove_value(path: Path, name: str) -> None:
    """Drop one attribute, if it is there."""

    _attributes().remove(_encode(path), name.encode("utf-8"))


def _attributes() -> _ExtendedAttributes:
    global _library

    with _lock:
        if _library is not None:
            return _library
        found = ctypes.util.find_library("c")
        if found is None:
            raise OSError("the C library could not be located")
        _library = _ExtendedAttributes(ctypes.CDLL(found, use_errno=True))
        return _library


def _encode(path: Path) -> bytes:
    return str(path).encode("utf-8")


def _require_success(status: int, path: bytes) -> None:
    if status >= 0:
        return
    errno = ctypes.get_errno()
    raise OSError(errno, f"extended attribute call failed for {path!r}")


__all__ = [
    "MAX_NAME_BYTES",
    "MAX_VALUE_BYTES",
    "XATTR_NOFOLLOW",
    "list_names",
    "read_value",
    "remove_value",
    "write_value",
]
