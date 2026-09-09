"""Platform-neutral permission policy, status caching, and UI data.

The macOS system calls live in :mod:`hanly_app.permissions_darwin`; other
platforms expose no invented permission requirements.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from time import monotonic
from typing import Protocol


class UnsupportedPermission(RuntimeError):
    """Raised when a permission is asked for that this platform does not manage."""


class PermissionActionFailed(RuntimeError):
    """Raised when a grant flow could not be started, with what to do instead."""


class Permission(Enum):
    """The privacy grants Hanly Desktop actually depends on."""

    SCREEN_RECORDING = "screen_recording"
    ACCESSIBILITY = "accessibility"


class PermissionState(Enum):
    """The app-facing state every platform answer is normalized into.

    ``UNKNOWN`` is deliberately distinct from ``REQUIRED``: a probe that could
    not run says nothing about the user's choice, and telling somebody to grant
    a permission they already granted is worse than admitting Hanly cannot tell.
    """

    GRANTED = "granted"
    REQUIRED = "required"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    """How one permission is named and explained to the user."""

    permission: Permission
    label: str
    requirement: str
    restart_note: str = ""


@dataclass(frozen=True, slots=True)
class PermissionStatus:
    """One permission's current state, ready for the Control Center."""

    spec: PermissionSpec
    state: PermissionState

    @property
    def permission(self) -> Permission:
        return self.spec.permission

    @property
    def granted(self) -> bool:
        return self.state is PermissionState.GRANTED

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible snapshot the web UI renders."""

        return {
            "id": self.spec.permission.value,
            "label": self.spec.label,
            "state": self.state.value,
            "granted": self.granted,
            "requirement": self.spec.requirement,
            # Only worth saying while the grant is still missing; repeating it
            # next to a working permission just adds doubt.
            "restart_note": "" if self.granted else self.spec.restart_note,
        }


SCREEN_RECORDING = PermissionSpec(
    Permission.SCREEN_RECORDING,
    "Screen Recording",
    "Hanly reads the word under your cursor from the screen. Without this macOS "
    "shows Hanly the desktop picture only, never the application you are reading.",
    restart_note="macOS may need Hanly restarted before a new grant takes effect.",
)

ACCESSIBILITY = PermissionSpec(
    Permission.ACCESSIBILITY,
    "Accessibility",
    "Automatic hover follows your cursor across other applications. The lookup "
    "hotkey does not need this.",
)

PERMISSION_SPECS: dict[Permission, PermissionSpec] = {
    SCREEN_RECORDING.permission: SCREEN_RECORDING,
    ACCESSIBILITY.permission: ACCESSIBILITY,
}

#: Capture cannot produce a usable image of another application without this.
CAPTURE_PERMISSIONS: tuple[Permission, ...] = (Permission.SCREEN_RECORDING,)

#: Global cursor observation is what needs to be trusted, not the hotkey: the
#: macOS hotkey backend registers with the window server instead of watching
#: the keyboard, so it stays usable while this one is missing.
HOVER_PERMISSIONS: tuple[Permission, ...] = (Permission.ACCESSIBILITY,)

#: Start Capture registers the hotkey *and* begins automatic hover, so today it
#: needs both. Splitting them belongs with a future manual-only default.
START_CAPTURE_PERMISSIONS: tuple[Permission, ...] = CAPTURE_PERMISSIONS + HOVER_PERMISSIONS


def missing_permission_refusal(missing: Sequence[PermissionStatus]) -> str:
    """Say which grant is missing, in the words the settings pane itself uses.

    Starting anyway is the failure this replaces: without Screen Recording
    macOS hands back a picture of the wallpaper, which reads as "no Korean text
    here" rather than as a permission the user never gave.
    """

    names = " and ".join(status.spec.label for status in missing)
    return f"Hanly needs {names} access before it can watch the screen."


class PermissionProbe(Protocol):
    """The platform half of the seam, kept replaceable for tests."""

    def state(self, permission: Permission) -> PermissionState:
        """Report one permission's current state without prompting."""

    def request(self, permission: Permission) -> PermissionState:
        """Run the platform's own grant flow and report the state after it."""


