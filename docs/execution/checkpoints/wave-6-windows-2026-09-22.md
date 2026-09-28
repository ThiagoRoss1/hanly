# Checkpoint — Wave 6, Windows accessible text acquisition

**Authorized:** 2026-09-22, one Phase A implementation run on a real Windows
machine, ending at the Wave 6 Review Handoff. Phase B is **not** part of it.
**Branch/worktree:** `visual/interface-update`, existing worktree, no new branch.
**Starting commit:** `456500e` (clean worktree). **Product boundary:** `73b7372`. `45a22a7`, the final reviewed
macOS implementation boundary, confirmed as an ancestor. No history rewritten.
**Interpreter:** `C:\Hanly\.venv\Scripts\python.exe`, CPython 3.13.11
(MSC v.1944, 64-bit).

## Environment as measured

| Fact | Value |
|---|---|
| OS | Windows 10 Enterprise, 10.0.19045 (22H2), AMD64 |
| Integrity level | medium; the session is **not** elevated |
| Monitors | `DISPLAY1` primary `(0, 0)–(1920, 1080)`; `DISPLAY2` **`(-1920, 0)–(0, 1080)`** |
| Monitor DPI | both 96 (100%). No other scale factor is available on this machine |
| Virtual desktop | origin `(-1920, 0)`, `3840 × 1080` |
| Process DPI awareness | bare interpreter: **unaware (0)**. After `ensure_qt_application()`: **per-monitor-aware-v2** (context `-4`), process awareness `2`, inherited by worker threads |
| Dictionary | `data/generated/krdict.sqlite3` present (88 MB); `HANLY_KRDICT_DB` unset. Nothing on the lookup pipeline changed, so it was not exercised |
| Test applications | Notepad, WordPad, Chrome 1, Edge, Discord, VS Code, Brave |

Qt 6 is what makes the shell per-monitor aware, and the shell is the process
that owns the acquisition worker. Pointer coordinates, `GetCursorPos`, pynput,
`mss` and UI Automation were all observed reporting the same physical
virtual-desktop pixels there, so **no coordinate transform is applied**, and the
coordinator's existing containment rule is what would catch it if that ever
stopped being true.

## Dependency decision

None added. UI Automation is bound through `ctypes`, the way
`text_acquisition_ax.py` binds the macOS accessibility API. `comtypes` was not
installed and is not needed: four interfaces are used out of a very large
library, and a COM code-generation dependency would have been a runtime
requirement on macOS and Linux as well. `collect_submodules("hanly_app")`
already carries the new module into every artifact, exactly as it carries the
macOS adapter, so the packaging spec is unchanged.

## What UI Automation actually does here

Every vtable slot was confirmed against the running system rather than
transcribed, because a wrong slot is an access violation and not an error code.

| Question | Measured answer |
|---|---|
| Timeout control | `IUIAutomation2` (`CLSID_CUIAutomation8`) exposes `put_ConnectionTimeout`/`put_TransactionTimeout`. Defaults **2000 ms** and **20000 ms** |
| Tightest timeout allowed | **50 ms**; anything below returns `E_INVALIDARG`. That is already wider than the caller's 40 ms budget |
| `RangeFromPoint` | Returns a degenerate range at the **nearest** character, with a ~1 px rectangle. Observed answering about a WordPad line 14 px above the pointer and about an Edge sync-promo overlay 200 px away |
| `MoveEndpointByUnit(Character)` | **Chromium counts code points. RichEdit counts UTF-16 code units.** On `🙂🙂초대받았어요`, the UTF-16 offset yields `받았어요` in Chromium and the correct `초대받았어요` in RichEdit |
| Cursor position | Taking the text *before* the pointer and measuring it in Python characters is correct on both, because a returned string decodes to code points either way |
| `GetBoundingRectangles` | Flat `left, top, width, height` quadruples, one per visual line; a password label line really does return two |
| `UIA_IsHiddenAttributeId` | Chromium reports **`True` for plainly visible text**. Not used |
| `UIA_IsPasswordPropertyId` | Reliable, and necessary: Chromium and Edge expose a **text pattern on password inputs** |
| Password refusal | Checked before any pattern is obtained |
| `UIA_IsPasswordAttributeId` | Does not exist. The element property above is the real check |
| Negative monitor origins | Reported verbatim; no adjustment needed |
| `CoUninitialize` | Raises two first-chance `RPC_E_DISCONNECTED` while dropping the cross-process connection, and handles both. The count does **not** grow with the number of reads, so nothing is leaking |

## Implemented

| Piece | Where |
|---|---|
| Windows adapter | `packages/hanly-app/src/hanly_app/text_acquisition_uia.py` |
| Platform selection | `default_text_acquisition()` split into `_darwin_coordinator()` / `_windows_coordinator()` |
| Worker thread lifecycle | `DirectTextCoordinator.bind_worker()` / `release_worker()`, forwarded to optional provider hooks |
| Windows native tests | `tests/native/windows/test_text_acquisition_uia.py` (62 cases) |
| Platform/import tests | `tests/test_text_acquisition_platform.py` (10 cases) |
| Service lifecycle tests | 4 cases appended to `tests/test_text_acquisition_service.py` |
| Packaging test | 1 case appended to `tests/test_packaging.py` |

