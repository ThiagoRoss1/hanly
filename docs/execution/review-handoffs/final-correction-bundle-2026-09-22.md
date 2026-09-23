# Final Correction Bundle Review Handoff

## Bundle

- Member scope: the corrections required by the independent review of the
  final text-acquisition review (`9962505..9b80ad4`): F3, F4/N2, N1, N4, F5
  hardening, F13, and the human-approved OCR architecture decision.
- Implementation ecosystem: Claude Opus 5.5, macOS 26.6.2 arm64,
  `.venv/bin/python` 3.13.11. No Windows or Linux host was used.
- Date: 2026-09-22. Branch `visual/interface-update`, starting at `9b80ad4`.
  Every earlier commit is unchanged; nothing was pushed, merged, rebased,
  amended or squashed.
- **Phase B has not started.** This handoff prepares a review; it performs none.

| Commit | Boundary |
|---|---|
| `6323a9e` | `fix: bind native text refinement to one snapshot` |
| `6510309` | `fix: verify UIA cursor positions exactly` |
| `289508f` | `fix: balance native acquisition lifecycle` |
| `ff309ab` | `fix: trace rejected direct-text delivery` |
| `6debf3c` | `test: verify packaged source identity` |
| `8eca4bd` | `docs: approve platform OCR selection` |
| `b2ace42` | `docs: preserve final review guidance` |

## Implemented

- **F3.** `refine_bounds` now receives the line originally read
  (`line=`) and both adapters refuse unless the re-read line is exactly equal.
  Security and offscreen checks during refinement are unchanged. A reader whose
  `refine_bounds` cannot take the line fails closed (`AMBIGUOUS`). No native
  object leaves the worker, and there is no new public token contract.
- **F4/N2.** UIA derives the caret position from a prefix and a suffix, which
  together must rebuild the line exactly. It then asks both neighbours of the
  caret for one UIA Character each. Exactly one must return the expected
  character with a rectangle containing the pointer; otherwise the read is
  refused. This covers caret-before and caret-after providers without dividing
  any rectangle. A line whose own rectangle already misses the pointer is still
  reported with that geometry, so the policy layer keeps its `not_containing`
  and `ambiguous` reasons.
- **N1.** The worker calls `release_worker()` only when `bind_worker()`
  succeeded (`bind_worker` now returns whether it did).
- **N4.** UIA's line and span clones are released even when `expand` or
  `MoveEndpointByUnit` raises. The new cursor helpers use `try/finally`
  throughout. AX was audited: it clones no ranges, and every CF object it
  creates is already released in a `finally`, so it needed no change.
- **F5.** A dispatcher rejection is caught inside `deliver`, so it can no
  longer escape into the worker. It emits `hover_direct_text_dispatch_failed`
  with only the hover request id and the exception class. An outcome arriving
  after hover shutdown is suppressed before the dispatcher is touched. There is
  no new timer, queue, recovery path or public contract.
- **F13.**
  - `verify_source_identity()` in `tools/smoke_packaged_runtime.py` reads the
    bundle's own `hanly_app/assets/hanly-build.json` from disk. It compares the
    commit, version, platform and architecture with an explicitly supplied
    expectation.
  - The packaged gate requires `HANLY_EXPECTED_SOURCE_COMMIT`. It skips locally
    without it and fails under `HANLY_REQUIRE_PACKAGED`.
  - CI passes `${{ github.sha }}`, the same value the build step stamps.
  - The package-version check is unchanged.
- **OCR decision.** `docs/architecture/DECISION-2026-09-22-ocr-backend.md`
  records the approved decision and synchronizes 01–03, their visuals,
  `AGENTS.md` and `CLAUDE.md`.
- **Scaffolding.** The two review-preparation files are committed, each with a
  status note marking it as executed.

## Before / after reproductions

The same scratch probes from the independent review, run before and after the
fixes. All reproduction text is synthetic.

| Case | Before | After |
|---|---|---|
| UIA same-length line change `초대`→`사과` between read and refine | `direct`, old word, new rectangle | `ambiguous` |
| UIA different element (same length) at refinement | `direct` | `ambiguous` |
| AX same-length line change | `direct` | `ambiguous` |
| UIA shorter matching prefix at index 2 | `direct`, cursor 1 | `unsupported` → OCR |
| UIA caret after the character, pointer on `초` of `초대` | `direct`, cursor 1 (`대`) | `direct`, cursor 0 |
| UIA caret after the last syllable | `not_korean` | `direct`, correct cursor |
| Dispatcher raises after accepted submission | exception into the service thread; no capture | traced by class; no capture (by design) |
| Stale `cb2d437` bundle against `HEAD` | packaged identity passed on version | fails: `source_commit 'cb2d437…', expected …` |

The new regressions were run against the pre-correction code:
- 34 cursor/caret cases failed before the fix, and all 111 in the UIA boundary
  file pass after it.
