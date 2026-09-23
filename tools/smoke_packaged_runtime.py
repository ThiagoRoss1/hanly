"""Prove a frozen Hanly bundle can look a word up with only what it ships.

Two checks, in order. The inventory says whether the required runtime
dependencies were collected at all; the self-check runs the bundle's own
executable and makes it construct the real providers. Inventory alone is not
evidence -- a present file that cannot be imported still leaves the desktop
unable to become ready.

Nothing here may fall back to the repository, the developer virtual
environment, or developer model caches: the run uses a temporary profile and a
working directory outside the checkout. What the run may be given is named on
the command line -- a dictionary to install, a model directory to seed -- so
determinism is always an explicit argument rather than an inherited accident.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

#: Packages the desktop imports by name at runtime. Their absence is exactly
#: the defect that shipped in v0.1.0: readiness waits on morphology forever.
REQUIRED_PACKAGES = ("kiwipiepy", "kiwipiepy_model", "easyocr")

#: Kiwi's analyzer is a native extension module beside the package.
REQUIRED_EXTENSION_STEM = "_kiwipiepy"

#: Model data Kiwi loads from ``kiwipiepy_model``. Sampled rather than
#: exhaustive: these three are enough to catch a data-free collection.
REQUIRED_MODEL_FILES = ("sj.morph", "default.dict", "combiningRule.txt")

REQUIRED_DATA_FILES = (
    "certifi/cacert.pem",
    "hanly_app/assets/easyocr_models/craft_mlt_25k.pth",
    "hanly_app/assets/easyocr_models/korean_g2.pth",
    "easyocr/character/ko_char.txt",
)

#: PyInstaller 6 places collected packages under this directory.
_INTERNAL_DIRECTORY = "_internal"

#: The application executable, and where a macOS bundle keeps it.
APPLICATION_STEM = "hanly-desktop"
BUNDLE_NAME = "Hanly.app"
_BUNDLE_PROGRAM_PARTS = ("Contents", "MacOS", APPLICATION_STEM)

#: Reported for a macOS bundle only: the seal an installed application needs.
BUNDLE_SIGNATURE = "Contents/_CodeSignature/CodeResources"

#: Where a collection can sit: ``_internal`` in a onedir build, or split
#: across ``Frameworks`` and ``Resources`` in a cross-linked macOS bundle.
_COLLECTION_ROOTS = (
    (),
    (_INTERNAL_DIRECTORY,),
    ("Contents", "Frameworks"),
    ("Contents", "Frameworks", _INTERNAL_DIRECTORY),
    ("Contents", "Resources"),
    ("Contents", "Resources", _INTERNAL_DIRECTORY),
)

#: macOS's own tools, used only to reconstruct and inspect what was published.
DITTO = "/usr/bin/ditto"
HDIUTIL = "/usr/bin/hdiutil"

CommandRunner = Callable[..., Any]

#: A cold frozen start imports torch and warms two models. The work itself was
#: measured at roughly 45 s; the rest of this is the platform reading a freshly
#: frozen bundle's tens of thousands of new files for the first time, which has
#: been observed to outlast 300 s on its own. It is the deadlock guard, not a
#: budget: a self-check that fails now reports and exits rather than waiting.
DEFAULT_TIMEOUT_SECONDS = 1200

#: Opening the window imports Qt WebEngine and starts Chromium; it constructs
#: no provider, so it is bounded far more tightly than the worker. It is not
#: bounded tightly: the first launch of a freshly frozen bundle waits on the
#: platform reading tens of thousands of new files, which cost two 300 s
#: timeouts here before the same check ran in under a second warm.
UI_TIMEOUT_SECONDS = 600

#: How long the timed-out process tree is given to actually die. Reaping has
#: already failed by this point, so this bounds the cleanup rather than the run.
TREE_KILL_SECONDS = 30

#: Where EasyOCR looks for its recognition models, in the order it asks. All
#: of them are redirected into the temporary profile, so a developer cache can
#: never be what makes a frozen run succeed.
EASYOCR_PATH_VARIABLES = ("EASYOCR_MODULE_PATH", "MODULE_PATH")

#: EasyOCR appends this to whichever module path it resolved, so a seeded
#: cache has to land there rather than beside it.
EASYOCR_MODEL_SUBDIRECTORY = "model"

#: Redirected so nothing resolves ``~`` back to the developer's account.
HOME_VARIABLES = ("HOME", "USERPROFILE", "XDG_CACHE_HOME")

#: Qt aborts rather than raises when it cannot load a platform plugin, and a
#: hosted Linux runner advertises a display it cannot actually serve. A check
#: that opens no window therefore names the one platform that always loads
#: instead of trusting the session, which is why this is set rather than
#: defaulted. The window check is not headless and keeps its real display.
QT_PLATFORM_VARIABLE = "QT_QPA_PLATFORM"
HEADLESS_QT_PLATFORM = "offscreen"

#: Self-check modes that construct no window and must never need a display.
HEADLESS_SELF_CHECK_MODES = ("worker",)

#: How much of a crashed run's output is repeated above the report. A fault
#: handler traceback is why this is measured in lines rather than in one.
OUTPUT_TAIL_LINES = 20

#: Fatal Windows exceptions, which arrive as the raw NTSTATUS a process died
#: on rather than as a signal. Reported by name because the bare number says
#: nothing: 3221225501 is an illegal instruction, which is a native library
#: meeting a CPU that does not implement what it was compiled to use.
WINDOWS_FATAL_STATUS = {
    0xC0000005: "ACCESS_VIOLATION",
    0xC000001D: "ILLEGAL_INSTRUCTION",
    0xC0000094: "INTEGER_DIVIDE_BY_ZERO",
    0xC0000135: "DLL_NOT_FOUND",
    0xC0000139: "ENTRYPOINT_NOT_FOUND",
    0xC0000142: "DLL_INIT_FAILED",
    0xC000013A: "CONTROL_C_EXIT",
    0xC0000374: "HEAP_CORRUPTION",
    0xC00000FD: "STACK_OVERFLOW",
    0xC0000409: "STACK_BUFFER_OVERRUN",
}

#: How first-run provisioning is pointed at an already-built dictionary.
#: Named here rather than imported: this harness runs against a frozen bundle
#: and must not depend on the source package it is checking.
LOCAL_KRDICT_VARIABLE = "HANLY_KRDICT_DB"

#: The packages a frozen bundle has to be able to name itself by. A build that
#: works and cannot say which source produced it is not release evidence: one
#: tested bundle reported 0.1.3 while the tree it was compared against was
#: 0.5.0, and nothing in the run said so.
IDENTITY_PACKAGES = ("hanly", "hanly-app")

#: The self-check writes one flushed JSON line per stage boundary on stderr.
#: Named here for the same reason as the variable above. A process killed by a
#: native fault prints no report, and these lines are the only account of how
#: far it got.
STAGE_MARKER_PREFIX = "hanly-self-check:"
STAGE_STARTED = "stage_started"
STAGE_COMPLETED = "stage_completed"


@dataclass(frozen=True, slots=True)
class BundleInventory:
    """What a frozen application directory actually contains."""

    root: Path
    present: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "ok": self.ok,
            "present": list(self.present),
            "missing": list(self.missing),
        }


def inspect_bundle(application_directory: str | Path) -> BundleInventory:
    """Report which required runtime dependencies the bundle carries."""

    root = Path(application_directory).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"not a frozen application directory: {root}")

    present: list[str] = []
    missing: list[str] = []
    for package_name in REQUIRED_PACKAGES:
        target = present if _find_package(root, package_name) is not None else missing
        target.append(package_name)

    extension = _find_extension(root, REQUIRED_EXTENSION_STEM)
    (present if extension is not None else missing).append(
        extension.name if extension is not None else f"{REQUIRED_EXTENSION_STEM} extension"
    )

    model_root = _find_package(root, "kiwipiepy_model")
    for model_file in REQUIRED_MODEL_FILES:
        found = model_root is not None and (model_root / model_file).is_file()
        (present if found else missing).append(f"kiwipiepy_model/{model_file}")

    for data_file in REQUIRED_DATA_FILES:
        (present if _find_data_file(root, data_file) is not None else missing).append(data_file)

    if root.suffix == ".app":
        # An application without one is not installable by Hanly's own updater,
        # and PyInstaller only warns when it could not sign the bundle.
        signature = root / "Contents" / "_CodeSignature" / "CodeResources"
        (present if signature.is_file() else missing).append(BUNDLE_SIGNATURE)

    return BundleInventory(root, tuple(present), tuple(missing))


def run_packaged_self_check(
    executable: str | Path,
    *,
    mode: str = "worker",
    runtime_config: str | Path | None = None,
    image: str | Path | None = None,
    profile: str | Path | None = None,
    model_cache: str | Path | None = None,
    krdict: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run one of the bundle's own ``--self-check`` modes and parse its report."""

    command = [str(Path(executable).resolve()), "--self-check", mode]
    if runtime_config is not None:
        command.extend(["--runtime-config", str(Path(runtime_config).resolve())])
    if image is not None:
        command.extend(["--self-check-image", str(Path(image).resolve())])

    with _ProfileContext(
        profile,
        model_cache=model_cache,
        krdict=krdict,
        headless=mode in HEADLESS_SELF_CHECK_MODES,
    ) as (
        environment,
        working_directory,
    ):
        # Files, not pipes. Qt WebEngine spawns helper processes that inherit
        # the child's stdout handle on Windows, so waiting for the pipe to
        # close outlives the process being measured and looks like a hang.
        output = working_directory / "self-check.out"
        errors = working_directory / "self-check.err"
        status: int | None = None
        timed_out = False
        with output.open("w", encoding="utf-8") as out, errors.open("w", encoding="utf-8") as err:
            child = subprocess.Popen(
                command, stdout=out, stderr=err, env=environment, cwd=working_directory
            )
            try:
                status = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # The report is written before the process winds Qt down, so a
                # run that stops exiting still says whether the check itself
                # passed. Reporting both keeps "the window is broken" separate
                # from "the window worked and the process did not leave".
                timed_out = True
                _terminate_tree(child)
        stdout = output.read_text(encoding="utf-8", errors="replace")
        stderr = errors.read_text(encoding="utf-8", errors="replace")

    report = _parse_report(stdout)
    report["exit_code"] = status
    report["exit_timeout"] = timed_out
    # Progress is read from the whole stream, before the tail is cut: the
    # markers a long-running check wrote first are exactly the ones a 4000
    # character tail would drop.
    report["progress"] = read_progress(stderr)
    report["stderr"] = stderr[-4000:]
    return report


