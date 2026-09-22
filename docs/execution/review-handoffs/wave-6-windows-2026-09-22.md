# Wave 6 Windows Review Handoff

## Bundle

- Member issues: Wave 6 — Windows UI Automation as the second native direct-text source.
- Implementation ecosystem: Windows 10 Enterprise 22H2 (10.0.19045), AMD64, CPython 3.13.11 in `C:\Hanly\.venv`.
- Date: 2026-09-22.
- Starting commit: `456500e`. Product boundary: `73b7372` (`feat: add windows accessible text acquisition`), followed by this handoff's own `docs:` commit.
- **Phase B has not started.** No review was performed in this run.

## Implemented

- `text_acquisition_uia.py` — a `ctypes` UI Automation adapter behind the existing app-owned `DirectTextProvider` boundary, returning normalized `DirectText`.
- A Windows branch in `default_text_acquisition()`, beside the macOS one, split into `_darwin_coordinator()` and `_windows_coordinator()`.
- `DirectTextCoordinator.bind_worker()` / `release_worker()`, called by `DirectTextService._work()` and forwarded to optional provider thread hooks. This is the one common-contract change.
- 77 tests: 62 Windows-native, 10 platform/import, 4 service lifecycle, 1 packaging.

## Main expected behavior

A stable pointer over Korean text in any Windows control that exposes a UIA text pattern now reaches the dictionary without a screen capture, with the exact word narrowed from the line and retained by its own rectangle. Everything else — no text pattern, a password field, off-screen content, access denied, a nearest rather than a containing range, non-Korean under the pointer, empty, or too slow — reaches the unchanged capture-and-OCR path, exactly once, invisibly. The user-facing lookup mode is unchanged.

## Architecture / seams touched

- `DirectTextProvider` gains a second implementation; the interface is unchanged.
- **Every acceptance rule stayed in `text_acquisition.py`.** The adapter reports a line, a cursor index and a rectangle, and decides nothing.
- `DirectTextService` keeps its one-active/one-pending latest-wins behavior, one-shot delivery, watcher sleeping, shutdown semantics and exactly-once OCR fallback. Only the bind/release wrapper around its loop is new.
- `hanly` is untouched. No COM, platform or geometry type entered the engine, and a new test enforces that the engine names no operating-system module at all.
- macOS selection is unchanged and is asserted by a test: `AccessibilityTextProvider` behind `accessibility_trusted`.
- No packaging surface changed and **no dependency was added**.

### The common-contract change, and why Windows required it

A COM apartment belongs to a **thread**, not a process. `CoInitializeEx` must run on the service's worker and `CoUninitialize` on that same thread, and nothing in the existing design told a provider when that thread began or ended. The hooks use the same duck-typed optional-capability pattern the coordinator already uses for `refine_bounds`, so `AccessibilityTextProvider` — which offers neither — is untouched. A provider that raises from a hook is still driven, because a worker that refused to start would leave every hover waiting for an outcome that never arrived.

The run produced its own evidence for why balance matters: a thread that died inside an apartment it never left disconnected the next thread's COM objects.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/text_acquisition_uia.py` (new, 780 lines: ~100 of constants and measured facts, ~260 of typed COM plumbing, ~170 of geometry and offset helpers, ~250 of the provider)
- `packages/hanly-app/src/hanly_app/text_acquisition.py`
- `tests/native/windows/test_text_acquisition_uia.py` (new)
- `tests/test_text_acquisition_platform.py` (new)
- `tests/test_text_acquisition_service.py`, `tests/test_packaging.py`
- `docs/execution/checkpoints/wave-6-windows-2026-09-22.md` — environment, measurements and limitations in full

## Binding and packaging decision

UI Automation is bound through `ctypes`, the way `text_acquisition_ax.py` binds the macOS accessibility API. `comtypes` was not installed and is not needed: four interfaces are used out of a very large library, and a COM code-generation dependency would have become a runtime requirement on macOS and Linux too. `collect_submodules("hanly_app")` already carries the new module into every artifact, exactly as it already carries the macOS adapter, so the spec needed no change. A test asserts that no COM binding entered the manifest and that the spec names no Windows-only hidden import for this.

