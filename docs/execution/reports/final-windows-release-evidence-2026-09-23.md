# Final Windows Release Evidence — Partial Run, 2026-09-23

**Status: incomplete. The human interrupted this run to continue on macOS.**
This report records what was verified on Windows, what is still missing, and
exactly how to resume. It adds to
`review-handoffs/final-correction-bundle-2026-09-22.md` and does not replace it.

Everything from **Environment** to **Package build** was observed on Windows at
`cd72d05`, before the macOS corrections below existed. Inside those sections,
only the notes marked *afterwards on macOS* are later. The next section records
what changed, and **Remaining work** is the one authoritative resume
sequence.

## Post-interruption corrections on macOS (2026-09-23)

These were made on macOS after the Windows run stopped. None of them is Windows
evidence; the Windows run must confirm them.

| Commit | Change |
|---|---|
| `f18a0d6` `fix: constrain the verified Qt release runtime` | `PyQt6-Qt6==6.11.2` in `packaging/release-constraints.txt`. A regression test fails if the constraint admits 6.10. `hanly-app` keeps `PyQt6>=6.7,<7`. |
| `d4f827d` `fix: keep benchmark gates portable` | Corpus privacy also refuses POSIX-absolute paths via `PurePosixPath`, whatever the host. The `resource`-based peak test skips where `resource` is absent, and a separate test covers the documented `None` on every host. |
| `docs: harden final windows continuation` | This report: a machine-neutral interpreter path, the corrected probe in Appendix A, and one resume sequence. |

- On macOS, the full release set (dev group, both packages with
  `[runtime]`, PyInstaller and hooks) resolves under the new constraints to
  PyQt6 6.11.0, PyQt6-Qt6 6.11.2, PyQt6-WebEngine 6.11.0 and its Qt6 6.11.2,
  easyocr 1.7.2, PyInstaller 6.22.2 and hooks 2026.7. Under the same
  constraints, PyQt6 6.10.x cannot be resolved.
- PyPI publishes PyQt6-Qt6 6.11.2 wheels for `win_amd64`, `macosx_11_0_arm64`
  and `manylinux_2_34_x86_64`, the three build targets.
- This does **not** show that a Windows build resolves or runs correctly.
  That still has to be confirmed in steps 2–3 below.

## Environment

| Fact | Value |
|---|---|
| Machine | Windows 10 Enterprise 10.0.19045 (22H2), AMD64, medium integrity, not elevated |
| Displays | as recorded in the Wave 6 checkpoint, **not re-measured in this run**: `DISPLAY1` primary `(0,0)–(1920,1080)` and `DISPLAY2` `(-1920,0)–(0,1080)`, both at 96 DPI (100%) |
| Tested commit | `cd72d057f40ff2e29c7c201e9413541d3a572ef3` (`visual/interface-update`); `origin` at the same commit; worktree clean at start |
| Interpreter | `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`, CPython 3.13.11 (MSC v.1944, 64-bit) |
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

*Both corrected afterwards on macOS in `d4f827d`.*

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
  - That is a dependency-policy decision and was **not made** during the run.
    *It was made afterwards on macOS: `f18a0d6` pins `PyQt6-Qt6==6.11.2`.*
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
- **Corrected afterwards on macOS: that method was invalid.**
  - `refine_bounds` is the production behaviour under test. It re-resolves the
    element and line from the pointer it is given, and chooses the span's
    rectangle by that pointer.
  - Asking it from one line-centre point cannot discover arbitrary character
    rectangles. Using it to generate the points it is then judged at is
    circular.
  - Why it returned `None` was never determined. The corrected probe does not
    depend on the answer.
  - Appendix A now builds reference rectangles from raw UIA calls only. A
    Chromium refusal to narrow a word would still show, as failed
    `word_bounds_exact` and snapshot rows.

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
- Whatever that build left, it is stamped `cd72d05` and cannot match the commit
  to validate now. Step 3 of Remaining work rebuilds.

## Remaining work (resume on Windows)

This is the one authoritative resume sequence; the final-correction handoff
links here rather than repeating it. Run it from `C:\Hanly`. The shell inherits
`C:\Hanly\.venv`, so clear `VIRTUAL_ENV` and name the validation interpreter
explicitly:

```powershell
$env:VIRTUAL_ENV = $null
$py = ".\.venv-final-validation\Scripts\python.exe"
```

