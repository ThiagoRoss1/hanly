"""Run metadata creation and validation for the benchmark runs."""

from __future__ import annotations

import json
import math
import os
import platform
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_SECRET_KEY = re.compile(r"(?:pass(?:word)?|secret|token|api[_-]?key|auth(?:orization)?)", re.I)
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_REQUIRED_FIELDS = ("schema_version", "run_id", "timestamp", "commit", "config", "scenario")


class MetadataError(ValueError):
    """Raised when run metadata is missing required or JSON-safe values."""


def build_metadata(
    *,
    run_id: str | None = None,
    commit: str | None = None,
    config: Mapping[str, Any] | None = None,
    scenario: Mapping[str, Any] | None = None,
    versions: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    repo_root: str | Path | None = None,
    timestamp: datetime | str | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe, self-contained metadata dictionary for one run.

    A generated run ID is created once and remains stable when the returned
    dictionary is written more than once. Sensitive mapping values and
    absolute paths are redacted before they enter the dictionary.
    """

    resolved_run_id = run_id or str(uuid.uuid4())
    if not isinstance(resolved_run_id, str) or not resolved_run_id.strip():
        raise MetadataError("run_id must be a non-empty string")

    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": resolved_run_id,
        "timestamp": _timestamp_value(timestamp),
        "commit": commit if commit is not None else _git_commit(repo_root),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_implementation": platform.python_implementation(),
        },
        "python": {
            "version": platform.python_version(),
            "executable": "<python>",
        },
        "cpu": {
            "count": os.cpu_count(),
            "processor": platform.processor() or "unknown",
        },
        "ram_bytes": _total_memory_bytes(),
        "config": config or {},
        "scenario": scenario or {},
        "versions": versions or {},
    }

    if environment is not None:
        metadata["environment"] = environment

    return _json_safe(metadata)


def validate_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize metadata before it is persisted."""

    if not isinstance(metadata, Mapping):
        raise MetadataError("metadata must be a mapping")

    normalized = _json_safe(dict(metadata))
    for field in _REQUIRED_FIELDS:
        if field not in normalized:
            raise MetadataError(f"metadata is missing required field: {field}")

    if normalized["schema_version"] != SCHEMA_VERSION:
        raise MetadataError(
            f"unsupported metadata schema_version: {normalized['schema_version']!r}"
        )
    if not isinstance(normalized["run_id"], str) or not normalized["run_id"].strip():
        raise MetadataError("metadata run_id must be a non-empty string")
    if not isinstance(normalized["timestamp"], str) or not normalized["timestamp"].strip():
        raise MetadataError("metadata timestamp must be a non-empty string")
    if not isinstance(normalized["commit"], str) or not normalized["commit"].strip():
        raise MetadataError("metadata commit must be a non-empty string")
    for field in ("config", "scenario"):
        if not isinstance(normalized[field], Mapping):
            raise MetadataError(f"metadata {field} must be a mapping")

    try:
        json.dumps(normalized, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MetadataError("metadata contains a value that cannot be encoded as JSON") from exc
    return normalized


def write_metadata(path: str | Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically write validated metadata and return the persisted value."""

    destination = Path(path)
    normalized = validate_metadata(metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")

    try:
        encoded = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise MetadataError(f"could not persist metadata at {destination}") from exc

    return normalized


def _timestamp_value(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    if isinstance(value, str) and value.strip():
        return value
    raise MetadataError("timestamp must be a datetime or non-empty string")


def _git_commit(repo_root: str | Path | None) -> str:
    cwd = Path(repo_root) if repo_root is not None else Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit or "unknown"


def _total_memory_bytes() -> int | None:
    if sys.platform == "win32":
        try:
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong),
                    ("available_phys", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.length = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_phys)
        except (AttributeError, OSError, TypeError):
            pass
        return None

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    return int(page_size * page_count)


def _json_safe(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str):
            return _safe_string(value)
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Path):
        return _safe_string(value.as_posix())
    if isinstance(value, datetime):
        return _timestamp_value(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): _json_safe(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return _safe_string(str(value))


def _safe_string(value: str) -> str:
    if value.startswith("/") or _WINDOWS_ABSOLUTE.match(value):
        return "[ABSOLUTE_PATH_REDACTED]"
    return value