## What UI Automation was measured doing

Every vtable slot was confirmed against the running system rather than transcribed, because a wrong slot is an access violation and not an error code.

- **`RangeFromPoint` really does answer about the nearest text.** Observed answering about a WordPad line 14 px above the pointer, and about an Edge sync-promo overlay 200 px away. Both became `not_containing` refusals.
- **Chromium counts code points and RichEdit counts UTF-16 code units** in `MoveEndpointByUnit(Character)`. On `🙂🙂초대받았어요` the UTF-16 offset yields `받았어요` in Chromium and the correct `초대받았어요` in RichEdit. The adapter asks both ways and keeps only the span whose text is the text it asked for.
- **The cursor index is taken from the text before the pointer**, which both providers agree on, because a returned string decodes to code points either way.
- **Chromium and Edge expose a text pattern on password inputs**, so `UIA_IsPasswordPropertyId` is checked before any pattern is obtained. There is no `UIA_IsPasswordAttributeId`; the element property is the real check.
- **`UIA_IsHiddenAttributeId` reports `True` for plainly visible Chromium text.** It is not used.
- **UIA's call timeouts have a 50 ms floor**; anything lower returns `E_INVALIDARG`. Defaults are 2 s connection and **20 s transaction**. Both are set to the floor so a wedged provider holds the one worker for 50 ms rather than 20 seconds. The caller's 40 ms deadline remains authoritative and is still enforced by the existing watcher; nothing here claims a Python future can cancel a synchronous COM call.

## Correctness and latency

Real applications, synthetic Korean fixtures, 40 warm samples per point, through the real adapter and coordinator. The full matrix is in the checkpoint.

- **Direct**: WordPad `RICHEDIT50W` (p50 8.0 ms, p95 10.2), Notepad `Edit` (p50 7.1, p95 8.0), Chrome on the **negative-origin monitor** (p50 6.6–7.1, p95 7.3–8.3), Chrome iframe, Edge, Edge iframe. Every one returned the exact Korean word, a cursor index that tracked the pointer across the line, and a rectangle containing the pointer and enclosed by the line.
- **Fallback**: `<canvas>` and raster `<img>` → `unsupported`; password input → `secure`; browser chrome and an Edge overlay → `not_containing`; blank areas → `empty`.
- **Electron**: a 650-point census over Discord gave `unsupported` 633, `not_containing` 8, `ambiguous` 5, `timed_out` 3, `not_korean` 1, p50 1.66 ms. Outcome counts only — no text read there was printed or stored.
- **Cold** first read is 13–32 ms, inside the 40 ms budget but the closest any measurement came to it.

## Privacy verification

- The adapter never places recognized text in an exception, a return value other than `DirectText`, or a log; it returns `None` on every refusal.
- A secure control returns `text=""`, `bounds=None`, `secure=True`, before any text pattern is obtained.
- The hover trace still carries only the outcome name, duration and a boolean; `test_direct_text_routing.py` already enforces that and passes unchanged.
- All persisted evidence in the checkpoint is synthetic Korean fixtures. The Discord census records outcome counts only. Nothing was written under the repository; the fixtures and browser profiles lived in the session scratchpad and were deleted, and every application opened for validation was closed.

## Implementation-side validation already run

| Check | Result |
|---|---|
| `ruff check packages packaging tests tools benchmarks` | clean |
| `mypy packages packaging tests tools benchmarks` | 26 errors, **exactly the baseline at `456500e`**; all are POSIX-only stdlib attributes reported because mypy ran on Windows, and CI runs it on Ubuntu |
| `pytest --suite portable` | `15 failed, 1976 passed, 101 skipped, 2 errors`; baseline `15 failed, 1961 passed, 101 skipped, 2 errors`. **Failing and erroring sets identical**; the 15 extra passes are this wave's portable cases |
| `pytest --suite native` | `105 passed, 33 skipped`, no failures, including the 62 new Windows cases |
| `pytest --suite packaged` | `1 failed, 2 passed` |
| Production path, live | `default_text_acquisition()` → `DirectTextService` → worker → adapter, over WordPad: `direct`, exact word, correct cursor, pointer-containing bounds, clean close |

