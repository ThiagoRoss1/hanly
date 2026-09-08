"""A windowed build has no console, so diagnostics have to survive on disk."""

from __future__ import annotations

from pathlib import Path

import pytest
from hanly_app import ocr_preload
from hanly_app.diagnostics import (
    LOG_FILE_NAME,
    DiagnosticLog,
    RotatingLogFile,
    StartupTimeline,
    open_diagnostics,
    runtime_versions,
)


def test_a_report_shows_one_line_and_files_the_whole_chain(tmp_path: Path) -> None:
    log = DiagnosticLog(RotatingLogFile(tmp_path / LOG_FILE_NAME))
    try:
        try:
            raise ValueError("kiwipiepy is unavailable")
        except ValueError as cause:
            raise RuntimeError("lookup providers failed") from cause
    except RuntimeError as error:
        log.report("Lookup providers", error)

    assert log.snapshot() == ("Lookup providers: lookup providers failed",)
    written = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "Lookup providers: lookup providers failed" in written
    # The cause is what a bug report needs, and only the file keeps it.
    assert "kiwipiepy is unavailable" in written
    assert "Traceback" in written


def test_the_memory_tail_is_bounded_but_the_file_is_not_truncated(tmp_path: Path) -> None:
    log = DiagnosticLog(RotatingLogFile(tmp_path / LOG_FILE_NAME), limit=3)

    for index in range(10):
        log.add(f"message {index}")

    assert log.snapshot() == ("message 7", "message 8", "message 9")
    assert (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").count("message ") == 10


def test_a_full_log_rotates_instead_of_growing(tmp_path: Path) -> None:
    path = tmp_path / LOG_FILE_NAME
    file = RotatingLogFile(path, max_bytes=200, backup_count=2)

    for index in range(40):
        file.write(f"record {index:03d} " + "x" * 40)

    assert path.is_file()
    assert path.stat().st_size <= 400
    assert path.with_name(f"{LOG_FILE_NAME}.1").is_file()
    assert not path.with_name(f"{LOG_FILE_NAME}.3").exists()


def test_an_unwritable_location_degrades_instead_of_failing(tmp_path: Path) -> None:
    """A profile Hanly cannot write to must not stop the desktop starting."""

    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    file = RotatingLogFile(blocker / "logs" / LOG_FILE_NAME)

    file.write("first")
    file.write("second")

    assert not file.usable


def test_a_session_log_records_where_it_is_and_what_it_ran_with(tmp_path: Path) -> None:
    log = open_diagnostics(tmp_path, versions={"python": "3.10.0", "hanly": "0.1.0"})

    assert log.path == tmp_path / LOG_FILE_NAME
    messages = log.snapshot()
    assert any(str(log.path) in message for message in messages)
    assert "version python: 3.10.0" in messages
    assert (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").count("version ") == 2


def test_runtime_versions_name_what_a_reader_needs_to_reproduce_a_run() -> None:
    versions = runtime_versions(("hanly", "hanly-app"))

    assert set(versions) >= {"python", "platform", "frozen", "hanly", "hanly-app"}
    assert versions["hanly"] != "not installed"


def test_a_rotating_file_rejects_bounds_it_cannot_honour(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        RotatingLogFile(tmp_path / LOG_FILE_NAME, max_bytes=0)
    with pytest.raises(ValueError, match="backup_count"):
        RotatingLogFile(tmp_path / LOG_FILE_NAME, backup_count=-1)


class _FakeClock:
    """A clock the test advances itself, so no timing is ever measured here."""

    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_startup_phases_are_recorded_with_their_duration_and_outcome() -> None:
    clock = _FakeClock()
    log = DiagnosticLog()
    timeline = StartupTimeline(log, clock=clock)

    with timeline.phase("resources", attempt=2):
        clock.advance(1.5)
    timeline.mark("ocr runtime preload", 0.25, outcome="loaded")
    clock.advance(0.5)
    timeline.reached("runtime ready")

    with pytest.raises(RuntimeError):
        with timeline.phase("lookup providers", attempt=2):
            clock.advance(0.125)
            raise RuntimeError("kiwipiepy is unavailable")

    assert log.snapshot() == (
        "startup resources: 1500 ms (ok, attempt 2)",
        "startup ocr runtime preload: 250 ms (loaded)",
        "startup runtime ready at 2000 ms",
        "startup lookup providers: 125 ms (failed: RuntimeError, attempt 2)",
    )


def test_a_timeline_without_a_log_records_nothing() -> None:
    timeline = StartupTimeline()

    with timeline.phase("resources"):
        pass
    timeline.reached("runtime ready")


def test_the_preload_measurement_is_claimed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The packaged hook measures before the log exists; nobody double-counts."""

    monkeypatch.setattr(
        ocr_preload, "_timing", ocr_preload.PreloadTiming(0.75, "loaded")
    )
    log = DiagnosticLog()
    timeline = StartupTimeline(log)

    ocr_preload.record_preload_timing(timeline)
    ocr_preload.record_preload_timing(timeline)

    assert log.snapshot() == ("startup ocr runtime preload: 750 ms (loaded)",)
