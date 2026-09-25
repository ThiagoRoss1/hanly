"""The Control Center's choice lists, driven in the engine that renders them.

The page's own logic runs elsewhere against a stubbed DOM that has no layout,
no focus and no events of its own. Opening, keyboard navigation, dismissal and
the native select staying the page's value all need the real Chromium page.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.hanly_fixtures.capabilities import require_display, require_modules

_CHILD_TIMEOUT_SECONDS = 300

_CHILD_PROGRAM = '''
import json
import time

from hanly_app.control_center import ControlCenterBridge
from hanly_app.control_center_host import ControlCenterHost

REPORT_PREFIX = "COMBO_REPORT "
host = ControlCenterHost(ControlCenterBridge(), width=1080, height=760)
report = {"steps": {}, "errors": []}

SETUP = """
(function () {
  window.__changes = [];
  document.getElementById("lookup-preload").addEventListener("change", function (e) {
    window.__changes.push(e.target.value);
  });
  return "ok";
}())
"""

STATE = """
(function () {
  var root = document.getElementById("lookup-preload-combo");
  var button = root.querySelector(".combo-button");
  var list = root.querySelector(".combo-list");
  var select = document.getElementById("lookup-preload");
  return JSON.stringify({
    open: root.hasAttribute("data-open"),
    expanded: button.getAttribute("aria-expanded"),
    role: button.getAttribute("role"),
    label: button.textContent.trim(),
    value: select.value,
    selectVisible: select.getBoundingClientRect().height > 0,
    options: list.children.length,
    selected: Array.prototype.filter.call(list.children, function (item) {
      return item.getAttribute("aria-selected") === "true";
    }).map(function (item) { return item.textContent; }),
    active: button.getAttribute("aria-activedescendant"),
    changes: window.__changes,
    focused: document.activeElement === button,
    listStyle: getComputedStyle(list).visibility,
    ocr: Array.prototype.map.call(
      document.getElementById("ocr-backend").options, function (o) { return o.value; })
  });
}())
"""

KEY = """
(function (key) {
  var button = document.querySelector("#lookup-preload-combo .combo-button");
  button.focus();
  button.dispatchEvent(new KeyboardEvent("keydown", {key: key, bubbles: true}));
  return "ok";
})"""


def state(name):
    time.sleep(0.4)
    report["steps"][name] = json.loads(host.evaluate(STATE))


def started():
    try:
        time.sleep(2.5)
        host.evaluate(SETUP)
        state("closed")
        host.evaluate('document.querySelector("#lookup-preload-combo .combo-button").click()')
        state("clicked_open")
        host.evaluate(
            'document.body.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true}))'
        )
        state("outside_closed")
        host.evaluate(KEY + '("ArrowDown")')
        state("key_open")
        host.evaluate(KEY + '("ArrowDown")')
        host.evaluate(KEY + '("Enter")')
        state("key_chosen")
        host.evaluate(KEY + '("Enter")')
        host.evaluate(KEY + '("Escape")')
        state("escaped")
        host.evaluate('document.getElementById("lookup-preload").value = "on_demand"')
        state("set_by_page")
        host.evaluate('document.getElementById("lookup-preload").disabled = true')
        state("disabled")
        report["disabled_button"] = host.evaluate(
            'document.querySelector("#lookup-preload-combo .combo-button").disabled'
        )
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        host.close()


host.run(on_started=started)
print(REPORT_PREFIX + json.dumps(report), flush=True)
'''


def _report(tmp_path: Path) -> dict[str, object]:
    require_modules("PyQt6.QtWebEngineWidgets", "webview")
    require_display()
    program = tmp_path / "combo_child.py"
    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program)],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )
    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    marker = "COMBO_REPORT "
    line = next((item for item in child.stdout.splitlines() if item.startswith(marker)), None)
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
    report: dict[str, object] = json.loads(line[len(marker) :])
    return report


def test_the_combobox_opens_chooses_and_dismisses_like_a_control(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report["errors"] == []
    steps = report["steps"]
    assert isinstance(steps, dict)

    closed = steps["closed"]
    assert closed["role"] == "combobox" and closed["expanded"] == "false"
    assert closed["open"] is False and closed["listStyle"] == "hidden"
    assert closed["selectVisible"] is False, "the native select is not what is shown"
    assert closed["options"] == 3
    assert closed["selected"] == [closed["label"]]

    assert steps["clicked_open"]["open"] is True
    assert steps["clicked_open"]["expanded"] == "true"
    assert steps["outside_closed"]["open"] is False

    key_open = steps["key_open"]
    assert key_open["open"] is True and key_open["active"]

    chosen = steps["key_chosen"]
    assert chosen["open"] is False and chosen["focused"] is True
    assert chosen["value"] != closed["value"]
    assert chosen["changes"] == [chosen["value"]], "one change event, from the select"
    assert chosen["label"] == chosen["selected"][0]

    escaped = steps["escaped"]
    assert escaped["open"] is False
    assert escaped["value"] == chosen["value"], "Escape chooses nothing"

    # The page re-renders the persisted choice over a direct write; whichever
    # value the select ends up holding, the combobox shows exactly that one.
    set_by_page = steps["set_by_page"]
    labels = {
        "when_capture_starts": "Load while watching the screen",
        "always": "Keep loaded",
        "on_demand": "Load only for a lookup",
    }
    assert set_by_page["label"] == labels[set_by_page["value"]]
    assert report["disabled_button"] is True


def test_the_recognizer_list_offers_only_what_this_machine_runs(tmp_path: Path) -> None:
    report = _report(tmp_path)
    steps = report["steps"]
    assert isinstance(steps, dict)
    offered = steps["closed"]["ocr"]
    if sys.platform == "darwin":
        assert offered == ["auto", "vision", "easyocr"]
    else:
        assert offered == ["auto", "easyocr"]
