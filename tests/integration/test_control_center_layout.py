"""The Control Center's own geometry, measured in the engine that renders it.

The page is exercised elsewhere against a stubbed DOM, which can prove what it
renders but never where anything lands. Horizontal overflow, wrapped action
rows, and controls pushed outside the window are geometry, so this one runs the
real window and reads the boxes back out of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: Every width the window can actually be, plus the narrower viewports display
#: scaling and page zoom produce inside it. 780 is the one that overflowed.
_WIDTHS = (400, 640, 760, 780, 900, 1039, 1040, 1080)

#: Controls that must stay inside the window at every one of those widths.
_CONTROLS = (
    "start-capture",
    "stop-capture",
    "select-area",
    "hotkey",
    "hover-hotkey",
    "capture-hotkey",
    "hover-activation",
    "lookup-preload",
    "hover-delay",
)

_CHILD_TIMEOUT_SECONDS = 300

_CHILD_PROGRAM = '''
import json
import sys
import time

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_host import ControlCenterHost

REPORT_PREFIX = "LAYOUT_REPORT "
WIDTHS = json.loads(sys.argv[1])
CONTROLS = json.dumps(json.loads(sys.argv[2]))

MEASURE = """
(function () {
  var doc = document.documentElement;
  var boxes = {};
  CONTROL_IDS.forEach(function (id) {
    var box = document.getElementById(id).getBoundingClientRect();
    boxes[id] = {
      left: Math.round(box.left),
      right: Math.round(box.right),
      top: Math.round(box.top),
      bottom: Math.round(box.bottom)
    };
  });
  return JSON.stringify({
    inner: window.innerWidth,
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    boxes: boxes
  });
}())
""".replace("CONTROL_IDS", CONTROLS)

host = ControlCenterHost(ControlCenterBridge(), width=1080, height=760)
report = {"measurements": [], "errors": []}


def started():
    try:
        time.sleep(2.5)
        window = host.window
        for width in WIDTHS:
            window.resize(width, 760)
            time.sleep(1.0)
            report["measurements"].append(
                {"requested": width, "measured": json.loads(host.evaluate(MEASURE))}
            )
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        host.close()


host.run(on_started=started)
print(REPORT_PREFIX + json.dumps(report), flush=True)
'''


def _skip_without_a_desktop() -> None:
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    pytest.importorskip("webview")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("the Control Center layout needs a real desktop session")


def test_every_supported_width_fits_without_scrolling_sideways(tmp_path: Path) -> None:
    """Two nested two-column grids wanted about 854px inside a 760px window.

    Between the minimum window and that, the page scrolled sideways and the
    controls on the right went past the edge.
    """

    _skip_without_a_desktop()

    program = tmp_path / "layout_child.py"
    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [
            sys.executable,
            str(program),
            json.dumps(list(_WIDTHS)),
            json.dumps(list(_CONTROLS)),
        ],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    marker = "LAYOUT_REPORT "
    line = next(
        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
    )
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    report = json.loads(line[len(marker) :])

    assert report["errors"] == []
    assert len(report["measurements"]) == len(_WIDTHS)
    for measurement in report["measurements"]:
        measured = measurement["measured"]
        width = measurement["requested"]
        assert measured["scrollWidth"] <= measured["clientWidth"], (
            f"the page scrolls sideways at {width}px: "
            f"{measured['scrollWidth']} > {measured['clientWidth']}"
        )
        for name, box in measured["boxes"].items():
            assert box["left"] >= 0, f"{name} starts off-screen at {width}px"
            assert box["right"] <= measured["clientWidth"], (
                f"{name} runs past the right edge at {width}px"
            )
            assert box["bottom"] > box["top"], f"{name} is collapsed at {width}px"
