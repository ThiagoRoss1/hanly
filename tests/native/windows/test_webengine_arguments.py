"""The Windows-only abort Chromium raises when it is handed no program name."""

from __future__ import annotations

from pathlib import Path

from tests.hanly_fixtures.capabilities import require_modules
from tests.hanly_fixtures.webengine_probe import LOADED_MARKER, run_webengine_child


def test_an_empty_argument_list_still_aborts_chromium_on_windows(tmp_path: Path) -> None:
    """The defect this fix exists for, kept executable rather than anecdotal.

    Only the Windows abort code is asserted here; every other platform asserts
    the successful contract in the shared suite instead of a native exception
    number.
    """

    require_modules("PyQt6.QtWebEngineWidgets")

    child = run_webengine_child(tmp_path, "empty-argv")

    assert child.returncode != 0
    assert LOADED_MARKER not in child.stdout
    assert "the program name is not passed" in child.stderr
