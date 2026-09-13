# Hanly Super QA Report

**Run date:** 2026-09-13  
**Repository:** `/Users/thiago/Projects/hanly`  
**Commit tested:** `900dba1` (`v0.5.0`, `main`, clean at test start)  
**Host:** macOS, arm64, Python 3.13.11 in `.venv`  
**Packaged artifact:** `dist/macos/Hanly.app` (embedded Python 3.10.20, reported app version `0.1.3`)  
**Scope:** read-only QA. No production files or tests were modified. This report is the only intended repository artifact.

## Executive verdict

**Overall: BLOCKED / UI cannot be approved from this host.**

The reusable lookup engine, provider composition, dictionary path, hover state
logic, update service, startup mocks, packaging inventory, and benchmark tooling
are healthy under deterministic tests. The real native UI path cannot be
validated on this host because child GUI processes have no usable screen:

1. Packaged `--self-check ui` exits with `SIGABRT` while creating Qt.
2. Control Center integration fails before the page is usable; the child has no
   primary screen and pywebview reaches an unsafe `QScreen.geometry` call.
3. Cocoa popup construction exits with `SIGABRT` in the Objective-C bridge.
4. Native process-lifecycle checks cannot inspect children because this sandbox
   denies `/bin/ps`; these results are environment-blocked, not proof of a
   product defect.

The packaged worker path is healthy: the isolated frozen self-check recognized
Korean text, ran Kiwi morphology, and returned a KRDICT entry. That does not
prove UI health, and the UI findings must be repeated in a normal visible macOS
session before they are classified as confirmed product defects.

## Evidence summary

| Area | Result | Evidence |
|---|---|---|
| Ruff | PASS | `All checks passed!` |
| Mypy | PASS | `Success: no issues found in 196 source files` |
| Broad non-native suite | PASS | `1182 passed, 1 skipped in 10.82s`, excluding native GUI integration, app-update handoff, and Qt popup files |
| Engine/provider focused tests | PASS | 125 passed in 4.58s |
| Capture/hotkeys/permissions | PASS | 123 passed in 0.68s; mocked/contract coverage |
| Hover logic | PASS | 83 passed in 1.75s; popup-native path excluded by crash |
| Updates | PASS | 108 passed in 0.82s; native Darwin handoff failures remain |
| Startup/runtime/application | PASS | 93 passed in 0.70s; GUI startup not represented by mocks |
| Packaging/release tests | PASS | 199 passed in 1.35s |
| KRDICT tooling | PASS | 49 passed, 1 skipped in 1.87s |
| Developer benchmark tests | PASS | 60 passed in 0.35s |
| Frozen worker self-check | PASS | `ok: true`; runtime, worker, OCR, morphology, dictionary all passed |
| Frozen UI self-check | FAIL / abort | exit 134; fatal native abort during `ensure_qt_application` |
| Control Center integration | BLOCKED / fail | no-screen child fails before usable page; run stopped after 246.60s |
| Qt popup window | BLOCKED / abort | isolated no-screen test process exits 134 in Cocoa native bridge |
| Qt WebEngine startup | BLOCKED / abort | `Cannot create window: no screens available`; 1 failed, 1 skipped |

## Findings requiring review

### SUPERQA-001 — Packaged UI self-check aborts before producing a report

**Severity:** Critical / release blocker.  
**Status:** Reproducible on this host; likely environment-sensitive and needs a
normal visible macOS retest before being called a product crash.

**Reproduction:**

```text
./dist/macos/Hanly.app/Contents/MacOS/hanly-desktop --self-check ui
```

**Observed:** exit code `134` (`SIGABRT`). Stderr contains Apple pasteboard/XPC
errors followed by a fatal Python abort. The fatal frames are:

```text
hanly_app/qt_bootstrap.py:58 in ensure_qt_application
hanly_app/control_center_host.py:348 in _load_webview
hanly_app/self_check.py:186 in _run_window
```

No JSON self-check report is emitted. A CUA launch of the same repository bundle
started a Hanly process, but its accessibility state timed out, so no
interactive UI feature could be verified.

**Impact:** This environment cannot complete the UI readiness probe. The lack of
a graceful “no screen” failure is itself a robustness concern, but the release
impact is unconfirmed until a normal visible desktop is tested.

