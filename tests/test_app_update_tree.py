"""Building the new installation beside the old one, and proving it is right.

A POSIX update never edits the installation. It reconstructs the published
build in a private directory - mostly out of bytes the installation already
holds - and the whole point of these cases is that what comes out is the
published build exactly, whether it was assembled from a delta or unpacked
from a whole product.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from hanly_app.app_inventory import read_tree, read_xattr
from hanly_app.app_manifest import tree_difference
from hanly_app.app_update_tree import (
    CandidateCancelled,
    CandidateError,
    assemble_candidate,
    copy_preserved,
    discard_candidate,
    extract_full_product,
    verify_candidate,
)

from tests.hanly_fixtures.update_release import PublishedRelease
from tests.hanly_fixtures.update_tree import LINUX, MACOS, Product, program_bytes

LINUX_CHANGES = {
    "hanly-desktop": program_bytes("linux", "x86_64", b"revised"),
    "_internal/added.so": b"a library the new build adds",
}


def _pair(
    tmp_path: Path, product: Product = LINUX, changes: dict[str, bytes] | None = None
) -> tuple[PublishedRelease, PublishedRelease, Path]:
    """Two published builds, and an installation of the earlier one."""

    base = PublishedRelease(
        tmp_path / "release-0.5.2", product, version="0.5.2", build_id="build-zero"
    )
    target = PublishedRelease(
        tmp_path / "release-0.5.3",
        product,
        version="0.5.3",
        build_id="build-one",
        changes=changes if changes is not None else LINUX_CHANGES,
        previous=base,
    )
    return base, target, base.install(tmp_path / "install")


def _reusable(base: PublishedRelease, target: PublishedRelease) -> tuple[str, ...]:
    """Every target file the installed build already holds unchanged."""

    difference = tree_difference(base.manifest, target.manifest)
    return tuple(
        entry.path
        for entry in target.manifest.files
        if entry.path not in difference.payload_paths
    )


def test_a_candidate_assembled_from_a_delta_is_exactly_the_published_build(
    tmp_path: Path,
) -> None:
    base, target, install = _pair(tmp_path)

    candidate = assemble_candidate(
        tmp_path / "tx" / "candidate",
        target.manifest,
        source_root=install,
        reusable=_reusable(base, target),
        payload=target.delta,
    )

    verify_candidate(candidate)
    assert read_tree(candidate.root, "linux").entries.keys() == target.manifest.entries.keys()
    assert candidate.reused_bytes > 0
    assert candidate.payload_bytes > 0


def test_a_candidate_unpacked_from_the_whole_product_is_the_same_build(
    tmp_path: Path,
) -> None:
    _base, target, _install = _pair(tmp_path)

    candidate = extract_full_product(tmp_path / "tx" / "candidate", target.full, target.manifest)

    verify_candidate(candidate)
    assert read_tree(candidate.root, "linux").entries.keys() == target.manifest.entries.keys()


def test_both_ways_of_building_a_candidate_produce_one_tree(tmp_path: Path) -> None:
    base, target, install = _pair(tmp_path)

    assembled = assemble_candidate(
        tmp_path / "from-delta" / "candidate",
        target.manifest,
        source_root=install,
        reusable=_reusable(base, target),
        payload=target.delta,
    )
    unpacked = extract_full_product(
        tmp_path / "from-product" / "candidate", target.full, target.manifest
    )

    left = read_tree(assembled.root, "linux")
    right = read_tree(unpacked.root, "linux")
    assert {path: entry.to_dict() for path, entry in left.entries.items()} == {
        path: entry.to_dict() for path, entry in right.entries.items()
    }


def test_a_reused_file_that_changed_since_planning_is_caught_while_it_is_copied(
    tmp_path: Path,
) -> None:
    base, target, install = _pair(tmp_path)
    (install / "_internal" / "libpython.so.1.0").write_bytes(b"replaced behind our back")

    with pytest.raises(CandidateError, match="changed while the update was being prepared"):
        assemble_candidate(
            tmp_path / "tx" / "candidate",
            target.manifest,
            source_root=install,
            reusable=_reusable(base, target),
            payload=target.delta,
        )


def test_a_payload_that_does_not_carry_a_needed_file_stops_the_build(
    tmp_path: Path,
) -> None:
    base, target, install = _pair(tmp_path)
    stripped = tmp_path / "stripped.zip"
    with zipfile.ZipFile(stripped, "w") as archive:
        archive.writestr("_internal/added.so", b"a library the new build adds")

    with pytest.raises(CandidateError, match="does not carry hanly-desktop"):
        assemble_candidate(
            tmp_path / "tx" / "candidate",
            target.manifest,
            source_root=install,
            reusable=_reusable(base, target),
            payload=stripped,
        )


def test_a_payload_carrying_a_link_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    _base, target, install = _pair(tmp_path)
    hostile = tmp_path / "hostile.zip"
    info = zipfile.ZipInfo("hanly-desktop")
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(hostile, "w") as archive:
        archive.writestr(info, "/etc/passwd")

    with pytest.raises(CandidateError, match="contains a link"):
        assemble_candidate(
            tmp_path / "tx" / "candidate",
            target.manifest,
            source_root=install,
            reusable=(),
            payload=hostile,
        )


def test_a_file_larger_than_the_release_describes_is_abandoned_mid_stream(
    tmp_path: Path,
) -> None:
    base, target, install = _pair(tmp_path)
    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("hanly-desktop", b"x" * 4096)
        archive.writestr("_internal/added.so", b"a library the new build adds")

    with pytest.raises(CandidateError, match="larger than the release describes"):
        assemble_candidate(
            tmp_path / "tx" / "candidate",
            target.manifest,
            source_root=install,
            reusable=_reusable(base, target),
            payload=oversized,
        )


def test_a_product_archive_carrying_more_than_a_build_does_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base, target, _install = _pair(tmp_path)
    monkeypatch.setattr("hanly_app.app_update_tree.MAX_PRODUCT_BYTES", 8)

    with pytest.raises(CandidateError, match="expands past"):
        extract_full_product(tmp_path / "tx" / "candidate", target.full, target.manifest)


def test_extras_a_person_kept_are_copied_across_and_stay_theirs(tmp_path: Path) -> None:
    base, target, install = _pair(tmp_path)
    (install / "notes.txt").write_bytes(b"mine")
    (install / "logs").mkdir()
    (install / "logs" / "session.log").write_bytes(b"a log")

    candidate = copy_preserved(
        assemble_candidate(
            tmp_path / "tx" / "candidate",
            target.manifest,
            source_root=install,
            reusable=_reusable(base, target),
            payload=target.delta,
        ),
        install,
        ("notes.txt", "logs", "logs/session.log"),
    )

    verify_candidate(candidate)
    assert (candidate.root / "notes.txt").read_bytes() == b"mine"
    assert (candidate.root / "logs" / "session.log").read_bytes() == b"a log"
    assert "notes.txt" not in target.manifest
    assert candidate.preserved_bytes > 0


def test_an_extra_that_is_part_of_the_new_build_is_not_an_extra(tmp_path: Path) -> None:
    base, target, install = _pair(tmp_path)
    candidate = assemble_candidate(
        tmp_path / "tx" / "candidate",
        target.manifest,
        source_root=install,
        reusable=_reusable(base, target),
        payload=target.delta,
    )

    with pytest.raises(CandidateError, match="part of the new build"):
        copy_preserved(candidate, install, ("hanly-desktop",))


def test_a_candidate_missing_or_carrying_something_extra_does_not_verify(
    tmp_path: Path,
) -> None:
    _base, target, _install = _pair(tmp_path)
    candidate = extract_full_product(
        tmp_path / "tx" / "candidate", target.full, target.manifest
    )
    (candidate.root / "stowaway").write_bytes(b"not in the release")

    with pytest.raises(CandidateError, match="unexpected"):
        verify_candidate(candidate)

    (candidate.root / "stowaway").unlink()
    (candidate.root / "hanly-desktop").unlink()
    with pytest.raises(CandidateError, match="missing"):
        verify_candidate(candidate)


def test_a_candidate_whose_permissions_are_wrong_does_not_verify(tmp_path: Path) -> None:
    _base, target, _install = _pair(tmp_path)
    candidate = extract_full_product(
        tmp_path / "tx" / "candidate", target.full, target.manifest
    )
    (candidate.root / "hanly-desktop").chmod(0o600)

    with pytest.raises(CandidateError, match="does not match the release"):
        verify_candidate(candidate)


def test_a_macos_candidate_reproduces_its_links_modes_and_signature_material(
    tmp_path: Path,
) -> None:
    base, target, install = _pair(
        tmp_path, MACOS, {"Contents/_CodeSignature/CodeResources": b"<seal>revised</seal>"}
    )

    candidate = assemble_candidate(
        tmp_path / "tx" / "candidate",
        target.manifest,
        source_root=install,
        reusable=_reusable(base, target),
        payload=target.delta,
    )

    verify_candidate(candidate)
    framework = candidate.root / "Contents/Frameworks/Qt.framework"
    assert os.readlink(framework / "Versions" / "Current") == "A"
    assert os.readlink(framework / "Qt") == "Versions/Current/Qt"
    program = candidate.root / "Contents/MacOS/hanly-desktop"
    assert program.stat().st_mode & 0o777 == 0o755
    assert read_xattr(program, "com.apple.cs.CodeDirectory") == b"signature for 0.5.3"


def test_a_signature_that_changed_without_the_bytes_costs_no_download(
    tmp_path: Path,
) -> None:
    """The one place a file changes and carries nothing: its signature moved."""

    base, target, _install = _pair(tmp_path, MACOS, {})
    difference = tree_difference(base.manifest, target.manifest)

    assert "Contents/MacOS/hanly-desktop" in difference.changed_paths
    assert "Contents/MacOS/hanly-desktop" not in difference.payload_paths


def test_cancelling_leaves_a_candidate_that_can_simply_be_thrown_away(
    tmp_path: Path,
) -> None:
    base, target, install = _pair(tmp_path)
    destination = tmp_path / "tx" / "candidate"

    with pytest.raises(CandidateCancelled):
        assemble_candidate(
            destination,
            target.manifest,
            source_root=install,
            reusable=_reusable(base, target),
            payload=target.delta,
            should_cancel=lambda: True,
        )

    discard_candidate(destination)
    assert not destination.exists()
    assert read_tree(install, "linux").entries.keys() == base.manifest.entries.keys()


def test_a_windows_manifest_is_not_installed_by_replacing_a_tree(tmp_path: Path) -> None:
    from tests.hanly_fixtures.update_tree import WINDOWS

    release = PublishedRelease(
        tmp_path / "release", WINDOWS, version="0.5.3", build_id="build-one"
    )

    with pytest.raises(CandidateError, match="does not install by replacing"):
        extract_full_product(tmp_path / "tx" / "candidate", release.full, release.manifest)