1. **Pull the macOS corrections.**
   ```powershell
   git fetch origin; git switch visual/interface-update; git pull --ff-only
   git status --short; git rev-parse HEAD
   git merge-base --is-ancestor f18a0d6 HEAD; git merge-base --is-ancestor d4f827d HEAD
   ```
   Required:
   - a clean worktree;
   - both `--is-ancestor` checks exit 0 (`$LASTEXITCODE`);
   - HEAD is the reviewed tip, including the documentation commit after the
     two corrections.
2. **Validation environment.** Reuse `.venv-final-validation`, brought to the
   new constraints:
   ```powershell
   & $py -m pip install --group dev -c packaging/release-constraints.txt
   & $py -m pip install -e packages/hanly -e "packages/hanly-app[runtime]" -c packaging/release-constraints.txt
   & $py -m pip install "pyinstaller>=6,<7" pyinstaller-hooks-contrib -c packaging/release-constraints.txt
   & $py -m pip check
   & $py -m pip show PyQt6-Qt6 hanly hanly-app
   & $py -m pytest --suite portable
   & $py -m pytest --suite native
   & $py -m ruff check packages packaging tests tools benchmarks
   & $py -m mypy --platform linux packages packaging tests tools benchmarks
   ```
   Required:
   - `pip check` is clean.
   - PyQt6-Qt6 is 6.11.2.
   - hanly and hanly-app are 0.5.3, editable from `C:\Hanly`.
   - The portable suite has **no failures**.
   - native, ruff and mypy are green as before.

   If the environment is invalid (a failed install, `pip check` errors, another
   interpreter, or the user site enabled), recreate it and repeat this step.
   Use `py -3.13 -m venv --without-pip .venv-final-validation`, then bootstrap
   pip from the bundled wheel as in *Clean-environment installation*. Never
   validate from `.venv`.
3. **Package.**
   ```powershell
   & $py tools\build_package.py
   Get-Content dist\windows\hanly-desktop\_internal\hanly_app\assets\hanly-build.json
   Get-ChildItem dist\windows -Recurse -Filter msvcp140.dll | % { "$($_.FullName) $($_.VersionInfo.FileVersion)" }
   $env:HANLY_EXPECTED_SOURCE_COMMIT = (git rev-parse HEAD); $env:HANLY_REQUIRE_PACKAGED = "1"
   & $py -m pytest --suite packaged
   ```
   Required:
   - The stamp's `source_commit` equals HEAD, with version 0.5.3 on AMD64.
   - No bundled `msvcp140.dll` is older than 14.44.
   - Inventory, source identity, the frozen worker and the frozen Control
     Center all pass.
4. **Chromium and RichEdit cursor matrix.**
   - Save Appendix A as `<scratch>\uia_probe.py`, and the Appendix B fixtures
     in `<scratch>`.
   - Open the HTML fixture in Chrome with
     `--user-data-dir=<scratch>\chrome-profile`.
   - Open the `.rtf` fixture in WordPad on the negative-origin monitor.
   ```powershell
   $env:PROBE_OUT = "<scratch>\chromium.json"; & $py <scratch>\uia_probe.py "Hanly Windows fixture" chromium
   $env:PROBE_OUT = "<scratch>\richedit.json"; & $py <scratch>\uia_probe.py "<rtf file name>" richedit
   ```
   Required, for each target:
   - All four fixture lines are found, and every character has exactly one
     raw reference rectangle. A missing reference is a probe finding, to be
     diagnosed with raw calls. It is never a production pass or fail.
   - Every `matrix` row has `pass: true`:
     - On a Hangul syllable's left or right half, the outcome is `direct`.
     - The provider's cursor is the reference index, and that character's
       reference rectangle holds the pointer.
     - The word and in-word cursor are right, and the word bounds equal the
       raw reference exactly.
     - The unchanged snapshot is accepted, and the changed one refused.
   - Any other character is refused rather than used.
   - `prefix_plus_suffix_is_line` holds on every row. Record `caret_side` for
     each provider.
   - Pointers right of the line end and between lines are refused.
5. **UIA boundary, COM lifecycle and ownership**, from the same JSON:
   - password and offscreen answer `VT_BOOL False` on ordinary lines;
   - both timeout setters return `S_OK`, the read-back gives 50 ms, and 49 ms
     gives `E_INVALIDARG`;
   - the coordinator deadline is 40 ms;
   - the password input refuses as `secure`, with **zero** `GetText` and
     `GetPattern` calls;
   - bridge creation, reads and disposal all happen on the service worker
     thread;
   - acquired and released interfaces balance.
