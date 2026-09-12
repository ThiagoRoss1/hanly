"""Typed, desktop-only application preferences and JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from .hotkeys import HotkeyError, canonical_hotkey


class CaptureMode(str, Enum):
    """The desktop area available to a future capture service."""

    FULL_MONITOR = "full_monitor"
    FULL_SCREEN = "full_monitor"
    REGION = "region"


class Theme(str, Enum):
    """Popup / desktop appearance preference."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class LookupPreload(str, Enum):
    """When the lookup engine's providers should be resident.

    The engine lives in a child process that can be retired, so residency is a
    real choice rather than a fixed cost: it buys a fast first lookup and costs
    around a gigabyte of memory while it is loaded.
    """

    #: Load when the user starts watching the screen, and retire on pause.
    WHEN_CAPTURE_STARTS = "when_capture_starts"
    #: Load at launch and stay loaded, deliberately including through pause.
    ALWAYS = "always"
    #: Load nothing until a lookup actually needs it.
    ON_DEMAND = "on_demand"


class HoverActivation(str, Enum):
    """Whether automatic hover waits to be switched on."""

    #: Off until the toggle hotkey, the tray, or the Control Center starts it.
    HOTKEY = "hotkey"
    #: On from launch, subject to the permissions hover needs.
    ALWAYS_ACTIVE = "always_active"


#: What the hover toggle is bound to when nothing else is stored. The desktop
#: binds no separate start and pause keys, so this position is free.
DEFAULT_HOVER_HOTKEY = "ctrl+shift+f9"

#: Tried in order when a stored manual binding already occupies the toggle's
#: default. Deterministic so the same profile always migrates the same way.
HOVER_HOTKEY_FALLBACKS: tuple[str, ...] = (
    DEFAULT_HOVER_HOTKEY,
    "ctrl+shift+f11",
    "ctrl+shift+f12",
    "ctrl+alt+h",
)


#: Supported bounds for the hover debounce, in milliseconds. Architecture V1
#: tunes hover empirically inside roughly 80-250 ms; these wider bounds keep
#: that experimentation open while rejecting values that cannot be a debounce.
HOVER_DELAY_MIN_MS = 20
HOVER_DELAY_MAX_MS = 2000

#: Preferences :meth:`ConfigManager.update` accepts. Capture target and region
#: are here because settings, not a launch-time prompt, is where they are now
#: chosen; the Control Center still exposes a narrower list to the page.
SETTABLE_FIELDS = frozenset(
    {
        "hotkey",
        "hover_hotkey",
        "hover_activation",
        "lookup_preload",
        "hover_delay_ms",
        "capture_mode",
        "capture_monitor",
        "capture_region",
        "theme",
        "popup_enabled",
        "update_checks_enabled",
    }
)


class ConfigError(ValueError):
    """Raised when persisted configuration cannot be read or validated."""


def _coerce_capture_mode(value: object) -> CaptureMode:
    if isinstance(value, CaptureMode):
        return value
    if isinstance(value, str):
        try:
            return CaptureMode(value)
        except ValueError as error:
            raise ValueError("capture_mode must be a supported capture mode") from error
    raise ValueError("capture_mode must be a supported capture mode")


def _coerce_preload(value: object) -> LookupPreload:
    if isinstance(value, LookupPreload):
        return value
    if isinstance(value, str):
        try:
            return LookupPreload(value)
        except ValueError as error:
            raise ValueError("lookup_preload must be a supported choice") from error
    raise ValueError("lookup_preload must be a supported choice")


def _coerce_activation(value: object) -> HoverActivation:
    if isinstance(value, HoverActivation):
        return value
    if isinstance(value, str):
        try:
            return HoverActivation(value)
        except ValueError as error:
            raise ValueError("hover_activation must be a supported choice") from error
    raise ValueError("hover_activation must be a supported choice")