class PermissionService:
    """Report and request the permissions Hanly needs on this platform.

    Nothing here is a policy decision about *whether* Hanly may proceed; the
    caller compares :meth:`missing` against the feature it is about to start.

    Statuses are cached for a moment because the Control Center asks for a
    whole snapshot on a timer, and a privacy check is a round trip to the
    system rather than a field read.
    """

    def __init__(
        self,
        probe: PermissionProbe | None = None,
        *,
        permissions: Sequence[Permission] = (),
        cache_seconds: float = 1.0,
    ) -> None:
        if cache_seconds < 0:
            raise ValueError("cache_seconds must not be negative")

        self._probe = probe
        self._permissions = tuple(permissions) if probe is not None else ()
        self._cache_seconds = float(cache_seconds)
        self._lock = RLock()
        self._cached: tuple[PermissionStatus, ...] | None = None
        self._cached_at = 0.0

    @property
    def supported(self) -> bool:
        """Whether this platform gates anything Hanly does behind a grant."""

        return bool(self._permissions)

    def statuses(self) -> tuple[PermissionStatus, ...]:
        """Return every permission this platform requires, in declaration order."""

        with self._lock:
            cached = self._cached
            fresh = cached is not None and monotonic() - self._cached_at < self._cache_seconds
        if fresh and cached is not None:
            return cached

        statuses = tuple(self._status(permission) for permission in self._permissions)
        with self._lock:
            self._cached = statuses
            self._cached_at = monotonic()
        return statuses

    def missing(
        self,
        required: Iterable[Permission] | None = None,
    ) -> tuple[PermissionStatus, ...]:
        """Return the required permissions that are not currently granted.

        A permission Hanly could not read is reported as missing: starting a
        feature on an unreadable grant is how a half-working capture happens.
        """

        wanted = set(self._permissions if required is None else required)
        return tuple(
            status
            for status in self.statuses()
            if status.permission in wanted and not status.granted
        )

    def request(self, permission: Permission) -> PermissionStatus:
        """Run the platform grant flow for one permission and report the result."""

        if self._probe is None or permission not in self._permissions:
            raise UnsupportedPermission(
                f"{permission.value} is not a permission this platform manages"
            )
        state = self._probe.request(permission)
        # The user may have granted it in the sheet the request opened, so the
        # snapshot the caller renders next must not be the pre-request one.
        self.invalidate()
        return PermissionStatus(PERMISSION_SPECS[permission], state)

    def invalidate(self) -> None:
        """Drop cached statuses so the next read asks the system again."""

        with self._lock:
            self._cached = None
            self._cached_at = 0.0

    def _status(self, permission: Permission) -> PermissionStatus:
        assert self._probe is not None  # guarded by a non-empty _permissions
        try:
            state = self._probe.state(permission)
        except Exception:
            # A probe that cannot answer must not take the Control Center down
            # with it; "unknown" is a state the interface already renders.
            state = PermissionState.UNKNOWN
        return PermissionStatus(PERMISSION_SPECS[permission], state)


def create_permission_service(platform: str | None = None) -> PermissionService:
    """Build the service for the running platform, or an empty one elsewhere."""

    if (platform if platform is not None else sys.platform) != "darwin":
        return PermissionService()

    from .permissions_darwin import DarwinPermissionProbe

    return PermissionService(
        DarwinPermissionProbe(),
        permissions=(Permission.SCREEN_RECORDING, Permission.ACCESSIBILITY),
    )


def permission_from_id(value: object) -> Permission:
    """Resolve a permission named by the UI, rejecting anything else."""

    if isinstance(value, str):
        try:
            return Permission(value)
        except ValueError:
            pass
    raise UnsupportedPermission(f"unknown permission: {value!r}")


__all__ = [
    "ACCESSIBILITY",
    "CAPTURE_PERMISSIONS",
    "HOVER_PERMISSIONS",
    "PERMISSION_SPECS",
    "SCREEN_RECORDING",
    "START_CAPTURE_PERMISSIONS",
    "Permission",
    "PermissionProbe",
    "PermissionService",
    "PermissionActionFailed",
    "PermissionSpec",
    "PermissionState",
    "PermissionStatus",
    "UnsupportedPermission",
    "create_permission_service",
    "missing_permission_refusal",
    "permission_from_id",
]