- The N1 case and three native-raise cases failed before the fix and pass
  after it.

## Validation

| Check | Result |
|---|---|
| `python -m pytest` (full, `HANLY_EXPECTED_SOURCE_COMMIT=6debf3c…`) | **2351 passed, 1 failed, 2 skipped** — the failure is N5 below |
| `python -m pytest --suite native` | **110 passed** |
| `python -m pytest --suite packaged` on the ZIP-reconstructed fresh app, `HANLY_REQUIRE_PACKAGED=1` | **3 passed, 1 failed** (N5): inventory, isolated-profile worker (frozen OCR + morphology + dictionary) and **source identity** pass |
| `python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `python -m mypy packages packaging tests tools benchmarks` | Success, 285 source files |
| Windows fake-provider file on macOS (real-COM cases deselected) | 59 passed |

Skips: the opt-in real-EasyOCR inference case and the non-macOS Vision case.

### Current artifact source identities

| Artifact | `source_commit` | Version | Built |
|---|---|---|---|
| `dist/macos/Hanly.app` (fresh) | `6debf3c949d0f06a6e81c8f4e9406a42cd7b2cbc` | 0.5.3 | 2026-09-23T02:40:37Z |
| `dist/reconstructed/Hanly.app` (from the fresh ZIP) | `6debf3c…` | 0.5.3 | same build |
| Previous `dist/macos/Hanly.app` (replaced) | `cb2d437…` (predates the branch base) | 0.5.3 | 2026-09-15 |
| Windows | **none built** | — | — |

No packaged file changed after `6debf3c`; the two later commits are
documentation only. The earlier passing packaged gate on the stale bundle was
never evidence for this branch.

## Evidence classes

1. **Verified on macOS now:**
   - AX snapshot refusal, through portable tests and the Mac-native AX units.
   - The native suite.
   - A fresh macOS artifact whose source identity matches, and whose frozen
     worker constructs its providers on an isolated profile.
   - The OCR decision's cited measurements, checked against their source
     reports.
2. **Proven only by deterministic portable tests:**
   - All UIA behaviour: snapshot equality, prefix/suffix and per-character
     verification under both caret models and both unit models, clone cleanup,
     and refusal reaching capture exactly once.
   - Service bind/release balance.
   - Dispatcher tracing and shutdown suppression.
   - The source-identity rules.
3. **Still requiring real Windows confirmation:** everything in the Windows
   list below. In particular, nobody has observed a real Chromium or RichEdit
   provider answering the one-Character range with the expected text and a
   pointer-containing rectangle.
4. **Unavailable:** a current Windows artifact. A green macOS frozen Control
   Center check, which is blocked by N5.

## Required Windows continuation evidence

Merge readiness also depends on this run, on a clean Windows 10/11 host:

```powershell
git checkout visual/interface-update; git rev-parse HEAD
py -3.13 -m venv .venv; .venv\Scripts\python -m pip install --group dev
.venv\Scripts\python -m pip install -e packages/hanly -e "packages/hanly-app[runtime]"
.venv\Scripts\python -m pytest --suite portable
.venv\Scripts\python -m pytest --suite native
.venv\Scripts\python -m ruff check packages packaging tests tools benchmarks
.venv\Scripts\python tools\build_package.py
$env:HANLY_EXPECTED_SOURCE_COMMIT = (git rev-parse HEAD)
$env:HANLY_REQUIRE_PACKAGED = "1"
.venv\Scripts\python -m pytest --suite packaged
```

Evidence required:
- [ ] A clean install reports version 0.5.3.
- [ ] The Torch `c10.dll` (WinError 1114) failure is resolved or conclusively
  diagnosed.
- [ ] A forced real production OCR fallback: a hover that UIA refuses (for
  example a raster image, or `<canvas>`) reaches capture and EasyOCR through
  the lookup child.
- [ ] Chromium and RichEdit: every syllable across complete words resolves to
  the correct cursor on left and right halves. Record whether each provider
  leaves the caret before or after the character.
- [ ] Password and offscreen properties answer `VT_BOOL` False on ordinary
  controls. If they don't, direct text falls back silently to OCR.
- [ ] The timed `IUIAutomation2` client is created and both timeout setters
  return `S_OK`.
- [ ] A current packaged artifact whose `source_commit` equals `HEAD`.
- [ ] Remote Ubuntu CI confirms the `fabceb8` typing fix once a separately
  authorized push happens.

## Findings

**Fixed now:**
- **F3:** snapshot coherence (`6323a9e`).
- **F4/N2:** UIA cursor and caret side (`6510309`).
- **N1:** bind/release balance (`289508f`).
- **N4:** UIA clone leak when a native call raises (`289508f`).
- **F5:** dispatcher rejection escaping into the worker; now traced and
  shutdown-aware (`ff309ab`).
- **F13:** version-only packaged identity (`6debf3c`).
- **Architecture:** the Vision decision was never synchronized into the
  authoritative documents (`8eca4bd`).

**Deferred:**
- **N5 — P1, release-blocking. The frozen Control Center check fails on every
  platform since `6c02d03`.** *Fixed in `d607740`; see the outcome section below.*
  - `self_check.UI_PROBE_ELEMENTS` still names `control-center`,
    `start-capture`, `runtime-state` and `quit-hanly`. The redesigned
    `assets/control_center/index.html` removed all four.
  - The window opens and the document loads; only the stale probe fails.
  - The redesigned page is independently exercised by the native
    Control Center tests.
  - This was invisible because the only local bundle predated the redesign,
    which is the F13 blind spot.
  - **Proposed fix:** probe IDs the redesign actually carries (likely
    `toggle-capture`, `live-runtime`, `quit-ask` and a shell element such as
    `nav`). Add a portable test asserting every probe ID exists in
    `index.html`.
  - Not fixed here: it is outside the authorized list, and choosing what the
    release gate asserts is a human decision.
  - **Trigger:** before any release build or merge recommendation.
- **F5 recovery.** A rejected outcome is traced, not recovered.
  - **Trigger:** a trace showing `hover_direct_text_dispatch_failed` while the
    runtime is active.
- **F11.** The Windows evidence above.
  - **Trigger:** the Windows continuation run.
- **F12.** `_narrowed` stops at the first candidate whose text matches.
  - It is safe, and ordinary false refusals use OCR.
  - **Trigger:** Windows evidence of lost coverage.

**Dismissed:**
- **Two candidates matching different occurrences in `_narrowed`.** Endpoint
  moves are anchored at both line ends, so a single consistent unit model
  cannot produce an equal-length match at a shifted position. Repeated-text
  cases all select the correct occurrence under both unit models.
- **AX range-clone leaks.** AX has no range clones.

## Privacy

- No recognized or accessibility text enters a trace, an error or a commit.
  - The new trace event carries a hover id and an exception class. A test
    feeds it an exception whose message holds Korean text and coordinates, and
    asserts neither appears.
  - The source-identity report holds only stamp fields.
- Freeze stays memory-only, and only explicit Export persists private content.
  Neither changed.
- Every test string is a synthetic fixture. No benchmark export, screenshot,
  crop or accessibility content was added.
- The OCR decision record keeps staged EasyOCR replay distinct from production
  `readtext()` evidence and from live Vision.

## Merge readiness

*Superseded for N5 by the outcome section below.* **Not merge-ready.** These corrections close F3, F4/N2, N1, N4, F5 and F13 on
the evidence classes above. Merge still requires:
- a fix for N5;
- the Windows continuation evidence;
- a current Windows artifact with a matching source commit;
- remote CI.

## Suggested review targets

- `_character_under` and `_caret_index` in `text_acquisition_uia.py`: whether
  refusing both-neighbours-contain (a boundary pixel) is right, and the extra
  UIA calls per read against the 40 ms budget.
- Whether the `line=` keyword on `refine_bounds` should be named on
  `DirectTextProvider`, or stay duck-typed as the capability already is.
- `verify_source_identity`: parsing the stamp without importing `hanly_app`,
  matching the harness's rule.
- The fixture move to `tests/hanly_fixtures/uia.py` and its caret model.

## Review assignment

Human-selected after implementation. Not started.

---

# N5 Packaged UI Probe Correction Outcome

- **Date:** 2026-09-23. Claude Opus 5.5, macOS 26.6.2 arm64, `.venv/bin/python`
  3.13.11. Narrow, human-authorized correction; not a review.
- **Commit:** `d607740` `fix: align packaged UI probe with control center`,
  on `67c56e9`. Earlier commits are unchanged; nothing was pushed or merged.

## Change

`self_check.UI_PROBE_ELEMENTS`, the element ids the frozen `--self-check ui`
looks up in the Control Center page, now follows the approved contract.

| Obsolete id (removed by `6c02d03`) | Replacement | Release-check meaning |
|---|---|---|
| `control-center` | `nav` | the application shell and its navigation rendered |
| `start-capture` | `toggle-capture` | the primary capture control rendered |
| `runtime-state` | `live-runtime` | runtime state can be presented |
| `quit-hanly` | `quit-ask` | the user can initiate application exit |

The rest of the UI self-check is unchanged: open the window, wait for the
document and the injected bridge, verify the controls, make the bridge round
trip, and close cleanly.

**Regression:** `tests/test_control_center.py::
test_the_packaged_window_probe_names_controls_the_shipped_page_has`.
- It parses the `id` attributes of the shipped `index.html` (loaded through
  `load_control_center_assets()`).
- It requires every value of `UI_PROBE_ELEMENTS` to be exactly one element.
  Parsed attributes rather than substrings, so `nav-bubble` cannot stand in
  for `nav`.
- It asserts the four legacy ids are not in the contract.
- It derives from `UI_PROBE_ELEMENTS` itself; there is no second list of probes.
- Against the old list it failed with `'control-center' is not one element of
  the shipped page`, and it passes against the new one.

## Validation

| Check | Result |
|---|---|
| Focused: Control Center, packaging, smoke-dictionary tests | 163 passed |
| Focused: native Control Center tests | 5 passed |
| Unfrozen `python -m hanly_app --self-check ui` | ok. Window opened and exited cleanly; document `Hanly · Control Center`; 4 controls rendered; bridge round trip |
| `python -m pytest` (full, `HANLY_EXPECTED_SOURCE_COMMIT=d607740…`) | **2353 passed, 2 skipped** (opt-in real EasyOCR inference; non-macOS Vision path) |
| `python -m pytest --suite native` | **110 passed** |
| `python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `python -m mypy packages packaging tests tools benchmarks` | Success, 285 source files |

