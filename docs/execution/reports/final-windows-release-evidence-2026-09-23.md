# Final Windows Release Evidence — Partial Run, 2026-09-23

**Status: incomplete. The human interrupted this run to continue on macOS.**
This report records what was verified on Windows, what is still missing, and
exactly how to resume. It adds to
`review-handoffs/final-correction-bundle-2026-09-22.md` and does not replace it.

## Environment

| Fact | Value |
|---|---|
| Machine | Windows 10 Enterprise 10.0.19045 (22H2), AMD64, medium integrity, not elevated |
| Displays | as recorded in the Wave 6 checkpoint, **not re-measured in this run**: `DISPLAY1` primary `(0,0)–(1920,1080)` and `DISPLAY2` `(-1920,0)–(0,1080)`, both at 96 DPI (100%) |
| Tested commit | `cd72d057f40ff2e29c7c201e9413541d3a572ef3` (`visual/interface-update`); `origin` at the same commit; worktree clean at start |
| Interpreter | `C:\Users\Thiago\AppData\Local\Programs\Python\Python313\python.exe`, CPython 3.13.11 (MSC v.1944, 64-bit) |
| Clean venv | `C:\Hanly\.venv-final-validation` (new; `.venv` untouched) |

## Remote CI

GitHub Actions run `35828977851` (workflow `CI`, push, `cd72d05`) finished with
**success**. All seven jobs passed: quality on py3.10, 3.11, 3.12 and 3.13, and
native on linux, macos and windows. It was checked through the public REST API,
because `gh` is not installed on this host. The build workflow (`build.yml`,
which holds the packaged gate) did not run for this commit.

## Clean-environment installation

- **Machine defect, not a repository defect:** `py -3.13 -m venv` failed in
  `ensurepip`. This Python install is inconsistent: `ensurepip._PIP_VERSION` is
  `25.3`, but `Lib\ensurepip\_bundled` contains only `pip-25.2-py3-none-any.whl`.
  - Workaround, with no system change: bootstrap pip from the bundled wheel
    using `PYTHONPATH=<wheel> python -m pip install --upgrade pip`, which
    installs pip 26.2.1.
  - Repairing the system Python install is a separate, human-owned action.
- Then `pip install --group dev` and
  `pip install -e packages/hanly -e "packages/hanly-app[runtime]"` succeeded.
- **Verified:**
  - `hanly` and `hanly-app` are both **0.5.3**, editable from
    `file:///C:/Hanly/packages/...`, and import from the checkout.
  - The user site is disabled, and `sys.path` holds only the venv's
    `site-packages`.
  - Resolved versions: torch 2.14.0+cpu, torchvision 0.29.0, easyocr 1.7.2,
    kiwipiepy 0.23.2, PyQt6 6.11.0 (Qt6 6.11.2), PyQt6-WebEngine 6.11.0,
    numpy 2.5.3, pillow 12.3.0, mss 10.2.0, pynput 1.8.2.
  - `data/generated/krdict.sqlite3` is present (92,508,160 bytes), and
    `HANLY_KRDICT_DB` is unset.
- PyInstaller is not part of the `dev` group. It was installed as CI's build
  workflow does:
  `pip install "pyinstaller>=6,<7" pyinstaller-hooks-contrib -c packaging/release-constraints.txt`,
  giving 6.22.2 and hooks-contrib 2026.7.

## Gate results (clean venv, `cd72d05`)

| Gate | Result |
|---|---|
| `pytest --suite portable` | **2 failed, 2138 passed, 101 skipped** (191 s) |
| `pytest --suite native` | **105 passed, 33 skipped** (193 s); every skip is POSIX- or macOS-only (POSIX update helper, POSIX signals, absent local Vision frozen artifacts) |
| `ruff check packages packaging tests tools benchmarks` | All checks passed |
| `mypy packages packaging tests tools benchmarks` | 22 errors in 7 files, all POSIX-only stdlib attributes (`fcntl.flock`, `os.O_NOFOLLOW`, `os.getxattr`, `os.statvfs`, `os.mkfifo`, `resource.getrusage`) |
| `mypy --platform linux …` (the platform CI checks) | **Success, 285 source files** |
| `pytest --suite packaged` | **not run**; see Remaining work |

