"""Per-user locations Hanly reads and writes, on every supported platform.

These live apart from the composition root so early bootstrap -- diagnostics
in particular -- can resolve a writable directory before importing the
desktop, Qt, or the update stack.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

#: File name a packaged installation uses for its runtime configuration.
RUNTIME_CONFIG_NAME = "runtime.json"

#: Diagnostics directory name, kept beside the settings file rather than in a
#: platform log location so one profile directory holds the whole session.
LOG_DIRECTORY_NAME = "logs"

#: Where a macOS program sits inside the application that contains it.
_BUNDLE_PROGRAM_PARENTS = ("MacOS", "Contents")


def macos_bundle_root(executable: str | Path | None = None) -> Path | None:
    """Return the ``.app`` a macOS program runs from, or ``None``.

    The answer is read from the path's shape rather than from the current
    platform, so the two things that care - where configuration may be written,
    and what an update replaces - agree about one installation.
    """

    program = Path(sys.executable if executable is None else executable).resolve()
    directory = program.parent
    if directory.name != _BUNDLE_PROGRAM_PARENTS[0]:
        return None
    contents = directory.parent
    if contents.name != _BUNDLE_PROGRAM_PARENTS[1] or contents.parent.suffix != ".app":
        return None
    return contents.parent


def default_app_config_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user V1 settings path without adding a platform package."""

    env = os.environ if environment is None else environment
    local = env.get("LOCALAPPDATA")
    if local:
        return (Path(local).expanduser() / "Hanly" / "config.json").resolve()
    xdg = env.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return (root / "hanly" / "config.json").resolve()


def default_runtime_config_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user runtime configuration path beside the settings file."""

    return default_app_config_path(environment).with_name(RUNTIME_CONFIG_NAME)


def default_log_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user diagnostics directory beside the settings file."""

    return default_app_config_path(environment).parent / LOG_DIRECTORY_NAME


def discover_runtime_config(
    environment: Mapping[str, str] | None = None,
    executable: str | Path | None = None,
) -> Path | None:
    """Find a runtime configuration without requiring a command-line argument.

    A packaged installation ships or writes ``runtime.json`` beside the
    executable; a developer or an updated installation keeps it with the
    per-user settings. Explicit ``--runtime-config`` still wins over both.
    """

    candidates = [default_runtime_config_path(environment)]
    # Beside the executable of a macOS application is inside the signed bundle,
    # which an update replaces; such an installation uses the per-user path only.
    if macos_bundle_root(executable) is None:
        beside_executable = (
            Path(sys.executable if executable is None else executable).resolve().parent
            / RUNTIME_CONFIG_NAME
        )
        candidates.insert(0, beside_executable)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


__all__ = [
    "LOG_DIRECTORY_NAME",
    "RUNTIME_CONFIG_NAME",
    "default_app_config_path",
    "default_log_directory",
    "default_runtime_config_path",
    "discover_runtime_config",
    "macos_bundle_root",
]
