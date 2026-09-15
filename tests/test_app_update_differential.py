"""Deciding, staging, and settling one in-place Windows update.

Everything here stops at the point the native helper takes over: what an update
would change, what it downloads to change it, and what a later launch makes of
whatever the last run left behind. The apply itself is native, and
``tests/native/windows`` runs the real one.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hanly_app.app_inventory import read_installation, read_installed_manifest
from hanly_app.app_manifest import (
    MANIFEST_ASSET,
    UPDATE_METADATA_ASSET,
    InstallManifest,
    UpdateMetadata,
)
from hanly_app.app_update_install import (
    ARCHIVE_ROOT,
    CHECKSUM_ASSET,
    DifferentialInstaller,
    DifferentialUpdateError,
    UpdateCancelled,
)
from hanly_app.app_update_journal import (
    COMMITTED,
    PREPARED,
    RECOVERY_REQUIRED,
    InstallLock,
    JournalError,
    UpdateJournal,
    unsettled_journals,
    working_root,
)
from hanly_app.app_update_plan import (
    ADD,
    DELETE,
    FROM_DELTA,
    FROM_FULL,
    OWNERSHIP_UNVERIFIED,
    REPLACE,
    plan_update,
)
from hanly_app.app_update_runner import settle_previous_update
from hanly_app.update_service import RemoteResource

from tools.update_artifacts import build_release_products, generate_manifest

BASE_BUILD = {
    "hanly-desktop.exe": "program v1\n",
    "_internal/torch/lib.dll": "an unchanged dependency\n",
    "_internal/base_library.zip": "dropped later\n",
}

TARGET_BUILD = {
    "hanly-desktop.exe": "program v2\n",
    "_internal/torch/lib.dll": "an unchanged dependency\n",
    "_internal/added.txt": "new\n",
}


def _tree(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class _Release:
    """A published release on disk, and the fetcher a client reads it with."""

    def __init__(self, tmp_path: Path, *, with_delta: bool = True) -> None:
        self.root = tmp_path / "release"
        base_root = _tree(tmp_path / "published-old", dict(BASE_BUILD))
        self.base_manifest = generate_manifest(base_root, "1.0.0", architecture="x86_64")
        base_path = tmp_path / "base.manifest.json"
        base_path.write_text(self.base_manifest.to_json(), encoding="utf-8")

        self.target_root = _tree(tmp_path / "published-new", dict(TARGET_BUILD))
        # The inventory goes into the build before it is archived, exactly as
        # the release lane does it, so the archive carries it.
        generate_manifest(self.target_root, "1.1.0", architecture="x86_64")
        archive = tmp_path / "hanly-desktop-windows.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for relative in TARGET_BUILD:
                bundle.write(
                    self.target_root.joinpath(*relative.split("/")),
                    arcname=f"{ARCHIVE_ROOT}/{relative}",
                )
            bundle.write(
                self.target_root / ".hanly-manifest.json",
                arcname=f"{ARCHIVE_ROOT}/.hanly-manifest.json",
            )

        self.products = build_release_products(
            self.target_root,
            archive,
            "1.1.0",
            self.root,
            architecture="x86_64",
            base_manifest_path=base_path if with_delta else None,
        )
        (self.root / archive.name).write_bytes(archive.read_bytes())
        self._write_checksums()
        self.downloads: list[str] = []

    @property
    def metadata(self) -> UpdateMetadata:
        return UpdateMetadata.from_json(
            self.products.metadata_path.read_text(encoding="utf-8")
        )

    @property
    def manifest(self) -> InstallManifest:
        return InstallManifest.from_json(
            self.products.manifest_path.read_text(encoding="utf-8")
        )

    def _write_checksums(self) -> None:
        lines = []
        for path in sorted(self.root.iterdir()):
            if path.name == CHECKSUM_ASSET or not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.name}\n")
        (self.root / CHECKSUM_ASSET).write_text("".join(lines), encoding="utf-8")

    def payload(self) -> dict[str, Any]:
        return {"tag_name": "v1.1.0"}

    def download(
        self, resource: RemoteResource, destination: Path, on_progress: Any = None
    ) -> None:
        name = resource.asset_name or ""
        self.downloads.append(name)
        source = self.root / name
        if not source.is_file():
            raise DifferentialUpdateError(f"no asset {name}")
        destination.write_bytes(source.read_bytes())

    def corrupt(self, name: str) -> None:
        """Change one published asset without changing what SHA256SUMS says."""

        (self.root / name).write_bytes(b"tampered")


def _installer(release: _Release, install_root: Path, tmp_path: Path) -> DifferentialInstaller:
    return DifferentialInstaller(
        release,
        release.payload,
        install_root=install_root,
        executable="hanly-desktop.exe",
        recovery_root=tmp_path / "recovery",
    )


def _installed(tmp_path: Path, files: dict[str, str], manifest: InstallManifest | None) -> Path:
    root = _tree(tmp_path / "install" / "hanly-desktop", dict(files))
    if manifest is not None:
        (root / ".hanly-manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return root


# --------------------------------------------------------------------- plan --


def test_a_patch_release_replaces_adds_and_deletes_and_touches_nothing_else(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)

    plan = plan_update(
        release.metadata,
        release.manifest,
        read_installation(root),
        base_manifest=release.base_manifest,
    )

    assert {(item.kind, item.path) for item in plan.operations} == {
        (REPLACE, "hanly-desktop.exe"),
        (ADD, "_internal/added.txt"),
        (DELETE, "_internal/base_library.zip"),
    }
    # The one large dependency is in neither the plan nor the download.
    assert "_internal/torch/lib.dll" not in plan.required_paths
    assert plan.source == FROM_DELTA
    assert plan.download_bytes < release.metadata.full.size


def test_a_file_the_delta_does_not_carry_sends_the_update_to_the_full_archive(
    tmp_path: Path,
) -> None:
    """A dependency corrupted since install differs here and did not differ
    between the two published builds, so the delta cannot repair it."""

    release = _Release(tmp_path)
    damaged = dict(BASE_BUILD)
    damaged["_internal/torch/lib.dll"] = "corrupted\n"
    root = _installed(tmp_path, damaged, release.base_manifest)

    plan = plan_update(
        release.metadata,
        release.manifest,
        read_installation(root),
        base_manifest=release.base_manifest,
    )

    assert plan.source == FROM_FULL
    assert "_internal/torch/lib.dll" in plan.required_paths
    assert "repairing" in plan.fallback_reason


def test_an_installation_from_a_different_build_does_not_use_the_delta(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    other = _tree(tmp_path / "other", {**BASE_BUILD, "hanly-desktop.exe": "rebuilt\n"})
    manifest = generate_manifest(other, "1.0.0", architecture="x86_64")
    root = _installed(tmp_path, {**BASE_BUILD, "hanly-desktop.exe": "rebuilt\n"}, manifest)

    plan = plan_update(
        release.metadata, release.manifest, read_installation(root), base_manifest=manifest
    )

    assert plan.source == FROM_FULL
    assert "not the published build" in plan.fallback_reason


def test_an_installation_with_no_inventory_updates_without_guessing_deletions(
    tmp_path: Path,
) -> None:
    """A build from before manifests has no trustworthy ownership, so the
    update adds and replaces and removes nothing."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, {**BASE_BUILD, "someone-elses.txt": "keep me\n"}, None)

    plan = plan_update(
        release.metadata, release.manifest, read_installation(root), base_manifest=None
    )

    assert plan.source == FROM_FULL
    assert plan.deletions == ()
    assert plan.ownership == OWNERSHIP_UNVERIFIED
    assert "no file inventory" in plan.fallback_reason


