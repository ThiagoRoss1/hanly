"""Real-process proof that the lookup engine lives outside the shell.

The unit tests run the child's own code on a thread, which covers the
transport, cancellation, and generation handling but not the boundary itself.
This one spawns the real child from a real shell process, reads a Korean
fixture through EasyOCR, Kiwi, and KRDICT, and asserts that the process which
keeps running never imported any of them -- and that retiring the engine
actually takes the child with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest

from tests.hanly_fixtures.process_probe import PROCESS_ROWS_PROGRAM

#: What the shell must never load. Memory a library does not return can only
#: be returned by the process that holds it exiting.
HEAVY_MODULES = ("easyocr", "torch", "kiwipiepy")

MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")

_CHILD_TIMEOUT_SECONDS = 420

_CHILD_PROGRAM = '''
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

from hanly import PixelFormat, Point, ROIImage
from hanly.easyocr_provider import EasyOCRConfig
from hanly_app.lookup_controller import LookupRequest
from hanly_app.lookup_process import LookupEngine, LookupSettings

REPORT_PREFIX = "SPAWN_REPORT "
HEAVY_MODULES = ("easyocr", "torch", "kiwipiepy")


def owned_children():
    """Processes this one still owns, less the ones that are not the engine.

    The ``ps`` doing the asking is itself a child, and multiprocessing's
    resource tracker lives for as long as this process does by design.
    """

    rows = process_rows()
    mine = os.getpid()
    found = []
    for line in rows:
        parts = line.split(None, 2)
        if len(parts) < 3 or int(parts[1]) != mine:
            continue
        if "resource_tracker" in parts[2] or "ps -axo" in parts[2]:
            continue
        found.append(int(parts[0]))
    return found


def settled_children():
    """Wait a bounded time for an exit, then report what is actually left."""

    import time

    for _ in range(40):
        remaining = owned_children()
        if not remaining:
            return remaining
        time.sleep(0.25)
    return owned_children()


def roi(path):
    with Image.open(path) as source:
        rgb = source.convert("RGB")
        return ROIImage(
            width=rgb.width,
            height=rgb.height,
            pixel_format=PixelFormat.RGB_888,
            data=rgb.tobytes(),
        )


def main(krdict, models, fixture):
    image = roi(fixture)
    engine = LookupEngine(
        LookupSettings(
            krdict_path=Path(krdict),
            easyocr=EasyOCRConfig(
                languages=("ko",),
                model_storage_directory=models,
                download_enabled=False,
            ),
        )
    )
    report = {"errors": []}
    try:
        engine.attach()
        report["state_after_attach"] = engine.state
        result = engine(
            LookupRequest(1, image, Point(image.width / 2, image.height / 2))
        )
        report["status"] = result.status.value
        report["headwords"] = [entry.headword for entry in result.entries]
        report["generation"] = engine.generation

        report["children_while_ready"] = owned_children()

        engine.retire()
        report["state_after_retire"] = engine.state
        # The memory a library does not give back is only returned by the
        # process holding it exiting, so the state is not the property.
        report["children_after_retire"] = settled_children()

        # A retired engine is still usable; the next request wakes a new child.
        again = engine(
            LookupRequest(2, image, Point(image.width / 2, image.height / 2))
        )
        report["status_after_wake"] = again.status.value
        report["generation_after_wake"] = engine.generation
    except BaseException as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        engine.close()
        report["state_after_close"] = engine.state
        report["children_after_close"] = settled_children()

    report["heavy_modules_in_the_shell"] = [
        name for name in HEAVY_MODULES if name in sys.modules
    ]
    print(REPORT_PREFIX + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
'''


def _existing_models() -> Path | None:
    candidates = [
        Path(__file__).parents[2]
        / "packages"
        / "hanly-app"
        / "src"
        / "hanly_app"
        / "assets"
        / "easyocr_models",
        Path.home() / ".EasyOCR" / "model",
    ]
    return next(
        (
            directory
            for directory in candidates
            if all((directory / name).is_file() for name in MODEL_FILES)
        ),
        None,
    )


def _existing_dictionary() -> Path | None:
    configured = os.environ.get("HANLY_KRDICT_DB")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3")
    return next((path for path in candidates if path.is_file()), None)


def _requirements() -> tuple[Path, Path, Path]:
    # Presence, not an import: loading the runtime to decide whether to run
    # would put the very libraries this test says the shell never imports into
    # the process running it.
    missing = [name for name in ("easyocr", "kiwipiepy", "PIL") if find_spec(name) is None]
    if missing:
        pytest.skip(f"the lookup runtime is not installed: {', '.join(missing)}")
    dictionary = _existing_dictionary()
    if dictionary is None:
        pytest.skip("no built KRDICT database; see data/README.md")
    models = _existing_models()
    if models is None:
        pytest.skip("no prepared EasyOCR weights; see tools/prepare_easyocr_models.py")
    fixture = Path(__file__).parents[1] / "hanly_fixtures" / "assets" / "korean_reading_roi.png"
    if not fixture.is_file():
        pytest.skip("the Korean reading fixture is not available")
    return dictionary, models, fixture


def test_a_real_korean_lookup_runs_in_a_child_the_shell_can_retire(tmp_path: Path) -> None:
    dictionary, models, fixture = _requirements()

    program = tmp_path / "spawn_child.py"
    program.write_text(PROCESS_ROWS_PROGRAM + _CHILD_PROGRAM, encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(program), str(dictionary), str(models), str(fixture)],
        capture_output=True,
        # The report carries Korean headwords. Without this the child writes
        # them in the console codepage, which on a Windows shell cannot encode
        # them at all, and the test fails for the encoding rather than the
        # lookup.
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=_CHILD_TIMEOUT_SECONDS,
        cwd=tmp_path,
    )

    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr[-3000:]!r}"
    marker = "SPAWN_REPORT "
    line = next(
        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
    )
    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr[-3000:]!r}"
    report = json.loads(line[len(marker) :])

    assert report["errors"] == []
    assert report["state_after_attach"] == "ready"
    assert report["status"] == "SUCCESS"
    assert report["headwords"]

    # A stopped engine can still accept a new request, on a new child.
    assert report["state_after_retire"] == "sleeping"
    assert report["status_after_wake"] == "SUCCESS"
    assert report["generation_after_wake"] > report["generation"]
    assert report["state_after_close"] == "sleeping"

    # Retiring and closing are promises about processes, not about a field.
    assert len(report["children_while_ready"]) == 1
    assert report["children_after_retire"] == []
    assert report["children_after_close"] == []

    assert report["heavy_modules_in_the_shell"] == []
