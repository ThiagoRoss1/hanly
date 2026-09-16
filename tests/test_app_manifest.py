"""The release inventory contract, and the producer that writes it.

One schema is read by two programs that never run together: the build that
publishes a release, and the installation that consumes it months later. These
cases hold both to the same document.
"""

from __future__ import annotations

import base64
import json
import os
import zipfile
from pathlib import Path

import pytest
from hanly_app.app_build_identity import BuildIdentityError
from hanly_app.app_inventory import (
    InventoryError,
    build_manifest,
    compare_tree,
    component_for,
    read_installation,
    read_installed_manifest,
    read_tree,
)
from hanly_app.app_manifest import (
    INSTALLED_MANIFEST_NAME,
    KIND_DIRECTORY,
    KIND_FILE,
    KIND_SYMLINK,
    SCHEMA_VERSION,
    TREE_SCHEMA_VERSION,
    BuildIdentity,
    FileEntry,
    InstallManifest,
    ManifestError,
    TreeEntry,
    TreeLayout,
    TreeManifest,
    UpdateMetadata,
    parse_checksums,
    require_safe_relative_path,
    require_tree_path,
    tree_difference,
)

from tests.hanly_fixtures.capabilities import requires_material_xattrs
from tests.hanly_fixtures.update_tree import (
    LINUX,
    MACOS,
    SOURCE_COMMIT,
    WINDOWS,
    Product,
    entry_at,
    manifest_for,
    sign_entry,
    write_tree,
)
from tools.update_artifacts import (
    ArtifactError,
    assemble_tree_delta,
    build_release_products,
    generate_manifest,
    generate_tree_manifest,
    host_architecture,
    load_base_manifest,
    read_build_stamp_file,
    tree_delta_path,
    write_build_stamp,
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


# --------------------------------------------------------------------------
# Schema 2: the whole tree, on every platform
# --------------------------------------------------------------------------


def _bundle_identity(platform: str = "macos", architecture: str = "arm64") -> BuildIdentity:
    return BuildIdentity(
        product="hanly-desktop",
        platform=platform,
        architecture=architecture,
        version="0.5.3",
        build_id="4e6a2b18-0f2c-4d41-9d0a-7b5c8e1f2a33",
    )


def _bundle_entries(**overrides: TreeEntry) -> list[TreeEntry]:
    """The smallest bundle-shaped tree the rules all have something to say about."""

    entries = {
        "Contents": TreeEntry(path="Contents", kind=KIND_DIRECTORY, mode=0o755),
        "Contents/MacOS": TreeEntry(path="Contents/MacOS", kind=KIND_DIRECTORY, mode=0o755),
        "Contents/MacOS/hanly-desktop": TreeEntry(
            path="Contents/MacOS/hanly-desktop",
            kind=KIND_FILE,
            sha256="c" * 64,
            size=120,
            mode=0o755,
        ),
        "Contents/Info.plist": TreeEntry(
            path="Contents/Info.plist", kind=KIND_FILE, sha256="d" * 64, size=20, mode=0o644
        ),
    }
    entries.update({entry.path: entry for entry in overrides.values()})
    return list(entries.values())


def _bundle_layout() -> TreeLayout:
    return TreeLayout(root="Hanly.app", executable="Contents/MacOS/hanly-desktop", mode=0o755)


def _bundle(*extra: TreeEntry) -> TreeManifest:
    return TreeManifest.from_entries(
        _bundle_identity(), _bundle_layout(), [*_bundle_entries(), *extra]
    )


def test_tree_manifest_round_trips_through_its_canonical_bytes() -> None:
    manifest = _bundle()

    restored = TreeManifest.from_json(manifest.to_json())

    assert restored.digest() == manifest.digest()
    assert restored.to_json() == manifest.to_json()
    assert json.loads(manifest.to_json())["schema_version"] == TREE_SCHEMA_VERSION


def test_two_manifests_of_one_tree_serialize_identically_whatever_the_order() -> None:
    entries = _bundle_entries()
    forward = TreeManifest.from_entries(_bundle_identity(), _bundle_layout(), entries)
    backward = TreeManifest.from_entries(
        _bundle_identity(), _bundle_layout(), list(reversed(entries))
    )

    assert forward.to_json() == backward.to_json()


def test_a_framework_reaches_its_binary_through_a_link_to_a_link() -> None:
    framework = "Contents/Frameworks/Qt.framework"
    manifest = _bundle(
        TreeEntry(path="Contents/Frameworks", kind=KIND_DIRECTORY, mode=0o755),
        TreeEntry(path=framework, kind=KIND_DIRECTORY, mode=0o755),
        TreeEntry(path=f"{framework}/Versions", kind=KIND_DIRECTORY, mode=0o755),
        TreeEntry(path=f"{framework}/Versions/A", kind=KIND_DIRECTORY, mode=0o755),
        TreeEntry(
            path=f"{framework}/Versions/A/Qt", kind=KIND_FILE, sha256="e" * 64, size=9, mode=0o755
        ),
        TreeEntry(path=f"{framework}/Versions/Current", kind=KIND_SYMLINK, link_target="A"),
        TreeEntry(path=f"{framework}/Qt", kind=KIND_SYMLINK, link_target="Versions/Current/Qt"),
    )

    assert manifest.get(f"{framework}/Qt") is not None


@pytest.mark.parametrize(
    ("link_target", "expected"),
    [
        ("../../../etc/passwd", "outside the installation"),
        ("/etc/passwd", "outside the installation"),
        ("Contents/absent", "not in the build"),
        ("Info.plist/deeper", "which is a file"),
    ],
)
def test_a_link_that_does_not_land_inside_the_build_is_refused(
    link_target: str, expected: str
) -> None:
    with pytest.raises(ManifestError, match=expected):
        _bundle(TreeEntry(path="Contents/link", kind=KIND_SYMLINK, link_target=link_target))


def test_a_loop_of_links_is_refused_rather_than_followed() -> None:
    with pytest.raises(ManifestError, match="too many links"):
        _bundle(
            TreeEntry(path="Contents/one", kind=KIND_SYMLINK, link_target="two"),
            TreeEntry(path="Contents/two", kind=KIND_SYMLINK, link_target="one"),
        )


def test_an_entry_whose_parent_the_manifest_omits_is_refused() -> None:
    with pytest.raises(ManifestError, match="which the manifest omits"):
        _bundle(
            TreeEntry(
                path="Contents/Resources/icon.icns",
                kind=KIND_FILE,
                sha256="f" * 64,
                size=4,
                mode=0o644,
            )
        )


def test_an_entry_below_something_that_is_not_a_directory_is_refused() -> None:
    with pytest.raises(ManifestError, match="not a directory"):
        _bundle(
            TreeEntry(path="Contents/Helpers", kind=KIND_SYMLINK, link_target="MacOS"),
            TreeEntry(
                path="Contents/Helpers/tool", kind=KIND_FILE, sha256="f" * 64, size=1, mode=0o755
            ),
        )


@pytest.mark.parametrize("platform", ["windows", "macos"])
def test_two_paths_one_filesystem_would_fold_together_are_refused(platform: str) -> None:
    identity = _bundle_identity(platform, "x86_64" if platform == "windows" else "arm64")
    posix = platform != "windows"
    entries = [
        TreeEntry(path="app", kind=KIND_DIRECTORY, mode=0o755 if posix else None),
        TreeEntry(
            path="app/Main.dat",
            kind=KIND_FILE,
            sha256="a" * 64,
            size=1,
            mode=0o644 if posix else None,
        ),
        TreeEntry(
            path="app/main.dat",
            kind=KIND_FILE,
            sha256="b" * 64,
            size=1,
            mode=0o644 if posix else None,
        ),
        TreeEntry(
            path="app/run",
            kind=KIND_FILE,
            sha256="c" * 64,
            size=1,
            mode=0o755 if posix else None,
        ),
    ]
    layout = TreeLayout(root="hanly-desktop", executable="app/run", mode=0o755 if posix else None)

    with pytest.raises(ManifestError, match="one name on this platform"):
        TreeManifest.from_entries(identity, layout, entries)


def test_linux_keeps_two_paths_that_differ_only_in_case() -> None:
    identity = _bundle_identity("linux", "x86_64")
    entries = [
        TreeEntry(path="app", kind=KIND_DIRECTORY, mode=0o755),
        TreeEntry(path="app/Main.dat", kind=KIND_FILE, sha256="a" * 64, size=1, mode=0o644),
        TreeEntry(path="app/main.dat", kind=KIND_FILE, sha256="b" * 64, size=1, mode=0o644),
        TreeEntry(path="app/run", kind=KIND_FILE, sha256="c" * 64, size=1, mode=0o755),
    ]
    layout = TreeLayout(root="hanly-desktop", executable="app/run", mode=0o755)

    assert len(TreeManifest.from_entries(identity, layout, entries)) == 4


@pytest.mark.parametrize(
    "path",
    ["/absolute", "Contents/../escape", "Contents//double", "Contents/./here", ".hanly-update/x"],
)
def test_a_path_that_does_not_stay_inside_an_installation_is_refused(path: str) -> None:
    with pytest.raises(ManifestError):
        require_tree_path(path, "linux")


@pytest.mark.parametrize("path", ["dir/COM1.dll", "dir/name.", "dir/name ", "C:/x", "a/b:stream"])
def test_windows_refuses_the_names_it_would_rewrite_rather_than_keep(path: str) -> None:
    with pytest.raises(ManifestError):
        require_tree_path(path, "windows")
    require_tree_path(path.replace(":", "-"), "linux")


def test_a_manifest_records_only_material_extended_attributes() -> None:
    signed = TreeEntry(
        path="Contents/Info.plist",
        kind=KIND_FILE,
        sha256="d" * 64,
        size=20,
        mode=0o644,
        xattrs={"com.apple.cs.CodeDirectory": base64.b64encode(b"seal").decode("ascii")},
    )

    assert entry_at(_bundle_signed(signed), "Contents/Info.plist").xattrs

    with pytest.raises(ManifestError, match="not product content"):
        TreeEntry(
            path="Contents/Info.plist",
            kind=KIND_FILE,
            sha256="d" * 64,
            size=20,
            xattrs={"com.apple.quarantine": "AA=="},
        )


def _bundle_signed(entry: TreeEntry) -> TreeManifest:
    entries = [item for item in _bundle_entries() if item.path != entry.path]
    return TreeManifest.from_entries(_bundle_identity(), _bundle_layout(), [*entries, entry])


@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1777])
def test_a_manifest_refuses_to_ask_for_a_privileged_permission_bit(mode: int) -> None:
    with pytest.raises(ManifestError, match="setuid, setgid, or the sticky bit"):
        TreeEntry(path="run", kind=KIND_FILE, sha256="a" * 64, size=1, mode=mode)


