"""The macOS half of an update: disk images, bundles, and signatures.

Nothing here runs macOS's own tools. What is held to account is how this build
asks for them - the flags a disk image is attached with, the device it detaches
rather than the path, the fact that a failure still detaches - and what it
makes of the bundle afterwards. The macOS lane runs the real tools.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from hanly_app.app_update_macos import (
    CODESIGN,
    DITTO,
    FIND,
    HDIUTIL,
    BundleError,
    acquire_disk_image,
    mounted_image,
    require_bundle_identity,
    require_no_unsupported_metadata,
    require_valid_signature,
)

from tests.hanly_fixtures.update_release import PublishedRelease
from tests.hanly_fixtures.update_tree import BUNDLE_IDENTIFIER, MACOS, info_plist


@dataclass
class _Tools:
    """macOS's tools, standing still: what was asked, and what to answer."""

    mount_point: Path | None = None
    attach_entities: int = 1
    failures: tuple[str, ...] = ()
    acl_output: bytes = b""
    commands: list[list[str]] = field(default_factory=list)

    def __call__(self, command: list[str], **_options: Any) -> Any:
        self.commands.append(list(command))
        tool = command[0]
        if any(failure in command for failure in self.failures):
            return _Completed(1, b"", b"the tool refused")
        if tool == HDIUTIL and command[1] == "attach":
            return _Completed(0, self._attach_plist(command), b"")
        if tool == FIND:
            return _Completed(0, self.acl_output, b"")
        if tool == DITTO:
            self._copy(Path(command[1]), Path(command[2]))
        return _Completed(0, b"", b"")

    @property
    def detached(self) -> list[str]:
        return [item[2] for item in self.commands if item[0] == HDIUTIL and item[1] == "detach"]

    def _attach_plist(self, command: list[str]) -> bytes:
        holder = Path(command[command.index("-mountrandom") + 1])
        mount = self.mount_point if self.mount_point is not None else holder / "Hanly"
        entities: list[dict[str, str]] = [{"dev-entry": "/dev/disk9"}]
        for index in range(self.attach_entities):
            entities.append(
                {"dev-entry": f"/dev/disk9s{index + 1}", "mount-point": str(mount)}
            )
        return plistlib.dumps({"system-entities": entities})

    @staticmethod
    def _copy(source: Path, destination: Path) -> None:
        import shutil

        shutil.copytree(source, destination, symlinks=True)


@dataclass(frozen=True)
class _Completed:
    returncode: int
    stdout: bytes
    stderr: bytes


def _bundle(tmp_path: Path, version: str = "0.5.3") -> Path:
    release = PublishedRelease(
        tmp_path / f"release-{version}", MACOS, version=version, build_id="build-one"
    )
    return release.build


def test_a_disk_image_is_attached_privately_and_detached_by_its_own_device(
    tmp_path: Path,
) -> None:
    tools = _Tools()

    with mounted_image(tmp_path / "hanly.dmg", runner=tools) as mount_point:
        assert mount_point.name == "Hanly"

    attach = next(item for item in tools.commands if item[1] == "attach")
    for flag in ("-readonly", "-nobrowse", "-noautoopen", "-plist", "-mountrandom"):
        assert flag in attach
    assert tools.detached == ["/dev/disk9s1"]


def test_a_disk_image_is_detached_even_when_reading_it_fails(tmp_path: Path) -> None:
    tools = _Tools()

    with pytest.raises(RuntimeError, match="deliberate"):
        with mounted_image(tmp_path / "hanly.dmg", runner=tools):
            raise RuntimeError("deliberate")

    assert tools.detached == ["/dev/disk9s1"]


def test_a_disk_image_holding_more_than_one_volume_is_refused(tmp_path: Path) -> None:
    tools = _Tools(attach_entities=2)

    with pytest.raises(BundleError, match="exactly one volume"):
        with mounted_image(tmp_path / "hanly.dmg", runner=tools):
            pass

    assert len(tools.detached) == 2


