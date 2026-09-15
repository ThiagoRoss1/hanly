"""The cross-platform update package, read as a client actually reads one.

A HUP arrives over the network before anything about it is known, so these
cases are mostly about refusal: a package that is the wrong shape, describes a
platform it does not carry, or claims a manifest it did not publish must fail
at the boundary rather than reach a planner.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from hanly_app.app_hup import (
    DELTA_FORMAT,
    HUP_VERSION,
    MAX_MEMBERS,
    DeltaDescriptor,
    HupError,
    HupIndex,
    PlatformEntry,
    ReleaseIdentity,
    delta_payload_name,
    manifest_member_name,
    package_asset_name,
    read_package,
    write_package,
)
from hanly_app.app_manifest import BuildIdentity, TreeManifest

from tests.hanly_fixtures.update_tree import (
    LINUX,
    MACOS,
    SOURCE_COMMIT,
    WINDOWS,
    Product,
    asset_for,
    delta_descriptor,
    manifest_for,
    manifest_member,
    platform_entry,
    write_hup,
    write_tree,
)


def _release(tmp_path: Path, *products: Product) -> tuple[Path, dict[str, TreeManifest]]:
    """Build one release's manifests and full products from real trees."""

    manifests: dict[str, TreeManifest] = {}
    entries: list[PlatformEntry] = []
    for product in products:
        root = write_tree(tmp_path / f"build-{product.platform}", product)
        manifest = manifest_for(root, product)
        archive = tmp_path / f"hanly-desktop-{product.platform}.zip"
        archive.write_bytes(b"full product for " + product.platform.encode())
        manifests[product.platform] = manifest
        entries.append(platform_entry(manifest, asset_for(archive, "zip")))
    package = write_hup(
        tmp_path / package_asset_name("0.5.3"), tuple(entries), tuple(manifests.values())
    )
    return package, manifests


def test_package_round_trips_every_published_platform(tmp_path: Path) -> None:
    package, manifests = _release(tmp_path, WINDOWS, MACOS, LINUX)

    read = read_package(package)

    assert read.version == "0.5.3"
    assert sorted(entry.tuple_name for entry in read.index) == [
        "linux-x86_64",
        "macos-arm64",
        "windows-x86_64",
    ]
    for platform, manifest in manifests.items():
        entry = read.index.entry_for(platform, manifest.identity.architecture)
        assert entry is not None
        assert read.manifest_for(entry).digest() == manifest.digest()


def test_a_tuple_the_release_never_built_is_absent_rather_than_approximated(
    tmp_path: Path,
) -> None:
    package, _manifests = _release(tmp_path, WINDOWS, MACOS)

    read = read_package(package)

    assert read.index.entry_for("macos", "x86_64") is None
    assert read.index.entry_for("linux", "x86_64") is None


