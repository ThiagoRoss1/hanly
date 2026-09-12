"""The macOS half of the permission seam, with the system calls replaced.

These tests never read or change the developer machine's real privacy
settings and never open System Settings: the framework calls and the ``open``
invocation are the boundary, and each one is substituted.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys

import pytest
from hanly_app import permissions_darwin
from hanly_app.permissions import (
    Permission,
    PermissionActionFailed,
    PermissionState,
    UnsupportedPermission,
)

from tests.hanly_fixtures.unchecked import unchecked


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> permissions_darwin.DarwinPermissionProbe:
    """A probe whose four platform calls all fail loudly until scripted."""

    def unscripted(*_args: object) -> bool:
        raise AssertionError("the test did not script this platform call")

    for name in (
        "screen_recording_granted",
        "request_screen_recording",
        "accessibility_trusted",
        "request_accessibility",
    ):
        monkeypatch.setattr(permissions_darwin, name, unscripted)
    monkeypatch.setattr(permissions_darwin, "open_privacy_settings", unscripted)
    return permissions_darwin.DarwinPermissionProbe()


def test_screen_recording_reads_the_preflight_answer(
    probe: permissions_darwin.DarwinPermissionProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(permissions_darwin, "screen_recording_granted", lambda: True)
    assert probe.state(Permission.SCREEN_RECORDING) is PermissionState.GRANTED

    monkeypatch.setattr(permissions_darwin, "screen_recording_granted", lambda: False)
    assert probe.state(Permission.SCREEN_RECORDING) is PermissionState.REQUIRED


def test_accessibility_reads_whether_the_process_is_trusted(
    probe: permissions_darwin.DarwinPermissionProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(permissions_darwin, "accessibility_trusted", lambda: True)
    assert probe.state(Permission.ACCESSIBILITY) is PermissionState.GRANTED

    monkeypatch.setattr(permissions_darwin, "accessibility_trusted", lambda: False)
    assert probe.state(Permission.ACCESSIBILITY) is PermissionState.REQUIRED


def test_a_granted_request_never_sends_the_user_to_system_settings(
    probe: permissions_darwin.DarwinPermissionProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Permission] = []
    monkeypatch.setattr(permissions_darwin, "request_screen_recording", lambda: True)
    monkeypatch.setattr(permissions_darwin, "open_privacy_settings", opened.append)

    assert probe.request(Permission.SCREEN_RECORDING) is PermissionState.GRANTED
    assert opened == []


def test_a_request_the_system_did_not_grant_opens_the_exact_pane(
    probe: permissions_darwin.DarwinPermissionProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The system prompt appears once; the pane is the route that always works."""

    opened: list[Permission] = []
    monkeypatch.setattr(permissions_darwin, "request_accessibility", lambda: False)
    monkeypatch.setattr(permissions_darwin, "open_privacy_settings", opened.append)

    assert probe.request(Permission.ACCESSIBILITY) is PermissionState.REQUIRED
    assert opened == [Permission.ACCESSIBILITY]


def test_both_panes_address_a_privacy_control_rather_than_settings_at_large() -> None:
    assert permissions_darwin.PRIVACY_PANES == {
        Permission.SCREEN_RECORDING: (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
        ),
        Permission.ACCESSIBILITY: (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        ),
    }


def test_opening_a_pane_launches_the_url_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append(command)
        assert kwargs["check"] is True

    monkeypatch.setattr(permissions_darwin.subprocess, "run", fake_run)

    permissions_darwin.open_privacy_settings(Permission.ACCESSIBILITY)

    assert calls == [
        [
            "/usr/bin/open",
            permissions_darwin.PRIVACY_PANES[Permission.ACCESSIBILITY],
        ]
    ]


def test_a_failed_settings_launch_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user clicked Grant, so a silent no-op is the one unacceptable answer.

    The message is what reaches the Control Center, so it names the pane to
    open by hand rather than surfacing the launcher's exit status.
    """

    def fake_run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(permissions_darwin.subprocess, "run", fake_run)

    with pytest.raises(PermissionActionFailed, match="System Settings"):
        permissions_darwin.open_privacy_settings(Permission.ACCESSIBILITY)


@pytest.mark.skipif(sys.platform != "darwin", reason="the frameworks are macOS-only")
def test_the_real_frameworks_answer_both_questions_without_prompting() -> None:
    """The ctypes bridge itself: both calls return a boolean, whatever it is."""

    assert isinstance(permissions_darwin.screen_recording_granted(), bool)
    assert isinstance(permissions_darwin.accessibility_trusted(), bool)


@pytest.mark.skipif(sys.platform != "darwin", reason="the frameworks are macOS-only")
def test_the_real_accessibility_options_have_one_prompt_entry() -> None:
    options = permissions_darwin._prompt_options()
    assert options is not None
    core_foundation = permissions_darwin._framework("CoreFoundation")
    core_foundation.CFDictionaryGetCount.restype = ctypes.c_long
    core_foundation.CFDictionaryGetCount.argtypes = [ctypes.c_void_p]

    try:
        assert core_foundation.CFDictionaryGetCount(options) == 1
    finally:
        core_foundation.CFRelease(options)


def test_a_permission_macos_does_not_gate_is_refused(
    probe: permissions_darwin.DarwinPermissionProbe,
) -> None:
    class _Other:
        value = "camera"

    with pytest.raises(UnsupportedPermission):
        probe.state(unchecked(_Other()))
    with pytest.raises(UnsupportedPermission):
        probe.request(unchecked(_Other()))
