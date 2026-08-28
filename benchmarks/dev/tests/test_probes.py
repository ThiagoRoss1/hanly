"""Focused tests for the isolated observational tooling."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.dev.package_composition import PackageCompositionAnalyzer, analyze_package
from benchmarks.dev.probes import (
    ProcessSampler,
    probe_capture,
    probe_dictionary,
    probe_morphology,
    probe_ocr,
    probe_result_dispatch,
    probe_stage,
)


def test_stage_probe_records_duration_and_preserves_return_identity() -> None:
    records: list[dict[str, Any]] = []
    result = object()

    observed = probe_capture(lambda: result, records, run_id="r1", iteration=2)

    assert observed is result
    assert records[0]["stage"] == "capture"
    assert isinstance(records[0]["duration_ns"], int)
    assert records[0]["run_id"] == "r1"
    json.dumps(records[0])


def test_each_named_stage_wrapper_records_its_stage() -> None:
    records: list[dict[str, Any]] = []

    assert probe_ocr(lambda: "ocr", records) == "ocr"
    assert probe_morphology(lambda: ("token",), records) == ("token",)
    assert probe_dictionary(lambda: {"status": "found"}, records)["status"] == "found"
    assert probe_result_dispatch(lambda: None, records) is None

    assert [record["stage"] for record in records] == [
        "ocr",
        "morphology",
        "dictionary",
        "result_dispatch",
    ]


def test_generic_probe_accepts_campaign_stage_names_and_measured_evidence() -> None:
    records: list[dict[str, Any]] = []

    assert probe_stage(
        "token_selection",
        lambda: "읽습니다",
        records,
        evidence_class="measured",
    ) == "읽습니다"

    assert records[0]["stage"] == "token_selection"
    assert records[0]["evidence_class"] == "measured"


def test_stage_probe_reraises_the_original_exception_and_records_failure() -> None:
    records: list[dict[str, Any]] = []
    error = ValueError("unchanged")

    def operation() -> object:
        raise error

    with pytest.raises(ValueError) as raised:
        probe_dictionary(operation, records)

    assert raised.value is error
    assert records[0]["correctness_status"] == "error"
    assert records[0]["exception_type"] == "ValueError"


def test_process_sampler_writes_flushed_csv_with_a_bounded_window() -> None:
    output = io.StringIO()
    sampler = ProcessSampler(output, interval_seconds=0.001, max_window_seconds=0.05)

    count = sampler.run(0.005)

    assert count >= 1
    rows = list(csv.DictReader(io.StringIO(output.getvalue())))
    assert len(rows) == count
    assert set(rows[0]) == {"timestamp", "cpu_percent", "rss_bytes"}
    assert output.getvalue().endswith("\n")


def test_package_analyzer_reports_exact_family_and_large_component_sizes(tmp_path: Path) -> None:
    files = {
        "easyocr/payload.bin": b"1234",
        "easyocr/model.pth": b"123456",
        "PyQt6/Qt6WebEngineCore.dll": b"12345",
        "numpy/core.pyd": b"123",
        "mystery/blob.bin": b"1234567890",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    report = analyze_package(tmp_path, large_component_threshold_bytes=8)

    assert report["total_bytes"] == sum(len(contents) for contents in files.values())
    assert report["file_count"] == len(files)
    assert report["families"]["EasyOCR"]["bytes"] == 10
    assert report["families"]["Qt/PyQt6/QtWebEngine"]["bytes"] == 5
    assert report["families"]["NumPy"]["bytes"] == 3
    assert report["unexpected_large_components"][0]["path"] == "mystery"
    json.dumps(report)


def test_package_analyzer_duplicate_hashing_is_explicit_and_bounded(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"duplicate")
    (tmp_path / "b.bin").write_bytes(b"duplicate")

    report = analyze_package(
        tmp_path,
        hash_duplicates=True,
        hash_max_files=1,
        hash_max_bytes=100,
    )

    assert report["duplicate_hashing"]["enabled"] is True
    assert report["duplicate_hashing"]["max_files"] == 1
    assert report["duplicate_hashing"]["hashed_files"] == 1
    assert report["duplicates"] == []


def test_package_analyzer_does_not_flag_the_expected_application_executable(
    tmp_path: Path,
) -> None:
    package = tmp_path / "hanly-desktop"
    package.mkdir()
    (package / "hanly-desktop.exe").write_bytes(b"expected-app")
    mystery = package / "mystery"
    mystery.mkdir()
    (mystery / "payload.bin").write_bytes(b"unexpected-data")

    report = analyze_package(package, large_component_threshold_bytes=8)

    assert [row["path"] for row in report["unexpected_large_components"]] == [
        "mystery"
    ]


def test_package_analyzer_object_exposes_analyze_method(tmp_path: Path) -> None:
    (tmp_path / "one.bin").write_bytes(b"1")

    report = PackageCompositionAnalyzer(tmp_path).analyze()

    assert report["file_count"] == 1


def test_package_analyzer_unwraps_one_pyinstaller_internal_prefix(tmp_path: Path) -> None:
    files = {
        "_internal/easyocr/model.bin": b"1234",
        "_internal/mystery/blob.bin": b"1234567890",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    report = analyze_package(tmp_path, large_component_threshold_bytes=8)

    assert [row["path"] for row in report["top_level"]] == ["mystery", "easyocr"]
    assert report["unexpected_large_components"][0]["path"] == "mystery"
    assert report["top_level"][1]["paths"] == ["_internal/easyocr/model.bin"]