def test_each_kind_carries_its_own_fields_and_no_others() -> None:
    with pytest.raises(ManifestError, match="no digest and size"):
        TreeEntry(path="a", kind=KIND_FILE)
    with pytest.raises(ManifestError, match="carries file content"):
        TreeEntry(path="a", kind=KIND_DIRECTORY, sha256="a" * 64, size=1)
    with pytest.raises(ManifestError, match="link with no target"):
        TreeEntry(path="a", kind=KIND_SYMLINK)
    with pytest.raises(ManifestError, match="link with permission bits"):
        TreeEntry(path="a", kind=KIND_SYMLINK, link_target="b", mode=0o777)


def test_the_legacy_control_file_is_a_windows_entry_and_nothing_else() -> None:
    identity = _bundle_identity("windows", "x86_64")
    layout = TreeLayout(root="hanly-desktop", executable="hanly-desktop.exe")
    entries = [
        TreeEntry(path="hanly-desktop.exe", kind=KIND_FILE, sha256="a" * 64, size=1),
        TreeEntry(path=INSTALLED_MANIFEST_NAME, kind=KIND_FILE, sha256="b" * 64, size=1),
    ]

    assert INSTALLED_MANIFEST_NAME in TreeManifest.from_entries(identity, layout, entries)

    with pytest.raises(ManifestError, match="not a file this build publishes"):
        TreeManifest.from_entries(
            _bundle_identity(),
            _bundle_layout(),
            [
                *_bundle_entries(),
                TreeEntry(path=INSTALLED_MANIFEST_NAME, kind=KIND_FILE, sha256="b" * 64, size=1),
            ],
        )


