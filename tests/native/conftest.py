"""Which native cases this host can run at all, and what marks them.

``shared`` holds real Qt, real child-process, and real window behavior that
every platform must satisfy. Each OS directory beside it holds that platform's
own adapters, and only the matching host ever imports one.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hanly_app.qt_popup import QtPopupView
    from PyQt6.QtWidgets import QApplication

#: The directory whose adapters this host actually has.
HOST_DIRECTORY = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")

#: Behavior every platform owes, regardless of which host is running.
SHARED_DIRECTORY = "shared"

_ROOT = Path(__file__).parent


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Keep another platform's adapters out of this host's collection.

    Before the import rather than after: a Windows-only module imports a
    Windows-only adapter, and a marker is consulted only once that has already
    happened.
    """

    if collection_path.parent != _ROOT or not collection_path.is_dir():
        return None
    return collection_path.name not in (SHARED_DIRECTORY, HOST_DIRECTORY)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker("native")


@pytest.fixture(scope="session")
def qt_application() -> QApplication:
    """The one ``QApplication`` a process may have, shared by every Qt case.

    Imported here rather than at module scope: this conftest also configures
    the native cases that assert they never loaded Qt at all.
    """

    from PyQt6.QtWidgets import QApplication

    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


@pytest.fixture
def popup_view(qt_application: QApplication) -> Iterator[QtPopupView]:
    from hanly_app.qt_popup import QtPopupView

    popup = QtPopupView()
    yield popup
    popup.close()
