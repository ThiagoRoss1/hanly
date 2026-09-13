"""The frozen product's own suite: it needs a built bundle, not a checkout."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HOST_DIRECTORY = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
SHARED_DIRECTORY = "shared"

_ROOT = Path(__file__).parent


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if collection_path.parent != _ROOT or not collection_path.is_dir():
        return None
    return collection_path.name not in (SHARED_DIRECTORY, HOST_DIRECTORY)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker("packaged")