**Suggested next test:** Run the exact command from a normal Terminal session
with the same bundle and on a clean macOS account. Capture the native crash
backtrace and compare with a source `python -m hanly_app --self-check ui` run.
The expected minimum is one visible display and a successful Qt/WebEngine
window, not merely a nonzero JSON status.

### SUPERQA-002 — Control Center has no headless/no-screen failure path

**Severity:** High robustness risk; environment-blocked product confirmation.  
**Status:** Reproducible only in the current screenless child environment.

**Observed traceback:**

```text
.venv/lib/python3.13/site-packages/webview/platforms/qt.py:343
self.screen = QScreen.geometry(QApplication.primaryScreen())
TypeError: geometry(self): first argument of unbound method must have type 'QScreen'
```

Installed versions are pywebview `6.2.1` and PyQt6 `6.11.0`. The same run also
reports `QT QtMsgType.QtFatalMsg Cannot create window: no screens available`.
The pywebview line is reached with `QApplication.primaryScreen()` unavailable,
so this run does not prove a normal-screen version incompatibility.

The lifecycle report had `page_reached_the_bridge: false` and
`running_after_open: false`.

**Impact:** The Control Center page does not reach the bridge in this
environment. A robustness improvement would convert no-screen/native-init
failures into a diagnostic result rather than an abort, but normal desktop
behavior remains to be tested.

**Suggested upgrade:** First rerun with a real visible screen. If it reproduces,
pin or constrain a known-compatible pywebview/PyQt6 pair or add a narrow
compatibility/no-screen guard before window creation. Re-run layout, lifecycle,
webengine, and packaged UI gates. Do not silently fall back to another GUI
backend.

### SUPERQA-003 — Cocoa popup construction aborts in the Objective-C bridge

**Severity:** High robustness risk; environment-blocked product confirmation.  
**Status:** Reproducible in the current screenless Cocoa test process.

**Reproduction:**

```text
./.venv/bin/python -m pytest tests/test_qt_popup_window.py -q
```

**Observed:** exit code `134` (`SIGABRT`). The fatal frame is:

```text
packages/hanly-app/src/hanly_app/qt_popup.py:139
    keep_visible_when_inactive(int(self.winId()))
```

The call enters `popup_darwin.py:keep_visible_when_inactive`, which sends
Objective-C messages through a hand-built `ctypes` `objc_msgSend` bridge. The
abort occurs while constructing the first `QtPopupView`, before any popup test
can assert flags, rendering, positioning, hide, or close behavior.

**Impact:** Popup behavior cannot be tested here. A crash-free fallback is still
desirable at this ABI boundary, but a normal-screen repro is required before
calling it a confirmed product defect.

**Suggested next test:** In a temporary copy only, and after repeating on a
visible screen, guard the native call behind
a post-show native-window check or disable it to determine whether the fault is
“window does not exist yet” or an ABI/selector problem. The production fix must
retain the non-activating popup contract and provide a crash-free fallback.

### SUPERQA-004 — Native process probes are blocked by `/bin/ps`

**Severity:** High test-environment blocker; product severity unconfirmed.  
**Status:** Reproduced by the current sandbox.

Affected evidence includes `test_lookup_process_spawn.py`,
`test_desktop_startup.py`, `test_control_center_lifecycle.py`, and three Darwin
cases in `test_app_update_handoff.py`. The common error is:

```text
PermissionError: [Errno 1] Operation not permitted: 'ps'
```

The production macOS update handoff also generates a `/bin/ps` probe in
`app_update_handoff.py:232`, so this needs an unsandboxed product check even
though the current failures originate in test/OS policy.

**Impact:** Child retirement, shell isolation, and update-candidate cleanup are
not proven by this run. This is not evidence that the implementation leaks.

**Suggested upgrade:** Add a supported process-inspection fallback or make the
test harness report “inspection unavailable” instead of turning this condition
into a product-looking failure. Verify `/bin/ps` in the actual packaged context.

### SUPERQA-005 — Source is v0.5.0 while the tested bundle reports v0.1.3

**Severity:** High release/process risk.  
**Status:** Confirmed.

`git HEAD` is `900dba1`, tag `v0.5.0`; both package manifests say `0.5.0`, but
the frozen worker reports `hanly: 0.1.3` and `hanly-app: 0.1.3`. `dist/` is
ignored, so this may simply be a stale local artifact, but it must not be used
as v0.5.0 release evidence until rebuilt from the tested commit.

