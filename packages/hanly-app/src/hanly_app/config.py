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
class AppConfig:
    """Preferences owned by the desktop client.

    This deliberately contains no OCR, morphology, dictionary, or other engine
    processing settings. Those values belong to engine composition and are not
    part of the desktop preferences file.
    """

    hotkey: str = "ctrl+shift+space"
    hover_delay_ms: int = 150
    capture_mode: CaptureMode = CaptureMode.FULL_MONITOR
    theme: Theme = Theme.SYSTEM
    popup_enabled: bool = True
    update_checks_enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.hotkey, str) or not self.hotkey.strip():
            raise ValueError("hotkey must be a non-empty string")
        if not isinstance(self.hover_delay_ms, int) or isinstance(self.hover_delay_ms, bool):
            raise ValueError("hover_delay_ms must be an integer")
        if self.hover_delay_ms <= 0:
            raise ValueError("hover_delay_ms must be greater than zero")
        if not isinstance(self.capture_mode, CaptureMode):
            object.__setattr__(self, "capture_mode", _coerce_capture_mode(self.capture_mode))
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
            "hotkey": self.hotkey,
            "hover_delay_ms": self.hover_delay_ms,
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

        if not isinstance(values, Mapping):
            raise ValueError("configuration must be a JSON object")

        defaults = cls()
        try:
            return cls(
                hotkey=cast(str, values.get("hotkey", defaults.hotkey)),
                hover_delay_ms=cast(int, values.get("hover_delay_ms", defaults.hover_delay_ms)),
                capture_mode=_coerce_capture_mode(
                    values.get("capture_mode", defaults.capture_mode)
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


class ConfigManager:
    """Load and atomically persist :class:`AppConfig` as deterministic JSON."""

    def __init__(self, path: str | Path, defaults: AppConfig | None = None) -> None:
        self._path = Path(path)
        self._defaults = defaults or AppConfig()
        self._config = self._defaults

    @property
    def path(self) -> Path:
        return self._path

    @property
    def config(self) -> AppConfig:
        return self._config

    def load(self) -> AppConfig:
        """Load settings, using defaults only when the file does not exist."""

        if not self._path.exists():
            self._config = self._defaults
            return self._config

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("configuration must be a JSON object")
            self._config = AppConfig.from_dict(raw)
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

        supported = {
            "hotkey",
            "hover_delay_ms",
            "capture_mode",
            "theme",
            "popup_enabled",
            "update_checks_enabled",
        }
        unknown = set(changes) - supported
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"unknown application configuration field(s): {names}")

        candidate = AppConfig(
            hotkey=cast(str, changes.get("hotkey", self._config.hotkey)),
            hover_delay_ms=cast(int, changes.get("hover_delay_ms", self._config.hover_delay_ms)),
            capture_mode=_coerce_capture_mode(
                changes.get("capture_mode", self._config.capture_mode)
            ),
            theme=_coerce_theme(changes.get("theme", self._config.theme)),
            popup_enabled=cast(bool, changes.get("popup_enabled", self._config.popup_enabled)),
            update_checks_enabled=cast(
                bool,
                changes.get("update_checks_enabled", self._config.update_checks_enabled),
            ),
        )
        return self.save(candidate)
