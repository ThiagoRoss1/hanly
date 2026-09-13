"""The Control Center page's own decision about when to keep asking for state.

Nothing pushes a snapshot to the window: the runtime finishes preparing on a
worker thread and the page only learns about it by asking again. These tests
run the packaged script in Node against scripted snapshots, because the bug
they cover -- a page that never notices the runtime became ready -- lives in
the script's timer lifecycle rather than in any Python seam.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from hanly_app.control_center import load_control_center_assets

_HARNESS = Path(__file__).parent / "hanly_fixtures" / "assets" / "control_center_harness.js"
_NODE = shutil.which("node")

if _NODE is None and os.environ.get("CI", "").lower() in {"1", "true"}:
    raise RuntimeError("Node.js is required for the Control Center tests in CI")
pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="the Control Center script is exercised in Node, which is not installed",
)


#: The shell derives its activity from more than readiness, but a fixture that
#: only varies the runtime phase gets the settled activity that phase implies.
_ACTIVITY_FOR_PHASE = {"ready": "stopped", "failed": "error"}

#: What a platform with no privacy gates reports, and the shape macOS fills in.
NO_PERMISSIONS: dict[str, Any] = {"supported": False, "items": []}


def _permission(identifier: str, label: str, state: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "label": label,
        "state": state,
        "granted": state == "granted",
        "requirement": f"{label} is needed.",
        "restart_note": "" if state == "granted" else "Hanly may need restarting.",
    }


def _macos_permissions(screen_recording: str, accessibility: str) -> dict[str, Any]:
    return {
        "supported": True,
        "items": [
            _permission("screen_recording", "Screen Recording", screen_recording),
            _permission("accessibility", "Accessibility", accessibility),
        ],
    }


def _snapshot(
    phase: str,
    *,
    message: str = "",
    update_status: str = "idle",
    permissions: dict[str, Any] | None = None,
    activity: str | None = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "app": {
            "state": "new",
            "activity": activity or _ACTIVITY_FOR_PHASE.get(phase, "preparing"),
            "detail": detail,
            "capture_running": False,
            "capture_mode": "full_monitor",
            "target": "cursor",
            "region": None,
            "targets": [],
        },
        "config": {"hover_delay_ms": 150, "hotkey": "ctrl+shift+space"},
        "runtime": {
            "ocr_provider": "EasyOCR",
            "resources": [],
            "diagnostics": [],
            "log_path": None,
            "status": {"phase": phase, "stage": "", "message": message},
        },
        "updates": {
            "available": False,
            "status": update_status,
            "message": "",
            "resources": [],
            "active_resource_id": None,
            "progress": None,
            "application": None,
            "restart_required": False,
        },
        "permissions": NO_PERMISSIONS if permissions is None else permissions,
    }


def _run(
    snapshots: list[dict[str, Any]],
    tmp_path: Path,
    *,
    actions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Render the packaged script against ``snapshots`` and return its trace."""

    page = tmp_path / "control_center.js"
    page.write_text(load_control_center_assets().javascript, encoding="utf-8")
    scripted = tmp_path / "snapshots.json"
    scripted.write_text(json.dumps(snapshots), encoding="utf-8")
    assert _NODE is not None
    command = [_NODE, str(_HARNESS), str(page), str(scripted)]
    if actions is not None:
        scripted_actions = tmp_path / "actions.json"
        scripted_actions.write_text(json.dumps(actions), encoding="utf-8")
        command.append(str(scripted_actions))

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    trace: list[dict[str, Any]] = json.loads(completed.stdout)
    return trace


def test_preparing_runtime_becomes_ready_without_the_user_doing_anything(
    tmp_path: Path,
) -> None:
    trace = _run(
        [
            _snapshot("preparing", message="Loading the lookup engine..."),
            _snapshot("ready", message="Hanly is ready."),
        ],
        tmp_path,
    )

    assert trace[0]["timer_running"] is True
    assert trace[0]["runtime_state"] == "preparing"
    assert trace[0]["start_disabled"] is True

    assert trace[-1]["runtime_state"] == "ready"
    assert trace[-1]["start_disabled"] is False
    assert trace[-1]["timer_running"] is False