Compared with the Wave 6 baseline (`15 failed, 2 errors`), the 12 Torch
failures, the stale-version failure and both `PYTEST_CURRENT_TEST` teardown
errors no longer occur in the clean environment.

### Portable failures, classified

Both are developer-benchmark tests that assume a POSIX host. Portable runs only
on Ubuntu in CI. Neither touches `packages/` or the release path.

1. `benchmarks/dev/tests/test_corpus.py::test_a_committed_manifest_cannot_carry_a_machine_specific_path`
   - On Windows, `/Users/someone/...` has no drive, so `Path.is_absolute()` is
     false. `_require_portable_path` also checks only `PureWindowsPath`, which
     says the same.
   - The path is **still refused**, by `_require_inside` ("resolves outside the
     manifest's own directory"). Only the message differs from what the test
     expects.
   - The fail-closed behaviour holds.
2. `benchmarks/dev/tests/test_ocr_benchmark.py::test_peak_memory_is_readable_without_psutil`
   - `peak_rss()` returns `None` without the POSIX `resource` module.
   - Its sibling test is already skipped for exactly that reason; this one lacks
     the same skip.

## Torch `c10.dll` / WinError 1114 — conclusively diagnosed

Each load boundary ran in its own child process.

| Case | Old `.venv` (torch 2.13.0, PyQt6-Qt6 6.10.2) | Clean venv (torch 2.14.0, PyQt6-Qt6 6.11.2) |
|---|---|---|
| `import torch` | ok | ok |
| `import easyocr` | ok | ok |
| `PyQt6.QtWidgets` then `torch` | **WinError 1114, `c10.dll`** | ok |
| `PyQt6.QtWebEngineWidgets` then `torch` | **WinError 1114** | ok |
| numpy / kiwipiepy / `hanly_app.application` / mss+pynput, then torch | ok | ok |
| preload **MSVC runtime 14.26** (`vcruntime140`+`msvcp140` from old `PyQt6\Qt6\bin`), then torch | **WinError 1114** | **WinError 1114** |
| preload System32 MSVC runtime 14.51, then torch | ok | ok |

- **Failing component:** the MSVC C++ runtime (`msvcp140.dll` /
  `vcruntime140.dll` **14.26.28720**) shipped inside the **PyQt6-Qt6 6.10.x**
  wheel.
  - When Qt loads first, that old runtime is already in the process, and
    Torch's `c10.dll` (built with a newer toolset) fails its DLL
    initialization.
  - Any Torch version fails the same way under that preload, so Torch is not at
    fault.
- **Not a machine prerequisite:** System32 has runtime 14.51.36247, and it
  works.
- **Not reproduced in the clean environment:** PyQt6-Qt6 6.11.2 ships runtime
  14.44.35211, which Torch accepts.
- **The stale 2026-09-15 bundle carried both:** `_internal\msvcp140.dll` 14.51
  and `_internal\PyQt6\Qt6\bin\MSVCP140.dll` 14.26. That is consistent with its
  frozen-worker failure.
- **Reproduction:** in `C:\Hanly\.venv`:
  `python -c "from PyQt6 import QtWidgets; import torch"` → `OSError: [WinError 1114] … torch\lib\c10.dll`.
- **Smallest corrective action:**
  - Build and run from an environment whose PyQt6-Qt6 is at least 6.11. The
    fresh venv already is.
  - To make that durable, the repository could constrain it, e.g. a
    `PyQt6-Qt6>=6.11` line in `packaging/release-constraints.txt` or a raised
    floor in `hanly-app`. The current floor is `PyQt6>=6.7,<7`, which still
    admits 6.10.
  - That is a dependency-policy decision and was **not made**; see Deferred.
  - The production design already keeps Torch out of the Qt shell: EasyOCR is
    imported first inside the lookup child.
  - A frozen bundle still collects every DLL into one tree, so it needs a
    packaged-worker check against a fresh build.

## Real UIA / OCR evidence — NOT yet obtained

The first Chrome cursor-matrix attempt produced no valid data. It is not
evidence either way.

- The probe discovered all four fixture lines through the production adapter,
  with pointer-containing line rectangles at Chrome window `(40,40)–(1290,990)`:

  | Line | Rectangle |
  |---|---|
  | `초대받았어요` | `(88,148)–(328,202)` |
  | `떨어뜨렸어요` | `(88,218)–(328,272)` |
  | `받았어요 초대받았어요 받았어요` | `(88,288)–(676,342)` |
  | `🙂🙂초대받았어요 Hello 떨어뜨렸어요` | `(88,358)–(800,412)` |

- Its per-character *reference* rectangles all came back `None`. They are taken
  from `refine_bounds(line_centre, i, i+1, line=text)`, so no hover points were
  generated.
  - The cause was being debugged when the run stopped. It is most likely in the
    probe's reference-rectangle step, not in the adapter.
  - It could also be the adapter's `_narrowed` refusing single-character spans
    in Chromium.
  - **That second possibility must be ruled out before any verdict**, because
    `refine_bounds` is the production path for word bounds too.

The Chrome fixture window and a WordPad `RICHEDIT50W` fixture on the secondary
(negative-origin) monitor were open, and were closed at the end of the run.

## Package build — started, not verified

- `tools\build_package.py` was started from the clean venv at `cd72d05`.
  - When the run stopped, PyInstaller was in its final `COLLECT` step into
    `dist\windows\hanly-desktop`.
  - The old 2026-09-15 bundle there was replaced.
- There is **no verified Windows artifact yet**:
  - its stamp was never read;
  - the packaged gate was never run.
- If the build finished, check its stamp and bundled runtime versions before
  trusting it. If it didn't, rebuild.

## Remaining work (resume on Windows)

From `C:\Hanly`, on the commit to be validated. Clear `VIRTUAL_ENV`, because
the shell inherits `C:\Hanly\.venv`.

1. **Package.** Confirm HEAD, then rebuild unless `dist\windows` is already
   stamped with it:
   ```powershell
   $env:VIRTUAL_ENV = $null
   .\.venv-final-validation\Scripts\python.exe tools\build_package.py
   Get-Content dist\windows\hanly-desktop\_internal\hanly_app\assets\hanly-build.json
   Get-ChildItem dist\windows -Recurse -Filter msvcp140.dll | % { "$($_.FullName) $($_.VersionInfo.FileVersion)" }
   $env:HANLY_EXPECTED_SOURCE_COMMIT = (git rev-parse HEAD); $env:HANLY_REQUIRE_PACKAGED = "1"
   .\.venv-final-validation\Scripts\python.exe -m pytest --suite packaged
   ```
   Required:
   - inventory, source identity (stamp = HEAD), the frozen worker and the
     frozen Control Center all pass;
   - version 0.5.3, AMD64;
   - no bundled `msvcp140.dll` older than 14.44.
2. **UIA cursor matrix, Chrome and WordPad.**
   - Fix the probe's reference rectangles (Appendix A). First run
     `refine_bounds` on a single character by hand to rule out an adapter
     refusal.
   - Then take the whole matrix for each target:
     - left and right halves of every syllable;
     - cursor index, selected neighbour (caret before or after the character),
       and pointer containment;
     - prefix + suffix = line;
     - the snapshot rule: an unchanged line gives the same bounds, and a
       same-length mutated line is refused;
     - the repeated-substring line and the emoji-prefixed line;
     - refusals right of the line end and between lines.
   - Fixture: Appendix B.
   - Launch Chrome with `--user-data-dir=<scratch>\chrome-profile` and open
     WordPad on the `.rtf` fixture.
3. **UIA boundary**, from the same probe:
   - password and offscreen answer `VT_BOOL False` on ordinary lines;
   - both timeout setters return `S_OK`, the read-back gives 50 ms, and 49 ms
     gives `E_INVALIDARG`;
   - the coordinator deadline is 40 ms;
   - the password input refuses as `secure`, with **zero** `GetText` and
     `GetPattern` calls;
   - bridge creation, reads and disposal all happen on the service worker
     thread;
   - acquired and released interfaces balance.
4. **Real production OCR fallback.**
   - Run the production composition with a recording trace sink that has
     neither `retain_text` nor evidence, as `benchmarks/dev/hud/session.py`
     does. Use an app config with `hover_activation: always_active` and
     `lookup_preload: always`.
   - Hover the `<canvas>` in the fixture, which draws `가공식품` or `?w=<word>`.
   - Required:
     - `hover_direct_text` reports outcome `unsupported`;
     - exactly one `hover_capture_attempted` / `hover_capture_completed` per
       hover id;
     - an `ocr` stage from the lookup child with `ocr_backend=easyocr` and
       `ocr_cached=false`;
     - the popup's `LookupResult` is `SUCCESS` for the fixture word;
     - timing is recorded.
   - Also launch once through `hanly --app-config <scratch config>`, the normal
     entry point, and confirm the session log records the lookup.
   - Keep production `readtext()` evidence separate from any staged EasyOCR
     replay.
5. Append the verdict to the final-correction handoff and commit
   documentation-only.

## Findings

**Fixed now:** none. This was a validation run, and no product code changed.

**Deferred:**
- **PyQt6-Qt6 6.10 bundles MSVC runtime 14.26, which breaks Torch loaded after
  Qt.** The dependency floor still admits it.
  - **Trigger:** the release-constraints review, or any Windows build
    environment that resolves PyQt6-Qt6 < 6.11.
  - **Proposed:** `PyQt6-Qt6>=6.11` in `packaging/release-constraints.txt`, and
    a packaged check that no bundled `msvcp140.dll` is older than the one Torch
    needs.
- **Two dev-benchmark tests assume POSIX** (above).
  - **Trigger:** adding Windows to the portable CI matrix.
  - **Proposed:** a `skipif` on `resource` for `peak_rss`, and treat a rooted,
    drive-less path as absolute in `_require_portable_path`.
- **This host's Python 3.13.11 `ensurepip` is inconsistent** (the bundled wheel
  is 25.2, the expected version 25.3).
  - **Trigger:** the next clean-environment run on this host.
  - **Action:** a human repair of the system Python install, which may need a
    reinstaller.