def _terminate_tree(child: subprocess.Popen[bytes]) -> None:
    """Kill the timed-out process and everything it started.

    Killing only the process that was launched leaves its children holding the
    inherited output files, so the run's own working directory cannot be
    removed and an abandoned bundle keeps running. The frozen desktop spawns
    both the lookup child and Qt WebEngine's helpers, and on Windows the
    launcher itself is a further process.
    """

    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(child.pid)],
                capture_output=True,
                timeout=TREE_KILL_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            child.kill()
    else:
        child.kill()

    try:
        child.wait(timeout=TREE_KILL_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def read_progress(stderr: str) -> dict[str, object]:
    """Reconstruct how far the self-check got from the markers it flushed.

    The current stage is the most recent one started and not completed, which
    is the innermost of any nested probes. A run that printed no marker at all
    leaves it unknown rather than guessing at the last stage that passed.
    """

    started: list[str] = []
    completed: list[dict[str, object]] = []
    open_stages: list[str] = []
    for event in _iter_markers(stderr):
        name = event.get("stage")
        if not isinstance(name, str):
            continue
        if event.get("event") == STAGE_STARTED:
            started.append(name)
            open_stages.append(name)
        elif event.get("event") == STAGE_COMPLETED:
            completed.append({key: value for key, value in event.items() if key != "event"})
            if name in open_stages:
                open_stages.remove(name)

    return {
        "started": started,
        "completed": completed,
        "current_stage": open_stages[-1] if open_stages else None,
    }


def _iter_markers(stderr: str) -> Iterator[dict[str, Any]]:
    """Read the marker lines, ignoring whatever native noise sits around them."""

    for line in stderr.splitlines():
        payload = _marker_payload(line)
        if payload is None:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _marker_payload(line: str) -> str | None:
    """Return the JSON a marker line carries, wherever the line starts.

    A native library can write a partial line without a newline, so a marker
    is located inside the line rather than required to begin it.
    """

    start = line.find(STAGE_MARKER_PREFIX)
    if start < 0:
        return None
    return line[start + len(STAGE_MARKER_PREFIX) :].strip()


def verify_frozen_identity(
    report: Mapping[str, object], expected: str
) -> dict[str, object]:
    """Compare the versions a frozen bundle reports with the one it claims.

    The bundle answers for itself, from the metadata its own interpreter
    collected. A missing version is a failure rather than an absence: a report
    that cannot name its packages proves nothing about which build it came
    from.
    """

    versions = report.get("versions")
    collected = versions if isinstance(versions, Mapping) else {}
    packages = {name: collected.get(name) for name in IDENTITY_PACKAGES}
    problems = [
        f"the frozen bundle reports {name} {value!r}, expected {expected!r}"
        for name, value in packages.items()
        if value != expected
    ]
    return {
        "expected": expected,
        "packages": packages,
        "ok": not problems,
        "problems": problems,
    }


#: Names the commit a packaged gate requires its artifact to have been built
#: from. It is given explicitly, never read from whatever checkout runs the gate.
EXPECTED_SOURCE_VARIABLE = "HANLY_EXPECTED_SOURCE_COMMIT"

_BUILD_STAMP_FILE = "hanly_app/assets/hanly-build.json"


def verify_source_identity(
    bundle: Path,
    *,
    expected_commit: str,
    expected_version: str,
    expected_platform: str,
    expected_architecture: str,
) -> dict[str, object]:
    """Compare the build stamp a frozen bundle carries with the build expected.

    Versions alone cannot tell two builds of one version apart, so a bundle
    frozen from an older commit passes every version check. The stamp written
    before the freeze names the exact commit, and it is read from the files on
    disk rather than asked of the program, which a stale build might predate.
    """

    expected = {
        "source_commit": expected_commit.strip().lower(),
        "version": expected_version,
        "platform": expected_platform,
        "architecture": expected_architecture,
    }
    result: dict[str, object] = {"expected": expected, "stamp": None, "ok": False}
    if not _is_full_commit(expected["source_commit"]):
        result["problems"] = ["the expected source commit is not a full 40-character hash"]
        return result

    stamp_file = _find_data_file(bundle, _BUILD_STAMP_FILE)
    if stamp_file is None:
        result["problems"] = ["the frozen bundle carries no build stamp"]
        return result
    try:
        stamp = json.loads(stamp_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        result["problems"] = [f"the frozen bundle's build stamp is unreadable: {error}"]
        return result
    if not isinstance(stamp, dict):
        result["problems"] = ["the frozen bundle's build stamp is not a JSON object"]
        return result

    # A missing field is a mismatch rather than an absence, as with versions.
    found = {name: stamp.get(name) for name in expected}
    if isinstance(found["source_commit"], str):
        found["source_commit"] = found["source_commit"].lower()
    problems = [
        f"the frozen bundle was built with {name} {found[name]!r}, expected {value!r}"
        for name, value in expected.items()
        if found[name] != value
    ]
    result.update(stamp=found, ok=not problems, problems=problems)
    return result


def _is_full_commit(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def _collection_roots(root: Path) -> tuple[Path, ...]:
    return tuple(root.joinpath(*parts) for parts in _COLLECTION_ROOTS)


def _find_package(root: Path, package_name: str) -> Path | None:
    for directory in _collection_roots(root):
        candidate = directory / package_name
        if candidate.is_dir():
            return candidate
    return None


def _find_data_file(root: Path, relative_path: str) -> Path | None:
    for directory in _collection_roots(root):
        candidate = directory.joinpath(*relative_path.split("/"))
        if candidate.is_file():
            return candidate
    return None


def _find_extension(root: Path, stem: str) -> Path | None:
    """Locate the native extension without assuming one platform's suffix."""

    for directory in _collection_roots(root):
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.startswith(stem) and _is_extension(entry):
                return entry
    return None


def _is_extension(path: Path) -> bool:
    return path.suffix in {".pyd", ".so", ".dylib"} or ".so." in path.name


class _ProfileContext:
    """A per-user profile and working directory outside the repository.

    Settings, home, the working directory, and every EasyOCR model location are
    redirected together. Redirecting only the settings root would still let a
    frozen bundle read the developer's ``~/.EasyOCR`` cache and pass a check
    the released artifact would fail on a user's machine.

    A packaged build carries its own EasyOCR weights and cannot download, so a
    clean profile has to succeed on what the bundle ships. ``model_cache``
    seeds the isolated model directory for a build that still resolves models
    through the environment; a current frozen bundle ignores it.

    ``headless`` belongs to a check that opens no window: it names a Qt
    platform that always loads rather than letting Qt abort on a display the
    session advertises but cannot serve.

    ``krdict`` names an already-built dictionary for the bundle to install.
    The database is licensed and ships in neither the bundle nor the
    repository, so without one a first run reaches the public release channel
    -- a network dependency this check has no business carrying.
    """

    def __init__(
        self,
        profile: str | Path | None,
        *,
        model_cache: str | Path | None = None,
        krdict: str | Path | None = None,
        headless: bool = False,
    ) -> None:
        self._profile = None if profile is None else Path(profile).resolve()
        self._model_cache = None if model_cache is None else Path(model_cache).resolve()
        self._krdict = None if krdict is None else Path(krdict).resolve()
        self._headless = headless
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> tuple[dict[str, str], Path]:
        if self._profile is None:
            # Errors ignored: a bundle that had to be killed can leave a handle
            # open on Windows, and losing a temporary directory must not be
            # what destroys the report explaining why it was killed.
            self._temporary = tempfile.TemporaryDirectory(
                prefix="hanly-smoke-", ignore_cleanup_errors=True
            )
            root = Path(self._temporary.name)
        else:
            root = self._profile
        settings = root / "profile"
        work = root / "work"
        home = root / "home"
        models = root / "models"
        for directory in (settings, work, home, models):
            directory.mkdir(parents=True, exist_ok=True)
        self._seed_models(models)
        self._require_krdict()

        return (
            isolated_environment(
                os.environ,
                settings,
                home,
                models,
                krdict=self._krdict,
                headless=self._headless,
            ),
            work,
        )

    def _seed_models(self, models: Path) -> None:
        """Copy a named model directory in, for a deterministic offline run."""

        if self._model_cache is None:
            return
        if not self._model_cache.is_dir():
            raise FileNotFoundError(f"no EasyOCR model directory at {self._model_cache}")
        destination = models / EASYOCR_MODEL_SUBDIRECTORY
        destination.mkdir(parents=True, exist_ok=True)
        for source in self._model_cache.iterdir():
            if source.is_file():
                shutil.copy2(source, destination / source.name)

    def _require_krdict(self) -> None:
        """Refuse a named dictionary that is not there, rather than downloading."""

        if self._krdict is not None and not self._krdict.is_file():
            raise FileNotFoundError(f"no KRDICT database at {self._krdict}")

    def __exit__(self, *_exc_info: object) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def reconstruct_application(
    archive: str | Path,
    destination: str | Path,
    *,
    payload_name: str = BUNDLE_NAME,
    runner: CommandRunner = subprocess.run,
) -> Path:
    """Unpack a published macOS ZIP and return the application inside it.

    The point is to check what was actually published: the same ZIP the
    updater downloads, unpacked with the same tool, rather than the build
    directory it was made from.
    """

    source = Path(archive).resolve()
    target = Path(destination).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    _run_native(
        runner,
        [DITTO, "-x", "-k", str(source), str(target)],
        f"could not unpack {source.name}",
    )
    application = target / payload_name
    if not application.joinpath(*_BUNDLE_PROGRAM_PARTS).is_file():
        raise FileNotFoundError(f"{source.name} does not contain {payload_name}")
    return application


def reconstruct_from_disk_image(
    image: str | Path,
    destination: str | Path,
    *,
    payload_name: str = BUNDLE_NAME,
    runner: CommandRunner = subprocess.run,
) -> Path:
    """Copy the application out of the published disk image, as a client does.

    The disk image is the whole product a HUP client downloads when it needs
    one, so what is smoked is what comes out of it - not the build directory it
    was made from, and not the ZIP beside it.
    """

    source = Path(image).resolve()
    target = Path(destination).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="hanly-dmg-") as scratch:
        mountpoint = Path(scratch) / "mount"
        mountpoint.mkdir()
        _run_native(
            runner,
            [HDIUTIL, "attach", str(source), "-readonly", "-nobrowse", "-mountpoint",
             str(mountpoint)],
            f"could not mount {source.name}",
        )
        try:
            application = mountpoint / payload_name
            if not application.is_dir():
                raise FileNotFoundError(f"{source.name} does not contain {payload_name}")
            _run_native(
                runner,
                [DITTO, str(application), str(target / payload_name)],
                f"could not copy {payload_name} out of {source.name}",
            )
        finally:
            _run_native(
                runner,
                [HDIUTIL, "detach", str(mountpoint), "-force"],
                f"could not unmount {source.name}",
            )

    copied = target / payload_name
    if not copied.joinpath(*_BUNDLE_PROGRAM_PARTS).is_file():
        raise FileNotFoundError(f"{source.name} does not contain {payload_name}")
    return copied


def compare_to_manifest(application: Path, manifest_path: Path) -> dict[str, object]:
    """Say exactly how a reconstructed product differs from what was published.

    Both published macOS products come from one finished bundle, so holding
    each to the same manifest is what proves they are the same application -
    and what would catch one of them losing a link or a permission bit on the
    way through its own format.
    """

    from hanly_app.app_inventory import compare_tree, read_tree
    from hanly_app.app_manifest import TreeManifest

    manifest = TreeManifest.from_json(Path(manifest_path).read_text(encoding="utf-8"))
    inventory = read_tree(Path(application), manifest.platform)
    comparison = compare_tree(inventory, manifest)
    return {
        "manifest": Path(manifest_path).name,
        "build_id": manifest.identity.build_id,
        "entries": len(manifest),
        "ok": comparison.matches,
        "missing": list(comparison.missing[:10]),
        "differing": list(comparison.differing[:10]),
        "unexpected": list(comparison.extra[:10]),
    }


def verify_disk_image(
    image: str | Path,
    *,
    payload_name: str = BUNDLE_NAME,
    runner: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """Mount the published disk image read-only and report what it holds.

    A DMG is never an update input, so this proves only that the download a
    person opens contains the application they are meant to drag out of it.
    """

    source = Path(image).resolve()
    with tempfile.TemporaryDirectory(prefix="hanly-dmg-") as scratch:
        mountpoint = Path(scratch) / "mount"
        mountpoint.mkdir()
        _run_native(
            runner,
            [
                HDIUTIL,
                "attach",
                str(source),
                "-readonly",
                "-nobrowse",
                "-mountpoint",
                str(mountpoint),
            ],
            f"could not mount {source.name}",
        )
        try:
            application = mountpoint / payload_name
            program = application.joinpath(*_BUNDLE_PROGRAM_PARTS)
            report = {
                "image": source.name,
                "application": payload_name,
                "ok": program.is_file(),
                "contents": sorted(item.name for item in mountpoint.iterdir()),
            }
        finally:
            _run_native(
                runner,
                [HDIUTIL, "detach", str(mountpoint), "-force"],
                f"could not unmount {source.name}",
            )
    return report


def _run_native(runner: CommandRunner, command: list[str], failure: str) -> None:
    completed = runner(command, check=False, capture_output=True)
    if getattr(completed, "returncode", 1) != 0:
        detail = getattr(completed, "stderr", b"") or b""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        raise RuntimeError(f"{failure}: {detail.strip() or command[0]}")


def isolated_environment(
    inherited: Mapping[str, str],
    settings: Path,
    home: Path,
    models: Path,
    *,
    krdict: Path | None = None,
    headless: bool = False,
) -> dict[str, str]:
    """Build the child environment, with every developer path redirected."""

    environment = dict(inherited)
    environment["LOCALAPPDATA"] = str(settings)
    environment["XDG_CONFIG_HOME"] = str(settings)
    for variable in HOME_VARIABLES:
        environment[variable] = str(home)
    for variable in EASYOCR_PATH_VARIABLES:
        environment[variable] = str(models)
    # An inherited value is a developer's own dictionary; the named one is the
    # only dictionary a run is allowed to install.
    if krdict is None:
        environment.pop(LOCAL_KRDICT_VARIABLE, None)
    else:
        environment[LOCAL_KRDICT_VARIABLE] = str(krdict)
    # The report names Korean text; a Windows console codepage cannot.
    environment["PYTHONIOENCODING"] = "utf-8"

    if headless:
        _apply_headless_qt_platform(environment)
    return environment


def _apply_headless_qt_platform(environment: dict[str, str]) -> None:
    """Name the Qt platform a Linux check that opens no window must use."""

    if sys.platform.startswith("linux"):
        environment[QT_PLATFORM_VARIABLE] = HEADLESS_QT_PLATFORM


def _parse_report(stdout: str) -> dict[str, object]:
    """Read the JSON document the self-check prints, tolerating native noise.

    A frozen process may print loader warnings before Python runs, so the
    report is located rather than assumed to start at byte zero.
    """

    start = stdout.find("{")
    if start >= 0:
        try:
            payload = json.loads(stdout[start:])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload
    return {"ok": False, "stages": [], "stdout": stdout[-4000:]}


def _iter_failures(report: Mapping[str, object]) -> Iterator[str]:
    """Say why the run failed, including when no stage lived to report it."""

    named = False
    stages = report.get("stages")
    if isinstance(stages, list):
        for stage in stages:
            if isinstance(stage, Mapping) and not stage.get("ok"):
                named = True
                yield f"{stage.get('name')}: {stage.get('detail')}"
    if named:
        return

    # Native startup failures kill the process before it prints its report, so
    # the exit status and whatever reached stderr are the whole account.
    yield _describe_exit(report)
    tail = _output_tail(report)
    if tail is not None:
        yield f"last output:\n{tail}"


def _describe_exit(report: Mapping[str, object]) -> str:
    """Say which stage was running and how the process ended, in that order.

    "exited with status 3221225501" names no suspect. The stage the markers
    left open does, and the two together are the whole diagnosis a crashed
    packaging run can offer.
    """

    return f"current_stage: {_current_stage(report)}; exit: {_exit_summary(report)}"


def _current_stage(report: Mapping[str, object]) -> str:
    progress = report.get("progress")
    if isinstance(progress, Mapping):
        stage = progress.get("current_stage")
        if isinstance(stage, str) and stage:
            return stage
    return "unknown"


def _exit_summary(report: Mapping[str, object]) -> str:
    """Name how the process ended, as a signal or fault rather than a number."""

    if report.get("exit_timeout"):
        return "did not exit before the deadline"

    status = report.get("exit_code")
    if isinstance(status, int) and status < 0:
        return _signal_name(-status)
    if isinstance(status, int):
        fatal = _windows_fault(status)
        if fatal is not None:
            return fatal
    return f"status {status}"


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


def _windows_fault(status: int) -> str | None:
    """Name a fatal Windows exception, which is not reported as a signal.

    Windows hands back the NTSTATUS the process died on, unsigned and in the
    range reserved for errors. Anything below that is an ordinary exit code a
    program chose for itself.
    """

    if not 0xC0000000 <= status <= 0xFFFFFFFF:
        return None
    named = WINDOWS_FATAL_STATUS.get(status)
    return f"{named} (0x{status:08X})" if named else f"Windows exception 0x{status:08X}"


def _output_tail(report: Mapping[str, object]) -> str | None:
    """Return the end of what the process said, on whichever stream it used.

    Lines rather than one line: the useful account of a native crash is the
    traceback the fault handler prints, and one line of it says nothing.
    """

    for key in ("stderr", "stdout"):
        text = report.get(key)
        if not isinstance(text, str):
            continue
        # Progress markers are reported on their own; leaving them here would
        # push the fault handler's traceback out of a bounded tail.
        lines = [
            line.rstrip()
            for line in text.splitlines()
            if line.strip() and _marker_payload(line) is None
        ]
        if lines:
            return "\n".join(lines[-OUTPUT_TAIL_LINES:])
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a frozen Hanly bundle's inventory and real provider readiness"
    )
    parser.add_argument(
        "application_directory",
        type=Path,
        nargs="?",
        help=(
            "the built application, e.g. dist/windows/hanly-desktop or "
            "dist/macos/Hanly.app"
        ),
    )
    parser.add_argument(
        "--from-archive",
        type=Path,
        help="published macOS ZIP to unpack and check instead of a built directory",
    )
    parser.add_argument(
        "--reconstruct-into",
        type=Path,
        help="where --from-archive unpacks (default: a temporary directory)",
    )
    parser.add_argument(
        "--from-disk-image",
        type=Path,
        help="reconstruct the application out of the published disk image, and check that",
    )
    parser.add_argument(
        "--against-manifest",
        type=Path,
        help="compare whatever was reconstructed to the manifest the release publishes",
    )
    parser.add_argument(
        "--disk-image",
        type=Path,
        help="published macOS DMG to mount read-only and report on",
    )
    parser.add_argument(
        "--runtime-config",
        type=Path,
        help="runtime configuration to use instead of provisioning one",
    )
    parser.add_argument(
        "--image",
        type=Path,
        help="Korean fixture image the frozen OCR stack must recognize",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="directory to use as the isolated settings profile (default: temporary)",
    )
    parser.add_argument(
        "--model-cache",
        type=Path,
        help=(
            "EasyOCR model directory (the '.EasyOCR/model' one) to copy into "
            "the isolated profile; a packaged build reads its bundled weights "
            "instead and ignores it"
        ),
    )
    parser.add_argument(
        "--krdict",
        type=Path,
        help=(
            "already-built krdict.sqlite3 for the frozen run to install; "
            "without one a clean machine provisions from the release channel "
            "and the check depends on the network"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="seconds to allow the frozen self-check",
    )
    parser.add_argument(
        "--window-only",
        action="store_true",
        help="check that the frozen main window opens, without touching providers",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="check collected dependencies without running the executable",
    )
    parser.add_argument(
        "--expect-version",
        help=(
            "the product version this bundle must report for both packages; "
            "a mismatch or a missing version fails the check"
        ),
    )
    parser.add_argument(
        "--reconstruct-only",
        action="store_true",
        help=(
            "unpack --from-archive and report where the application landed, "
            "without inspecting it; the checks that follow are separate steps "
            "so one of them failing cannot suppress the others"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Check whichever published products this invocation was given."""

    args = _build_parser().parse_args(None if argv is None else list(argv))
    problem = _argument_problem(args)
    if problem is not None:
        print(f"Hanly smoke: {problem}", file=sys.stderr)
        return 2

    output: dict[str, object] = {}
    reconstruction: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.disk_image is not None:
            output["disk_image"] = verify_disk_image(args.disk_image)

        application = args.application_directory
        source = args.from_archive if args.from_archive is not None else args.from_disk_image
        if source is not None:
            destination = args.reconstruct_into
            if destination is None:
                reconstruction = tempfile.TemporaryDirectory(prefix="hanly-reconstruct-")
                destination = Path(reconstruction.name) / "app"
            application = (
                reconstruct_application(source, destination)
                if args.from_archive is not None
                else reconstruct_from_disk_image(source, destination)
            )
            output["reconstructed"] = {
                "archive": Path(source).name,
                "application": str(application),
            }

        if application is not None and args.against_manifest is not None:
            output["manifest"] = compare_to_manifest(application, args.against_manifest)

        if application is None or args.reconstruct_only:
            print(json.dumps(output, indent=2))
            return _unusable_disk_image(output)
        return max(
            _report(args, application, output),
            _unusable_disk_image(output),
            _mismatched_manifest(output),
        )
    finally:
        if reconstruction is not None:
            reconstruction.cleanup()


def _argument_problem(args: argparse.Namespace) -> str | None:
    """Reject an invocation that names no subject, or two of them."""

    named = [
        subject
        for subject in (args.application_directory, args.from_archive, args.from_disk_image)
        if subject is not None
    ]
    if len(named) > 1:
        return "name one application directory, --from-archive, or --from-disk-image"
    subjects = (*named, args.disk_image)
    if all(subject is None for subject in subjects):
        return "name an application directory, --from-archive, or --disk-image"
    if args.reconstruct_only and not named:
        return "--reconstruct-only needs --from-archive or --from-disk-image"
    if args.against_manifest is not None and not named:
        return "--against-manifest needs an application to compare"
    if args.expect_version is not None and (args.inventory_only or args.reconstruct_only):
        # The bundle answers for its own version by running; a check that does
        # not run it would report an identity it never asked for.
        return "--expect-version needs a check that runs the executable"
    return None


def _mismatched_manifest(output: Mapping[str, object]) -> int:
    """Fail on a reconstructed product that is not the build it claims to be.

    A product that unpacks is not evidence. One that unpacks into a tree the
    release does not describe is a product a client would refuse to install,
    discovered here rather than by the first person to update.
    """

    report = output.get("manifest")
    if isinstance(report, Mapping) and report.get("ok") is not True:
        print(
            f"Hanly smoke: what was reconstructed is not the build {report.get('manifest')} "
            f"describes; missing {report.get('missing')}, differing {report.get('differing')}, "
            f"unexpected {report.get('unexpected')}",
            file=sys.stderr,
        )
        return 1
    return 0


def _unusable_disk_image(output: Mapping[str, object]) -> int:
    """Fail on a disk image that mounted without the application inside it.

    Mounting is not the check. A DMG that opens onto the wrong contents is
    exactly the published product a person would download and find empty.
    """

    report = output.get("disk_image")
    if isinstance(report, Mapping) and report.get("ok") is not True:
        print(
            f"Hanly smoke: {report.get('image')} does not contain {report.get('application')}",
            file=sys.stderr,
        )
        return 1
    return 0


def _report(
    args: argparse.Namespace,
    application: Path,
    output: dict[str, object],
) -> int:
    inventory = inspect_bundle(application)
    output["inventory"] = inventory.to_dict()

    if not inventory.ok:
        # ASCII-escaped: the report names Korean, and a Windows console
        # codepage cannot encode it.
        print(json.dumps(output, indent=2))
        print(
            "Hanly smoke: missing bundled dependencies: "
            + ", ".join(inventory.missing),
            file=sys.stderr,
        )
        return 1
    if args.inventory_only:
        print(json.dumps(output, indent=2))
        return 0

    executable = _executable_in(inventory.root)
    if args.window_only:
        report = run_packaged_self_check(
            executable,
            mode="ui",
            profile=args.profile,
            timeout=min(args.timeout, UI_TIMEOUT_SECONDS),
        )
    else:
        report = run_packaged_self_check(
            executable,
            runtime_config=args.runtime_config,
            image=args.image,
            profile=args.profile,
            model_cache=args.model_cache,
            krdict=args.krdict,
            timeout=args.timeout,
        )
    output["self_check"] = report
    identity: dict[str, object] | None = None
    if args.expect_version is not None:
        identity = verify_frozen_identity(report, args.expect_version)
        output["identity"] = identity
    print(json.dumps(output, indent=2))

    if identity is not None and not identity["ok"]:
        for problem in cast(list[str], identity["problems"]):
            print(f"Hanly smoke: {problem}", file=sys.stderr)
        return 1
    if report.get("ok") is True and report.get("exit_code") == 0:
        return 0
    for failure in _iter_failures(report):
        print(f"Hanly smoke: {failure}", file=sys.stderr)
    return 1


def _executable_in(application_directory: Path) -> Path:
    """Find the one program, whether it sits in a onedir tree or a bundle."""

    candidates = (
        application_directory / f"{APPLICATION_STEM}.exe",
        application_directory / APPLICATION_STEM,
        application_directory.joinpath(*_BUNDLE_PROGRAM_PARTS),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no Hanly executable in {application_directory}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APPLICATION_STEM",
    "BUNDLE_NAME",
    "BUNDLE_SIGNATURE",
    "DEFAULT_TIMEOUT_SECONDS",
    "EASYOCR_MODEL_SUBDIRECTORY",
    "EXPECTED_SOURCE_VARIABLE",
    "EASYOCR_PATH_VARIABLES",
    "HEADLESS_QT_PLATFORM",
    "HEADLESS_SELF_CHECK_MODES",
    "HOME_VARIABLES",
    "IDENTITY_PACKAGES",
    "LOCAL_KRDICT_VARIABLE",
    "QT_PLATFORM_VARIABLE",
    "REQUIRED_DATA_FILES",
    "REQUIRED_EXTENSION_STEM",
    "REQUIRED_MODEL_FILES",
    "REQUIRED_PACKAGES",
    "STAGE_COMPLETED",
    "STAGE_MARKER_PREFIX",
    "STAGE_STARTED",
    "TREE_KILL_SECONDS",
    "UI_TIMEOUT_SECONDS",
    "WINDOWS_FATAL_STATUS",
    "BundleInventory",
    "inspect_bundle",
    "isolated_environment",
    "main",
    "read_progress",
    "reconstruct_application",
    "run_packaged_self_check",
    "verify_disk_image",
    "verify_frozen_identity",
    "verify_source_identity",
]