6. **Real UIA refusal → capture → production EasyOCR → popup.**
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
7. **Verdict.** Append the final Windows verdict to
   `review-handoffs/final-correction-bundle-2026-09-22.md` and commit it as
   documentation only.

## Findings

**Fixed during the Windows run:** none. It was a validation run, and no product
code changed.

**Fixed afterwards on macOS** (not yet confirmed on Windows):
- **PyQt6-Qt6 6.10 bundles MSVC runtime 14.26, which breaks Torch loaded after
  Qt.** `f18a0d6` pins the verified `PyQt6-Qt6==6.11.2` for release builds.
- **Two dev-benchmark tests assumed POSIX.** Fixed in `d4f827d`.
- **The probe's reference method was circular.** Appendix A has been replaced.

**Deferred:**
- **This host's Python 3.13.11 `ensurepip` is inconsistent** (the bundled wheel
  is 25.2, the expected version 25.3).
  - **Trigger:** the next clean-environment run on this host.
  - **Action:** a human repair of the system Python install, which may need a
    reinstaller.

**Dismissed:**
- **A packaged test on bundled `msvcp140.dll` versions.** It was proposed
  during the run.
  - It would read Windows DLL metadata only, so it cannot be a durable
    cross-platform gate.
  - The durable protections are the verified constraint and the real
    frozen-worker check.
  - Step 3 still records the bundled versions as evidence.

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
- `8e0cd7d` recorded the interpreter under the local Windows account's profile
  directory. The current text reads `%LOCALAPPDATA%\…` instead. The original
  line stays in that commit's history, which was not rewritten.
- Neither the Windows run nor the macOS corrections committed pixels, OCR
  output, accessibility content, passwords or private captures.

## Verdict

**Blocked by missing evidence.** This is unchanged by the macOS corrections,
which still need confirming on Windows.
- CI, lint, Linux-platform typing and the native suite were green at `cd72d05`.
- The two portable failures were classified. They are now corrected on macOS.
- The `c10.dll` failure is conclusively diagnosed and absent in a clean
  environment. Release builds are now constrained away from it.
- Not yet obtained: a real production OCR fallback, the Chromium/RichEdit
  cursor matrix, the observed UIA boundary, and a verified packaged artifact.

## Appendix A — `uia_probe.py` (diagnostic scratch probe, not product code)

**Corrected on macOS after the run.** The invalid original is in `8e0cd7d`. The
probe reaches into private adapter names (`_UIABridge`, its constants). It is
not a contract, and it follows the adapter if those change.

Method:
1. Get each fixture line's range from raw UIA calls: element, text pattern,
   `RangeFromPoint`, clone, then expand to a line. Nothing production is
   involved.
2. Clone that line and narrow each clone to one character, and to each Hangul
   word. Use the code-point and UTF-16 candidate offsets the adapter uses.
3. Keep a span only if its text reads back as the expected string.
4. Read its native rectangles with no pointer-containment filtering.
5. Hover the left and right halves of each character's rectangle, and pass
   those points to the real provider and coordinator.
6. Judge the result independently:
   - the provider's cursor is the reference index, and that character's
     reference rectangle holds the pointer;
   - the raw prefix and suffix rebuild the line;
   - the word and in-word cursor are right;
   - the word bounds equal the raw reference exactly;
   - `refine_bounds` accepts the unchanged snapshot and refuses a changed one.

`refine_bounds` is only ever *judged*. It never produces a reference point.
Every native interface is released on every path: `try`/`finally` for each span
clone, and an `ExitStack` that registers each interface as soon as it is
acquired.

**Not confirmed.** The probe has not run against real Chromium or RichEdit, and
it is not known to work there.

On macOS, its reference and judging functions ran against the repository's fake
UIA bridge (`tests/hanly_fixtures/uia.py`). Both unit models and both caret
models were used, over all four fixture lines:
- all 392 rows passed;
- no interface was left unreleased;
- reference generation never called `refine_bounds`;
- a provider reporting the cursor one character late failed 26 of 32 rows.

That shows only that the algorithm is internally consistent.

