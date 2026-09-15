"""The release inventory contract, and the producer that writes it.

One schema is read by two programs that never run together: the build that
publishes a release, and the installation that consumes it months later. These
cases hold both to the same document.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from hanly_app.app_inventory import (
    build_manifest,
    component_for,
    read_installation,
    read_installed_manifest,
)
from hanly_app.app_manifest import (
    INSTALLED_MANIFEST_NAME,
    SCHEMA_VERSION,
    BuildIdentity,
    FileEntry,
    InstallManifest,
    ManifestError,
    UpdateMetadata,
    parse_checksums,
    require_safe_relative_path,
)

from tools.update_artifacts import (
    ArtifactError,
    build_release_products,
    generate_manifest,
    host_architecture,
    load_base_manifest,
)


def _identity(version: str = "1.0.0", build_id: str = "abc123") -> BuildIdentity:
    return BuildIdentity(
        product="hanly-desktop",
        platform="windows",
        architecture="x86_64",
        version=version,
        build_id=build_id,
    )


def _entry(path: str, content: str) -> FileEntry:
    import hashlib

    raw = content.encode("utf-8")
    return FileEntry(path=path, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))


def _tree(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


BUILD = {
    "hanly-desktop.exe": "program v1\n",
    "_internal/base_library.zip": "library\n",
    "_internal/torch/lib.dll": "a very large dependency\n",
    "_internal/hanly_app/assets/page.html": "<p>hello</p>\n",
}


@pytest.mark.parametrize(
    "path",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "back\\slash.txt",
        "stream.txt:hidden",
        "CON",
        "nul.txt",
        "trailing. /file.txt",
        "trailing.",
        ".hanly-update/payload/0001",
        ".hanly-manifest.json",
        "",
    ],
)
def test_a_path_that_could_land_outside_the_installation_is_refused(path: str) -> None:
    """Every one of these either escapes the installation, names a device
    Windows reserves, or belongs to the updater rather than the product."""

    with pytest.raises(ManifestError):
        require_safe_relative_path(path)


def test_two_paths_windows_cannot_tell_apart_are_not_one_manifest() -> None:
    """A case-insensitive filesystem would make these one file, so a manifest
    holding both describes a build that cannot exist."""

    with pytest.raises(ManifestError, match="differ only in case"):
        InstallManifest.from_entries(
            _identity(), [_entry("Data/File.txt", "a"), _entry("data/file.txt", "b")]
        )


def test_a_file_cannot_also_be_another_file_s_directory() -> None:
    with pytest.raises(ManifestError, match="both a file and a directory"):
        InstallManifest.from_entries(
            _identity(), [_entry("lib", "a"), _entry("lib/inner.txt", "b")]
        )


def test_a_manifest_round_trips_through_its_own_json(tmp_path: Path) -> None:
    manifest = build_manifest(_tree(tmp_path, BUILD), _identity())

    restored = InstallManifest.from_json(manifest.to_json())

    assert restored == manifest
    assert restored.digest() == manifest.digest()
    assert len(restored) == len(BUILD)


def test_a_document_from_a_future_schema_is_refused_rather_than_guessed_at() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION + 1,
        "identity": _identity().to_dict(),
        "files": [_entry("a.txt", "a").to_dict()],
    }

    with pytest.raises(ManifestError, match="schema version"):
        InstallManifest.from_payload(payload)


def test_the_digest_changes_when_any_file_does(tmp_path: Path) -> None:
    """A delta names the digest of the build it starts from, so two builds that
    differ anywhere must not share one."""

    first = build_manifest(_tree(tmp_path / "a", BUILD), _identity())
    second = build_manifest(
        _tree(tmp_path / "b", {**BUILD, "hanly-desktop.exe": "program v2\n"}), _identity()
    )

    assert first.digest() != second.digest()


def test_the_inventory_excludes_the_updater_s_own_files(tmp_path: Path) -> None:
    """A tree that has been updated once carries a working directory and its own
    manifest; adopting either as product content would make every later update
    try to install the last one."""

    root = _tree(tmp_path, BUILD)
    (root / ".hanly-update" / "t1").mkdir(parents=True)
    (root / ".hanly-update" / "t1" / "plan.json").write_text("{}", encoding="utf-8")
    (root / INSTALLED_MANIFEST_NAME).write_text("{}", encoding="utf-8")

    tree = read_installation(root)

    assert set(tree.entries) == set(BUILD)


def test_a_python_cache_the_runtime_wrote_is_left_alone_entirely(tmp_path: Path) -> None:
    """A frozen build ships no bytecode cache, so anything under one was
    written by a run. It is not hashed, not owned, and not deleted: a whole
    directory of them would cost the inspection more than the update."""

    cache = "_internal/hanly_app/__pycache__/x.pyc"
    root = _tree(tmp_path, {**BUILD, cache: "cached"})

    tree = read_installation(root)

    assert cache not in tree.entries
    assert set(tree.entries) == set(BUILD)
    assert root.joinpath(*cache.split("/")).is_file()


@pytest.mark.parametrize(
    "path, component",
    [
        ("hanly-desktop.exe", "application"),
        ("_internal/torch/lib.dll", "torch"),
        ("_internal/python310.dll", "python310"),
    ],
)
def test_a_file_is_labelled_by_the_package_a_person_would_recognize(
    path: str, component: str
) -> None:
    assert component_for(path) == component


def test_checksums_are_read_from_the_format_sha256sum_writes() -> None:
    text = "".join(
        (
            f"{'a' * 64}  hanly-desktop-windows.zip\n",
            f"{'b' * 64} *SHA256SUMS.sig\n",
            "not a checksum line\n",
        )
    )

    assert parse_checksums(text) == {
        "hanly-desktop-windows.zip": "a" * 64,
        "SHA256SUMS.sig": "b" * 64,
    }


def test_the_producer_leaves_the_inventory_inside_the_build(tmp_path: Path) -> None:
    """A fresh installation has to know what it is made of without asking the
    network, which is what makes its first update differential."""

    root = _tree(tmp_path, BUILD)

    manifest = generate_manifest(root, "1.2.3", architecture="x86_64")

    written = read_installed_manifest(root)
    assert written == manifest
    assert manifest.identity.version == "1.2.3"
    # Derived from the contents, so one build is reproducibly named and two
    # builds of one version are still distinguishable.
    assert manifest.identity.build_id == generate_manifest(root, "1.2.3").identity.build_id


def test_a_release_publishes_a_delta_holding_only_what_changed(tmp_path: Path) -> None:
    """The whole point: an unchanged dependency is not in the payload."""

    base_root = _tree(tmp_path / "old", BUILD)
    base = generate_manifest(base_root, "1.0.0", architecture="x86_64")
    base_manifest = tmp_path / "base.manifest.json"
    base_manifest.write_text(base.to_json(), encoding="utf-8")

    target_root = _tree(
        tmp_path / "new",
        {
            **BUILD,
            "hanly-desktop.exe": "program v2\n",
            "_internal/hanly_app/assets/new.js": "added\n",
        },
    )
    del_path = target_root / "_internal" / "base_library.zip"
    del_path.unlink()
    archive = tmp_path / "hanly-desktop-windows.zip"
    archive.write_bytes(b"the full archive")

    products = build_release_products(
        target_root,
        archive,
        "1.1.0",
        tmp_path / "out",
        architecture="x86_64",
        base_manifest_path=base_manifest,
    )

    assert products.delta_path is not None
    with zipfile.ZipFile(products.delta_path) as payload:
        assert sorted(payload.namelist()) == [
            "_internal/hanly_app/assets/new.js",
            "hanly-desktop.exe",
        ]

    metadata = UpdateMetadata.from_json(products.metadata_path.read_text(encoding="utf-8"))
    assert metadata.delta is not None
    assert metadata.delta.base_version == "1.0.0"
    assert metadata.delta.deletions == ("_internal/base_library.zip",)
    assert metadata.manifest_digest == InstallManifest.from_json(
        products.manifest_path.read_text(encoding="utf-8")
    ).digest()


def test_a_release_with_no_usable_predecessor_still_publishes(tmp_path: Path) -> None:
    """The first manifest-aware build has nothing to diff against, and a
    release that stopped for that reason would never be the first one."""

    archive = tmp_path / "hanly-desktop-windows.zip"
    archive.write_bytes(b"the full archive")

    products = build_release_products(
        _tree(tmp_path / "new", BUILD),
        archive,
        "1.0.0",
        tmp_path / "out",
        architecture="x86_64",
    )

    assert products.delta_path is None
    metadata = UpdateMetadata.from_json(products.metadata_path.read_text(encoding="utf-8"))
    assert metadata.delta is None
    assert metadata.delta_omitted_reason
    assert metadata.full.name == "hanly-desktop-windows.zip"


def test_a_previous_manifest_its_release_did_not_publish_is_refused(tmp_path: Path) -> None:
    """A delta assembled against a rebuilt tag applies to a build nobody has
    installed, so the base is proved against that release's own checksums."""

    manifest = tmp_path / "base.manifest.json"
    manifest.write_text(
        generate_manifest(_tree(tmp_path / "old", BUILD), "1.0.0", architecture="x86_64").to_json(),
        encoding="utf-8",
    )
    checksums = tmp_path / "SHA256SUMS"
    checksums.write_text(f"{'0' * 64}  hanly-desktop-windows.manifest.json\n", encoding="utf-8")

    with pytest.raises(ArtifactError, match="not the manifest"):
        load_base_manifest(manifest, checksums)


def test_a_release_without_the_application_it_describes_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="not a built application directory"):
        build_release_products(
            tmp_path / "missing", tmp_path / "nothing.zip", "1.0.0", tmp_path / "out"
        )


@pytest.mark.parametrize(
    "machine, expected",
    [("AMD64", "x86_64"), ("x86_64", "x86_64"), ("arm64", "arm64"), ("aarch64", "arm64")],
)
def test_the_machine_name_is_normalized_into_one_label(machine: str, expected: str) -> None:
    assert host_architecture(machine) == expected


def test_update_metadata_round_trips_through_its_published_json(tmp_path: Path) -> None:
    archive = tmp_path / "hanly-desktop-windows.zip"
    archive.write_bytes(b"the full archive")
    products = build_release_products(
        _tree(tmp_path / "new", BUILD), archive, "1.0.0", tmp_path / "out", architecture="x86_64"
    )

    text = products.metadata_path.read_text(encoding="utf-8")

    assert UpdateMetadata.from_json(text).to_dict() == json.loads(text)
