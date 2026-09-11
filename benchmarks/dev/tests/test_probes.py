"""Focused tests for the isolated observational tooling."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from benchmarks.dev.package_composition import analyze_package
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


def test_package_analyzer_groups_a_macos_bundle_by_package_not_by_contents(
    tmp_path: Path,
) -> None:
    """Every collected file in a ``.app`` sits under ``Contents``, so leaving
    that prefix on reports one component holding the whole bundle and never
    names an unrecognized one."""

    files = {
        "Contents/Frameworks/torch/lib/libtorch.dylib": b"1234567890",
        "Contents/Frameworks/_internal/mystery/blob.bin": b"1234567890",
        "Contents/Resources/easyocr/character/ko_char.txt": b"1234",
        "Contents/MacOS/hanly-desktop": b"12",
        "Contents/Info.plist": b"1",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    report = analyze_package(tmp_path, large_component_threshold_bytes=8)

    assert [row["path"] for row in report["top_level"]] == [
        "mystery",
        "torch",
        "easyocr",
        "hanly-desktop",
        "Contents",
    ]
    assert [row["path"] for row in report["unexpected_large_components"]] == ["mystery"]


def test_package_analyzer_separates_bundled_weights_and_kiwi_assets(
    tmp_path: Path,
) -> None:
    files = {
        "hanly_app/assets/easyocr_models/korean_g2.pth": b"weight",
        "kiwipiepy_model/nounchr.mdl": b"kiwi-model",
        "kiwipiepy/core.py": b"core",
        "_kiwipiepy.abi3.so": b"native",
        "torchvision/models/resnet.py": b"python-module",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    report = analyze_package(tmp_path)

    assert report["families"]["EasyOCR bundled weights"]["bytes"] == 6
    assert report["families"]["Kiwi/model assets"]["bytes"] == 20
    assert report["families"]["models/KRDICT"]["files"] == 0


def test_package_analyzer_reports_optional_zip_metrics(tmp_path: Path) -> None:
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_internal/app.bin", b"1234")
        archive.writestr("_internal/data.txt", b"56789")
        archive.writestr(
            "_internal/hanly_app/assets/easyocr_models/korean_g2.pth",
            b"weight",
        )
        archive.writestr("_internal/kiwipiepy_model/nounchr.mdl", b"kiwi")
        archive.writestr("_internal/", b"")

    report = analyze_package(tmp_path, archive=archive_path)
    archive_report = report["archive"]

    assert archive_report["file_count"] == 4
    assert archive_report["uncompressed_member_bytes"] == 19
    with zipfile.ZipFile(archive_path) as archive:
        expected_compressed_bytes = sum(
            info.compress_size for info in archive.infolist() if not info.is_dir()
        )
    assert archive_report["compressed_member_bytes"] == expected_compressed_bytes
    assert archive_report["archive_bytes"] == archive_path.stat().st_size
    with zipfile.ZipFile(archive_path) as archive:
        archive_infos = {
            info.filename: info
            for info in archive.infolist()
            if not info.is_dir()
        }
    assert archive_report["families"]["EasyOCR bundled weights"] == {
        "file_count": 1,
        "uncompressed_member_bytes": 6,
        "compressed_member_bytes": archive_infos[
            "_internal/hanly_app/assets/easyocr_models/korean_g2.pth"
        ].compress_size,
    }
    assert archive_report["families"]["Kiwi/model assets"] == {
        "file_count": 1,
        "uncompressed_member_bytes": 4,
        "compressed_member_bytes": archive_infos[
            "_internal/kiwipiepy_model/nounchr.mdl"
        ].compress_size,
    }
    assert archive_report["largest_members"][:2] == [
        {
            "path": "_internal/hanly_app/assets/easyocr_models/korean_g2.pth",
            "uncompressed_bytes": 6,
            "compressed_bytes": archive_infos[
                "_internal/hanly_app/assets/easyocr_models/korean_g2.pth"
            ].compress_size,
        },
        {
            "path": "_internal/data.txt",
            "uncompressed_bytes": 5,
            "compressed_bytes": archive_infos["_internal/data.txt"].compress_size,
        },
    ]
    json.dumps(report)


def test_package_analyzer_reports_bounded_hash_duplicates(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"duplicate")
    (tmp_path / "b.bin").write_bytes(b"duplicate")
    (tmp_path / "c.bin").write_bytes(b"different")

    report = analyze_package(
        tmp_path,
        hash_duplicates=True,
        hash_max_files=2,
        hash_max_bytes=100,
    )

    assert report["duplicates"][0]["files"] == [
        {"path": "a.bin", "bytes": 9},
        {"path": "b.bin", "bytes": 9},
    ]
    assert report["duplicate_hashing"]["skipped_files"] == 1


def test_package_analyzer_keeps_posix_symlink_targets_out_of_tree_totals(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    try:
        (tmp_path / "link.bin").symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable on this platform")

    report = analyze_package(tmp_path)

    assert report["file_count"] == 1
    assert report["total_bytes"] == len(b"target")