### Fresh packaged evidence (macOS)

- Built with `tools/build_package.py` from a clean worktree at `d607740`.
- The build stamp in `dist/macos/Hanly.app` and in the app reconstructed from
  `dist/hanly-desktop-macos.zip` reads `source_commit`
  `d6077405a56c4bb064eda80ac8dd70bcc98b7082`, version 0.5.3, arm64, built
  2026-09-23T04:54:45Z.
- The packaged gate ran on the reconstructed app with `HANLY_REQUIRE_PACKAGED=1`
  and `HANLY_EXPECTED_SOURCE_COMMIT=d6077405a56c4bb064eda80ac8dd70bcc98b7082`.
  **All 4 passed:**
  - runtime inventory;
  - source identity;
  - isolated-profile frozen worker (runtime, lookup worker, OCR, morphology,
    dictionary);
  - frozen Control Center.
- `tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --window-only`
  reported every stage ok, frozen, exit 0: the window opened and its loop
  exited cleanly, the document loaded, 4 controls rendered, and the bridge made
  its round trip.
- The previous artifact (`6debf3c`) fails source identity against `d607740`,
  as intended. The older `cb2d437` bundle no longer exists locally; its failure
  was recorded above.
- Nothing was written under the ignored `artifacts/` export root during this
  run, and Git holds no bundle, stamp or capture.

