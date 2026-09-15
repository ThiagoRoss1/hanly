"""Preparing one update, on the one path all three platforms share.

These cases stop where a platform's own staging begins. What they hold is the
part that is the same everywhere: the release is pinned, the metadata package
is proved, this machine's entry is selected, the installation is read, and what
it is gets established rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hanly_app.app_build_identity import ReceiptStore, receipt_for
from hanly_app.app_update_install import (
    DifferentialUpdateError,
    TreeUpdateInstaller,
    UnsupportedPlatform,
    UpdateBlocked,
    UpdateCancelled,
    WindowsFileStaging,
    snapshot_release,
)
from hanly_app.app_update_journal import acknowledgement_matches
from hanly_app.app_update_plan import (
    FROM_DELTA,
    FROM_FULL,
    OWNERSHIP_BOOTSTRAP,
    OWNERSHIP_RECEIPT,
    OwnershipUnknown,
)

from tests.hanly_fixtures.update_release import PublishedRelease, ReleaseChannel
from tests.hanly_fixtures.update_tree import LINUX, SOURCE_COMMIT, WINDOWS, Product

TARGET_CHANGES = {
    "hanly-desktop.exe": b"windows program, revised",
    "_internal/added.dat": b"a file the new build adds",
}
LINUX_CHANGES = {
    "hanly-desktop": b"linux program, revised",
    "_internal/added.so": b"a library the new build adds",
}


def _published(
    tmp_path: Path, product: Product = WINDOWS, *, changes: dict[str, bytes] | None = None
) -> tuple[PublishedRelease, PublishedRelease, ReleaseChannel]:
    """Two consecutive releases of one product, and the channel serving them."""

    base = PublishedRelease(
        tmp_path / "release-0.5.2", product, version="0.5.2", build_id="build-zero"
    )
    target = PublishedRelease(
        tmp_path / "release-0.5.3",
        product,
        version="0.5.3",
        build_id="build-one",
        changes=changes if changes is not None else TARGET_CHANGES,
        previous=base,
    )
    return base, target, ReleaseChannel(base, target)


def _installer(
    tmp_path: Path,
    base: PublishedRelease,
    channel: ReleaseChannel,
    *,
    install: Path,
    store: ReceiptStore,
    tagged: bool = True,
) -> TreeUpdateInstaller:
    strategy = WindowsFileStaging(
        install_root=install,
        executable="hanly-desktop.exe",
        recovery_root=tmp_path / "recovery",
        store=store,
        source_commit=SOURCE_COMMIT,
    )
    return TreeUpdateInstaller(
        channel,
        channel.release_source,
        stamp=base.stamp,
        install_root=install,
        store=store,
        strategy=strategy,
        tagged_release_source=channel.tagged_release_source if tagged else None,
    )


def _with_receipt(store: ReceiptStore, install: Path, base: PublishedRelease) -> None:
    store.store_manifest(base.manifest)
    store.write_receipt(
        receipt_for(
            install,
            base.manifest,
            release_tag=base.tag,
            source_commit=SOURCE_COMMIT,
            now=0.0,
        )
    )


def test_an_installation_this_updater_installed_updates_from_its_delta(
    tmp_path: Path,
) -> None:
    base, target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)

    prepared = _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.3")

    assert prepared.plan.ownership == OWNERSHIP_RECEIPT
    assert prepared.plan.source == FROM_DELTA
    assert not prepared.requires_confirmation
    assert prepared.plan.required_paths == ("_internal/added.dat", "hanly-desktop.exe")
    assert "_internal/base_library.zip" in prepared.plan.reusable_paths
    assert not any(item.endswith(target.full.name) for item in channel.requested)


def test_a_fresh_installation_with_no_receipt_bootstraps_from_its_own_tag(
    tmp_path: Path,
) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")

    prepared = _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.3")

    assert prepared.plan.ownership == OWNERSHIP_BOOTSTRAP
    assert prepared.plan.source == FROM_DELTA
    assert store.read_manifest(base.manifest.digest()) is not None


def test_an_installation_that_is_not_the_build_it_claims_is_not_adopted(
    tmp_path: Path,
) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    (install / "_internal" / "base_library.zip").write_bytes(b"edited by somebody")
    store = ReceiptStore(tmp_path / "state")

    with pytest.raises(OwnershipUnknown, match="differs from the published"):
        _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.3")


def test_an_installation_whose_own_release_published_no_package_is_not_adopted(
    tmp_path: Path,
) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")

    with pytest.raises(OwnershipUnknown, match="cannot confirm"):
        _installer(
            tmp_path, base, channel, install=install, store=store, tagged=False
        ).prepare("0.5.3")


def test_extra_files_a_person_added_do_not_stop_a_bootstrap(tmp_path: Path) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    (install / "notes.txt").write_bytes(b"mine")
    store = ReceiptStore(tmp_path / "state")

    prepared = _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.3")

    assert prepared.plan.ownership == OWNERSHIP_BOOTSTRAP
    assert prepared.plan.preserved == ("notes.txt",)


def test_a_damaged_file_the_delta_does_not_carry_sends_the_update_to_the_product(
    tmp_path: Path,
) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    (install / "_internal" / "base_library.zip").write_bytes(b"corrupted since installation")

    prepared = _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.3")

    assert prepared.plan.source == FROM_FULL
    assert prepared.requires_confirmation
    assert "need repairing" in prepared.plan.fallback_reason


def test_a_file_this_installation_does_not_own_is_reported_not_overwritten(
    tmp_path: Path,
) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    (install / "_internal" / "added.dat").write_bytes(b"something else entirely")

    installer = _installer(tmp_path, base, channel, install=install, store=store)
    prepared = installer.prepare("0.5.3")

    assert prepared.plan.collisions == ("_internal/added.dat",)
    assert prepared.is_blocked
    with pytest.raises(UpdateBlocked, match="does not own"):
        installer.stage(prepared)


def test_a_release_that_publishes_nothing_for_this_machine_says_so(
    tmp_path: Path,
) -> None:
    base, _target, channel = _published(tmp_path, LINUX, changes=LINUX_CHANGES)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    windows = PublishedRelease(
        tmp_path / "other", WINDOWS, version="0.5.2", build_id="build-zero"
    )
    installer = TreeUpdateInstaller(
        channel,
        channel.release_source,
        stamp=windows.stamp,
        install_root=install,
        store=store,
        strategy=WindowsFileStaging(
            install_root=install,
            executable="hanly-desktop.exe",
            recovery_root=tmp_path / "recovery",
            store=store,
            source_commit=SOURCE_COMMIT,
        ),
    )

    with pytest.raises(UnsupportedPlatform, match="publishes no build for windows"):
        installer.prepare("0.5.3")


def test_a_metadata_package_the_release_did_not_publish_is_refused(tmp_path: Path) -> None:
    base, target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    target.corrupt(target.package.name)

    with pytest.raises(DifferentialUpdateError, match="not the file the release published"):
        _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.3")


def test_a_release_that_moved_on_since_the_check_is_not_installed(tmp_path: Path) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)

    with pytest.raises(DifferentialUpdateError, match="no longer offers Hanly"):
        _installer(tmp_path, base, channel, install=install, store=store).prepare("0.5.4")


def test_a_pinned_release_is_read_once_and_never_re_resolved() -> None:
    payload = {
        "tag_name": "v0.5.3",
        "id": 77,
        "assets": [
            {
                "name": "hanly-desktop-windows.zip",
                "id": 3,
                "size": 120,
                "browser_download_url": "https://example.invalid/zip",
                "digest": "sha256:" + "a" * 64,
            },
            {"name": "broken", "size": 1},
        ],
    }

    snapshot = snapshot_release(payload, "0.5.3")

    assert snapshot.release_id == 77
    assert set(snapshot.assets) == {"hanly-desktop-windows.zip"}
    record = snapshot.require("hanly-desktop-windows.zip")
    assert record.size == 120
    assert record.digest == "a" * 64


def test_cancelling_while_the_installation_is_read_changes_nothing(tmp_path: Path) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)

    with pytest.raises(UpdateCancelled):
        _installer(tmp_path, base, channel, install=install, store=store).prepare(
            "0.5.3", should_cancel=lambda: True
        )

    assert not (install / ".hanly-update").exists()


def test_an_update_the_volume_cannot_hold_stops_before_it_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    installer = _installer(tmp_path, base, channel, install=install, store=store)
    prepared = installer.prepare("0.5.3")
    monkeypatch.setattr(
        "hanly_app.app_update_install.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 1})(),
    )

    with pytest.raises(DifferentialUpdateError, match="free on the drive"):
        installer.stage(prepared)


def test_staging_writes_only_the_changed_files_and_the_answer_it_will_accept(
    tmp_path: Path,
) -> None:
    base, target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    installer = _installer(tmp_path, base, channel, install=install, store=store)

    staged = installer.stage(installer.prepare("0.5.3"))

    journal = staged.transaction.journal
    operations = staged.transaction.transaction.operations
    assert sorted(item.path for item in operations) == [
        "_internal/added.dat",
        "hanly-desktop.exe",
    ]
    expected = staged.transaction.challenge.expected()
    assert journal.expected_path.read_text(encoding="utf-8") == expected
    assert staged.transaction.transaction.manifest_sha256 == target.manifest.digest()
    assert sorted(path.name for path in journal.payload_root.iterdir()) == ["0001", "0002"]


def test_the_receipt_the_new_build_will_earn_is_staged_and_not_adopted(
    tmp_path: Path,
) -> None:
    base, target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    installer = _installer(tmp_path, base, channel, install=install, store=store)

    installer.stage(installer.prepare("0.5.3"))

    current = store.read_receipt()
    assert current is not None and current.identity.version == "0.5.2"
    assert store.pending_path.is_file()
    assert store.previous_path.is_file()

    store.restore_previous()
    restored = store.read_receipt()
    assert restored is not None and restored.identity.version == "0.5.2"
    assert not store.pending_path.exists()


def test_the_staged_receipt_is_adopted_only_by_the_build_that_was_installed(
    tmp_path: Path,
) -> None:
    base, target, channel = _published(tmp_path)
    install = base.install(tmp_path / "install")
    store = ReceiptStore(tmp_path / "state")
    _with_receipt(store, install, base)
    installer = _installer(tmp_path, base, channel, install=install, store=store)
    staged = installer.stage(installer.prepare("0.5.3"))

    assert store.promote_pending(base.stamp) is None
    adopted = store.promote_pending(target.stamp)

    assert adopted is not None and adopted.identity.version == "0.5.3"
    assert acknowledgement_matches(
        staged.transaction.challenge.expected(), staged.transaction.challenge
    )
    assert not acknowledgement_matches("0.5.3\n", staged.transaction.challenge)
