"""Which of the three suites a run collects, decided before anything imports.

Portable tests are the engine, the contracts, the tooling, and every platform
decision exercised through a double: they run on any host, with none of the
desktop runtime installed. The native suites run the real thing -- Qt, Qt
WebEngine, pywebview, spawned children, the OS adapters -- and the packaged
suite runs the frozen product. Each needs a different machine, so each is
selectable on its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_TESTS = Path(__file__).parent / "tests"

#: The directory each non-portable suite owns. Everything else is portable.
SUITE_ROOTS = {"native": _TESTS / "native", "packaged": _TESTS / "packaged"}

SUITES = ("all", "portable", *SUITE_ROOTS)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--suite",
        choices=SUITES,
        default="all",
        help="collect one suite instead of every one (default: all)",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Drop the suites this run did not ask for, before they are imported.

    A marker cannot do this. Deselection by marker happens after the module has
    been imported, and a native module imports Qt, pywebview, or the OCR
    runtime at module scope -- which is the very thing a portable run is meant
    to prove it does without.
    """

    suite = str(config.getoption("--suite"))
    if suite == "all":
        return None
    # A directory on the way to a suite root still has to be descended into.
    if any(collection_path in root.parents for root in SUITE_ROOTS.values()):
        return None
    return _suite_of(collection_path) != suite


def _suite_of(path: Path) -> str:
    for name, root in SUITE_ROOTS.items():
        if path == root or root in path.parents:
            return name
    return "portable"