def test_a_file_the_installation_does_not_own_is_reported_not_overwritten(
    tmp_path: Path,
) -> None:
    """Something else put a file where the new build wants one. Destroying it
    silently is the one outcome an updater must never choose."""

    release = _Release(tmp_path)
    occupied = dict(BASE_BUILD)
    occupied["_internal/added.txt"] = "not ours\n"
    root = _installed(tmp_path, occupied, release.base_manifest)

    plan = plan_update(
        release.metadata,
        release.manifest,
        read_installation(root),
        base_manifest=release.base_manifest,
    )

    assert plan.collisions == ("_internal/added.txt",)
    assert "_internal/added.txt" not in plan.required_paths


def test_an_installation_already_at_the_new_build_has_nothing_to_do(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, TARGET_BUILD, release.manifest)

    plan = plan_update(
        release.metadata, release.manifest, read_installation(root), base_manifest=release.manifest
    )

    assert plan.is_empty


# ------------------------------------------------------------------ staging --


def test_staging_downloads_the_delta_and_no_application_payload_before_it(
    tmp_path: Path,
) -> None:
    """Discovery and planning read metadata only: a check must never cost the
    user a download they did not ask for."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)

    prepared = installer.prepare("1.1.0")

    assert release.downloads == [CHECKSUM_ASSET, UPDATE_METADATA_ASSET, MANIFEST_ASSET]
    assert not prepared.requires_confirmation

    staged = installer.stage(prepared)

    assert release.downloads[-1].endswith(".delta.zip")
    assert staged.journal.read_plan().target.version == "1.1.0"
    # Staged, not installed: the running build is still exactly as it was.
    assert (root / "hanly-desktop.exe").read_text(encoding="utf-8") == "program v1\n"


def test_a_full_fallback_asks_again_before_it_downloads(tmp_path: Path) -> None:
    """The user agreed to a small differential download. Discovering here that
    it cannot be used changes the bargain, so the payload waits."""

    release = _Release(tmp_path)
    damaged = dict(BASE_BUILD)
    damaged["_internal/torch/lib.dll"] = "corrupted\n"
    root = _installed(tmp_path, damaged, release.base_manifest)

    prepared = _installer(release, root, tmp_path).prepare("1.1.0")

    assert prepared.requires_confirmation
    assert prepared.summary()["source"] == FROM_FULL
    assert prepared.summary()["download_bytes"] == release.metadata.full.size
    assert not any(name.endswith(".zip") for name in release.downloads)


def test_a_release_with_no_delta_still_names_its_size_before_downloading(
    tmp_path: Path,
) -> None:
    """Discovery costs no payload and reports no size, so nothing about a full
    archive has been authorized by the time the plan exists - whether the
    release published no delta or this installation cannot use the one it did."""

    release = _Release(tmp_path, with_delta=False)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)

    prepared = _installer(release, root, tmp_path).prepare("1.1.0")

    assert prepared.plan.source == FROM_FULL
    assert prepared.requires_confirmation
    assert prepared.summary()["download_bytes"] == release.metadata.full.size


def test_only_the_needed_members_come_out_of_a_full_archive(tmp_path: Path) -> None:
    """Falling back to the full archive is a change of source, not a return to
    unpacking a whole replacement tree."""

    release = _Release(tmp_path, with_delta=False)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)

    staged = installer.stage(installer.prepare("1.1.0"))

    operations = staged.journal.read_plan().operations
    written = {item.path for item in operations if item.writes_a_file}
    assert written == {"hanly-desktop.exe", "_internal/added.txt"}
    assert sorted(p.name for p in staged.journal.payload_root.iterdir()) == ["0001", "0002"]


def test_a_payload_that_does_not_match_its_published_digest_is_refused(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)
    prepared = installer.prepare("1.1.0")
    release.corrupt(release.metadata.delta.payload.name)  # type: ignore[union-attr]

    with pytest.raises(DifferentialUpdateError, match="size the release declares"):
        installer.stage(prepared)

    assert not list(working_root(root).glob("t*"))


def test_metadata_that_is_not_what_the_release_published_is_refused(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    release.corrupt(UPDATE_METADATA_ASSET)

    with pytest.raises(DifferentialUpdateError, match="not the file the release published"):
        _installer(release, root, tmp_path).prepare("1.1.0")


def test_a_release_that_moved_on_since_the_check_is_not_installed(tmp_path: Path) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    release.payload = lambda: {"tag_name": "v2.0.0"}  # type: ignore[method-assign]

    with pytest.raises(DifferentialUpdateError, match="no longer offers"):
        _installer(release, root, tmp_path).prepare("1.1.0")


def test_cancelling_during_preparation_changes_nothing(tmp_path: Path) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)

    with pytest.raises(UpdateCancelled):
        _installer(release, root, tmp_path).prepare("1.1.0", should_cancel=lambda: True)

    assert (root / "hanly-desktop.exe").read_text(encoding="utf-8") == "program v1\n"


def test_a_collision_stops_the_update_rather_than_destroying_the_file(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    occupied = dict(BASE_BUILD)
    occupied["_internal/added.txt"] = "not ours\n"
    root = _installed(tmp_path, occupied, release.base_manifest)
    installer = _installer(release, root, tmp_path)

    with pytest.raises(DifferentialUpdateError, match="does not own"):
        installer.stage(installer.prepare("1.1.0"))

    assert (root / "_internal" / "added.txt").read_text(encoding="utf-8") == "not ours\n"


# ------------------------------------------------------------------ journal --


def test_a_transaction_records_its_plan_and_its_phases(tmp_path: Path) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)

    staged = installer.stage(installer.prepare("1.1.0"))
    journal = staged.journal

    assert journal.phase() == PREPARED
    assert journal.is_settled()
    journal.record("applying")
    assert not journal.is_settled()
    assert [item.directory for item in unsettled_journals(root)] == [journal.directory]


def test_a_torn_final_record_does_not_make_the_journal_unreadable(
    tmp_path: Path,
) -> None:
    """The last line is what an interruption cuts in half, and a journal that
    could not be read at all would leave recovery with nothing to work from."""

    journal = UpdateJournal(tmp_path / "t")
    journal.directory.mkdir()
    journal.record("applying")
    with journal.progress_path.open("a", encoding="utf-8") as stream:
        stream.write('{"phase": "app')

    assert journal.phase() == "applying"


def test_one_installation_admits_one_updater_at_a_time(tmp_path: Path) -> None:
    """Two Hanlys started from one installation are two processes, so the
    coordinator's own in-process lock is not the one that matters here."""

    root = _installed(tmp_path, BASE_BUILD, None)
    lock = InstallLock(root)
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock.path.write_text(json.dumps({"pid": other.pid, "at": 0}), encoding="utf-8")

        with pytest.raises(JournalError, match="already updating"):
            lock.acquire()
    finally:
        other.kill()
        other.wait(timeout=30)


