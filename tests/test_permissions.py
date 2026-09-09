"""The platform-neutral half of the permission seam.

Nothing here touches the developer machine's own privacy settings: the probe
is the seam, and every state a real macOS can report is exercised through it.
"""

from __future__ import annotations

import pytest
from hanly_app.permissions import (
    HOVER_PERMISSIONS,
    START_CAPTURE_PERMISSIONS,
    Permission,
    PermissionService,
    PermissionState,
    UnsupportedPermission,
    create_permission_service,
    missing_permission_refusal,
    permission_from_id,
)


class _Probe:
    """A scripted stand-in for the platform calls."""

    def __init__(self, **states: PermissionState) -> None:
        self.states = {Permission(name): state for name, state in states.items()}
        self.reads: list[Permission] = []
        self.requests: list[Permission] = []
        self.grants_on_request = True
        self.raise_on_read: Exception | None = None

    def state(self, permission: Permission) -> PermissionState:
        self.reads.append(permission)
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.states.get(permission, PermissionState.REQUIRED)

    def request(self, permission: Permission) -> PermissionState:
        self.requests.append(permission)
        if self.grants_on_request:
            self.states[permission] = PermissionState.GRANTED
        return self.states.get(permission, PermissionState.REQUIRED)


def _service(probe: _Probe, *, cache_seconds: float = 0.0) -> PermissionService:
    return PermissionService(
        probe,
        permissions=(Permission.SCREEN_RECORDING, Permission.ACCESSIBILITY),
        cache_seconds=cache_seconds,
    )


def test_every_platform_answer_normalizes_into_one_explicit_state() -> None:
    probe = _Probe(
        screen_recording=PermissionState.GRANTED,
        accessibility=PermissionState.REQUIRED,
    )

    snapshot = {status.permission: status for status in _service(probe).statuses()}

    assert snapshot[Permission.SCREEN_RECORDING].state is PermissionState.GRANTED
    assert snapshot[Permission.SCREEN_RECORDING].granted is True
    assert snapshot[Permission.ACCESSIBILITY].state is PermissionState.REQUIRED
    assert snapshot[Permission.ACCESSIBILITY].granted is False


def test_a_probe_that_cannot_answer_reports_unknown_rather_than_denied() -> None:
    probe = _Probe()
    probe.raise_on_read = OSError("the framework is unavailable")

    states = {status.state for status in _service(probe).statuses()}

    assert states == {PermissionState.UNKNOWN}


def test_an_unknown_permission_counts_as_missing() -> None:
    """Starting on a grant Hanly could not read is how capture half-works."""

    probe = _Probe()
    probe.raise_on_read = OSError("the framework is unavailable")

    missing = _service(probe).missing(START_CAPTURE_PERMISSIONS)

    assert [status.permission for status in missing] == [
        Permission.SCREEN_RECORDING,
        Permission.ACCESSIBILITY,
    ]


def test_missing_reports_only_the_permissions_the_caller_asked_about() -> None:
    probe = _Probe(
        screen_recording=PermissionState.REQUIRED,
        accessibility=PermissionState.GRANTED,
    )

    assert _service(probe).missing(HOVER_PERMISSIONS) == ()
    assert [status.permission for status in _service(probe).missing()] == [
        Permission.SCREEN_RECORDING
    ]


def test_granting_a_permission_transitions_the_reported_state() -> None:
    probe = _Probe(screen_recording=PermissionState.REQUIRED)
    service = _service(probe, cache_seconds=60.0)
    assert service.missing(START_CAPTURE_PERMISSIONS) != ()

    granted = service.request(Permission.SCREEN_RECORDING)

    assert granted.state is PermissionState.GRANTED
    assert probe.requests == [Permission.SCREEN_RECORDING]
    # The long cache must not survive the request that may have changed it.
    assert Permission.SCREEN_RECORDING not in [
        status.permission for status in service.missing(START_CAPTURE_PERMISSIONS)
    ]


def test_a_refused_request_leaves_the_permission_reported_as_missing() -> None:
    probe = _Probe(accessibility=PermissionState.REQUIRED)
    probe.grants_on_request = False
    service = _service(probe)

    assert service.request(Permission.ACCESSIBILITY).state is PermissionState.REQUIRED
    assert [status.permission for status in service.missing(HOVER_PERMISSIONS)] == [
        Permission.ACCESSIBILITY
    ]


def test_statuses_are_cached_so_a_polling_window_does_not_hammer_the_system() -> None:
    probe = _Probe(
        screen_recording=PermissionState.GRANTED,
        accessibility=PermissionState.GRANTED,
    )
    service = _service(probe, cache_seconds=60.0)

    service.statuses()
    service.statuses()
    service.statuses()
    assert len(probe.reads) == 2

    service.invalidate()
    service.statuses()
    assert len(probe.reads) == 4


def test_platforms_without_privacy_gates_report_and_require_nothing() -> None:
    service = create_permission_service("win32")

    assert service.supported is False
    assert service.statuses() == ()
    assert service.missing(START_CAPTURE_PERMISSIONS) == ()
    with pytest.raises(UnsupportedPermission):
        service.request(Permission.SCREEN_RECORDING)


def test_darwin_is_the_platform_that_manages_both_grants() -> None:
    pytest.importorskip("hanly_app.permissions_darwin")
    service = create_permission_service("darwin")

    assert service.supported is True
    assert [status.permission for status in service.statuses()] == [
        Permission.SCREEN_RECORDING,
        Permission.ACCESSIBILITY,
    ]


def test_a_permission_named_by_the_ui_is_resolved_or_rejected() -> None:
    assert permission_from_id("accessibility") is Permission.ACCESSIBILITY
    for value in ("camera", "", None, 3):
        with pytest.raises(UnsupportedPermission):
            permission_from_id(value)


def test_the_refusal_names_the_grants_the_settings_pane_uses() -> None:
    probe = _Probe()
    missing = _service(probe).missing(START_CAPTURE_PERMISSIONS)

    assert missing_permission_refusal(missing) == (
        "Hanly needs Screen Recording and Accessibility access "
        "before it can watch the screen."
    )
