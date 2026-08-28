"""Exact, read-only package-tree composition analysis of a frozen build."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO, cast

_FAMILY_NAMES = (
    "EasyOCR",
    "Qt/PyQt6/QtWebEngine",
    "NumPy",
    "Pandas",
    "OpenCV",
    "Torch",
    "SciPy",
    "models/KRDICT",
)


def _family_for(path: Path) -> str | None:
    parts = tuple(part.casefold() for part in path.parts)
    joined = "/".join(parts)

    if any(part in {"easyocr"} for part in parts):
        return "EasyOCR"
    if any(part in {"pyqt6", "qt6", "qt", "qtwebengine", "pyqt6_qt6"} for part in parts):
        return "Qt/PyQt6/QtWebEngine"
    if any(part in {"numpy", "numpy.libs", "numpy_core"} for part in parts):
        return "NumPy"
    if any(part in {"pandas", "pandas.libs"} for part in parts):
        return "Pandas"
    if any(part in {"cv2", "opencv", "opencv_python"} for part in parts):
        return "OpenCV"
    if any(part in {"torch", "torch.libs"} for part in parts):
        return "Torch"
    if any(part in {"scipy", "scipy.libs"} for part in parts):
        return "SciPy"
    if any(part in {"models", "model", "krdict", "krdict.sqlite", "krdict.db"} for part in parts):
        return "models/KRDICT"

    # Distribution snapshots often contain names such as ``easyocr-1.7.2``.
    if "easyocr" in joined:
        return "EasyOCR"
    if "qtwebengine" in joined or "pyqt6" in joined:
        return "Qt/PyQt6/QtWebEngine"
    if "numpy" in joined:
        return "NumPy"
    if "pandas" in joined:
        return "Pandas"
    if "opencv" in joined or "cv2" in joined:
        return "OpenCV"
    if "torch" in joined:
        return "Torch"
    if "scipy" in joined:
        return "SciPy"
    if "krdict" in joined:
        return "models/KRDICT"
    return None


def _files_under(root: Path) -> list[tuple[str, Path, int]]:
    files: list[tuple[str, Path, int]] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = sorted(
            name for name in directory_names if not (Path(current) / name).is_symlink()
        )
        for name in sorted(file_names):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            files.append((relative, path, path.stat().st_size))
    return files


def _component_name(relative: str) -> str:
    logical = _logical_relative(relative)
    return logical.split("/", 1)[0]


def _logical_relative(relative: str) -> str:
    """Drop one PyInstaller payload prefix for component grouping only."""
    parts = relative.split("/")
    if len(parts) > 1 and parts[0].casefold() == "_internal":
        return "/".join(parts[1:])
    return relative


def _empty_group() -> dict[str, Any]:
    return {"bytes": 0, "files": 0, "paths": []}


def _hash_duplicates(
    entries: Iterable[tuple[str, Path, int]],
    *,
    max_files: int,
    max_bytes: int,
) -> tuple[list[dict[str, Any]], int, int, int]:
    digest_paths: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hashed_files = 0
    hashed_bytes = 0
    skipped_files = 0

    for relative, path, size in entries:
        if hashed_files >= max_files or hashed_bytes + size > max_bytes:
            skipped_files += 1
            continue

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest_paths[digest.hexdigest()].append({"path": relative, "bytes": size})
        hashed_files += 1
        hashed_bytes += size

    duplicates = [
        {"sha256": digest, "files": paths}
        for digest, paths in sorted(digest_paths.items())
        if len(paths) > 1
    ]
    return duplicates, hashed_files, hashed_bytes, skipped_files


def analyze_package(
    root: str | os.PathLike[str],
    *,
    large_component_threshold_bytes: int = 50 * 1024 * 1024,
    hash_duplicates: bool = False,
    hash_max_files: int = 10_000,
    hash_max_bytes: int = 2 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    """Return exact file/byte totals and dependency-family groupings.

    The default pass never reads file contents.  Duplicate hashing is opt-in
    and has independent file and byte caps so a large package cannot trigger
    an unbounded hashing campaign.
    """
    package_root = Path(root).resolve()
    if not package_root.is_dir():
        raise NotADirectoryError(str(package_root))
    if large_component_threshold_bytes < 0:
        raise ValueError("large_component_threshold_bytes must be non-negative")
    if hash_max_files < 0 or hash_max_bytes < 0:
        raise ValueError("duplicate hashing limits must be non-negative")

    entries = _files_under(package_root)
    top_level: dict[str, dict[str, Any]] = {}
    families = {name: _empty_group() for name in _FAMILY_NAMES}
    recognized_components: set[str] = set()
    total_bytes = 0

    for relative, _path, size in entries:
        total_bytes += size
        component = _component_name(relative)
        group = top_level.setdefault(component, _empty_group())
        group["bytes"] += size
        group["files"] += 1
        group["paths"].append(relative)

        family = _family_for(Path(relative))
        if family is not None:
            recognized_components.add(component)
            family_group = families[family]
            family_group["bytes"] += size
            family_group["files"] += 1
            family_group["paths"].append(relative)

    top_level_rows = [
        {"path": name, **values}
        for name, values in sorted(top_level.items(), key=lambda item: (-item[1]["bytes"], item[0]))
    ]
    for values in families.values():
        values["paths"].sort()

    large_components = [
        row
        for row in top_level_rows
        if row["bytes"] >= large_component_threshold_bytes
        and row["path"] not in recognized_components
        and row["path"] not in {package_root.name, f"{package_root.name}.exe"}
    ]

    if hash_duplicates:
        duplicates, hashed_files, hashed_bytes, skipped_files = _hash_duplicates(
            entries,
            max_files=hash_max_files,
            max_bytes=hash_max_bytes,
        )
    else:
        duplicates, hashed_files, hashed_bytes, skipped_files = [], 0, 0, len(entries)

    return {
        "schema_version": 1,
        "root": str(package_root),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "top_level": top_level_rows,
        "families": families,
        "unexpected_large_components": large_components,
        "duplicate_hashing": {
            "enabled": hash_duplicates,
            "bounded": True,
            "max_files": hash_max_files if hash_duplicates else None,
            "max_bytes": hash_max_bytes if hash_duplicates else None,
            "hashed_files": hashed_files,
            "hashed_bytes": hashed_bytes,
            "skipped_files": skipped_files,
        },
        "duplicates": duplicates,
    }


def write_package_report(
    root: str | os.PathLike[str],
    destination: str | os.PathLike[str] | TextIO,
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze ``root`` and write its JSON report to a stream or path."""
    report = analyze_package(root, **kwargs)
    if hasattr(destination, "write"):
        stream = cast(TextIO, destination)
        close_stream = False
    else:
        stream = Path(destination).open("w", encoding="utf-8")
        close_stream = True
    try:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
    finally:
        if close_stream:
            stream.close()
    return report


analyze_package_composition = analyze_package


class PackageCompositionAnalyzer:
    """Reusable configuration object for package composition reports."""

    def __init__(self, root: str | os.PathLike[str], **options: Any) -> None:
        self.root = root
        self.options = dict(options)

    def analyze(self) -> dict[str, Any]:
        """Analyze the configured package tree."""
        return analyze_package(self.root, **self.options)

    def write(self, destination: str | os.PathLike[str] | TextIO) -> dict[str, Any]:
        """Analyze and write the configured report as JSON."""
        return write_package_report(self.root, destination, **self.options)


__all__ = [
    "PackageCompositionAnalyzer",
    "analyze_package",
    "analyze_package_composition",
    "write_package_report",
]