The Windows-only harness was not executed anywhere: window discovery, the
instrumentation, the boundary and HRESULT reads, and the service lifecycle.

```python
"""Real-control UIA evidence: cursor matrix, boundary properties, timeouts, lifecycle.

Usage (Windows only): python uia_probe.py <window-title-substring> <label> [name=X,Y ...]
Writes JSON to the path in PROBE_OUT.

Reference geometry comes only from raw UIA calls, narrowed from the line range
without any pointer filtering. The production provider and coordinator are then
judged at points taken from that geometry; neither is ever asked to produce the
points it is judged at. Every string recorded is a synthetic fixture, and a
password control's text pattern is never requested.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from contextlib import ExitStack

from hanly import BoundingBox, Point
from hanly_app import text_acquisition_uia as uia
from hanly_app.text_acquisition import (
    DEFAULT_TIMEOUT_MS,
    DirectTextCoordinator,
    DirectTextService,
)

FIXTURES = (
    "초대받았어요",
    "떨어뜨렸어요",
    "받았어요 초대받았어요 받았어요",
    "🙂🙂초대받았어요 Hello 떨어뜨렸어요",
)
LIMIT = 4096


# --- raw reference geometry: diagnostic only, never production refinement ------


def contains(box: BoundingBox | None, p: Point) -> bool:
    return box is not None and box.left <= p.x <= box.right and box.top <= p.y <= box.bottom


def raw_line(bridge, stack: ExitStack, point: Point):
    """(found, line, text) at ``point`` from raw calls; ``stack`` releases each.

    Refuses before any text call unless the element answers password False.
    """

    element = bridge.element_at(point)
    if element is None:
        return None
    stack.callback(bridge.release, element)
    if bridge.flag(element, uia._UIA_IS_PASSWORD_PROPERTY) is not False:
        return None
    pattern = bridge.text_pattern(element)
    if pattern is None:
        return None
    stack.callback(bridge.release, pattern)
    found = bridge.range_at(pattern, point)
    if found is None:
        return None
    stack.callback(bridge.release, found)
    line = bridge.clone(found)
    if line is None:
        return None
    stack.callback(bridge.release, line)
    if not bridge.expand(line, uia._TEXT_UNIT_LINE):
        return None
    return found, line, bridge.text_of(line, LIMIT)


def candidate_offsets(text: str, start: int, end: int):
    """Code points (Chromium) and UTF-16 units (RichEdit), each as (start, end, total)."""

    def units(s: str) -> int:
        return len(s.encode("utf-16-le")) // 2

    points = (start, end, len(text))
    utf16 = (units(text[:start]), units(text[:end]), units(text))
    return (points,) if points == utf16 else (points, utf16)


def raw_span_rects(bridge, line, text: str, start: int, end: int):
    """Native rectangles of ``text[start:end]``, or ``None`` if no candidate reads it back."""

    wanted = text[start:end]
    for first, last, total in candidate_offsets(text, start, end):
        span = bridge.clone(line)
        if span is None:
            continue
        try:
            if not bridge.move_endpoint(span, uia._ENDPOINT_START, uia._TEXT_UNIT_CHARACTER, first):
                continue
            if not bridge.move_endpoint(span, uia._ENDPOINT_END, uia._TEXT_UNIT_CHARACTER, last - total):
                continue
            if bridge.text_of(span, LIMIT) == wanted:
                return bridge.rectangles(span)
        finally:
            bridge.release(span)
    return None


def one_rect(rects) -> BoundingBox | None:
    return rects[0] if rects is not None and len(rects) == 1 else None


def syllable_runs(text: str) -> list[tuple[int, str]]:
    """Each run of precomposed Hangul syllables, the only Hangul in the fixtures.

    The probe's own expectation, deliberately not the coordinator's helper.
    """

    runs: list[tuple[int, str]] = []
    start = None
    for i, ch in enumerate(text + " "):
        hangul = "가" <= ch <= "힣"
        if hangul and start is None:
            start = i
        elif not hangul and start is not None:
            runs.append((start, text[start:i]))
            start = None
    return runs


def reference_line(bridge, anchor: Point, text: str) -> dict | None:
    """Every character's and every word's native rectangle, from one raw line range."""

    with ExitStack() as stack:
        opened = raw_line(bridge, stack, anchor)
        if opened is None or opened[2] != text:
            return None
        line = opened[1]
        chars = [raw_span_rects(bridge, line, text, i, i + 1) for i in range(len(text))]
        words = {
            start: raw_span_rects(bridge, line, text, start, start + len(word))
            for start, word in syllable_runs(text)
        }
    return {
        "chars": [one_rect(r) for r in chars],
        "char_rect_counts": [None if r is None else len(r) for r in chars],
        "words": {start: one_rect(r) for start, r in words.items()},
    }


def raw_part(bridge, line, found, endpoint: int) -> str | None:
    part = bridge.clone(line)
    if part is None:
        return None
    try:
        if not bridge.align_endpoint(part, endpoint, found, uia._ENDPOINT_START):
            return None
        return bridge.text_of(part, LIMIT)
    finally:
        bridge.release(part)


def raw_caret(bridge, point: Point, text: str) -> dict:
    """Where RangeFromPoint leaves its degenerate range, from raw prefix and suffix."""

    with ExitStack() as stack:
        opened = raw_line(bridge, stack, point)
        if opened is None:
            return {"raw_line_is_fixture": False}
        found, line, line_text = opened
        prefix = raw_part(bridge, line, found, uia._ENDPOINT_END)
        suffix = raw_part(bridge, line, found, uia._ENDPOINT_START)
    return {
        "raw_line_is_fixture": line_text == text,
        "raw_caret": None if prefix is None else len(prefix),
        "prefix_plus_suffix_is_line": prefix is not None and suffix is not None
        and prefix + suffix == text,
    }


# --- judging production at reference points ------------------------------------


def mutate(text: str, index: int) -> str:
    replacement = "가" if text[index] != "가" else "나"
    return text[:index] + replacement + text[index + 1:]


def judge(bridge, provider, coordinator, text: str, i: int, reference: dict, p: Point) -> dict:
    word = next(((s, w) for s, w in syllable_runs(text) if s <= i < s + len(w)), None)
    reading = provider.read_at(p, timeout_ms=DEFAULT_TIMEOUT_MS)
    started = time.perf_counter_ns()
    acquisition = coordinator.acquire(p)
    elapsed = (time.perf_counter_ns() - started) / 1e6

    cursor = reading.cursor_index if reading is not None else None
    chars = reference["chars"]
    row = {
        "index": i, "char": text[i], "point": [p.x, p.y],
        "outcome": acquisition.outcome.value, "ms": round(elapsed, 2),
        **raw_caret(bridge, p, text),
        "provider_line_is_fixture": reading is not None and reading.text == text,
        "cursor_correct": cursor == i,
        "cursor_char_rect_contains_point": cursor is not None and 0 <= cursor < len(chars)
        and contains(chars[cursor], p),
    }
    if row["raw_caret"] is not None:
        row["caret_side"] = {i: "before", i + 1: "after"}.get(row["raw_caret"], "other")
    if word is None:
        # Any refusal sends this pointer to OCR; which one is recorded, not required.
        row["expected_outcome"] = "refused"
        row["pass"] = row["outcome"] != "direct"
        return row

    start, expected = word
    selection = acquisition.selection
    row["expected_outcome"] = "direct"
    row["word_correct"] = selection is not None and selection.text == expected \
        and selection.cursor_index == i - start
    reference_word = reference["words"].get(start)
    row["word_bounds_exact"] = reference_word is not None and acquisition.bounds == reference_word
    end = start + len(expected)
    same = provider.refine_bounds(p, start, end, line=text, timeout_ms=DEFAULT_TIMEOUT_MS)
    changed = provider.refine_bounds(p, start, end, line=mutate(text, i), timeout_ms=DEFAULT_TIMEOUT_MS)
    row["unchanged_snapshot_accepted"] = same is not None and same == acquisition.bounds
    row["changed_snapshot_refused"] = changed is None
    row["pass"] = row["outcome"] == "direct" and all(row[key] for key in (
        "cursor_correct", "cursor_char_rect_contains_point", "word_correct",
        "word_bounds_exact", "unchanged_snapshot_accepted", "changed_snapshot_refused"))
    return row


def matrix(bridge, provider, coordinator, anchors: dict[str, Point]) -> list[dict]:
    rows = []
    for text, anchor in anchors.items():
        reference = reference_line(bridge, anchor, text)
        if reference is None:
            rows.append({"line": text, "reference": None})
            continue
        for i, rect in enumerate(reference["chars"]):
            if rect is None:
                rows.append({"line": text, "index": i, "char": text[i], "char_rect": None,
                             "rect_count": reference["char_rect_counts"][i]})
                continue
            for half, fraction in (("left", 0.25), ("right", 0.75)):
                p = Point(round(rect.left + (rect.right - rect.left) * fraction),
                          round((rect.top + rect.bottom) / 2))
                rows.append({"line": text, "half": half,
                             **judge(bridge, provider, coordinator, text, i, reference, p)})
    return rows


# --- Windows-only harness -------------------------------------------------------


ledger = {"acquired": 0, "released": 0, "text_calls": 0, "pattern_calls": 0}
threads: dict[str, list[int]] = {"create": [], "dispose": [], "read": []}


def instrument() -> tuple[uia.UIAutomationTextProvider, DirectTextCoordinator]:
    """Count every native acquisition and release, and record which thread did what."""

    bridge_class = uia._UIABridge
    orig = {name: getattr(bridge_class, name) for name in (
        "element_at", "text_pattern", "range_at", "clone", "release", "text_of", "dispose")}

    def counting(name):
        def wrapper(self, *args):
            if name == "text_pattern":
                ledger["pattern_calls"] += 1
            result = orig[name](self, *args)
            if result is not None:
                ledger["acquired"] += 1
            return result
        return wrapper

    for name in ("element_at", "text_pattern", "range_at", "clone"):
        setattr(bridge_class, name, counting(name))

    def release(self, interface):
        if interface:
            ledger["released"] += 1
        return orig["release"](self, interface)

    def text_of(self, text_range, limit):
        ledger["text_calls"] += 1
        return orig["text_of"](self, text_range, limit)

    def dispose(self):
        threads["dispose"].append(threading.get_ident())
        return orig["dispose"](self)

    bridge_class.release = release
    bridge_class.text_of = text_of
    bridge_class.dispose = dispose
    orig_create = uia._create_bridge

    def create():
        threads["create"].append(threading.get_ident())
        return orig_create()

    uia._create_bridge = create
    provider = uia.UIAutomationTextProvider()
    orig_read = provider.read_at

    def read(point, *, timeout_ms):
        threads["read"].append(threading.get_ident())
        return orig_read(point, timeout_ms=timeout_ms)

    provider.read_at = read  # type: ignore[method-assign]
    return provider, DirectTextCoordinator(provider)


def window_rect(fragment: str) -> tuple[int, int, int, int]:
    from ctypes import wintypes

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


def discover(bridge, rect) -> tuple[dict[str, Point], dict[str, BoundingBox], Point | None]:
    """A pointer-containing anchor and line box per fixture line, and a password point."""

    left, top, right, bottom = rect
    anchors: dict[str, Point] = {}
    boxes: dict[str, BoundingBox] = {}
    password = None
    for y in range(top + 60, bottom - 10, 12):
        for x in range(left + 10, right - 10, 24):
            p = Point(x, y)
            element = bridge.element_at(p)
            if element is None:
                continue
            try:
                is_password = bridge.flag(element, uia._UIA_IS_PASSWORD_PROPERTY)
            finally:
                bridge.release(element)
            if is_password is True:
                password = password or p
                continue
            with ExitStack() as stack:
                opened = raw_line(bridge, stack, p)
                if opened is None or opened[2] not in FIXTURES or opened[2] in anchors:
                    continue
                box = next((b for b in bridge.rectangles(opened[1]) if contains(b, p)), None)
                if box is not None:
                    anchors[opened[2]], boxes[opened[2]] = p, box
    return anchors, boxes, password


def boundary(bridge, coordinator, samples: list[tuple[str, Point]]) -> dict:
    out: dict = {}
    # _create_bridge returns None unless the timed IUIAutomation2 client was
    # created and both setters succeeded; they are re-invoked here for raw HRESULTs.
    out["timed_client"] = bridge is not None
    statuses = [
        bridge._method(bridge._automation, slot, ctypes.c_uint32)(
            bridge._automation, uia._NATIVE_TIMEOUT_MS)
        for slot in (uia._AUTOMATION_PUT_CONNECTION_TIMEOUT, uia._AUTOMATION_PUT_TRANSACTION_TIMEOUT)
    ]
    out["timeout_setter_hresults"] = [hex(s & 0xFFFFFFFF) for s in statuses]
    readback = []
    # Each getter sits one slot before its setter on IUIAutomation2.
    for slot in (uia._AUTOMATION_PUT_CONNECTION_TIMEOUT - 1, uia._AUTOMATION_PUT_TRANSACTION_TIMEOUT - 1):
        value = ctypes.c_uint32()
        status = bridge._method(bridge._automation, slot, ctypes.POINTER(ctypes.c_uint32))(
            bridge._automation, ctypes.byref(value))
        readback.append({"hresult": hex(status & 0xFFFFFFFF), "ms": value.value})
    out["timeout_readback"] = readback
    below = bridge._method(bridge._automation, uia._AUTOMATION_PUT_CONNECTION_TIMEOUT,
                           ctypes.c_uint32)(bridge._automation, 49)
    out["setter_49ms_hresult"] = hex(below & 0xFFFFFFFF)
    out["restored"] = bridge.limit_calls(uia._NATIVE_TIMEOUT_MS)
    out["coordinator_deadline_ms"] = coordinator.timeout_ms

    props = []
    for name, p in samples:
        element = bridge.element_at(p)
        entry: dict = {"sample": name}
        if element is not None:
            try:
                for label, pid in (("password", uia._UIA_IS_PASSWORD_PROPERTY),
                                   ("offscreen", uia._UIA_IS_OFFSCREEN_PROPERTY)):
                    value = bridge._property(element, pid)
                    if value is None:
                        entry[label] = None
                        continue
                    try:
                        entry[label] = {
                            "vt": value.vt, "is_vt_bool": value.vt == uia._VT_BOOL,
                            "value": bool(value.value.bool_value) if value.vt == uia._VT_BOOL else None,
                        }
                    finally:
                        bridge._oleaut32.VariantClear(ctypes.byref(value))
            finally:
                bridge.release(element)
        props.append(entry)
    out["properties"] = props
    return out


def refusal(coordinator, name: str, p: Point) -> dict:
    before_text, before_pattern = ledger["text_calls"], ledger["pattern_calls"]
    acquisition = coordinator.acquire(p)
    return {
        "sample": name, "point": [p.x, p.y], "outcome": acquisition.outcome.value,
        "selection": acquisition.selection is not None,
        "text_calls": ledger["text_calls"] - before_text,
        "pattern_calls": ledger["pattern_calls"] - before_pattern,
        "ms": round(acquisition.duration_ns / 1e6, 2),
    }


def service_lifecycle(provider, p: Point) -> dict:
    """Run the production service once and record which thread did what."""

    main_thread = threading.get_ident()
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
        "worker_is_not_caller": worker != main_thread,
    }


def main() -> None:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    fragment, label = sys.argv[1], sys.argv[2]
    extra = dict(arg.split("=", 1) for arg in sys.argv[3:])
    provider, coordinator = instrument()
    bridge = uia._bridge_for_thread()
    if bridge is None:
        raise SystemExit("no timed UIA client on this thread")

    rect = window_rect(fragment)
    anchors, boxes, password = discover(bridge, rect)
    if password is not None:
        extra.setdefault("password", f"{int(password.x)},{int(password.y)}")
    result: dict = {"target": label, "window": rect,
                    "lines_found": {k: [v.left, v.top, v.right, v.bottom] for k, v in boxes.items()}}
    result["matrix"] = matrix(bridge, provider, coordinator, anchors)

    samples = [(f"line:{t}", p) for t, p in list(anchors.items())[:2]]
    refusals = []
    for key, value in extra.items():
        x, y = (int(v) for v in value.split(","))
        refusals.append(refusal(coordinator, key, Point(x, y)))
        if key == "password":
            samples.append((key, Point(x, y)))
    first = next(iter(boxes.values()))
    refusals.append(refusal(coordinator, "right_of_line_end",
                            Point(first.right + 60, (first.top + first.bottom) // 2)))
    refusals.append(refusal(coordinator, "between_lines", Point(first.left + 5, first.bottom + 3)))
    result["refusals"] = refusals
    result["boundary"] = boundary(bridge, coordinator, samples)
    result["service"] = service_lifecycle(provider, samples[0][1])
    # Each dispose also releases its automation client, which is not a range or
    # element and was never counted as acquired.
    result["ledger"] = dict(ledger, disposes=len(threads["dispose"]),
                            balanced=ledger["acquired"] == ledger["released"] - len(threads["dispose"]))
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
