"""What a release produces, read back by the client that will install it.

Two builds are frozen, their products are made, one update package indexes
them, and a client then plans an update from it. No release is uploaded and no
network is reached: producer and consumer agree here or they do not agree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app.app_hup import HupError, package_asset_name, read_package
from hanly_app.app_inventory import read_tree
from hanly_app.app_manifest import TreeLayout, TreeManifest
from hanly_app.app_update_plan import FROM_DELTA, OWNERSHIP_RECEIPT, plan_tree_update
from hanly_app.app_update_tree import assemble_candidate, verify_candidate

from tests.hanly_fixtures.update_tree import (
    LINUX,
    MACOS,
    SOURCE_COMMIT,
    WINDOWS,
    Product,
    info_plist,
    program_bytes,
    write_tree,
)
from tools.update_artifacts import (
    ArtifactError,
    PlatformRelease,
    assemble_update_package,
    build_platform_release,
    executable_architecture,
    load_base_package_manifest,
    write_build_stamp,
)

FULL_FORMATS = {"windows": "zip", "macos": "dmg", "linux": "tar.gz"}


def _build(
    tmp_path: Path,
    product: Product,
    *,
    version: str,
    changes: dict[str, bytes] | None = None,
) -> tuple[Path, Path]:
    """Freeze one build of one product, and the whole product beside it."""

    root = write_tree(tmp_path / f"build-{product.platform}-{version}", product, changes=changes)
    full = tmp_path / f"hanly-desktop-{product.platform}{_suffix(product.platform)}"
    full.write_bytes(f"the whole {product.platform} product for {version}".encode())
    return root, full


def _suffix(platform: str) -> str:
    return {"windows": ".zip", "macos": ".dmg", "linux": ".tar.gz"}[platform]


def _release(
    tmp_path: Path,
    product: Product,
    *,
    version: str,
    build_id: str,
    changes: dict[str, bytes] | None = None,
    base: TreeManifest | None = None,
) -> PlatformRelease:
    """Produce every schema-2 artifact one platform contributes to a release."""

    root, full = _build(tmp_path, product, version=version, changes=changes)
    stamp = write_build_stamp(
        tmp_path / f"package-{product.platform}-{version}",
        platform_name=product.platform,
        architecture=product.architecture,
        version=version,
        source_commit=SOURCE_COMMIT,
        build_id=build_id,
    )
    return build_platform_release(
        root,
        stamp,
        product.layout,
        full,
        tmp_path / "release" / version / product.platform,
        full_format=FULL_FORMATS[product.platform],
        base=base,
    )


def _changes(product: Product, version: str) -> dict[str, bytes]:
    """What a second build of one product actually differs in."""

    if product.platform == "macos":
        return {
            "Contents/Info.plist": info_plist(version),
            "Contents/MacOS/hanly-desktop": program_bytes(
                "macos", "arm64", version.encode("ascii")
            ),
        }
    name = product.executable
    return {name: program_bytes(product.platform, product.architecture, version.encode("ascii"))}


def test_a_release_indexes_every_platform_it_built_and_nothing_it_did_not(
    tmp_path: Path,
) -> None:
    releases = [
        _release(tmp_path, product, version="0.5.3", build_id=f"b-{product.platform}")
        for product in (WINDOWS, MACOS, LINUX)
    ]

    package = assemble_update_package(
        [release.directory for release in releases],
        tmp_path / package_asset_name("0.5.3"),
        source_commit=SOURCE_COMMIT,
    )

    index = read_package(package).index
    assert sorted(entry.tuple_name for entry in index) == [
        "linux-x86_64",
        "macos-arm64",
        "windows-x86_64",
    ]
    assert index.release.source_commit == SOURCE_COMMIT
    assert all(entry.delta is None for entry in index)
    assert all(entry.delta_omitted_reason for entry in index)


def test_the_second_release_offers_a_delta_a_client_can_actually_use(
    tmp_path: Path,
) -> None:
    base = _release(tmp_path, LINUX, version="0.5.2", build_id="build-zero")
    target = _release(
        tmp_path,
        LINUX,
        version="0.5.3",
        build_id="build-one",
        changes=_changes(LINUX, "0.5.3"),
        base=base.manifest,
    )
    package = assemble_update_package(
        [target.directory], tmp_path / package_asset_name("0.5.3"), source_commit=SOURCE_COMMIT
    )

    entry = read_package(package).index.entry_for("linux", "x86_64")
    assert entry is not None and entry.delta is not None
    assert entry.delta.base_identity.version == "0.5.2"
    assert entry.delta.changed_paths == ("hanly-desktop",)


def test_a_client_reconstructs_the_published_build_from_what_the_release_made(
    tmp_path: Path,
) -> None:
    """The whole point of the wave, end to end and without a network."""

    base = _release(tmp_path, LINUX, version="0.5.2", build_id="build-zero")
    target = _release(
        tmp_path,
        LINUX,
        version="0.5.3",
        build_id="build-one",
        changes=_changes(LINUX, "0.5.3"),
        base=base.manifest,
    )
    installed = write_tree(tmp_path / "install", LINUX)

    plan = plan_tree_update(
        target.manifest,
        read_tree(installed, "linux"),
        base.manifest,
        ownership=OWNERSHIP_RECEIPT,
        full=target.full,
        delta=target.delta,
    )
    assert plan.source == FROM_DELTA
    assert target.delta is not None

    candidate = assemble_candidate(
        tmp_path / "candidate",
        target.manifest,
        source_root=installed,
        reusable=plan.reusable_paths,
        payload=target.directory / target.delta.payload.name,
    )

    verify_candidate(candidate)
    assert candidate.reused_bytes > 0
    assert candidate.payload_bytes < candidate.reused_bytes + candidate.payload_bytes


def test_a_previous_package_is_read_only_when_its_release_vouches_for_it(
    tmp_path: Path,
) -> None:
    base = _release(tmp_path, LINUX, version="0.5.2", build_id="build-zero")
    package = assemble_update_package(
        [base.directory], tmp_path / package_asset_name("0.5.2"), source_commit=SOURCE_COMMIT
    )
    sums = tmp_path / "SHA256SUMS"
    digest = __import__("hashlib").sha256(package.read_bytes()).hexdigest()
    sums.write_text(f"{digest}  {package.name}\n", encoding="utf-8")

    manifest = load_base_package_manifest(
        package, sums, platform_name="linux", architecture="x86_64"
    )
    assert manifest.digest() == base.manifest.digest()

    package.write_bytes(package.read_bytes() + b"tampered")
    with pytest.raises(ArtifactError, match="not the package"):
        load_base_package_manifest(package, sums, platform_name="linux", architecture="x86_64")


def test_a_predecessor_for_another_machine_is_not_a_predecessor(tmp_path: Path) -> None:
    base = _release(tmp_path, LINUX, version="0.5.2", build_id="build-zero")
    package = assemble_update_package(
        [base.directory], tmp_path / package_asset_name("0.5.2"), source_commit=SOURCE_COMMIT
    )

    with pytest.raises(ArtifactError, match="publishes no build for linux arm64"):
        load_base_package_manifest(package, None, platform_name="linux", architecture="arm64")


def test_two_builds_that_were_never_released_together_are_not_indexed_together(
    tmp_path: Path,
) -> None:
    first = _release(tmp_path, LINUX, version="0.5.3", build_id="build-one")
    second = _release(tmp_path, WINDOWS, version="0.5.4", build_id="build-two")

    with pytest.raises(ArtifactError, match="different versions"):
        assemble_update_package(
            [first.directory, second.directory],
            tmp_path / package_asset_name("0.5.3"),
            source_commit=SOURCE_COMMIT,
        )


def test_a_platform_descriptor_that_disagrees_with_its_manifest_is_refused(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path, LINUX, version="0.5.3", build_id="build-one")
    payload = json.loads(release.descriptor_path.read_text(encoding="utf-8"))
    payload["identity"]["build_id"] = "another-build"
    release.descriptor_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactError, match="describes a build its manifest does not"):
        PlatformRelease.read(release.directory)


def test_an_advertised_asset_is_proved_against_the_file_this_run_produced(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path, LINUX, version="0.5.3", build_id="build-one")
    products = tmp_path / "products"
    products.mkdir()
    published = products / release.full.name
    published.write_bytes(b"the whole linux product for 0.5.3")

    assemble_update_package(
        [release.directory],
        tmp_path / package_asset_name("0.5.3"),
        source_commit=SOURCE_COMMIT,
        products=products,
    )

    published.write_bytes(b"a different product entirely")
    with pytest.raises(ArtifactError, match="not the file its descriptor describes"):
        assemble_update_package(
            [release.directory],
            tmp_path / "again.hup",
            source_commit=SOURCE_COMMIT,
            products=products,
        )

    published.unlink()
    with pytest.raises(ArtifactError, match="this run did not produce"):
        assemble_update_package(
            [release.directory],
            tmp_path / "again.hup",
            source_commit=SOURCE_COMMIT,
            products=products,
        )


def test_a_build_for_another_machine_than_it_claims_never_becomes_a_product(
    tmp_path: Path,
) -> None:
    root, full = _build(tmp_path, LINUX, version="0.5.3")
    (root / "hanly-desktop").write_bytes(program_bytes("linux", "arm64"))
    stamp = write_build_stamp(
        tmp_path / "package",
        platform_name="linux",
        architecture="x86_64",
        version="0.5.3",
        source_commit=SOURCE_COMMIT,
    )

    with pytest.raises(ArtifactError, match="built for arm64"):
        build_platform_release(
            root,
            stamp,
            LINUX.layout,
            full,
            tmp_path / "release",
            full_format="tar.gz",
        )


@pytest.mark.parametrize(
    ("platform", "architecture"),
    [("linux", "x86_64"), ("linux", "arm64"), ("macos", "arm64"), ("windows", "x86_64")],
)
def test_an_executable_says_which_machine_it_is_for(
    tmp_path: Path, platform: str, architecture: str
) -> None:
    program = tmp_path / "program"
    program.write_bytes(program_bytes(platform, architecture))

    assert executable_architecture(program) == architecture


def test_something_that_is_not_a_program_says_nothing(tmp_path: Path) -> None:
    program = tmp_path / "notes.txt"
    program.write_bytes(b"this is not an executable at all, it is a note")

    assert executable_architecture(program) is None


def test_a_layout_naming_no_executable_is_refused_before_anything_is_published(
    tmp_path: Path,
) -> None:
    root, full = _build(tmp_path, LINUX, version="0.5.3")
    stamp = write_build_stamp(
        tmp_path / "package",
        platform_name="linux",
        architecture="x86_64",
        version="0.5.3",
        source_commit=SOURCE_COMMIT,
    )

    with pytest.raises(ArtifactError, match="could not read what machine"):
        build_platform_release(
            root,
            stamp,
            TreeLayout(root="hanly-desktop", executable="absent", mode=0o755),
            full,
            tmp_path / "release",
            full_format="tar.gz",
        )


def test_an_index_this_build_could_not_read_back_is_never_written(tmp_path: Path) -> None:
    release = _release(tmp_path, LINUX, version="0.5.3", build_id="build-one")
    release.manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises((ArtifactError, HupError)):
        assemble_update_package(
            [release.directory],
            tmp_path / package_asset_name("0.5.3"),
            source_commit=SOURCE_COMMIT,
        )