Every failure was reproduced and attributed; the table is in the checkpoint. Twelve are torch's `c10.dll` failing to initialize on this machine, one is POSIX-only `resource`, one a machine-specific benchmark manifest, one a stale editable install reporting `0.5.2`, two are pytest writing an oversized parametrized id into a Windows environment variable during teardown, and the packaged one is the same torch failure inside a bundle built on 2026-09-15 that contains none of this wave's code. None were fixed.

## Known limitations / intentionally unvalidated areas

- **Only 100% scaling exists on this machine.** 125%, 150%, 200% and mixed-DPI transitions were not exercised. Qt makes the shell per-monitor-aware-v2, and UIA, `GetCursorPos`, pynput and `mss` were all observed reporting the same physical virtual-desktop pixels there, so **no transform is applied**. Rectangle conversion at fractional and negative coordinates is covered by automated cases, and the coordinator's pointer-containment rule is what would refuse a mismatch if one ever appeared.
- **A higher-integrity target was not exercised.** Triggering UAC while the user was away was not authorized. Access-denied is covered by a deterministic case in which every property and pattern call refuses.
- **VS Code and Brave were not separately attributed**: both were maximized over the same rectangle and the census reached only the topmost window. Discord is the Electron data point.
- **Notepad's text pattern was absent on one probe** from a background STA client and present from the adapter's own MTA client. Absence is a safe `unsupported` fallback either way, but the inconsistency is real.
- **A job pending behind a busy worker is not watched** until the worker picks it up. This is pre-existing macOS-reviewed behavior; on Windows the 50 ms native floor is what bounds it, in place of the macOS messaging timeout.
- `CoUninitialize` raises two first-chance `RPC_E_DISCONNECTED` while dropping a cross-process connection and handles both. The count does not grow with the number of reads, so nothing is leaking; two native tests disable pytest's fault handler so the run's output stays readable.
- The lookup pipeline, popup, dictionary, morphology, ROI, capture and OCR paths were not touched and were not re-validated beyond the suites.
- The frozen bundle was **not rebuilt**, because no dependency or packaging surface changed.

## Suggested review targets

- `_narrowed()` and `_span_offsets()`: the candidate-plus-verification scheme is the whole defence against the Chromium/RichEdit disagreement. Worth asking whether refusing when neither candidate matches is right, and whether two candidates are the right bound.
- `_cursor_index()`: it accepts any prefix the line starts with. Consider whether a provider returning a shorter-but-matching prefix could place the cursor wrongly.
- `_rect_for_point()`: returning a single non-containing rectangle so the policy layer can refuse it with evidence, versus refusing in the adapter.
- `bind_worker` / `release_worker` on `DirectTextCoordinator`: whether the optional-hook shape is the right seam, and whether swallowing a hook's exception is right.
- `_MAX_LINE_CHARACTERS = 4096` and the outright refusal above it.
- The `_UIABridge` release paths: whether any `finally` is missing on an error branch. The fake-bridge ledger asserts balance for the paths it drives, but it cannot see a native early return.
- Whether `TextSelection.source` should distinguish the two acquisitions, given that today both say `"accessibility"`.

## Review assignment

Human-selected after implementation. Not started.

## Final cross-platform review — 2026-09-22

**Changes required.** The final review committed six narrow fixes, including
pending deadlines, failed-bind refusal, COM/security hardening and secure AX
subroles. Earlier claims that pending work is bounded by the 50 ms native floor
and that failed binding can safely continue are superseded. Snapshot/cursor
validation and dispatcher recovery remain merge blockers; fresh Windows OCR
fallback and current-source frozen-artifact evidence are still required.
See [the final review report](../reports/final-text-acquisition-review-2026-09-22.md)
for reproductions, all gate results, dispositions and exact next actions. Nothing
was pushed or merged.
