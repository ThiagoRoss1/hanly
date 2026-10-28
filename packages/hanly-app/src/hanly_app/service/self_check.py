"""Qt-free packaged-runtime checks used by the native Hanly host."""

from __future__ import annotations

import faulthandler
import importlib.metadata
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from hanly_app.paths import default_runtime_config_path, discover_runtime_config
from hanly_app.updates.build_identity import read_build_stamp

SELF_CHECK_MODES = ("inventory", "ocr", "worker", "ui")
MORPHOLOGY_PROBE = "한국어"
DICTIONARY_PROBE = "한국어"
_REQUIRED_DATA_FILES = (
    "certifi/cacert.pem",
    "easyocr/character/ko_char.txt",
    "hanly_app/assets/easyocr_models/craft_mlt_25k.pth",
    "hanly_app/assets/easyocr_models/korean_g2.pth",
)
STAGE_MARKER_PREFIX = "hanly-self-check:"
STAGE_STARTED = "stage_started"
STAGE_COMPLETED = "stage_completed"


def run_service_self_check(
    mode: str,
    image: str | Path | None = None,
    *,
    runtime_config: str | Path | None = None,
) -> dict[str, object]:
    """Return a bounded JSON-shaped report for one packaged service check.

    ``inventory`` and ``ui`` inspect files and build identity only. The native
    host owns the actual UI readiness test. ``worker`` exercises the language
    providers, while ``ocr`` also requires a local image and exercises the
    configured recognizer without returning recognized text.
    """

    _enable_fatal_traceback()
    if mode not in SELF_CHECK_MODES:
        raise ValueError(f"unsupported self-check mode: {mode!r}")

    report: dict[str, object] = {
        "mode": mode,
        "ok": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "versions": _versions(),
        "stages": [],
    }
    stages = report["stages"]
    assert isinstance(stages, list)

    _stage(stages, "inventory", _inventory)
    if mode in {"inventory", "ui"}:
        report["ok"] = all(stage["ok"] for stage in stages)
        return report

    selected_config = _stage(
        stages,
        "runtime configuration",
        lambda: _runtime_config_path(runtime_config),
    )
    if selected_config is None:
        report["ok"] = False
        return report
    runtime = _stage(
        stages,
        "runtime",
        lambda: _load_runtime(selected_config),
        success_detail="runtime configuration loaded",
    )
    if runtime is None:
        report["ok"] = False
        return report

    worker: Any | None = _stage(
        stages,
        "lookup worker",
        lambda: runtime.create_worker_factory()(),
        success_detail="providers constructed and warmed",
    )
    if worker is None:
        report["ok"] = False
        return report

    try:
        result = _stage(
            stages,
            "dictionary",
            lambda: _lookup_selection(worker),
            success_detail="dictionary lookup completed",
        )
        if result is not None:
            analyses = result.context.analyses if result.context is not None else ()
            _record(
                stages,
                "morphology",
                bool(analyses),
                f"{len(analyses)} normalized analyses",
            )
            _record(
                stages,
                "dictionary",
                bool(result.entries),
                f"{len(result.entries)} matching entries",
                replace_last=True,
            )
        if mode == "ocr" or image is not None:
            if image is None:
                _record(stages, "ocr", False, "a local image is required")
            else:
                _stage(
                    stages,
                    "ocr",
                    lambda: _recognize(worker, Path(image)),
                    success_detail="OCR recognized text in the supplied image",
                )
    finally:
        _stage(stages, "worker close", worker.close, success_detail="providers closed")

    report["ok"] = all(stage["ok"] for stage in stages)
    return report


def _inventory() -> str:
    """Check packaged data and build identity without constructing providers."""

    if bool(getattr(sys, "frozen", False)):
        root = _runtime_root()
        missing = [name for name in _REQUIRED_DATA_FILES if not (root / name).is_file()]
    else:
        missing = _source_inventory_gaps()
    if missing:
        raise RuntimeError("missing packaged data: " + ", ".join(missing))

    stamp = read_build_stamp()
    if bool(getattr(sys, "frozen", False)) and stamp is None:
        raise RuntimeError("packaged build identity is missing or invalid")
    return "build identity and required service data are present"


def _source_inventory_gaps() -> list[str]:
    """Inspect source-installed dependencies without importing providers."""

    from importlib.util import find_spec

    gaps: list[str] = []
    package_specs: dict[str, Any] = {}
    for name in ("certifi", "easyocr", "torch", "kiwipiepy", "kiwipiepy_model"):
        try:
            spec = find_spec(name)
            if spec is None:
                gaps.append(name)
            else:
                package_specs[name] = spec
        except (ImportError, ValueError):
            gaps.append(name)

    app_root = Path(__file__).resolve().parents[1]
    for required_file in _REQUIRED_DATA_FILES[1:]:
        package, _, relative = required_file.partition("/")
        if package == "hanly_app":
            if not (app_root / relative).is_file():
                gaps.append(relative)
            continue

        roots = _package_data_roots(package_specs.get(package))
        if not any((root / relative).is_file() for root in roots):
            gaps.append(required_file)
    return gaps