def test_failing_runtime_is_reported_and_then_stops_the_refresh(tmp_path: Path) -> None:
    trace = _run(
        [
            _snapshot("preparing"),
            _snapshot("failed", message="krdict is unavailable"),
        ],
        tmp_path,
    )

    assert trace[-1]["runtime_state"] == "failed"
    assert trace[-1]["runtime_message"] == "krdict is unavailable"
    assert trace[-1]["retry_hidden"] is False
    assert trace[-1]["timer_running"] is False


def test_a_settled_runtime_never_starts_a_refresh(tmp_path: Path) -> None:
    trace = _run([_snapshot("ready", message="Hanly is ready.")], tmp_path)

    assert trace == [trace[0]]
    assert trace[0]["timer_running"] is False
    assert trace[0]["intervals_created"] == 0


def test_update_work_keeps_refreshing_while_the_runtime_is_already_ready(
    tmp_path: Path,
) -> None:
    trace = _run(
        [
            _snapshot("ready", update_status="downloading"),
            _snapshot("ready", update_status="installing"),
            _snapshot("ready", update_status="success"),
        ],
        tmp_path,
    )

    assert trace[0]["timer_running"] is True
    assert trace[0]["check_disabled"] is True
    assert trace[-1]["timer_running"] is False
    assert trace[-1]["check_disabled"] is False


def test_a_ready_runtime_does_not_cancel_the_refresh_an_update_still_needs(
    tmp_path: Path,
) -> None:
    """The regression: two renderers each owning the one timer.

    Whichever ran last decided, so a ready runtime cancelled update polling and
    an idle updater cancelled readiness polling.
    """

    trace = _run(
        [
            _snapshot("preparing", update_status="downloading"),
            _snapshot("ready", update_status="downloading"),
            _snapshot("preparing", update_status="idle"),
            _snapshot("ready", update_status="idle"),
        ],
        tmp_path,
    )

    assert [entry["timer_running"] for entry in trace] == [True, True, True, False]
    assert trace[-1]["runtime_state"] == "ready"


def test_one_interval_is_created_and_released_for_a_whole_refresh_run(
    tmp_path: Path,
) -> None:
    trace = _run(
        [
            _snapshot("preparing"),
            _snapshot("preparing"),
            _snapshot("preparing"),
            _snapshot("ready"),
        ],
        tmp_path,
    )

    assert trace[-1]["intervals_created"] == 1
    assert trace[-1]["clears_requested"] == 1
    assert trace[-1]["timer_running"] is False


def test_a_platform_without_privacy_gates_renders_no_permission_panel(
    tmp_path: Path,
) -> None:
    trace = _run([_snapshot("ready")], tmp_path)

    assert trace[0]["permissions_hidden"] is True
    assert trace[0]["permission_rows"] == []


def test_granted_permissions_are_shown_without_offering_a_grant_action(
    tmp_path: Path,
) -> None:
    trace = _run(
        [_snapshot("ready", permissions=_macos_permissions("granted", "granted"))],
        tmp_path,
    )

    assert trace[0]["permissions_hidden"] is False
    assert [(row["permission"], row["badge"], row["grant_offered"]) for row in
            trace[0]["permission_rows"]] == [
        ("screen_recording", "Granted", False),
        ("accessibility", "Granted", False),
    ]
    # Nothing is pending, so a settled page with every grant in place is quiet.
    assert trace[0]["timer_running"] is False


def test_a_missing_grant_is_named_and_offers_the_action_that_fixes_it(
    tmp_path: Path,
) -> None:
    trace = _run(
        [_snapshot("ready", permissions=_macos_permissions("required", "granted"))],
        tmp_path,
    )

    rows = {row["permission"]: row for row in trace[0]["permission_rows"]}
    assert rows["screen_recording"]["state"] == "required"
    assert rows["screen_recording"]["badge"] == "Required"
    assert rows["screen_recording"]["grant_offered"] is True
    assert "Hanly may need restarting." in rows["screen_recording"]["detail"]
    assert rows["accessibility"]["grant_offered"] is False
    # A permission the user has not been asked about yet is not something the
    # page should poll for on its own.
    assert trace[0]["timer_running"] is False
    assert trace[0]["intervals_created"] == 0


