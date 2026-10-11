"""Durable append-only measurement storage for benchmark runs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from .metadata import MetadataError, validate_metadata, write_metadata

SCHEMA_VERSION = 1
_CONDITIONS = {"cold", "warmup", "warm"}
_EVIDENCE_CLASSES = {"measured", "derived", "estimated"}
_REQUIRED_RECORD_FIELDS = (
    "schema_version",
    "run_id",
    "timestamp",
    "evidence_class",
    "scenario",
    "stage",
    "iteration",
    "condition",
    "duration_ns",
    "correctness_status",
)


class RunStoreError(ValueError):
    """Raised when a run record is invalid or cannot be durably stored."""


class RunStore:
    """Persist one run's metadata and immediately flushed JSONL samples."""

    def __init__(
        self,
        run_dir: str | Path,
        metadata: Mapping[str, Any],
        *,
        fsync: bool = True,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.metadata_path = self.run_dir / "metadata.json"
        self.measurements_path = self.run_dir / "measurements.jsonl"
        self._fsync = fsync
        self._closed = False

        try:
            normalized = validate_metadata(metadata)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            if self.metadata_path.exists():
                existing = validate_metadata(
                    json.loads(self.metadata_path.read_text(encoding="utf-8"))
                )
                if existing["run_id"] != normalized["run_id"]:
                    raise RunStoreError("metadata run_id does not match the existing run")
            else:
                write_metadata(self.metadata_path, normalized)
        except (MetadataError, OSError, json.JSONDecodeError) as exc:
            if isinstance(exc, RunStoreError):
                raise
            raise RunStoreError(f"could not initialize run store at {self.run_dir}") from exc

        self._recover_partial_line()
        try:
            self._stream = self.measurements_path.open("a", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise RunStoreError(f"could not open measurements at {self.measurements_path}") from exc
        self.run_id = str(normalized["run_id"])

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, append, flush, and return one measurement record."""

        if self._closed:
            raise RunStoreError("run store is closed")
        normalized = dict(record)
        normalized.setdefault("schema_version", SCHEMA_VERSION)
        normalized.setdefault("run_id", self.run_id)
        normalized.setdefault("timestamp", _utc_timestamp())
        self._validate_record(normalized)

        try:
            encoded = json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise RunStoreError(
                "measurement contains a value that cannot be encoded as JSON"
            ) from exc

        try:
            line = encoded + "\n"
            written = self._stream.write(line)
            if written != len(line):
                raise OSError("measurement write was incomplete")
            self._stream.flush()
            if self._fsync:
                os.fsync(self._stream.fileno())
        except (OSError, ValueError) as exc:
            self._recover_after_failed_append()
            raise RunStoreError(
                f"could not append measurement to {self.measurements_path}"
            ) from exc

        return normalized

    def append_sample(
        self,
        *,
        evidence_class: str,
        scenario: str,
        stage: str,
        iteration: int,
        condition: str,
        duration_ns: int,
        correctness_status: str,
        timestamp: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Append a record with the fields required by the benchmark protocol."""

        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "timestamp": timestamp or _utc_timestamp(),
            "evidence_class": evidence_class,
            "scenario": scenario,
            "stage": stage,
            "iteration": iteration,
            "condition": condition,
            "duration_ns": duration_ns,
            "correctness_status": correctness_status,
        }
        record.update(fields)
        return self.append(record)

    @contextmanager
    def timed_sample(self, **sample_fields: Any) -> Iterator[dict[str, Any]]:
        """Measure a block with ``perf_counter_ns`` and append its sample."""

        started = perf_counter_ns()
        try:
            yield sample_fields
        except Exception:
            sample_fields["correctness_status"] = "error"
            sample_fields["duration_ns"] = perf_counter_ns() - started
            self.append_sample(**sample_fields)
            raise
        else:
            sample_fields["duration_ns"] = perf_counter_ns() - started
            sample_fields.setdefault("correctness_status", "success")
            self.append_sample(**sample_fields)

    def read_samples(self) -> list[dict[str, Any]]:
        """Read all complete samples, repairing only a trailing partial line."""

        if not self._closed:
            self._stream.flush()
        self._recover_partial_line()
        try:
            lines = self.measurements_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise RunStoreError(
                f"could not read measurements from {self.measurements_path}"
            ) from exc

        samples: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RunStoreError(f"invalid JSON in measurements line {line_number}") from exc
            if not isinstance(record, Mapping):
                raise RunStoreError(f"measurements line {line_number} must contain an object")
            normalized = dict(record)
            self._validate_record(normalized)
            samples.append(normalized)
        return samples

    def close(self) -> None:
        """Flush and close the measurements file."""

        if self._closed:
            return
        try:
            self._stream.flush()
            if self._fsync:
                os.fsync(self._stream.fileno())
            self._stream.close()
        except OSError as exc:
            raise RunStoreError(
                f"could not close measurements at {self.measurements_path}"
            ) from exc
        finally:
            self._closed = True

    def __enter__(self) -> RunStore:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def _validate_record(self, record: Mapping[str, Any]) -> None:
        missing = [field for field in _REQUIRED_RECORD_FIELDS if field not in record]
        if missing:
            raise RunStoreError(f"measurement is missing required field(s): {', '.join(missing)}")
        if record["schema_version"] != SCHEMA_VERSION:
            raise RunStoreError(
                f"unsupported measurement schema_version: {record['schema_version']!r}"
            )
        if record["run_id"] != self.run_id:
            raise RunStoreError("measurement run_id does not match the run store")
        for field in ("timestamp", "scenario", "stage", "correctness_status"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise RunStoreError(f"measurement {field} must be a non-empty string")
        if record["evidence_class"] not in _EVIDENCE_CLASSES:
            raise RunStoreError(
                "measurement evidence_class must be measured, derived, or estimated"
            )
        if record["condition"] not in _CONDITIONS:
            raise RunStoreError("measurement condition must be cold, warmup, or warm")
        if (
            isinstance(record["iteration"], bool)
            or not isinstance(record["iteration"], int)
            or record["iteration"] < 0
        ):
            raise RunStoreError("measurement iteration must be a non-negative integer")
        if (
            isinstance(record["duration_ns"], bool)
            or not isinstance(record["duration_ns"], int)
            or record["duration_ns"] < 0
        ):
            raise RunStoreError("measurement duration_ns must be a non-negative integer")

    def _recover_partial_line(self) -> None:
        if not self.measurements_path.exists():
            return
        try:
            content = self.measurements_path.read_bytes()
        except OSError as exc:
            raise RunStoreError(
                f"could not inspect measurements at {self.measurements_path}"
            ) from exc
        if not content or content.endswith(b"\n"):
            return
        complete_end = content.rfind(b"\n") + 1
        try:
            with self.measurements_path.open("r+b") as stream:
                stream.truncate(complete_end)
        except OSError as exc:
            raise RunStoreError(
                f"could not recover measurements at {self.measurements_path}"
            ) from exc

    def _recover_after_failed_append(self) -> None:
        """Reset the writer before trimming an incomplete failed append."""

        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass
        try:
            self._stream.close()
        except (OSError, ValueError):
            pass

        self._recover_partial_line()
        try:
            self._stream = self.measurements_path.open("a", encoding="utf-8", newline="\n")
        except OSError:
            self._closed = True


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