def test_a_manifest_must_describe_the_executable_its_layout_names() -> None:
    entries = [item for item in _bundle_entries() if item.path != "Contents/MacOS/hanly-desktop"]

    with pytest.raises(ManifestError, match="no executable at"):
        TreeManifest.from_entries(_bundle_identity(), _bundle_layout(), entries)


def test_only_a_changed_file_needs_its_bytes_carried() -> None:
    base = _bundle()
    retimed = TreeEntry(
        path="Contents/Info.plist", kind=KIND_FILE, sha256="d" * 64, size=20, mode=0o600
    )
    rewritten = TreeEntry(
        path="Contents/MacOS/hanly-desktop",
        kind=KIND_FILE,
        sha256="9" * 64,
        size=130,
        mode=0o755,
    )
    target = TreeManifest.from_entries(
        _bundle_identity(),
        _bundle_layout(),
        [
            item
            for item in _bundle_entries()
            if item.path not in (retimed.path, rewritten.path)
        ]
        + [retimed, rewritten],
    )

    difference = tree_difference(base, target)

    assert difference.changed_paths == (retimed.path, rewritten.path)
    assert difference.payload_paths == (rewritten.path,)
    assert difference.deleted_paths == ()


def test_a_dropped_file_is_reported_as_deleted_and_carries_nothing() -> None:
    base = _bundle(
        TreeEntry(path="Contents/old.dat", kind=KIND_FILE, sha256="7" * 64, size=3, mode=0o644)
    )

    difference = tree_difference(base, _bundle())

    assert difference.deleted_paths == ("Contents/old.dat",)
    assert difference.payload_paths == ()


