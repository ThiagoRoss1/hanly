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

    beside_executable = (
        Path(sys.executable if executable is None else executable).resolve().parent
        / RUNTIME_CONFIG_NAME
    )
    for candidate in (beside_executable, default_runtime_config_path(environment)):
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
]
