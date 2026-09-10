"""Exact, read-only package-tree composition analysis of a frozen build."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO, cast

_FAMILY_NAMES = (
    "EasyOCR",
    "EasyOCR bundled weights",
    "Kiwi/model assets",
    "Qt/PyQt6/QtWebEngine",
    "NumPy",
    "OpenCV",
    "Torch",
    "SciPy",
    "models/KRDICT",
)
_ARCHIVE_LARGEST_MEMBER_LIMIT = 10

#: Payload prefixes stripped before grouping, outermost first so a macOS
#: bundle directory is removed before the ``_internal`` it may contain.
_PAYLOAD_PREFIXES = (
    ("contents", "frameworks"),
    ("contents", "resources"),
    ("contents", "macos"),
    ("_internal",),
)


def _family_for(path: Path) -> str | None:
    parts = tuple(part.casefold() for part in path.parts)
    joined = "/".join(parts)

    if any(part == "easyocr_models" for part in parts) or path.name.casefold() in {
        "craft_mlt_25k.pth",
        "korean_g2.pth",
    }:
        return "EasyOCR bundled weights"
    if any(part in {"easyocr"} for part in parts):
        return "EasyOCR"
    if any(
        part == "kiwipiepy"
        or part == "kiwipiepy_model"
        or part.startswith(("kiwipiepy-", "kiwipiepy_model-", "_kiwipiepy."))
        for part in parts
    ):
        return "Kiwi/model assets"
    if any(part in {"pyqt6", "qt6", "qt", "qtwebengine", "pyqt6_qt6"} for part in parts):
        return "Qt/PyQt6/QtWebEngine"
    if any(part in {"numpy", "numpy.libs", "numpy_core"} for part in parts):
        return "NumPy"
    if any(part in {"cv2", "opencv", "opencv_python"} for part in parts):
        return "OpenCV"
    if any(part in {"torch", "torch.libs", "torchvision"} for part in parts):
        return "Torch"
    if any(part in {"scipy", "scipy.libs"} for part in parts):
        return "SciPy"
    if any(part in {"models", "model", "krdict", "krdict.sqlite", "krdict.db"} for part in parts):
        return "models/KRDICT"

    # Distribution snapshots often contain names such as ``easyocr-1.7.2``.
    if "easyocr" in joined:
        return "EasyOCR"
    if "kiwipiepy_model" in joined or "kiwipiepy" in joined or "_kiwipiepy" in joined:
        return "Kiwi/model assets"
    if "qtwebengine" in joined or "pyqt6" in joined:
        return "Qt/PyQt6/QtWebEngine"
    if "numpy" in joined:
        return "NumPy"
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
    """Drop the frozen payload prefixes for component grouping only.

    A macOS bundle splits one collection across ``Frameworks`` and
    ``Resources``, either of which may hold an ``_internal`` of its own, so
    more than one prefix can apply to the same path.
    """
    parts = relative.split("/")
    for prefix in _PAYLOAD_PREFIXES:
        head = tuple(part.casefold() for part in parts[: len(prefix)])
        if head == prefix and len(parts) > len(prefix):
            parts = parts[len(prefix) :]
    return "/".join(parts)


def _empty_group() -> dict[str, Any]:
    return {"bytes": 0, "files": 0, "paths": []}


def _empty_archive_group() -> dict[str, Any]:
    return {
        "file_count": 0,
        "uncompressed_member_bytes": 0,
        "compressed_member_bytes": 0,
    }


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


def _archive_report(archive: str | os.PathLike[str]) -> dict[str, Any]:
    """Read ZIP metadata without extracting or reading member contents."""
    archive_path = Path(archive).resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(str(archive_path))

    file_count = 0
    uncompressed_member_bytes = 0
    compressed_member_bytes = 0
    families = {name: _empty_archive_group() for name in _FAMILY_NAMES}
    largest_members: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive_path) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            file_count += 1
            uncompressed_member_bytes += member.file_size
            compressed_member_bytes += member.compress_size

            largest_members.append(
                {
                    "path": member.filename,
                    "uncompressed_bytes": member.file_size,
                    "compressed_bytes": member.compress_size,
                }
            )
            largest_members.sort(
                key=lambda item: (-item["uncompressed_bytes"], item["path"])
            )
            del largest_members[_ARCHIVE_LARGEST_MEMBER_LIMIT:]
            family = _family_for(Path(member.filename))
            if family is not None:
                family_group = families[family]
                family_group["file_count"] += 1
                family_group["uncompressed_member_bytes"] += member.file_size
                family_group["compressed_member_bytes"] += member.compress_size

    return {
        "path": str(archive_path),
        "file_count": file_count,
        "uncompressed_member_bytes": uncompressed_member_bytes,
        "compressed_member_bytes": compressed_member_bytes,
        "archive_bytes": archive_path.stat().st_size,
        "families": families,
        "largest_members": largest_members,
    }


def analyze_package(
    root: str | os.PathLike[str],
    *,
    large_component_threshold_bytes: int = 50 * 1024 * 1024,
    hash_duplicates: bool = False,
    hash_max_files: int = 10_000,
    hash_max_bytes: int = 2 * 1024 * 1024 * 1024,
    archive: str | os.PathLike[str] | None = None,
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
        "archive": None if archive is None else _archive_report(archive),
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


__all__ = [
    "analyze_package",
    "write_package_report",
]