Observation, out of scope: the self-check's own window uses an unconfigured
`ControlCenterBridge()`, so its bridge probe reports the default "EasyOCR"
rather than the resolved macOS backend. The desktop resolves `auto` separately
(`runtime.ocr_display_name`). This is not a failure and was not changed.

## Status

**All known macOS-side release blockers are closed** (F3, F4/N2, N1, N4, F5,
F13 and N5). The branch is still **not merge-ready** until the following exist:
- Remote CI on a pushed branch, including Ubuntu typing, the Windows and Linux
  native jobs, and the build workflow's packaged gate now given
  `HANLY_EXPECTED_SOURCE_COMMIT`.
- The Windows continuation evidence listed above: a clean install, the
  `c10.dll` diagnosis, a forced real OCR fallback, Chromium and RichEdit
  per-character caret behaviour, `VT_BOOL` False handling, the timed
  `IUIAutomation2` client, and a current Windows artifact whose source commit
  matches.

---

# Windows Release Evidence — Partial, 2026-09-23

- **Run:** Windows 10 Enterprise 10.0.19045 AMD64, CPython 3.13.11 in a new
  `.venv-final-validation`. Tested commit `cd72d05`. The human interrupted
  it to continue on macOS; it resumes on Windows later.
- **Full record and resume steps:**
  [final Windows release evidence](../reports/final-windows-release-evidence-2026-09-23.md).

| Evidence | Status |
|---|---|
| Remote CI, run `35828977851` on `cd72d05` | **success**, all 7 jobs |
| Clean install, version 0.5.3 | done; pip bootstrapped around this host's broken `ensurepip` |
| Portable / native / ruff / mypy (`--platform linux`) | 2 failed (dev-benchmark POSIX assumptions, classified) · 105 passed · clean · success |
| Torch `c10.dll` (WinError 1114) | **diagnosed**: the MSVC runtime 14.26 bundled with PyQt6-Qt6 6.10, loaded before Torch; absent with PyQt6-Qt6 6.11.2 |
| Real production OCR fallback | **not yet obtained** |
| Chromium / RichEdit cursor matrix | **not yet obtained**; the first probe attempt was invalid |
| Password/offscreen `VT_BOOL`, timeout setters, COM worker lifecycle | **not yet observed** |
| Fresh Windows artifact with `source_commit` = HEAD, packaged gate | build started, **not verified** |

**Verdict: blocked by missing evidence.** No product code changed.