**Dismissed:** none.

## Privacy

- Every string used or recorded is a synthetic fixture.
- No screenshot, capture, OCR output, accessibility text from real
  applications, or export was produced.
- Nothing was written under `artifacts/`.
- The password input held the synthetic value `synthetic-fixture`, and the probe
  never requests its text.
- All probe scripts and outputs lived in the session scratchpad. The scripts
  are reproduced in the appendices; their outputs held only fixture strings and
  coordinates.

## Verdict

**Blocked by missing evidence.**
- CI, lint, Linux-platform typing and the native suite are green.
- The two portable failures are classified.
- The `c10.dll` failure is conclusively diagnosed and absent in a clean
  environment.
- Not yet obtained: a real production OCR fallback, the Chromium/RichEdit
  cursor matrix, the observed UIA boundary, and a verified packaged artifact.

## Appendix A — `uia_probe.py` (scratch probe, not product code)

Known defect: every per-character reference rectangle came back `None` (see above).

```python
"""Real-control UIA evidence: cursor matrix, boundary properties, timeouts, lifecycle.

Usage: python uia_probe.py <window-title-substring> <label> [--password X,Y] [--blank X,Y ...]

Every string recorded is one of the synthetic fixtures; a password control's
contents are never requested, and the probe asserts that no text call is made.
"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from hanly import BoundingBox, Point  # noqa: E402
from hanly_app import text_acquisition_uia as uia  # noqa: E402
from hanly_app.text_acquisition import (  # noqa: E402
    DEFAULT_TIMEOUT_MS,
    DirectTextCoordinator,
    DirectTextService,
    _korean_run,
)

FIXTURES = {
    "초대받았어요",
    "떨어뜨렸어요",
    "받았어요 초대받았어요 받았어요",
    "🙂🙂초대받았어요 Hello 떨어뜨렸어요",
}

# --- instrumentation: native acquisition/release ledger and thread identity ---
ledger = {"acquired": 0, "released": 0, "text_calls": 0, "pattern_calls": 0}
threads: dict[str, list[int]] = {"create": [], "dispose": [], "read": []}
Bridge = uia._UIABridge
_orig = {name: getattr(Bridge, name) for name in (
    "element_at", "text_pattern", "range_at", "clone", "release", "text_of", "dispose")}


def _counting(name):
    def wrapper(self, *args):
        result = _orig[name](self, *args)
        if result is not None:
            ledger["acquired"] += 1
        if name == "text_pattern":
            ledger["pattern_calls"] += 1
        return result
    return wrapper


for _name in ("element_at", "text_pattern", "range_at", "clone"):
    setattr(Bridge, _name, _counting(_name))


def _release(self, interface):
    if interface:
        ledger["released"] += 1
    return _orig["release"](self, interface)


def _text_of(self, text_range, limit):
    ledger["text_calls"] += 1
    return _orig["text_of"](self, text_range, limit)


def _dispose(self):
    threads["dispose"].append(threading.get_ident())
    return _orig["dispose"](self)


Bridge.release = _release
Bridge.text_of = _text_of
Bridge.dispose = _dispose
_orig_create = uia._create_bridge


def _create():
    threads["create"].append(threading.get_ident())
    return _orig_create()


uia._create_bridge = _create
provider = uia.UIAutomationTextProvider()
_orig_read = provider.read_at


def _read(point, *, timeout_ms):
    threads["read"].append(threading.get_ident())
    return _orig_read(point, timeout_ms=timeout_ms)


provider.read_at = _read  # type: ignore[method-assign]
coordinator = DirectTextCoordinator(provider)
secure_points: dict[str, Point] = {}


# --- helpers ------------------------------------------------------------------

def window_rect(fragment: str) -> tuple[int, int, int, int]:
    found: list[int] = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buffer, 512)
            if fragment in buffer.value:
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        raise SystemExit(f"no window titled *{fragment}*")
    rect = wintypes.RECT()
    user32.SetForegroundWindow(found[0])
    time.sleep(0.4)
    user32.GetWindowRect(found[0], ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def contains(box: BoundingBox | None, p: Point) -> bool:
    return box is not None and box.left <= p.x <= box.right and box.top <= p.y <= box.bottom


def discover_lines(rect) -> dict[str, BoundingBox]:
    """Scan the window and keep each fixture line's own rectangle."""

    left, top, right, bottom = rect
    lines: dict[str, BoundingBox] = {}
    bridge = uia._bridge_for_thread()
    for y in range(top + 60, bottom - 10, 12):
        for x in range(left + 10, right - 10, 24):
            p = Point(x, y)
            reading = provider.read_at(p, timeout_ms=DEFAULT_TIMEOUT_MS)
            if reading and reading.secure:
                secure_points.setdefault("password", p)
            if reading and reading.text in FIXTURES and contains(reading.bounds, p):
                lines.setdefault(reading.text, reading.bounds)
    assert bridge is not None
    return lines


def char_rects(text: str, box: BoundingBox) -> list[BoundingBox | None]:
    centre = Point((box.left + box.right) / 2, (box.top + box.bottom) / 2)
    return [
        provider.refine_bounds(centre, i, i + 1, line=text, timeout_ms=DEFAULT_TIMEOUT_MS)
        for i in range(len(text))
    ]


def raw_detail(p: Point) -> dict:
    """The adapter's own steps, one by one, so caret side and component are visible."""

    bridge = uia._bridge_for_thread()
    P = uia.UIAutomationTextProvider
    element = bridge.element_at(p)
    if element is None:
        return {"element": False}
    try:
        pattern = bridge.text_pattern(element)
        if pattern is None:
            return {"pattern": False}
        try:
            found = bridge.range_at(pattern, p)
            if found is None:
                return {"range": False}
            try:
                line = P._line_of(bridge, found)
                try:
                    text = bridge.text_of(line, 4096)
                    before = P._part_of_line(bridge, line, found, uia._ENDPOINT_END)
                    after = P._part_of_line(bridge, line, found, uia._ENDPOINT_START)
                    caret = len(before) if before is not None else None
                    right_ok = caret is not None and caret < len(text) and P._character_holds(
                        bridge, found, uia._ENDPOINT_END, 1, text[caret], p)
                    left_ok = caret is not None and caret > 0 and P._character_holds(
                        bridge, found, uia._ENDPOINT_START, -1, text[caret - 1], p)
                    return {
                        "caret": caret,
                        "prefix_plus_suffix_is_line": before is not None and after is not None
                        and before + after == text,
                        "char_after_caret_holds": right_ok,
                        "char_before_caret_holds": left_ok,
                    }
                finally:
                    bridge.release(line)
            finally:
                bridge.release(found)
        finally:
            bridge.release(pattern)
    finally:
        bridge.release(element)


def mutate(text: str, index: int) -> str:
    replacement = "가" if text[index] != "가" else "나"
    return text[:index] + replacement + text[index + 1:]


def matrix(lines: dict[str, BoundingBox]) -> list[dict]:
    rows = []
    for text, box in lines.items():
        rects = char_rects(text, box)
        for i, rect in enumerate(rects):
            if rect is None:
                rows.append({"line": text, "index": i, "char": text[i], "char_rect": None})
                continue
            for half, fraction in (("left", 0.25), ("right", 0.75)):
                p = Point(round(rect.left + (rect.right - rect.left) * fraction),
                          round((rect.top + rect.bottom) / 2))
                started = time.perf_counter_ns()
                acquisition = coordinator.acquire(p)
                elapsed = (time.perf_counter_ns() - started) / 1e6
                run = _korean_run(text, i)
                row = {
                    "line": text, "index": i, "char": text[i], "half": half,
                    "point": [p.x, p.y], "outcome": acquisition.outcome.value,
                    "ms": round(elapsed, 2), **raw_detail(p),
                }
                if acquisition.selection is not None:
                    row.update(
                        word=acquisition.selection.text,
                        word_cursor=acquisition.selection.cursor_index,
                        expected_word=run[0] if run else None,
                        expected_cursor=run[1] if run else None,
                        bounds_contain_point=contains(acquisition.bounds, p),
                    )
                    start = run[2]
                    same = provider.refine_bounds(p, start, start + len(run[0]),
                                                  line=text, timeout_ms=40)
                    changed = provider.refine_bounds(p, start, start + len(run[0]),
                                                     line=mutate(text, i), timeout_ms=40)
                    row.update(refine_same_snapshot=same == acquisition.bounds,
                               refine_changed_snapshot_refused=changed is None)
                else:
                    row.update(expected_word=run[0] if run else None)
                rows.append(row)
    return rows


def boundary(rect, samples: list[tuple[str, Point]]) -> dict:
    bridge = uia._bridge_for_thread()
    out: dict = {}
    # Client identity and both timeout setters, re-invoked for their raw HRESULTs.
    out["timed_client_iid"] = "IUIAutomation2" if bridge is not None else None
    statuses = []
    for slot in (uia._AUTOMATION_PUT_CONNECTION_TIMEOUT, uia._AUTOMATION_PUT_TRANSACTION_TIMEOUT):
        statuses.append(bridge._method(bridge._automation, slot, ctypes.c_uint32)(
            bridge._automation, uia._NATIVE_TIMEOUT_MS))
    out["timeout_setter_hresults"] = [hex(s & 0xFFFFFFFF) for s in statuses]
    readback = []
    for slot in (uia._AUTOMATION_PUT_CONNECTION_TIMEOUT - 1, uia._AUTOMATION_PUT_TRANSACTION_TIMEOUT - 1):
        value = ctypes.c_uint32()
        status = bridge._method(bridge._automation, slot, ctypes.POINTER(ctypes.c_uint32))(
            bridge._automation, ctypes.byref(value))
        readback.append({"hresult": hex(status & 0xFFFFFFFF), "ms": value.value})
    out["timeout_readback"] = readback
    below = bridge._method(bridge._automation, uia._AUTOMATION_PUT_CONNECTION_TIMEOUT,
                           ctypes.c_uint32)(bridge._automation, 49)
    out["setter_49ms_hresult"] = hex(below & 0xFFFFFFFF)
    bridge.limit_calls(uia._NATIVE_TIMEOUT_MS)
    out["coordinator_deadline_ms"] = coordinator.timeout_ms

    props = []
    for name, p in samples:
        element = bridge.element_at(p)
        entry = {"sample": name}
        if element is not None:
            try:
                for label, pid in (("password", uia._UIA_IS_PASSWORD_PROPERTY),
                                   ("offscreen", uia._UIA_IS_OFFSCREEN_PROPERTY)):
                    value = bridge._property(element, pid)
                    entry[label] = None if value is None else {
                        "vt": value.vt, "is_vt_bool": value.vt == uia._VT_BOOL,
                        "value": bool(value.value.bool_value) if value.vt == uia._VT_BOOL else None,
                    }
                    if value is not None:
                        bridge._oleaut32.VariantClear(ctypes.byref(value))
            finally:
                bridge.release(element)
        props.append(entry)
    out["properties"] = props
    return out


def refusal(name: str, p: Point) -> dict:
    before_text, before_pattern = ledger["text_calls"], ledger["pattern_calls"]
    acquisition = coordinator.acquire(p)
    return {
        "sample": name, "point": [p.x, p.y], "outcome": acquisition.outcome.value,
        "selection": acquisition.selection is not None,
        "text_calls": ledger["text_calls"] - before_text,
        "pattern_calls": ledger["pattern_calls"] - before_pattern,
        "ms": round(acquisition.duration_ns / 1e6, 2),
    }


def service_lifecycle(p: Point) -> dict:
    """Run the production service once and record which thread did what."""

    main = threading.get_ident()
    provider.release_thread()  # leave the probe thread's own apartment first
    create0, dispose0, read0 = len(threads["create"]), len(threads["dispose"]), len(threads["read"])
    delivered = threading.Event()
    got: dict = {}

    def deliver(acquisition):
        got["outcome"] = acquisition.outcome.value
        got["thread"] = threading.current_thread().name
        delivered.set()

    service = DirectTextService(DirectTextCoordinator(provider))
    service.submit(p, deliver)
    delivered.wait(5)
    worker = service._worker.ident
    service.close()
    return {
        "outcome": got.get("outcome"), "delivered_on": got.get("thread"),
        "bridge_created_on_worker": threads["create"][create0:] == [worker],
        "reads_on_worker": set(threads["read"][read0:]) == {worker},
        "bridge_disposed_on_worker": threads["dispose"][dispose0:] == [worker],
        "worker_is_not_caller": worker != main,
    }


def main() -> None:
    fragment, label = sys.argv[1], sys.argv[2]
    extra = dict(arg.split("=", 1) for arg in sys.argv[3:])
    rect = window_rect(fragment)
    lines = discover_lines(rect)
    for key, p in secure_points.items():
        extra.setdefault(key, f"{int(p.x)},{int(p.y)}")
    result: dict = {"target": label, "window": rect, "lines_found": {
        k: [v.left, v.top, v.right, v.bottom] for k, v in lines.items()}}
    result["matrix"] = matrix(lines)

    samples = [(f"line:{t}", Point((b.left + b.right) // 2, (b.top + b.bottom) // 2))
               for t, b in list(lines.items())[:2]]
    refusals = []
    for key, value in extra.items():
        x, y = (int(v) for v in value.split(","))
        refusals.append(refusal(key, Point(x, y)))
        if key == "password":
            samples.append((key, Point(x, y)))
    first = next(iter(lines.values()))
    refusals.append(refusal("right_of_line_end", Point(first.right + 60, (first.top + first.bottom) // 2)))
    refusals.append(refusal("between_lines", Point(first.left + 5, first.bottom + 3)))
    result["refusals"] = refusals
    result["boundary"] = boundary(rect, samples)
    anchor = samples[0][1]
    result["service"] = service_lifecycle(anchor)
    # Each dispose also releases its automation client, which is not a range
    # or element and was never counted as acquired.
    result["ledger"] = dict(ledger, disposes=len(threads["dispose"]),
                            balanced=ledger["acquired"] == ledger["released"] - len(threads["dispose"]))
    import os
    with open(os.environ["PROBE_OUT"], "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)


if __name__ == "__main__":
    main()
```