def test_package_names_only_the_assets_its_entries_refer_to(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", MACOS)
    previous = write_tree(tmp_path / "previous", MACOS, changes={"Contents/Info.plist": b"old"})
    manifest = manifest_for(root, MACOS)
    base = manifest_for(previous, MACOS, version="0.5.2", build_id="build-zero")
    archive = tmp_path / "hanly-desktop-macos.dmg"
    archive.write_bytes(b"disk image")
    payload = tmp_path / delta_payload_name("macos", "arm64", "0.5.2", "0.5.3")
    payload.write_bytes(b"delta payload")

    entry = platform_entry(
        manifest,
        asset_for(archive, "dmg"),
        delta=delta_descriptor(base, payload, ("Contents/Info.plist",)),
    )
    package = write_hup(tmp_path / package_asset_name("0.5.3"), (entry,), (manifest,))

    assert read_package(package).asset_names() == tuple(sorted((archive.name, payload.name)))


def test_index_refuses_a_platform_whose_version_is_not_the_release(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", LINUX)
    manifest = manifest_for(root, LINUX, version="0.5.4")
    archive = tmp_path / "hanly-desktop-linux.tar.gz"
    archive.write_bytes(b"tarball")

    with pytest.raises(HupError, match="version the release does not"):
        HupIndex(
            release=ReleaseIdentity(
                tag="v0.5.3", version="0.5.3", source_commit=SOURCE_COMMIT
            ),
            platforms=(platform_entry(manifest, asset_for(archive, "tar.gz")),),
        )


def test_index_refuses_one_platform_tuple_described_twice(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", LINUX)
    manifest = manifest_for(root, LINUX)
    archive = tmp_path / "hanly-desktop-linux.tar.gz"
    archive.write_bytes(b"tarball")
    entry = platform_entry(manifest, asset_for(archive, "tar.gz"))

    with pytest.raises(HupError, match="twice"):
        HupIndex(
            release=ReleaseIdentity(
                tag="v0.5.3", version="0.5.3", source_commit=SOURCE_COMMIT
            ),
            platforms=(entry, entry),
        )


def test_delta_may_not_start_from_a_build_of_another_machine(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", LINUX)
    previous = write_tree(tmp_path / "previous", LINUX, changes={"hanly-desktop": b"old"})
    manifest = manifest_for(root, LINUX)
    base = manifest_for(previous, LINUX, version="0.5.2", build_id="build-zero")
    foreign = BuildIdentity(
        product="hanly-desktop",
        platform="linux",
        architecture="arm64",
        version="0.5.2",
        build_id="build-zero",
    )
    archive = tmp_path / "hanly-desktop-linux.tar.gz"
    archive.write_bytes(b"tarball")
    payload = tmp_path / delta_payload_name("linux", "x86_64", "0.5.2", "0.5.3")
    payload.write_bytes(b"delta")
    delta = DeltaDescriptor(
        base_identity=foreign,
        base_manifest_sha256=base.digest(),
        payload=asset_for(payload, DELTA_FORMAT),
        changed_paths=("hanly-desktop",),
    )

    with pytest.raises(HupError, match="different product or machine"):
        platform_entry(manifest, asset_for(archive, "tar.gz"), delta=delta)


def test_reading_refuses_a_manifest_that_is_not_the_one_the_index_describes(
    tmp_path: Path,
) -> None:
    package, manifests = _release(tmp_path, WINDOWS)
    member = manifest_member(manifests["windows"]).member
    _rewrite_member(package, member, manifests["windows"].to_json() + " ")

    with pytest.raises(HupError, match="not the size the index declares"):
        read_package(package)


def test_reading_refuses_an_index_naming_a_manifest_the_package_omits(
    tmp_path: Path,
) -> None:
    package, manifests = _release(tmp_path, WINDOWS)
    _drop_member(package, manifest_member(manifests["windows"]).member)

    with pytest.raises(HupError, match="missing"):
        read_package(package)


def test_reading_refuses_a_member_the_index_never_named(tmp_path: Path) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr(manifest_member_name("linux", "x86_64"), "{}")

    with pytest.raises(HupError, match="its index omits"):
        read_package(package)


def test_reading_refuses_a_member_at_a_path_no_package_carries(tmp_path: Path) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("../escape.json", "{}")

    with pytest.raises(HupError, match="not a member"):
        read_package(package)


def test_reading_refuses_more_members_than_a_package_may_carry(tmp_path: Path) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    with zipfile.ZipFile(package, "a") as archive:
        for index in range(MAX_MEMBERS + 1):
            archive.writestr(manifest_member_name("linux", f"x{index}"), "{}")

    with pytest.raises(HupError, match="more members"):
        read_package(package)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ('{"hup_version": 99}', "declares version"),
        ('{"hup_version": 1, "product": "something-else"}', "not the product"),
        ('{"hup_version": 1, "platforms": []}', "describes no platforms"),
    ],
)
def test_reading_refuses_an_index_this_build_does_not_understand(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    payload = json.loads(_member_text(package, "index.json"))
    payload.update(json.loads(mutation))
    _rewrite_member(package, "index.json", json.dumps(payload))

    with pytest.raises(HupError, match=expected):
        read_package(package)


def test_reading_refuses_an_index_naming_one_key_twice(tmp_path: Path) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    text = _member_text(package, "index.json")
    _rewrite_member(package, "index.json", text[:-1] + ',"product":"hanly-desktop"}')

    with pytest.raises(HupError, match="twice"):
        read_package(package)


def test_reading_refuses_an_index_carrying_a_number_that_is_not_one(tmp_path: Path) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    text = _member_text(package, "index.json")
    _rewrite_member(package, "index.json", text[:-1] + ',"slack":NaN}')

    with pytest.raises(HupError, match="not a number"):
        read_package(package)


def test_reading_refuses_a_package_larger_than_this_build_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, _manifests = _release(tmp_path, WINDOWS)
    monkeypatch.setattr("hanly_app.app_hup.MAX_PACKAGE_BYTES", 16)

    with pytest.raises(HupError, match="larger than this build reads"):
        read_package(package)


def test_writing_refuses_manifests_the_index_does_not_describe(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "build", WINDOWS)
    manifest = manifest_for(root, WINDOWS)
    archive = tmp_path / "hanly-desktop-windows.zip"
    archive.write_bytes(b"zip")
    index = HupIndex(
        release=ReleaseIdentity(tag="v0.5.3", version="0.5.3", source_commit=SOURCE_COMMIT),
        platforms=(platform_entry(manifest, asset_for(archive, "zip")),),
    )

    with pytest.raises(HupError, match="different platforms"):
        write_package(tmp_path / "out.hup", index, {})


def test_release_identity_binds_its_tag_to_its_version() -> None:
    with pytest.raises(HupError, match="does not name version"):
        ReleaseIdentity(tag="v0.5.2", version="0.5.3", source_commit=SOURCE_COMMIT)
    with pytest.raises(HupError, match="full commit"):
        ReleaseIdentity(tag="v0.5.3", version="0.5.3", source_commit="abc")


def test_asset_names_are_derived_the_one_way_both_sides_derive_them() -> None:
    assert package_asset_name("1.2.3") == "Hanly-v1.2.3.hup"
    assert manifest_member_name("macos", "arm64") == "manifests/macos-arm64.json"
    assert delta_payload_name("linux", "x86_64", "1.0.0", "1.0.1") == (
        "hanly-desktop-linux-x86_64-from-1.0.0-to-1.0.1.delta.zip"
    )
    assert HUP_VERSION == 1


def _member_text(package: Path, member: str) -> str:
    with zipfile.ZipFile(package) as archive:
        return archive.read(member).decode("utf-8")


def _rewrite_member(package: Path, member: str, text: str) -> None:
    _rebuild(package, {member: text.encode("utf-8")})


def _drop_member(package: Path, member: str) -> None:
    _rebuild(package, {member: None})


def _rebuild(package: Path, changes: dict[str, bytes | None]) -> None:
    with zipfile.ZipFile(package) as archive:
        existing = {info.filename: archive.read(info) for info in archive.infolist()}
    existing.update({name: value for name, value in changes.items() if value is not None})
    for name, value in changes.items():
        if value is None:
            existing.pop(name, None)
    package.unlink()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in existing.items():
            archive.writestr(name, value)