### The one common-contract change, and why it was necessary

`DirectTextCoordinator` gained `bind_worker()` / `release_worker()`, called by
`DirectTextService._work()` around its loop. They forward to an optional
`bind_thread()` / `release_thread()` on the provider using the same duck-typed
capability check the coordinator already uses for `refine_bounds`.

It is necessary because a COM apartment belongs to a **thread**, not a process.
The adapter must call `CoInitializeEx` on the service's worker and
`CoUninitialize` on that same thread, and nothing else in the design tells the
provider when that thread starts or ends. Leaving the apartment un-exited was
the alternative, and the run's own evidence shows why balance matters: a thread
that dies inside an apartment it never left disconnects the next thread's
objects.

macOS is unaffected — `AccessibilityTextProvider` offers neither hook, and a
provider that raises from one is still driven, because a worker that refused to
start would leave every hover waiting for an outcome that never came.

### Design points worth naming

- **The span is verified, not trusted.** A narrowed range is asked for with code
  point offsets and, when they differ, UTF-16 offsets, and is accepted only if
  the text it returns is the text that was asked for. This is the whole defence
  against the Chromium/RichEdit disagreement, and it refuses rather than
  approximating when neither matches.
- **Native timeouts are not the deadline.** Both UIA call timeouts are set to
  the platform floor of 50 ms. The caller's 40 ms budget remains authoritative
  and is enforced by the existing watcher. The floor is set anyway so a wedged
  provider holds the one worker thread for 50 ms rather than 20 seconds.
- **Policy stayed in `text_acquisition.py`.** The adapter reports a line, a
  cursor index and a rectangle; every acceptance rule is still the common one.
- **A line longer than 4096 characters is refused,** because past the truncation
  point it is the cap and not the pointer that decides every offset.
- **`role` is not read.** Nothing consumes it, and reading a class name would
  cost a cross-process round trip on the hot path for a diagnostic.

## Real-application coverage

Synthetic Korean fixtures only, under the session scratchpad; nothing persisted
in the repository. Latencies are through the real adapter and coordinator, 40
warm samples per point, milliseconds.

### Direct text

| Application | Control | Monitor | Surface | Result | cold | p50 | p95 | max |
|---|---|---|---|---|---|---|---|---|
| WordPad | `RICHEDIT50W`, Win32 | primary | `초대받았어요` | direct, exact word, cursor-sensitive | 31.84 | 8.02 | 10.19 | 11.61 |
| WordPad | `RICHEDIT50W` | primary | `떨어뜨렸어요` | direct | 7.66 | 8.06 | 9.78 | 9.87 |
| WordPad | `RICHEDIT50W` | primary | `깨뜨렸습니다` | direct | 7.71 | 8.01 | 10.64 | 12.24 |
| WordPad | `RICHEDIT50W` | primary | `가공식품` | direct | 8.47 | 8.02 | 10.19 | 10.20 |
| WordPad | `RICHEDIT50W` | primary | `🙂🙂초대받았어요` | direct, **UTF-16 candidate won** | 7.72 | 8.01 | 9.47 | 9.75 |
| Notepad | `Edit`, Win32 | primary | `🙂🙂초대받았어요` | direct, word rectangle excludes the emoji, cursor 1→3→5 across x | 13.98 | 7.08 | 8.04 | 8.12 |
| Chrome | Chromium document | **secondary, negative origin** | `초대받았어요` | direct, bounds `(-1468, 213)–(-1276, 256)` | 15.47 | 7.07 | 8.14 | 9.39 |
| Chrome | Chromium | secondary | `Hello 초대받았어요 world` | direct, answers `초대받았어요` alone | 8.92 | 6.73 | 7.99 | 8.19 |
| Chrome | Chromium | secondary | `🙂🙂초대받았어요` | direct, **code-point candidate won** | 6.44 | 6.61 | 7.49 | 7.68 |
| Chrome | iframe document | secondary | `깨뜨렸습니다 가공식품` | direct, frame reached transparently | 6.30 | 6.63 | 7.29 | 7.41 |
| Edge | Chromium | primary | `초대받았어요` | direct | 16.11 | 7.24 | 7.88 | 7.88 |
| Edge | Chromium | primary | `Hello 초대받았어요 world` | direct | 7.93 | 7.32 | 8.97 | 9.05 |
| Edge | iframe document | primary | `깨뜨렸습니다` | direct | 7.10 | 7.09 | 7.96 | 8.41 |
| Edge | Chromium | primary | `🙂🙂초대받았어요` | direct, bounds `(324, 418)–(516, 461)` exclude the emoji | — | — | — | — |

### Fallback

