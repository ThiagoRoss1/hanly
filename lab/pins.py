"""The local registry of protected runs: which are baselines and which are kept.

``artifacts/lab/pins.json`` is gitignored and belongs to one machine, as the
runs do. An entry holds only the run's name, its role (``baseline`` or
``keep``) and why; everything that decides whether two runs can be compared is
read from the run itself through :func:`lab.identity.run_identity`, so the
registry can never disagree with the evidence it points at.

At most one baseline is active per compatibility key. Registering a second for
the same key is refused unless replacement is explicit. Removing an entry
touches only the registry, never a run directory.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .identity import LAB_ROOT, RUNS_ROOT, RunIdentity, resolve_name, run_identity, run_name

PINS_PATH = LAB_ROOT / "pins.json"
SCHEMA_VERSION = 1
ROLES = ("baseline", "keep")


class PinError(ValueError):
    """An operation the registry refuses; nothing was changed."""


@dataclass(frozen=True)
class Pin:
    run: str
    role: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"run": self.run, "role": self.role, "reason": self.reason}


@dataclass(frozen=True)
class Registry:
    """One read of the registry, tied to the runs root it describes."""

    path: Path
    runs_root: Path
    pins: tuple[Pin, ...]

    def of(self, run: str) -> tuple[Pin, ...]:
        return tuple(pin for pin in self.pins if pin.run == run)

    def roles(self, run: str) -> set[str]:
        return {pin.role for pin in self.of(run)}

    def protected(self) -> set[str]:
        return {pin.run for pin in self.pins}

    def baselines(self) -> tuple[Pin, ...]:
        return tuple(pin for pin in self.pins if pin.role == "baseline")

    def dangling(self) -> tuple[Pin, ...]:
        return tuple(pin for pin in self.pins if not (self.runs_root / pin.run).is_dir())

    def baseline_for(self, identity: RunIdentity) -> RunIdentity | None:
        """The registered baseline sharing ``identity``'s compatibility key."""

        for pin in self.baselines():
            path = self.runs_root / pin.run
            if pin.run == identity.name or not path.is_dir():
                continue
            candidate = run_identity(path)
            if candidate.compatibility_key == identity.compatibility_key:
                return candidate
        return None


def load(path: Path | None = None, runs_root: Path | None = None) -> Registry:
    """Read the registry; a missing file is an empty registry, a corrupt one an error."""

    path = PINS_PATH if path is None else path
    root = RUNS_ROOT if runs_root is None else runs_root
    if not path.is_file():
        return Registry(path, root, ())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PinError(f"{path} is unreadable ({type(error).__name__}); fix or move it") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise PinError(f"{path} is not a version {SCHEMA_VERSION} pin registry")
    pins = []
    for entry in payload.get("pins", []):
        if not isinstance(entry, dict) or entry.get("role") not in ROLES:
            raise PinError(f"{path} holds an entry that is not a pin: {entry!r}")
        try:
            name = run_name(str(entry.get("run")))
        except ValueError as error:
            raise PinError(f"{path}: {error}") from error
        pins.append(Pin(name, str(entry["role"]), str(entry.get("reason") or "")))
    return Registry(path, root, tuple(pins))


def set_baseline(
    registry: Registry,
    run: str,
    reason: str,
    *,
    allow_dirty: bool = False,
    replace: bool = False,
) -> tuple[Registry, RunIdentity, Pin | None]:
    """Register ``run`` as the baseline for its key; returns the one it replaced."""

    path = _existing(registry, run)
    identity = run_identity(path)
    _require_trustworthy(identity, allow_dirty)
    if "baseline" in registry.roles(identity.name):
        raise PinError(f"{identity.name} is already a baseline")
    current = registry.baseline_for(identity)
    if current is not None and not replace:
        raise PinError(
            f"{current.name} is already the baseline for {identity.compatibility_key}; "
            "pass --replace to make this run the baseline instead"
        )
    kept = [
        pin
        for pin in registry.pins
        if not (current is not None and pin.run == current.name and pin.role == "baseline")
    ]
    added = Pin(identity.name, "baseline", _reason(reason))
    replaced = (
        None
        if current is None
        else next(pin for pin in registry.baselines() if pin.run == current.name)
    )
    return _save(registry, [*kept, added]), identity, replaced