def test_a_real_tree_reads_back_as_the_manifest_that_describes_it(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", MACOS)

    inventory = read_tree(root, "macos")
    manifest = manifest_for(root, MACOS)

    assert inventory.unsupported == ()
    assert compare_tree(inventory, manifest).matches
    assert entry_at(manifest, "Contents/Frameworks/Qt.framework/Qt").link_target == (
        "Versions/Current/Qt"
    )
    assert entry_at(manifest, "Contents/MacOS/hanly-desktop").mode == 0o755


@requires_material_xattrs
def test_a_real_tree_reads_back_the_signature_material_it_carries(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", MACOS)
    sign_entry(root / "Contents" / "Info.plist")

    manifest = manifest_for(root, MACOS)

    assert read_tree(root, "macos").unsupported == ()
    assert entry_at(manifest, "Contents/Info.plist").xattrs


def test_the_updater_s_own_working_directory_is_never_part_of_a_tree(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", LINUX)
    (root / ".hanly-update" / "t1" / "payload").mkdir(parents=True)
    (root / ".hanly-update" / "t1" / "payload" / "0001").write_bytes(b"staged")

    assert not any(path.startswith(".hanly-update") for path in read_tree(root, "linux").entries)


def test_a_tree_carrying_something_a_manifest_cannot_describe_says_so(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", LINUX)
    os.mkfifo(root / "pipe")

    inventory = read_tree(root, "linux")

    assert inventory.unsupported == ("pipe",)
    with pytest.raises(InventoryError, match="cannot describe"):
        inventory.manifest(LINUX.identity("0.5.3", "build-one"), LINUX.layout)


def test_comparing_a_tree_separates_what_changed_from_what_was_added(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", LINUX)
    manifest = manifest_for(root, LINUX)
    (root / "hanly-desktop").write_bytes(b"a different program")
    (root / "user-notes.txt").write_bytes(b"mine")
    (root / "_internal" / "libpython.so.1.0").unlink()

    comparison = compare_tree(read_tree(root, "linux"), manifest)

    assert comparison.differing == ("hanly-desktop",)
    assert comparison.extra == ("user-notes.txt",)
    assert comparison.missing == ("_internal/libpython.so.1.0",)
    assert not comparison.matches


@pytest.mark.parametrize("product", [WINDOWS, MACOS, LINUX], ids=lambda item: item.platform)
def test_the_producer_and_a_client_read_one_build_as_one_identity(
    tmp_path: Path, product: Product
) -> None:
    package_root = tmp_path / "package"
    stamp = write_build_stamp(
        package_root,
        platform_name=product.platform,
        architecture=product.architecture,
        version="0.5.3",
        source_commit=SOURCE_COMMIT,
    )
    root = write_tree(tmp_path / "build", product)

    published = generate_tree_manifest(root, stamp, product.layout)
    installed = read_tree(root, product.platform).manifest(stamp.identity, product.layout)

    assert read_build_stamp_file(package_root) == stamp
    assert published.identity.to_dict() == stamp.identity.to_dict()
    assert installed.digest() == published.digest()
    assert compare_tree(read_tree(root, product.platform), published).matches


def test_two_freezes_of_one_version_are_two_distinguishable_builds(tmp_path: Path) -> None:
    first = write_build_stamp(
        tmp_path / "one",
        platform_name="linux",
        architecture="x86_64",
        version="0.5.3",
        source_commit=SOURCE_COMMIT,
    )
    second = write_build_stamp(
        tmp_path / "two",
        platform_name="linux",
        architecture="x86_64",
        version="0.5.3",
        source_commit=SOURCE_COMMIT,
    )

    assert first.build_id != second.build_id


def test_a_build_the_release_matrix_does_not_cover_has_no_stamp(tmp_path: Path) -> None:
    with pytest.raises(BuildIdentityError):
        write_build_stamp(
            tmp_path / "package",
            platform_name="linux",
            architecture="riscv64",
            version="0.5.3",
            source_commit=SOURCE_COMMIT,
        )


def test_a_delta_payload_carries_changed_bytes_and_nothing_a_manifest_already_says(
    tmp_path: Path,
) -> None:
    base_root = write_tree(tmp_path / "base", MACOS)
    base = manifest_for(base_root, MACOS, version="0.5.2", build_id="build-zero")
    target_root = write_tree(
        tmp_path / "target",
        MACOS,
        changes={
            "Contents/Info.plist": b"<plist>new</plist>",
            "Contents/Resources": None,
            "Contents/Resources/icon.icns": b"icon bytes",
        },
    )
    (target_root / "Contents" / "MacOS" / "hanly-desktop").chmod(0o700)
    target = manifest_for(target_root, MACOS)
    payload = tree_delta_path(tmp_path / "out", base, target)

    difference = assemble_tree_delta(target_root, target, base, payload)

    with zipfile.ZipFile(payload) as archive:
        members = sorted(archive.namelist())
    assert members == [
        "Contents/Info.plist",
        "Contents/Resources/icon.icns",
    ]
    assert "Contents/MacOS/hanly-desktop" in difference.changed_paths
    assert "Contents/MacOS/hanly-desktop" not in difference.payload_paths
    assert payload.name == "hanly-desktop-macos-arm64-from-0.5.2-to-0.5.3.delta.zip"


def test_a_windows_build_an_in_place_update_could_not_install_fails_the_producer(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "package"
    stamp = write_build_stamp(
        package_root,
        platform_name="windows",
        architecture="x86_64",
        version="0.5.3",
        source_commit=SOURCE_COMMIT,
    )
    root = write_tree(tmp_path / "build", WINDOWS)
    (root / "_internal" / "plugins").mkdir()

    with pytest.raises(ArtifactError, match="empty directories"):
        generate_tree_manifest(root, stamp, WINDOWS.layout)