## Appendix B — fixtures

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Hanly Windows fixture</title>
<style>
  body { margin: 24px 40px; font-family: "Malgun Gothic", sans-serif; background: #fff; color: #000; }
  p { font-size: 40px; margin: 0 0 22px 0; line-height: 1.2; white-space: nowrap; }
  #gap { height: 70px; }
  canvas { display: block; margin-top: 10px; }
  input { font-size: 24px; margin-top: 16px; }
</style>
</head>
<body>
<p id="l1">초대받았어요</p>
<p id="l2">떨어뜨렸어요</p>
<p id="l3">받았어요 초대받았어요 받았어요</p>
<p id="l4">🙂🙂초대받았어요 Hello 떨어뜨렸어요</p>
<div id="gap"></div>
<canvas id="c" width="520" height="110"></canvas>
<input id="pw" type="password" value="synthetic-fixture" autocomplete="off">
<script>
  const ctx = document.getElementById("c").getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, 520, 110);
  ctx.fillStyle = "#000"; ctx.font = "64px 'Malgun Gothic'"; ctx.textBaseline = "middle";
  ctx.fillText(new URLSearchParams(location.search).get("w") || "가공식품", 20, 58);
</script>
</body>
</html>
```

```python
# make_rtf.py <out.rtf>
import sys
from pathlib import Path