### SUPERQA-006 — Startup/warmup and package size dominate performance

**Severity:** Medium-to-high performance risk.  
**Status:** Measured for the frozen worker; memory leakage not measurable in the
current sandbox.

Frozen worker timing:

```text
real 9.32s, user 7.38s, sys 0.98s
runtime:        185.3 ms
lookup worker: 5555.1 ms
OCR:            1907.1 ms
morphology:     1154.0 ms
dictionary:      135.9 ms
```

Disk measurements:

```text
Hanly.app:                  1.3G
macOS onedir tree:          1.3G
macOS ZIP:                  534M
macOS DMG:                  608M
KRDICT generated database:   96M
```

Worker construction dominates. This becomes a serious UX problem if the lookup
child is retired and recreated too aggressively. The dictionary query is not
the bottleneck. Repeat RSS and warm-lookup measurements in an unsandboxed run.

## Feature-by-feature QA

### F01 — Engine contracts and lookup pipeline

**Grade:** GOOD  
**Code quality:** Clear provider seams and normalized contracts; normal
non-success is separate from processing errors.  
**Possible bugs:** None found in exercised paths.  
**Tests made:** 125 engine/provider tests passed; frozen worker passed from ROI
through OCR, morphology, and dictionary.  
**Observations:** Korean fixture lookup returned a valid entry. This is the
strongest part of the current build.

### F02 — EasyOCR provider and OCR policy

**Grade:** GOOD, with performance follow-up  
**Code quality:** Configuration and image formats are validated; malformed
results become provider errors; no Paddle selector was found.  
**Possible bugs:** None functional; first worker construction is expensive.  
**Tests made:** EasyOCR tests passed within the 125 engine/provider tests and
the frozen OCR self-check passed.  
**Observations:** OCR took about 1.9s in the frozen worker run.

### F03 — Kiwi morphology and KRDICT dictionary

**Grade:** GOOD  
**Code quality:** Outputs are normalized, SQLite is read-only, and schema
validation is shared across build/runtime/update paths.  
**Possible bugs:** None found in normal, empty, not-found, or provider-error
paths.  
**Tests made:** 49 KRDICT tooling tests passed with one skip; frozen dictionary
stage passed with one entry for `한국어`.  
**Observations:** Dictionary latency was about 36–136ms and is not the primary
performance issue.

### F04 — Lookup child, process transport, and lifecycle

**Grade:** MID / insufficient native evidence  
**Code quality:** Framing, bounded message size, child ownership, and close paths
are well-covered by unit tests.  
**Possible bugs:** No confirmed transport defect; retirement and shell isolation
remain unproven because process inspection is denied.  
**Tests made:** Unit/transport tests passed; real child integration failed when
the fixture called `ps`.  
**Observations:** Frozen worker construction and close succeeded; repeat with
native process inspection enabled.

### F05 — Capture, ROI selection, hotkeys, and permissions

**Grade:** GOOD in deterministic tests; LIVE status unverified  
**Code quality:** Services are isolated behind seams and platform adapters;
permission states distinguish denied, missing, and unknown.  
**Possible bugs:** No deterministic defect; actual capture, DPI, multi-monitor
coordinates, and global hotkey delivery were not live-verified.  
**Tests made:** 123 capture/hotkey/permission tests passed.  
**Observations:** This is contract-level confidence, not a manual desktop pass.

### F06 — Hover controller, debounce, retention, and stale results

**Grade:** GOOD for orchestration; popup presentation blocked  
**Code quality:** Hover decision-making is separate from observation and OCR;
latest-wins and retention rules are covered.  
**Possible bugs:** None found in 83 focused hover tests.  
**Tests made:** 83 hover tests passed; popup-native test process aborts.  
**Observations:** The path is blocked at the final UI surface, not hover logic.

### F07 — Popup rendering, positioning, hide/close, and non-activation

**Grade:** BLOCKED / unconfirmed  
**Code quality:** Responsibilities and intended flags are explicit, but the
macOS visibility workaround is a high-risk ABI boundary with no safe fallback.
  
**Possible bugs:** SUPERQA-003; current repro may be caused by the screenless
child environment.  
**Tests made:** `tests/test_qt_popup_window.py` exits 134.  
**Observations:** Do not accept the popup capability based on static flags or
mocked controller tests.

### F08 — Control Center and bridge

