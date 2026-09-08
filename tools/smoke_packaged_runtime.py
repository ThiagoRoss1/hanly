"""Prove a frozen Hanly bundle can look a word up with only what it ships.

Two checks, in order. The inventory says whether the required runtime
dependencies were collected at all; the self-check runs the bundle's own
executable and makes it construct the real providers. Inventory alone is not
evidence -- a present file that cannot be imported still leaves the desktop
unable to become ready.

Nothing here may fall back to the repository, the developer virtual
environment, or developer model caches: the run uses a temporary profile and a
working directory outside the checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Packages the desktop imports by name at runtime. Their absence is exactly
#: the defect that shipped in v0.1.0: readiness waits on morphology forever.
REQUIRED_PACKAGES = ("kiwipiepy", "kiwipiepy_model", "easyocr")

#: Kiwi's analyzer is a native extension module beside the package.
REQUIRED_EXTENSION_STEM = "_kiwipiepy"

#: Model data Kiwi loads from ``kiwipiepy_model``. Sampled rather than
#: exhaustive: these three are enough to catch a data-free collection.
REQUIRED_MODEL_FILES = ("sj.morph", "default.dict", "combiningRule.txt")

#: The two files a frozen build cannot obtain for itself: the trust store its
#: HTTPS verification needs, and the weights its OCR loads with downloading off.
REQUIRED_DATA_FILES = (
    "certifi/cacert.pem",
    "hanly_app/assets/easyocr_models/craft_mlt_25k.pth",
    "hanly_app/assets/easyocr_models/korean_g2.pth",
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

#: A cold frozen start imports torch and warms two models.
DEFAULT_TIMEOUT_SECONDS = 900

#: Opening the window imports Qt WebEngine and starts Chromium; it constructs
#: no provider, so it is bounded far more tightly than the worker. It is not
#: bounded tightly: the first launch of a freshly frozen bundle waits on the
#: platform reading tens of thousands of new files, which cost two 300 s
#: timeouts here before the same check ran in under a second warm.
UI_TIMEOUT_SECONDS = 600

#: Where EasyOCR looks for its recognition models, in the order it asks. All
#: of them are redirected into the temporary profile, so a developer cache can
#: never be what makes a frozen run succeed.
EASYOCR_PATH_VARIABLES = ("EASYOCR_MODULE_PATH", "MODULE_PATH")

#: EasyOCR appends this to whichever module path it resolved, so a seeded
#: cache has to land there rather than beside it.
EASYOCR_MODEL_SUBDIRECTORY = "model"

#: Redirected so nothing resolves ``~`` back to the developer's account.
HOME_VARIABLES = ("HOME", "USERPROFILE", "XDG_CACHE_HOME")


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
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run one of the bundle's own ``--self-check`` modes and parse its report."""

    command = [str(Path(executable).resolve()), "--self-check", mode]
    if runtime_config is not None:
        command.extend(["--runtime-config", str(Path(runtime_config).resolve())])
    if image is not None:
        command.extend(["--self-check-image", str(Path(image).resolve())])

    with _ProfileContext(profile, model_cache=model_cache) as (
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
            try:
                status = subprocess.run(
                    command,
                    stdout=out,
                    stderr=err,
                    timeout=timeout,
                    env=environment,
                    cwd=working_directory,
                ).returncode
            except subprocess.TimeoutExpired:
                # The report is written before the process winds Qt down, so a
                # run that stops exiting still says whether the check itself
                # passed. Reporting both keeps "the window is broken" separate
                # from "the window worked and the process did not leave".
                timed_out = True
        stdout = output.read_text(encoding="utf-8", errors="replace")
        stderr = errors.read_text(encoding="utf-8", errors="replace")

    report = _parse_report(stdout)
    report["exit_code"] = status
    report["exit_timeout"] = timed_out
    report["stderr"] = stderr[-4000:]
    return report


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
    """

    def __init__(
        self,
        profile: str | Path | None,
        *,
        model_cache: str | Path | None = None,
    ) -> None:
        self._profile = None if profile is None else Path(profile).resolve()
        self._model_cache = None if model_cache is None else Path(model_cache).resolve()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> tuple[dict[str, str], Path]:
        if self._profile is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="hanly-smoke-")
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

        return isolated_environment(os.environ, settings, home, models), work

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
) -> dict[str, str]:
    """Build the child environment, with every developer path redirected."""

    environment = dict(inherited)
    environment["LOCALAPPDATA"] = str(settings)
    environment["XDG_CONFIG_HOME"] = str(settings)
    for variable in HOME_VARIABLES:
        environment[variable] = str(home)
    for variable in EASYOCR_PATH_VARIABLES:
        environment[variable] = str(models)
    environment.pop("HANLY_KRDICT_DB", None)
    # The report names Korean text; a Windows console codepage cannot.
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


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
    stages = report.get("stages")
    if not isinstance(stages, list):
        return
    for stage in stages:
        if isinstance(stage, Mapping) and not stage.get("ok"):
            yield f"{stage.get('name')}: {stage.get('detail')}"


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Report the bundle's inventory and, unless skipped, its self-check."""

    args = _build_parser().parse_args(None if argv is None else list(argv))
    if (args.application_directory is None) == (args.from_archive is None):
        print(
            "Hanly smoke: name either an application directory or --from-archive",
            file=sys.stderr,
        )
        return 2

    output: dict[str, object] = {}
    reconstruction: tempfile.TemporaryDirectory[str] | None = None
    try:
        application = args.application_directory
        if args.from_archive is not None:
            if args.reconstruct_into is None:
                reconstruction = tempfile.TemporaryDirectory(prefix="hanly-reconstruct-")
                destination = Path(reconstruction.name) / "app"
            else:
                destination = args.reconstruct_into
            application = reconstruct_application(args.from_archive, destination)
            output["reconstructed"] = {
                "archive": Path(args.from_archive).name,
                "application": str(application),
            }
        if args.disk_image is not None:
            output["disk_image"] = verify_disk_image(args.disk_image)

        return _report(args, application, output)
    finally:
        if reconstruction is not None:
            reconstruction.cleanup()


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
            timeout=args.timeout,
        )
    output["self_check"] = report
    print(json.dumps(output, indent=2))

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
    "EASYOCR_PATH_VARIABLES",
    "HOME_VARIABLES",
    "REQUIRED_DATA_FILES",
    "REQUIRED_EXTENSION_STEM",
    "REQUIRED_MODEL_FILES",
    "REQUIRED_PACKAGES",
    "UI_TIMEOUT_SECONDS",
    "BundleInventory",
    "inspect_bundle",
    "isolated_environment",
    "main",
    "reconstruct_application",
    "run_packaged_self_check",
    "verify_disk_image",
]