def _canonical(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    try:
        return canonical_hotkey(value)
    except HotkeyError as error:
        raise ValueError(f"{field} is not a usable key combination: {error}") from error


def _coerce_theme(value: object) -> Theme:
    if isinstance(value, Theme):
        return value
    if isinstance(value, str):
        try:
            return Theme(value)
        except ValueError as error:
            raise ValueError("theme must be a supported theme") from error
    raise ValueError("theme must be a supported theme")


@dataclass(frozen=True, slots=True)
class CaptureRegion:
    """A persisted screen-space capture rectangle.

    Deliberately not ``ScreenRect``: capture imports this module, so the
    preference type has to live below that seam. The desktop converts at the
    boundary.
    """

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("left", "top", "width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("capture region bounds must be integers")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("capture region dimensions must be positive")

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> CaptureRegion:
        if not isinstance(values, Mapping):
            raise ValueError("capture_region must be a JSON object")
        try:
            return cls(
                left=values["left"],
                top=values["top"],
                width=values["width"],
                height=values["height"],
            )
        except KeyError as error:
            raise ValueError(f"capture_region is missing {error.args[0]}") from error


def _coerce_capture_region(value: object) -> CaptureRegion | None:
    if value is None or isinstance(value, CaptureRegion):
        return value
    if isinstance(value, Mapping):
        return CaptureRegion.from_dict(value)
    raise ValueError("capture_region must be a JSON object or null")


def _coerce_capture_monitor(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("capture_monitor must be an integer index or null")
    # Monitor indices are the capture service's, which are 1-based.
    if value < 1:
        raise ValueError("capture_monitor must be a positive monitor index")
    return value


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Preferences owned by the desktop client.

    This deliberately contains no OCR, morphology, dictionary, or other engine
    processing settings. Those values belong to engine composition and are not
    part of the desktop preferences file.
    """

    hotkey: str = "ctrl+shift+space"
    #: One binding turns automatic hover on and off. It is never the old manual
    #: lookup key: reinterpreting a key the user already has would change what
    #: their muscle memory does.
    hover_hotkey: str = DEFAULT_HOVER_HOTKEY
    hover_activation: HoverActivation = HoverActivation.HOTKEY
    lookup_preload: LookupPreload = LookupPreload.WHEN_CAPTURE_STARTS
    # 80 ms sits at the low end of the architecture's empirical hover range.
    # It became affordable once a flat ROI stopped costing a full OCR call and
    # nearby cursor positions started reusing one cached recognition.
    hover_delay_ms: int = 80
    capture_mode: CaptureMode = CaptureMode.FULL_MONITOR
    #: None means the capture follows the cursor rather than a fixed monitor.
    capture_monitor: int | None = None
    # Region mode without a region is a real state: a monitor can disappear
    # between sessions. Capture falls back to the whole monitor and the user
    # reselects, which beats refusing to load their settings at all.
    capture_region: CaptureRegion | None = None
    theme: Theme = Theme.SYSTEM
    popup_enabled: bool = True
    update_checks_enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.hotkey, str) or not self.hotkey.strip():
            raise ValueError("hotkey must be a non-empty string")
        if not isinstance(self.hover_activation, HoverActivation):
            object.__setattr__(
                self, "hover_activation", _coerce_activation(self.hover_activation)
            )
        if not isinstance(self.lookup_preload, LookupPreload):
            object.__setattr__(self, "lookup_preload", _coerce_preload(self.lookup_preload))
        if _canonical(self.hotkey, "hotkey") == _canonical(self.hover_hotkey, "hover_hotkey"):
            raise ValueError("the lookup and hover shortcuts must be different keys")
        if not isinstance(self.hover_delay_ms, int) or isinstance(self.hover_delay_ms, bool):
            raise ValueError("hover_delay_ms must be an integer")
        if not HOVER_DELAY_MIN_MS <= self.hover_delay_ms <= HOVER_DELAY_MAX_MS:
            raise ValueError(
                "hover_delay_ms must be between "
                f"{HOVER_DELAY_MIN_MS} and {HOVER_DELAY_MAX_MS} milliseconds"
            )
        if not isinstance(self.capture_mode, CaptureMode):
            object.__setattr__(self, "capture_mode", _coerce_capture_mode(self.capture_mode))
        object.__setattr__(self, "capture_monitor", _coerce_capture_monitor(self.capture_monitor))
        object.__setattr__(self, "capture_region", _coerce_capture_region(self.capture_region))
        if not isinstance(self.theme, Theme):
            object.__setattr__(self, "theme", _coerce_theme(self.theme))
        if not isinstance(self.popup_enabled, bool):
            raise ValueError("popup_enabled must be a boolean")
        if not isinstance(self.update_checks_enabled, bool):
            raise ValueError("update_checks_enabled must be a boolean")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping with stable primitive values."""

        return {
            "capture_mode": self.capture_mode.value,
            "capture_monitor": self.capture_monitor,
            "capture_region": (
                None if self.capture_region is None else self.capture_region.to_dict()
            ),
            "hotkey": self.hotkey,
            "hover_activation": self.hover_activation.value,
            "hover_delay_ms": self.hover_delay_ms,
            "hover_hotkey": self.hover_hotkey,
            "lookup_preload": self.lookup_preload.value,
            "popup_enabled": self.popup_enabled,
            "theme": self.theme.value,
            "update_checks_enabled": self.update_checks_enabled,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> AppConfig:
        """Build and validate preferences from a JSON object.

        Unknown keys are ignored so a newer client can add preferences without
        making an older client unable to start. Missing keys use current defaults.
        """

        return cls.migrate(values)[0]

    @classmethod
    def migrate(cls, values: Mapping[str, Any]) -> tuple[AppConfig, tuple[str, ...]]:
        """Build preferences from stored values, reporting what had to move.

        A profile written before the hover toggle existed has a manual key and
        nothing else. That key keeps doing exactly what it did; only the new
        toggle has to find somewhere to live, and if the manual key is already
        sitting in the toggle's default position the toggle moves rather than
        the key the user has been pressing for months.
        """

        if not isinstance(values, Mapping):
            raise ValueError("configuration must be a JSON object")

        defaults = cls()
        notes: list[str] = []
        try:
            hotkey = cast(str, values.get("hotkey", defaults.hotkey))
            hover_hotkey = _migrated_hover_hotkey(hotkey, values.get("hover_hotkey"), notes)
            config = cls(
                hotkey=hotkey,
                hover_hotkey=hover_hotkey,
                hover_activation=_coerce_activation(
                    values.get("hover_activation", defaults.hover_activation)
                ),
                lookup_preload=_coerce_preload(
                    values.get("lookup_preload", defaults.lookup_preload)
                ),
                hover_delay_ms=cast(int, values.get("hover_delay_ms", defaults.hover_delay_ms)),
                capture_mode=_coerce_capture_mode(
                    values.get("capture_mode", defaults.capture_mode)
                ),
                capture_monitor=_coerce_capture_monitor(
                    values.get("capture_monitor", defaults.capture_monitor)
                ),
                capture_region=_coerce_capture_region(
                    values.get("capture_region", defaults.capture_region)
                ),
                theme=_coerce_theme(values.get("theme", defaults.theme)),
                popup_enabled=cast(bool, values.get("popup_enabled", defaults.popup_enabled)),
                update_checks_enabled=cast(
                    bool,
                    values.get("update_checks_enabled", defaults.update_checks_enabled),
                ),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid application configuration: {error}") from error
        return config, tuple(notes)


def _migrated_hover_hotkey(
    hotkey: object, stored: object, notes: list[str]
) -> str:
    """Choose the toggle's binding, moving it rather than the manual key.

    A stored value is the user's own choice and is kept. Without one, the
    default is used unless the manual lookup key already occupies it, in which
    case the next free position in a fixed list is taken and said out loud.
    """

    if stored is not None:
        return cast(str, stored)

    manual = _canonical(hotkey, "hotkey")
    for candidate in HOVER_HOTKEY_FALLBACKS:
        if _canonical(candidate, "hover_hotkey") != manual:
            if candidate != DEFAULT_HOVER_HOTKEY:
                notes.append(
                    f"Your lookup shortcut already uses {DEFAULT_HOVER_HOTKEY}, so the "
                    f"hover toggle was set to {candidate}."
                )
            return candidate
    raise ValueError("no hover toggle shortcut is free beside the lookup shortcut")


class ConfigManager:
    """Load and atomically persist :class:`AppConfig` as deterministic JSON."""

    def __init__(self, path: str | Path, defaults: AppConfig | None = None) -> None:
        self._path = Path(path)
        self._defaults = defaults or AppConfig()
        self._config = self._defaults
        self._migrations: tuple[str, ...] = ()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def migrations(self) -> tuple[str, ...]:
        """What the last load had to change, in words a user can act on."""

        return self._migrations

    def load(self) -> AppConfig:
        """Load settings, using defaults only when the file does not exist."""

        if not self._path.exists():
            self._config = self._defaults
            self._migrations = ()
            return self._config

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("configuration must be a JSON object")
            self._config, self._migrations = AppConfig.migrate(raw)
        except (OSError, json.JSONDecodeError, UnicodeError, ValueError) as error:
            raise ConfigError(f"could not load configuration from {self._path}") from error
        return self._config

    def save(self, config: AppConfig | None = None) -> AppConfig:
        """Persist settings using a same-directory temporary file and replace."""

        if config is not None and not isinstance(config, AppConfig):
            raise TypeError("config must be an AppConfig")
        next_config = config if config is not None else self._config
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(next_config.to_dict(), indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        descriptor: int | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=self._path.parent,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._path)
        except OSError as error:
            raise ConfigError(f"could not save configuration to {self._path}") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

        self._config = next_config
        return self._config

    def update(self, **changes: object) -> AppConfig:
        """Validate, persist, and return a copy with selected preferences changed."""

        return self.save(self.candidate(**changes))

    def candidate(self, **changes: object) -> AppConfig:
        """Validate a change without persisting or applying it.

        Settings that register a native shortcut have to be tried before they
        are stored, so the candidate is built separately from the save.
        """

        unknown = set(changes) - SETTABLE_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"unknown application configuration field(s): {names}")

        return AppConfig(
            hotkey=cast(str, changes.get("hotkey", self._config.hotkey)),
            hover_hotkey=cast(str, changes.get("hover_hotkey", self._config.hover_hotkey)),
            hover_activation=_coerce_activation(
                changes.get("hover_activation", self._config.hover_activation)
            ),
            lookup_preload=_coerce_preload(
                changes.get("lookup_preload", self._config.lookup_preload)
            ),
            hover_delay_ms=cast(int, changes.get("hover_delay_ms", self._config.hover_delay_ms)),
            capture_mode=_coerce_capture_mode(
                changes.get("capture_mode", self._config.capture_mode)
            ),
            capture_monitor=_coerce_capture_monitor(
                changes.get("capture_monitor", self._config.capture_monitor)
            ),
            capture_region=_coerce_capture_region(
                changes.get("capture_region", self._config.capture_region)
            ),
            theme=_coerce_theme(changes.get("theme", self._config.theme)),
            popup_enabled=cast(bool, changes.get("popup_enabled", self._config.popup_enabled)),
            update_checks_enabled=cast(
                bool,
                changes.get("update_checks_enabled", self._config.update_checks_enabled),
            ),
        )


__all__ = [
    "DEFAULT_HOVER_HOTKEY",
    "HOVER_DELAY_MAX_MS",
    "HOVER_DELAY_MIN_MS",
    "HOVER_HOTKEY_FALLBACKS",
    "SETTABLE_FIELDS",
    "AppConfig",
    "CaptureMode",
    "CaptureRegion",
    "ConfigError",
    "ConfigManager",
    "HoverActivation",
    "LookupPreload",
    "Theme",
]
