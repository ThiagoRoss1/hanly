"""Select the focused React DOM check used by the Lab UI scenario."""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "apps" / "desktop"
UI_TESTS = {
    "CC-LIFECYCLE": "waits for the /popup event listener before marking its window ready",
    "CC-CONTROLS": "persists an appearance setting and reflects the acknowledged state",
    "CAPTURE-CHOICE": "lets a user cancel the capture-scope dialog without changing settings",
    "HOVER-POPUP": "ignores stale popup events and reports measured geometry for the current entry",
    "CC-UPDATE-STAGE": (
        "updates transfer progress in place and keeps reduced-motion rules"
    ),
}


def command(test_name: str) -> list[str]:
    """Return a focused Vitest command without launching a desktop window."""

    node = shutil.which("node")
    entry = FRONTEND_ROOT / "node_modules" / "vitest" / "vitest.mjs"
    if node is None or not entry.is_file():
        raise FileNotFoundError("Node and the desktop Vitest dependencies are required")
    return [
        node,
        str(entry),
        "run",
        "--config",
        str(FRONTEND_ROOT / "vitest.ui.config.ts"),
        str(FRONTEND_ROOT / "tests" / "ui" / "desktop-pages.test.tsx"),
        "-t",
        test_name,
    ]
