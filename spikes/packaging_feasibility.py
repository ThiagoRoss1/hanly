"""Local-only Windows packaging feasibility evidence.

This is an executable observation harness, not a packaging command, a release
builder, or a pytest test.  It deliberately uses only the Python standard
library so it can report what is available before optional packaging work is
started.  Model construction is attempted only when both named local model
directories contain the required inference files; otherwise it is skipped to
avoid a library fallback that could download weights.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import importlib.util
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

EXPECTED_MODELS = (
    "PP-OCRv5_mobile_det",
    "korean_PP-OCRv5_mobile_rec",
)
REQUIRED_MODEL_FILES = ("inference.yml", "inference.pdiparams")
# A cold PaddleOCR import on Windows exceeds 30s on first run (warm ~13s).
# Too tight a bound records a false "import unavailable" and silently skips the
# model-loading evidence this spike exists to capture.
IMPORT_TIMEOUT_SECONDS = 180.0
MODEL_ROOT_ENV_VARS = (
    "PADDLE_PDX_LOCAL_DIR",
    "PADDLE_HOME",
    "PADDLEOCR_HOME",
)


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.3f}s"


def _one_line(value: str) -> str:
    return " ".join(value.strip().splitlines())


def _display_command(command: Iterable[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def _run_command(command: list[str], timeout: float = 20.0) -> None:
    """Run a version probe only; never invoke install/build/download actions."""

    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"command={_display_command(command)} exit=ERROR elapsed={_elapsed(started)} "
            f"error={type(exc).__name__}: {_one_line(str(exc))}"
        )
        return

    stdout = _one_line(result.stdout)
    stderr = _one_line(result.stderr)
    print(
        f"command={_display_command(command)} exit={result.returncode} "
        f"elapsed={_elapsed(started)} stdout={stdout!r} stderr={stderr!r}"
    )


def _probe_distribution(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "UNAVAILABLE"
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        return f"ERROR:{type(exc).__name__}:{_one_line(str(exc))}"


def _probe_import(module_name: str) -> dict[str, str]:
    started = time.perf_counter()
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        return {
            "spec": "ERROR",
            "import": "UNEXERCISED",
            "elapsed": _elapsed(started),
            "origin": "",
            "error": f"{type(exc).__name__}: {_one_line(str(exc))}",
        }

    if spec is None:
        return {
            "spec": "MISSING",
            "import": "UNEXERCISED",
            "elapsed": _elapsed(started),
            "origin": "",
            "error": "",
        }

    # Keep each native import in a fresh interpreter.  Paddle and its
    # transitive torch/modelscope dependencies can affect DLL state in-process,
    # which is itself probed separately below as an ordering constraint.
    command = [
        sys.executable,
        "-c",
        "import importlib; importlib.import_module(" + repr(module_name) + "); print('import_ok')",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "spec": "FOUND",
            "import": "ERROR",
            "elapsed": _elapsed(started),
            "origin": str(spec.origin or ""),
            "error": f"{type(exc).__name__}: {_one_line(str(exc))}",
        }

    if result.returncode != 0:
        return {
            "spec": "FOUND",
            "import": "ERROR",
            "elapsed": _elapsed(started),
            "origin": str(spec.origin or ""),
            "error": _one_line(result.stderr or result.stdout),
        }

    return {
        "spec": "FOUND",
        "import": "OK",
        "elapsed": _elapsed(started),
        "origin": str(spec.origin or ""),
        "error": "",
    }


def _probe_import_order(label: str, statement: str) -> None:
    """Record native-DLL behavior for an order a packager may encounter."""

    command = [sys.executable, "-c", statement]
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"import_order={label} exit=ERROR elapsed={_elapsed(started)} "
            f"error={type(exc).__name__}: {_one_line(str(exc))}"
        )
        return

    output = _one_line(result.stderr or result.stdout)
    if result.returncode != 0:
        # The final native-loader line carries the actionable constraint; the
        # full traceback is intentionally not repeated in the durable report.
        output = next(
            (
                line.strip()
                for line in reversed((result.stderr or result.stdout).splitlines())
                if line.strip()
            ),
            "",
        )
    print(
        f"import_order={label} exit={result.returncode} elapsed={_elapsed(started)} "
        f"output={output!r}"
    )


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []

    def add(path: Path) -> None:
        expanded = path.expanduser()
        if expanded not in roots:
            roots.append(expanded)

    for variable in MODEL_ROOT_ENV_VARS:
        value = os.environ.get(variable)
        if value:
            add(Path(value))

    home = Path.home()
    add(home / ".paddlex")
    add(home / ".paddleocr")
    add(home / "AppData" / "Local" / "paddlex")
    add(home / "AppData" / "Local" / "PaddleX")
    return roots


def _model_directory(model_name: str, roots: Iterable[Path]) -> Path | None:
    for root in roots:
        candidates = (root / model_name, root / "official_models" / model_name)
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
    return None


def _model_inventory(model_name: str, roots: Iterable[Path]) -> dict[str, object]:
    directory = _model_directory(model_name, roots)
    if directory is None:
        return {
            "directory": "MISSING",
            "files": 0,
            "bytes": 0,
            "required": (),
            "complete": False,
        }

    try:
        direct_files = [item for item in directory.iterdir() if item.is_file()]
    except OSError as exc:
        return {
            "directory": str(directory),
            "files": "ERROR",
            "bytes": "ERROR",
            "required": (),
            "complete": False,
            "error": f"{type(exc).__name__}: {_one_line(str(exc))}",
        }

    names = {item.name for item in direct_files}
    required = tuple(name for name in REQUIRED_MODEL_FILES if name in names)
    byte_count: int | str
    try:
        byte_count = sum(item.stat().st_size for item in direct_files)
    except OSError as exc:
        byte_count = "ERROR"
        error = f"{type(exc).__name__}: {_one_line(str(exc))}"
    else:
        error = ""

    return {
        "directory": str(directory),
        "files": len(direct_files),
        "bytes": byte_count,
        "required": required,
        "complete": len(required) == len(REQUIRED_MODEL_FILES),
        "error": error,
    }


def _probe_model_loading(
    platform_name: str,
    imports: dict[str, dict[str, str]],
    inventories: dict[str, dict[str, object]],
) -> None:
    if platform_name != "Windows":
        print("model_loading=status=UNEXERCISED reason=Windows-only spike")
        return

    paddleocr_import = imports["paddleocr"]
    if paddleocr_import["import"] != "OK":
        print(
            "model_loading=status=SKIPPED_IMPORT_UNAVAILABLE "
            f"reason={paddleocr_import['import']}:{paddleocr_import['error']}"
        )
        return

    missing = [name for name, inventory in inventories.items() if not inventory["complete"]]
    if missing:
        print(
            "model_loading=status=SKIPPED_NO_COMPLETE_LOCAL_MODELS "
            f"missing_or_incomplete={','.join(missing)} "
            "reason=explicit local model dirs are required; no fallback/download is allowed"
        )
        return

    # Explicit directories plus this flag make the experiment local-only. The
    # model directories were checked above before PaddleOCR is constructed.
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    det_dir = str(inventories["PP-OCRv5_mobile_det"]["directory"])
    rec_dir = str(inventories["korean_PP-OCRv5_mobile_rec"]["directory"])
    started = time.perf_counter()
    captured_stdout: list[str] = []
    captured_stderr: list[str] = []
    try:
        with contextlib.redirect_stdout(_ListWriter(captured_stdout)):
            with contextlib.redirect_stderr(_ListWriter(captured_stderr)):
                paddleocr_module = importlib.import_module("paddleocr")
                paddleocr_module.PaddleOCR(
                    # The installed PaddleOCR defaults to a newer model family
                    # than the locally cached assets, so the name must be given
                    # explicitly alongside the directory or construction fails
                    # with a model-name mismatch.
                    text_detection_model_name=EXPECTED_MODELS[0],
                    text_detection_model_dir=det_dir,
                    text_recognition_model_name=EXPECTED_MODELS[1],
                    text_recognition_model_dir=rec_dir,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
    except Exception as exc:  # pragma: no cover - depends on local native stack
        print(
            "model_loading=status=ERROR "
            f"elapsed={_elapsed(started)} error={type(exc).__name__}: {_one_line(str(exc))} "
            f"captured_stdout={_one_line(''.join(captured_stdout))!r} "
            f"captured_stderr={_one_line(''.join(captured_stderr))!r}"
        )
        return

    print(
        "model_loading=status=OK "
        f"elapsed={_elapsed(started)} mode=explicit-local-model-dirs "
        f"captured_stdout={_one_line(''.join(captured_stdout))!r} "
        f"captured_stderr={_one_line(''.join(captured_stderr))!r}"
    )


class _ListWriter:
    """Small text sink for optional-library startup diagnostics."""

    def __init__(self, buffer: list[str]) -> None:
        self.buffer = buffer

    def write(self, value: str) -> int:
        self.buffer.append(value)
        return len(value)

    def flush(self) -> None:
        return None


def _packaged_probe() -> int:
    """Exercise a bounded frozen startup with Paddle only.

    PaddleOCR is intentionally not bundled by this smoke target: its model
    orchestration and optional backends make the artifact unbounded for an
    evidence spike.  The regular harness still probes PaddleOCR import and
    gates model construction on complete local assets.
    """

    print("PACKAGED STARTUP PROBE")
    print(
        f"platform={platform.system()} python={platform.python_version()} "
        f"executable={sys.executable}"
    )
    print(f"frozen={getattr(sys, 'frozen', False)}")
    started = time.perf_counter()
    try:
        paddle = importlib.import_module("paddle")
    except Exception as exc:  # pragma: no cover - depends on frozen native bundle
        print(
            "paddle_import=status=ERROR "
            f"elapsed={_elapsed(started)} error={type(exc).__name__}: {_one_line(str(exc))}"
        )
        print("paddleocr_import=status=NOT_ATTEMPTED reason=bounded-Paddle-only-probe")
        print("model_loading=status=NOT_ATTEMPTED reason=probe does not bundle or download models")
        return 1

    version = getattr(paddle, "__version__", "UNKNOWN")
    print(f"paddle_import=status=OK version={version} elapsed={_elapsed(started)}")
    print("paddleocr_import=status=NOT_ATTEMPTED reason=bounded-Paddle-only-probe")
    print("model_loading=status=NOT_ATTEMPTED reason=probe does not bundle or download models")
    return 0


def _packaged_ocr_probe() -> int:
    """Exercise frozen Paddle/PaddleOCR imports with a no-download model gate."""

    print("PACKAGED PADDLEOCR STARTUP PROBE")
    print(
        f"platform={platform.system()} python={platform.python_version()} "
        f"executable={sys.executable}"
    )
    print(f"frozen={getattr(sys, 'frozen', False)}")

    started = time.perf_counter()
    try:
        paddle = importlib.import_module("paddle")
    except Exception as exc:  # pragma: no cover - depends on frozen native bundle
        print(
            "paddle_import=status=ERROR "
            f"elapsed={_elapsed(started)} error={type(exc).__name__}: {_one_line(str(exc))}"
        )
        print("paddleocr_import=status=NOT_ATTEMPTED reason=paddle_import_failed")
        print("model_loading=status=NOT_ATTEMPTED reason=imports_failed_no_model_path_used")
        return 1

    print(
        f"paddle_import=status=OK version={getattr(paddle, '__version__', 'UNKNOWN')} "
        f"elapsed={_elapsed(started)}"
    )
    started = time.perf_counter()
    try:
        paddleocr_module = importlib.import_module("paddleocr")
    except Exception as exc:  # pragma: no cover - depends on frozen native bundle
        print(
            "paddleocr_import=status=ERROR "
            f"elapsed={_elapsed(started)} error={type(exc).__name__}: {_one_line(str(exc))}"
        )
        print("model_loading=status=NOT_ATTEMPTED reason=imports_failed_no_model_path_used")
        return 1

    print(
        "paddleocr_import=status=OK "
        f"version={getattr(paddleocr_module, '__version__', 'UNKNOWN')} "
        f"elapsed={_elapsed(started)}"
    )

    roots = _candidate_roots()
    inventories = {
        model_name: _model_inventory(model_name, roots) for model_name in EXPECTED_MODELS
    }
    missing = [name for name, inventory in inventories.items() if not inventory["complete"]]
    if missing:
        print(
            "model_loading=status=SKIPPED_NO_COMPLETE_LOCAL_MODELS "
            f"missing_or_incomplete={','.join(missing)} "
            "reason=explicit local dirs required; no fallback/download allowed"
        )
        return 0

    # This branch is reachable only with both explicit local model directories
    # complete. It never asks PaddleOCR to resolve a model by name.
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    det_dir = str(inventories["PP-OCRv5_mobile_det"]["directory"])
    rec_dir = str(inventories["korean_PP-OCRv5_mobile_rec"]["directory"])
    started = time.perf_counter()
    try:
        paddleocr_module.PaddleOCR(
            text_detection_model_dir=det_dir,
            text_recognition_model_dir=rec_dir,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except Exception as exc:  # pragma: no cover - depends on local native stack
        print(
            "model_loading=status=ERROR "
            f"elapsed={_elapsed(started)} error={type(exc).__name__}: {_one_line(str(exc))}"
        )
        return 1

    print(f"model_loading=status=OK elapsed={_elapsed(started)} mode=explicit-local-model-dirs")
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--packaged-probe":
        return _packaged_probe()
    if len(sys.argv) == 2 and sys.argv[1] == "--packaged-ocr-probe":
        return _packaged_ocr_probe()
    if len(sys.argv) > 1:
        print("usage=packaging_feasibility.py [--packaged-probe|--packaged-ocr-probe]")
        return 2

    platform_name = platform.system()
    print("PACKAGING FEASIBILITY SPIKE")
    print(
        "scope=local-only observation; harness does not create packaging artifacts, "
        "install, download, or run CI"
    )
    print(
        f"platform={platform_name} release={platform.release()} "
        f"python={platform.python_version()} executable={sys.executable}"
    )
    if platform_name == "Windows":
        print("platform_scope=Windows exercised")
    else:
        print("platform_scope=Windows-only; macOS/Linux unexercised")

    print("[dependencies]")
    distributions = (
        "paddleocr",
        "paddlepaddle",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "build",
        "setuptools",
    )
    for distribution in distributions:
        print(f"distribution={distribution} version={_probe_distribution(distribution)}")

    print("[imports]")
    imports: dict[str, dict[str, str]] = {}
    for module_name in ("paddle", "paddleocr", "PyInstaller", "build"):
        result = _probe_import(module_name)
        imports[module_name] = result
        print(
            f"module={module_name} spec={result['spec']} import={result['import']} "
            f"elapsed={result['elapsed']} origin={result['origin']!r} error={result['error']!r}"
        )
    _probe_import_order(
        "paddleocr_then_paddle",
        "import paddleocr; import paddle; print('import_order_ok')",
    )
    _probe_import_order(
        "paddle_then_paddleocr",
        "import paddle; import paddleocr; print('import_order_ok')",
    )

    print("[packaging_tools]")
    print("authoritative_packaging_tool=.venv\\Scripts\\python.exe -m PyInstaller")
    _run_command([sys.executable, "-m", "PyInstaller", "--version"])
    _run_command([sys.executable, "-m", "build", "--version"])
    _run_command([sys.executable, "-m", "pip", "--version"])
    print("artifact_creation=NOT_ATTEMPTED reason=release artifacts are out of spike scope")

    print("[model_cache]")
    roots = _candidate_roots()
    existing_roots = [str(root) for root in roots if root.is_dir()]
    print(f"candidate_roots={roots}")
    print(f"existing_roots={existing_roots}")
    inventories: dict[str, dict[str, object]] = {}
    for model_name in EXPECTED_MODELS:
        inventory = _model_inventory(model_name, roots)
        inventories[model_name] = inventory
        print(
            f"model={model_name} directory={inventory['directory']!r} files={inventory['files']} "
            f"bytes={inventory['bytes']} required={inventory['required']} "
            f"complete={inventory['complete']} error={inventory.get('error', '')!r}"
        )

    print("[startup_and_model_loading]")
    print(
        "startup_constraint=module imports are measurable; PaddleOCR construction is "
        "guarded by complete local model assets"
    )
    _probe_model_loading(platform_name, imports, inventories)
    print("network_and_install_actions=NONE (version probes only; no pip/install/download/build)")
    print("result=EVIDENCE_CAPTURED_WITH_LIMITATIONS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