LINES = [
    "초대받았어요",
    "떨어뜨렸어요",
    "받았어요 초대받았어요 받았어요",
    "🙂🙂초대받았어요 Hello 떨어뜨렸어요",
]


def rtf_escape(text: str) -> str:
    out = []
    for unit in memoryview(text.encode("utf-16-le")).cast("H"):
        out.append(chr(unit) if unit < 128 else f"\\u{unit - 65536 if unit > 32767 else unit}?")
    return "".join(out)


body = "\\par\n".join(rtf_escape(line) for line in LINES)
rtf = (
    "{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\fnil Malgun Gothic;}}\n"
    "\\f0\\fs60\\sl480\\slmult0 " + body + "\\par\n}"
)
Path(sys.argv[1]).write_text(rtf, encoding="ascii")
```

## Appendix C — load-boundary diagnostics

```python
"""Run each Torch load boundary in its own child so one failure can't mask another."""

import subprocess
import sys

CASES = {
    "torch": "import torch; print(torch.__version__, torch.__file__)",
    "easyocr": "import easyocr; print('ok')",
    "qt_then_torch": "from PyQt6 import QtWidgets; import torch; print('ok')",
    "qtwebengine_then_torch": "from PyQt6 import QtWebEngineWidgets; import torch; print('ok')",
    "numpy_then_torch": "import numpy; import torch; print('ok')",
    "kiwi_then_torch": "import kiwipiepy; import torch; print('ok')",
    "hanly_app_then_torch": "import hanly_app.application; import torch; print('ok')",
    "mss_pynput_then_torch": "import mss, pynput; import torch; print('ok')",
    "provider": (
        "from hanly.easyocr_provider import EasyOCRProvider\n"
        "import inspect; print(inspect.signature(EasyOCRProvider))"
    ),
}

