"""Measure stage-label continuity in the real page with controlled update states."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from hanly_app.cli import _leave
from hanly_app.control_center.bridge import ControlCenterBridge
from hanly_app.control_center.host import ControlCenterHost

REPORT_PREFIX = "APP_LAB_UI "


class _ScriptedBridge(ControlCenterBridge):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.stage = "idle"
        self.completed = 0

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        with self.lock:
            stage, completed = self.stage, self.completed
        state["updates"] = {
            "status": stage,
            "message": {
                "idle": "Ready",
                "inspecting": "Checking installed files",
                "downloading": "Downloading update",
            }[stage],
            "progress": {
                "phase": stage,
                "completed": completed,
                "total": 100,
                "fraction": completed / 100,
            },
            "cancellable": True,
        }
        return state

    def change(self, stage: str, completed: int) -> None:
        with self.lock:
            self.stage, self.completed = stage, completed


_INSTALL = """
(() => {
  window.__labStarts = [];
  document.getElementById('update-panel').addEventListener('animationstart', event => {
    if (event.target.classList.contains('think-text'))
      window.__labStarts.push(event.animationName);
  });
  document.querySelector('#nav [data-page="updates"]').click();
  return true;
})()
"""

_MEASURE = """
(() => {
  const panel = document.getElementById('update-panel');
  const label = panel.querySelector('.think-text');
  if (!label) return null;
  const previous = window.__labLabel;
  window.__labLabel = label;
  return JSON.stringify({
    retained: previous === label,
    percent: panel.querySelector('.update-percent').textContent,
    starts: window.__labStarts.slice(),
    iterations: getComputedStyle(label).animationIterationCount,
    reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
    visible: label.getBoundingClientRect().height > 0,
    mode: panel.dataset.updateMode,
    label: label.textContent
  });
})()
"""


def main() -> None:
    """Open only an isolated probe window; emit allowlisted synthetic measurements."""

    bridge = _ScriptedBridge()
    host = ControlCenterHost(bridge)
    report: dict[str, Any] = {"steps": [], "errors": []}

    def drive() -> None:
        try:
            deadline = time.monotonic() + 30
            while not host.evaluate("!!document.querySelector('#nav [data-page=updates]')"):
                if time.monotonic() > deadline:
                    raise TimeoutError
                time.sleep(0.1)
            host.evaluate(_INSTALL)
            for stage, completed in (
                ("inspecting", 10),
                ("inspecting", 20),
                ("inspecting", 30),
                ("downloading", 40),
            ):
                bridge.change(stage, completed)
                deadline = time.monotonic() + 10
                while True:
                    measured = host.evaluate(_MEASURE)
                    sample = json.loads(measured) if measured else None
                    expected_label = (
                        "Checking installed files"
                        if stage == "inspecting"
                        else "Downloading update"
                    )
                    if (
                        sample
                        and sample["percent"] == f"{completed}%"
                        and sample["label"] == expected_label
                    ):
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError
                    time.sleep(0.1)
                # Include several real refreshes, not just the render that changed progress.
                time.sleep(1.6)
                sample = json.loads(host.evaluate(_MEASURE))
                sample.pop("label")
                sample["stage"] = stage
                report["steps"].append(sample)
            bridge.change("idle", 0)
            time.sleep(0.8)
            report["idle_mode"] = host.evaluate(
                "document.getElementById('update-panel').dataset.updateMode"
            )
        except Exception as error:
            report["errors"].append(type(error).__name__)
        finally:
            host.close()

    host.run(on_started=drive)
    print(REPORT_PREFIX + json.dumps(report), flush=True)
    _leave(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