def test_a_lock_whose_owner_is_gone_does_not_block_the_next_update(
    tmp_path: Path,
) -> None:
    """A process killed mid-update leaves the file behind, and honouring it
    forever would make one crash permanent."""

    root = _installed(tmp_path, BASE_BUILD, None)
    lock = InstallLock(root)
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(json.dumps({"pid": 999999999, "at": 0}), encoding="utf-8")

    lock.acquire()

    assert lock.holder() is not None
    lock.release()


# ----------------------------------------------------------------- settling --


def test_a_launch_after_a_committed_update_clears_the_transaction(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)
    staged = installer.stage(installer.prepare("1.1.0"))
    staged.journal.record(COMMITTED)
    staged.journal.write_result(COMMITTED, "Hanly 1.1.0 started.")

    settled = settle_previous_update(root, tmp_path / "recovery")

    assert settled is not None
    assert settled.outcome == COMMITTED
    assert settled.version == "1.1.0"
    assert not working_root(root).exists()


def test_a_launch_with_no_recovery_record_keeps_an_unsettled_transaction(
    tmp_path: Path,
) -> None:
    """Nothing here may finish or delete a transaction whose outcome is
    unknown: the installation may be mid-replacement, and this interpreter is
    running out of it."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)
    staged = installer.stage(installer.prepare("1.1.0"))
    staged.journal.record("applying")

    settled = settle_previous_update(root, tmp_path / "elsewhere")

    assert settled is not None
    assert settled.outcome == RECOVERY_REQUIRED
    assert staged.journal.directory.is_dir()


def test_a_launch_with_nothing_outstanding_reports_nothing(tmp_path: Path) -> None:
    root = _installed(tmp_path, BASE_BUILD, None)

    assert settle_previous_update(root, tmp_path / "recovery") is None


def test_an_installed_build_carries_the_inventory_its_next_update_reads(
    tmp_path: Path,
) -> None:
    release = _Release(tmp_path)

    assert read_installed_manifest(release.target_root) == release.manifest


def test_the_build_a_helper_just_launched_does_not_start_a_second_one(
    tmp_path: Path,
) -> None:
    """This is the commonest unsettled transaction there is: the helper starts
    the new build and waits for it to answer, so settling runs while that
    helper is still there. Two programs moving the same files is the one
    outcome recovery must not produce."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)
    staged = installer.stage(installer.prepare("1.1.0"))
    staged.journal.record("awaiting-startup")

    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        staged.journal.helper_path.write_text(
            json.dumps({"pid": alive.pid}), encoding="utf-8"
        )
        recovery = tmp_path / "recovery"
        recovery.mkdir(parents=True, exist_ok=True)
        (recovery / "pending.json").write_text(
            json.dumps({"transaction": str(staged.journal.directory)}), encoding="utf-8"
        )

        settled = settle_previous_update(root, recovery)

        assert settled is not None
        assert settled.detail == "An update is being applied."
        # Untouched: the helper that owns it is the only thing allowed to act.
        assert staged.journal.directory.is_dir()
        assert (recovery / "pending.json").is_file()
    finally:
        alive.kill()
        alive.wait(timeout=30)