for name, code in CASES.items():
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    err = [line for line in proc.stderr.splitlines() if "Error" in line][-1:] if proc.returncode else []
    print(f"{name:26} exit={proc.returncode} {tail[:110]} {' '.join(err)[:220]}")
```

```python
"""Load one specific msvcp140.dll first, then Torch, each in a fresh child."""

import subprocess
import sys

OLD_QT_BIN = r"C:\Hanly\.venv\Lib\site-packages\PyQt6\Qt6\bin"
CASES = {
    "preload_old_qt_crt_14.26": OLD_QT_BIN,
    "preload_system32_crt_14.51": r"C:\Windows\System32",
}
CODE = (
    "import ctypes, os, sys\n"
    "d = sys.argv[1]\n"
    "ctypes.WinDLL(os.path.join(d, 'vcruntime140.dll'))\n"
    "ctypes.WinDLL(os.path.join(d, 'msvcp140.dll'))\n"
    "import torch\n"
    "print('ok', torch.__version__)\n"
)
for name, directory in CASES.items():
    proc = subprocess.run([sys.executable, "-c", CODE, directory], capture_output=True, text=True)
    err = [line for line in proc.stderr.splitlines() if "Error" in line][-1:]
    print(f"{name:28} exit={proc.returncode} {proc.stdout.strip()} {' '.join(err)[:160]}")
```