**Grade:** BLOCKED / unconfirmed  
**Code quality:** Assets and bridge contracts have broad pure tests; the host
explicitly requires Qt.  
**Possible bugs:** SUPERQA-001 and SUPERQA-002; both need a visible-screen
retest.  
**Tests made:** Pure Control Center tests passed; layout/lifecycle integration
fails before bridge reachability.  
**Observations:** Start/stop, settings, runtime state, resources, updates, and
quit cannot be graded as working through the real page.

### F09 — Startup, first run, runtime config, and shell lifecycle

**Grade:** MID / UI blocked  
**Code quality:** Entry ordering, diagnostics, first-run provisioning, and
runtime factory composition are strongly tested.  
**Possible bugs:** Actual packaged UI startup is blocked by SUPERQA-001; source
desktop startup did not produce its report on this host.  
**Tests made:** 93 startup/runtime/application tests passed; frozen worker passed;
packaged UI self-check aborted.  
**Observations:** Worker readiness is healthy, shell/UI readiness is not.

### F10 — Update service, handoff, rollback, and cleanup

**Grade:** MID  
**Code quality:** Resource update tests cover checksum, schema, atomic activation,
rollback, and serialization.  
**Possible bugs:** SUPERQA-004 blocks three Darwin handoff cases; LaunchServices
also reported `kLSNoExecutableErr` for synthetic fixture apps.  
**Tests made:** 108 update/coordinator tests passed; Darwin handoff isolation
reported 154 passed, 3 failed, and 2 skipped before additional native cases
were stopped.  
**Observations:** Retest with a real executable bundle and native process tools.

### F11 — Packaging, frozen inventory, and release gates

**Grade:** GOOD for worker/inventory; UI gate blocked  
**Code quality:** One entry point is enforced and the worker self-check uses real
frozen providers.  
**Possible bugs:** SUPERQA-005 stale local artifact; SUPERQA-001 UI gate failure.
  
**Tests made:** 199 packaging/release tests passed; packaged dependency and
worker integration passed (`2 passed`); deep strict ad-hoc codesign verification
returned no error.  
**Observations:** Rebuild `dist/` from `v0.5.0` before release evidence.

### F12 — Benchmark and observability tooling

**Grade:** GOOD as tooling; live telemetry insufficient  
**Code quality:** Tests cover bounded telemetry, privacy redaction, summaries,
and failure handling.  
**Possible bugs:** No tooling defect; live RSS/process sampling is blocked by
process-inspection restrictions.  
**Tests made:** 60 benchmark tests passed; frozen worker timing captured.  
**Observations:** The tooling is ready for an unsandboxed performance run.

## Code quality assessment

**Grade:** GOOD overall, with two dangerous native boundaries.

- Ruff and mypy are clean.
- Package direction and provider seams are preserved.
- The engine models success, normal non-success, and errors well.
- The test suite is extensive and mostly deterministic.
- The Objective-C popup bridge and Qt/pywebview compatibility boundary need
  stronger runtime guards and native smoke coverage.
- Broad exception handling appears intentional at process/UI boundaries, but a
  follow-up review should verify that every swallowed exception is reported and
  that fatal native calls are not assumed catchable by Python `try` blocks.

## Recommended follow-up order

1. Reproduce SUPERQA-001, SUPERQA-002, and SUPERQA-003 in a normal visible,
   unsandboxed macOS session; only then fix confirmed native failures.
2. If SUPERQA-002 reproduces with a screen, resolve it by pinning/adapting the
   pywebview/PyQt6 pair, then run layout, lifecycle, webengine, and packaged UI
   gates.
3. Rebuild `dist/` from `900dba1` and rerun worker plus UI packaged gates.
4. Repeat process-retirement, update-handoff, desktop-startup, and memory tests
   where `/bin/ps` and LaunchServices are available.
5. Only after UI stability, manually exercise launch, Control Center, runtime
   state, capture start/stop, target/ROI selection, hotkey lookup, popup
   retention/dismissal, resource update, quit, and relaunch.

## Delegation note

Ten GPT-5.6 Luna reviewers were requested in parallel at high reasoning effort,
split across the ten subsystem slices described in the kickoff. The thread
creation API returned setup handles (`clientThreadId`) but did not expose
readable task IDs/results during this run, so no subagent output is represented
as evidence here. All findings above come from direct repository inspection and
executed commands listed in this report.