def test_an_update_the_volume_cannot_hold_stops_before_it_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The payload, the files unpacked from it, and the originals moved aside
    are all present at once, so the requirement is their sum - not, as a
    download alone would suggest, the size of the download."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)
    prepared = installer.prepare("1.1.0")
    monkeypatch.setattr(
        "hanly_app.app_update_install.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=0, used=0, free=1024),
    )

    with pytest.raises(DifferentialUpdateError, match="free on the drive"):
        installer.stage(prepared)

    assert not list(working_root(root).glob("t*"))


def test_deciding_an_update_writes_nothing_into_the_installation(
    tmp_path: Path,
) -> None:
    """Preparing happens before the user has committed to anything, and an
    installation the user cannot write to is still one Hanly may check."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    before = sorted(item.name for item in root.iterdir())

    _installer(release, root, tmp_path).prepare("1.1.0")

    assert sorted(item.name for item in root.iterdir()) == before


def test_a_member_that_expands_past_its_declared_size_is_abandoned(
    tmp_path: Path,
) -> None:
    """The manifest says exactly how large each file is, so a member that keeps
    decompressing is stopped mid-stream rather than allowed to fill the disk
    and fail a digest check afterwards."""

    release = _Release(tmp_path)
    root = _installed(tmp_path, BASE_BUILD, release.base_manifest)
    installer = _installer(release, root, tmp_path)
    prepared = installer.prepare("1.1.0")

    # Every member the plan needs is still there; one of them lies about its
    # size, which is the only thing a digest check alone would catch too late.
    delta = release.root / release.metadata.delta.payload.name  # type: ignore[union-attr]
    with zipfile.ZipFile(delta, "w") as payload:
        payload.writestr("hanly-desktop.exe", "x" * 50_000_000)
        added = release.target_root / "_internal" / "added.txt"
        payload.writestr("_internal/added.txt", added.read_bytes())
    release.products.metadata_path.write_text(
        _reissued(release, delta).to_json(), encoding="utf-8"
    )
    release._write_checksums()

    with pytest.raises(DifferentialUpdateError, match="larger than the release describes"):
        installer.stage(installer.prepare("1.1.0"))

    assert prepared.plan.source == FROM_DELTA
    assert not list(working_root(root).glob("t*"))


def _reissued(release: _Release, delta_path: Path) -> UpdateMetadata:
    """Re-describe a rewritten payload so it passes its own integrity check."""

    from dataclasses import replace

    from hanly_app.app_manifest import AssetReference

    metadata = release.metadata
    assert metadata.delta is not None
    payload = AssetReference(
        name=delta_path.name,
        size=delta_path.stat().st_size,
        sha256=hashlib.sha256(delta_path.read_bytes()).hexdigest(),
    )
    return replace(metadata, delta=replace(metadata.delta, payload=payload))