def keep(registry: Registry, run: str, reason: str) -> Registry:
    """Protect any existing run directory, whatever is known about it."""

    path = _existing(registry, run)
    if "keep" in registry.roles(path.name):
        raise PinError(f"{path.name} is already kept")
    return _save(registry, [*registry.pins, Pin(path.name, "keep", _reason(reason))])


def remove(registry: Registry, run: str, role: str) -> Registry:
    """Drop one role from one run; its other entries and its files are untouched.

    Works for a run whose directory is gone, which is how a dangling entry is
    cleared. A run without that role is refused and nothing is written.
    """

    name = _registry_name(run)
    if role not in registry.roles(name):
        raise PinError(f"{name} has no {role} registration; nothing changed")
    return _save(
        registry, [pin for pin in registry.pins if not (pin.run == name and pin.role == role)]
    )


def describe(registry: Registry, pins: Iterable[Pin]) -> list[dict[str, Any]]:
    """Registry rows with what the run itself says, for listings."""

    rows = []
    for pin in pins:
        path = registry.runs_root / pin.run
        row: dict[str, Any] = pin.as_dict()
        if path.is_dir():
            identity = run_identity(path)
            row.update(
                kind=identity.kind,
                key=identity.compatibility_key,
                commit=identity.commit,
                source=identity.source_state,
                completion=identity.completion,
            )
        else:
            row["dangling"] = True
        rows.append(row)
    return rows


# -- helpers -----------------------------------------------------------------------------


def _existing(registry: Registry, run: str) -> Path:
    try:
        path = resolve_name(run, registry.runs_root)
    except ValueError as error:
        raise PinError(str(error)) from error
    if not path.is_dir():
        raise PinError(f"{run} is not a run directory under {registry.runs_root}")
    return path


def _registry_name(run: str) -> str:
    try:
        return run_name(Path(run).name if Path(run).is_absolute() else run)
    except ValueError as error:
        raise PinError(str(error)) from error


def _require_trustworthy(identity: RunIdentity, allow_dirty: bool) -> None:
    """A baseline is chosen automatically later, so its provenance must be complete."""

    problems = []
    if identity.kind == "unknown":
        problems.append("no Lab writer produced it")
    if not identity.complete:
        problems.append(f"it did not finish ({identity.completion})")
    if identity.commit == "unknown":
        problems.append("its commit is unknown")
    if identity.source_state == "unknown":
        problems.append("whether its checkout was modified is unknown")
    elif identity.source_state == "dirty" and not allow_dirty:
        problems.append("it was recorded from a modified checkout (pass --allow-dirty)")
    if identity.backend == "unknown":
        problems.append("its OCR backend cannot be shown")
    if identity.conflicts:
        problems.append("; ".join(identity.conflicts))
    if problems:
        raise PinError(
            f"{identity.name} cannot be a baseline: {'; '.join(problems)}. "
            "`python -m lab pin` still protects it."
        )


def _reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        raise PinError("a pin needs a --reason")
    return text


def _save(registry: Registry, pins: list[Pin]) -> Registry:
    """Replace the registry atomically: a reader sees the old or the new file, never half."""

    registry.path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "pins": [pin.as_dict() for pin in pins]}
    temporary = registry.path.with_name(f".{registry.path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, registry.path)
    finally:
        temporary.unlink(missing_ok=True)
    return Registry(registry.path, registry.runs_root, tuple(pins))


__all__ = [
    "PINS_PATH",
    "ROLES",
    "Pin",
    "PinError",
    "Registry",
    "describe",
    "keep",
    "load",
    "remove",
    "set_baseline",
]
