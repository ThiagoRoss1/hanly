"""The identity a build carries, and what an update leaves behind about it.

Schema 2 cannot hash a build to name it: on macOS the manifest is produced
after signing and lives outside the bundle, so the name has to go in before the
freeze. These cases hold that stamp, and the per-installation receipt that ties
it to a manifest, to the contract the updater reads them under.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from hanly_app.app_build_identity import (
    BUILD_STAMP_NAME,
    BuildIdentityError,
    BuildStamp,
    InstalledReceipt,
    ReceiptStore,
    install_key,
    read_build_stamp,
    receipt_for,
    receipt_store,
    updates_root,
)

from tests.hanly_fixtures.update_tree import (
    LINUX,
    MACOS,
    SOURCE_COMMIT,
    manifest_for,
    write_tree,
)


def _stamp(**overrides: str) -> BuildStamp:
    values = {
        "product": "hanly-desktop",
        "platform": "macos",
        "architecture": "arm64",
        "version": "0.5.3",
        "build_id": "4e6a2b18-0f2c-4d41-9d0a-7b5c8e1f2a33",
        "source_commit": SOURCE_COMMIT,
    }
    values.update(overrides)
    return BuildStamp(**values)


def test_a_stamp_round_trips_and_names_the_identity_documents_carry() -> None:
    stamp = _stamp()

    restored = BuildStamp.from_json(stamp.to_json())

    assert restored == stamp
    assert restored.identity.build_id == stamp.build_id
    assert restored.release_tag == "v0.5.3"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("platform", "solaris"),
        ("architecture", "ppc64"),
        ("source_commit", "abc123"),
    ],
)
def test_a_stamp_this_build_could_not_have_produced_is_refused(field: str, value: str) -> None:
    with pytest.raises(BuildIdentityError):
        _stamp(**{field: value})


def test_a_package_that_was_never_frozen_carries_no_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asked of a bare package rather than this checkout's: a local build
    writes the stamp into the source tree before freezing, so what the
    checkout holds depends on whether anyone has built here."""

    package = tmp_path / "unfrozen_product"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert read_build_stamp("unfrozen_product") is None


def test_the_stamp_is_generated_by_a_build_and_never_checked_in() -> None:
    """It names one build. A stamp in the repository would name whichever
    build last happened to be made on somebody's machine."""

    ignored = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert f"assets/{BUILD_STAMP_NAME}" in ignored


def test_a_frozen_build_reads_its_stamp_back_out_of_its_own_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "frozen_product"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / BUILD_STAMP_NAME).write_text(_stamp().to_json(), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert read_build_stamp("frozen_product") == _stamp()


def test_an_unreadable_stamp_answers_none_rather_than_a_guess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "damaged_product"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / BUILD_STAMP_NAME).write_text("{not json", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert read_build_stamp("damaged_product") is None


def test_two_installations_get_two_directories_and_one_gets_one(tmp_path: Path) -> None:
    first = tmp_path / "one" / "Hanly.app"
    second = tmp_path / "two" / "Hanly.app"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    assert install_key(first) == install_key(first)
    assert install_key(first) != install_key(second)
    assert receipt_store(first).directory.parent == updates_root()


@pytest.mark.skipif(
    not sys.platform.startswith(("win32", "darwin")),
    reason="only the case-folding platforms reach one installation by two spellings",
)
def test_one_installation_reached_by_two_spellings_is_one_installation(tmp_path: Path) -> None:
    root = tmp_path / "Hanly.app"
    root.mkdir()

    assert install_key(root) == install_key(Path(str(root).upper()))


def test_a_receipt_records_the_build_and_the_manifest_it_was_verified_against(
    tmp_path: Path,
) -> None:
    root = write_tree(tmp_path / "install", MACOS)
    manifest = manifest_for(root, MACOS)
    store = ReceiptStore(tmp_path / "state")

    receipt = receipt_for(
        root,
        manifest,
        release_tag="v0.5.3",
        source_commit=SOURCE_COMMIT,
        preserved_paths=("Contents/user.log",),
        now=1_700_000_000.0,
    )
    store.write_receipt(receipt)
    store.store_manifest(manifest)

    read = store.read_receipt()
    assert read == receipt
    assert read.manifest_sha256 == manifest.digest()
    assert read.preserved_paths == ("Contents/user.log",)
    stored = store.read_manifest(manifest.digest())
    assert stored is not None and stored.digest() == manifest.digest()


def test_a_stored_manifest_that_is_not_what_it_is_filed_under_is_refused(
    tmp_path: Path,
) -> None:
    root = write_tree(tmp_path / "install", LINUX)
    manifest = manifest_for(root, LINUX)
    store = ReceiptStore(tmp_path / "state")
    store.store_manifest(manifest)
    path = store.manifest_path(manifest.digest())
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    assert store.read_manifest(manifest.digest()) is None


def test_an_unusable_receipt_reads_as_no_receipt_rather_than_as_ownership(
    tmp_path: Path,
) -> None:
    store = ReceiptStore(tmp_path / "state")
    store.directory.mkdir(parents=True)
    store.receipt_path.write_text(json.dumps({"identity": {}}), encoding="utf-8")

    assert store.read_receipt() is None


def test_a_receipt_only_describes_the_build_it_actually_names(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "install", MACOS)
    manifest = manifest_for(root, MACOS, build_id="4e6a2b18-0f2c-4d41-9d0a-7b5c8e1f2a33")
    receipt = receipt_for(
        root, manifest, release_tag="v0.5.3", source_commit=SOURCE_COMMIT, now=0.0
    )

    assert receipt.describes(_stamp())
    assert not receipt.describes(_stamp(build_id="another-build"))


def test_clearing_a_receipt_leaves_the_manifests_it_referred_to(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "install", LINUX)
    manifest = manifest_for(root, LINUX)
    store = ReceiptStore(tmp_path / "state")
    store.write_receipt(
        receipt_for(root, manifest, release_tag="v0.5.3", source_commit=SOURCE_COMMIT, now=0.0)
    )
    store.store_manifest(manifest)

    store.clear_receipt()

    assert store.read_receipt() is None
    assert store.read_manifest(manifest.digest()) is not None


def test_a_receipt_read_from_a_foreign_document_is_not_accepted() -> None:
    with pytest.raises(BuildIdentityError):
        InstalledReceipt.from_payload(["not", "an", "object"])