def test_an_image_that_will_not_detach_says_how_to_close_it(tmp_path: Path) -> None:
    tools = _Tools(failures=("detach",))

    with pytest.raises(BundleError, match="hdiutil detach /dev/disk9s1"):
        with mounted_image(tmp_path / "hanly.dmg", runner=tools):
            pass


def test_the_published_bundle_is_copied_out_of_its_image_with_ditto(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    release = PublishedRelease(
        tmp_path / "release-copy", MACOS, version="0.5.3", build_id="build-one"
    )
    tools = _Tools(mount_point=bundle.parent)

    candidate = acquire_disk_image(
        tmp_path / "tx" / "candidate", tmp_path / "hanly.dmg", release.manifest, runner=tools
    )

    assert any(item[0] == DITTO for item in tools.commands)
    assert (candidate.root / "Contents" / "MacOS" / "hanly-desktop").is_file()
    assert tools.detached == ["/dev/disk9s1"]


def test_an_image_without_the_expected_application_is_refused(tmp_path: Path) -> None:
    release = PublishedRelease(
        tmp_path / "release", MACOS, version="0.5.3", build_id="build-one"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    tools = _Tools(mount_point=empty)

    with pytest.raises(BundleError, match="does not contain Hanly.app"):
        acquire_disk_image(
            tmp_path / "tx" / "candidate", tmp_path / "hanly.dmg", release.manifest, runner=tools
        )

    assert tools.detached == ["/dev/disk9s1"]


def test_a_bundle_that_is_this_application_at_this_version_is_accepted(
    tmp_path: Path,
) -> None:
    require_bundle_identity(
        _bundle(tmp_path), version="0.5.3", executable="Contents/MacOS/hanly-desktop"
    )


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("CFBundleIdentifier", "com.example.other", "is not Hanly"),
        ("CFBundleShortVersionString", "0.4.0", "CFBundleShortVersionString is not"),
        ("CFBundleVersion", "0.4.0", "CFBundleVersion is not"),
    ],
)
def test_a_bundle_whose_plist_disagrees_with_the_release_is_refused(
    tmp_path: Path, key: str, value: str, expected: str
) -> None:
    bundle = _bundle(tmp_path)
    payload = plistlib.loads(info_plist("0.5.3"))
    payload[key] = value
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(payload))

    with pytest.raises(BundleError, match=expected):
        require_bundle_identity(
            bundle, version="0.5.3", executable="Contents/MacOS/hanly-desktop"
        )


def test_a_bundle_with_no_signature_or_no_program_is_refused(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "Contents" / "_CodeSignature" / "CodeResources").unlink()
    with pytest.raises(BundleError, match="carries no signature"):
        require_bundle_identity(
            bundle, version="0.5.3", executable="Contents/MacOS/hanly-desktop"
        )

    other = _bundle(tmp_path, version="0.5.2")
    with pytest.raises(BundleError, match="no program at"):
        require_bundle_identity(other, version="0.5.2", executable="Contents/MacOS/absent")


def test_signature_verification_reaches_nested_code_and_fails_loudly(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    tools = _Tools()

    require_valid_signature(bundle, runner=tools)

    command = next(item for item in tools.commands if item[0] == CODESIGN)
    assert command[1:5] == ["--verify", "--deep", "--strict", "--verbose=2"]

    with pytest.raises(BundleError, match="signature verification"):
        require_valid_signature(bundle, runner=_Tools(failures=("--verify",)))


def test_a_tree_carrying_an_access_control_list_fails_the_producer(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)

    require_no_unsupported_metadata(bundle, runner=_Tools())

    with pytest.raises(BundleError, match="access-control list"):
        require_no_unsupported_metadata(
            bundle, runner=_Tools(acl_output=b"./Contents/Resources\n")
        )


def test_the_bundle_identifier_a_release_publishes_is_the_one_checked() -> None:
    from hanly_app.app_update_macos import BUNDLE_IDENTIFIER as CHECKED

    assert CHECKED == BUNDLE_IDENTIFIER