def test_an_unreadable_grant_is_reported_as_unknown_rather_than_denied(
    tmp_path: Path,
) -> None:
    trace = _run(
        [_snapshot("ready", permissions=_macos_permissions("unknown", "granted"))],
        tmp_path,
    )

    row = trace[0]["permission_rows"][0]
    assert row["badge"] == "Unknown"
    assert row["grant_offered"] is True


def test_clicking_grant_watches_for_the_change_and_stops_once_it_lands(
    tmp_path: Path,
) -> None:
    """The grant happens in System Settings, which never tells the page."""

    required = _snapshot("ready", permissions=_macos_permissions("required", "granted"))
    granted = _snapshot("ready", permissions=_macos_permissions("granted", "granted"))
    trace = _run(
        [required, required, required, granted],
        tmp_path,
        actions=[{"step": 0, "grant": "screen_recording"}],
    )

    assert trace[0]["timer_running"] is False
    assert trace[0]["intervals_created"] == 0
    # The click is what starts the watching, and it keeps going while the grant
    # is still missing.
    assert trace[1]["timer_running"] is True
    assert trace[1]["permission_rows"][0]["badge"] == "Required"

    assert trace[-1]["permission_rows"][0]["badge"] == "Granted"
    assert trace[-1]["timer_running"] is False
    assert trace[-1]["intervals_created"] == 1
    assert trace[-1]["clears_requested"] == 1


def test_a_grant_the_user_never_makes_stops_being_watched_for(tmp_path: Path) -> None:
    """Otherwise a declined permission polls the system for the whole session."""

    required = _snapshot("ready", permissions=_macos_permissions("required", "granted"))
    trace = _run(
        [required] * 90,
        tmp_path,
        actions=[{"step": 0, "grant": "screen_recording"}],
    )

    assert trace[-1]["timer_running"] is False
    assert trace[-1]["permission_rows"][0]["badge"] == "Required"
    assert len(trace) < 90


def test_a_bridge_that_never_answers_is_reported_rather_than_rendered(
    tmp_path: Path,
) -> None:
    """A window whose parent has gone must not show a convincing snapshot.

    The page owns a fallback state so it can render before the first answer.
    Presenting that fallback as the runtime is how a dead bridge became a
    Hanly that looked new and idle rather than disconnected.
    """

    trace = _run([{"__reject__": "Hanly is no longer available."}], tmp_path)

    assert trace[0]["connection_hidden"] is False
    assert trace[0]["connection_state"] == "Connection lost"
    assert trace[0]["app_state"] == "Connection lost"
    assert trace[0]["reconnect_hidden"] is False
    # An unreachable parent is not something to poll for.
    assert trace[0]["timer_running"] is False


def test_the_explicit_retry_reconnects_without_starting_a_poll(tmp_path: Path) -> None:
    trace = _run(
        [
            {"__reject__": "Hanly is no longer available."},
            _snapshot("ready", message="Hanly is ready."),
        ],
        tmp_path,
        actions=[{"step": 0, "click": "reconnect"}],
    )

    assert trace[0]["connection_state"] == "Connection lost"
    assert trace[-1]["connection_hidden"] is True
    assert trace[-1]["runtime_state"] == "ready"
    assert trace[-1]["timer_running"] is False


def test_lost_connection_stops_an_already_running_poll(tmp_path: Path) -> None:
    trace = _run(
        [_snapshot("preparing"), {"__reject__": "Hanly closed before answering."}],
        tmp_path,
    )

    assert trace[0]["timer_running"] is True
    assert trace[-1]["connection_state"] == "Connection lost"
    assert trace[-1]["timer_running"] is False