| Application | Target | Outcome | p50 | Note |
|---|---|---|---|---|
| Chrome / Edge | `<canvas>` with drawn Korean | `unsupported` | 2.20 / 2.33 | no text pattern; UIA exposes no containing semantic text |
| Chrome / Edge | raster `<img>` of Korean | `unsupported` | 2.27 / 2.33 | no text pattern |
| Chrome / Edge | `<input type=password>` | `secure` | 1.99 / 2.19 | refused on `UIA_IsPasswordPropertyId`, before any pattern is obtained |
| Chrome | browser toolbar | `not_containing` | 3.37 | nearest range returned page text 30 px below |
| Edge | sync-promo overlay | `not_containing` | — | nearest range returned overlay text 200 px away |
| WordPad | above the first line | `not_containing` | 3.83 | nearest range |
| Notepad | past the end of a line | `not_containing` | 3.20 | nearest range |
| Notepad | blank area below the text | `empty` | 2.64 | |
| Discord (Electron) | 650-point census over the window | `unsupported` 633, `not_containing` 8, `ambiguous` 5, `timed_out` 3, `not_korean` 1 | 1.66 (p95 3.02, max 61.45) | outcome counts only; **no text read was printed or stored** |

Every fallback row above reaches the unchanged capture-and-OCR path.

## Commands run

| Command | Result |
|---|---|
| `python -m ruff check packages packaging tests tools benchmarks` | clean |
| `python -m mypy packages packaging tests tools benchmarks` | 26 errors, **exactly the baseline at `456500e`** (POSIX-only stdlib attributes reported because mypy is running on Windows; CI runs it on Ubuntu) |
| `python -m pytest --suite portable` | `15 failed, 1976 passed, 101 skipped, 2 errors`. Baseline at `456500e`: `15 failed, 1961 passed, 101 skipped, 2 errors`. **The failing and erroring sets are identical**; the 15 extra passes are exactly this wave's portable cases |
| `python -m pytest --suite native` | `105 passed, 33 skipped`, no failures, including the 62 new Windows cases |
| `python -m pytest --suite packaged` | `1 failed, 2 passed` |

### Every pre-existing failure, reproduced and attributed

| Count | Case | Cause |
|---|---|---|
| 12 | `benchmarks/dev/tests/test_easyocr_stages.py` | `OSError [WinError 1114]` loading `torch\lib\c10.dll`. Torch imports standalone in this venv but fails to initialize inside the test process |
| 1 | `benchmarks/dev/tests/test_ocr_benchmark.py::test_peak_memory_is_readable_without_psutil` | `resource.getrusage` is POSIX-only |
| 1 | `benchmarks/dev/tests/test_corpus.py::test_a_committed_manifest_cannot_carry_a_machine_specific_path` | benchmark corpus manifest carries a machine-specific path |
| 1 | `tests/test_release_version.py::test_installed_metadata_matches_the_declared_source_of_truth` | the editable install reports `0.5.2` while `pyproject.toml` declares `0.5.3` |
| 2 errors | `tests/test_direct_text_routing.py::test_only_a_bounded_route_label_reaches_the_trace` | pytest writes the parametrized id into `PYTEST_CURRENT_TEST`; the deliberately oversized id exceeds Windows' 32767-character environment-variable limit. Teardown only — the case itself passes |
| 1 | `tests/packaged/shared/test_packaged_desktop.py::test_the_frozen_worker_becomes_ready_on_an_isolated_profile` | the same torch `c10.dll` failure inside `dist/windows/hanly-desktop`, a bundle built 2026-09-15 that contains none of this wave's code |

None were fixed: they are unrelated to this wave, and the run's instruction was to record rather than repair them.

## End-to-end through the production path

`default_text_acquisition()` on this host returns a `DirectTextService`; a real
submission over WordPad, on the service's own worker thread with `bind_worker`
applied, delivered:

```
(700,195) direct  '초대받았어요'  cursor=1  source=accessibility  (682,182)-(772,208)  native 21.46 ms cold / 3.98 ms warm
(740,240) direct  '초대받았어요'  cursor=2  source=accessibility  (712,234)-(802,260)  native 3.74 ms
(616,168) not_containing                                                             native 4.75 ms
close     clean
```

`source` stays the coordinator's own `"accessibility"` label on both platforms.
It is diagnostics-only, never traced, and making it platform-specific would put
platform knowledge back into the common policy.

## Limitations

- **Only 100% scaling exists on this machine.** 125%, 150% and 200% were not
  exercised, and neither was a mixed-DPI transition. The identity transform is
  what the machine proves; the pointer-containment rule is what would refuse a
  mismatch, and the rectangle conversion is covered by automated cases at
  fractional and negative coordinates.
- **A higher-integrity target was not exercised.** Triggering UAC while the user
  is away was not authorized, so access-denied is covered by a deterministic
  boundary test in which every property and pattern call refuses.
- **VS Code and Brave were not separately attributed**: both were maximized over
  the same rectangle and the census reached only the topmost window. Discord is
  the Electron data point.
- **Notepad's text pattern was absent on a first probe** from a background STA
  client and present from the adapter's own MTA client. Both are safe: absence
  is an `unsupported` fallback.
- The lookup pipeline, popup, dictionary, ROI, capture and OCR paths were not
  touched and were not re-validated beyond the suites.

## Next safe action

Phase B deep review of this wave, on explicit human authorization, with the
human choosing the reviewer and ecosystem.