def _package_data_roots(spec: Any) -> tuple[Path, ...]:
    """Return source-package directories from a module spec without importing it."""

    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        return tuple(Path(location) for location in locations)

    origin = getattr(spec, "origin", None)
    if isinstance(origin, str) and origin not in {"built-in", "frozen"}:
        return (Path(origin).parent,)
    return ()


def _runtime_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if isinstance(frozen_root, str):
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def _versions() -> dict[str, str]:
    """Collect product and lookup dependency versions, excluding old UI stacks."""

    versions = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "frozen": str(bool(getattr(sys, "frozen", False))),
    }
    for name in ("hanly", "hanly-app", "easyocr", "torch", "kiwipiepy"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    stamp = read_build_stamp()
    if stamp is not None:
        versions["build_id"] = stamp.build_id
        versions["source_commit"] = stamp.source_commit
        versions["product_version"] = stamp.version
    return versions


def _runtime_config_path(path: str | Path | None) -> Path:
    if path is not None:
        candidate = Path(path).expanduser().resolve()
    else:
        candidate = discover_runtime_config() or default_runtime_config_path()
    if not candidate.is_file():
        raise FileNotFoundError("runtime configuration is not available")
    return candidate


def _load_runtime(path: Path) -> Any:
    from hanly_app.runtime import load_runtime

    return load_runtime(path)


def _lookup_selection(worker: Any) -> Any:
    from hanly import Point, TextSelection

    from hanly_app.lookup.controller import LookupRequest

    result = worker(
        LookupRequest(
            request_id=1,
            image=None,
            target=Point(0, 0),
            selection=TextSelection(DICTIONARY_PROBE, source="self-check"),
        )
    )
    if not result.entries:
        raise RuntimeError(f"dictionary has no entry for {DICTIONARY_PROBE}")
    return result


def _recognize(worker: Any, image_path: Path) -> str:
    from hanly import PixelFormat, Point, ROIImage
    from PIL import Image

    from hanly_app.lookup.controller import LookupRequest

    resolved = image_path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError("self-check image is not available")
    with Image.open(resolved) as source:
        rgb = source.convert("RGB")
        image = ROIImage(
            width=rgb.width,
            height=rgb.height,
            pixel_format=PixelFormat.RGB_888,
            data=rgb.tobytes(),
        )

    result = worker(
        LookupRequest(request_id=2, image=image, target=Point(0.5, 0.5))
    )
    recognized = result.context.ocr_results if result.context is not None else ()
    if not recognized:
        raise RuntimeError("OCR recognized no text in the self-check image")
    # Recognized content and file names stay out of reports and logs.
    return f"OCR returned {len(recognized)} regions"


def _stage(
    stages: list[dict[str, object]],
    name: str,
    operation: Any,
    *,
    success_detail: str = "completed",
) -> Any | None:
    _emit_marker(STAGE_STARTED, name)
    started = perf_counter()
    try:
        value = operation()
    except Exception as error:
        _record(stages, name, False, f"{type(error).__name__}: {error}", started=started)
        _emit_marker(STAGE_COMPLETED, name, ok=False)
        return None
    _record(stages, name, True, success_detail, started=started)
    _emit_marker(STAGE_COMPLETED, name, ok=True)
    return value


def _enable_fatal_traceback() -> None:
    """Leave a useful Python frame when a native provider aborts the child."""

    try:
        faulthandler.enable()
    except (OSError, RuntimeError, ValueError):
        return


def _emit_marker(event: str, name: str, **fields: object) -> None:
    payload = {"event": event, "stage": name, **fields}
    try:
        print(f"{STAGE_MARKER_PREFIX} {json.dumps(payload)}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _record(
    stages: list[dict[str, object]],
    name: str,
    ok: bool,
    detail: str,
    *,
    started: float | None = None,
    replace_last: bool = False,
) -> None:
    stage = {
        "name": name,
        "ok": ok,
        "detail": detail[:1000],
        "duration_ms": 0.0 if started is None else round((perf_counter() - started) * 1000, 1),
    }
    if replace_last and stages and stages[-1]["name"] == name:
        stages[-1] = stage
    else:
        stages.append(stage)


__all__ = [
    "SELF_CHECK_MODES",
    "STAGE_COMPLETED",
    "STAGE_MARKER_PREFIX",
    "STAGE_STARTED",
    "run_service_self_check",
]
