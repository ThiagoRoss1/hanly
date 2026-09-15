# HAN-43, HAN-44 and Super QA — implementation review report

**Prepared:** 2026-09-13
**Branch:** `codex/han-43-44-superqa`, eight commits on top of `main` at `5f7eb2a`
**Executor:** Claude Opus 5, directly (Phase A only)
**Plan followed:** `docs/execution/han-43-44-superqa-patch-plan.md`
**Status:** implementation complete; stopped at the Review Handoff. Phase B not started.
Nothing pushed, nothing merged, no tag.

This document exists for a later reviewer. It is not the session ledger
(`docs/execution/checkpoints/han-43-44-superqa.md`) and not the Review Handoff
(`docs/execution/review-handoffs/han-43-44-superqa.md`); it repeats what those
two carry only where a reviewer would otherwise have to open them, and adds the
complete diff at the end.

It is deliberately **untracked**. `docs/execution/05-execution-plan.md` forbids
committing a diff copy into the repository, because Git already holds every diff
and a committed copy becomes a second, stale source of truth.

---

## 1. What was asked, and what was delivered

| Part | Issue | Tier proposed by the plan | Delivered |
| --- | --- | --- | --- |
| 1 | HAN-44 — packaging smoke diagnostics and failure visibility | Standard | Yes, all four required improvements |
| 2 | HAN-43 — restructure platform-specific smoke/build tests | Gate | Yes |
| 3 | Super QA — SUPERQA-001–006 | Gate | Yes; three of the six did not reproduce, two were fixed, one was measured |

Execution order was the plan's: **HAN-44 → HAN-43 → Super QA**, so that the
restructuring and the native follow-ups produced failure evidence worth reading.

### A correction worth reading before the rest

The implementation was built against the **patch plan's summary** of HAN-43 and
HAN-44, not against the issues. Linear was unauthenticated for the whole
implementation run; the plan told me to recheck readiness, and I recorded the
limitation and carried on rather than stopping to get it connected. The issues
were read directly only afterwards.

Re-checked line by line against the real text, the plan's summary turned out to
be faithful — all four of HAN-44's required updates and every one of HAN-43's
stated goals are met — but **two named fields were missing** and are closed in
`1f8354a`, and **one scope note** came out of HAN-43 that the summary did not
carry. All three are in §7. That check should have happened before the work, not
after it.

### The eight commits

| Commit | Title |
| --- | --- |
| `3e05574` | `fix: preserve packaging smoke diagnostics on failure` |
| `17c841a` | `chore: separate portable native and packaged test suites` |
| `ce94fe4` | `fix: validate packaged artifact identity` |
| `af44fd7` | `fix: report unavailable native UI and process capabilities` |
| `13de683` | `fix: read this platform's own maxrss unit when sampling memory` |
| `c6ef4bc` | `chore: record the HAN-43, HAN-44 and Super QA handoff` |
| `1f8354a` | `fix: record the two host fingerprint fields the issue names` |
| `ba87cce` | `chore: record the acceptance check against the issues themselves` |

Every message uses the required `fix:` / `chore:` prefix with brief main-topic
bullets, and **carries no agent attribution of any kind** — no
`Co-authored-by:`, no generated-by footer, no session link. That was checked
after each commit and again across the whole range.

---

## 2. HAN-44 — making one failed packaging run informative

### 2.1 Stage progress markers

`packages/hanly-app/src/hanly_app/self_check.py` now emits one flushed JSON line
per stage boundary on **stderr**, before the work it names:

```
hanly-self-check: {"event": "stage_started", "stage": "ocr"}
hanly-self-check: {"event": "stage_completed", "stage": "ocr", "ok": true, "duration_ms": 1800.1}
```

stderr rather than stdout, so the existing final-report JSON parser is untouched.
Flushed before the action, because a fatal native error never returns.

Coverage: `runtime`, `lookup worker`, `ocr`, `morphology`, `dictionary`,
`worker close`, `versions`, and on the UI side `window host`, `main window`,
`document`, `controls`, `bridge`.

Two stages are **new** and change the report shape by one entry each:

- **`worker close`** — closing the worker releases native handles and can crash.
  It used to run outside any stage, so a crash there was attributed to the last
  provider stage that passed. It is now its own stage.
- **`window host`** — importing Qt WebEngine and constructing the host used to
  run before the first stage. A frozen build that dies there produced no stage
  at all; it now names one.

`tools/smoke_packaged_runtime.py` reconstructs progress from the **full** stderr
stream before any tail is truncated, and the failure description became:

```
current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)
current_stage: unknown; exit: SIGABRT
current_stage: main window; exit: did not exit before the deadline
```

`current_stage` is the innermost stage started and not completed. A crash before
the first marker stays `unknown` — naming the last stage that passed would
invent a diagnosis. Marker lines are excluded from the reported output tail, so
progress cannot push a fault-handler traceback out of a bounded tail.

### 2.2 Host fingerprint

`tools/native_host_fingerprint.py` (new, 429 lines) writes one small JSON
document: OS, release, version, product build, architecture, CPU model and
vendor, logical and physical cores, and the build interpreter — labelled
`build_interpreter` so it is never confused with the frozen runtime's own
versions, which the self-check already reports.

Torch is probed **in a subprocess of its own** (`--with-torch`), because
importing Torch is one of the things that ends a packaging run. A crash or a
hang there costs the document a field, not the document.

A value the host will not give up carries the reason, never a default:

```json
"cpu": {
  "architecture": "arm64", "logical_cores": 6, "model": "Apple A18 Pro",
  "physical_cores": 6, "vendor": null,
  "unavailable": {"vendor": "/usr/sbin/sysctl exited with status 1: sysctl: unknown oid 'machdep.cpu.vendor'"}
}
```

No environment variables and no machine-wide process inventory are collected;
a test asserts both, and asserts the only two CIM classes named are
`Win32_OperatingSystem` and `Win32_Processor`.

Run on this host, `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` —
exactly the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the
real runners.

### 2.3 The `build.yml` failure graph

Every post-build step now has a stable id and states the product it actually
needs, using `${{ !cancelled() && steps.X.outcome == 'success' }}`:

| Step | Prerequisite |
| --- | --- |
| `resolve` (reconstruct on macOS) | `build` |
| `disk_image` (macOS only) | `build` — **not** `resolve` |
| `inventory` | `resolve` |
| `dictionary` | `build` |
| `worker_smoke` | `resolve` **and** `dictionary` |
| `ui_smoke` | `resolve` only — the window opens no provider |
| `packaged_tests` | `resolve` **and** `dictionary` |
| `archives` | `build` |
| `identity` | `archives` |
| Diagnostics upload | `!cancelled()` — always |
| Release-product upload | default `success()` |

macOS reconstruction, DMG inspection and inventory were one step and are now
three, so a bad DMG cannot suppress a valid ZIP's checks and vice versa. Two new
tool modes support that: `--reconstruct-only` and a standalone `--disk-image`.
A DMG that mounts onto something other than `Hanly.app` now **fails**; before,
`verify_disk_image` reported `ok: false` and nothing acted on it.

Both smokes write stdout and stderr to files and then echo them, rather than
piping through `tee`, so a harness that dies before printing its report still
leaves the reason somewhere the diagnostics upload can collect.

The new `hanly-diagnostics-<platform>` artifact carries `dist/reports/` plus
PyInstaller's `warn-*.txt` and `xref-*.html`, uploads on failure, and is
deliberately named so it cannot match `release.yml`'s `hanly-desktop-*` pattern.

### 2.4 How the conditions are checked

`tests/test_ci_workflows.py` gained a small evaluator for the expression subset
these workflows use, and replays the job:

- a failed `worker_smoke` still leaves `ui_smoke`, `disk_image`, `archives`,
  `identity` and the diagnostics upload, and does **not** publish;
- a failed `dictionary` skips `worker_smoke` and leaves `ui_smoke`;
- a failed `resolve` still leaves `disk_image` and `archives`;
- a failed `build` skips everything downstream and still uploads diagnostics;
- an all-green run publishes.

The evaluator raises on an expression it does not model, so a future condition
cannot be silently assumed true. **This is a model of Actions, not Actions** —
see the limitations.

---

## 3. HAN-43 — three suites, three machines

### 3.1 Selection

A new repository-root `conftest.py` adds `--suite portable|native|packaged|all`
and implements it with `pytest_ignore_collect`, so a suite is excluded **before
its modules are imported**. A marker cannot do this: deselection by marker
happens after the import, and the native modules import Qt, pywebview and the
OCR runtime at module scope.

`tests/native/conftest.py` and `tests/packaged/conftest.py` do the same for the
OS directories — a Windows-only module is never imported on macOS — and apply
the `native` / `packaged` markers from the directory a case lives in.

`python -m pytest` remains the documented full local gate.

### 3.2 Layout, and the routing decisions

```
tests/native/shared/     real Qt, real child processes, real windows
tests/native/macos/      Cocoa, LaunchServices, Darwin behaviour
tests/native/windows/    Windows adapters and the Windows rollback
tests/packaged/shared/   the frozen product
tests/hanly_fixtures/    shared deterministic helpers
```

`tests/native/linux/` is deliberately **absent**: no case is Linux-only, and an
empty suite is a gate that passes because it asked nothing. Linux-native
behaviour is exercised by the shared cases on the Linux job.

Two routing calls worth a reviewer's attention:

- **`tests/test_hotkeys_darwin.py` stayed portable.** It drives a `_FakeCarbon`
  double, never a real registration. The plan says a mocked Darwin API test can
  remain portable, and it does.
- **`tests/test_hover_exit_qt.py` and `tests/test_qt_hover_scheduler.py` moved.**
  Both build a real `QApplication` and run a real event loop. They were the
  reason `PyQt6` still appeared in a portable collection, which is the thing the
  portable matrix exists to avoid.

`tests/test_app_update_handoff.py` was split: the rendered-script decisions stay
portable, the executing cases moved to the native suites, and the shared
scaffolding (the C probe, `prepare_handoff`, `run_handoff`, `Handoff`, the
compiler discovery) moved to `tests/hanly_fixtures/update_handoff.py`, where the
Windows-only and macOS-only rollbacks can reuse it.

### 3.3 Two latent defects the move exposed

Neither was introduced by the restructuring; both were passing on collection
order and stopped when the order changed.

1. **`test_qt_webengine_is_prepared_before_qapplication_creation`** asserted
   `QApplication.instance() is None` — a process-global precondition satisfied by
   luck. The production guard refuses to prepare the backend once a
   `QApplication` exists, so the test could only ever pass first. It now runs in
   a child of its own, in `tests/native/shared/test_webengine_startup.py`.
2. **`pytest.importorskip("PyQt6.QtWebEngineWidgets")`** in three capability
   checks imported Qt WebEngine into the *parent* process, which then refuses to
   import once any `QApplication` exists. All of that work happens in
   subprocesses, so the checks now use `find_spec` and import nothing.

### 3.4 A skip that cannot be a pass

`tests/hanly_fixtures/capabilities.py` gained `unavailable(reason)`,
`require_modules(...)` and `require_display()`. On a developer machine they skip
with a precise reason. In the job whose whole purpose is that capability —
`HANLY_REQUIRE_NATIVE=1`, `HANLY_REQUIRE_PACKAGED=1` — every one of those reasons
becomes a **failure**. Two tests prove both directions.

The stale-bundle compatibility skip in the packaged gate went the same way.

### 3.5 CI ownership

`ci.yml` now has `quality` (the four-Python portable matrix, plus lint and
types, on a machine with none of the desktop runtime) and `native`
(windows / macos / linux, `fail-fast: false`, no `needs`), each installing the
runtime extra, fetching the EasyOCR weights, and building a small KRDICT so its
cases have something real to read.

`build.yml` gave up the portable suite, ruff and mypy — three more full runs of
what the matrix had already proved, on the slowest machines in the project — and
gained `--suite packaged` against the bundle it just froze.

**Two consequences a human has to decide on**, both recorded in the ledger and
the handoff and neither acted on:

- `windows tests (py3.10)` no longer exists. Anything pinning a required check
  to that name needs updating. `quality (py<version>)` was left unchanged on
  purpose, because required checks are pinned to it.
- Release eligibility now leans on CI for the tag rather than on the build job
  repeating the gates. `release.yml` still requires a successful build run, and
  no repository setting was touched.

### 3.6 Coverage accounting

Collected node IDs were compared before and after, normalised for the moved
paths:

- before: 1278 collected on this host
- after: 1283, then 1300 once the Super QA tests landed
- **every** previously collected case has an owner
- the only two no longer collected here are
  `test_an_empty_argument_list_still_aborts_chromium_on_windows` and
  `test_a_rejected_build_that_is_still_running_is_stopped_before_the_restore`,
  now routed to `tests/native/windows/`. They were previously collected on macOS
  and skipped; they are now not collected on macOS at all, which is the point of
  OS selection before import.

No portable suite was cloned per OS; no directory was created empty.

---

## 4. Super QA — the six findings

| ID | Outcome | Basis |
| --- | --- | --- |
| SUPERQA-001 | **Not reproduced** | Fresh frozen `--self-check ui`: `ok: true`, exit 0, 2.54 s. Source run passes too |
| SUPERQA-002 | **Fixed now** | `verify_primary_screen` between Qt init and pywebview window creation |
| SUPERQA-003 | **Not reproduced** | The whole popup suite passes on this visible Cocoa session |
| SUPERQA-004 | **Not reproduced**, and hardened | `/bin/ps` is permitted here; the inventory now refuses to answer an empty list |
| SUPERQA-005 | **Confirmed, then fixed** | The bundle on this machine really did report `0.1.3` against a `0.5.0` tree |
| SUPERQA-006 | **Measured** | No regression; the residual cost and a revisit trigger are recorded |

### 4.1 The environment difference, stated plainly

`superqa.md` itself flagged its four UI/process findings as environment-sensitive
and asked for a normal visible macOS retest. This session **is** that retest: a
visible window server, a permitted `/bin/ps`, a built KRDICT database and the
EasyOCR weights all present. Under those conditions the frozen UI self-check,
the Cocoa popup panel, the Control Center lifecycle, the real lookup child and
the Darwin update handoff all pass. Three findings were therefore closed as
*not reproduced* rather than fixed — no speculative native change was made for
any of them.

### 4.2 SUPERQA-005 — reproduced here, and now enforced

The `dist/macos/Hanly.app` on this machine reported:

```
python 3.10.20   hanly 0.1.3   hanly-app 0.1.3
```

against a `0.5.0` checkout. `--expect-version` makes the bundle answer for
itself from the metadata its own interpreter collected:

```
$ python tools/smoke_packaged_runtime.py dist/macos/Hanly.app --expect-version 0.5.0 ...
Hanly smoke: the frozen bundle reports hanly '0.1.3', expected '0.5.0'
Hanly smoke: the frozen bundle reports hanly-app '0.1.3', expected '0.5.0'
exit 1
```

A report that names **no** version fails too — a missing identity leaves a
release in the same position a wrong one does. The option is refused alongside
`--inventory-only` and `--reconstruct-only`, neither of which starts the
executable. `dist/reports/hanly-artifact-*.json` now records the build commit
and the source version beside the archive hashes, because a hash says two
downloads are the same file, not which source made it.

### 4.3 SUPERQA-002 — the guard, and what it cannot do

`verify_primary_screen` runs after `ensure_qt_application` and before pywebview
creates its window, raising the existing `ControlCenterUnavailable`. pywebview
reads the primary screen's geometry there without checking that there is one,
which is how a screenless session used to fail from inside that library.

It **cannot** prevent an abort inside `QApplication` itself, because it runs
after construction. That case is covered only by HAN-44's stage markers, and
both the docstring and `packaging/README.md` say so rather than claiming
graceful recovery. No GUI backend was swapped and no Qt or pywebview version was
pinned or downgraded: visible-screen evidence establishes no incompatibility.

### 4.4 SUPERQA-004 — an empty list is not a retired child

`tests/hanly_fixtures/process_probe.py` now raises
`ProcessInspectionUnavailable` for a missing probe tool, a permission denial, a
timeout, or a non-zero exit. Both consumers report that as
`inspection_unavailable` and the tests turn it into `unavailable(...)` — a skip
locally, a failure in the required native job. Previously a refused `ps` and a
genuinely empty child list were indistinguishable, and they mean opposite
things.

The production updater's process logic was **not** changed. The Darwin handoff
was retested for real instead, with compiled probe builds and working
LaunchServices, and passes — including the macOS rollback that finds the
candidate by a path full of regular-expression metacharacters.

### 4.5 A fresh artifact, built the way a release is

Built from this branch with a disposable **Python 3.10.20** environment
installed under `packaging/release-constraints.txt` — the interpreter
`build.yml` uses, not the 3.13 `.venv`.

| Check | Result |
| --- | --- |
| Reconstruct the published ZIP | ok |
| Inspect the DMG | `ok: true`, contains `Hanly.app` |
| Inventory | ok, nothing missing |
| Frozen worker with `--expect-version 0.5.0` | passed; both packages `0.5.0` |
| Frozen `--self-check ui` | passed in 2.54 s; 4 controls, bridge answered |
| `pytest --suite packaged` with `HANLY_REQUIRE_PACKAGED=1` | 3 passed |

The frozen worker's own markers confirm the HAN-44 work end to end in a real
bundle: all seven stages started and completed, `current_stage: None`.

### 4.6 SUPERQA-006 — measured, no regression

| Metric | Now | `superqa.md` (stale `0.1.3` artifact) |
| --- | ---: | ---: |
| Frozen worker self-check, wall clock (warm) | 7.74 s | 9.32 s |
| Lookup worker construction (cold / warm) | 7,863 / **4,277** ms | 5,555 ms |
| OCR (cold / warm) | 3,047 / **1,800** ms | 1,907 ms |
| Morphology (cold / warm) | 1,881 / **1,300** ms | 1,154 ms |
| Dictionary | **3–4** ms | 136 ms |
| Frozen UI self-check | **2.54 s** | aborted |
| Source warm lookup, 192x48, 40 samples | **p50 29.8 / p95 30.7 ms** | not measured |
| RSS with providers resident, 20 s idle | **834.9 MiB, flat** | not measurable |
| `Hanly.app` tree | 1,342,418,115 B (4,906 files) | ~1.3 G |
| macOS ZIP / DMG | 560,323,613 / 637,255,977 B | 534 M / 608 M |

Largest families: Torch 484.7 MB, Qt/PyQt6/QtWebEngine 387.4 MB, Kiwi 124.0 MB,
OpenCV 123.6 MB, EasyOCR weights 99.2 MB.

Real process lifecycle, from the actual spawned child: one lookup child while
ready, none after `retire()`, none after `close()`, a new generation after
waking a retired engine, and none of `easyocr` / `torch` / `kiwipiepy` imported
in the shell.

**Nothing was changed for performance.** Worker construction still dominates the
first lookup after a retirement — about 4.3 s — which is the price the approved
policy already charges (`LookupPreload.WHEN_CAPTURE_STARTS` loads at Start;
`manual_lookup.IDLE_TIMEOUT_SECONDS` retires an idle manual session after 60 s),
while the warm path is 30 ms. Revisit trigger: a reported user-visible delay on
the first lookup after an idle retirement, or a change to the `LookupPreload`
default.

### 4.7 One defect found while measuring

`benchmarks/dev/probes.py`'s RSS fallback multiplied `ru_maxrss` by 1024 on
every platform. `getrusage` reports it in KiB on Linux and in **bytes** on the
BSDs, macOS included, so the first idle sample read 39 MiB of resident memory as
39 GiB — a plausible-looking number in a CSV nobody reads twice. Fixed narrowly,
with a focused test. It is developer instrumentation; nothing in `packages/`
uses it.

---

## 5. Gates

| Gate | Result |
| --- | --- |
| `python -m pytest` | **1300 passed, 1 skipped** (an opt-in real-EasyOCR KRDICT case) |
| `python -m ruff check packages packaging tests tools benchmarks` | clean |
| `python -m mypy packages packaging tests tools benchmarks` | clean, 216 files |
| `python -m pytest --suite native` | **37 passed, 0 skipped** |
| `python -m pytest --suite packaged` (`HANLY_REQUIRE_PACKAGED=1`) | **3 passed** |
| `python -m pytest --suite portable` | collects 1257+ cases and imports no Qt, Torch, pywebview, pynput or mss |

---

## 6. What a reviewer should not take on trust

1. **No CI run exists.** The failure graph and the three native jobs are proved
   by a local replay of the step conditions. Nothing was pushed; no Actions run
   confirms them. This is recorded as pending CI confirmation rather than
   manufactured by pushing.
2. **Windows and Linux native evidence is absent.** `tests/native/windows/` was
   never collected here, and the Linux job's xvfb display is unexercised.
3. **Required-check names changed.** See §3.5 — a human decision, untouched.
4. **Three findings were closed as not reproduced**, on a machine that had the
   capabilities the original sandbox lacked. That is evidence about this host,
   not proof the defects can never occur; the HAN-44 diagnostics exist precisely
   for the day they do.
5. **The screen guard runs after `QApplication` construction** and cannot catch
   an abort inside it.
6. **No human desktop pass.** Capture start/stop, ROI and target selection,
   hotkey lookup, popup retention and dismissal against a real application, a
   resource update through the Control Center, quit, and relaunch on a
   disposable profile were not performed — they need a person at the keyboard.
7. **The 60 s idle retirement was not timed live.** Process-level retirement is
   proved by the real child; the timeout itself is covered by unit tests with an
   injected scheduler.
8. **Linear was not reachable** (the MCP server is unauthenticated). No issue
   state was changed and no comment was posted; HAN-43 and HAN-44 still need to
   be moved to `In Review` by hand.

### Suggested review targets

- `read_progress` and `_describe_exit` — nested stages, and a run that emits one
  marker and then nothing.
- The `build.yml` conditions, read as GitHub would read them rather than as the
  local evaluator does.
- Whether the suite exclusion really precedes every import on Windows too.
- The two added stages (`worker close`, `window host`) against any consumer that
  reads the stage list positionally.
- `verify_primary_screen`'s placement — whether anything else reaches Qt
  geometry first, and whether the shell's own paths want the same check.
- `tests/hanly_fixtures/update_handoff.py`: scaffolding lifted out of a test
  module, and whether the portable half still covers what it used to.

---

## 7. Acceptance criteria, read from the issues

### 7.1 HAN-44 — all four required updates met

| Required update | Evidence |
| --- | --- |
| **1.** Independent post-build smokes continue after one fails | Per-step `!cancelled() && steps.X.outcome == 'success'`. The issue's example is replayed exactly: a failed worker smoke still leaves the Control Center smoke, the inventory, the archive checks and the identity record, and the job still ends red. No blanket `continue-on-error` — a test asserts there is none anywhere in the job |
| **2.** Diagnostics retained on a failed job | `hanly-diagnostics-<platform>` uploads on `!cancelled()`, carrying every item the issue lists: the worker smoke report, the window smoke report, artifact identity and product reports, PyInstaller `warn-*`/`xref-*`, and the host fingerprint — plus both smokes' captured stdout and stderr. Release artifacts stay success-only, which the issue permits |
| **3.** Compact cross-platform host fingerprint | `tools/native_host_fingerprint.py`, written for all three platforms and persisted into the diagnostics artifact. Windows reads `Win32_Processor` and `Win32_OperatingSystem`; macOS reads `sw_vers` and `machdep.cpu.brand_string`; Linux reads `/proc/cpuinfo` and `/etc/os-release`. No environment dump — a test asserts it |
| **4.** `stage_started` persisted before native work | A flushed marker precedes every stage. The failure line is the issue's desired shape, `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)`. No retries, no crash recovery, completed-stage timings unchanged on success |

**Two gaps found on re-reading, both closed in `1f8354a`:**

- The issue lists **"frozen/not-frozen context where relevant"** among the common
  fields. The fingerprint had none. It now reports `build_interpreter.frozen`,
  which is always `false` in a packaging job — stated rather than left to be
  assumed, with the frozen half of the comparison coming from the self-check's
  own report.
- The issue lists Windows **"processor architecture"**. The CIM query already
  selected `OSArchitecture` and then threw it away. It is now recorded as
  `os.architecture`, distinct from `cpu.architecture` (`platform.machine()`),
  because OS bitness and processor architecture are different questions.

Every constraint holds: no Torch dispatch change, no pin or downgrade, no
weakened native coverage, no retries, no blanket `continue-on-error`, workflow
stays red on a required failure.

### 7.2 HAN-43 — every stated goal met, with one scope note

| Goal | Status |
| --- | --- |
| Shared portable/unit/contract tests stay common | Yes |
| Platform-native tests under OS-specific suites | Yes — `tests/native/{shared,macos,windows}` |
| Packaging smoke split by platform where behaviour differs | Yes — it does not differ, so `tests/packaged/shared/` only |
| Shared contracts once, native adapters per platform | Yes |
| Avoid generic tests full of `if sys.platform == ...` | Yes — extracted into OS files; the one remaining adapter is `HANDOFF_VARIANTS`, which the plan explicitly allowed |
| Avoid duplicating the entire suite per OS | Yes — no file exists twice |
| Keep build/frozen workflows separate from fast portable CI | Yes — `build.yml` gave up the portable suite, lint and types |
| Native/build jobs independent and parallel | Yes — `fail-fast: false`, no `needs`, one job per platform |

**Of the six named pain areas, five are routed**: frozen packaging smoke,
Control Center lifecycle, subprocess/process probes, Qt/native dependencies,
updater handoff.

**Hotkeys are the exception, and not because they were skipped.**
`test_hotkeys.py` and `test_hotkeys_darwin.py` drive doubles throughout — a
`_Listener` stand-in, a `_FakeCarbon` recording double, and a patched
`sys.platform` — and never reach a real registration or an Accessibility grant.
They are correctly portable and there was nothing to move. The real finding is
that **no native hotkey coverage exists at all**: nothing registers a real
Carbon hotkey on macOS or a real pynput one on Windows or Linux. Writing that is
new coverage rather than restructuring, so it was reported instead of done.

**`tests/native/linux/` is absent.** No case is Linux-only today, and an empty
suite is a gate that passes because it asked nothing. The issue does name
Linux-specific suites, so this is a reading — "avoid duplicating the entire test
suite per OS" plus "do not create empty suites" — and it is worth your second
opinion. Linux-native behaviour (the xcb plugin, the display) is exercised by
the shared cases on the Linux job.

---

## 8. The diff

`git diff 5f7eb2a..HEAD` — 59 files, +4545 / −1027. Per commit:

| Commit | Files | Lines |
| --- | ---: | --- |
| `3e05574` | 11 | 2097 insertions(+), 57 deletions(-) |
| `17c841a` | 42 | 1728 insertions(+), 957 deletions(-) |
| `ce94fe4` | 6 | 184 insertions(+), 5 deletions(-) |
| `af44fd7` | 11 | 257 insertions(+), 12 deletions(-) |
| `13de683` | 5 | 52 insertions(+), 9 deletions(-) |
| `c6ef4bc` | 2 | 205 insertions(+), 25 deletions(-) |
| `1f8354a` | 2 | 14 insertions(+) |
| `ba87cce` | 2 | 51 insertions(+), 5 deletions(-) |

The complete diff follows, fenced with five backticks: it carries Markdown
files whose own three-backtick fences would otherwise end the block early.

### 8.1 `3e05574` — fix: preserve packaging smoke diagnostics on failure

`````diff
diff --git a/.github/workflows/build.yml b/.github/workflows/build.yml
index 9a15ec1..0751dcd 100644
--- a/.github/workflows/build.yml
+++ b/.github/workflows/build.yml
@@ -47,6 +47,17 @@ jobs:
         with:
           node-version: "22"
 
+      # Written before the first install, so a run that dies later still says
+      # which machine it died on. The crash this exists for is a native library
+      # meeting a CPU that does not implement what it was compiled to use.
+      - name: Record the host fingerprint
+        id: fingerprint
+        shell: bash
+        run: >
+          python tools/native_host_fingerprint.py
+          --context "before install"
+          --output "dist/reports/hanly-host-${{ matrix.platform }}.json"
+
       - name: Install Linux packaging dependencies
         if: matrix.platform == 'linux'
         run: |
@@ -74,6 +85,17 @@ jobs:
           python -m pip install --editable packages/hanly
           python -m pip install --editable "packages/hanly-app[runtime]" -c packaging/release-constraints.txt
 
+      # Torch is probed only once it exists, and in a child of its own: the
+      # import is one of the things that ends a packaging run outright.
+      - name: Record what the installed runtime reports
+        id: runtime_fingerprint
+        shell: bash
+        run: >
+          python tools/native_host_fingerprint.py
+          --context "installed runtime"
+          --with-torch
+          --output "dist/reports/hanly-host-runtime-${{ matrix.platform }}.json"
+
       # A tag push is the release identity, so the tag and the product
       # version must agree before any artifact is produced under that name.
       - name: Verify the tag matches the product version
@@ -101,11 +123,17 @@ jobs:
         run: python tools/prepare_easyocr_models.py
 
       - name: Build application package
+        id: build
         env:
           PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR: "1"
         run: python tools/build_package.py --platform ${{ matrix.platform }}
 
+      # Every check below states the product it actually needs. A failed worker
+      # smoke used to skip the window smoke, the archive checks, and the whole
+      # diagnostic upload, so one failure produced one line of evidence.
       - name: Resolve the frozen application to smoke
+        id: resolve
+        if: ${{ !cancelled() && steps.build.outcome == 'success' }}
         shell: bash
         env:
           RUNNER_PLATFORM: ${{ matrix.platform }}
@@ -116,46 +144,91 @@ jobs:
             python tools/smoke_packaged_runtime.py \
               --from-archive dist/hanly-desktop-macos.zip \
               --reconstruct-into dist/reconstructed \
-              --disk-image dist/hanly-desktop-macos.dmg \
-              --inventory-only \
+              --reconstruct-only \
               | tee "dist/reports/hanly-products-macos.json"
             echo "SMOKE_APP=dist/reconstructed/Hanly.app" >> "$GITHUB_ENV"
           else
             echo "SMOKE_APP=dist/$RUNNER_PLATFORM/hanly-desktop" >> "$GITHUB_ENV"
           fi
 
+      # The disk image is its own published product, made from the same build
+      # as the ZIP. A ZIP that will not reconstruct says nothing about it.
+      - name: Inspect the published disk image
+        id: disk_image
+        if: ${{ !cancelled() && steps.build.outcome == 'success' && matrix.platform == 'macos' }}
+        shell: bash
+        run: |
+          set -euo pipefail
+          mkdir -p dist/reports
+          python tools/smoke_packaged_runtime.py \
+            --disk-image dist/hanly-desktop-macos.dmg \
+            | tee "dist/reports/hanly-diskimage-macos.json"
+
       - name: Check the frozen bundle inventory
+        id: inventory
+        if: ${{ !cancelled() && steps.resolve.outcome == 'success' }}
         shell: bash
-        run: python tools/smoke_packaged_runtime.py "$SMOKE_APP" --inventory-only
+        run: |
+          set -euo pipefail
+          mkdir -p dist/reports
+          python tools/smoke_packaged_runtime.py "$SMOKE_APP" --inventory-only \
+            | tee "dist/reports/hanly-inventory-${{ matrix.platform }}.json"
 
       - name: Build the dictionary the frozen smoke installs
+        id: dictionary
+        if: ${{ !cancelled() && steps.build.outcome == 'success' }}
         shell: bash
         run: python tools/build_smoke_krdict.py "$RUNNER_TEMP/hanly-smoke-krdict/krdict.sqlite3"
 
+      # Both streams are captured to files rather than piped: a harness that
+      # dies before printing its report leaves the reason on stderr, and a
+      # failed step whose evidence lives only in the log cannot be uploaded.
       - name: Smoke the frozen lookup runtime
+        id: worker_smoke
+        if: >-
+          ${{ !cancelled() && steps.resolve.outcome == 'success'
+          && steps.dictionary.outcome == 'success' }}
         shell: bash
+        env:
+          RUNNER_PLATFORM: ${{ matrix.platform }}
         run: |
-          set -euo pipefail
+          set -uo pipefail
           mkdir -p dist/reports
+          report="dist/reports/hanly-smoke-$RUNNER_PLATFORM"
+          status=0
           python tools/smoke_packaged_runtime.py \
             "$SMOKE_APP" \
             --image tests/hanly_fixtures/assets/korean_reading_roi.png \
             --krdict "$RUNNER_TEMP/hanly-smoke-krdict/krdict.sqlite3" \
-            | tee "dist/reports/hanly-smoke-${{ matrix.platform }}.json"
+            > "$report.json" 2> "$report.err" || status=$?
+          cat "$report.json"
+          tail -c 200000 "$report.err" >&2
+          exit "$status"
 
       - name: Smoke the frozen Control Center
+        id: ui_smoke
+        if: ${{ !cancelled() && steps.resolve.outcome == 'success' }}
         shell: bash
+        env:
+          RUNNER_PLATFORM: ${{ matrix.platform }}
         run: |
-          set -euo pipefail
+          set -uo pipefail
           mkdir -p dist/reports
           display=""
-          if [ "${{ matrix.platform }}" = "linux" ]; then display="xvfb-run -a"; fi
+          if [ "$RUNNER_PLATFORM" = "linux" ]; then display="xvfb-run -a"; fi
+          report="dist/reports/hanly-window-$RUNNER_PLATFORM"
+          status=0
           $display python tools/smoke_packaged_runtime.py \
             "$SMOKE_APP" \
             --window-only \
-            | tee "dist/reports/hanly-window-${{ matrix.platform }}.json"
+            > "$report.json" 2> "$report.err" || status=$?
+          cat "$report.json"
+          tail -c 200000 "$report.err" >&2
+          exit "$status"
 
       - name: Verify the release archive exists
+        id: archives
+        if: ${{ !cancelled() && steps.build.outcome == 'success' }}
         shell: bash
         env:
           RUNNER_PLATFORM: ${{ matrix.platform }}
@@ -179,6 +252,8 @@ jobs:
           done
 
       - name: Record the artifact identity
+        id: identity
+        if: ${{ !cancelled() && steps.archives.outcome == 'success' }}
         shell: bash
         env:
           RUNNER_PLATFORM: ${{ matrix.platform }}
@@ -222,6 +297,20 @@ jobs:
           )
           PY
 
+      # Never a release product: this is what a failed run leaves behind, and
+      # it has to survive the failure that produced it.
+      - name: Retain build diagnostics
+        if: ${{ !cancelled() }}
+        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
+        with:
+          name: hanly-diagnostics-${{ matrix.platform }}
+          path: |
+            dist/reports/
+            dist/.pyinstaller/${{ matrix.platform }}/**/warn-*.txt
+            dist/.pyinstaller/${{ matrix.platform }}/**/xref-*.html
+          if-no-files-found: ignore
+          retention-days: 14
+
       # Only the archive is retained. The uncompressed onedir tree beside it is
       # the same payload again, and PyInstaller's work cache is not releasable.
       - name: Retain platform artifact
diff --git a/docs/execution/checkpoints/han-43-44-superqa.md b/docs/execution/checkpoints/han-43-44-superqa.md
new file mode 100644
index 0000000..6af4f0a
--- /dev/null
+++ b/docs/execution/checkpoints/han-43-44-superqa.md
@@ -0,0 +1,30 @@
+# HAN-43 / HAN-44 / Super QA session updates
+
+## Session
+- Branch / base SHA: `codex/han-43-44-superqa` from `main` at `5f7eb2af68ab7883ec5f43525e00fd325867fd49`
+- Interpreter / OS / display and process-inspection availability: `.venv` Python 3.13.11,
+  macOS arm64 (Darwin 25.6.0). `/bin/ps` is permitted in this session, unlike the
+  sandbox that produced `superqa.md`. Visible-desktop availability is checked per native
+  run and recorded with the result.
+- Scope: HAN-44, HAN-43, SUPERQA-001–006
+- Linear: not reachable from this session (the MCP Linear server is unauthenticated).
+  No issue state was changed and no comment was posted. Status progression for HAN-43
+  and HAN-44 is pending human action.
+
+## Checkpoints
+| Patch | State | Main changes | Check and result | Commit |
+| --- | --- | --- | --- | --- |
+| HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and standalone `--disk-image` in the smoke harness. | `pytest tests/test_packaging.py tests/test_ci_workflows.py tests/test_host_fingerprint.py` 153 passed; full `pytest` 1275 passed / 3 skipped; ruff + mypy clean. | |
+| HAN-43 | Pending | | | |
+| Super QA | Pending | | | |
+
+## Observations for future review
+| Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
+| --- | --- | --- | --- |
+| Per-OS runner behaviour of the new `build.yml` failure graph is unproven | The conditions are checked by a local scenario replay in `tests/test_ci_workflows.py`, not by Actions | Implemented; pending CI confirmation. No push authorization in this run | The next `workflow_dispatch` or tag build |
+| `worker close` became a reported stage | A crash while releasing native handles used to be attributed to the last provider stage | Implemented. The worker report now carries one extra stage | If a consumer parses the stage list positionally |
+| `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |
+
+## Next action / blockers
+- HAN-43: route native cases into `tests/native/**` and `tests/packaged/**`, add suite
+  selection, and rebuild the CI job layout.
diff --git a/docs/execution/han-43-44-superqa-patch-plan.md b/docs/execution/han-43-44-superqa-patch-plan.md
new file mode 100644
index 0000000..e57e2ef
--- /dev/null
+++ b/docs/execution/han-43-44-superqa-patch-plan.md
@@ -0,0 +1,191 @@
+# HAN-43, HAN-44, and Super QA — Claude execution plan
+
+Prepared 2026-09-13. **Planning only; implementation and testing belong to Claude.**
+
+Execute the three parts below in one Claude session and one branch, in the listed order: **HAN-44 → HAN-43 → Super QA**. Diagnostics come first so the restructuring and native follow-ups produce useful failure evidence. These are three separately checked patch areas within one bundle, not three independent execution runs.
+
+## Scope and evidence
+
+- [HAN-44 — Improve packaging smoke diagnostics and failure visibility](https://linear.app/hmx-gen-projects/issue/HAN-44/improve-packaging-smoke-diagnostics-and-failure-visibility): four required diagnostic improvements; High priority.
+- [HAN-43 — Restructure platform-specific smoke/build tests](https://linear.app/hmx-gen-projects/issue/HAN-43/restructure-platform-specific-smokebuild-tests): portable/native/build separation; Medium priority.
+- [superqa.md](../../superqa.md): existing investigation and six findings. Follow its evidence and bounded follow-up order; do not repeat the broad QA audit.
+
+Both Linear issues were Backlog, related to each other, with no blocking relationships or comments when read. The human explicitly selected both for this bundle, superseding their earlier separate scheduling. Recheck for newly introduced real blockers before implementation.
+
+Planning checkout: local `main`, HEAD and locally recorded `origin/main` both `5f7eb2af68ab7883ec5f43525e00fd325867fd49`. This was a local comparison, not a fresh remote fetch. `superqa.md` was the only untracked file before this plan was added. Its evidence is older: source `900dba1` / v0.5.0, but the tested bundle reported v0.1.3. Do not reset to that historical commit or treat that bundle as current release evidence.
+
+Read `CLAUDE.md`, `docs/CODE-MAP.md`, architecture `01`–`04`, and `docs/execution/05-execution-plan.md` before executing. This is the bundle plan required by `05`; do not add another plan, mandatory reviewer chain, or repeated QA cycle. Proposed tiers: HAN-44 Standard, HAN-43 Gate (CI coverage convergence), Super QA Gate (native UI and artifact validation). Claude is the direct executor by default.
+
+### Start: local branch and session record
+
+1. Inspect `git status --short --branch`, `git branch --show-current`, and `git rev-parse HEAD main`. Preserve all existing user work. If another branch is active, inspect before switching; never discard changes to satisfy this plan.
+2. From the actual local `main`, create **`codex/han-43-44-superqa`** with `git switch -c codex/han-43-44-superqa main`. Use the current checkout, not a fresh clone, remote checkout, or clean worktree: the uncommitted QA report and this plan must carry over. Do not pull, reset, clean, or stash them away. If the branch already exists, inspect whether this is a resume; never overwrite it.
+3. Create **`docs/execution/checkpoints/han-43-44-superqa.md`** before code changes. Use the short template below. Update it after each meaningful patch/checkpoint, not after every command. Include this plan, the unchanged QA report, and the ledger in the first patch commit so the context is durable.
+4. Recheck Linear readiness; use the normal `Todo` / `In Progress` progression for each issue when actionable and active, then `In Review` only at the completed handoff. Do not mark `Done`, invent blockers, or create a Super QA parent issue. Keep Super QA findings granular in the ledger. Do not send unsolicited Linear comments or other messages; draft any proposed status summary in the ledger unless the human authorizes posting it.
+5. Confirm `.venv` is the intended local interpreter and the available native display/process capabilities. Use Python 3.10-compatible code. No baseline full-suite rerun is necessary: use the existing logs and run focused checks for changed behavior.
+
+```markdown
+# HAN-43 / HAN-44 / Super QA session updates
+
+## Session
+- Branch / base SHA:
+- Interpreter / OS / display and process-inspection availability:
+- Scope: HAN-44, HAN-43, SUPERQA-001–006
+
+## Checkpoints
+| Patch | State | Main changes | Check and result | Commit |
+| --- | --- | --- | --- | --- |
+| HAN-44 | Pending | | | |
+| HAN-43 | Pending | | | |
+| Super QA | Pending | | | |
+
+## Observations for future review
+| Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
+| --- | --- | --- | --- |
+
+## Next action / blockers
+- Exact next step; omit when complete.
+```
+
+Use `Implemented`, `Validated`, `Environment-blocked`, `Not reproduced`, or `Deferred` precisely. Do not imply a deep review has occurred. Record each commit SHA in the next ledger update; no amend loop just to put a commit's own hash inside itself.
+
+### Commit policy — explicitly authorized by the human
+
+Commit **after every coherent patch**, following its focused checks. Normally one commit for HAN-44, one for HAN-43, and one or more for the bounded Super QA fixes. Do not combine everything into one final commit or create empty commits for unconfirmed defects.
+
+Titles must start with `fix:`, `feat:`, or `chore:` and briefly name the update. Bodies contain only brief main-topic bullets, for example:
+
+```text
+fix: preserve packaging smoke diagnostics on failure
+
+- Updates host fingerprints and self-check stage reporting.
+- Fixes skipped independent smokes and missing failure artifacts.
+```
+
+Use only applicable `- Updates ...` / `- Fixes ...` bullets; do not invent a fix to fill a template. **No `Co-authored-by:`, `Co-authorized by Claude`, Claude attribution, generated-by footer, or other agent credit anywhere in any commit message.** Disable automatic attribution for these commits without changing the user's global Git configuration. Inspect the exact message before committing and the resulting message afterward. Stage explicit paths, inspect the staged diff, and exclude generated bundles, logs, caches, and unrelated work. A final documentation-only commit may record the handoff. No push, tag, release, or merge is authorized here.
+
+## Part 1 — HAN-44: make one failed packaging run informative
+
+### Incident and current implementation
+
+A Windows smoke died with `STATUS_ILLEGAL_INSTRUCTION (0xC000001D)`; a rerun passed. CPU/ISA differences remain a hypothesis, not a diagnosis. Recent code already names Windows fatal statuses and enables `faulthandler`; retain that work.
+
+`.github/workflows/build.yml` already has three OS matrix entries with `fail-fast: false`. The missing independence is inside each job: default success conditions skip later smokes and the sole artifact upload after a failure. macOS archive reconstruction, DMG verification, and inventory currently share one step. `self_check._stage` records outcomes only after actions return, and `tools/smoke_packaged_runtime.py` receives no started-stage evidence after a native abort.
+
+### Execute
+
+1. Give prerequisite steps stable IDs and apply explicit post-build conditions. Use `always()` with successful prerequisite outcomes and a cancellation guard; do not use blanket `continue-on-error`. Keep required failed steps red. Split the coupled macOS reconstruction/DMG/inventory work enough that a bad DMG does not suppress a valid ZIP's worker/UI checks.
+
+   | Check | Actual prerequisite |
+   | --- | --- |
+   | Resolve/reconstruct application | Successful application/product build; ZIP available on macOS |
+   | Inventory | Resolved application |
+   | Worker smoke | Resolved application and generated smoke dictionary |
+   | UI smoke | Resolved application and usable display; no worker dependency |
+   | DMG inspection / archive existence and size / artifact identity | Their own produced files; no smoke dependency |
+   | Diagnostic upload | Always when evidence exists, including failed builds |
+   | Release-product upload | All required checks successful |
+
+   Keep artifact existence guards honest: absent required products must still be reported as failures. `run_build` currently includes archive creation; do not treat a failed freeze as a usable application. Avoid a general workflow orchestration framework.
+
+2. Add a separate, failure-safe diagnostics upload per platform, retaining worker/window reports, inventory/product/identity reports, the host fingerprint, and available PyInstaller warning/build output from `dist/.pyinstaller/<platform>/`. Retain bounded stdout/stderr evidence when JSON is absent. Keep current release artifact names and their consumer contract intact; inspect `.github/workflows/release.yml`, `tools/release_build.py`, and `tests/test_release_build.py` before changing artifact contents. Diagnostic artifacts must not become release products.
+
+3. Add a small tooling-owned host-fingerprint collector, preferably `tools/native_host_fingerprint.py`. Write base OS/version/build, architecture, CPU model/vendor, logical cores, optional physical cores, Python, and collection context early. Supplement with Torch version and available CPU/backend capability information after dependencies install. Use bounded OS probes: Windows CIM, macOS `sysctl`/`sw_vers`, Linux `/proc/cpuinfo` and OS metadata. Missing optional fields carry an unavailable reason, not fabricated defaults. Do not dump environment variables or machine-wide process inventories.
+
+   Keep Torch probing in a bounded subprocess so an import crash cannot erase the base fingerprint or prevent independent smokes. Label build-interpreter information separately from frozen-runtime information; reuse self-check version data for the latter. Do not import Torch into the persistent desktop shell for diagnostics.
+
+4. Before every `_stage` action, emit a structured `stage_started` marker and flush it. A prefixed JSON line on **stderr** is sufficient and leaves the existing final stdout JSON parser intact. Emit matching completion events so the harness can distinguish completed work from the active stage, including nested UI probes. Parse markers from the full captured stream before truncating diagnostic tails. Preserve completed-stage timing/details and the final JSON shape; add `current_stage`/progress evidence without replacing existing results.
+
+   Cover provider construction, OCR, morphology, dictionary, and Qt window startup. If native cleanup or version probing can run outside those stages, give it an explicit marker too; never blame the last successful OCR stage for a later cleanup crash. Preserve exit status, timeout, stderr, and `faulthandler` output. A crash before any marker remains explicitly unknown. No crash recovery or retries.
+
+5. Update the harness's failure description to combine the active stage with the existing exit decoder, e.g. `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)`. Keep progress collection inside self-check/tooling paths, with no alternate desktop entry point and no engine changes.
+
+### Focused acceptance and checkpoint
+
+- Extend the existing packaging/self-check tests around `tests/test_packaging.py`: marker survives a deliberately terminated child, successful JSON still parses, completed timings remain, and stage plus fatal status/timeout are shown correctly. Use a tiny helper subprocess for the crash case, not a real crashing OCR workload.
+- Check workflow prerequisite cases: worker failure still permits UI/archive/identity; dictionary failure skips worker but permits UI; reconstruction failure does not suppress independent DMG evidence; build failure suppresses dependent smokes; diagnostic upload remains reachable and required failure remains red. Validate conditions with focused workflow tests or a small scenario check; do not call YAML parsing alone proof of Actions behavior.
+- Run the fingerprint on the available host and exercise other platform parsers with fixtures. Actual per-OS runner evidence remains a native validation item.
+- Update `packaging/README.md` for diagnostic outputs. Record checkpoint and commit, suggested title: **`fix: preserve packaging smoke diagnostics on failure`**.
+
+## Part 2 — HAN-43: separate portable contracts from native execution
+
+### Problem and chosen structure
+
+Today `ci.yml` runs the entire suite on Linux across Python 3.10–3.13 and again on Windows 3.10. `build.yml` repeats the full suite/lint/types with the runtime extra installed before freezing. Optional imports and host capabilities therefore change which native tests run inside otherwise shared jobs. No separate macOS source-native CI job exists.
+
+Keep portable tests shared. Separate only tests that genuinely execute OS/native behavior; a mocked Darwin API test can remain portable. Do not copy the whole suite into three directories.
+
+### Execute
+
+1. Make a short routing inventory in the existing ledger for the affected files: `tests/integration/test_{packaged_desktop,control_center_layout,control_center_lifecycle,webengine_startup,desktop_startup,lookup_process_spawn}.py`, `tests/test_qt_popup_window.py`, `tests/test_hotkeys*.py`, `tests/test_app_update_handoff.py`, and `tests/hanly_fixtures/process_probe.py`. Identify pure versus real-native cases before moving anything.
+2. Keep ordinary engine/unit/contract/tooling tests in their current locations and `benchmarks/dev/tests` in its existing location. Use this bounded layout for the native cases:
+
+   ```text
+   tests/native/shared/          # real Qt/child-process behavior shared across OSes
+   tests/native/windows/         # actual Windows adapters and handoff behavior
+   tests/native/macos/           # Cocoa, LaunchServices, Darwin-specific behavior
+   tests/native/linux/           # X11/platform-plugin and Linux-native behavior
+   tests/packaged/shared/        # frozen worker/UI contracts, one implementation
+   tests/packaged/<os>/          # only genuinely distinct product/native checks
+   tests/hanly_fixtures/         # shared deterministic helpers
+   ```
+
+   Do not create empty suites or gratuitously move portable files. Extract native cases from mixed files, preserving pure parametrized tests of platform decisions. Avoid new generic test bodies full of `sys.platform` branches; small platform fixtures/adapters are appropriate.
+3. Provide explicit portable/native/packaged suite selection, registered pytest markers where useful, and OS selection **before incompatible native modules import**. A marker deselected after module import is insufficient. Keep `python -m pytest` as the documented full local gate; add explicit selection for fast CI. Adapt fixture scope, asset paths, imports, and moved node references without weakening assertions. Offscreen Qt tests may exercise widget contracts but cannot satisfy a visible native-window gate.
+4. In `ci.yml`, keep the fast shared Python-version matrix for portable coverage/lint/types. Replace the duplicate full Windows suite with independent Windows/macOS/Linux source-native jobs using the actual runtime dependencies and required OS libraries/display setup. Run shared native contracts plus the host's native cases in each applicable job. Use `fail-fast: false`; do not make native jobs wait for other OS jobs or for a frozen build.
+5. Keep the deliberate `build.yml` dispatch/tag workflow and its three parallel platform builds. Remove redundant full portable-suite/lint/type execution from packaging jobs once its owner is explicit in CI. Retain build-specific prerequisite checks, real frozen worker/UI checks, and published-product checks. Preserve HAN-44's failure graph and diagnostics. Do not make a release eligible without required quality/native/build evidence: preserve existing release gates and document any branch-protection check-name changes for the human; do not silently edit repository settings.
+6. Required native/build jobs must fail or explicitly block when their dependencies, display, artifact, or process inspection are missing. Local unsupported-environment skips need precise reasons and cannot count as acceptance. Remove stale-bundle compatibility skips from required packaged validation. Do not globally skip macOS, popup, updater, or WebEngine coverage to make CI green.
+
+### Focused acceptance and checkpoint
+
+- Compare collected test cases before/after routing, accounting for moved node IDs. Every affected case has an owner; no coverage silently disappears and no portable suite is cloned per OS.
+- Prove portable selection does not import real GUI/native dependencies. Prove each native selection includes shared cases plus its OS cases and that missing required capabilities cannot yield an all-skipped green gate.
+- Run the affected portable tests and available native cases once. Verify updated workflow syntax, dependency ownership, and the retained HAN-44 failure scenarios only where this refactor changes them.
+- Update test commands in `packaging/README.md` and relevant repository guidance; update `docs/CODE-MAP.md` only for changed paths. Record routing and unavailable-host checks in the ledger. Commit, suggested title: **`chore: separate portable native and packaged test suites`**.
+
+## Part 3 — Super QA: close evidence gaps and fix confirmed native boundaries
+
+### Findings and bounded dispositions
+
+| Finding | What the existing log establishes | Work in this patch |
+| --- | --- | --- |
+| SUPERQA-001 | Frozen UI aborts during Qt construction in a screenless/sandboxed session; no final JSON | Preserve stage/exit evidence through HAN-44; validate source and freshly built UI on a visible macOS desktop; fix only a reproduced boundary defect |
+| SUPERQA-002 | pywebview receives no primary screen and reaches unsafe geometry access | Add a narrow no-screen guard after successful Qt bootstrap and before webview window creation; validate an ordinary screen still works |
+| SUPERQA-003 | Cocoa popup aborts at the Objective-C bridge in that environment | Verify visible-screen behavior; if reproduced, correct native-window readiness/bridge usage without losing non-activation |
+| SUPERQA-004 | Sandbox denies `ps`; lifecycle/leak and Darwin handoff evidence is unavailable | Report inspection unavailable accurately in the harness; verify real process retirement and updater handoff outside that sandbox |
+| SUPERQA-005 | Tested bundle says v0.1.3 while tested source says v0.5.0 | Fresh build from this branch and enforce source/package/artifact identity agreement |
+| SUPERQA-006 | Old frozen artifact has expensive cold worker startup and large disk footprint | Measure current cold/warm/residency/size once after UI works; compare existing evidence before selecting any runtime change |
+
+### Execute
+
+1. **Establish current artifact identity (005) before accepting new frozen evidence.** Inspect `tools/release_version.py`, package manifests, PyInstaller metadata collection, and existing identity reports. Extend the existing smoke/build verification to compare both frozen package versions with the expected source product version; record build commit and archive hashes in artifact identity. Version mismatch or missing required identity must fail the required gate. Do not “fix” the report by hardcoding `0.5.0`, changing the report to match an old bundle, or bumping versions without a release request. A hash of the archive is useful evidence but does not alone prove its source commit.
+2. **Handle the known no-screen boundary (001/002).** In `hanly_app/qt_bootstrap.py` / `control_center_host.py`, check for a usable primary screen after Qt successfully initializes and before pywebview reaches geometry/window creation. Raise/report the existing `ControlCenterUnavailable` condition. Add focused missing-screen and normal-screen tests. A check after `QApplication` construction cannot prevent an abort inside its constructor: retain the HAN-44 parent diagnostics for that case and do not claim universal graceful recovery. Do not select an alternate GUI backend or pin/downgrade Qt/pywebview unless visible-screen evidence actually establishes an incompatibility.
+3. **Validate and, if necessary, fix the Cocoa bridge (003).** Run the relocated popup-native checks in a normal visible macOS session. Current `QtPopupView._keep_visible_when_inactive` already guards `darwin` and the `cocoa` platform; do not repeat that fix. If the fault persists, isolate whether `winId()` has a real native window at construction or the typed selector call is wrong. Prefer applying the property once the native window exists, with a narrowly guarded readiness result, over replacing the whole adapter. Never message an arbitrary/offscreen handle or expect Python `try/except` to catch an Objective-C abort. If the optional native adjustment is unavailable, report it and keep safe Qt behavior; explicitly verify non-activation and inactive visibility before claiming the feature preserved.
+4. **Distinguish unavailable inspection from success (004).** Update `tests/hanly_fixtures/process_probe.py` and its consumers to report permission denial, missing probe tools, and timeout as inspection unavailable, never as an empty process list or a proven leak. Reuse an existing supported process API only if it preserves required PID/parent/command information; no new process-management framework. Local unsupported environments may skip with the reason; required native jobs must remain unsuccessful when they cannot verify retirement.
+
+   Retest Darwin `app_update_handoff.py` with a real executable fixture bundle and functioning LaunchServices/`/bin/ps`, not the synthetic unusable apps from the report. Preserve PID ownership, candidate cleanup, rollback, and unrelated-process safety. Do not change the production updater's process logic solely because a test sandbox denied `ps`; only make a narrowly evidenced change if the real packaged path reproduces it.
+5. **Build and validate the actual changed artifact.** Use the canonical `tools/prepare_easyocr_models.py`, `tools/build_package.py --platform macos`, and smoke commands documented in `packaging/README.md`. Use the intended packaging interpreter/constraints and isolated profile. Build the small dictionary with `tools/build_smoke_krdict.py`; do not depend on an incidental cache or a network release. Test the reconstructed ZIP's application and verify the DMG, not just an old `dist/macos/Hanly.app`. Record source/frozen versions, interpreter versions, commit, hashes, and diagnostics. Keep build outputs ignored.
+6. **Run only the missing native confirmations (001–004).** In a visible, unsandboxed macOS session, run source `python -m hanly_app --self-check ui`, the fresh packaged UI/worker smokes, popup, Control Center layout/lifecycle/WebEngine, lookup-process retirement, desktop startup, and Darwin updater handoff. Use the moved paths from Part 2. Bound each child run with the existing timeouts and capture stage/exit evidence. One successful frozen worker does not prove UI health. After UI passes, exercise launch, Control Center open/close/reopen, runtime status, settings, capture start/stop, ROI/target selection, hotkey lookup, popup retention/dismissal, resource update, quit, and relaunch once with a disposable profile.
+7. **Close the performance observation (006) without reopening optimization research.** Read `docs/execution/review-handoffs/han-40-packaged-size.md`, `han-41-idle-performance.md`, and `docs/execution/reports/ocr-latency-and-roadmap.md`. Using existing benchmark tooling, record current cold startup, a warm lookup, worker PID reuse across nearby lookups, retirement after the configured idle policy, RSS after close/retirement, and bundle/archive sizes. The historical 5.55s worker startup / 1.9s OCR / 1.3G bundle are stale-artifact observations, not new SLAs. If current behavior matches the approved policy, record the residual cost and a revisit trigger. If it demonstrates an actual lifecycle regression, fix that narrow regression and check it; do not change preload/idle defaults, Torch dispatch, OCR models, or dependency versions speculatively.
+
+### Acceptance and checkpoint
+
+- All six IDs have an explicit evidence-backed outcome in the ledger. Identity enforcement and missing-screen/inspection diagnostics have focused regression checks. Any confirmed popup/update/runtime fix has a check of the behavior it changes.
+- Visible UI, non-activation, process retirement, and update handoff need real native evidence. If the session cannot obtain the required display/process capabilities, finish independent code work and record the exact blocked checks; do not repeat the same failing environment or declare the bundle fully validated. No speculative native fix substitutes for that evidence.
+- Commit each coherent Super QA patch after its relevant check; suggested titles include **`fix: validate packaged artifact identity`**, **`fix: report unavailable native UI and process capabilities`**, and a precise popup title only if a popup fix is actually needed. Keep the existing QA report unchanged; put new evidence in the session record.
+
+### Bundle convergence and stop
+
+1. Run the mechanical gates once at convergence using `.venv` (or its activated `python`):
+
+   ```bash
+   python -m pytest
+   python -m ruff check packages packaging tests tools benchmarks
+   python -m mypy packages packaging tests tools benchmarks
+   ```
+
+   Record passes, failures, skips, and environment blocks separately. Include the explicit native/packaged commands established in Part 2 where the default command cannot exercise them. Reuse focused checks already run; rerun only affected checks after a correction. No broad test-audit loop.
+2. Verify HAN-44 failure behavior, HAN-43 coverage ownership, and the fresh artifact/UI findings together. Windows/Linux native/build acceptance needs the corresponding hosts; local parser tests do not establish it. Without push/remote-run authorization, record pending CI confirmation precisely rather than pushing or tagging to manufacture it.
+3. Consolidate the ledger with commit references, six finding dispositions, and remaining native/CI limitations. Inspect the final diff and all commit messages for scope and the **no attribution** requirement.
+4. Write one handoff at **`docs/execution/review-handoffs/han-43-44-superqa.md`**, using `TEMPLATE.md` through its Review assignment section only. Include implemented behavior, seams/files touched, checks and limitations, and suggested review targets. State **human-selected review; Phase B not started**. Commit this final documentation with `chore:` and the required concise bullets.
+5. Move completed, materially accepted implementation members to `In Review`; keep blocked/incomplete work accurately labeled. Do not claim release readiness if required native evidence is missing. Stop at the handoff. No merge, publication, new bundle, or self-authorized deep review.
diff --git a/packages/hanly-app/src/hanly_app/self_check.py b/packages/hanly-app/src/hanly_app/self_check.py
index 7ba02fc..e001519 100644
--- a/packages/hanly-app/src/hanly_app/self_check.py
+++ b/packages/hanly-app/src/hanly_app/self_check.py
@@ -13,15 +13,19 @@ from __future__ import annotations
 import faulthandler
 import json
 import sys
-from collections.abc import Callable
+from collections.abc import Callable, Iterator
+from contextlib import contextmanager
 from dataclasses import dataclass, field
 from pathlib import Path
 from time import perf_counter, sleep
-from typing import Any, TypeVar, cast
+from typing import TYPE_CHECKING, Any, TypeVar, cast
 
 from .diagnostics import runtime_versions
 from .runtime import HanlyRuntime, load_runtime
 
+if TYPE_CHECKING:
+    from .control_center_host import ControlCenterHost
+
 #: What ``--self-check`` accepts. ``worker`` proves the lookup runtime and
 #: ``ui`` proves the main window: a frozen build can fail at either one alone.
 SELF_CHECK_MODES = ("worker", "ui")
@@ -43,6 +47,13 @@ UI_READY_TIMEOUT_SECONDS = 60.0
 MORPHOLOGY_PROBE = "한국어"
 DICTIONARY_PROBE = "한국어"
 
+#: Progress markers go on stderr, one flushed JSON line each, because the
+#: report on stdout is written last and a native abort destroys it. The
+#: harness reads these to say which stage a killed process was inside.
+STAGE_MARKER_PREFIX = "hanly-self-check:"
+STAGE_STARTED = "stage_started"
+STAGE_COMPLETED = "stage_completed"
+
 StageValueT = TypeVar("StageValueT")
 
 
@@ -117,9 +128,11 @@ def run_self_check(
         _stage(stages, "morphology", _analyze)
         _stage(stages, "dictionary", lambda: _lookup(runtime))
         if worker is not None:
-            worker.close()
+            # Closing releases native handles the providers opened, so it is a
+            # stage of its own: a crash here is not the dictionary's fault.
+            _stage(stages, "worker close", worker.close)
 
-    return SelfCheckReport(mode=mode, stages=tuple(stages), versions=runtime_versions())
+    return SelfCheckReport(mode=mode, stages=tuple(stages), versions=_collected_versions())
 
 
 def report_self_check(
@@ -156,13 +169,15 @@ def _trace_native_crashes() -> None:
 def _run_ui_check() -> SelfCheckReport:
     """Open the real main window and drive it the way the desktop does."""
 
-    from .control_center import ControlCenterBridge
-    from .control_center_host import ControlCenterHost
-
-    host = ControlCenterHost(ControlCenterBridge())
     opened: list[StageResult] = []
     probes: list[StageResult] = []
 
+    # Importing Qt WebEngine is where a frozen build dies before a window ever
+    # exists, so the import is its own stage rather than the window's preamble.
+    host = _stage(opened, "window host", _create_window_host)
+    if host is None:
+        return SelfCheckReport(mode="ui", stages=tuple(opened), versions=_collected_versions())
+
     def drive() -> None:
         try:
             if _stage(probes, "document", lambda: _await_document(host)) is None:
@@ -176,10 +191,19 @@ def _run_ui_check() -> SelfCheckReport:
     # separately and reported after the window they were taken through.
     _stage(opened, "main window", lambda: _run_window(host, drive))
     return SelfCheckReport(
-        mode="ui", stages=(*opened, *probes), versions=runtime_versions()
+        mode="ui", stages=(*opened, *probes), versions=_collected_versions()
     )
 
 
+def _create_window_host() -> ControlCenterHost:
+    """Import the window's own stack and build the host that will run it."""
+
+    from .control_center import ControlCenterBridge
+    from .control_center_host import ControlCenterHost
+
+    return ControlCenterHost(ControlCenterBridge())
+
+
 def _run_window(host: object, drive: Callable[[], None]) -> str:
     """Run the GUI loop until the probe closes the window it opened."""
 
@@ -253,18 +277,59 @@ def _stage(
     """Run one step, recording its outcome instead of raising out of the check."""
 
     started = perf_counter()
+    _emit_marker(STAGE_STARTED, name)
     try:
         value = action()
     except BaseException as error:
-        stages.append(
-            StageResult(name, False, f"{type(error).__name__}: {error}", _elapsed_ms(started))
+        result = StageResult(
+            name, False, f"{type(error).__name__}: {error}", _elapsed_ms(started)
         )
+        stages.append(result)
+        _emit_marker(STAGE_COMPLETED, name, ok=False, duration_ms=result.duration_ms)
         return None
     detail = value if isinstance(value, str) else ""
-    stages.append(StageResult(name, True, detail, _elapsed_ms(started)))
+    result = StageResult(name, True, detail, _elapsed_ms(started))
+    stages.append(result)
+    _emit_marker(STAGE_COMPLETED, name, ok=True, duration_ms=result.duration_ms)
     return value
 
 
+@contextmanager
+def _marked(name: str) -> Iterator[None]:
+    """Bracket work that is worth naming but does not belong in the report."""
+
+    _emit_marker(STAGE_STARTED, name)
+    started = perf_counter()
+    try:
+        yield
+    finally:
+        _emit_marker(STAGE_COMPLETED, name, duration_ms=round(_elapsed_ms(started), 1))
+
+
+def _emit_marker(event: str, name: str, **fields: object) -> None:
+    """Write one flushed progress line, on the stream the report does not use.
+
+    A fatal native error never returns, so the harness cannot be told which
+    stage was running after the fact. Each marker is written and flushed before
+    the work it names, which is what survives an abort.
+    """
+
+    payload = {"event": event, "stage": name, **fields}
+    try:
+        print(f"{STAGE_MARKER_PREFIX} {json.dumps(payload)}", file=sys.stderr, flush=True)
+    except (OSError, ValueError):
+        # A frozen Windows build can be launched with no usable stderr at all;
+        # losing progress evidence must not lose the check itself.
+        return
+
+
+def _collected_versions() -> dict[str, str]:
+    """Read the identities the report carries, under a marker of its own."""
+
+    with _marked("versions"):
+        return runtime_versions()
+
+
 def _recognize(runtime: HanlyRuntime, image_path: Path) -> str:
     """Recognize a Korean fixture through the OCR provider this build ships."""
 
@@ -321,6 +386,9 @@ __all__ = [
     "MORPHOLOGY_PROBE",
     "RUNTIME_SELF_CHECK_MODES",
     "SELF_CHECK_MODES",
+    "STAGE_COMPLETED",
+    "STAGE_MARKER_PREFIX",
+    "STAGE_STARTED",
     "UI_PROBE_ELEMENTS",
     "SelfCheckReport",
     "StageResult",
diff --git a/packaging/README.md b/packaging/README.md
index 11c1d3c..a29be44 100644
--- a/packaging/README.md
+++ b/packaging/README.md
@@ -162,18 +162,23 @@ belongs to no bundle and no artifact; the released dictionary is still the
 independently published resource a real first run downloads.
 
 On macOS the checks run against the application unpacked back out of the
-published ZIP, not the build directory it was made from, and the disk image is
-mounted read-only and reported on beside it:
+published ZIP, not the build directory it was made from. Reconstruction and the
+disk image are separate invocations, because they check separate published
+products and a ZIP that will not unpack says nothing about the DMG:
 
 ```bash
 python tools/smoke_packaged_runtime.py \
     --from-archive dist/hanly-desktop-macos.zip \
     --reconstruct-into dist/reconstructed \
-    --disk-image dist/hanly-desktop-macos.dmg \
-    --inventory-only
+    --reconstruct-only
+python tools/smoke_packaged_runtime.py --disk-image dist/hanly-desktop-macos.dmg
+python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --inventory-only
 python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --window-only
 ```
 
+Mounting is not the disk-image check: a DMG that opens onto something other
+than `Hanly.app` fails, because that is the download a person would find empty.
+
 The inventory also names the two build inputs a frozen bundle cannot fetch:
 `certifi/cacert.pem` and both EasyOCR weights. A bundle missing them has
 working code and no way to verify a certificate or read a word.
@@ -183,6 +188,44 @@ uses the platform's build output (`dist/<platform>/hanly-desktop`, or
 `dist/macos/Hanly.app`) by default, or the bundle named by
 `HANLY_PACKAGED_APP`.
 
+## What a failed run leaves behind
+
+A native fault ends the frozen process before it prints its report, so the exit
+status used to be the whole account — and `3221225501` names no suspect. Two
+things now survive that.
+
+The self-check writes one flushed JSON line per stage boundary on **stderr**,
+which the harness reads before it truncates anything. The stage that was
+started and never completed is reported as `current_stage`, so a failed run
+says `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)` rather than a
+number. A crash before the first marker stays `current_stage: unknown`; naming
+the last stage that passed would invent a diagnosis. Provider construction,
+OCR, morphology, dictionary, closing the worker, the Qt WebEngine import, the
+window itself, and each page probe all carry a marker.
+
+`tools/native_host_fingerprint.py` records what the machine actually is —
+operating system and build, CPU model and vendor, core counts, the build
+interpreter — before the first install, so a run that dies later still says
+which host it died on. `--with-torch` adds what Torch reports about the CPU
+from a subprocess of its own, since importing Torch is one of the things that
+ends a packaging run. A field the host will not answer for carries the reason;
+nothing is filled in with a plausible default, and neither environment
+variables nor process inventories are collected.
+
+```bash
+python tools/native_host_fingerprint.py --context "before install" \
+    --output dist/reports/hanly-host-macos.json
+```
+
+In CI every check states the product it needs, so one failure no longer skips
+the rest. A failed worker smoke still leaves the window smoke, the archive
+checks, and the artifact identity; a failed reconstruction still leaves the
+disk-image evidence. The `hanly-diagnostics-<platform>` artifact is uploaded
+whether or not the run succeeded, and carries `dist/reports/` — every JSON
+report, the captured stdout and stderr of each smoke, and the host
+fingerprints — plus PyInstaller's warning and cross-reference output. It is
+never a release product, and a required failure still fails the job.
+
 ## Artifact and resource conventions
 
 Windows and Linux write a onedir tree under `dist/<platform>/hanly-desktop/`;
diff --git a/superqa.md b/superqa.md
new file mode 100644
index 0000000..da2a5ba
--- /dev/null
+++ b/superqa.md
@@ -0,0 +1,390 @@
+# Hanly Super QA Report
+
+**Run date:** 2026-09-13  
+**Repository:** `/Users/thiago/Projects/hanly`  
+**Commit tested:** `900dba1` (`v0.5.0`, `main`, clean at test start)  
+**Host:** macOS, arm64, Python 3.13.11 in `.venv`  
+**Packaged artifact:** `dist/macos/Hanly.app` (embedded Python 3.10.20, reported app version `0.1.3`)  
+**Scope:** read-only QA. No production files or tests were modified. This report is the only intended repository artifact.
+
+## Executive verdict
+
+**Overall: BLOCKED / UI cannot be approved from this host.**
+
+The reusable lookup engine, provider composition, dictionary path, hover state
+logic, update service, startup mocks, packaging inventory, and benchmark tooling
+are healthy under deterministic tests. The real native UI path cannot be
+validated on this host because child GUI processes have no usable screen:
+
+1. Packaged `--self-check ui` exits with `SIGABRT` while creating Qt.
+2. Control Center integration fails before the page is usable; the child has no
+   primary screen and pywebview reaches an unsafe `QScreen.geometry` call.
+3. Cocoa popup construction exits with `SIGABRT` in the Objective-C bridge.
+4. Native process-lifecycle checks cannot inspect children because this sandbox
+   denies `/bin/ps`; these results are environment-blocked, not proof of a
+   product defect.
+
+The packaged worker path is healthy: the isolated frozen self-check recognized
+Korean text, ran Kiwi morphology, and returned a KRDICT entry. That does not
+prove UI health, and the UI findings must be repeated in a normal visible macOS
+session before they are classified as confirmed product defects.
+
+## Evidence summary
+
+| Area | Result | Evidence |
+|---|---|---|
+| Ruff | PASS | `All checks passed!` |
+| Mypy | PASS | `Success: no issues found in 196 source files` |
+| Broad non-native suite | PASS | `1182 passed, 1 skipped in 10.82s`, excluding native GUI integration, app-update handoff, and Qt popup files |
+| Engine/provider focused tests | PASS | 125 passed in 4.58s |
+| Capture/hotkeys/permissions | PASS | 123 passed in 0.68s; mocked/contract coverage |
+| Hover logic | PASS | 83 passed in 1.75s; popup-native path excluded by crash |
+| Updates | PASS | 108 passed in 0.82s; native Darwin handoff failures remain |
+| Startup/runtime/application | PASS | 93 passed in 0.70s; GUI startup not represented by mocks |
+| Packaging/release tests | PASS | 199 passed in 1.35s |
+| KRDICT tooling | PASS | 49 passed, 1 skipped in 1.87s |
+| Developer benchmark tests | PASS | 60 passed in 0.35s |
+| Frozen worker self-check | PASS | `ok: true`; runtime, worker, OCR, morphology, dictionary all passed |
+| Frozen UI self-check | FAIL / abort | exit 134; fatal native abort during `ensure_qt_application` |
+| Control Center integration | BLOCKED / fail | no-screen child fails before usable page; run stopped after 246.60s |
+| Qt popup window | BLOCKED / abort | isolated no-screen test process exits 134 in Cocoa native bridge |
+| Qt WebEngine startup | BLOCKED / abort | `Cannot create window: no screens available`; 1 failed, 1 skipped |
+
+## Findings requiring review
+
+### SUPERQA-001 — Packaged UI self-check aborts before producing a report
+
+**Severity:** Critical / release blocker.  
+**Status:** Reproducible on this host; likely environment-sensitive and needs a
+normal visible macOS retest before being called a product crash.
+
+**Reproduction:**
+
+```text
+./dist/macos/Hanly.app/Contents/MacOS/hanly-desktop --self-check ui
+```
+
+**Observed:** exit code `134` (`SIGABRT`). Stderr contains Apple pasteboard/XPC
+errors followed by a fatal Python abort. The fatal frames are:
+
+```text
+hanly_app/qt_bootstrap.py:58 in ensure_qt_application
+hanly_app/control_center_host.py:348 in _load_webview
+hanly_app/self_check.py:186 in _run_window
+```
+
+No JSON self-check report is emitted. A CUA launch of the same repository bundle
+started a Hanly process, but its accessibility state timed out, so no
+interactive UI feature could be verified.
+
+**Impact:** This environment cannot complete the UI readiness probe. The lack of
+a graceful “no screen” failure is itself a robustness concern, but the release
+impact is unconfirmed until a normal visible desktop is tested.
+
+**Suggested next test:** Run the exact command from a normal Terminal session
+with the same bundle and on a clean macOS account. Capture the native crash
+backtrace and compare with a source `python -m hanly_app --self-check ui` run.
+The expected minimum is one visible display and a successful Qt/WebEngine
+window, not merely a nonzero JSON status.
+
+### SUPERQA-002 — Control Center has no headless/no-screen failure path
+
+**Severity:** High robustness risk; environment-blocked product confirmation.  
+**Status:** Reproducible only in the current screenless child environment.
+
+**Observed traceback:**
+
+```text
+.venv/lib/python3.13/site-packages/webview/platforms/qt.py:343
+self.screen = QScreen.geometry(QApplication.primaryScreen())
+TypeError: geometry(self): first argument of unbound method must have type 'QScreen'
+```
+
+Installed versions are pywebview `6.2.1` and PyQt6 `6.11.0`. The same run also
+reports `QT QtMsgType.QtFatalMsg Cannot create window: no screens available`.
+The pywebview line is reached with `QApplication.primaryScreen()` unavailable,
+so this run does not prove a normal-screen version incompatibility.
+
+The lifecycle report had `page_reached_the_bridge: false` and
+`running_after_open: false`.
+
+**Impact:** The Control Center page does not reach the bridge in this
+environment. A robustness improvement would convert no-screen/native-init
+failures into a diagnostic result rather than an abort, but normal desktop
+behavior remains to be tested.
+
+**Suggested upgrade:** First rerun with a real visible screen. If it reproduces,
+pin or constrain a known-compatible pywebview/PyQt6 pair or add a narrow
+compatibility/no-screen guard before window creation. Re-run layout, lifecycle,
+webengine, and packaged UI gates. Do not silently fall back to another GUI
+backend.
+
+### SUPERQA-003 — Cocoa popup construction aborts in the Objective-C bridge
+
+**Severity:** High robustness risk; environment-blocked product confirmation.  
+**Status:** Reproducible in the current screenless Cocoa test process.
+
+**Reproduction:**
+
+```text
+./.venv/bin/python -m pytest tests/test_qt_popup_window.py -q
+```
+
+**Observed:** exit code `134` (`SIGABRT`). The fatal frame is:
+
+```text
+packages/hanly-app/src/hanly_app/qt_popup.py:139
+    keep_visible_when_inactive(int(self.winId()))
+```
+
+The call enters `popup_darwin.py:keep_visible_when_inactive`, which sends
+Objective-C messages through a hand-built `ctypes` `objc_msgSend` bridge. The
+abort occurs while constructing the first `QtPopupView`, before any popup test
+can assert flags, rendering, positioning, hide, or close behavior.
+
+**Impact:** Popup behavior cannot be tested here. A crash-free fallback is still
+desirable at this ABI boundary, but a normal-screen repro is required before
+calling it a confirmed product defect.
+
+**Suggested next test:** In a temporary copy only, and after repeating on a
+visible screen, guard the native call behind
+a post-show native-window check or disable it to determine whether the fault is
+“window does not exist yet” or an ABI/selector problem. The production fix must
+retain the non-activating popup contract and provide a crash-free fallback.
+
+### SUPERQA-004 — Native process probes are blocked by `/bin/ps`
+
+**Severity:** High test-environment blocker; product severity unconfirmed.  
+**Status:** Reproduced by the current sandbox.
+
+Affected evidence includes `test_lookup_process_spawn.py`,
+`test_desktop_startup.py`, `test_control_center_lifecycle.py`, and three Darwin
+cases in `test_app_update_handoff.py`. The common error is:
+
+```text
+PermissionError: [Errno 1] Operation not permitted: 'ps'
+```
+
+The production macOS update handoff also generates a `/bin/ps` probe in
+`app_update_handoff.py:232`, so this needs an unsandboxed product check even
+though the current failures originate in test/OS policy.
+
+**Impact:** Child retirement, shell isolation, and update-candidate cleanup are
+not proven by this run. This is not evidence that the implementation leaks.
+
+**Suggested upgrade:** Add a supported process-inspection fallback or make the
+test harness report “inspection unavailable” instead of turning this condition
+into a product-looking failure. Verify `/bin/ps` in the actual packaged context.
+
+### SUPERQA-005 — Source is v0.5.0 while the tested bundle reports v0.1.3
+
+**Severity:** High release/process risk.  
+**Status:** Confirmed.
+
+`git HEAD` is `900dba1`, tag `v0.5.0`; both package manifests say `0.5.0`, but
+the frozen worker reports `hanly: 0.1.3` and `hanly-app: 0.1.3`. `dist/` is
+ignored, so this may simply be a stale local artifact, but it must not be used
+as v0.5.0 release evidence until rebuilt from the tested commit.
+
+### SUPERQA-006 — Startup/warmup and package size dominate performance
+
+**Severity:** Medium-to-high performance risk.  
+**Status:** Measured for the frozen worker; memory leakage not measurable in the
+current sandbox.
+
+Frozen worker timing:
+
+```text
+real 9.32s, user 7.38s, sys 0.98s
+runtime:        185.3 ms
+lookup worker: 5555.1 ms
+OCR:            1907.1 ms
+morphology:     1154.0 ms
+dictionary:      135.9 ms
+```
+
+Disk measurements:
+
+```text
+Hanly.app:                  1.3G
+macOS onedir tree:          1.3G
+macOS ZIP:                  534M
+macOS DMG:                  608M
+KRDICT generated database:   96M
+```
+
+Worker construction dominates. This becomes a serious UX problem if the lookup
+child is retired and recreated too aggressively. The dictionary query is not
+the bottleneck. Repeat RSS and warm-lookup measurements in an unsandboxed run.
+
+## Feature-by-feature QA
+
+### F01 — Engine contracts and lookup pipeline
+
+**Grade:** GOOD  
+**Code quality:** Clear provider seams and normalized contracts; normal
+non-success is separate from processing errors.  
+**Possible bugs:** None found in exercised paths.  
+**Tests made:** 125 engine/provider tests passed; frozen worker passed from ROI
+through OCR, morphology, and dictionary.  
+**Observations:** Korean fixture lookup returned a valid entry. This is the
+strongest part of the current build.
+
+### F02 — EasyOCR provider and OCR policy
+
+**Grade:** GOOD, with performance follow-up  
+**Code quality:** Configuration and image formats are validated; malformed
+results become provider errors; no Paddle selector was found.  
+**Possible bugs:** None functional; first worker construction is expensive.  
+**Tests made:** EasyOCR tests passed within the 125 engine/provider tests and
+the frozen OCR self-check passed.  
+**Observations:** OCR took about 1.9s in the frozen worker run.
+
+### F03 — Kiwi morphology and KRDICT dictionary
+
+**Grade:** GOOD  
+**Code quality:** Outputs are normalized, SQLite is read-only, and schema
+validation is shared across build/runtime/update paths.  
+**Possible bugs:** None found in normal, empty, not-found, or provider-error
+paths.  
+**Tests made:** 49 KRDICT tooling tests passed with one skip; frozen dictionary
+stage passed with one entry for `한국어`.  
+**Observations:** Dictionary latency was about 36–136ms and is not the primary
+performance issue.
+
+### F04 — Lookup child, process transport, and lifecycle
+
+**Grade:** MID / insufficient native evidence  
+**Code quality:** Framing, bounded message size, child ownership, and close paths
+are well-covered by unit tests.  
+**Possible bugs:** No confirmed transport defect; retirement and shell isolation
+remain unproven because process inspection is denied.  
+**Tests made:** Unit/transport tests passed; real child integration failed when
+the fixture called `ps`.  
+**Observations:** Frozen worker construction and close succeeded; repeat with
+native process inspection enabled.
+
+### F05 — Capture, ROI selection, hotkeys, and permissions
+
+**Grade:** GOOD in deterministic tests; LIVE status unverified  
+**Code quality:** Services are isolated behind seams and platform adapters;
+permission states distinguish denied, missing, and unknown.  
+**Possible bugs:** No deterministic defect; actual capture, DPI, multi-monitor
+coordinates, and global hotkey delivery were not live-verified.  
+**Tests made:** 123 capture/hotkey/permission tests passed.  
+**Observations:** This is contract-level confidence, not a manual desktop pass.
+
+### F06 — Hover controller, debounce, retention, and stale results
+
+**Grade:** GOOD for orchestration; popup presentation blocked  
+**Code quality:** Hover decision-making is separate from observation and OCR;
+latest-wins and retention rules are covered.  
+**Possible bugs:** None found in 83 focused hover tests.  
+**Tests made:** 83 hover tests passed; popup-native test process aborts.  
+**Observations:** The path is blocked at the final UI surface, not hover logic.
+
+### F07 — Popup rendering, positioning, hide/close, and non-activation
+
+**Grade:** BLOCKED / unconfirmed  
+**Code quality:** Responsibilities and intended flags are explicit, but the
+macOS visibility workaround is a high-risk ABI boundary with no safe fallback.
+  
+**Possible bugs:** SUPERQA-003; current repro may be caused by the screenless
+child environment.  
+**Tests made:** `tests/test_qt_popup_window.py` exits 134.  
+**Observations:** Do not accept the popup capability based on static flags or
+mocked controller tests.
+
+### F08 — Control Center and bridge
+
+**Grade:** BLOCKED / unconfirmed  
+**Code quality:** Assets and bridge contracts have broad pure tests; the host
+explicitly requires Qt.  
+**Possible bugs:** SUPERQA-001 and SUPERQA-002; both need a visible-screen
+retest.  
+**Tests made:** Pure Control Center tests passed; layout/lifecycle integration
+fails before bridge reachability.  
+**Observations:** Start/stop, settings, runtime state, resources, updates, and
+quit cannot be graded as working through the real page.
+
+### F09 — Startup, first run, runtime config, and shell lifecycle
+
+**Grade:** MID / UI blocked  
+**Code quality:** Entry ordering, diagnostics, first-run provisioning, and
+runtime factory composition are strongly tested.  
+**Possible bugs:** Actual packaged UI startup is blocked by SUPERQA-001; source
+desktop startup did not produce its report on this host.  
+**Tests made:** 93 startup/runtime/application tests passed; frozen worker passed;
+packaged UI self-check aborted.  
+**Observations:** Worker readiness is healthy, shell/UI readiness is not.
+
+### F10 — Update service, handoff, rollback, and cleanup
+
+**Grade:** MID  
+**Code quality:** Resource update tests cover checksum, schema, atomic activation,
+rollback, and serialization.  
+**Possible bugs:** SUPERQA-004 blocks three Darwin handoff cases; LaunchServices
+also reported `kLSNoExecutableErr` for synthetic fixture apps.  
+**Tests made:** 108 update/coordinator tests passed; Darwin handoff isolation
+reported 154 passed, 3 failed, and 2 skipped before additional native cases
+were stopped.  
+**Observations:** Retest with a real executable bundle and native process tools.
+
+### F11 — Packaging, frozen inventory, and release gates
+
+**Grade:** GOOD for worker/inventory; UI gate blocked  
+**Code quality:** One entry point is enforced and the worker self-check uses real
+frozen providers.  
+**Possible bugs:** SUPERQA-005 stale local artifact; SUPERQA-001 UI gate failure.
+  
+**Tests made:** 199 packaging/release tests passed; packaged dependency and
+worker integration passed (`2 passed`); deep strict ad-hoc codesign verification
+returned no error.  
+**Observations:** Rebuild `dist/` from `v0.5.0` before release evidence.
+
+### F12 — Benchmark and observability tooling
+
+**Grade:** GOOD as tooling; live telemetry insufficient  
+**Code quality:** Tests cover bounded telemetry, privacy redaction, summaries,
+and failure handling.  
+**Possible bugs:** No tooling defect; live RSS/process sampling is blocked by
+process-inspection restrictions.  
+**Tests made:** 60 benchmark tests passed; frozen worker timing captured.  
+**Observations:** The tooling is ready for an unsandboxed performance run.
+
+## Code quality assessment
+
+**Grade:** GOOD overall, with two dangerous native boundaries.
+
+- Ruff and mypy are clean.
+- Package direction and provider seams are preserved.
+- The engine models success, normal non-success, and errors well.
+- The test suite is extensive and mostly deterministic.
+- The Objective-C popup bridge and Qt/pywebview compatibility boundary need
+  stronger runtime guards and native smoke coverage.
+- Broad exception handling appears intentional at process/UI boundaries, but a
+  follow-up review should verify that every swallowed exception is reported and
+  that fatal native calls are not assumed catchable by Python `try` blocks.
+
+## Recommended follow-up order
+
+1. Reproduce SUPERQA-001, SUPERQA-002, and SUPERQA-003 in a normal visible,
+   unsandboxed macOS session; only then fix confirmed native failures.
+2. If SUPERQA-002 reproduces with a screen, resolve it by pinning/adapting the
+   pywebview/PyQt6 pair, then run layout, lifecycle, webengine, and packaged UI
+   gates.
+3. Rebuild `dist/` from `900dba1` and rerun worker plus UI packaged gates.
+4. Repeat process-retirement, update-handoff, desktop-startup, and memory tests
+   where `/bin/ps` and LaunchServices are available.
+5. Only after UI stability, manually exercise launch, Control Center, runtime
+   state, capture start/stop, target/ROI selection, hotkey lookup, popup
+   retention/dismissal, resource update, quit, and relaunch.
+
+## Delegation note
+
+Ten GPT-5.6 Luna reviewers were requested in parallel at high reasoning effort,
+split across the ten subsystem slices described in the kickoff. The thread
+creation API returned setup handles (`clientThreadId`) but did not expose
+readable task IDs/results during this run, so no subagent output is represented
+as evidence here. All findings above come from direct repository inspection and
+executed commands listed in this report.
diff --git a/tests/test_ci_workflows.py b/tests/test_ci_workflows.py
index 7f1fba3..2201d96 100644
--- a/tests/test_ci_workflows.py
+++ b/tests/test_ci_workflows.py
@@ -7,6 +7,7 @@ change does not fail and a semantic regression does not pass unnoticed.
 from __future__ import annotations
 
 import re
+from collections.abc import Sequence
 from pathlib import Path
 from typing import Any
 
@@ -240,11 +241,7 @@ def test_linux_build_uses_the_cpu_only_ocr_runtime() -> None:
 
 
 def test_build_retains_the_release_archive_and_its_evidence() -> None:
-    upload = next(
-        step
-        for step in _steps(_workflow("build.yml"), "build")
-        if "upload-artifact" in step.get("uses", "")
-    )
+    upload = _step(_workflow("build.yml"), "build", name="Retain platform artifact")
     paths = [line.strip() for line in upload["with"]["path"].splitlines() if line.strip()]
 
     assert upload["with"]["name"] == "hanly-desktop-${{ matrix.platform }}"
@@ -271,14 +268,14 @@ def test_every_native_build_proves_the_frozen_runtime_before_retaining_it() -> N
     inventory = names.index("Check the frozen bundle inventory")
     smoke = names.index("Smoke the frozen lookup runtime")
     build = names.index("Build application package")
-    retain = next(
-        index for index, step in enumerate(steps) if "upload-artifact" in step.get("uses", "")
-    )
+    retain = names.index("Retain platform artifact")
 
     assert build < inventory < smoke < retain
     for index in (inventory, smoke):
         assert "smoke_packaged_runtime.py" in steps[index]["run"]
-        assert "if" not in steps[index], "the frozen gates run on every platform"
+        assert "matrix.platform" not in str(
+            steps[index].get("if", "")
+        ), "the frozen gates run on every platform"
     # A real image, so the frozen OCR stack has to read Korean rather than
     # merely import.
     assert "korean_reading_roi.png" in steps[smoke]["run"]
@@ -296,7 +293,9 @@ def test_the_frozen_smoke_installs_a_dictionary_built_on_the_runner() -> None:
 
     assert build_dictionary < smoke
     for index in (build_dictionary, smoke):
-        assert "if" not in steps[index], "every platform needs the dictionary"
+        assert "matrix.platform" not in str(
+            steps[index].get("if", "")
+        ), "every platform needs the dictionary"
     # The runner's own temporary space: it is never an artifact, never part of
     # the bundle, and disappears with the job.
     assert _uses_shell_variable(steps[build_dictionary]["run"], "RUNNER_TEMP")
@@ -312,13 +311,13 @@ def test_every_native_build_opens_the_frozen_window_it_is_about_to_ship() -> Non
     steps = _steps(_workflow("build.yml"), "build")
     names = [step.get("name", "") for step in steps]
     window = names.index("Smoke the frozen Control Center")
-    retain = next(
-        index for index, step in enumerate(steps) if "upload-artifact" in step.get("uses", "")
-    )
+    retain = names.index("Retain platform artifact")
 
     assert names.index("Build application package") < window < retain
     assert "--window-only" in steps[window]["run"]
-    assert "if" not in steps[window], "the window check runs on every platform"
+    assert "matrix.platform" not in str(
+        steps[window].get("if", "")
+    ), "the window check runs on every platform"
     # A hosted Linux runner has no display of its own.
     assert "xvfb-run" in steps[window]["run"]
     # All three are gates now. macOS and Linux were recorded-only for one
@@ -327,6 +326,178 @@ def test_every_native_build_opens_the_frozen_window_it_is_about_to_ship() -> Non
     assert "continue-on-error" not in steps[window]
 
 
+# --- What one failed packaging step is still allowed to prove -----------------
+#
+# A default GitHub step runs only while every step before it succeeded, so one
+# failed smoke used to skip every later check and the artifact upload with
+# them: a red run produced a single line of evidence. Each step below states
+# the product it actually needs, and the scenarios prove what survives.
+
+#: The step conditions these workflows use, evaluated the way Actions does.
+_STATUS_TERMS = {"always()": True, "!cancelled()": True, "cancelled()": False}
+
+_STEP_OUTCOME = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outcome\s*==\s*'(\w+)'")
+_MATRIX_PLATFORM = re.compile(r"matrix\.platform\s*==\s*'(\w+)'")
+
+
+def _step_key(step: dict[str, Any]) -> str:
+    return str(step.get("id") or step.get("name", ""))
+
+
+def _term_holds(term: str, outcomes: dict[str, str], platform: str, failed: bool) -> bool:
+    """Decide one ``&&``-separated term, refusing to guess at an unknown one."""
+
+    if term in _STATUS_TERMS:
+        return _STATUS_TERMS[term]
+    if term == "success()":
+        return not failed
+    outcome = _STEP_OUTCOME.fullmatch(term)
+    if outcome is not None:
+        return outcomes.get(outcome.group(1)) == outcome.group(2)
+    matrix = _MATRIX_PLATFORM.fullmatch(term)
+    if matrix is not None:
+        return platform == matrix.group(1)
+    if term.startswith("startsWith(github.ref"):
+        return False
+    raise AssertionError(f"unmodelled step condition: {term!r}")
+
+
+def _condition_holds(
+    condition: str, outcomes: dict[str, str], platform: str, failed: bool
+) -> bool:
+    expression = condition.strip().removeprefix("${{").removesuffix("}}").strip()
+    return all(
+        _term_holds(term.strip(), outcomes, platform, failed)
+        for term in expression.split("&&")
+    )
+
+
+def _run_plan(
+    job: str, *, platform: str, failing: Sequence[str] = ()
+) -> dict[str, str]:
+    """Replay the job, returning what each step's outcome would have been.
+
+    A step that states no condition of its own inherits ``success()``, which is
+    exactly the default that made one failure hide every later check.
+    """
+
+    outcomes: dict[str, str] = {}
+    failed = False
+    for step in _steps(_workflow("build.yml"), job):
+        key = _step_key(step)
+        condition = step.get("if")
+        runs = (
+            not failed
+            if condition is None
+            else _condition_holds(str(condition), outcomes, platform, failed)
+        )
+        outcomes[key] = ("failure" if key in failing else "success") if runs else "skipped"
+        failed = failed or outcomes[key] == "failure"
+    return outcomes
+
+
+RELEASE_UPLOAD = "Retain platform artifact"
+DIAGNOSTIC_UPLOAD = "Retain build diagnostics"
+
+
+def test_a_failed_worker_smoke_still_proves_the_window_and_the_products() -> None:
+    outcomes = _run_plan("build", platform="macos", failing=["worker_smoke"])
+
+    assert outcomes["ui_smoke"] == "success"
+    assert outcomes["disk_image"] == "success"
+    assert outcomes["archives"] == "success"
+    assert outcomes["identity"] == "success"
+    assert outcomes[DIAGNOSTIC_UPLOAD] == "success"
+    # The failure is still the job's failure; nothing is published from it.
+    assert outcomes[RELEASE_UPLOAD] == "skipped"
+
+
+def test_a_missing_dictionary_skips_the_worker_and_leaves_the_window() -> None:
+    """The window opens no provider, so it never needed the dictionary."""
+
+    outcomes = _run_plan("build", platform="linux", failing=["dictionary"])
+
+    assert outcomes["worker_smoke"] == "skipped"
+    assert outcomes["ui_smoke"] == "success"
+    assert outcomes[DIAGNOSTIC_UPLOAD] == "success"
+
+
+def test_a_zip_that_will_not_reconstruct_still_leaves_disk_image_evidence() -> None:
+    outcomes = _run_plan("build", platform="macos", failing=["resolve"])
+
+    assert outcomes["disk_image"] == "success"
+    assert outcomes["archives"] == "success"
+    for dependent in ("inventory", "worker_smoke", "ui_smoke"):
+        assert outcomes[dependent] == "skipped"
+
+
+def test_a_failed_build_suppresses_every_check_of_what_it_did_not_make() -> None:
+    """A freeze that failed produced no application; smoking one would report
+    a second, invented failure on top of the real one."""
+
+    outcomes = _run_plan("build", platform="windows", failing=["build"])
+
+    for dependent in ("resolve", "inventory", "dictionary", "worker_smoke", "ui_smoke"):
+        assert outcomes[dependent] == "skipped"
+    assert outcomes["archives"] == "skipped"
+    # The host fingerprint and any PyInstaller output still travel.
+    assert outcomes[DIAGNOSTIC_UPLOAD] == "success"
+
+
+def test_a_run_where_everything_passes_publishes_its_artifact() -> None:
+    outcomes = _run_plan("build", platform="macos")
+
+    assert outcomes[RELEASE_UPLOAD] == "success"
+    assert outcomes[DIAGNOSTIC_UPLOAD] == "success"
+
+
+def test_no_packaging_step_is_allowed_to_fail_quietly() -> None:
+    """`continue-on-error` keeps a run green; these steps are the gates."""
+
+    for step in _steps(_workflow("build.yml"), "build"):
+        assert "continue-on-error" not in step, step.get("name")
+
+
+def test_the_diagnostic_upload_is_never_a_release_product() -> None:
+    workflow = _workflow("build.yml")
+    diagnostics = _step(workflow, "build", name=DIAGNOSTIC_UPLOAD)
+    release = _step(workflow, "build", name=RELEASE_UPLOAD)
+
+    assert diagnostics["with"]["if-no-files-found"] == "ignore"
+    # `release.yml` collects `hanly-desktop-*`; a diagnostic bundle that matched
+    # that pattern would be downloaded as a platform build.
+    assert not diagnostics["with"]["name"].startswith("hanly-desktop-")
+    assert release["with"]["name"].startswith("hanly-desktop-")
+    assert "if" not in release
+
+
+def test_the_host_is_fingerprinted_before_anything_can_crash_on_it() -> None:
+    """An illegal instruction is a CPU the build had no record of."""
+
+    steps = _steps(_workflow("build.yml"), "build")
+    names = [step.get("name", "") for step in steps]
+    fingerprint = names.index("Record the host fingerprint")
+    runtime = names.index("Record what the installed runtime reports")
+
+    assert fingerprint < names.index("Install development dependencies")
+    assert names.index("Install packages") < runtime < names.index("Build application package")
+    # Torch is only asked once it exists, and in a child that may not survive.
+    assert "--with-torch" not in steps[fingerprint]["run"]
+    assert "--with-torch" in steps[runtime]["run"]
+
+
+def test_each_smoke_keeps_the_output_of_a_harness_that_never_reported() -> None:
+    """A JSON report is written only if the harness lived to write one, and a
+    step whose evidence exists only in the log cannot be uploaded."""
+
+    for step_id in ("worker_smoke", "ui_smoke"):
+        step = _step(_workflow("build.yml"), "build", step_id=step_id)
+        code = _shell_code(step["run"])
+
+        assert '> "$report.json" 2> "$report.err"' in code
+        assert 'exit "$status"' in code
+
+
 def test_each_artifact_records_the_identity_it_was_built_from() -> None:
     """One macOS runner architecture cannot stand in for the other."""
 
diff --git a/tests/test_host_fingerprint.py b/tests/test_host_fingerprint.py
new file mode 100644
index 0000000..5355ae7
--- /dev/null
+++ b/tests/test_host_fingerprint.py
@@ -0,0 +1,224 @@
+"""What the packaging host fingerprint records, and what it refuses to invent."""
+
+from __future__ import annotations
+
+import json
+import re
+import subprocess
+import sys
+from collections.abc import Callable, Sequence
+from pathlib import Path
+from typing import cast
+
+import pytest
+
+from tools.native_host_fingerprint import (
+    CPUINFO_PATH,
+    OS_RELEASE_PATH,
+    TORCH_PROBE,
+    ProbeError,
+    collect_fingerprint,
+    darwin_facts,
+    linux_facts,
+    probe_torch,
+    windows_facts,
+)
+
+CPUINFO = """\
+processor\t: 0
+vendor_id\t: GenuineIntel
+model name\t: Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz
+cpu cores\t: 2
+"""
+
+OS_RELEASE = """\
+NAME="Ubuntu"
+PRETTY_NAME="Ubuntu 24.04.3 LTS"
+VERSION_ID="24.04"
+"""
+
+WINDOWS_RECORDS = {
+    "os": {
+        "Caption": "Microsoft Windows Server 2022 Datacenter",
+        "Version": "10.0.20348",
+        "BuildNumber": "20348",
+    },
+    "cpu": {
+        "Name": "AMD EPYC 7763 64-Core Processor",
+        "Manufacturer": "AuthenticAMD",
+        "NumberOfCores": 2,
+        "NumberOfLogicalProcessors": 4,
+    },
+}
+
+
+def _answers(replies: dict[str, str]):
+    """A probe runner that answers by command name, and refuses anything else."""
+
+    def run(command: Sequence[str]) -> str:
+        key = " ".join(command[1:]) if len(command) > 1 else command[0]
+        if key not in replies:
+            raise ProbeError(f"{command[0]} has no {key}")
+        return replies[key]
+
+    return run
+
+
+def _reader(files: dict[str, str]):
+    def read(path: str) -> str:
+        if path not in files:
+            raise OSError(2, "No such file or directory")
+        return files[path]
+
+    return read
+
+
+def test_macos_reports_the_product_build_and_the_cpu_brand() -> None:
+    operating_system, cpu = darwin_facts(
+        _answers(
+            {
+                "-productName": "macOS",
+                "-productVersion": "15.6",
+                "-buildVersion": "24G84",
+                "-n machdep.cpu.brand_string": "Apple M1 Pro",
+                "-n hw.physicalcpu": "8",
+            }
+        )
+    )
+
+    assert operating_system.values["build"] == "24G84"
+    assert cpu.values["model"] == "Apple M1 Pro"
+    assert cpu.values["physical_cores"] == 8
+
+
+def test_a_field_the_host_withholds_carries_its_reason_not_a_default() -> None:
+    """Apple silicon has no ``machdep.cpu.vendor``, and "unknown" would read as
+    a fact. The reason is what tells the next reader the probe was even tried."""
+
+    _, cpu = darwin_facts(_answers({"-n machdep.cpu.brand_string": "Apple M1 Pro"}))
+
+    assert cpu.values["vendor"] is None
+    assert "machdep.cpu.vendor" in cpu.unavailable["vendor"]
+    assert cpu.values["physical_cores"] is None
+    assert "hw.physicalcpu" in cpu.unavailable["physical_cores"]
+
+
+def test_linux_reads_the_two_files_a_host_describes_itself_with() -> None:
+    operating_system, cpu = linux_facts(
+        _reader({OS_RELEASE_PATH: OS_RELEASE, CPUINFO_PATH: CPUINFO})
+    )
+
+    assert operating_system.values["name"] == "Ubuntu 24.04.3 LTS"
+    assert cpu.values["vendor"] == "GenuineIntel"
+    assert str(cpu.values["model"]).startswith("Intel(R) Xeon(R)")
+    assert cpu.values["physical_cores"] == 2
+
+
+def test_a_linux_host_without_the_metadata_files_says_so() -> None:
+    operating_system, cpu = linux_facts(_reader({}))
+
+    assert OS_RELEASE_PATH in operating_system.unavailable["name"]
+    assert CPUINFO_PATH in cpu.unavailable["model"]
+
+
+def test_windows_reads_one_cim_query_for_both_groups() -> None:
+    operating_system, cpu = windows_facts(lambda _: json.dumps(WINDOWS_RECORDS))
+
+    assert operating_system.values["build"] == "20348"
+    assert cpu.values["model"] == "AMD EPYC 7763 64-Core Processor"
+    assert cpu.values["vendor"] == "AuthenticAMD"
+    assert cpu.values["physical_cores"] == 2
+
+
+def test_a_failed_cim_query_leaves_every_field_with_the_same_reason() -> None:
+    def refuse(_: Sequence[str]) -> str:
+        raise ProbeError("powershell.exe exited with status 1: access denied")
+
+    operating_system, cpu = windows_facts(refuse)
+
+    assert "access denied" in operating_system.unavailable["name"]
+    assert "access denied" in cpu.unavailable["model"]
+    # The portable facts still stand; one refused query is not the whole host.
+    assert cpu.values["architecture"]
+
+
+def test_a_cim_query_that_is_not_json_is_not_read_as_data() -> None:
+    operating_system, _ = windows_facts(lambda _: "Get-CimInstance : not recognized")
+
+    assert "no JSON" in operating_system.unavailable["name"]
+
+
+def _completed(
+    returncode: int, stdout: str = "", stderr: str = ""
+) -> Callable[..., subprocess.CompletedProcess[str]]:
+    process = subprocess.CompletedProcess(["python"], returncode, stdout, stderr)
+    return lambda *_, **__: process
+
+
+def test_the_torch_probe_reports_what_the_cpu_supports() -> None:
+    answer = {"version": "2.4.1", "cpu_capability": "AVX2", "mkldnn": True}
+
+    assert probe_torch(runner=_completed(0, json.dumps(answer))) == answer
+
+
+@pytest.mark.parametrize(
+    ("runner", "expected"),
+    [
+        (_completed(1, stderr="Illegal instruction"), "Illegal instruction"),
+        (_completed(0), "no report"),
+    ],
+)
+def test_a_torch_probe_that_fails_costs_a_field_not_the_document(
+    runner: Callable[..., subprocess.CompletedProcess[str]], expected: str
+) -> None:
+    assert expected in str(probe_torch(runner=runner)["unavailable"])
+
+
+def test_a_hanging_torch_probe_is_bounded() -> None:
+    def runner(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
+        raise subprocess.TimeoutExpired(cmd="python", timeout=1)
+
+    assert "did not answer within" in str(probe_torch(runner=runner)["unavailable"])
+
+
+def test_the_torch_probe_runs_in_a_child_that_may_not_survive_it() -> None:
+    """Importing Torch is one of the things that ends a packaging run, so the
+    base fingerprint must already be complete when it is attempted."""
+
+    source = (Path(__file__).parents[1] / "tools" / "native_host_fingerprint.py").read_text(
+        encoding="utf-8"
+    )
+
+    assert "import torch" not in source.replace(TORCH_PROBE, "")
+    assert "-c" in source
+
+
+def test_this_host_reports_the_fields_a_crash_report_needs() -> None:
+    document = collect_fingerprint("test")
+
+    def group(name: str) -> dict[str, object]:
+        return cast("dict[str, object]", document[name])
+
+    assert document["context"] == "test"
+    assert group("os")["system"]
+    assert group("cpu")["architecture"]
+    assert group("cpu")["logical_cores"]
+    # The build interpreter is labelled as such: a frozen bundle reports its
+    # own embedded versions through the self-check, and the two are not one.
+    assert group("build_interpreter")["version"] == ".".join(
+        str(part) for part in sys.version_info[:3]
+    )
+    assert "torch" not in document
+
+
+def test_the_fingerprint_collects_no_environment_or_process_inventory() -> None:
+    """A diagnostic that dumps the environment is a secret leak, and a process
+    inventory describes everything on the machine except the build."""
+
+    assert "environ" not in json.dumps(collect_fingerprint("test"))
+
+    source = (Path(__file__).parents[1] / "tools" / "native_host_fingerprint.py").read_text(
+        encoding="utf-8"
+    )
+    assert "os.environ" not in source
+    assert set(re.findall(r"Win32_\w+", source)) == {"Win32_OperatingSystem", "Win32_Processor"}
diff --git a/tests/test_packaging.py b/tests/test_packaging.py
index b930bc1..c423288 100644
--- a/tests/test_packaging.py
+++ b/tests/test_packaging.py
@@ -2,6 +2,7 @@
 
 from __future__ import annotations
 
+import json
 import signal
 import sys
 from pathlib import Path
@@ -323,7 +324,7 @@ def test_an_ordinary_windows_exit_status_is_not_read_as_a_fault() -> None:
 
     failures = list(_iter_failures({"stages": [], "exit_code": 2, "stderr": ""}))
 
-    assert "exited with status 2" in failures[0]
+    assert failures[0].endswith("exit: status 2")
 
 
 def test_the_frozen_smoke_reports_a_failed_stage_rather_than_the_exit() -> None:
@@ -997,3 +998,267 @@ def test_the_shell_s_bootstrap_carries_neither_heavy_runtime() -> None:
     assert "QtWebEngine" not in application
     assert "preload_ocr_runtime" not in application
     assert "prepare_control_center_qt" not in application
+
+
+# --- progress markers, which are all a killed frozen run leaves behind -------
+
+#: A run that reaches the report. Two stages complete, and the JSON the harness
+#: parses is printed last, exactly as the real check prints it.
+_COMPLETED_PROGRAM = """
+import json
+
+from hanly_app import self_check
+
+stages = []
+self_check._stage(stages, "runtime", lambda: "loaded")
+self_check._stage(stages, "dictionary", lambda: "1 entry")
+report = self_check.SelfCheckReport(mode="worker", stages=tuple(stages), versions={})
+print(json.dumps(report.to_dict(), indent=2), flush=True)
+"""
+
+#: A run killed inside a stage. ``os._exit`` rather than a real fault: the
+#: point is that no report and no completion marker is written, which is what a
+#: native abort looks like from outside, without a crash report to collect.
+_KILLED_PROGRAM = """
+import os
+
+from hanly_app import self_check
+
+stages = []
+self_check._stage(stages, "runtime", lambda: "loaded")
+self_check._stage(stages, "ocr", lambda: os._exit(134))
+"""
+
+#: A run that starts a stage and never leaves it.
+_HANGING_PROGRAM = """
+import time
+
+from hanly_app import self_check
+
+self_check._emit_marker(self_check.STAGE_STARTED, "main window")
+time.sleep(120)
+"""
+
+
+def _self_check_program(directory: Path, program: str) -> Path:
+    """Write a stand-in the harness launches the way it launches a bundle.
+
+    A launcher rather than the program itself, because the harness runs one
+    executable path and Windows does not run a ``.py`` file as one.
+    """
+
+    directory.mkdir(parents=True, exist_ok=True)
+    script = directory / "self_check_program.py"
+    script.write_text(program, encoding="utf-8")
+
+    if sys.platform == "win32":
+        launcher = directory / "hanly-desktop.bat"
+        launcher.write_text(
+            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
+        )
+        return launcher
+
+    launcher = directory / "hanly-desktop"
+    launcher.write_text(
+        f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
+    )
+    launcher.chmod(0o755)
+    return launcher
+
+
+def test_a_completed_run_still_parses_and_keeps_its_stage_timings(
+    tmp_path: Path,
+) -> None:
+    """Markers travel on stderr, so the report on stdout is untouched by them."""
+
+    report = run_packaged_self_check(
+        _self_check_program(tmp_path / "bundle", _COMPLETED_PROGRAM), timeout=60
+    )
+
+    assert report["ok"] is True
+    assert report["exit_code"] == 0
+    stages = cast(list[dict[str, object]], report["stages"])
+    assert [stage["name"] for stage in stages] == ["runtime", "dictionary"]
+    assert all(isinstance(stage["duration_ms"], float) for stage in stages)
+
+    progress = cast(dict[str, object], report["progress"])
+    assert progress["started"] == ["runtime", "dictionary"]
+    assert [stage["stage"] for stage in cast(list[dict], progress["completed"])] == [
+        "runtime",
+        "dictionary",
+    ]
+    # Nothing is still open, so nothing is blamed.
+    assert progress["current_stage"] is None
+
+
+def test_a_killed_run_names_the_stage_it_was_inside(tmp_path: Path) -> None:
+    """The stage that never completed is the only suspect a crash leaves."""
+
+    report = run_packaged_self_check(
+        _self_check_program(tmp_path / "bundle", _KILLED_PROGRAM), timeout=60
+    )
+
+    progress = cast(dict[str, object], report["progress"])
+    assert progress["current_stage"] == "ocr"
+    assert progress["started"] == ["runtime", "ocr"]
+    # The stage that did finish keeps its evidence; the crash is not its fault.
+    assert [stage["stage"] for stage in cast(list[dict], progress["completed"])] == [
+        "runtime"
+    ]
+
+    failure = next(_iter_failures(report))
+    assert "current_stage: ocr" in failure
+    assert "status 134" in failure
+
+
+def test_a_hanging_run_names_its_stage_and_the_deadline(tmp_path: Path) -> None:
+    report = run_packaged_self_check(
+        _self_check_program(tmp_path / "bundle", _HANGING_PROGRAM), timeout=5
+    )
+
+    assert report["exit_timeout"] is True
+    failure = next(_iter_failures(report))
+    assert failure == "current_stage: main window; exit: did not exit before the deadline"
+
+
+def test_a_crash_before_any_marker_stays_explicitly_unknown() -> None:
+    """Naming the last stage that passed would invent a diagnosis."""
+
+    failures = list(
+        _iter_failures(
+            {
+                "ok": False,
+                "stages": [],
+                "progress": {"started": [], "completed": [], "current_stage": None},
+                "exit_code": 0xC000001D,
+                "stderr": "",
+            }
+        )
+    )
+
+    assert failures[0] == "current_stage: unknown; exit: ILLEGAL_INSTRUCTION (0xC000001D)"
+
+
+def test_progress_is_read_before_the_stderr_tail_is_cut() -> None:
+    """A long run's first markers are exactly what a bounded tail would lose."""
+
+    markers = "\n".join(
+        f'{smoke_packaged_runtime.STAGE_MARKER_PREFIX} '
+        f'{{"event": "stage_started", "stage": "runtime"}}'
+        for _ in range(1)
+    )
+    stderr = markers + "\n" + "x" * 8000
+
+    progress = smoke_packaged_runtime.read_progress(stderr)
+
+    assert progress["current_stage"] == "runtime"
+    assert len(stderr[-4000:]) == 4000
+
+
+def test_marker_lines_are_kept_out_of_the_reported_output_tail() -> None:
+    """Twenty lines of progress would push the fault traceback out of view."""
+
+    marker = f'{smoke_packaged_runtime.STAGE_MARKER_PREFIX} {{"event": "x", "stage": "y"}}'
+    stderr = "\n".join([marker] * 40 + ["Fatal Python error: Aborted"])
+
+    tail = smoke_packaged_runtime._output_tail({"stderr": stderr})
+
+    assert tail == "Fatal Python error: Aborted"
+
+
+def test_the_self_check_flushes_a_start_marker_before_the_work_it_names() -> None:
+    """A marker written after the action would never survive the action."""
+
+    source = (
+        ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "self_check.py"
+    ).read_text(encoding="utf-8")
+    body = source.split("def _stage(", 1)[1]
+
+    assert body.index("_emit_marker(STAGE_STARTED") < body.index("value = action()")
+    assert "flush=True" in source
+
+
+def test_closing_the_worker_is_a_stage_of_its_own() -> None:
+    """Releasing native handles can crash; blaming the dictionary for it is a
+    diagnosis that sends the next person to the wrong provider."""
+
+    assert '_stage(stages, "worker close", worker.close)' in (
+        ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "self_check.py"
+    ).read_text(encoding="utf-8")
+
+
+# --- the products a run checks, each independently of the others -------------
+
+
+def test_reconstructing_an_archive_can_stop_before_inspecting_it(
+    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Reconstruction and inspection are separate steps, so a bundle that
+    cannot be inspected still says whether the published ZIP unpacked."""
+
+    archive = tmp_path / "hanly-desktop-macos.zip"
+    archive.write_bytes(b"archive")
+    destination = tmp_path / "out"
+
+    def unpack(source: Path, target: Path) -> Path:
+        application = Path(target) / SMOKE_BUNDLE_NAME
+        application.joinpath("Contents", "MacOS").mkdir(parents=True)
+        application.joinpath("Contents", "MacOS", "hanly-desktop").write_bytes(b"")
+        return application
+
+    monkeypatch.setattr(smoke_packaged_runtime, "reconstruct_application", unpack)
+    status = smoke_packaged_runtime.main(
+        [
+            "--from-archive",
+            str(archive),
+            "--reconstruct-into",
+            str(destination),
+            "--reconstruct-only",
+        ]
+    )
+
+    assert status == 0
+    report = json.loads(capsys.readouterr().out)
+    assert report["reconstructed"]["archive"] == archive.name
+    assert "inventory" not in report
+
+
+def test_a_disk_image_is_checked_without_an_application_to_smoke(
+    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """A ZIP that will not reconstruct says nothing about the disk image."""
+
+    image = tmp_path / "hanly-desktop-macos.dmg"
+    image.write_bytes(b"image")
+    monkeypatch.setattr(
+        smoke_packaged_runtime,
+        "verify_disk_image",
+        lambda path: {"image": Path(path).name, "application": SMOKE_BUNDLE_NAME, "ok": True},
+    )
+
+    assert smoke_packaged_runtime.main(["--disk-image", str(image)]) == 0
+    assert json.loads(capsys.readouterr().out)["disk_image"]["ok"] is True
+
+
+def test_a_disk_image_without_the_application_fails_the_step(
+    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Mounting is not the check: a DMG a person opens onto nothing is broken."""
+
+    image = tmp_path / "hanly-desktop-macos.dmg"
+    image.write_bytes(b"image")
+    monkeypatch.setattr(
+        smoke_packaged_runtime,
+        "verify_disk_image",
+        lambda path: {"image": Path(path).name, "application": SMOKE_BUNDLE_NAME, "ok": False},
+    )
+
+    assert smoke_packaged_runtime.main(["--disk-image", str(image)]) == 1
+    assert "does not contain" in capsys.readouterr().err
+
+
+def test_an_invocation_that_names_no_product_is_refused(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    assert smoke_packaged_runtime.main([]) == 2
+    assert "name an application directory" in capsys.readouterr().err
diff --git a/tools/native_host_fingerprint.py b/tools/native_host_fingerprint.py
new file mode 100644
index 0000000..fbebf14
--- /dev/null
+++ b/tools/native_host_fingerprint.py
@@ -0,0 +1,429 @@
+"""Record what a packaging host actually is, before a build can lose it.
+
+A frozen build that dies on an illegal instruction is a native library meeting
+a CPU that does not implement what it was compiled to use, and the exit status
+alone names no suspect. This writes the host's identity as one small JSON
+document early in a run, so a later crash still has a machine to describe.
+
+The probes are deliberately narrow: operating system, CPU, core counts, the
+build interpreter, and -- in a subprocess of its own -- what Torch believes the
+CPU supports. Environment variables and machine-wide process inventories are
+never collected. A value the host will not give up is reported as unavailable
+with the reason, never as a plausible default.
+"""
+
+from __future__ import annotations
+
+import argparse
+import json
+import os
+import platform
+import subprocess
+import sys
+from collections.abc import Callable, Sequence
+from dataclasses import dataclass, field
+from datetime import datetime, timezone
+from pathlib import Path
+
+#: The OS metadata files and tools each platform answers with.
+OS_RELEASE_PATH = "/etc/os-release"
+CPUINFO_PATH = "/proc/cpuinfo"
+SW_VERS = "/usr/bin/sw_vers"
+SYSCTL = "/usr/sbin/sysctl"
+POWERSHELL = "powershell.exe"
+
+#: One CIM query for both facts Windows owns. Two invocations would pay
+#: PowerShell's startup cost twice for the same answer.
+WINDOWS_QUERY = (
+    "$os = Get-CimInstance Win32_OperatingSystem | "
+    "Select-Object Caption,Version,BuildNumber,OSArchitecture;"
+    "$cpu = @(Get-CimInstance Win32_Processor | "
+    "Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors)[0];"
+    "ConvertTo-Json -Compress -InputObject @{ os = $os; cpu = $cpu }"
+)
+
+#: What the Torch probe answers with. Every field is guarded on its own: a
+#: build where one accessor is missing still reports the version.
+TORCH_PROBE = """
+import json
+
+report = {}
+try:
+    import torch
+except BaseException as error:
+    report["unavailable"] = "%s: %s" % (type(error).__name__, error)
+else:
+    report["version"] = getattr(torch, "__version__", None)
+    for name, accessor in (
+        ("cpu_capability", lambda: torch.backends.cpu.get_cpu_capability()),
+        ("mkldnn", lambda: torch.backends.mkldnn.is_available()),
+        ("threads", lambda: torch.get_num_threads()),
+    ):
+        try:
+            report[name] = accessor()
+        except BaseException as error:
+            report[name] = None
+print(json.dumps(report))
+"""
+
+#: Torch imports a large native stack that can abort rather than raise, which
+#: is the very failure this fingerprint exists to describe. It is bounded so a
+#: hung or crashed import costs the run a field, not the document.
+TORCH_TIMEOUT_SECONDS = 120.0
+
+#: How long any single OS probe may take. These are local queries; a probe
+#: that does not answer in this is not going to.
+PROBE_TIMEOUT_SECONDS = 30.0
+
+TextRunner = Callable[[Sequence[str]], str]
+TextReader = Callable[[str], str]
+CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
+
+
+class ProbeError(RuntimeError):
+    """Raised when a host will not answer for one optional fact."""
+
+
+@dataclass
+class Facts:
+    """Values one probe group produced, and the reason for each it could not."""
+
+    values: dict[str, object] = field(default_factory=dict)
+    unavailable: dict[str, str] = field(default_factory=dict)
+
+    def record(self, name: str, probe: Callable[[], object]) -> None:
+        """Store what the probe answered, or why it could not answer."""
+
+        try:
+            self.values[name] = probe()
+        except ProbeError as error:
+            self.values[name] = None
+            self.unavailable[name] = str(error)
+
+    def to_dict(self) -> dict[str, object]:
+        return {**self.values, "unavailable": dict(self.unavailable)}
+
+
+def collect_fingerprint(
+    context: str,
+    *,
+    platform_name: str = sys.platform,
+    run: TextRunner | None = None,
+    read: TextReader | None = None,
+    torch: dict[str, object] | None = None,
+) -> dict[str, object]:
+    """Describe the host, naming the moment in the run it was described at."""
+
+    operating_system, cpu = _host_facts(
+        platform_name,
+        _run_text if run is None else run,
+        _read_text if read is None else read,
+    )
+    document: dict[str, object] = {
+        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
+        "context": context,
+        "os": operating_system.to_dict(),
+        "cpu": cpu.to_dict(),
+        "build_interpreter": _build_interpreter(),
+    }
+    if torch is not None:
+        document["torch"] = torch
+    return document
+
+
+def probe_torch(
+    *,
+    interpreter: str | Path | None = None,
+    timeout: float = TORCH_TIMEOUT_SECONDS,
+    runner: CommandRunner = subprocess.run,
+) -> dict[str, object]:
+    """Ask Torch what the CPU supports, from a process that may not survive it.
+
+    Torch is imported in a child precisely because importing it is one of the
+    things that kills a packaging run, and a base fingerprint that dies with it
+    is worth nothing.
+    """
+
+    command = [str(interpreter or sys.executable), "-c", TORCH_PROBE]
+    try:
+        completed = runner(
+            command, capture_output=True, text=True, timeout=timeout, check=False
+        )
+    except subprocess.TimeoutExpired:
+        return {"unavailable": f"the Torch probe did not answer within {timeout:g}s"}
+    except OSError as error:
+        return {"unavailable": f"could not start the Torch probe: {error}"}
+
+    if completed.returncode != 0:
+        detail = (completed.stderr or "").strip().splitlines()
+        return {
+            "unavailable": (
+                f"the Torch probe exited with status {completed.returncode}: "
+                + (detail[-1] if detail else "no output")
+            )
+        }
+    try:
+        report = json.loads(completed.stdout)
+    except json.JSONDecodeError:
+        return {"unavailable": "the Torch probe printed no report"}
+    return report if isinstance(report, dict) else {"unavailable": "unexpected Torch report"}
+
+
+def _host_facts(
+    platform_name: str, run: TextRunner, read: TextReader
+) -> tuple[Facts, Facts]:
+    """Route to the probes the host in question actually answers."""
+
+    if platform_name == "darwin":
+        return darwin_facts(run)
+    if platform_name.startswith("linux"):
+        return linux_facts(read)
+    if platform_name == "win32":
+        return windows_facts(run)
+    return _portable_os(), _portable_cpu()
+
+
+def darwin_facts(run: TextRunner) -> tuple[Facts, Facts]:
+    """Read macOS's own answers for the product build and the CPU brand."""
+
+    operating_system = _portable_os()
+    operating_system.record("name", lambda: run([SW_VERS, "-productName"]))
+    operating_system.record("product_version", lambda: run([SW_VERS, "-productVersion"]))
+    operating_system.record("build", lambda: run([SW_VERS, "-buildVersion"]))
+
+    cpu = _portable_cpu()
+    cpu.record("model", lambda: run([SYSCTL, "-n", "machdep.cpu.brand_string"]))
+    cpu.record("vendor", lambda: run([SYSCTL, "-n", "machdep.cpu.vendor"]))
+    cpu.record("physical_cores", lambda: _as_count(run([SYSCTL, "-n", "hw.physicalcpu"])))
+    return operating_system, cpu
+
+
+def linux_facts(read: TextReader) -> tuple[Facts, Facts]:
+    """Read the two files a Linux host describes itself with."""
+
+    operating_system = _portable_os()
+    operating_system.record("name", lambda: _os_release_field(read, "PRETTY_NAME"))
+
+    cpu = _portable_cpu()
+    cpu.record("model", lambda: _cpuinfo_field(read, "model name"))
+    cpu.record("vendor", lambda: _cpuinfo_field(read, "vendor_id"))
+    cpu.record("physical_cores", lambda: _as_count(_cpuinfo_field(read, "cpu cores")))
+    return operating_system, cpu
+
+
+def windows_facts(run: TextRunner) -> tuple[Facts, Facts]:
+    """Read one CIM query covering both the operating system and the CPU."""
+
+    try:
+        records = _windows_records(run)
+    except ProbeError as error:
+        records = None
+        reason = str(error)
+
+    def field_of(group: str, name: str) -> Callable[[], object]:
+        def probe() -> object:
+            if records is None:
+                raise ProbeError(reason)
+            value = records.get(group, {}).get(name)
+            if value in (None, ""):
+                raise ProbeError(f"the CIM query returned no {group} {name}")
+            return value
+
+        return probe
+
+    operating_system = _portable_os()
+    operating_system.record("name", field_of("os", "Caption"))
+    operating_system.record("product_version", field_of("os", "Version"))
+    operating_system.record("build", field_of("os", "BuildNumber"))
+
+    cpu = _portable_cpu()
+    cpu.record("model", field_of("cpu", "Name"))
+    cpu.record("vendor", field_of("cpu", "Manufacturer"))
+    cpu.record("physical_cores", field_of("cpu", "NumberOfCores"))
+    return operating_system, cpu
+
+
+def _windows_records(run: TextRunner) -> dict[str, dict[str, object]]:
+    """Parse the one JSON document the CIM query prints."""
+
+    payload = run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_QUERY])
+    try:
+        parsed = json.loads(payload)
+    except json.JSONDecodeError as error:
+        raise ProbeError(f"the CIM query printed no JSON: {error}") from error
+    if not isinstance(parsed, dict):
+        raise ProbeError("the CIM query printed an unexpected document")
+    records: dict[str, dict[str, object]] = {}
+    for group in ("os", "cpu"):
+        found = parsed.get(group)
+        records[group] = found if isinstance(found, dict) else {}
+    return records
+
+
+def _portable_os() -> Facts:
+    """What every host reports without being asked anything platform-specific."""
+
+    return Facts(
+        values={
+            "system": platform.system(),
+            "release": platform.release(),
+            "version": platform.version(),
+            "platform": platform.platform(),
+        }
+    )
+
+
+def _portable_cpu() -> Facts:
+    """Architecture and logical cores, which the standard library always knows."""
+
+    facts = Facts(values={"architecture": platform.machine()})
+    facts.record("logical_cores", _logical_cores)
+    return facts
+
+
+def _logical_cores() -> int:
+    count = os.cpu_count()
+    if count is None:
+        raise ProbeError("os.cpu_count() reported no answer")
+    return count
+
+
+def _build_interpreter() -> dict[str, object]:
+    """Describe the interpreter that runs the build, never the frozen one.
+
+    A frozen bundle reports its own embedded versions through the self-check;
+    conflating the two is how a report ends up describing the wrong Python.
+    """
+
+    return {
+        "version": platform.python_version(),
+        "implementation": platform.python_implementation(),
+        "executable": sys.executable,
+    }
+
+
+def _os_release_field(read: TextReader, key: str) -> str:
+    for line in _lines(read, OS_RELEASE_PATH):
+        name, separator, value = line.partition("=")
+        if separator and name.strip() == key:
+            return value.strip().strip('"')
+    raise ProbeError(f"{OS_RELEASE_PATH} carries no {key}")
+
+
+def _cpuinfo_field(read: TextReader, key: str) -> str:
+    for line in _lines(read, CPUINFO_PATH):
+        name, separator, value = line.partition(":")
+        if separator and name.strip() == key:
+            return value.strip()
+    raise ProbeError(f"{CPUINFO_PATH} carries no {key}")
+
+
+def _lines(read: TextReader, path: str) -> list[str]:
+    try:
+        return read(path).splitlines()
+    except OSError as error:
+        raise ProbeError(f"could not read {path}: {error}") from error
+
+
+def _as_count(value: object) -> int:
+    try:
+        return int(str(value).strip())
+    except ValueError as error:
+        raise ProbeError(f"{value!r} is not a core count") from error
+
+
+def _run_text(command: Sequence[str]) -> str:
+    """Run one bounded local probe and return what it said, or why it did not."""
+
+    try:
+        completed = subprocess.run(
+            list(command),
+            capture_output=True,
+            text=True,
+            timeout=PROBE_TIMEOUT_SECONDS,
+            check=False,
+        )
+    except subprocess.TimeoutExpired as error:
+        raise ProbeError(f"{command[0]} did not answer in time") from error
+    except OSError as error:
+        raise ProbeError(f"could not run {command[0]}: {error}") from error
+
+    if completed.returncode != 0:
+        detail = (completed.stderr or "").strip().splitlines()
+        raise ProbeError(
+            f"{command[0]} exited with status {completed.returncode}: "
+            + (detail[-1] if detail else "no output")
+        )
+    answer = completed.stdout.strip()
+    if not answer:
+        raise ProbeError(f"{command[0]} answered with nothing")
+    return answer
+
+
+def _read_text(path: str) -> str:
+    return Path(path).read_text(encoding="utf-8", errors="replace")
+
+
+def _build_parser() -> argparse.ArgumentParser:
+    parser = argparse.ArgumentParser(
+        description="Describe the host a packaging run is happening on"
+    )
+    parser.add_argument(
+        "--context",
+        default="unspecified",
+        help="what point of the run this fingerprint was taken at",
+    )
+    parser.add_argument(
+        "--output",
+        type=Path,
+        help="also write the document here, for a run that retains diagnostics",
+    )
+    parser.add_argument(
+        "--with-torch",
+        action="store_true",
+        help="add what Torch reports about the CPU, from a subprocess of its own",
+    )
+    parser.add_argument(
+        "--torch-timeout",
+        type=float,
+        default=TORCH_TIMEOUT_SECONDS,
+        help="seconds to allow the Torch probe",
+    )
+    return parser
+
+
+def main(argv: Sequence[str] | None = None) -> int:
+    """Print the fingerprint, and write it beside the run's other evidence."""
+
+    args = _build_parser().parse_args(None if argv is None else list(argv))
+    torch = probe_torch(timeout=args.torch_timeout) if args.with_torch else None
+    document = collect_fingerprint(args.context, torch=torch)
+
+    rendered = json.dumps(document, indent=2, sort_keys=True)
+    if args.output is not None:
+        args.output.parent.mkdir(parents=True, exist_ok=True)
+        args.output.write_text(rendered + "\n", encoding="utf-8")
+    print(rendered)
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
+
+
+__all__ = [
+    "CPUINFO_PATH",
+    "OS_RELEASE_PATH",
+    "PROBE_TIMEOUT_SECONDS",
+    "TORCH_PROBE",
+    "TORCH_TIMEOUT_SECONDS",
+    "WINDOWS_QUERY",
+    "Facts",
+    "ProbeError",
+    "collect_fingerprint",
+    "darwin_facts",
+    "linux_facts",
+    "main",
+    "probe_torch",
+    "windows_facts",
+]
diff --git a/tools/smoke_packaged_runtime.py b/tools/smoke_packaged_runtime.py
index 6a90e70..0045968 100644
--- a/tools/smoke_packaged_runtime.py
+++ b/tools/smoke_packaged_runtime.py
@@ -137,6 +137,14 @@ WINDOWS_FATAL_STATUS = {
 #: and must not depend on the source package it is checking.
 LOCAL_KRDICT_VARIABLE = "HANLY_KRDICT_DB"
 
+#: The self-check writes one flushed JSON line per stage boundary on stderr.
+#: Named here for the same reason as the variable above. A process killed by a
+#: native fault prints no report, and these lines are the only account of how
+#: far it got.
+STAGE_MARKER_PREFIX = "hanly-self-check:"
+STAGE_STARTED = "stage_started"
+STAGE_COMPLETED = "stage_completed"
+
 
 @dataclass(frozen=True, slots=True)
 class BundleInventory:
@@ -251,10 +259,72 @@ def run_packaged_self_check(
     report = _parse_report(stdout)
     report["exit_code"] = status
     report["exit_timeout"] = timed_out
+    # Progress is read from the whole stream, before the tail is cut: the
+    # markers a long-running check wrote first are exactly the ones a 4000
+    # character tail would drop.
+    report["progress"] = read_progress(stderr)
     report["stderr"] = stderr[-4000:]
     return report
 
 
+def read_progress(stderr: str) -> dict[str, object]:
+    """Reconstruct how far the self-check got from the markers it flushed.
+
+    The current stage is the most recent one started and not completed, which
+    is the innermost of any nested probes. A run that printed no marker at all
+    leaves it unknown rather than guessing at the last stage that passed.
+    """
+
+    started: list[str] = []
+    completed: list[dict[str, object]] = []
+    open_stages: list[str] = []
+    for event in _iter_markers(stderr):
+        name = event.get("stage")
+        if not isinstance(name, str):
+            continue
+        if event.get("event") == STAGE_STARTED:
+            started.append(name)
+            open_stages.append(name)
+        elif event.get("event") == STAGE_COMPLETED:
+            completed.append({key: value for key, value in event.items() if key != "event"})
+            if name in open_stages:
+                open_stages.remove(name)
+
+    return {
+        "started": started,
+        "completed": completed,
+        "current_stage": open_stages[-1] if open_stages else None,
+    }
+
+
+def _iter_markers(stderr: str) -> Iterator[dict[str, Any]]:
+    """Read the marker lines, ignoring whatever native noise sits around them."""
+
+    for line in stderr.splitlines():
+        payload = _marker_payload(line)
+        if payload is None:
+            continue
+        try:
+            event = json.loads(payload)
+        except json.JSONDecodeError:
+            continue
+        if isinstance(event, dict):
+            yield event
+
+
+def _marker_payload(line: str) -> str | None:
+    """Return the JSON a marker line carries, wherever the line starts.
+
+    A native library can write a partial line without a newline, so a marker
+    is located inside the line rather than required to begin it.
+    """
+
+    start = line.find(STAGE_MARKER_PREFIX)
+    if start < 0:
+        return None
+    return line[start + len(STAGE_MARKER_PREFIX) :].strip()
+
+
 def _collection_roots(root: Path) -> tuple[Path, ...]:
     return tuple(root.joinpath(*parts) for parts in _COLLECTION_ROOTS)
 
@@ -546,19 +616,39 @@ def _iter_failures(report: Mapping[str, object]) -> Iterator[str]:
 
 
 def _describe_exit(report: Mapping[str, object]) -> str:
-    """Describe how the process ended, naming a signal rather than a number."""
+    """Say which stage was running and how the process ended, in that order.
+
+    "exited with status 3221225501" names no suspect. The stage the markers
+    left open does, and the two together are the whole diagnosis a crashed
+    packaging run can offer.
+    """
+
+    return f"current_stage: {_current_stage(report)}; exit: {_exit_summary(report)}"
+
+
+def _current_stage(report: Mapping[str, object]) -> str:
+    progress = report.get("progress")
+    if isinstance(progress, Mapping):
+        stage = progress.get("current_stage")
+        if isinstance(stage, str) and stage:
+            return stage
+    return "unknown"
+
+
+def _exit_summary(report: Mapping[str, object]) -> str:
+    """Name how the process ended, as a signal or fault rather than a number."""
 
     if report.get("exit_timeout"):
-        return "the self-check did not exit before the deadline"
+        return "did not exit before the deadline"
 
     status = report.get("exit_code")
     if isinstance(status, int) and status < 0:
-        return f"the self-check was killed by {_signal_name(-status)} before reporting a stage"
+        return _signal_name(-status)
     if isinstance(status, int):
         fatal = _windows_fault(status)
         if fatal is not None:
-            return f"the self-check died on {fatal} before reporting a stage"
-    return f"the self-check reported no stage and exited with status {status}"
+            return fatal
+    return f"status {status}"
 
 
 def _signal_name(number: int) -> str:
@@ -593,7 +683,13 @@ def _output_tail(report: Mapping[str, object]) -> str | None:
         text = report.get(key)
         if not isinstance(text, str):
             continue
-        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
+        # Progress markers are reported on their own; leaving them here would
+        # push the fault handler's traceback out of a bounded tail.
+        lines = [
+            line.rstrip()
+            for line in text.splitlines()
+            if line.strip() and _marker_payload(line) is None
+        ]
         if lines:
             return "\n".join(lines[-OUTPUT_TAIL_LINES:])
     return None
@@ -676,44 +772,84 @@ def _build_parser() -> argparse.ArgumentParser:
         action="store_true",
         help="check collected dependencies without running the executable",
     )
+    parser.add_argument(
+        "--reconstruct-only",
+        action="store_true",
+        help=(
+            "unpack --from-archive and report where the application landed, "
+            "without inspecting it; the checks that follow are separate steps "
+            "so one of them failing cannot suppress the others"
+        ),
+    )
     return parser
 
 
 def main(argv: Sequence[str] | None = None) -> int:
-    """Report the bundle's inventory and, unless skipped, its self-check."""
+    """Check whichever published products this invocation was given."""
 
     args = _build_parser().parse_args(None if argv is None else list(argv))
-    if (args.application_directory is None) == (args.from_archive is None):
-        print(
-            "Hanly smoke: name either an application directory or --from-archive",
-            file=sys.stderr,
-        )
+    problem = _argument_problem(args)
+    if problem is not None:
+        print(f"Hanly smoke: {problem}", file=sys.stderr)
         return 2
 
     output: dict[str, object] = {}
     reconstruction: tempfile.TemporaryDirectory[str] | None = None
     try:
+        if args.disk_image is not None:
+            output["disk_image"] = verify_disk_image(args.disk_image)
+
         application = args.application_directory
         if args.from_archive is not None:
-            if args.reconstruct_into is None:
+            destination = args.reconstruct_into
+            if destination is None:
                 reconstruction = tempfile.TemporaryDirectory(prefix="hanly-reconstruct-")
                 destination = Path(reconstruction.name) / "app"
-            else:
-                destination = args.reconstruct_into
             application = reconstruct_application(args.from_archive, destination)
             output["reconstructed"] = {
                 "archive": Path(args.from_archive).name,
                 "application": str(application),
             }
-        if args.disk_image is not None:
-            output["disk_image"] = verify_disk_image(args.disk_image)
 
-        return _report(args, application, output)
+        if application is None or args.reconstruct_only:
+            print(json.dumps(output, indent=2))
+            return _unusable_disk_image(output)
+        return max(_report(args, application, output), _unusable_disk_image(output))
     finally:
         if reconstruction is not None:
             reconstruction.cleanup()
 
 
+def _argument_problem(args: argparse.Namespace) -> str | None:
+    """Reject an invocation that names no subject, or two of them."""
+
+    if args.application_directory is not None and args.from_archive is not None:
+        return "name either an application directory or --from-archive, not both"
+    subjects = (args.application_directory, args.from_archive, args.disk_image)
+    if all(subject is None for subject in subjects):
+        return "name an application directory, --from-archive, or --disk-image"
+    if args.reconstruct_only and args.from_archive is None:
+        return "--reconstruct-only needs --from-archive"
+    return None
+
+
+def _unusable_disk_image(output: Mapping[str, object]) -> int:
+    """Fail on a disk image that mounted without the application inside it.
+
+    Mounting is not the check. A DMG that opens onto the wrong contents is
+    exactly the published product a person would download and find empty.
+    """
+
+    report = output.get("disk_image")
+    if isinstance(report, Mapping) and report.get("ok") is not True:
+        print(
+            f"Hanly smoke: {report.get('image')} does not contain {report.get('application')}",
+            file=sys.stderr,
+        )
+        return 1
+    return 0
+
+
 def _report(
     args: argparse.Namespace,
     application: Path,
@@ -798,12 +934,16 @@ __all__ = [
     "REQUIRED_EXTENSION_STEM",
     "REQUIRED_MODEL_FILES",
     "REQUIRED_PACKAGES",
+    "STAGE_COMPLETED",
+    "STAGE_MARKER_PREFIX",
+    "STAGE_STARTED",
     "UI_TIMEOUT_SECONDS",
     "WINDOWS_FATAL_STATUS",
     "BundleInventory",
     "inspect_bundle",
     "isolated_environment",
     "main",
+    "read_progress",
     "reconstruct_application",
     "run_packaged_self_check",
     "verify_disk_image",
`````

### 8.2 `17c841a` — chore: separate portable native and packaged test suites

`````diff
diff --git a/.github/workflows/build.yml b/.github/workflows/build.yml
index 0751dcd..54f8b7c 100644
--- a/.github/workflows/build.yml
+++ b/.github/workflows/build.yml
@@ -110,15 +110,6 @@ jobs:
           python -m pip install "pyinstaller>=6,<7" pyinstaller-hooks-contrib
           -c packaging/release-constraints.txt
 
-      - name: Run tests
-        run: python -m pytest
-
-      - name: Run lint
-        run: python -m ruff check packages packaging tests tools benchmarks
-
-      - name: Run type checks
-        run: python -m mypy packages packaging tests tools benchmarks
-
       - name: Prepare the bundled EasyOCR weights
         run: python tools/prepare_easyocr_models.py
 
@@ -226,6 +217,22 @@ jobs:
           tail -c 200000 "$report.err" >&2
           exit "$status"
 
+      # The gate as a test, against the bundle this job just froze. Nothing
+      # here may skip: the artifact it needs is the thing being produced.
+      - name: Run the packaged tests
+        id: packaged_tests
+        if: >-
+          ${{ !cancelled() && steps.resolve.outcome == 'success'
+          && steps.dictionary.outcome == 'success' }}
+        shell: bash
+        env:
+          HANLY_REQUIRE_PACKAGED: "1"
+          HANLY_PACKAGED_APP: ${{ env.SMOKE_APP }}
+        run: |
+          display=""
+          if [ "${{ matrix.platform }}" = "linux" ]; then display="xvfb-run -a"; fi
+          $display python -m pytest --suite packaged
+
       - name: Verify the release archive exists
         id: archives
         if: ${{ !cancelled() && steps.build.outcome == 'success' }}
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index fa74f12..9aba481 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,5 +1,10 @@
 name: CI
 
+# Two owners, deliberately separated. `quality` proves the portable contracts
+# across every supported Python on a machine with none of the desktop runtime;
+# the `native` jobs prove the real Qt, child-process, and OS-adapter behavior
+# on the three platforms that can actually run it. `build.yml` owns the frozen
+# product and no longer repeats either of these.
 on:
   push:
   pull_request:
@@ -31,16 +36,32 @@ jobs:
         run: |
           python -m pip install --editable packages/hanly
           python -m pip install --editable packages/hanly-app
-      - name: Run tests
-        run: python -m pytest
+      # Without the runtime extra, so a portable test that quietly needs Qt or
+      # the OCR stack fails here instead of passing on a developer's machine.
+      - name: Run the portable tests
+        run: python -m pytest --suite portable
       - name: Run lint
         run: python -m ruff check packages packaging tests tools benchmarks
       - name: Run type checks
         run: python -m mypy packages packaging tests tools benchmarks
-        
-  windows-tests:
-    name: windows tests (py3.10)
-    runs-on: windows-latest
+
+  native:
+    name: native (${{ matrix.platform }})
+    runs-on: ${{ matrix.runner }}
+    strategy:
+      fail-fast: false
+      matrix:
+        include:
+          - platform: windows
+            runner: windows-latest
+          - platform: macos
+            runner: macos-latest
+          - platform: linux
+            runner: ubuntu-latest
+    env:
+      # Every capability these cases need is installed below, so a missing one
+      # is a defect in this job rather than a reason to pass without running.
+      HANLY_REQUIRE_NATIVE: "1"
     steps:
       - uses: actions/checkout@v7
       - uses: actions/setup-python@v7
@@ -49,13 +70,48 @@ jobs:
       - uses: actions/setup-node@v7
         with:
           node-version: "22"
+
+      # The same libraries Qt's xcb plugin is linked against, plus the display
+      # the real windows open in. A hosted Linux runner has neither.
+      - name: Install Linux desktop dependencies
+        if: matrix.platform == 'linux'
+        run: |
+          packages=(
+            libegl1 libgl1 libfontconfig1 libx11-xcb1
+            libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
+            libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-shm0
+            libxcb-sync1 libxcb-util1 libxcb-xfixes0 libxcb-xkb1
+            libxkbcommon-x11-0 xvfb
+          )
+          sudo apt-get update
+          sudo apt-get install --yes --no-install-recommends "${packages[@]}"
+
       - name: Install development dependencies
         run: |
           python -m pip install --upgrade pip
           python -m pip install --group dev
-      - name: Install packages
+
+      - name: Install CPU-only OCR runtime on Linux
+        if: matrix.platform == 'linux'
+        run: python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
+
+      - name: Install packages with the desktop runtime
         run: |
           python -m pip install --editable packages/hanly
-          python -m pip install --editable packages/hanly-app
-      - name: Run tests
-        run: python -m pytest
+          python -m pip install --editable "packages/hanly-app[runtime]"
+
+      # The real lookup child reads both. Neither is in the repository: the
+      # weights are fetched and verified, and the dictionary is built here so
+      # the run never reaches the public release channel for one.
+      - name: Prepare the EasyOCR weights
+        run: python tools/prepare_easyocr_models.py
+
+      - name: Build the dictionary the native lookup reads
+        run: python tools/build_smoke_krdict.py data/generated/krdict.sqlite3
+
+      - name: Run the native tests
+        shell: bash
+        run: |
+          display=""
+          if [ "${{ matrix.platform }}" = "linux" ]; then display="xvfb-run -a"; fi
+          $display python -m pytest --suite native
diff --git a/CLAUDE.md b/CLAUDE.md
index 23ce2d8..59c5518 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -44,6 +44,14 @@ python -m ruff check packages packaging tests tools benchmarks
 python -m mypy packages packaging tests tools benchmarks
 ```
 
+`python -m pytest` remains the full local gate. The suite is also selectable by
+the machine a case needs: `--suite portable` (no Qt, no Torch, no display),
+`--suite native` (`tests/native/`, the real desktop runtime and a window
+server), `--suite packaged` (`tests/packaged/`, a frozen bundle). Selection
+excludes a suite before its modules import, so a portable run never loads Qt and
+one platform's adapters are never imported on another. `packaging/README.md`
+carries the details.
+
 Run the desktop the way a user does:
 
 ```bash
diff --git a/conftest.py b/conftest.py
new file mode 100644
index 0000000..f30f6e5
--- /dev/null
+++ b/conftest.py
@@ -0,0 +1,56 @@
+"""Which of the three suites a run collects, decided before anything imports.
+
+Portable tests are the engine, the contracts, the tooling, and every platform
+decision exercised through a double: they run on any host, with none of the
+desktop runtime installed. The native suites run the real thing -- Qt, Qt
+WebEngine, pywebview, spawned children, the OS adapters -- and the packaged
+suite runs the frozen product. Each needs a different machine, so each is
+selectable on its own.
+"""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+
+_TESTS = Path(__file__).parent / "tests"
+
+#: The directory each non-portable suite owns. Everything else is portable.
+SUITE_ROOTS = {"native": _TESTS / "native", "packaged": _TESTS / "packaged"}
+
+SUITES = ("all", "portable", *SUITE_ROOTS)
+
+
+def pytest_addoption(parser: pytest.Parser) -> None:
+    parser.addoption(
+        "--suite",
+        choices=SUITES,
+        default="all",
+        help="collect one suite instead of every one (default: all)",
+    )
+
+
+def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
+    """Drop the suites this run did not ask for, before they are imported.
+
+    A marker cannot do this. Deselection by marker happens after the module has
+    been imported, and a native module imports Qt, pywebview, or the OCR
+    runtime at module scope -- which is the very thing a portable run is meant
+    to prove it does without.
+    """
+
+    suite = str(config.getoption("--suite"))
+    if suite == "all":
+        return None
+    # A directory on the way to a suite root still has to be descended into.
+    if any(collection_path in root.parents for root in SUITE_ROOTS.values()):
+        return None
+    return _suite_of(collection_path) != suite
+
+
+def _suite_of(path: Path) -> str:
+    for name, root in SUITE_ROOTS.items():
+        if path == root or root in path.parents:
+            return name
+    return "portable"
diff --git a/docs/CODE-MAP.md b/docs/CODE-MAP.md
index a353ec7..0ba2e5f 100644
--- a/docs/CODE-MAP.md
+++ b/docs/CODE-MAP.md
@@ -366,7 +366,7 @@ macOS keeps `ditto`, which is the only thing that reproduces an `.app` intact.
 | `benchmarks/dev/` | Developer-only measurement harness — code, its own `tests/`, and the unwired hover `hud/`. Nothing in `packages/` imports it |
 | `data/` | Local KRDICT source and build outputs. Gitignored except the README |
 | `resources/dev/` | Machine-local benchmark configuration. Gitignored |
-| `tests/` | Product tests for both packages |
+| `tests/` | Product tests for both packages, in three selectable suites: portable by default, `tests/native/` for real Qt and OS adapters, `tests/packaged/` for the frozen product |
 
 ---
 
@@ -420,3 +420,7 @@ python -m pytest
 python -m ruff check packages packaging tests tools benchmarks
 python -m mypy packages packaging tests tools benchmarks
 ```
+
+`python -m pytest` is the full local gate. CI splits it by the machine each
+suite needs — `--suite portable`, `--suite native`, `--suite packaged` — and
+`packaging/README.md` says what each one requires.
diff --git a/docs/execution/checkpoints/han-43-44-superqa.md b/docs/execution/checkpoints/han-43-44-superqa.md
index 6af4f0a..5987260 100644
--- a/docs/execution/checkpoints/han-43-44-superqa.md
+++ b/docs/execution/checkpoints/han-43-44-superqa.md
@@ -15,12 +15,34 @@
 | Patch | State | Main changes | Check and result | Commit |
 | --- | --- | --- | --- | --- |
 | HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and standalone `--disk-image` in the smoke harness. | `pytest tests/test_packaging.py tests/test_ci_workflows.py tests/test_host_fingerprint.py` 153 passed; full `pytest` 1275 passed / 3 skipped; ruff + mypy clean. | |
-| HAN-43 | Pending | | | |
+| HAN-43 | Implemented | Native and packaged cases routed into `tests/native/{shared,macos,windows}` and `tests/packaged/shared`; `--suite portable\|native\|packaged` selection that excludes a suite before its modules import; `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn capability skips into failures in the jobs that own them; `ci.yml` gains three source-native jobs and `build.yml` gives up the duplicated portable suite, lint, and types. | Collected node IDs compared before/after: every case has an owner (`--suite` totals 1286 + 1 skipped, and the two Windows-only cases are now OS-routed rather than collected-and-skipped on macOS). `pytest --suite native` 35 passed on this host; full `pytest` 1286 passed / 1 skipped; ruff + mypy clean. | |
 | Super QA | Pending | | | |
 
+## HAN-43 routing inventory
+
+| File | Disposition |
+| --- | --- |
+| `tests/integration/test_packaged_desktop.py` | → `tests/packaged/shared/`; stale-bundle and missing-bundle skips now fail under `HANLY_REQUIRE_PACKAGED` |
+| `tests/integration/test_control_center_layout.py` | → `tests/native/shared/`; capability check no longer imports Qt in the parent |
+| `tests/integration/test_control_center_lifecycle.py` | → `tests/native/shared/`; the macOS identity case → `tests/native/macos/test_control_center_identity.py`. The POSIX-signal case stays shared: POSIX is not one OS |
+| `tests/integration/test_desktop_startup.py` | → `tests/native/shared/` |
+| `tests/integration/test_lookup_process_spawn.py` | → `tests/native/shared/` |
+| `tests/integration/test_webengine_startup.py` | → `tests/native/shared/`; the Windows abort case → `tests/native/windows/test_webengine_arguments.py`; the child program → `tests/hanly_fixtures/webengine_probe.py` |
+| `tests/test_qt_popup_window.py` | → `tests/native/shared/` (real Qt widgets); the Cocoa panel case → `tests/native/macos/test_popup_panel.py`; the zero-pointer guard is a pure platform decision and moved to `tests/test_popup.py` |
+| `tests/test_hover_exit_qt.py`, `tests/test_qt_hover_scheduler.py` | → `tests/native/shared/`: both build a real `QApplication` and run a real event loop, which is what kept `PyQt6` in the portable collection |
+| `tests/test_control_center.py` | the WebEngine-ordering case → `tests/native/shared/test_webengine_startup.py`, now in a child: the production guard refuses once any `QApplication` exists, so it was passing on collection order |
+| `tests/test_app_update_handoff.py` | split. Rendered-script decisions stay portable; the executing cases → `tests/native/shared/test_update_handoff_native.py`, the Windows rollback → `tests/native/windows/`, the macOS rollback → `tests/native/macos/`; shared scaffolding → `tests/hanly_fixtures/update_handoff.py` |
+| `tests/test_hotkeys.py`, `tests/test_hotkeys_darwin.py` | stay portable: both drive doubles (`_Listener`, `_FakeCarbon`), never a real registration |
+| `tests/hanly_fixtures/process_probe.py` | stays; consumers updated by the Super QA patch |
+
+`tests/native/linux/` is deliberately absent: no case is Linux-only. Linux-native
+behavior (xcb plugin, display) is exercised by the shared cases on the Linux job.
+
 ## Observations for future review
 | Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
 | --- | --- | --- | --- |
+| `ci.yml` job names changed: `windows tests (py3.10)` is gone, replaced by `native (windows)`, `native (macos)`, `native (linux)` | The Windows job was a duplicate full suite; the three native jobs are the explicit owner of native coverage | **Needs a human decision**: branch protection or any required-check list naming the old job must be updated. `quality (py<version>)` is unchanged on purpose | Before the next merge that relies on required checks |
+| `build.yml` no longer runs the portable suite, ruff, or mypy | `ci.yml` owns them explicitly, and `ci.yml` runs on every push including a tag push | Release eligibility now depends on CI for the tag rather than on the build job repeating it. `release.yml` still requires a successful build run | If a release is ever cut from a tag whose CI run did not pass |
 | Per-OS runner behaviour of the new `build.yml` failure graph is unproven | The conditions are checked by a local scenario replay in `tests/test_ci_workflows.py`, not by Actions | Implemented; pending CI confirmation. No push authorization in this run | The next `workflow_dispatch` or tag build |
 | `worker close` became a reported stage | A crash while releasing native handles used to be attributed to the last provider stage | Implemented. The worker report now carries one extra stage | If a consumer parses the stage list positionally |
 | `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |
diff --git a/packaging/README.md b/packaging/README.md
index a29be44..4618a06 100644
--- a/packaging/README.md
+++ b/packaging/README.md
@@ -183,10 +183,46 @@ The inventory also names the two build inputs a frozen bundle cannot fetch:
 `certifi/cacert.pem` and both EasyOCR weights. A bundle missing them has
 working code and no way to verify a certificate or read a word.
 
-`tests/integration/test_packaged_desktop.py` is the same gate as a test. It
+`tests/packaged/shared/test_packaged_desktop.py` is the same gate as a test. It
 uses the platform's build output (`dist/<platform>/hanly-desktop`, or
 `dist/macos/Hanly.app`) by default, or the bundle named by
-`HANLY_PACKAGED_APP`.
+`HANLY_PACKAGED_APP`:
+
+```bash
+python -m pytest --suite packaged
+```
+
+## Three suites, three machines
+
+`python -m pytest` runs everything and stays the full local gate. Each suite is
+also selectable on its own, because each needs a different machine:
+
+```bash
+python -m pytest --suite portable   # no Qt, no Torch, no display
+python -m pytest --suite native     # the desktop runtime and a window server
+python -m pytest --suite packaged   # a frozen bundle
+```
+
+| Suite | Where it lives | What it needs |
+| --- | --- | --- |
+| portable | everything outside the two below | the root `dev` group only |
+| native | `tests/native/shared/`, plus `tests/native/<os>/` for this host | `hanly-app[runtime]`, a display, the EasyOCR weights, a KRDICT database |
+| packaged | `tests/packaged/` | a built bundle |
+
+Selection excludes a suite **before its modules are imported**, so a portable
+run never loads Qt, pywebview, or the OCR stack, and one platform's adapters
+are never imported on another. A marker cannot do that: deselection by marker
+happens after the import.
+
+`ci.yml` owns the first two — a Python matrix for the portable suite plus one
+native job per platform, each installing the runtime and building the
+dictionary its cases read. `build.yml` owns the third and no longer repeats the
+portable suite, the lint, or the type check.
+
+A capability a developer's machine lacks is a skip with a reason. In the jobs
+that exist to exercise it, `HANLY_REQUIRE_NATIVE=1` and
+`HANLY_REQUIRE_PACKAGED=1` turn every one of those reasons into a failure: a
+native gate that skipped everything would be a green run proving nothing.
 
 ## What a failed run leaves behind
 
diff --git a/pyproject.toml b/pyproject.toml
index 78bef50..ce79b82 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -17,6 +17,13 @@ dev = [
 [tool.pytest.ini_options]
 testpaths = ["tests", "benchmarks/dev/tests"]
 pythonpath = ["."]
+# Applied by the suite conftests from the directory a case lives in, so a
+# report says which machine ran what. Selection itself is `--suite`, which
+# excludes a suite before its modules are imported.
+markers = [
+    "native: runs real Qt, child-process, or OS-adapter behavior",
+    "packaged: runs the frozen product rather than the checkout",
+]
 
 [tool.ruff]
 target-version = "py310"
diff --git a/tests/hanly_fixtures/__init__.py b/tests/hanly_fixtures/__init__.py
index a10789c..f63f22e 100644
--- a/tests/hanly_fixtures/__init__.py
+++ b/tests/hanly_fixtures/__init__.py
@@ -1,5 +1,7 @@
 """Small deterministic fixtures shared by Hanly tests."""
 
+from pathlib import Path
+
 from .korean import (
     KOREAN_DICTIONARY_ENTRIES,
     KOREAN_OCR_RESULTS,
@@ -7,9 +9,16 @@ from .korean import (
     KOREAN_TOKEN_ANALYSES,
 )
 
+#: Named once, so a test that moves between suite directories does not have to
+#: recount how far it sits from the checkout it reads fixtures and builds from.
+REPO_ROOT = Path(__file__).resolve().parents[2]
+FIXTURE_ASSETS = Path(__file__).resolve().parent / "assets"
+
 __all__ = [
+    "FIXTURE_ASSETS",
     "KOREAN_DICTIONARY_ENTRIES",
     "KOREAN_OCR_RESULTS",
     "KOREAN_TEXT",
     "KOREAN_TOKEN_ANALYSES",
+    "REPO_ROOT",
 ]
diff --git a/tests/hanly_fixtures/capabilities.py b/tests/hanly_fixtures/capabilities.py
index d747649..2a630cf 100644
--- a/tests/hanly_fixtures/capabilities.py
+++ b/tests/hanly_fixtures/capabilities.py
@@ -3,15 +3,78 @@
 A capability the operating system withholds belongs in a skip with a reason,
 not in a failure: an unprivileged desktop and a CI runner have to disagree
 about what ran, never about what passed.
+
+That holds for an ordinary developer run. It does not hold for the job whose
+entire purpose is the capability in question -- a native or packaged gate that
+skips everything is a green run proving nothing. Those jobs set the variable
+below, and every reason becomes a failure instead.
 """
 
 from __future__ import annotations
 
+import os
+import sys
 import tempfile
+from importlib.util import find_spec
 from pathlib import Path
+from typing import NoReturn
 
 import pytest
 
+#: Set by the CI jobs that exist to run the native suites, and by the build
+#: job that exists to run the packaged suite.
+REQUIRE_NATIVE = "HANLY_REQUIRE_NATIVE"
+REQUIRE_PACKAGED = "HANLY_REQUIRE_PACKAGED"
+
+
+def unavailable(
+    reason: str, *, required_by: str = REQUIRE_NATIVE, module_level: bool = False
+) -> NoReturn:
+    """Skip for want of a capability, or fail where that want is the defect.
+
+    ``module_level`` is for a guard that runs while the module is being
+    imported, which is where a suite has to decide before it imports the
+    runtime it is about to exercise.
+    """
+
+    if os.environ.get(required_by) == "1":
+        pytest.fail(f"{reason} (required by {required_by})")
+    pytest.skip(reason, allow_module_level=module_level)
+
+
+def require_modules(
+    *names: str, required_by: str = REQUIRE_NATIVE, module_level: bool = False
+) -> None:
+    """Require installed packages without importing them.
+
+    Presence rather than an import: several native tests assert that the
+    process running them never loaded the desktop runtime, and importing it to
+    decide whether to run would be the thing they rule out.
+    """
+
+    missing = [name for name in names if find_spec(name) is None]
+    if missing:
+        unavailable(
+            f"the desktop runtime is not installed: {', '.join(missing)}",
+            required_by=required_by,
+            module_level=module_level,
+        )
+
+
+def require_display(*, required_by: str = REQUIRE_NATIVE) -> None:
+    """Require a session that can actually open a window.
+
+    Only Linux advertises a display it may not have; macOS and Windows answer
+    for their own window server, and a session without one fails there rather
+    than lying about it.
+    """
+
+    if not sys.platform.startswith("linux"):
+        return
+    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
+        return
+    unavailable("this needs a real display session", required_by=required_by)
+
 
 def _symlinks_available() -> bool:
     with tempfile.TemporaryDirectory() as directory:
@@ -30,4 +93,11 @@ requires_symlinks = pytest.mark.skipif(
     reason="creating a symbolic link needs a privilege this session does not have",
 )
 
-__all__ = ["requires_symlinks"]
+__all__ = [
+    "REQUIRE_NATIVE",
+    "REQUIRE_PACKAGED",
+    "require_display",
+    "require_modules",
+    "requires_symlinks",
+    "unavailable",
+]
diff --git a/tests/hanly_fixtures/update_handoff.py b/tests/hanly_fixtures/update_handoff.py
new file mode 100644
index 0000000..68208c3
--- /dev/null
+++ b/tests/hanly_fixtures/update_handoff.py
@@ -0,0 +1,391 @@
+"""Two compiled builds, a real script, and the swap that replaces one with the other.
+
+The rendered body of an update script proves nothing about what a shell does
+with it, so every executing case builds a throwaway old and new program, runs
+the production script over them, and reads back which one was started. The
+scaffolding lives here because the Windows-only and macOS-only rollbacks need
+exactly the same two builds as the shared cases.
+"""
+
+from __future__ import annotations
+
+import shutil
+import subprocess
+import sys
+import tempfile
+from dataclasses import dataclass
+from pathlib import Path
+from time import monotonic, sleep
+
+from hanly_app.app_update import APPLICATION_STEM, BUNDLE_NAME
+from hanly_app.app_update_handoff import (
+    EXIT_WAIT_SECONDS,
+    READY_WAIT_SECONDS,
+    UpdateTransaction,
+    _write_handoff_script,
+    handoff_arguments,
+    render_handoff_script,
+)
+
+from .capabilities import unavailable
+
+NEW_VERSION = "0.2.0"
+
+#: Bounded so an unlaunched build fails the test instead of hanging it.
+LAUNCH_WAIT_SECONDS = 60.0
+
+#: What each platform's installation is called, and the program inside it.
+MACOS_PROGRAM = f"Contents/MacOS/{APPLICATION_STEM}"
+
+#: What the host's own compiler driver calls the program it produces.
+PROGRAM_SUFFIX = ".exe" if sys.platform == "win32" else ""
+
+
+#: ``LINGER_SECONDS`` is how long the build stays alive after reporting, which
+#: is what makes it a build the handoff has to stop rather than one that has
+#: already let go of the directory it was started from.
+PROBE_SOURCE = """
+#include <stdio.h>
+#include <string.h>
+#ifdef _WIN32
+#include <windows.h>
+#else
+#include <unistd.h>
+#endif
+
+int main(int argc, char **argv) {
+    FILE *log = fopen(LOG, "a");
+    if (log) { fprintf(log, "%s\\n", IDENTITY); fclose(log); }
+    for (int index = 1; index + 1 < argc; index++) {
+        if (strcmp(argv[index], "--update-ready") == 0) {
+            FILE *ready = fopen(argv[index + 1], "w");
+            if (ready) { fputs(VERSION, ready); fclose(ready); }
+        }
+    }
+#ifdef _WIN32
+    if (LINGER_SECONDS > 0) { Sleep(LINGER_SECONDS * 1000); }
+#else
+    if (LINGER_SECONDS > 0) { sleep(LINGER_SECONDS); }
+#endif
+    return 0;
+}
+"""
+
+
+#: Which handoff variants this host can actually execute. macOS runs its own
+#: and Linux's: the Linux body is plain POSIX shell that execs the program at
+#: the final path, which a macOS host runs identically. Only the ``open``
+#: relaunch is Darwin-specific, and only Windows needs a Windows host.
+HANDOFF_VARIANTS = ["linux"] if sys.platform != "win32" else ["win32"]
+if sys.platform == "darwin":
+    HANDOFF_VARIANTS.insert(0, "darwin")
+
+
+@dataclass
+class Handoff:
+    """One prepared swap, and where its two programs record what happened."""
+
+    transaction: UpdateTransaction
+    log: Path
+    script: Path
+    program: Path
+
+    @property
+    def launched(self) -> list[str]:
+        text = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
+        return text.split()
+
+    def await_launched(self, expected: list[str]) -> list[str]:
+        """Wait out an asynchronous relaunch before reading the record.
+
+        ``open`` returns as soon as it has asked for the application; the
+        handoff does not wait for it either, so neither the script's exit nor
+        its own cleanup means the relaunched build has run yet.
+        """
+
+        deadline = monotonic() + LAUNCH_WAIT_SECONDS
+        while self.launched != expected and monotonic() < deadline:
+            sleep(0.1)
+        return self.launched
+
+
+def transaction_for(
+    install_root: Path,
+    *,
+    version: str = NEW_VERSION,
+    ready_root: Path | None = None,
+) -> UpdateTransaction:
+    directory = install_root.parent / ".hanly-update-probe"
+    directory.mkdir(parents=True, exist_ok=True)
+    return UpdateTransaction(
+        directory=directory,
+        install_root=install_root,
+        staged_path=directory / install_root.name,
+        backup_path=directory / "previous",
+        ready_path=(ready_root or directory) / "ready",
+        version=version,
+    )
+
+
+def c_string(value: object) -> str:
+    """Quote a value as a C string literal.
+
+    A Windows path is full of backslashes, so a macro expanding to
+    ``"C:\\Users\\runneradmin\\..."`` is a string of escape sequences rather
+    than a path -- and ``\\U`` is not even a valid one, which is how this
+    first failed to compile on the Windows runner.
+    """
+
+    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
+    return f'"{text}"'
+
+
+def _compile(
+    source: Path,
+    program: Path,
+    *,
+    identity: str,
+    version: str,
+    log: Path,
+    linger: int = 0,
+) -> None:
+    """Build one probe beside its source, then put it where it belongs.
+
+    The compiler only ever sees the probe directory, which is ASCII: binutils
+    takes ``argv`` through the Windows ANSI code page, so an output path
+    containing Hangul reaches ``ld`` as ``?? ????`` and cannot be opened.
+    Moving the finished program to an installation path the handoff is
+    supposed to cope with is Python's job, and Python has no such limit.
+    """
+
+    built = source.parent / f"probe-{identity}{PROGRAM_SUFFIX}"
+    command = [
+        str(COMPILER),
+        f"-DIDENTITY={c_string(identity)}",
+        f"-DVERSION={c_string(version)}",
+        f"-DLINGER_SECONDS={linger}",
+        # Forward slashes: every Windows CRT accepts them, and they leave the
+        # macro with nothing left to escape.
+        f"-DLOG={c_string(log.as_posix())}",
+        "-o",
+        str(built),
+        str(source),
+    ]
+    finished = subprocess.run(command, capture_output=True, timeout=120)
+    if finished.returncode != 0:
+        # Without this the failure is a bare CalledProcessError and the
+        # compiler's own explanation is thrown away.
+        raise AssertionError(
+            "could not compile the update probe\n"
+            f"command: {' '.join(command)}\n"
+            f"stderr:\n{finished.stderr.decode('utf-8', 'replace')}"
+        )
+
+    program.parent.mkdir(parents=True, exist_ok=True)
+    shutil.copy2(built, program)
+
+
+def _dead_pid() -> str:
+    """Return a pid that has already exited, so the handoff stops waiting."""
+
+    finished = subprocess.Popen([sys.executable, "-c", ""])
+    finished.wait()
+    return str(finished.pid)
+
+
+def _macos_bundle(root: Path) -> None:
+    """Give a bundle the Info.plist LaunchServices refuses to open without."""
+
+    import plistlib
+
+    (root / "Contents").mkdir(parents=True, exist_ok=True)
+    (root / "Contents" / "Info.plist").write_bytes(
+        plistlib.dumps(
+            {
+                "CFBundleExecutable": APPLICATION_STEM,
+                "CFBundleIdentifier": f"io.github.thiagoross1.hanly.probe.{root.parent.name}",
+                "CFBundleName": "Hanly",
+                "CFBundlePackageType": "APPL",
+            }
+        )
+    )
+
+
+def prepare_handoff(
+    tmp_path: Path,
+    platform: str,
+    *,
+    new_version: str = NEW_VERSION,
+    probe_root: Path | None = None,
+    linger: int = 0,
+) -> Handoff:
+    """Build an old installation, a staged replacement, and the real script.
+
+    ``probe_root`` is where the probe's own two files live: the program's log
+    and the readiness file it writes. It is separate from ``tmp_path`` so the
+    installation under test can carry spaces and Hangul while the C probe --
+    which receives paths through a compile-time macro and an ANSI ``argv`` on
+    Windows -- only ever handles ASCII. What the handoff renames, relaunches
+    and cleans up is still the awkward path.
+    """
+
+    _require_a_compiler()
+    tmp_path.mkdir(parents=True, exist_ok=True)
+    probes = probe_root or tmp_path
+    probes.mkdir(parents=True, exist_ok=True)
+    source = probes / "probe.c"
+    source.write_text(PROBE_SOURCE, encoding="ascii")
+    log = probes / "launched.txt"
+
+    darwin = platform == "darwin"
+    name = BUNDLE_NAME if darwin else APPLICATION_STEM
+    # The name the layout really carries on this platform, so the swap under
+    # test relaunches exactly what a shipped update would.
+    inside = MACOS_PROGRAM if darwin else f"{APPLICATION_STEM}{PROGRAM_SUFFIX}"
+
+    install_root = tmp_path / "install" / name
+    transaction = transaction_for(install_root, ready_root=probes)
+    for root, identity, version, stays in (
+        (install_root, "old", "0.1.0", 0),
+        (transaction.staged_path, "new", new_version, linger),
+    ):
+        _compile(
+            source, root / inside, identity=identity, version=version, log=log, linger=stays
+        )
+        if darwin:
+            _macos_bundle(root)
+
+    return Handoff(
+        transaction,
+        log,
+        _script(tmp_path, executable=inside, platform=platform),
+        install_root / inside,
+    )
+
+
+#: Ten minutes is the right bound for a frozen build on a cold start and the
+#: wrong one for a test, so the two waits are shortened in the copy that runs
+#: here. Their presence in the shipped body is asserted by the portable suite.
+def _script(tmp_path: Path, *, executable: str, platform: str) -> Path:
+    body = render_handoff_script(executable=executable, platform=platform)
+    for bound in (EXIT_WAIT_SECONDS, READY_WAIT_SECONDS):
+        assert body.count(str(bound)) == 1, body
+        body = body.replace(str(bound), "8")
+
+    # The production writer owns encoding, line endings and mode. Restating
+    # them here would let this suite stay green while the real one regressed.
+    return _write_handoff_script(body, platform=platform, directory=tmp_path)
+
+
+def run_handoff(handoff: Handoff, *, expect_status: int) -> Handoff:
+    launcher = (
+        [
+            "powershell.exe",
+            "-NoProfile",
+            "-NonInteractive",
+            "-ExecutionPolicy",
+            "Bypass",
+            "-File",
+        ]
+        if handoff.script.suffix == ".ps1"
+        else ["/bin/sh"]
+    )
+    arguments = handoff_arguments(handoff.transaction)
+    arguments[0] = _dead_pid()
+    finished = subprocess.run(
+        [*launcher, str(handoff.script), *arguments],
+        check=False,
+        capture_output=True,
+        timeout=180,
+        cwd=handoff.script.parent,
+    )
+
+    assert finished.returncode == expect_status, finished.stderr.decode("utf-8", "replace")
+    return handoff
+
+
+def _builds_programs(compiler: str) -> bool:
+    """Answer whether a compiler on PATH can in fact produce a program.
+
+    Being on PATH is not the same as working: an MSYS2 ``cc`` whose ``cc1``
+    cannot load its own libraries exits non-zero with an empty stderr, which
+    would otherwise fail every test below with nothing to go on.
+    """
+
+    with tempfile.TemporaryDirectory() as directory:
+        source = Path(directory) / "usable.c"
+        source.write_text("int main(void) { return 0; }\n", encoding="ascii")
+        try:
+            finished = subprocess.run(
+                [compiler, "-o", str(source.with_suffix(PROGRAM_SUFFIX or ".out")), str(source)],
+                capture_output=True,
+                timeout=120,
+            )
+        except OSError:
+            return False
+    return finished.returncode == 0
+
+
+#: The two builds being swapped are compiled rather than scripted: macOS
+#: refuses to ``open`` a bundle whose executable is a shell script, and Windows
+#: needs a real executable to ``Start-Process``. Named explicitly so a host
+#: without a working one says so, rather than failing on a missing or broken
+#: ``cc``.
+COMPILER = next(
+    (
+        found
+        for name in ("cc", "clang", "gcc")
+        if (found := shutil.which(name)) and _builds_programs(found)
+    ),
+    None,
+)
+
+
+def _require_a_compiler() -> None:
+    """Refuse to pretend a host without a compiler checked the swap.
+
+    Called from :func:`prepare_handoff` rather than declared as a marker, so
+    every case -- including the two platform-specific rollbacks -- inherits it
+    without repeating it, and a required native job fails instead of skipping.
+    """
+
+    if COMPILER is None:
+        unavailable(
+            "the handoff cases compile the builds they swap; "
+            "no cc, clang, or gcc on PATH"
+        )
+
+
+def with_dead_pid(handoff: Handoff) -> list[str]:
+    """The handoff's own arguments, with a pid that has already exited."""
+
+    arguments = handoff_arguments(handoff.transaction)
+    arguments[0] = _dead_pid()
+    return arguments
+
+
+def assert_identity(handoff: Handoff, expected: str) -> None:
+    """Run whatever is at the installation path and see which build answers."""
+
+    before = len(handoff.launched)
+    subprocess.run([str(handoff.program)], check=True, timeout=60)
+
+    assert handoff.launched[before:] == [expected]
+
+
+__all__ = [
+    "HANDOFF_VARIANTS",
+    "LAUNCH_WAIT_SECONDS",
+    "MACOS_PROGRAM",
+    "NEW_VERSION",
+    "PROBE_SOURCE",
+    "COMPILER",
+    "PROGRAM_SUFFIX",
+    "Handoff",
+    "assert_identity",
+    "c_string",
+    "prepare_handoff",
+    "run_handoff",
+    "transaction_for",
+    "with_dead_pid",
+]
diff --git a/tests/integration/test_webengine_startup.py b/tests/hanly_fixtures/webengine_probe.py
similarity index 52%
rename from tests/integration/test_webengine_startup.py
rename to tests/hanly_fixtures/webengine_probe.py
index b6169ef..ec90e35 100644
--- a/tests/integration/test_webengine_startup.py
+++ b/tests/hanly_fixtures/webengine_probe.py
@@ -1,29 +1,23 @@
-"""Real-process proof that Qt WebEngine starts through the shared application.
+"""The child that starts Qt WebEngine for real, and how to run it.
 
-Every other Control Center test injects a fake webview, so none of them ever
-initializes Chromium. This one does: it launches a bounded subprocess that
-builds the production ``QApplication`` and loads a document in a real
-``QWebEngineView``. Surviving a few seconds is not the assertion -- the child
-must report a finished load and exit cleanly.
+Shared rather than duplicated: the successful contract is every platform's,
+and the Windows abort it guards against is asserted against the same child.
 """
 
 from __future__ import annotations
 
-import os
 import subprocess
 import sys
 from pathlib import Path
 
-import pytest
-
 #: Printed by the child only after ``loadFinished(True)``.
 LOADED_MARKER = "WEBENGINE_LOADED"
 
 #: Generous enough for a cold Chromium start on a loaded CI runner, short
 #: enough that a hung child fails the run instead of stalling it.
-_CHILD_TIMEOUT_SECONDS = 300
+CHILD_TIMEOUT_SECONDS = 300
 
-_CHILD_PROGRAM = '''
+CHILD_PROGRAM = '''
 import sys
 
 MARKER = "WEBENGINE_LOADED"
@@ -88,47 +82,23 @@ if __name__ == "__main__":
 '''
 
 
-def _skip_without_a_desktop() -> None:
-    pytest.importorskip("PyQt6.QtWebEngineWidgets")
-    if sys.platform.startswith("linux") and not (
-        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
-    ):
-        pytest.skip("Qt WebEngine startup needs a real display session")
-
+def run_webengine_child(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
+    """Run the probe in a bounded child, in the mode the caller is checking."""
 
-def _run_child(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
     program = tmp_path / "webengine_child.py"
-    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
+    program.write_text(CHILD_PROGRAM, encoding="utf-8")
     return subprocess.run(
         [sys.executable, str(program), mode],
         capture_output=True,
         text=True,
-        timeout=_CHILD_TIMEOUT_SECONDS,
+        timeout=CHILD_TIMEOUT_SECONDS,
         cwd=tmp_path,
     )
 
 
-def test_the_shared_application_loads_a_document_in_qt_webengine(tmp_path: Path) -> None:
-    _skip_without_a_desktop()
-
-    child = _run_child(tmp_path, "shared")
-
-    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
-    assert LOADED_MARKER in child.stdout, f"stderr={child.stderr!r}"
-
-
-@pytest.mark.skipif(sys.platform != "win32", reason="the abort code is Windows-specific")
-def test_an_empty_argument_list_still_aborts_chromium_on_windows(tmp_path: Path) -> None:
-    """The defect this fix exists for, kept executable rather than anecdotal.
-
-    Only the Windows abort code is asserted here; every other platform asserts
-    the successful contract above instead of a native exception number.
-    """
-
-    _skip_without_a_desktop()
-
-    child = _run_child(tmp_path, "empty-argv")
-
-    assert child.returncode != 0
-    assert LOADED_MARKER not in child.stdout
-    assert "the program name is not passed" in child.stderr
+__all__ = [
+    "CHILD_PROGRAM",
+    "CHILD_TIMEOUT_SECONDS",
+    "LOADED_MARKER",
+    "run_webengine_child",
+]
diff --git a/tests/integration/__init__.py b/tests/native/__init__.py
similarity index 100%
rename from tests/integration/__init__.py
rename to tests/native/__init__.py
diff --git a/tests/native/conftest.py b/tests/native/conftest.py
new file mode 100644
index 0000000..1466e57
--- /dev/null
+++ b/tests/native/conftest.py
@@ -0,0 +1,70 @@
+"""Which native cases this host can run at all, and what marks them.
+
+``shared`` holds real Qt, real child-process, and real window behavior that
+every platform must satisfy. Each OS directory beside it holds that platform's
+own adapters, and only the matching host ever imports one.
+"""
+
+from __future__ import annotations
+
+import sys
+from collections.abc import Iterator
+from pathlib import Path
+from typing import TYPE_CHECKING
+
+import pytest
+
+if TYPE_CHECKING:
+    from hanly_app.qt_popup import QtPopupView
+    from PyQt6.QtWidgets import QApplication
+
+#: The directory whose adapters this host actually has.
+HOST_DIRECTORY = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
+
+#: Behavior every platform owes, regardless of which host is running.
+SHARED_DIRECTORY = "shared"
+
+_ROOT = Path(__file__).parent
+
+
+def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
+    """Keep another platform's adapters out of this host's collection.
+
+    Before the import rather than after: a Windows-only module imports a
+    Windows-only adapter, and a marker is consulted only once that has already
+    happened.
+    """
+
+    if collection_path.parent != _ROOT or not collection_path.is_dir():
+        return None
+    return collection_path.name not in (SHARED_DIRECTORY, HOST_DIRECTORY)
+
+
+def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
+    for item in items:
+        item.add_marker("native")
+
+
+@pytest.fixture(scope="session")
+def qt_application() -> QApplication:
+    """The one ``QApplication`` a process may have, shared by every Qt case.
+
+    Imported here rather than at module scope: this conftest also configures
+    the native cases that assert they never loaded Qt at all.
+    """
+
+    from PyQt6.QtWidgets import QApplication
+
+    existing = QApplication.instance()
+    if isinstance(existing, QApplication):
+        return existing
+    return QApplication([])
+
+
+@pytest.fixture
+def popup_view(qt_application: QApplication) -> Iterator[QtPopupView]:
+    from hanly_app.qt_popup import QtPopupView
+
+    popup = QtPopupView()
+    yield popup
+    popup.close()
diff --git a/tests/native/macos/__init__.py b/tests/native/macos/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/native/macos/test_control_center_identity.py b/tests/native/macos/test_control_center_identity.py
new file mode 100644
index 0000000..b2ff042
--- /dev/null
+++ b/tests/native/macos/test_control_center_identity.py
@@ -0,0 +1,131 @@
+"""What macOS thinks the window child is, run on a real Cocoa session."""
+
+from __future__ import annotations
+
+import json
+import subprocess
+import sys
+from pathlib import Path
+
+from tests.hanly_fixtures.capabilities import require_display, require_modules
+
+_CHILD_TIMEOUT_SECONDS = 300
+
+_IDENTITY_PROGRAM = '''
+import json
+import re
+import subprocess
+import threading
+import time
+
+from hanly_app.control_center import ControlCenterBridge
+from hanly_app.control_center_process import ControlCenterProcess, bridge_operations
+
+REPORT_PREFIX = "IDENTITY_REPORT "
+
+
+def registrations(pids):
+    """What LaunchServices thinks each of these processes is."""
+
+    listing = subprocess.run(["lsappinfo", "list"], capture_output=True, text=True).stdout
+    found = {}
+    for block in listing.split("ASN:"):
+        match = re.search(r"pid = (\\d+)", block)
+        kind = re.search(r'type="([^"]+)"', block)
+        if match and int(match.group(1)) in pids:
+            found[int(match.group(1))] = kind.group(1) if kind else "unknown"
+    return found
+
+
+def descendants(root):
+    rows = subprocess.run(
+        ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True
+    ).stdout
+    children = []
+    for line in rows.splitlines():
+        parts = line.split()
+        if len(parts) == 2 and int(parts[1]) == root:
+            children.append(int(parts[0]))
+    return children
+
+
+class CountingBridge(ControlCenterBridge):
+    def __init__(self):
+        super().__init__()
+        self.calls = []
+
+    def get_state(self):
+        self.calls.append("get_state")
+        return super().get_state()
+
+
+def main():
+    import os
+
+    bridge = CountingBridge()
+    control = ControlCenterProcess(bridge_operations(bridge))
+    report = {"errors": []}
+    try:
+        control.show()
+        waiter = threading.Event()
+        for _ in range(240):
+            if bridge.calls:
+                break
+            waiter.wait(0.25)
+        report["page_reached_the_bridge"] = bool(bridge.calls)
+        time.sleep(1.5)
+        children = descendants(os.getpid())
+        report["registrations"] = {
+            str(pid): kind for pid, kind in registrations(set(children)).items()
+        }
+    except BaseException as error:
+        report["errors"].append(f"{type(error).__name__}: {error}")
+    finally:
+        control.shutdown()
+    print(REPORT_PREFIX + json.dumps(report), flush=True)
+    return 0 if not report["errors"] else 1
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
+'''
+
+
+def _require_a_desktop() -> None:
+    require_modules("PyQt6.QtWebEngineWidgets", "webview")
+    require_display()
+
+
+def test_the_window_child_is_not_a_second_application_on_macos(tmp_path: Path) -> None:
+    """One Hanly in the Dock, whatever the window is running in.
+
+    ``Foreground`` is a full application: a Dock tile, a menu bar, and an entry
+    in the app switcher. ``UIElement`` still shows windows and still takes the
+    keyboard, which is what a panel owned by another process needs.
+    """
+
+    _require_a_desktop()
+
+    program = tmp_path / "identity_child.py"
+    program.write_text(_IDENTITY_PROGRAM, encoding="utf-8")
+    child = subprocess.run(
+        [sys.executable, str(program)],
+        capture_output=True,
+        text=True,
+        timeout=_CHILD_TIMEOUT_SECONDS,
+        cwd=tmp_path,
+    )
+
+    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
+    marker = "IDENTITY_REPORT "
+    line = next(
+        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
+    )
+    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
+    report = json.loads(line[len(marker) :])
+
+    assert report["errors"] == []
+    assert report["page_reached_the_bridge"] is True
+    registrations = report["registrations"]
+    assert registrations, "no owned process was registered with LaunchServices"
+    assert "Foreground" not in registrations.values(), registrations
diff --git a/tests/native/macos/test_popup_panel.py b/tests/native/macos/test_popup_panel.py
new file mode 100644
index 0000000..de48af9
--- /dev/null
+++ b/tests/native/macos/test_popup_panel.py
@@ -0,0 +1,54 @@
+"""The one native property that keeps the popup on screen while Hanly is not.
+
+Everything else about the popup is a Qt window contract and lives in the shared
+suite. This is the Objective-C property underneath it, which only a real Cocoa
+session can answer for.
+"""
+
+from __future__ import annotations
+
+from hanly import DictionaryEntry, LookupResult, LookupStatus
+
+from tests.hanly_fixtures.capabilities import require_modules, unavailable
+
+require_modules("PyQt6.QtWidgets", module_level=True)
+
+from hanly_app.popup import PopupPosition  # noqa: E402
+from hanly_app.qt_popup import QtPopupView  # noqa: E402
+from PyQt6.QtWidgets import QApplication  # noqa: E402
+
+
+def _result() -> LookupResult:
+    return LookupResult(
+        status=LookupStatus.SUCCESS,
+        entries=(
+            DictionaryEntry(
+                headword="한국어",
+                definitions=("the Korean language",),
+                part_of_speech="noun",
+            ),
+        ),
+    )
+
+
+def test_the_popup_is_not_withdrawn_when_hanly_loses_focus(
+    qt_application: QApplication, popup_view: QtPopupView
+) -> None:
+    """The regression: AppKit stops compositing a utility panel on deactivation.
+
+    Qt and NSWindow both keep reporting the popup visible while the window
+    server has dropped it, so the property itself is what gets asserted.
+    """
+
+    if qt_application.platformName() != "cocoa":
+        unavailable("winId() is an NSView only under the cocoa platform plugin")
+
+    from hanly_app.popup_darwin import hides_when_inactive
+
+    assert hides_when_inactive(int(popup_view.winId())) is False
+
+    # Still false across a show/hide cycle, which is when Qt could have
+    # replaced the native window under the widget.
+    popup_view.show_result(_result(), PopupPosition(60, 60))
+    popup_view.hide()
+    assert hides_when_inactive(int(popup_view.winId())) is False
diff --git a/tests/native/macos/test_update_handoff_darwin.py b/tests/native/macos/test_update_handoff_darwin.py
new file mode 100644
index 0000000..864a07f
--- /dev/null
+++ b/tests/native/macos/test_update_handoff_darwin.py
@@ -0,0 +1,49 @@
+"""The rollback only macOS needs: ``open`` returns no pid to stop."""
+
+from __future__ import annotations
+
+import subprocess
+from pathlib import Path
+
+from tests.hanly_fixtures.update_handoff import assert_identity, prepare_handoff, run_handoff
+
+
+def test_a_rejected_macos_build_is_stopped_from_a_path_full_of_metacharacters(
+    tmp_path: Path,
+) -> None:
+    """``open`` returns no pid, so macOS finds the candidate by the path it runs
+    from -- and an installation path is text a person chose, not a pattern. Read
+    as a regular expression, ``C++ apps`` does not compile and ``[beta]`` is a
+    character class, so the candidate is silently never matched and survives the
+    rollback that deletes the directory underneath it."""
+
+    handoff = run_handoff(
+        prepare_handoff(
+            tmp_path / "C++ apps [beta]",
+            "darwin",
+            new_version="9.9.9",
+            linger=60,
+            probe_root=tmp_path / "probe",
+        ),
+        expect_status=1,
+    )
+
+    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
+    # Only the candidate is started with the readiness argument, so this sees
+    # that one process and never the restored build launched beside it.
+    assert not _running_with(str(handoff.transaction.ready_path))
+    assert not handoff.transaction.directory.exists()
+    assert_identity(handoff, "old")
+
+
+def _running_with(argument: str) -> bool:
+    """Whether any process still carries ``argument`` on its command line.
+
+    Compared as literal text rather than handed to ``pgrep -f``: the paths this
+    checks are exactly the ones a regular expression would misread.
+    """
+
+    listing = subprocess.run(
+        ["/bin/ps", "-axww", "-o", "args="], capture_output=True, text=True
+    ).stdout
+    return any(argument in line for line in listing.splitlines())
diff --git a/tests/native/shared/__init__.py b/tests/native/shared/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/integration/test_control_center_layout.py b/tests/native/shared/test_control_center_layout.py
similarity index 91%
rename from tests/integration/test_control_center_layout.py
rename to tests/native/shared/test_control_center_layout.py
index d113033..dc4040c 100644
--- a/tests/integration/test_control_center_layout.py
+++ b/tests/native/shared/test_control_center_layout.py
@@ -9,12 +9,11 @@ real window and reads the boxes back out of it.
 from __future__ import annotations
 
 import json
-import os
 import subprocess
 import sys
 from pathlib import Path
 
-import pytest
+from tests.hanly_fixtures.capabilities import require_display, require_modules
 
 #: Every width the window can actually be, plus the narrower viewports display
 #: scaling and page zoom produce inside it. 780 is the one that overflowed.
@@ -94,13 +93,9 @@ print(REPORT_PREFIX + json.dumps(report), flush=True)
 '''
 
 
-def _skip_without_a_desktop() -> None:
-    pytest.importorskip("PyQt6.QtWebEngineWidgets")
-    pytest.importorskip("webview")
-    if sys.platform.startswith("linux") and not (
-        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
-    ):
-        pytest.skip("the Control Center layout needs a real desktop session")
+def _require_a_desktop() -> None:
+    require_modules("PyQt6.QtWebEngineWidgets", "webview")
+    require_display()
 
 
 def test_every_supported_width_fits_without_scrolling_sideways(tmp_path: Path) -> None:
@@ -110,7 +105,7 @@ def test_every_supported_width_fits_without_scrolling_sideways(tmp_path: Path) -
     controls on the right went past the edge.
     """
 
-    _skip_without_a_desktop()
+    _require_a_desktop()
 
     program = tmp_path / "layout_child.py"
     program.write_text(_CHILD_PROGRAM, encoding="utf-8")
diff --git a/tests/integration/test_control_center_lifecycle.py b/tests/native/shared/test_control_center_lifecycle.py
similarity index 74%
rename from tests/integration/test_control_center_lifecycle.py
rename to tests/native/shared/test_control_center_lifecycle.py
index 1449b26..a9e08b3 100644
--- a/tests/integration/test_control_center_lifecycle.py
+++ b/tests/native/shared/test_control_center_lifecycle.py
@@ -11,13 +11,13 @@ that the shell survived both and that Qt never reported a nested event loop.
 from __future__ import annotations
 
 import json
-import os
 import subprocess
 import sys
 from pathlib import Path
 
 import pytest
 
+from tests.hanly_fixtures.capabilities import require_display, require_modules
 from tests.hanly_fixtures.process_probe import PROCESS_ROWS_PROGRAM
 
 #: Qt's own complaint when a second ``exec`` runs inside a live loop. This is
@@ -227,99 +227,15 @@ if __name__ == "__main__":
 #: macOS registers every process that creates a ``QApplication`` as a
 #: user-facing application, which made the Control Center child a second Hanly
 #: in the Dock and the app switcher beside the shell.
-_IDENTITY_PROGRAM = '''
-import json
-import re
-import subprocess
-import threading
-import time
-
-from hanly_app.control_center import ControlCenterBridge
-from hanly_app.control_center_process import ControlCenterProcess, bridge_operations
-
-REPORT_PREFIX = "IDENTITY_REPORT "
-
-
-def registrations(pids):
-    """What LaunchServices thinks each of these processes is."""
-
-    listing = subprocess.run(["lsappinfo", "list"], capture_output=True, text=True).stdout
-    found = {}
-    for block in listing.split("ASN:"):
-        match = re.search(r"pid = (\\d+)", block)
-        kind = re.search(r'type="([^"]+)"', block)
-        if match and int(match.group(1)) in pids:
-            found[int(match.group(1))] = kind.group(1) if kind else "unknown"
-    return found
-
-
-def descendants(root):
-    rows = subprocess.run(
-        ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True
-    ).stdout
-    children = []
-    for line in rows.splitlines():
-        parts = line.split()
-        if len(parts) == 2 and int(parts[1]) == root:
-            children.append(int(parts[0]))
-    return children
-
-
-class CountingBridge(ControlCenterBridge):
-    def __init__(self):
-        super().__init__()
-        self.calls = []
-
-    def get_state(self):
-        self.calls.append("get_state")
-        return super().get_state()
-
-
-def main():
-    import os
-
-    bridge = CountingBridge()
-    control = ControlCenterProcess(bridge_operations(bridge))
-    report = {"errors": []}
-    try:
-        control.show()
-        waiter = threading.Event()
-        for _ in range(240):
-            if bridge.calls:
-                break
-            waiter.wait(0.25)
-        report["page_reached_the_bridge"] = bool(bridge.calls)
-        time.sleep(1.5)
-        children = descendants(os.getpid())
-        report["registrations"] = {
-            str(pid): kind for pid, kind in registrations(set(children)).items()
-        }
-    except BaseException as error:
-        report["errors"].append(f"{type(error).__name__}: {error}")
-    finally:
-        control.shutdown()
-    print(REPORT_PREFIX + json.dumps(report), flush=True)
-    return 0 if not report["errors"] else 1
-
-
-if __name__ == "__main__":
-    raise SystemExit(main())
-'''
-
-
-def _skip_without_a_desktop() -> None:
-    pytest.importorskip("PyQt6.QtWebEngineWidgets")
-    pytest.importorskip("webview")
-    if sys.platform.startswith("linux") and not (
-        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
-    ):
-        pytest.skip("the Control Center lifecycle needs a real desktop session")
+def _require_a_desktop() -> None:
+    require_modules("PyQt6.QtWebEngineWidgets", "webview")
+    require_display()
 
 
 def test_the_window_opens_closes_and_reopens_without_touching_the_shell(
     tmp_path: Path,
 ) -> None:
-    _skip_without_a_desktop()
+    _require_a_desktop()
 
     program = tmp_path / "lifecycle_child.py"
     program.write_text(PROCESS_ROWS_PROGRAM + _CHILD_PROGRAM, encoding="utf-8")
@@ -373,7 +289,7 @@ def test_focusing_a_window_that_is_still_starting_keeps_the_page_connected(
     placeholder state rather than reporting that nothing answered.
     """
 
-    _skip_without_a_desktop()
+    _require_a_desktop()
 
     program = tmp_path / "focus_race_child.py"
     program.write_text(_RACING_FOCUS_PROGRAM, encoding="utf-8")
@@ -402,42 +318,6 @@ def test_focusing_a_window_that_is_still_starting_keeps_the_page_connected(
     assert "ControlCenterUnavailable" not in child.stderr
 
 
-@pytest.mark.skipif(sys.platform != "darwin", reason="macOS application identity")
-def test_the_window_child_is_not_a_second_application_on_macos(tmp_path: Path) -> None:
-    """One Hanly in the Dock, whatever the window is running in.
-
-    ``Foreground`` is a full application: a Dock tile, a menu bar, and an entry
-    in the app switcher. ``UIElement`` still shows windows and still takes the
-    keyboard, which is what a panel owned by another process needs.
-    """
-
-    _skip_without_a_desktop()
-
-    program = tmp_path / "identity_child.py"
-    program.write_text(_IDENTITY_PROGRAM, encoding="utf-8")
-    child = subprocess.run(
-        [sys.executable, str(program)],
-        capture_output=True,
-        text=True,
-        timeout=_CHILD_TIMEOUT_SECONDS,
-        cwd=tmp_path,
-    )
-
-    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
-    marker = "IDENTITY_REPORT "
-    line = next(
-        (item for item in child.stdout.splitlines() if item.startswith(marker)), None
-    )
-    assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
-    report = json.loads(line[len(marker) :])
-
-    assert report["errors"] == []
-    assert report["page_reached_the_bridge"] is True
-    registrations = report["registrations"]
-    assert registrations, "no owned process was registered with LaunchServices"
-    assert "Foreground" not in registrations.values(), registrations
-
-
 @pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminal signal delivery")
 def test_owned_child_leaves_sigint_to_parent_shutdown(tmp_path: Path) -> None:
     program = tmp_path / "child_sigint.py"
diff --git a/tests/integration/test_desktop_startup.py b/tests/native/shared/test_desktop_startup.py
similarity index 88%
rename from tests/integration/test_desktop_startup.py
rename to tests/native/shared/test_desktop_startup.py
index 121f354..766f7ef 100644
--- a/tests/integration/test_desktop_startup.py
+++ b/tests/native/shared/test_desktop_startup.py
@@ -17,7 +17,12 @@ import subprocess
 import sys
 from pathlib import Path
 
-import pytest
+from tests.hanly_fixtures import REPO_ROOT
+from tests.hanly_fixtures.capabilities import (
+    require_display,
+    require_modules,
+    unavailable,
+)
 
 #: The child writes its report to a file rather than a pipe. Qt WebEngine
 #: spawns helper processes that inherit stdout on Windows, so waiting for the
@@ -114,13 +119,7 @@ def _existing_models() -> Path | None:
     """Find prepared EasyOCR weights, which are an input rather than a download."""
 
     candidates = [
-        Path(__file__).parents[2]
-        / "packages"
-        / "hanly-app"
-        / "src"
-        / "hanly_app"
-        / "assets"
-        / "easyocr_models",
+        REPO_ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "assets" / "easyocr_models",
         Path.home() / ".EasyOCR" / "model",
     ]
     return next(
@@ -139,31 +138,26 @@ def _existing_dictionary() -> Path | None:
     local = os.environ.get("LOCALAPPDATA")
     if local:
         candidates.append(Path(local) / "Hanly" / "resources" / "krdict" / "krdict.sqlite3")
-    candidates.append(Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3")
+    candidates.append(REPO_ROOT / "data" / "generated" / "krdict.sqlite3")
     return next((path for path in candidates if path.is_file()), None)
 
 
-def _skip_without_a_desktop_runtime() -> tuple[Path, Path]:
-    pytest.importorskip("PyQt6.QtWebEngineWidgets")
-    pytest.importorskip("webview")
-    pytest.importorskip("kiwipiepy")
-    if sys.platform.startswith("linux") and not (
-        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
-    ):
-        pytest.skip("desktop startup needs a real display session")
+def _require_a_desktop_runtime() -> tuple[Path, Path]:
+    require_modules("PyQt6.QtWebEngineWidgets", "webview", "kiwipiepy")
+    require_display()
     dictionary = _existing_dictionary()
     if dictionary is None:
-        pytest.skip("no built KRDICT database; see data/README.md")
+        unavailable("no built KRDICT database; see data/README.md")
     models = _existing_models()
     if models is None:
-        pytest.skip("no prepared EasyOCR weights; see tools/prepare_easyocr_models.py")
+        unavailable("no prepared EasyOCR weights; see tools/prepare_easyocr_models.py")
     return dictionary, models
 
 
 def test_the_desktop_opens_and_reaches_ready_without_starting_capture(
     tmp_path: Path,
 ) -> None:
-    dictionary, models = _skip_without_a_desktop_runtime()
+    dictionary, models = _require_a_desktop_runtime()
 
     config = tmp_path / "runtime.json"
     config.write_text(
diff --git a/tests/test_hover_exit_qt.py b/tests/native/shared/test_hover_exit_qt.py
similarity index 92%
rename from tests/test_hover_exit_qt.py
rename to tests/native/shared/test_hover_exit_qt.py
index 010c6bf..59fc4e0 100644
--- a/tests/test_hover_exit_qt.py
+++ b/tests/native/shared/test_hover_exit_qt.py
@@ -11,10 +11,11 @@ from __future__ import annotations
 
 from collections.abc import Callable
 
-import pytest
 from hanly import LookupResult, LookupStatus, PixelFormat, Point, ROIImage
 
-pytest.importorskip("PyQt6.QtWidgets")
+from tests.hanly_fixtures.capabilities import require_modules
+
+require_modules("PyQt6.QtWidgets", module_level=True)
 
 from hanly_app.capture import CaptureResult, ScreenRect  # noqa: E402
 from hanly_app.hover_lookup import HoverLookupRuntime  # noqa: E402
@@ -30,14 +31,6 @@ _POPUP = ScreenRect(300, 100, 320, 180)
 _DWELL_MS = 80
 
 
-@pytest.fixture(scope="module")
-def application() -> QApplication:
-    existing = QCoreApplication.instance()
-    if isinstance(existing, QApplication):
-        return existing
-    return QApplication([])
-
-
 class _Listener:
     def __init__(self, on_move: Callable[[int, int], None]) -> None:
         self.on_move = on_move
@@ -113,12 +106,12 @@ def _runtime(cleared: list[int]) -> tuple[HoverLookupRuntime, _Listeners, _Captu
 
 
 def test_leaving_a_retained_word_dismisses_it_on_the_real_qt_scheduler(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     """The measured failure: no dismissal at all, because the dwell scheduled
     on the way out replaced the exit's callback on the one shared timer."""
 
-    del application
+    del qt_application
     cleared: list[int] = []
     runtime, listeners, _capture = _runtime(cleared)
     try:
@@ -137,9 +130,9 @@ def test_leaving_a_retained_word_dismisses_it_on_the_real_qt_scheduler(
 
 
 def test_a_crossing_to_the_popup_outlives_the_dwell_it_shares_the_moment_with(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
-    del application
+    del qt_application
     cleared: list[int] = []
     runtime, listeners, capture = _runtime(cleared)
     try:
diff --git a/tests/integration/test_lookup_process_spawn.py b/tests/native/shared/test_lookup_process_spawn.py
similarity index 90%
rename from tests/integration/test_lookup_process_spawn.py
rename to tests/native/shared/test_lookup_process_spawn.py
index f2075fe..d835447 100644
--- a/tests/integration/test_lookup_process_spawn.py
+++ b/tests/native/shared/test_lookup_process_spawn.py
@@ -14,11 +14,10 @@ import json
 import os
 import subprocess
 import sys
-from importlib.util import find_spec
 from pathlib import Path
 
-import pytest
-
+from tests.hanly_fixtures import FIXTURE_ASSETS, REPO_ROOT
+from tests.hanly_fixtures.capabilities import require_modules, unavailable
 from tests.hanly_fixtures.process_probe import PROCESS_ROWS_PROGRAM
 
 #: What the shell must never load. Memory a library does not return can only
@@ -149,13 +148,7 @@ if __name__ == "__main__":
 
 def _existing_models() -> Path | None:
     candidates = [
-        Path(__file__).parents[2]
-        / "packages"
-        / "hanly-app"
-        / "src"
-        / "hanly_app"
-        / "assets"
-        / "easyocr_models",
+        REPO_ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "assets" / "easyocr_models",
         Path.home() / ".EasyOCR" / "model",
     ]
     return next(
@@ -171,7 +164,7 @@ def _existing_models() -> Path | None:
 def _existing_dictionary() -> Path | None:
     configured = os.environ.get("HANLY_KRDICT_DB")
     candidates = [Path(configured)] if configured else []
-    candidates.append(Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3")
+    candidates.append(REPO_ROOT / "data" / "generated" / "krdict.sqlite3")
     return next((path for path in candidates if path.is_file()), None)
 
 
@@ -179,18 +172,16 @@ def _requirements() -> tuple[Path, Path, Path]:
     # Presence, not an import: loading the runtime to decide whether to run
     # would put the very libraries this test says the shell never imports into
     # the process running it.
-    missing = [name for name in ("easyocr", "kiwipiepy", "PIL") if find_spec(name) is None]
-    if missing:
-        pytest.skip(f"the lookup runtime is not installed: {', '.join(missing)}")
+    require_modules("easyocr", "kiwipiepy", "PIL")
     dictionary = _existing_dictionary()
     if dictionary is None:
-        pytest.skip("no built KRDICT database; see data/README.md")
+        unavailable("no built KRDICT database; see data/README.md")
     models = _existing_models()
     if models is None:
-        pytest.skip("no prepared EasyOCR weights; see tools/prepare_easyocr_models.py")
-    fixture = Path(__file__).parents[1] / "hanly_fixtures" / "assets" / "korean_reading_roi.png"
+        unavailable("no prepared EasyOCR weights; see tools/prepare_easyocr_models.py")
+    fixture = FIXTURE_ASSETS / "korean_reading_roi.png"
     if not fixture.is_file():
-        pytest.skip("the Korean reading fixture is not available")
+        unavailable("the Korean reading fixture is not available")
     return dictionary, models, fixture
 
 
diff --git a/tests/test_qt_hover_scheduler.py b/tests/native/shared/test_qt_hover_scheduler.py
similarity index 86%
rename from tests/test_qt_hover_scheduler.py
rename to tests/native/shared/test_qt_hover_scheduler.py
index ac4d469..55b926b 100644
--- a/tests/test_qt_hover_scheduler.py
+++ b/tests/native/shared/test_qt_hover_scheduler.py
@@ -5,23 +5,15 @@ from __future__ import annotations
 import threading
 from collections.abc import Callable
 
-import pytest
+from tests.hanly_fixtures.capabilities import require_modules
 
-pytest.importorskip("PyQt6.QtWidgets")
+require_modules("PyQt6.QtWidgets", module_level=True)
 
 from hanly_app.qt_hover_scheduler import QtHoverScheduler  # noqa: E402
-from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
+from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
 from PyQt6.QtWidgets import QApplication  # noqa: E402
 
 
-@pytest.fixture(scope="module")
-def application() -> QApplication:
-    existing = QCoreApplication.instance()
-    if isinstance(existing, QApplication):
-        return existing
-    return QApplication([])
-
-
 def _spin(milliseconds: int) -> None:
     """Run the event loop for a fixed span, to show something never happens."""
 
@@ -55,7 +47,7 @@ def _spin_until(ready: Callable[[], bool], *, timeout_ms: int = 5000) -> bool:
 
 
 def test_scheduled_callback_runs_on_the_qt_thread_without_a_timer_thread(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     scheduler = QtHoverScheduler()
     fired: list[int] = []
@@ -68,7 +60,7 @@ def test_scheduled_callback_runs_on_the_qt_thread_without_a_timer_thread(
     assert threading.active_count() == before
 
 
-def test_cancelled_delay_never_fires(application: QApplication) -> None:
+def test_cancelled_delay_never_fires(qt_application: QApplication) -> None:
     scheduler = QtHoverScheduler()
     fired: list[str] = []
 
@@ -80,7 +72,7 @@ def test_cancelled_delay_never_fires(application: QApplication) -> None:
 
 
 def test_rescheduling_replaces_the_pending_delay_and_reuses_one_timer(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     """Cursor movement reschedules on every event, so the scheduler must
     replace the pending delay rather than accumulate timers."""
@@ -101,7 +93,7 @@ def test_rescheduling_replaces_the_pending_delay_and_reuses_one_timer(
 
 
 def test_cancelling_a_superseded_handle_leaves_the_newer_delay_pending(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     scheduler = QtHoverScheduler()
     fired: list[str] = []
@@ -115,7 +107,7 @@ def test_cancelling_a_superseded_handle_leaves_the_newer_delay_pending(
 
 
 def test_a_dwell_and_a_popup_crossing_do_not_take_each_others_timer(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     """The production defect: one ``QtHoverScheduler`` is one ``QTimer``.
 
@@ -124,7 +116,7 @@ def test_a_dwell_and_a_popup_crossing_do_not_take_each_others_timer(
     answer on screen was never dismissed. Two schedulers are two timers.
     """
 
-    del application
+    del qt_application
     dwell = QtHoverScheduler()
     crossing = QtHoverScheduler()
     fired: list[str] = []
@@ -137,11 +129,11 @@ def test_a_dwell_and_a_popup_crossing_do_not_take_each_others_timer(
 
 
 def test_one_scheduler_still_replaces_its_own_pending_delay(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     """Which is exactly why the exit cannot share the dwell's scheduler."""
 
-    del application
+    del qt_application
     scheduler = QtHoverScheduler()
     fired: list[str] = []
 
diff --git a/tests/test_qt_popup_window.py b/tests/native/shared/test_qt_popup_window.py
similarity index 58%
rename from tests/test_qt_popup_window.py
rename to tests/native/shared/test_qt_popup_window.py
index 72b36b6..e058cd5 100644
--- a/tests/test_qt_popup_window.py
+++ b/tests/native/shared/test_qt_popup_window.py
@@ -9,13 +9,12 @@ top-level window rather than a child of the main window.
 
 from __future__ import annotations
 
-import sys
-from collections.abc import Iterator
-
 import pytest
 from hanly import DictionaryEntry, LookupResult, LookupStatus
 
-pytest.importorskip("PyQt6.QtWidgets")
+from tests.hanly_fixtures.capabilities import require_modules
+
+require_modules("PyQt6.QtWidgets", module_level=True)
 
 from hanly_app.popup import PopupPosition  # noqa: E402
 from hanly_app.qt_popup import QtPopupView  # noqa: E402
@@ -24,21 +23,6 @@ from PyQt6.QtGui import QColor, QPixmap  # noqa: E402
 from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402
 
 
-@pytest.fixture(scope="module")
-def application() -> QApplication:
-    existing = QApplication.instance()
-    if isinstance(existing, QApplication):
-        return existing
-    return QApplication([])
-
-
-@pytest.fixture
-def view(application: QApplication) -> Iterator[QtPopupView]:
-    popup = QtPopupView()
-    yield popup
-    popup.close()
-
-
 def _result() -> LookupResult:
     return LookupResult(
         status=LookupStatus.SUCCESS,
@@ -49,25 +33,25 @@ def _result() -> LookupResult:
 
 
 def test_the_popup_is_a_top_level_window_not_a_control_center_child(
-    view: QtPopupView,
+    popup_view: QtPopupView,
 ) -> None:
-    assert view.parent() is None
-    assert view.isWindow() is True
+    assert popup_view.parent() is None
+    assert popup_view.isWindow() is True
 
 
 def test_the_popup_never_takes_focus_or_activates_the_application(
-    view: QtPopupView,
+    popup_view: QtPopupView,
 ) -> None:
-    flags = view.windowFlags()
+    flags = popup_view.windowFlags()
 
     assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
-    assert view.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
+    assert popup_view.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
 
 
 def test_the_popup_stays_a_frameless_always_on_top_tool_window(
-    view: QtPopupView,
+    popup_view: QtPopupView,
 ) -> None:
-    flags = view.windowFlags()
+    flags = popup_view.windowFlags()
 
     assert flags & Qt.WindowType.FramelessWindowHint
     assert flags & Qt.WindowType.WindowStaysOnTopHint
@@ -75,7 +59,7 @@ def test_the_popup_stays_a_frameless_always_on_top_tool_window(
 
 
 def test_showing_and_updating_still_renders_and_repositions(
-    application: QApplication,
+    qt_application: QApplication,
     monkeypatch: pytest.MonkeyPatch,
 ) -> None:
     """Record the placement asked for, which is the part Hanly decides.
@@ -109,19 +93,19 @@ def test_showing_and_updating_still_renders_and_repositions(
         view.close()
 
 
-def test_hiding_and_closing_the_popup_still_work(view: QtPopupView) -> None:
-    view.show_result(_result(), PopupPosition(10, 10))
+def test_hiding_and_closing_the_popup_still_work(popup_view: QtPopupView) -> None:
+    popup_view.show_result(_result(), PopupPosition(10, 10))
 
-    view.hide()
-    assert view.isVisible() is False
+    popup_view.hide()
+    assert popup_view.isVisible() is False
 
-    view.show_result(_result(), PopupPosition(20, 20))
-    assert view.close() is True
-    assert view.isVisible() is False
+    popup_view.show_result(_result(), PopupPosition(20, 20))
+    assert popup_view.close() is True
+    assert popup_view.isVisible() is False
 
 
 def test_an_explicit_parent_is_still_honoured_for_callers_that_pass_one(
-    application: QApplication,
+    qt_application: QApplication,
 ) -> None:
     """The window contract is about flags, not about forbidding a parent.
 
@@ -139,7 +123,7 @@ def test_an_explicit_parent_is_still_honoured_for_callers_that_pass_one(
         parent.close()
 
 
-def test_the_popup_paints_its_own_panel_background(view: QtPopupView) -> None:
+def test_the_popup_paints_its_own_panel_background(popup_view: QtPopupView) -> None:
     """A translucent widget is cleared to nothing unless it paints itself.
 
     Without the paint handler the popup reached the screen as bare text over
@@ -147,42 +131,11 @@ def test_the_popup_paints_its_own_panel_background(view: QtPopupView) -> None:
     the widget onto a known background runs the same paint path the screen does.
     """
 
-    view.show_result(_result(), PopupPosition(60, 60))
-    canvas = QPixmap(view.size())
+    popup_view.show_result(_result(), PopupPosition(60, 60))
+    canvas = QPixmap(popup_view.size())
     canvas.fill(QColor("white"))
 
-    view.render(canvas)
+    popup_view.render(canvas)
 
-    centre = canvas.toImage().pixelColor(view.width() // 2, view.height() // 2)
+    centre = canvas.toImage().pixelColor(popup_view.width() // 2, popup_view.height() // 2)
     assert centre == QColor("#20252b")
-
-
-@pytest.mark.skipif(sys.platform != "darwin", reason="the panel property is macOS-only")
-def test_the_popup_is_not_withdrawn_when_hanly_loses_focus(
-    application: QApplication, view: QtPopupView
-) -> None:
-    """The regression: AppKit stops compositing a utility panel on deactivation.
-
-    Qt and NSWindow both keep reporting the popup visible while the window
-    server has dropped it, so the property itself is what gets asserted.
-    """
-
-    if application.platformName() != "cocoa":
-        pytest.skip("winId() is an NSView only under the cocoa platform plugin")
-
-    from hanly_app.popup_darwin import hides_when_inactive
-
-    assert hides_when_inactive(int(view.winId())) is False
-
-    # Still false across a show/hide cycle, which is when Qt could have
-    # replaced the native window under the widget.
-    view.show_result(_result(), PopupPosition(60, 60))
-    view.hide()
-    assert hides_when_inactive(int(view.winId())) is False
-
-
-def test_a_widget_with_no_native_window_is_reported_rather_than_crashing() -> None:
-    from hanly_app.popup_darwin import hides_when_inactive, keep_visible_when_inactive
-
-    assert keep_visible_when_inactive(0) is False
-    assert hides_when_inactive(0) is None
diff --git a/tests/native/shared/test_update_handoff_native.py b/tests/native/shared/test_update_handoff_native.py
new file mode 100644
index 0000000..0652c89
--- /dev/null
+++ b/tests/native/shared/test_update_handoff_native.py
@@ -0,0 +1,151 @@
+"""The swap itself, run for real: two compiled builds and the production script.
+
+What the rendered script says is a portable contract and is checked in the
+portable suite. What a shell does with it is not: these cases execute the
+handoff against builds this host compiled, and read back which one answered at
+the installation path afterwards.
+"""
+
+from __future__ import annotations
+
+import os
+import shutil
+import subprocess
+import sys
+from pathlib import Path
+
+import pytest
+
+from tests.hanly_fixtures.update_handoff import (
+    HANDOFF_VARIANTS,
+    assert_identity,
+    prepare_handoff,
+    run_handoff,
+    with_dead_pid,
+)
+
+
+@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
+def test_a_verified_update_replaces_the_installation_and_cleans_up_after_itself(
+    tmp_path: Path, platform: str
+) -> None:
+    handoff = run_handoff(prepare_handoff(tmp_path, platform), expect_status=0)
+    install_root = handoff.transaction.install_root
+
+    assert handoff.await_launched(["new"]) == ["new"]
+    assert install_root.is_dir()
+    # Nothing of the update survives it: no staged build, no backup, no script.
+    assert not handoff.transaction.directory.exists()
+    assert not handoff.script.exists()
+    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]
+
+
+@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
+def test_a_new_build_that_never_reports_starting_gives_the_old_one_back(
+    tmp_path: Path, platform: str
+) -> None:
+    """The swap succeeding is not the update succeeding. A build that installs
+    and then cannot run would otherwise leave the user with nothing, because the
+    only working copy was deleted the moment the rename returned."""
+
+    handoff = run_handoff(prepare_handoff(tmp_path, platform, new_version="9.9.9"), expect_status=1)
+    install_root = handoff.transaction.install_root
+
+    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
+    assert not handoff.transaction.directory.exists()
+    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]
+    assert_identity(handoff, "old")
+
+
+@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
+def test_a_replacement_that_cannot_be_moved_into_place_relaunches_the_old_build(
+    tmp_path: Path, platform: str
+) -> None:
+    handoff = prepare_handoff(tmp_path, platform)
+    shutil.rmtree(handoff.transaction.staged_path)
+
+    run_handoff(handoff, expect_status=1)
+
+    assert handoff.await_launched(["old"]) == ["old"]
+    assert not handoff.transaction.directory.exists()
+    assert_identity(handoff, "old")
+
+
+@pytest.mark.skipif(
+    sys.platform == "win32" or shutil.which("pgrep") is None,
+    reason="this is the POSIX rollback, and pgrep is how it is observed",
+)
+def test_a_rejected_build_that_is_still_running_is_stopped_before_the_posix_restore(
+    tmp_path: Path,
+) -> None:
+    """POSIX renames a directory out from under a running program without
+    complaint, so a rollback that does not stop the rejected build leaves it
+    running out of a directory the handoff then deletes -- beside the restored
+    build it just relaunched."""
+
+    handoff = run_handoff(
+        prepare_handoff(tmp_path, "linux", new_version="9.9.9", linger=60), expect_status=1
+    )
+
+    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
+    # Only the candidate is started with the readiness argument, so this sees
+    # that one process and never the restored build launched beside it.
+    assert not _running(f"update-ready {handoff.transaction.ready_path}")
+    assert_identity(handoff, "old")
+
+
+def _running(pattern: str) -> bool:
+    """Whether any process's command line still matches ``pattern``."""
+
+    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0
+
+
+@pytest.mark.skipif(sys.platform == "win32", reason="the shim replaces a POSIX mv")
+def test_a_rollback_that_itself_fails_launches_nothing_and_keeps_the_backup(
+    tmp_path: Path,
+) -> None:
+    """Neither build is at the installation path, so nothing there is safe to
+    start; the previous one stays under the transaction for a person to restore."""
+
+    handoff = prepare_handoff(tmp_path, sys.platform)
+    shutil.rmtree(handoff.transaction.staged_path)
+    shim = tmp_path / "bin"
+    shim.mkdir()
+    # Fail only the restoring move, so the branch under test is the one that
+    # cannot put the previous build back.
+    (shim / "mv").write_text(
+        f'#!/bin/sh\ncase "$1" in "{handoff.transaction.backup_path}") exit 1 ;; esac\n'
+        'exec /bin/mv "$@"\n',
+        encoding="ascii",
+        newline="\n",
+    )
+    (shim / "mv").chmod(0o755)
+
+    environment = dict(os.environ)
+    environment["PATH"] = f"{shim}{os.pathsep}{environment['PATH']}"
+    finished = subprocess.run(
+        ["/bin/sh", str(handoff.script), *with_dead_pid(handoff)],
+        check=False,
+        capture_output=True,
+        timeout=180,
+        env=environment,
+    )
+
+    assert finished.returncode == 1, finished.stderr.decode("utf-8", "replace")
+    assert handoff.launched == []  # nothing was asked to start, so nothing can arrive
+    assert not handoff.transaction.install_root.exists()
+    assert handoff.transaction.backup_path.is_dir()
+
+
+@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
+def test_an_installation_path_with_spaces_and_non_ascii_survives_the_handoff(
+    tmp_path: Path, platform: str
+) -> None:
+    handoff = run_handoff(
+        prepare_handoff(tmp_path / "한글 프로그램", platform, probe_root=tmp_path / "probe"),
+        expect_status=0,
+    )
+
+    assert "한글 프로그램" in str(handoff.transaction.install_root)
+    assert handoff.await_launched(["new"]) == ["new"]
+    assert_identity(handoff, "new")
diff --git a/tests/native/shared/test_webengine_startup.py b/tests/native/shared/test_webengine_startup.py
new file mode 100644
index 0000000..18d0ab1
--- /dev/null
+++ b/tests/native/shared/test_webengine_startup.py
@@ -0,0 +1,66 @@
+"""Real-process proof that Qt WebEngine starts through the shared application.
+
+Every other Control Center test injects a fake webview, so none of them ever
+initializes Chromium. This one does: it launches a bounded subprocess that
+builds the production ``QApplication`` and loads a document in a real
+``QWebEngineView``. Surviving a few seconds is not the assertion -- the child
+must report a finished load and exit cleanly.
+"""
+
+from __future__ import annotations
+
+import subprocess
+import sys
+from pathlib import Path
+
+from tests.hanly_fixtures.capabilities import require_display, require_modules
+from tests.hanly_fixtures.webengine_probe import (
+    CHILD_TIMEOUT_SECONDS,
+    LOADED_MARKER,
+    run_webengine_child,
+)
+
+#: The ordering the production guard enforces, checked in a process of its own:
+#: ``prepare_control_center_qt`` refuses once a ``QApplication`` exists, so a
+#: run that shares a process with any Qt case asserts nothing about it.
+_PREPARE_PROGRAM = """
+from hanly_app.control_center import prepare_control_center_qt
+
+prepare_control_center_qt()
+
+from PyQt6.QtWidgets import QApplication
+
+print("NO_APPLICATION" if QApplication.instance() is None else "APPLICATION")
+"""
+
+
+def test_the_webengine_backend_is_prepared_before_any_qapplication_exists(
+    tmp_path: Path,
+) -> None:
+    """Preparing the shared pywebview backend must not be what creates the
+    application: the shell owns that, and a backend that made one first would
+    own the event loop too."""
+
+    require_modules("PyQt6.QtWebEngineWidgets", "webview")
+    program = tmp_path / "prepare_child.py"
+    program.write_text(_PREPARE_PROGRAM, encoding="utf-8")
+    child = subprocess.run(
+        [sys.executable, str(program)],
+        capture_output=True,
+        text=True,
+        timeout=CHILD_TIMEOUT_SECONDS,
+        cwd=tmp_path,
+    )
+
+    assert child.returncode == 0, child.stderr
+    assert "NO_APPLICATION" in child.stdout
+
+
+def test_the_shared_application_loads_a_document_in_qt_webengine(tmp_path: Path) -> None:
+    require_modules("PyQt6.QtWebEngineWidgets")
+    require_display()
+
+    child = run_webengine_child(tmp_path, "shared")
+
+    assert child.returncode == 0, f"stdout={child.stdout!r} stderr={child.stderr!r}"
+    assert LOADED_MARKER in child.stdout, f"stderr={child.stderr!r}"
diff --git a/tests/native/windows/__init__.py b/tests/native/windows/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/native/windows/test_update_handoff_windows.py b/tests/native/windows/test_update_handoff_windows.py
new file mode 100644
index 0000000..5a9a591
--- /dev/null
+++ b/tests/native/windows/test_update_handoff_windows.py
@@ -0,0 +1,28 @@
+"""The rollback only Windows needs: a directory it will not rename."""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+from tests.hanly_fixtures.update_handoff import assert_identity, prepare_handoff, run_handoff
+
+
+def test_a_rejected_build_that_is_still_running_is_stopped_before_the_restore(
+    tmp_path: Path,
+) -> None:
+    """A build that comes up and then reports the wrong version is the case the
+    swap has to undo while the new build is still holding the installation
+    directory. Windows refuses to rename that directory until the program
+    started from it is gone, so a rollback that does not stop it first restores
+    nothing and leaves the rejected build installed."""
+
+    handoff = run_handoff(
+        prepare_handoff(tmp_path, "win32", new_version="9.9.9", linger=60), expect_status=1
+    )
+
+    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
+    assert not handoff.transaction.directory.exists()
+    assert [item.name for item in handoff.transaction.install_root.parent.iterdir()] == [
+        handoff.transaction.install_root.name
+    ]
+    assert_identity(handoff, "old")
diff --git a/tests/native/windows/test_webengine_arguments.py b/tests/native/windows/test_webengine_arguments.py
new file mode 100644
index 0000000..8c41f96
--- /dev/null
+++ b/tests/native/windows/test_webengine_arguments.py
@@ -0,0 +1,25 @@
+"""The Windows-only abort Chromium raises when it is handed no program name."""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+from tests.hanly_fixtures.capabilities import require_modules
+from tests.hanly_fixtures.webengine_probe import LOADED_MARKER, run_webengine_child
+
+
+def test_an_empty_argument_list_still_aborts_chromium_on_windows(tmp_path: Path) -> None:
+    """The defect this fix exists for, kept executable rather than anecdotal.
+
+    Only the Windows abort code is asserted here; every other platform asserts
+    the successful contract in the shared suite instead of a native exception
+    number.
+    """
+
+    require_modules("PyQt6.QtWebEngineWidgets")
+
+    child = run_webengine_child(tmp_path, "empty-argv")
+
+    assert child.returncode != 0
+    assert LOADED_MARKER not in child.stdout
+    assert "the program name is not passed" in child.stderr
diff --git a/tests/packaged/__init__.py b/tests/packaged/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/packaged/conftest.py b/tests/packaged/conftest.py
new file mode 100644
index 0000000..982e297
--- /dev/null
+++ b/tests/packaged/conftest.py
@@ -0,0 +1,24 @@
+"""The frozen product's own suite: it needs a built bundle, not a checkout."""
+
+from __future__ import annotations
+
+import sys
+from pathlib import Path
+
+import pytest
+
+HOST_DIRECTORY = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
+SHARED_DIRECTORY = "shared"
+
+_ROOT = Path(__file__).parent
+
+
+def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
+    if collection_path.parent != _ROOT or not collection_path.is_dir():
+        return None
+    return collection_path.name not in (SHARED_DIRECTORY, HOST_DIRECTORY)
+
+
+def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
+    for item in items:
+        item.add_marker("packaged")
diff --git a/tests/packaged/shared/__init__.py b/tests/packaged/shared/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/integration/test_packaged_desktop.py b/tests/packaged/shared/test_packaged_desktop.py
similarity index 86%
rename from tests/integration/test_packaged_desktop.py
rename to tests/packaged/shared/test_packaged_desktop.py
index 6ec0263..fdb1e38 100644
--- a/tests/integration/test_packaged_desktop.py
+++ b/tests/packaged/shared/test_packaged_desktop.py
@@ -4,20 +4,21 @@ This is the only test that runs the produced artifact. It refuses every
 developer fallback -- no repository, no virtual environment, no developer
 model cache -- so a bundle that passes here is one a user could actually run.
 
-It skips when no bundle has been built, and a skip is not a pass: the native
-acceptance matrix in the review handoff records where it really ran.
+It skips when no bundle has been built, and a skip is not a pass -- so the
+build job that exists to run it sets ``HANLY_REQUIRE_PACKAGED`` and turns every
+one of those reasons into a failure.
 """
 
 from __future__ import annotations
 
 import os
-import sys
 from collections.abc import Mapping
 from pathlib import Path
 
-import pytest
 from hanly_app.self_check import SELF_CHECK_MODES
 
+from tests.hanly_fixtures import FIXTURE_ASSETS, REPO_ROOT
+from tests.hanly_fixtures.capabilities import REQUIRE_PACKAGED, require_display, unavailable
 from tools.build_package import PackageLayout, host_platform
 from tools.build_smoke_krdict import build_smoke_krdict
 from tools.smoke_packaged_runtime import (
@@ -27,13 +28,11 @@ from tools.smoke_packaged_runtime import (
     run_packaged_self_check,
 )
 
-ROOT = Path(__file__).parents[2]
-
 #: Points the gate at a bundle outside ``dist/``, such as an extracted release.
 BUNDLE_VARIABLE = "HANLY_PACKAGED_APP"
 
 #: The Korean fixture the frozen OCR stack must actually read.
-FIXTURE_IMAGE = ROOT / "tests" / "hanly_fixtures" / "assets" / "korean_reading_roi.png"
+FIXTURE_IMAGE = FIXTURE_ASSETS / "korean_reading_roi.png"
 
 #: The same bound the harness uses, rather than a second, smaller number: a
 #: cold or memory-pressured machine can take minutes to start Chromium, and a
@@ -45,15 +44,16 @@ def _bundle() -> Path:
     configured = os.environ.get(BUNDLE_VARIABLE)
     if configured:
         return Path(configured).expanduser().resolve()
-    return PackageLayout.for_platform(ROOT, host_platform()).application_directory
+    return PackageLayout.for_platform(REPO_ROOT, host_platform()).application_directory
 
 
 def _require_bundle() -> Path:
     bundle = _bundle()
     if not bundle.is_dir():
-        pytest.skip(
+        unavailable(
             f"no frozen bundle at {bundle}; build one with tools/build_package.py "
-            f"or set {BUNDLE_VARIABLE}"
+            f"or set {BUNDLE_VARIABLE}",
+            required_by=REQUIRE_PACKAGED,
         )
     return bundle
 
@@ -85,7 +85,7 @@ def _executable() -> Path:
     try:
         return _executable_in(bundle)
     except FileNotFoundError:
-        pytest.skip(f"no Hanly executable in {bundle}")
+        unavailable(f"no Hanly executable in {bundle}", required_by=REQUIRE_PACKAGED)
 
 
 def _failures(report: Mapping[str, object]) -> tuple[list[Mapping[str, object]], str]:
@@ -137,10 +137,7 @@ def test_the_frozen_control_center_opens_and_answers_its_own_page(
 
     # A removed mode must fail here rather than quietly become a stale bundle.
     assert "ui" in SELF_CHECK_MODES
-    if sys.platform.startswith("linux") and not (
-        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
-    ):
-        pytest.skip("the frozen window needs a real display session")
+    require_display(required_by=REQUIRE_PACKAGED)
 
     report = run_packaged_self_check(
         _executable(),
@@ -149,9 +146,10 @@ def test_the_frozen_control_center_opens_and_answers_its_own_page(
         timeout=_WINDOW_TIMEOUT_SECONDS,
     )
     if _predates_the_window_check(report):
-        pytest.skip(
+        unavailable(
             f"the bundle at {_bundle()} was built before --self-check ui; "
-            "rebuild it with tools/build_package.py"
+            "rebuild it with tools/build_package.py",
+            required_by=REQUIRE_PACKAGED,
         )
 
     recorded, failures = _failures(report)
diff --git a/tests/test_app_update_handoff.py b/tests/test_app_update_handoff.py
index a825602..00598bd 100644
--- a/tests/test_app_update_handoff.py
+++ b/tests/test_app_update_handoff.py
@@ -1,45 +1,38 @@
-"""The native swap, run for real on the platform it is written for.
+"""What the update handoff script says, before any shell is asked to run it.
 
-A rendered script proves nothing about what a shell does with it. Every test
-below that can execute drives the actual handoff against two tiny programs
-standing in for the old and new builds, and reads back which one was started.
+These are the decisions the renderer makes -- which program each platform
+relaunches, how the previous build outlives the swap, which waits are bounded,
+how paths travel -- and every one of them is checked by reading the rendered
+body. Running that body against real builds is native behavior and lives in
+the native suite.
 """
 
 from __future__ import annotations
 
 import os
-import shutil
-import subprocess
 import sys
-import tempfile
-from dataclasses import dataclass
 from pathlib import Path
-from time import monotonic, sleep
 
 import pytest
-from hanly_app.app_update import APPLICATION_STEM, BUNDLE_NAME
+from hanly_app.app_update import APPLICATION_STEM
 from hanly_app.app_update_handoff import (
     EXIT_WAIT_SECONDS,
     READY_ARGUMENT,
     READY_WAIT_SECONDS,
-    UpdateTransaction,
     _write_handoff_script,
     handoff_arguments,
     render_handoff_script,
     start_handoff,
 )
 
-NEW_VERSION = "0.2.0"
-
-#: Bounded so an unlaunched build fails the test instead of hanging it.
-_LAUNCH_WAIT_SECONDS = 60.0
+from tests.hanly_fixtures.update_handoff import (
+    MACOS_PROGRAM,
+    c_string,
+    transaction_for,
+)
 
-#: What each platform's installation is called, and the program inside it.
+#: What a Windows installation calls the program inside it.
 _WINDOWS_PROGRAM = f"{APPLICATION_STEM}.exe"
-_MACOS_PROGRAM = f"Contents/MacOS/{APPLICATION_STEM}"
-
-#: What the host's own compiler driver calls the program it produces.
-_PROGRAM_SUFFIX = ".exe" if sys.platform == "win32" else ""
 
 
 # --- what the rendered body has to say ---------------------------------------
@@ -90,10 +83,10 @@ def test_macos_relaunches_the_application_and_never_the_program_inside_it() -> N
     """``open`` is what registers the relaunched build with the window server;
     executing the program directly produces a process with no Dock entry."""
 
-    script = render_handoff_script(executable=_MACOS_PROGRAM, platform="darwin")
+    script = render_handoff_script(executable=MACOS_PROGRAM, platform="darwin")
 
     assert '/usr/bin/open "$install" --args' in script
-    assert _MACOS_PROGRAM not in script
+    assert MACOS_PROGRAM not in script
 
 
 @pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@@ -159,10 +152,10 @@ def test_a_windows_path_survives_being_compiled_into_the_probe() -> None:
     and ``\\U`` is not a valid one. This is what failed on the Windows runner
     before the probe's paths were escaped."""
 
-    literal = _c_string(r"C:\Users\runneradmin\AppData\Local\Temp\launched.txt")
+    literal = c_string(r"C:\Users\runneradmin\AppData\Local\Temp\launched.txt")
 
     assert literal == r'"C:\\Users\\runneradmin\\AppData\\Local\\Temp\\launched.txt"'
-    assert _c_string('a "quoted" name') == r'"a \"quoted\" name"'
+    assert c_string('a "quoted" name') == r'"a \"quoted\" name"'
 
 
 def test_a_powershell_handoff_is_written_with_the_bom_and_line_endings_it_needs(
@@ -209,7 +202,7 @@ def test_a_posix_handoff_is_written_executable_without_a_bom(
 
 
 def test_the_script_is_written_outside_the_directory_it_removes(tmp_path: Path) -> None:
-    transaction = _transaction(tmp_path / "install")
+    transaction = transaction_for(tmp_path / "install")
     spawned: list[tuple[list[str], Path]] = []
 
     start_handoff(
@@ -225,526 +218,3 @@ def test_the_script_is_written_outside_the_directory_it_removes(tmp_path: Path)
     assert transaction.directory not in script.parents
     assert directory == script.parent
     assert command[-7:] == handoff_arguments(transaction)
-
-
-# --- and what a shell actually does with it ----------------------------------
-
-
-#: ``LINGER_SECONDS`` is how long the build stays alive after reporting, which
-#: is what makes it a build the handoff has to stop rather than one that has
-#: already let go of the directory it was started from.
-_PROBE_SOURCE = """
-#include <stdio.h>
-#include <string.h>
-#ifdef _WIN32
-#include <windows.h>
-#else
-#include <unistd.h>
-#endif
-
-int main(int argc, char **argv) {
-    FILE *log = fopen(LOG, "a");
-    if (log) { fprintf(log, "%s\\n", IDENTITY); fclose(log); }
-    for (int index = 1; index + 1 < argc; index++) {
-        if (strcmp(argv[index], "--update-ready") == 0) {
-            FILE *ready = fopen(argv[index + 1], "w");
-            if (ready) { fputs(VERSION, ready); fclose(ready); }
-        }
-    }
-#ifdef _WIN32
-    if (LINGER_SECONDS > 0) { Sleep(LINGER_SECONDS * 1000); }
-#else
-    if (LINGER_SECONDS > 0) { sleep(LINGER_SECONDS); }
-#endif
-    return 0;
-}
-"""
-
-
-#: Which handoff variants this host can actually execute. macOS runs its own
-#: and Linux's: the Linux body is plain POSIX shell that execs the program at
-#: the final path, which a macOS host runs identically. Only the ``open``
-#: relaunch is Darwin-specific, and only Windows needs a Windows host.
-_HANDOFF_VARIANTS = ["linux"] if sys.platform != "win32" else ["win32"]
-if sys.platform == "darwin":
-    _HANDOFF_VARIANTS.insert(0, "darwin")
-
-
-@dataclass
-class _Handoff:
-    """One prepared swap, and where its two programs record what happened."""
-
-    transaction: UpdateTransaction
-    log: Path
-    script: Path
-    program: Path
-
-    @property
-    def launched(self) -> list[str]:
-        text = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
-        return text.split()
-
-    def await_launched(self, expected: list[str]) -> list[str]:
-        """Wait out an asynchronous relaunch before reading the record.
-
-        ``open`` returns as soon as it has asked for the application; the
-        handoff does not wait for it either, so neither the script's exit nor
-        its own cleanup means the relaunched build has run yet.
-        """
-
-        deadline = monotonic() + _LAUNCH_WAIT_SECONDS
-        while self.launched != expected and monotonic() < deadline:
-            sleep(0.1)
-        return self.launched
-
-
-def _transaction(
-    install_root: Path,
-    *,
-    version: str = NEW_VERSION,
-    ready_root: Path | None = None,
-) -> UpdateTransaction:
-    directory = install_root.parent / ".hanly-update-probe"
-    directory.mkdir(parents=True, exist_ok=True)
-    return UpdateTransaction(
-        directory=directory,
-        install_root=install_root,
-        staged_path=directory / install_root.name,
-        backup_path=directory / "previous",
-        ready_path=(ready_root or directory) / "ready",
-        version=version,
-    )
-
-
-def _c_string(value: object) -> str:
-    """Quote a value as a C string literal.
-
-    A Windows path is full of backslashes, so a macro expanding to
-    ``"C:\\Users\\runneradmin\\..."`` is a string of escape sequences rather
-    than a path -- and ``\\U`` is not even a valid one, which is how this
-    first failed to compile on the Windows runner.
-    """
-
-    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
-    return f'"{text}"'
-
-
-def _compile(
-    source: Path,
-    program: Path,
-    *,
-    identity: str,
-    version: str,
-    log: Path,
-    linger: int = 0,
-) -> None:
-    """Build one probe beside its source, then put it where it belongs.
-
-    The compiler only ever sees the probe directory, which is ASCII: binutils
-    takes ``argv`` through the Windows ANSI code page, so an output path
-    containing Hangul reaches ``ld`` as ``?? ????`` and cannot be opened.
-    Moving the finished program to an installation path the handoff is
-    supposed to cope with is Python's job, and Python has no such limit.
-    """
-
-    built = source.parent / f"probe-{identity}{_PROGRAM_SUFFIX}"
-    command = [
-        str(_COMPILER),
-        f"-DIDENTITY={_c_string(identity)}",
-        f"-DVERSION={_c_string(version)}",
-        f"-DLINGER_SECONDS={linger}",
-        # Forward slashes: every Windows CRT accepts them, and they leave the
-        # macro with nothing left to escape.
-        f"-DLOG={_c_string(log.as_posix())}",
-        "-o",
-        str(built),
-        str(source),
-    ]
-    finished = subprocess.run(command, capture_output=True, timeout=120)
-    if finished.returncode != 0:
-        # Without this the failure is a bare CalledProcessError and the
-        # compiler's own explanation is thrown away.
-        raise AssertionError(
-            "could not compile the update probe\n"
-            f"command: {' '.join(command)}\n"
-            f"stderr:\n{finished.stderr.decode('utf-8', 'replace')}"
-        )
-
-    program.parent.mkdir(parents=True, exist_ok=True)
-    shutil.copy2(built, program)
-
-
-def _dead_pid() -> str:
-    """Return a pid that has already exited, so the handoff stops waiting."""
-
-    finished = subprocess.Popen([sys.executable, "-c", ""])
-    finished.wait()
-    return str(finished.pid)
-
-
-def _macos_bundle(root: Path) -> None:
-    """Give a bundle the Info.plist LaunchServices refuses to open without."""
-
-    import plistlib
-
-    (root / "Contents").mkdir(parents=True, exist_ok=True)
-    (root / "Contents" / "Info.plist").write_bytes(
-        plistlib.dumps(
-            {
-                "CFBundleExecutable": APPLICATION_STEM,
-                "CFBundleIdentifier": f"io.github.thiagoross1.hanly.probe.{root.parent.name}",
-                "CFBundleName": "Hanly",
-                "CFBundlePackageType": "APPL",
-            }
-        )
-    )
-
-
-def _prepare(
-    tmp_path: Path,
-    platform: str,
-    *,
-    new_version: str = NEW_VERSION,
-    probe_root: Path | None = None,
-    linger: int = 0,
-) -> _Handoff:
-    """Build an old installation, a staged replacement, and the real script.
-
-    ``probe_root`` is where the probe's own two files live: the program's log
-    and the readiness file it writes. It is separate from ``tmp_path`` so the
-    installation under test can carry spaces and Hangul while the C probe --
-    which receives paths through a compile-time macro and an ANSI ``argv`` on
-    Windows -- only ever handles ASCII. What the handoff renames, relaunches
-    and cleans up is still the awkward path.
-    """
-
-    tmp_path.mkdir(parents=True, exist_ok=True)
-    probes = probe_root or tmp_path
-    probes.mkdir(parents=True, exist_ok=True)
-    source = probes / "probe.c"
-    source.write_text(_PROBE_SOURCE, encoding="ascii")
-    log = probes / "launched.txt"
-
-    darwin = platform == "darwin"
-    name = BUNDLE_NAME if darwin else APPLICATION_STEM
-    # The name the layout really carries on this platform, so the swap under
-    # test relaunches exactly what a shipped update would.
-    inside = _MACOS_PROGRAM if darwin else f"{APPLICATION_STEM}{_PROGRAM_SUFFIX}"
-
-    install_root = tmp_path / "install" / name
-    transaction = _transaction(install_root, ready_root=probes)
-    for root, identity, version, stays in (
-        (install_root, "old", "0.1.0", 0),
-        (transaction.staged_path, "new", new_version, linger),
-    ):
-        _compile(
-            source, root / inside, identity=identity, version=version, log=log, linger=stays
-        )
-        if darwin:
-            _macos_bundle(root)
-
-    return _Handoff(
-        transaction,
-        log,
-        _script(tmp_path, executable=inside, platform=platform),
-        install_root / inside,
-    )
-
-
-#: Ten minutes is the right bound for a frozen build on a cold start and the
-#: wrong one for a test, so the two waits are shortened in the copy that runs
-#: here. Their presence in the shipped body is asserted separately above.
-def _script(tmp_path: Path, *, executable: str, platform: str) -> Path:
-    body = render_handoff_script(executable=executable, platform=platform)
-    for bound in (EXIT_WAIT_SECONDS, READY_WAIT_SECONDS):
-        assert body.count(str(bound)) == 1, body
-        body = body.replace(str(bound), "8")
-
-    # The production writer owns encoding, line endings and mode. Restating
-    # them here would let this suite stay green while the real one regressed.
-    return _write_handoff_script(body, platform=platform, directory=tmp_path)
-
-
-def _run(handoff: _Handoff, *, expect_status: int) -> _Handoff:
-    launcher = (
-        [
-            "powershell.exe",
-            "-NoProfile",
-            "-NonInteractive",
-            "-ExecutionPolicy",
-            "Bypass",
-            "-File",
-        ]
-        if handoff.script.suffix == ".ps1"
-        else ["/bin/sh"]
-    )
-    arguments = handoff_arguments(handoff.transaction)
-    arguments[0] = _dead_pid()
-    finished = subprocess.run(
-        [*launcher, str(handoff.script), *arguments],
-        check=False,
-        capture_output=True,
-        timeout=180,
-        cwd=handoff.script.parent,
-    )
-
-    assert finished.returncode == expect_status, finished.stderr.decode("utf-8", "replace")
-    return handoff
-
-
-def _builds_programs(compiler: str) -> bool:
-    """Answer whether a compiler on PATH can in fact produce a program.
-
-    Being on PATH is not the same as working: an MSYS2 ``cc`` whose ``cc1``
-    cannot load its own libraries exits non-zero with an empty stderr, which
-    would otherwise fail every test below with nothing to go on.
-    """
-
-    with tempfile.TemporaryDirectory() as directory:
-        source = Path(directory) / "usable.c"
-        source.write_text("int main(void) { return 0; }\n", encoding="ascii")
-        try:
-            finished = subprocess.run(
-                [compiler, "-o", str(source.with_suffix(_PROGRAM_SUFFIX or ".out")), str(source)],
-                capture_output=True,
-                timeout=120,
-            )
-        except OSError:
-            return False
-    return finished.returncode == 0
-
-
-#: The two builds being swapped are compiled rather than scripted: macOS
-#: refuses to ``open`` a bundle whose executable is a shell script, and Windows
-#: needs a real executable to ``Start-Process``. Named explicitly so a host
-#: without a working one skips with a reason instead of failing on a missing
-#: or broken ``cc``.
-_COMPILER = next(
-    (
-        found
-        for name in ("cc", "clang", "gcc")
-        if (found := shutil.which(name)) and _builds_programs(found)
-    ),
-    None,
-)
-
-_native = pytest.mark.skipif(
-    _COMPILER is None,
-    reason="the handoff test compiles the builds it swaps; no cc, clang, or gcc on PATH",
-)
-
-
-@_native
-@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
-def test_a_verified_update_replaces_the_installation_and_cleans_up_after_itself(
-    tmp_path: Path, platform: str
-) -> None:
-    handoff = _run(_prepare(tmp_path, platform), expect_status=0)
-    install_root = handoff.transaction.install_root
-
-    assert handoff.await_launched(["new"]) == ["new"]
-    assert install_root.is_dir()
-    # Nothing of the update survives it: no staged build, no backup, no script.
-    assert not handoff.transaction.directory.exists()
-    assert not handoff.script.exists()
-    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]
-
-
-@_native
-@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
-def test_a_new_build_that_never_reports_starting_gives_the_old_one_back(
-    tmp_path: Path, platform: str
-) -> None:
-    """The swap succeeding is not the update succeeding. A build that installs
-    and then cannot run would otherwise leave the user with nothing, because the
-    only working copy was deleted the moment the rename returned."""
-
-    handoff = _run(_prepare(tmp_path, platform, new_version="9.9.9"), expect_status=1)
-    install_root = handoff.transaction.install_root
-
-    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
-    assert not handoff.transaction.directory.exists()
-    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]
-    _assert_identity(handoff, "old")
-
-
-@_native
-@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
-def test_a_replacement_that_cannot_be_moved_into_place_relaunches_the_old_build(
-    tmp_path: Path, platform: str
-) -> None:
-    handoff = _prepare(tmp_path, platform)
-    shutil.rmtree(handoff.transaction.staged_path)
-
-    _run(handoff, expect_status=1)
-
-    assert handoff.await_launched(["old"]) == ["old"]
-    assert not handoff.transaction.directory.exists()
-    _assert_identity(handoff, "old")
-
-
-@pytest.mark.skipif(
-    sys.platform != "win32",
-    reason="only Windows refuses to rename a directory a running program was started from",
-)
-@_native
-def test_a_rejected_build_that_is_still_running_is_stopped_before_the_restore(
-    tmp_path: Path,
-) -> None:
-    """A build that comes up and then reports the wrong version is the case the
-    swap has to undo while the new build is still holding the installation
-    directory. Windows refuses to rename that directory until the program
-    started from it is gone, so a rollback that does not stop it first restores
-    nothing and leaves the rejected build installed."""
-
-    handoff = _run(
-        _prepare(tmp_path, "win32", new_version="9.9.9", linger=60), expect_status=1
-    )
-
-    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
-    assert not handoff.transaction.directory.exists()
-    assert [item.name for item in handoff.transaction.install_root.parent.iterdir()] == [
-        handoff.transaction.install_root.name
-    ]
-    _assert_identity(handoff, "old")
-
-
-@pytest.mark.skipif(
-    sys.platform == "win32" or shutil.which("pgrep") is None,
-    reason="this is the POSIX rollback, and pgrep is how it is observed",
-)
-@_native
-def test_a_rejected_build_that_is_still_running_is_stopped_before_the_posix_restore(
-    tmp_path: Path,
-) -> None:
-    """POSIX renames a directory out from under a running program without
-    complaint, so a rollback that does not stop the rejected build leaves it
-    running out of a directory the handoff then deletes -- beside the restored
-    build it just relaunched."""
-
-    handoff = _run(
-        _prepare(tmp_path, "linux", new_version="9.9.9", linger=60), expect_status=1
-    )
-
-    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
-    # Only the candidate is started with the readiness argument, so this sees
-    # that one process and never the restored build launched beside it.
-    assert not _running(f"update-ready {handoff.transaction.ready_path}")
-    _assert_identity(handoff, "old")
-
-
-def _running(pattern: str) -> bool:
-    """Whether any process's command line still matches ``pattern``."""
-
-    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0
-
-
-@pytest.mark.skipif(sys.platform != "darwin", reason="this is the macOS rollback")
-@_native
-def test_a_rejected_macos_build_is_stopped_from_a_path_full_of_metacharacters(
-    tmp_path: Path,
-) -> None:
-    """``open`` returns no pid, so macOS finds the candidate by the path it runs
-    from -- and an installation path is text a person chose, not a pattern. Read
-    as a regular expression, ``C++ apps`` does not compile and ``[beta]`` is a
-    character class, so the candidate is silently never matched and survives the
-    rollback that deletes the directory underneath it."""
-
-    handoff = _run(
-        _prepare(
-            tmp_path / "C++ apps [beta]",
-            "darwin",
-            new_version="9.9.9",
-            linger=60,
-            probe_root=tmp_path / "probe",
-        ),
-        expect_status=1,
-    )
-
-    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
-    # Only the candidate is started with the readiness argument, so this sees
-    # that one process and never the restored build launched beside it.
-    assert not _running_with(str(handoff.transaction.ready_path))
-    assert not handoff.transaction.directory.exists()
-    _assert_identity(handoff, "old")
-
-
-def _running_with(argument: str) -> bool:
-    """Whether any process still carries ``argument`` on its command line.
-
-    Compared as literal text rather than handed to ``pgrep -f``: the paths this
-    checks are exactly the ones a regular expression would misread.
-    """
-
-    listing = subprocess.run(
-        ["/bin/ps", "-axww", "-o", "args="], capture_output=True, text=True
-    ).stdout
-    return any(argument in line for line in listing.splitlines())
-
-
-@pytest.mark.skipif(sys.platform == "win32", reason="the shim replaces a POSIX mv")
-@_native
-def test_a_rollback_that_itself_fails_launches_nothing_and_keeps_the_backup(
-    tmp_path: Path,
-) -> None:
-    """Neither build is at the installation path, so nothing there is safe to
-    start; the previous one stays under the transaction for a person to restore."""
-
-    handoff = _prepare(tmp_path, sys.platform)
-    shutil.rmtree(handoff.transaction.staged_path)
-    shim = tmp_path / "bin"
-    shim.mkdir()
-    # Fail only the restoring move, so the branch under test is the one that
-    # cannot put the previous build back.
-    (shim / "mv").write_text(
-        f'#!/bin/sh\ncase "$1" in "{handoff.transaction.backup_path}") exit 1 ;; esac\n'
-        'exec /bin/mv "$@"\n',
-        encoding="ascii",
-        newline="\n",
-    )
-    (shim / "mv").chmod(0o755)
-
-    environment = dict(os.environ)
-    environment["PATH"] = f"{shim}{os.pathsep}{environment['PATH']}"
-    finished = subprocess.run(
-        ["/bin/sh", str(handoff.script), *_with_dead_pid(handoff)],
-        check=False,
-        capture_output=True,
-        timeout=180,
-        env=environment,
-    )
-
-    assert finished.returncode == 1, finished.stderr.decode("utf-8", "replace")
-    assert handoff.launched == []  # nothing was asked to start, so nothing can arrive
-    assert not handoff.transaction.install_root.exists()
-    assert handoff.transaction.backup_path.is_dir()
-
-
-@_native
-@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
-def test_an_installation_path_with_spaces_and_non_ascii_survives_the_handoff(
-    tmp_path: Path, platform: str
-) -> None:
-    handoff = _run(
-        _prepare(tmp_path / "한글 프로그램", platform, probe_root=tmp_path / "probe"),
-        expect_status=0,
-    )
-
-    assert "한글 프로그램" in str(handoff.transaction.install_root)
-    assert handoff.await_launched(["new"]) == ["new"]
-    _assert_identity(handoff, "new")
-
-
-def _with_dead_pid(handoff: _Handoff) -> list[str]:
-    arguments = handoff_arguments(handoff.transaction)
-    arguments[0] = _dead_pid()
-    return arguments
-
-
-def _assert_identity(handoff: _Handoff, expected: str) -> None:
-    """Run whatever is at the installation path and see which build answers."""
-
-    before = len(handoff.launched)
-    subprocess.run([str(handoff.program)], check=True, timeout=60)
-
-    assert handoff.launched[before:] == [expected]
diff --git a/tests/test_ci_workflows.py b/tests/test_ci_workflows.py
index 2201d96..18ccb52 100644
--- a/tests/test_ci_workflows.py
+++ b/tests/test_ci_workflows.py
@@ -147,23 +147,39 @@ def test_desktop_build_runs_only_manually_or_for_release_tags() -> None:
     assert "branches" not in triggers.get("push", {})
 
 
-def test_build_runs_repository_gates_before_producing_an_artifact() -> None:
+def test_the_packaging_job_owns_the_product_and_nothing_ci_already_owns() -> None:
+    """Three packaging jobs used to rerun the whole portable suite, the lint,
+    and the type check with the runtime installed -- three more full runs of
+    what `ci.yml` had already proved, on the slowest machines in the project."""
+
     commands = [step.get("run", "") for step in _steps(_workflow("build.yml"), "build")]
     joined = "\n".join(commands)
 
     assert 'python -m pip install --editable "packages/hanly-app[runtime]"' in joined
-    assert "python -m pytest" in joined
-    assert "python -m ruff check packages packaging tests tools benchmarks" in joined
-    assert "python -m mypy packages packaging tests tools benchmarks" in joined
+    assert "--suite portable" not in joined
+    assert "ruff check" not in joined
+    assert "mypy" not in joined
 
-    gates = [index for index, command in enumerate(commands) if "python -m pytest" in command]
+    # What it does own: the frozen product, checked after it exists.
+    packaged = [index for index, command in enumerate(commands) if "--suite packaged" in command]
     builds = [index for index, command in enumerate(commands) if "build_package.py" in command]
-    assert gates and builds and max(gates) < min(builds)
+    assert packaged and builds and min(packaged) > max(builds)
+
+
+def test_the_packaged_gate_cannot_pass_by_skipping_itself() -> None:
+    """The bundle it needs is the artifact this job produced, so "no bundle" is
+    a failure of the job rather than a machine this one does not have."""
+
+    step = _step(_workflow("build.yml"), "build", step_id="packaged_tests")
+
+    assert step["env"]["HANLY_REQUIRE_PACKAGED"] == "1"
+    assert step["env"]["HANLY_PACKAGED_APP"] == "${{ env.SMOKE_APP }}"
+    assert "xvfb-run" in step["run"], "the frozen window needs a display on Linux"
 
 
 @pytest.mark.parametrize(
     ("workflow_name", "job_name"),
-    [("ci.yml", "quality"), ("ci.yml", "windows-tests"), ("build.yml", "build")],
+    [("ci.yml", "quality"), ("ci.yml", "native"), ("build.yml", "build")],
 )
 def test_every_pytest_job_declares_the_node_runtime_used_by_browser_tests(
     workflow_name: str, job_name: str
@@ -589,24 +605,46 @@ def test_release_lane_actions_are_pinned_to_immutable_commits(name: str) -> None
         assert re.search(r"#\s*v\d+\.\d+\.\d+", trailer), (name, reference)
 
 
-def test_every_push_is_checked_on_windows_without_renaming_the_linux_gates() -> None:
-    """A POSIX-only assumption in a test is invisible on a Linux-only matrix
-    until a tag build runs it. The Linux job keeps its name because required
-    status checks are pinned to it, so Windows arrives as its own job."""
+def test_the_portable_matrix_keeps_its_name_and_stays_free_of_the_runtime() -> None:
+    """Required status checks are pinned to this job's name, and its whole
+    point is a machine with none of the desktop runtime installed."""
 
     workflow = _workflow("ci.yml")
     quality = workflow["jobs"]["quality"]
-    windows = workflow["jobs"]["windows-tests"]
+    commands = "\n".join(step.get("run", "") for step in _steps(workflow, "quality"))
 
     assert quality["name"] == "quality (py${{ matrix.python-version }})"
     assert quality["runs-on"] == "ubuntu-latest"
-    assert windows["runs-on"] == "windows-latest"
     assert "push" in _triggers(workflow)
+    assert "python -m pytest --suite portable" in commands
+    assert "[runtime]" not in commands
+
+
+def test_every_platform_that_can_run_native_cases_has_a_job_that_does() -> None:
+    """A POSIX-only assumption is invisible on a Linux-only matrix until a tag
+    build runs it, and a macOS-only one was invisible everywhere."""
+
+    native = _workflow("ci.yml")["jobs"]["native"]
+    runners = [entry["runner"] for entry in native["strategy"]["matrix"]["include"]]
+    commands = "\n".join(step.get("run", "") for step in _steps(_workflow("ci.yml"), "native"))
+
+    assert native["strategy"]["fail-fast"] is False
+    assert runners == ["windows-latest", "macos-latest", "ubuntu-latest"]
+    assert "needs" not in native, "a native job waits for no other platform"
+    # The real runtime, the real weights, and a real dictionary: without all
+    # three these cases would have nothing to exercise but their own skips.
+    assert 'python -m pip install --editable "packages/hanly-app[runtime]"' in commands
+    assert "tools/prepare_easyocr_models.py" in commands
+    assert "tools/build_smoke_krdict.py" in commands
+    assert "python -m pytest --suite native" in commands
+    assert "xvfb-run" in commands
+
+
+def test_a_native_job_that_cannot_run_its_cases_fails_instead_of_skipping() -> None:
+    """Every capability is installed by the job itself, so a skip here would be
+    a green run reporting that it checked the thing it did not check."""
 
-    commands = "\n".join(step.get("run", "") for step in _steps(workflow, "windows-tests"))
-    assert "python -m pip install --group dev" in commands
-    assert "python -m pip install --editable packages/hanly-app" in commands
-    assert "python -m pytest" in commands
+    assert _workflow("ci.yml")["jobs"]["native"]["env"]["HANLY_REQUIRE_NATIVE"] == "1"
 
 
 @pytest.mark.parametrize(
diff --git a/tests/test_control_center.py b/tests/test_control_center.py
index 01c40ea..d14c743 100644
--- a/tests/test_control_center.py
+++ b/tests/test_control_center.py
@@ -269,20 +269,6 @@ def test_bridge_validates_region_and_monitor_target_choices(tmp_path: Path) -> N
         bridge.set_region({"left": 0, "top": 0, "width": 0, "height": 600})
 
 
-def test_qt_webengine_is_prepared_before_qapplication_creation() -> None:
-    """The shared pywebview backend must load before Qt creates its app."""
-
-    pytest.importorskip("PyQt6")
-    import hanly_app.control_center as control_center
-
-    assert hasattr(control_center, "prepare_control_center_qt")
-    control_center.prepare_control_center_qt()
-
-    from PyQt6.QtWidgets import QApplication
-
-    assert QApplication.instance() is None
-
-
 def test_control_center_assets_are_packaged_and_have_no_provider_logic() -> None:
     assets = load_control_center_assets()
 
diff --git a/tests/test_dev_dependencies.py b/tests/test_dev_dependencies.py
index dc26c53..32f322c 100644
--- a/tests/test_dev_dependencies.py
+++ b/tests/test_dev_dependencies.py
@@ -1,10 +1,13 @@
-"""The test suite must run in the environment CI actually builds.
+"""Each suite must run in the environment its own CI job actually builds.
 
-CI installs the root ``dev`` dependency group and the two packages without
-extras, while a developer machine carries the whole desktop runtime. A test
-that reaches a library present only locally passes here and fails there, so
-every third-party module the suite touches is either declared in that group
-or acquired through a ``pytest.importorskip`` that precedes it.
+The portable job installs the root ``dev`` dependency group and the two
+packages without extras, while a developer machine carries the whole desktop
+runtime. A portable test that reaches a library present only locally passes
+here and fails there, so every third-party module it touches is either declared
+in that group or acquired through a ``pytest.importorskip`` that precedes it.
+
+The native and packaged jobs install the ``runtime`` extra on purpose, so their
+cases may reach it -- and nothing beyond it.
 """
 
 from __future__ import annotations
@@ -19,8 +22,26 @@ import pytest
 ROOT = Path(__file__).parents[1]
 TEST_ROOTS = (ROOT / "tests", ROOT / "benchmarks" / "dev" / "tests")
 
+#: The suites whose own job installs the desktop runtime extra.
+RUNTIME_SUITES = (ROOT / "tests" / "native", ROOT / "tests" / "packaged")
+
+#: Where the extra those jobs install is declared.
+_APP_PYPROJECT = ROOT / "packages" / "hanly-app" / "pyproject.toml"
+
+#: Locates ``runtime = [...]`` in the app project, read the same way.
+_RUNTIME_EXTRA = re.compile(r"^runtime\s*=\s*(\[.*?^\])", re.DOTALL | re.MULTILINE)
+
 #: Distributions whose importable name differs from the name pip installs.
-_IMPORT_NAMES = {"pillow": "PIL", "pyyaml": "yaml"}
+_IMPORT_NAMES = {
+    "pillow": "PIL",
+    "pyyaml": "yaml",
+    "pywebview": "webview",
+    "hanly": "hanly",
+}
+
+#: Installed by the runtime extra as transitive dependencies, and imported by
+#: name rather than through the distribution that pulls them in.
+_RUNTIME_TRANSITIVE = frozenset({"easyocr", "kiwipiepy", "torch", "numpy"})
 
 #: Reached through the repository root on pytest's ``pythonpath``, not pip.
 _FIRST_PARTY = frozenset({"benchmarks", "hanly", "hanly_app", "tests", "tools"})
@@ -61,7 +82,22 @@ def _dev_requirements() -> list[str]:
 def _declared_modules() -> set[str]:
     """Import names the root dev dependency group makes available."""
 
-    names = (re.split(r"[<>=!~\[;\s]", line, maxsplit=1)[0] for line in _dev_requirements())
+    return _import_names(_dev_requirements())
+
+
+def _runtime_modules() -> set[str]:
+    """Import names the desktop runtime extra makes available."""
+
+    block = _RUNTIME_EXTRA.search(_APP_PYPROJECT.read_text(encoding="utf-8"))
+    assert block is not None, "hanly-app declares no runtime extra"
+    requirements = ast.literal_eval(block.group(1))
+
+    assert requirements, "the runtime extra is empty"
+    return _import_names(requirements) | set(_RUNTIME_TRANSITIVE)
+
+
+def _import_names(requirements: list[str]) -> set[str]:
+    names = (re.split(r"[<>=!~\[;\s]", line, maxsplit=1)[0] for line in requirements)
     return {_IMPORT_NAMES.get(name.lower(), name) for name in names if name}
 
 
@@ -158,16 +194,38 @@ def _test_modules() -> list[Path]:
 
 def test_every_library_the_suite_reaches_is_declared_or_skippable() -> None:
     declared = _declared_modules()
+    with_runtime = declared | _runtime_modules()
 
     for path in _test_modules():
-        undeclared = _undeclared_modules(path.read_text(encoding="utf-8"), declared)
+        available = with_runtime if _needs_the_runtime(path) else declared
+        undeclared = _undeclared_modules(path.read_text(encoding="utf-8"), available)
         assert not undeclared, (
-            f"{path.relative_to(ROOT)} reaches {sorted(undeclared)}, which CI does "
-            "not install; add it to the root dev dependency group or acquire it "
-            "with pytest.importorskip"
+            f"{path.relative_to(ROOT)} reaches {sorted(undeclared)}, which its CI "
+            "job does not install; add it to the root dev dependency group or "
+            "acquire it with pytest.importorskip"
         )
 
 
+def _needs_the_runtime(path: Path) -> bool:
+    """Whether this module belongs to a suite whose job installs the extra."""
+
+    return any(suite == path or suite in path.parents for suite in RUNTIME_SUITES)
+
+
+def test_a_portable_module_may_not_reach_the_desktop_runtime() -> None:
+    """This is the rule the portable matrix exists to keep: four Python
+    versions on a machine with no Qt, no Torch, and no display."""
+
+    declared = _declared_modules()
+
+    assert "PyQt6" not in declared
+    assert "torch" not in declared
+    for path in _test_modules():
+        if _needs_the_runtime(path):
+            continue
+        assert not _undeclared_modules(path.read_text(encoding="utf-8"), declared)
+
+
 def test_an_importorskip_below_an_import_does_not_excuse_it() -> None:
     """The import runs first and fails collection, so the guard never sees it."""
 
diff --git a/tests/test_lookup_process.py b/tests/test_lookup_process.py
index 1f6a302..e56a667 100644
--- a/tests/test_lookup_process.py
+++ b/tests/test_lookup_process.py
@@ -3,7 +3,7 @@
 These run the real child body on a thread over a real pipe, so the transport,
 the reader/processing split, cancellation, and generation handling are the
 production ones. The process boundary itself is covered by
-``tests/integration/test_lookup_process_spawn.py``.
+``tests/native/shared/test_lookup_process_spawn.py``.
 """
 
 from __future__ import annotations
diff --git a/tests/test_popup.py b/tests/test_popup.py
index 21f5f0b..cb0dd43 100644
--- a/tests/test_popup.py
+++ b/tests/test_popup.py
@@ -233,3 +233,14 @@ def test_clear_hides_the_popup_and_drops_the_result_it_was_showing() -> None:
     assert controller.visible is False
     assert controller.result is None
     assert [name for name, _, _ in events][-1] == "hide"
+
+
+def test_a_widget_with_no_native_window_is_reported_rather_than_crashing() -> None:
+    """The adapter answers for a pointer of zero without loading a runtime, so
+    a caller that ran before the native window existed gets a value, not an
+    Objective-C message to nothing."""
+
+    from hanly_app.popup_darwin import hides_when_inactive, keep_visible_when_inactive
+
+    assert keep_visible_when_inactive(0) is False
+    assert hides_when_inactive(0) is None
diff --git a/tests/test_suite_routing.py b/tests/test_suite_routing.py
new file mode 100644
index 0000000..e2c00b4
--- /dev/null
+++ b/tests/test_suite_routing.py
@@ -0,0 +1,178 @@
+"""What each suite selection collects, and what it refuses to import.
+
+A portable job runs on a machine with none of the desktop runtime; a native job
+runs on a machine that has it and a window server; the packaged job runs a
+frozen product. Selecting the wrong thing is not a failure anyone would notice
+-- it is a green run that proved less than it looked like it did.
+"""
+
+from __future__ import annotations
+
+import json
+import os
+import subprocess
+import sys
+from pathlib import Path
+
+import pytest
+
+from tests.hanly_fixtures import REPO_ROOT
+from tests.hanly_fixtures.capabilities import REQUIRE_NATIVE, unavailable
+
+#: pytest raises these rather than exporting them under a usable name.
+Failed = pytest.fail.Exception
+Skipped = pytest.skip.Exception
+
+NATIVE_ROOT = REPO_ROOT / "tests" / "native"
+PACKAGED_ROOT = REPO_ROOT / "tests" / "packaged"
+
+#: What a portable run must never have loaded. Importing any of these is a
+#: machine requirement the portable matrix does not meet.
+DESKTOP_MODULES = (
+    "PyQt6",
+    "PyQt6.QtWidgets",
+    "PyQt6.QtWebEngineWidgets",
+    "webview",
+    "easyocr",
+    "torch",
+    "kiwipiepy",
+    "pynput",
+    "mss",
+)
+
+#: Written to a temporary file and loaded with ``-p``: the modules a collection
+#: pulled in are only visible from inside the process that collected them.
+_REPORTER = """
+import json
+import os
+import sys
+
+FORBIDDEN = {forbidden!r}
+REPORT = {report!r}
+
+
+def pytest_collection_finish(session):
+    loaded = sorted(name for name in FORBIDDEN if name in sys.modules)
+    collected = [item.nodeid for item in session.items]
+    with open(REPORT, "w", encoding="utf-8") as stream:
+        json.dump({{"loaded": loaded, "collected": collected}}, stream)
+"""
+
+
+def _collect(tmp_path: Path, suite: str) -> dict[str, list[str]]:
+    """Collect one suite in a clean process and report what it loaded."""
+
+    report = tmp_path / "report.json"
+    plugin = tmp_path / "suite_reporter.py"
+    plugin.write_text(
+        _REPORTER.format(forbidden=DESKTOP_MODULES, report=str(report)), encoding="utf-8"
+    )
+    finished = subprocess.run(
+        [
+            sys.executable,
+            "-m",
+            "pytest",
+            "--suite",
+            suite,
+            "--collect-only",
+            "-q",
+            "-p",
+            "no:cacheprovider",
+            "-p",
+            "suite_reporter",
+        ],
+        cwd=REPO_ROOT,
+        capture_output=True,
+        text=True,
+        timeout=300,
+        env={**_child_environment(), "PYTHONPATH": str(tmp_path)},
+    )
+    assert report.is_file(), f"stdout={finished.stdout[-4000:]}\nstderr={finished.stderr[-4000:]}"
+    return json.loads(report.read_text(encoding="utf-8"))
+
+
+def _child_environment() -> dict[str, str]:
+    environment = dict(os.environ)
+    environment.pop("PYTHONPATH", None)
+    return environment
+
+
+def test_the_portable_suite_imports_none_of_the_desktop_runtime(tmp_path: Path) -> None:
+    """This is what lets the portable matrix run four Python versions on a
+    machine with no display and no multi-gigabyte runtime installed."""
+
+    report = _collect(tmp_path, "portable")
+
+    assert report["loaded"] == []
+    assert report["collected"]
+    assert not any(
+        node.startswith(("tests/native/", "tests/packaged/")) for node in report["collected"]
+    )
+
+
+def test_the_native_suite_is_the_shared_cases_plus_this_host_s_own(
+    tmp_path: Path,
+) -> None:
+    report = _collect(tmp_path, "native")
+    directories = {node.split("/")[2] for node in report["collected"]}
+
+    assert all(node.startswith("tests/native/") for node in report["collected"])
+    assert "shared" in directories
+    assert directories <= {"shared", _host_directory()}
+
+
+def test_the_packaged_suite_is_only_the_frozen_product(tmp_path: Path) -> None:
+    report = _collect(tmp_path, "packaged")
+
+    assert report["collected"]
+    assert all(node.startswith("tests/packaged/") for node in report["collected"])
+
+
+def test_another_platform_s_adapters_are_never_imported_on_this_host() -> None:
+    """A marker cannot do this: deselection happens after the import, and these
+    modules import the adapter of an operating system that is not here."""
+
+    foreign = [
+        directory
+        for directory in NATIVE_ROOT.iterdir()
+        if directory.is_dir() and directory.name not in ("shared", _host_directory(), "__pycache__")
+    ]
+
+    assert foreign, "no other platform's directory to check against"
+    for directory in foreign:
+        assert list(directory.glob("test_*.py")), f"{directory.name} holds no cases"
+
+
+def test_every_native_directory_that_exists_holds_cases() -> None:
+    """An empty suite is a gate that passes because it asked nothing."""
+
+    for root in (NATIVE_ROOT, PACKAGED_ROOT):
+        for directory in root.iterdir():
+            if not directory.is_dir() or directory.name == "__pycache__":
+                continue
+            assert list(directory.glob("test_*.py")), f"{directory} holds no cases"
+
+
+def test_a_missing_capability_fails_the_job_that_exists_to_exercise_it(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Otherwise a native runner without a display is a green run proving
+    nothing, which is the only way this whole separation can be wasted."""
+
+    monkeypatch.setenv(REQUIRE_NATIVE, "1")
+
+    with pytest.raises(Failed, match="no display"):
+        unavailable("no display")
+
+
+def test_the_same_capability_only_skips_an_ordinary_developer_run(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    monkeypatch.delenv(REQUIRE_NATIVE, raising=False)
+
+    with pytest.raises(Skipped, match="no display"):
+        unavailable("no display")
+
+
+def _host_directory() -> str:
+    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
`````

### 8.3 `ce94fe4` — fix: validate packaged artifact identity

`````diff
diff --git a/.github/workflows/build.yml b/.github/workflows/build.yml
index 54f8b7c..d786a08 100644
--- a/.github/workflows/build.yml
+++ b/.github/workflows/build.yml
@@ -96,6 +96,14 @@ jobs:
           --with-torch
           --output "dist/reports/hanly-host-runtime-${{ matrix.platform }}.json"
 
+      # What every product of this run has to report for itself afterwards.
+      # A bundle that works and cannot name the source that produced it is not
+      # release evidence, however green the rest of the job is.
+      - name: Resolve the product version this build must carry
+        id: source_version
+        shell: bash
+        run: echo "SOURCE_VERSION=$(python tools/release_version.py)" >> "$GITHUB_ENV"
+
       # A tag push is the release identity, so the tag and the product
       # version must agree before any artifact is produced under that name.
       - name: Verify the tag matches the product version
@@ -191,6 +199,7 @@ jobs:
             "$SMOKE_APP" \
             --image tests/hanly_fixtures/assets/korean_reading_roi.png \
             --krdict "$RUNNER_TEMP/hanly-smoke-krdict/krdict.sqlite3" \
+            --expect-version "$SOURCE_VERSION" \
             > "$report.json" 2> "$report.err" || status=$?
           cat "$report.json"
           tail -c 200000 "$report.err" >&2
@@ -266,6 +275,7 @@ jobs:
           RUNNER_PLATFORM: ${{ matrix.platform }}
           RUNNER_OS_NAME: ${{ runner.os }}
           RUNNER_ARCHITECTURE: ${{ runner.arch }}
+          BUILD_COMMIT: ${{ github.sha }}
         run: |
           set -euo pipefail
           mkdir -p dist/reports
@@ -292,6 +302,10 @@ jobs:
           json.dump(
               {
                   "platform": os.environ["RUNNER_PLATFORM"],
+                  # An archive hash says two downloads are the same file. Only
+                  # these say which source the file was made from.
+                  "build_commit": os.environ["BUILD_COMMIT"],
+                  "source_version": os.environ["SOURCE_VERSION"],
                   "runner_os": os.environ["RUNNER_OS_NAME"],
                   "runner_arch": os.environ["RUNNER_ARCHITECTURE"],
                   "os_version": platform.platform(),
diff --git a/packaging/README.md b/packaging/README.md
index 4618a06..a8f8284 100644
--- a/packaging/README.md
+++ b/packaging/README.md
@@ -179,6 +179,30 @@ python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --window-onl
 Mounting is not the disk-image check: a DMG that opens onto something other
 than `Hanly.app` fails, because that is the download a person would find empty.
 
+### Which source the bundle came from
+
+A stale bundle passes every check it ever passed. Working is therefore not
+evidence that an artifact is this tree's build, and one tested bundle reported
+`0.1.3` beside a `0.5.0` checkout with nothing in the run saying so.
+
+`--expect-version` makes the bundle answer for itself, from the metadata its
+own interpreter collected:
+
+```bash
+python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop \
+    --image tests/hanly_fixtures/assets/korean_reading_roi.png \
+    --krdict /tmp/hanly-smoke/krdict.sqlite3 \
+    --expect-version "$(python tools/release_version.py)"
+```
+
+Both `hanly` and `hanly-app` must report that version. A mismatch fails, and so
+does a report that names no version at all — a missing identity leaves the
+release in the same position a wrong one does. The option is refused alongside
+`--inventory-only` and `--reconstruct-only`: neither starts the executable, so
+neither has anything to compare. `dist/reports/hanly-artifact-<platform>.json`
+records the build commit and the source version beside the archive hashes,
+because a hash says two downloads are the same file, not which source made it.
+
 The inventory also names the two build inputs a frozen bundle cannot fetch:
 `certifi/cacert.pem` and both EasyOCR weights. A bundle missing them has
 working code and no way to verify a certificate or read a word.
diff --git a/tests/packaged/shared/test_packaged_desktop.py b/tests/packaged/shared/test_packaged_desktop.py
index fdb1e38..e0fc87b 100644
--- a/tests/packaged/shared/test_packaged_desktop.py
+++ b/tests/packaged/shared/test_packaged_desktop.py
@@ -21,11 +21,13 @@ from tests.hanly_fixtures import FIXTURE_ASSETS, REPO_ROOT
 from tests.hanly_fixtures.capabilities import REQUIRE_PACKAGED, require_display, unavailable
 from tools.build_package import PackageLayout, host_platform
 from tools.build_smoke_krdict import build_smoke_krdict
+from tools.release_version import product_version
 from tools.smoke_packaged_runtime import (
     UI_TIMEOUT_SECONDS,
     _executable_in,
     inspect_bundle,
     run_packaged_self_check,
+    verify_frozen_identity,
 )
 
 #: Points the gate at a bundle outside ``dist/``, such as an extracted release.
@@ -129,6 +131,13 @@ def test_the_frozen_worker_becomes_ready_on_an_isolated_profile(tmp_path: Path)
         "dictionary",
     }
 
+    # The same run says which source produced it. A stale bundle passes every
+    # functional check it ever passed, so working is not evidence of being
+    # this tree's build: one tested artifact reported 0.1.3 beside a 0.5.0
+    # checkout and nothing in the run said so.
+    identity = verify_frozen_identity(report, product_version())
+    assert identity["ok"], identity["problems"]
+
 
 def test_the_frozen_control_center_opens_and_answers_its_own_page(
     tmp_path: Path,
diff --git a/tests/test_ci_workflows.py b/tests/test_ci_workflows.py
index 18ccb52..8e2c6f2 100644
--- a/tests/test_ci_workflows.py
+++ b/tests/test_ci_workflows.py
@@ -515,12 +515,32 @@ def test_each_smoke_keeps_the_output_of_a_harness_that_never_reported() -> None:
 
 
 def test_each_artifact_records_the_identity_it_was_built_from() -> None:
-    """One macOS runner architecture cannot stand in for the other."""
+    """One macOS runner architecture cannot stand in for the other, and an
+    archive hash says two downloads are the same file, not which source made
+    it."""
 
     record = _step(_workflow("build.yml"), "build", name="Record the artifact identity")
 
     for field in ("archive_sha256", "runner_arch", "os_version", "python"):
         assert field in record["run"]
+    assert record["env"]["BUILD_COMMIT"] == "${{ github.sha }}"
+    for field in ("build_commit", "source_version"):
+        assert field in record["run"]
+
+
+def test_the_frozen_bundle_has_to_report_the_version_that_built_it() -> None:
+    """A bundle that works and reports another version is a stale artifact, and
+    one of those was tested as release evidence for a version it was not."""
+
+    steps = _steps(_workflow("build.yml"), "build")
+    names = [step.get("name", "") for step in steps]
+    resolve = names.index("Resolve the product version this build must carry")
+    smoke = _step(_workflow("build.yml"), "build", step_id="worker_smoke")
+
+    assert resolve < names.index("Build application package")
+    assert "release_version.py" in steps[resolve]["run"]
+    assert _uses_quoted_shell_variable(smoke["run"], "SOURCE_VERSION")
+    assert "--expect-version" in smoke["run"]
 
 
 def test_build_rejects_an_archive_too_large_for_github_releases() -> None:
@@ -559,8 +579,8 @@ def test_workflow_env_writes_do_not_shadow_job_environment() -> None:
 def test_build_refuses_a_tag_that_disagrees_with_the_product_version() -> None:
     build = _steps(_workflow("build.yml"), "build")
 
-    tag_push_check = next(
-        step for step in build if "release_version.py" in step.get("run", "")
+    tag_push_check = _step(
+        _workflow("build.yml"), "build", name="Verify the tag matches the product version"
     )
     assert tag_push_check["if"] == "startsWith(github.ref, 'refs/tags/')"
     assert tag_push_check["env"]["RELEASE_TAG"] == "${{ github.ref_name }}"
@@ -575,7 +595,9 @@ def test_build_refuses_a_tag_that_disagrees_with_the_product_version() -> None:
 
 def test_build_context_values_are_env_backed_in_shell_commands() -> None:
     steps = _steps(_workflow("build.yml"), "build")
-    version_check = next(step for step in steps if "release_version.py" in step.get("run", ""))
+    version_check = _step(
+        _workflow("build.yml"), "build", name="Verify the tag matches the product version"
+    )
     assert version_check.get("env", {}).get("RELEASE_TAG") == "${{ github.ref_name }}"
     assert _uses_quoted_shell_variable(version_check["run"], "RELEASE_TAG")
     # The build job runs one step list on three platforms. GitHub's default
diff --git a/tests/test_packaging.py b/tests/test_packaging.py
index c423288..aaf02ac 100644
--- a/tests/test_packaging.py
+++ b/tests/test_packaging.py
@@ -1262,3 +1262,59 @@ def test_an_invocation_that_names_no_product_is_refused(
 ) -> None:
     assert smoke_packaged_runtime.main([]) == 2
     assert "name an application directory" in capsys.readouterr().err
+
+
+# --- which source a frozen bundle says it came from --------------------------
+
+
+def test_a_frozen_bundle_that_reports_another_version_is_not_this_build() -> None:
+    """A stale artifact passes every check it ever passed. Only its own
+    reported version says which source produced it, and one tested bundle
+    reported 0.1.3 beside a 0.5.0 checkout with nothing in the run saying so."""
+
+    identity = smoke_packaged_runtime.verify_frozen_identity(
+        {"versions": {"hanly": "0.1.3", "hanly-app": "0.1.3"}}, "0.5.0"
+    )
+
+    assert identity["ok"] is False
+    assert len(cast(list[str], identity["problems"])) == 2
+    assert "expected '0.5.0'" in cast(list[str], identity["problems"])[0]
+
+
+def test_a_report_that_names_no_version_is_a_failure_not_an_absence() -> None:
+    """Missing identity proves nothing about the build, which is the same
+    position a mismatch leaves the release in."""
+
+    identity = smoke_packaged_runtime.verify_frozen_identity({}, "0.5.0")
+
+    assert identity["ok"] is False
+    assert cast(dict[str, object], identity["packages"]) == {
+        "hanly": None,
+        "hanly-app": None,
+    }
+
+
+def test_both_packages_agreeing_with_the_source_is_the_whole_check() -> None:
+    identity = smoke_packaged_runtime.verify_frozen_identity(
+        {"versions": {"hanly": "0.5.0", "hanly-app": "0.5.0", "torch": "2.4.1"}}, "0.5.0"
+    )
+
+    assert identity["ok"] is True
+    assert identity["problems"] == []
+
+
+def test_an_identity_check_that_never_runs_the_executable_is_refused(
+    tmp_path: Path, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """An inventory reads files. The version comes from the bundle's own
+    interpreter, so a check that does not start one has nothing to compare."""
+
+    bundle = tmp_path / "bundle"
+    bundle.mkdir()
+
+    status = smoke_packaged_runtime.main(
+        [str(bundle), "--inventory-only", "--expect-version", "0.5.0"]
+    )
+
+    assert status == 2
+    assert "runs the executable" in capsys.readouterr().err
diff --git a/tools/smoke_packaged_runtime.py b/tools/smoke_packaged_runtime.py
index 0045968..28480a7 100644
--- a/tools/smoke_packaged_runtime.py
+++ b/tools/smoke_packaged_runtime.py
@@ -26,7 +26,7 @@ import tempfile
 from collections.abc import Callable, Iterator, Mapping, Sequence
 from dataclasses import dataclass
 from pathlib import Path
-from typing import Any
+from typing import Any, cast
 
 #: Packages the desktop imports by name at runtime. Their absence is exactly
 #: the defect that shipped in v0.1.0: readiness waits on morphology forever.
@@ -137,6 +137,12 @@ WINDOWS_FATAL_STATUS = {
 #: and must not depend on the source package it is checking.
 LOCAL_KRDICT_VARIABLE = "HANLY_KRDICT_DB"
 
+#: The packages a frozen bundle has to be able to name itself by. A build that
+#: works and cannot say which source produced it is not release evidence: one
+#: tested bundle reported 0.1.3 while the tree it was compared against was
+#: 0.5.0, and nothing in the run said so.
+IDENTITY_PACKAGES = ("hanly", "hanly-app")
+
 #: The self-check writes one flushed JSON line per stage boundary on stderr.
 #: Named here for the same reason as the variable above. A process killed by a
 #: native fault prints no report, and these lines are the only account of how
@@ -325,6 +331,33 @@ def _marker_payload(line: str) -> str | None:
     return line[start + len(STAGE_MARKER_PREFIX) :].strip()
 
 
+def verify_frozen_identity(
+    report: Mapping[str, object], expected: str
+) -> dict[str, object]:
+    """Compare the versions a frozen bundle reports with the one it claims.
+
+    The bundle answers for itself, from the metadata its own interpreter
+    collected. A missing version is a failure rather than an absence: a report
+    that cannot name its packages proves nothing about which build it came
+    from.
+    """
+
+    versions = report.get("versions")
+    collected = versions if isinstance(versions, Mapping) else {}
+    packages = {name: collected.get(name) for name in IDENTITY_PACKAGES}
+    problems = [
+        f"the frozen bundle reports {name} {value!r}, expected {expected!r}"
+        for name, value in packages.items()
+        if value != expected
+    ]
+    return {
+        "expected": expected,
+        "packages": packages,
+        "ok": not problems,
+        "problems": problems,
+    }
+
+
 def _collection_roots(root: Path) -> tuple[Path, ...]:
     return tuple(root.joinpath(*parts) for parts in _COLLECTION_ROOTS)
 
@@ -772,6 +805,13 @@ def _build_parser() -> argparse.ArgumentParser:
         action="store_true",
         help="check collected dependencies without running the executable",
     )
+    parser.add_argument(
+        "--expect-version",
+        help=(
+            "the product version this bundle must report for both packages; "
+            "a mismatch or a missing version fails the check"
+        ),
+    )
     parser.add_argument(
         "--reconstruct-only",
         action="store_true",
@@ -830,6 +870,10 @@ def _argument_problem(args: argparse.Namespace) -> str | None:
         return "name an application directory, --from-archive, or --disk-image"
     if args.reconstruct_only and args.from_archive is None:
         return "--reconstruct-only needs --from-archive"
+    if args.expect_version is not None and (args.inventory_only or args.reconstruct_only):
+        # The bundle answers for its own version by running; a check that does
+        # not run it would report an identity it never asked for.
+        return "--expect-version needs a check that runs the executable"
     return None
 
 
@@ -891,8 +935,16 @@ def _report(
             timeout=args.timeout,
         )
     output["self_check"] = report
+    identity: dict[str, object] | None = None
+    if args.expect_version is not None:
+        identity = verify_frozen_identity(report, args.expect_version)
+        output["identity"] = identity
     print(json.dumps(output, indent=2))
 
+    if identity is not None and not identity["ok"]:
+        for problem in cast(list[str], identity["problems"]):
+            print(f"Hanly smoke: {problem}", file=sys.stderr)
+        return 1
     if report.get("ok") is True and report.get("exit_code") == 0:
         return 0
     for failure in _iter_failures(report):
@@ -928,6 +980,7 @@ __all__ = [
     "HEADLESS_QT_PLATFORM",
     "HEADLESS_SELF_CHECK_MODES",
     "HOME_VARIABLES",
+    "IDENTITY_PACKAGES",
     "LOCAL_KRDICT_VARIABLE",
     "QT_PLATFORM_VARIABLE",
     "REQUIRED_DATA_FILES",
@@ -947,4 +1000,5 @@ __all__ = [
     "reconstruct_application",
     "run_packaged_self_check",
     "verify_disk_image",
+    "verify_frozen_identity",
 ]
`````

### 8.4 `af44fd7` — fix: report unavailable native UI and process capabilities

`````diff
diff --git a/packages/hanly-app/src/hanly_app/control_center_host.py b/packages/hanly-app/src/hanly_app/control_center_host.py
index 4b4dad2..0af11b4 100644
--- a/packages/hanly-app/src/hanly_app/control_center_host.py
+++ b/packages/hanly-app/src/hanly_app/control_center_host.py
@@ -23,7 +23,11 @@ from .control_center import (
     prepare_control_center_qt,
 )
 from .diagnostics import DiagnosticLog, StartupTimeline
-from .qt_bootstrap import ensure_qt_application, install_qt_thread_invoker
+from .qt_bootstrap import (
+    ensure_qt_application,
+    install_qt_thread_invoker,
+    verify_primary_screen,
+)
 
 #: The backend module Hanly's single-Qt design requires. pywebview falls back
 #: to Cocoa, GTK, or WinForms when Qt cannot load, which would silently mix two
@@ -346,6 +350,9 @@ class ControlCenterHost:
         # argument zero, before any Qt object exists in this process.
         prepare_control_center_qt()
         ensure_qt_application(diagnostics=self._diagnostics)
+        # Between the two: pywebview reads the primary screen's geometry while
+        # creating the window, and a session with none reaches that call.
+        verify_primary_screen()
         try:
             import webview
         except ImportError as error:
diff --git a/packages/hanly-app/src/hanly_app/qt_bootstrap.py b/packages/hanly-app/src/hanly_app/qt_bootstrap.py
index a80d98d..6a15efd 100644
--- a/packages/hanly-app/src/hanly_app/qt_bootstrap.py
+++ b/packages/hanly-app/src/hanly_app/qt_bootstrap.py
@@ -73,6 +73,37 @@ def ensure_qt_application(
     return _application
 
 
+#: How the primary screen is asked for. Injectable because the answer, not the
+#: Qt call, is what the decision below is made from.
+ScreenProbe = Callable[[], object | None]
+
+
+def verify_primary_screen(probe: ScreenProbe | None = None) -> None:
+    """Fail before a library reads the geometry of a screen that is not there.
+
+    Qt initializes in a session with no screen and only says so fatally later.
+    pywebview then asks the primary screen for its geometry while creating the
+    window, without checking that there is one, and the failure surfaces from
+    inside that library rather than from Hanly.
+
+    This runs after the application exists, so it cannot prevent an abort
+    inside ``QApplication`` itself; that case stays with the packaging
+    self-check's stage markers and Qt's own message handler.
+    """
+
+    screen = (_primary_screen if probe is None else probe)()
+    if screen is None:
+        raise ControlCenterUnavailable(
+            "this session has no usable screen; the Control Center needs a desktop"
+        )
+
+
+def _primary_screen() -> object | None:
+    from PyQt6.QtGui import QGuiApplication
+
+    return QGuiApplication.primaryScreen()
+
+
 def verify_platform_plugin(environment: Mapping[str, str] | None = None) -> None:
     """Fail with an exception where Qt would abort the process instead.
 
@@ -194,4 +225,5 @@ __all__ = [
     "install_qt_thread_invoker",
     "qt_application",
     "verify_platform_plugin",
+    "verify_primary_screen",
 ]
diff --git a/packaging/README.md b/packaging/README.md
index a8f8284..5a33a76 100644
--- a/packaging/README.md
+++ b/packaging/README.md
@@ -263,6 +263,18 @@ the last stage that passed would invent a diagnosis. Provider construction,
 OCR, morphology, dictionary, closing the worker, the Qt WebEngine import, the
 window itself, and each page probe all carry a marker.
 
+Two native boundaries now say what they could not do instead of reaching into
+it. The Control Center checks for a usable primary screen after Qt
+initializes and before pywebview creates its window: pywebview reads the
+primary screen's geometry there without checking that there is one, so a
+screenless session used to fail from inside that library, under Qt's own fatal
+"no screens available". The check runs after the `QApplication` exists, so it
+cannot prevent an abort inside the constructor — that case stays with the
+stage markers above. And the process inventory the native smokes embed raises
+rather than returning nothing when the host refuses to answer: a denied `ps`
+and an empty child list look identical and mean opposite things, and only one
+of them is a retired child.
+
 `tools/native_host_fingerprint.py` records what the machine actually is —
 operating system and build, CPU model and vendor, core counts, the build
 interpreter — before the first install, so a run that dies later still says
diff --git a/tests/hanly_fixtures/process_probe.py b/tests/hanly_fixtures/process_probe.py
index 052b770..e713a30 100644
--- a/tests/hanly_fixtures/process_probe.py
+++ b/tests/hanly_fixtures/process_probe.py
@@ -5,27 +5,72 @@ program they write out, so the child needs no path setup to ask the operating
 system what is running. Each row is ``pid ppid detail``, where ``detail`` is
 the command line -- callers identify multiprocessing's resource tracker and
 the inventory command itself by what is in it.
+
+``process_rows`` raises rather than returning nothing when the operating
+system refuses to answer. A denied ``ps``, a missing probe tool, and a probe
+that never returns are all *inspection unavailable*; an empty list would say
+the opposite, that the process owns no children, and a test reading it that
+way would report a clean retirement it never observed.
 """
 
+#: Raised in the child when the host will not say what is running. Its name is
+#: what a consumer matches on, because the child and the test share no module.
+PROBE_UNAVAILABLE = "ProcessInspectionUnavailable"
+
 PROCESS_ROWS_PROGRAM = '''
+class ProcessInspectionUnavailable(RuntimeError):
+    """The operating system refused to say what is running."""
+
+
 def process_rows():
     import json
     import subprocess
     import sys
 
     if sys.platform != "win32":
-        return subprocess.check_output(
-            ["ps", "-axo", "pid=,ppid=,command="], text=True, timeout=15
-        ).splitlines()
+        return _rows_from(
+            ["ps", "-axo", "pid=,ppid=,command="],
+            lambda output: output.splitlines(),
+        )
 
-    output = subprocess.check_output(
+    return _rows_from(
         ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
          "Get-CimInstance Win32_Process | "
          "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
          "ConvertTo-Json -Compress"],
-        text=True,
-        timeout=15,
+        _windows_rows,
     )
+
+
+def _rows_from(command, parse):
+    """Run one inventory command, or say why the host would not answer."""
+
+    import subprocess
+
+    try:
+        output = subprocess.check_output(command, text=True, timeout=15)
+    except FileNotFoundError as error:
+        raise ProcessInspectionUnavailable(
+            "%s is not on this host: %s" % (command[0], error)
+        ) from error
+    except PermissionError as error:
+        raise ProcessInspectionUnavailable(
+            "%s is not permitted here: %s" % (command[0], error)
+        ) from error
+    except subprocess.TimeoutExpired as error:
+        raise ProcessInspectionUnavailable(
+            "%s did not answer in time" % command[0]
+        ) from error
+    except subprocess.CalledProcessError as error:
+        raise ProcessInspectionUnavailable(
+            "%s exited with status %d" % (command[0], error.returncode)
+        ) from error
+    return parse(output)
+
+
+def _windows_rows(output):
+    import json
+
     records = json.loads(output)
     if isinstance(records, dict):
         records = [records]
@@ -45,3 +90,5 @@ def process_rows():
         rows.append("%d %d %s" % (pid, parent, detail.replace("\\n", " ")))
     return rows
 '''
+
+__all__ = ["PROBE_UNAVAILABLE", "PROCESS_ROWS_PROGRAM"]
diff --git a/tests/native/macos/test_control_center_identity.py b/tests/native/macos/test_control_center_identity.py
index b2ff042..049de4a 100644
--- a/tests/native/macos/test_control_center_identity.py
+++ b/tests/native/macos/test_control_center_identity.py
@@ -11,6 +11,9 @@ from tests.hanly_fixtures.capabilities import require_display, require_modules
 
 _CHILD_TIMEOUT_SECONDS = 300
 
+#: macOS registers every process that creates a ``QApplication`` as a
+#: user-facing application, which made the Control Center child a second Hanly
+#: in the Dock and the app switcher beside the shell.
 _IDENTITY_PROGRAM = '''
 import json
 import re
diff --git a/tests/native/shared/test_control_center_lifecycle.py b/tests/native/shared/test_control_center_lifecycle.py
index a9e08b3..a240849 100644
--- a/tests/native/shared/test_control_center_lifecycle.py
+++ b/tests/native/shared/test_control_center_lifecycle.py
@@ -17,7 +17,7 @@ from pathlib import Path
 
 import pytest
 
-from tests.hanly_fixtures.capabilities import require_display, require_modules
+from tests.hanly_fixtures.capabilities import require_display, require_modules, unavailable
 from tests.hanly_fixtures.process_probe import PROCESS_ROWS_PROGRAM
 
 #: Qt's own complaint when a second ``exec`` runs inside a live loop. This is
@@ -144,6 +144,11 @@ def main():
         control.shutdown()
         report["running_after_shutdown"] = control.running
         report["descendants_after_shutdown"] = settled_descendants()
+    except ProcessInspectionUnavailable as refusal:
+        # Not a leak and not a defect: this host will not say what is running,
+        # and an empty descendant list would claim the opposite.
+        report["inspection_unavailable"] = str(refusal)
+        control.shutdown()
     except BaseException as error:
         report["errors"].append(f"{type(error).__name__}: {error}")
         control.shutdown()
@@ -224,14 +229,23 @@ if __name__ == "__main__":
 '''
 
 
-#: macOS registers every process that creates a ``QApplication`` as a
-#: user-facing application, which made the Control Center child a second Hanly
-#: in the Dock and the app switcher beside the shell.
 def _require_a_desktop() -> None:
     require_modules("PyQt6.QtWebEngineWidgets", "webview")
     require_display()
 
 
+def _require_inspection(report: dict[str, object]) -> None:
+    """A host that will not say what is running has proved no retirement.
+
+    Reading an empty descendant list as a clean close would turn a refused
+    ``ps`` into evidence of exactly the thing it could not observe.
+    """
+
+    refusal = report.get("inspection_unavailable")
+    if refusal:
+        unavailable(f"process inspection is unavailable here: {refusal}")
+
+
 def test_the_window_opens_closes_and_reopens_without_touching_the_shell(
     tmp_path: Path,
 ) -> None:
@@ -254,6 +268,7 @@ def test_the_window_opens_closes_and_reopens_without_touching_the_shell(
     )
     assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr!r}"
     report = json.loads(line[len(marker) :])
+    _require_inspection(report)
 
     assert report["errors"] == []
     # The page itself calls the parent bridge, which is the whole proxy path:
diff --git a/tests/native/shared/test_lookup_process_spawn.py b/tests/native/shared/test_lookup_process_spawn.py
index d835447..99ca6c6 100644
--- a/tests/native/shared/test_lookup_process_spawn.py
+++ b/tests/native/shared/test_lookup_process_spawn.py
@@ -127,12 +127,17 @@ def main(krdict, models, fixture):
         )
         report["status_after_wake"] = again.status.value
         report["generation_after_wake"] = engine.generation
+    except ProcessInspectionUnavailable as refusal:
+        # Not a leak and not a defect: this host will not say what is running,
+        # and an empty child list would claim the opposite.
+        report["inspection_unavailable"] = str(refusal)
     except BaseException as error:
         report["errors"].append(f"{type(error).__name__}: {error}")
     finally:
         engine.close()
         report["state_after_close"] = engine.state
-        report["children_after_close"] = settled_children()
+        if "inspection_unavailable" not in report:
+            report["children_after_close"] = settled_children()
 
     report["heavy_modules_in_the_shell"] = [
         name for name in HEAVY_MODULES if name in sys.modules
@@ -185,6 +190,18 @@ def _requirements() -> tuple[Path, Path, Path]:
     return dictionary, models, fixture
 
 
+def _require_inspection(report: dict[str, object]) -> None:
+    """A host that will not say what is running has proved no retirement.
+
+    Reading an empty child list as a retired engine would turn a refused ``ps``
+    into evidence of exactly the thing it could not observe.
+    """
+
+    refusal = report.get("inspection_unavailable")
+    if refusal:
+        unavailable(f"process inspection is unavailable here: {refusal}")
+
+
 def test_a_real_korean_lookup_runs_in_a_child_the_shell_can_retire(tmp_path: Path) -> None:
     dictionary, models, fixture = _requirements()
 
@@ -211,6 +228,7 @@ def test_a_real_korean_lookup_runs_in_a_child_the_shell_can_retire(tmp_path: Pat
     )
     assert line is not None, f"stdout={child.stdout!r} stderr={child.stderr[-3000:]!r}"
     report = json.loads(line[len(marker) :])
+    _require_inspection(report)
 
     assert report["errors"] == []
     assert report["state_after_attach"] == "ready"
diff --git a/tests/native/shared/test_qt_screen.py b/tests/native/shared/test_qt_screen.py
new file mode 100644
index 0000000..8b27bdb
--- /dev/null
+++ b/tests/native/shared/test_qt_screen.py
@@ -0,0 +1,22 @@
+"""A real desktop session answers for its own screen.
+
+The portable suite covers both branches of the guard with an injected probe.
+This is the one thing it cannot cover: that an ordinary session actually
+reaches Qt's primary screen, so the guard does not refuse a working desktop.
+"""
+
+from __future__ import annotations
+
+from tests.hanly_fixtures.capabilities import require_modules
+
+require_modules("PyQt6.QtWidgets", module_level=True)
+
+from hanly_app.qt_bootstrap import verify_primary_screen  # noqa: E402
+from PyQt6.QtGui import QGuiApplication  # noqa: E402
+from PyQt6.QtWidgets import QApplication  # noqa: E402
+
+
+def test_a_real_session_reports_a_primary_screen(qt_application: QApplication) -> None:
+    assert QGuiApplication.primaryScreen() is not None
+
+    verify_primary_screen()
diff --git a/tests/test_control_center_host.py b/tests/test_control_center_host.py
index bb6f834..30e76fc 100644
--- a/tests/test_control_center_host.py
+++ b/tests/test_control_center_host.py
@@ -7,6 +7,7 @@ from types import SimpleNamespace
 from typing import Any
 
 import pytest
+from hanly_app import control_center_host
 from hanly_app.control_center import ControlCenterUnavailable
 from hanly_app.control_center_host import QT_BACKEND_MODULE, ControlCenterHost
 
@@ -185,3 +186,32 @@ def test_the_loop_refuses_to_run_twice() -> None:
     assert len(webview.reentered) == 1
     assert "already running" in str(webview.reentered[0])
     assert webview.names.count("start") == 1
+
+
+def test_a_session_without_a_screen_is_reported_before_pywebview_is_asked(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Order is the whole point: past this call pywebview reaches the primary
+    screen's geometry itself, and answers for a session that has none from
+    inside its own window creation."""
+
+    reached: list[str] = []
+    monkeypatch.setattr(
+        control_center_host, "prepare_control_center_qt", lambda: reached.append("backend")
+    )
+    monkeypatch.setattr(
+        control_center_host,
+        "ensure_qt_application",
+        lambda **_: reached.append("application"),
+    )
+
+    def refuse() -> None:
+        reached.append("screen")
+        raise ControlCenterUnavailable("this session has no usable screen")
+
+    monkeypatch.setattr(control_center_host, "verify_primary_screen", refuse)
+
+    with pytest.raises(ControlCenterUnavailable, match="no usable screen"):
+        ControlCenterHost(object())._load_webview()
+
+    assert reached == ["backend", "application", "screen"]
diff --git a/tests/test_process_probe.py b/tests/test_process_probe.py
new file mode 100644
index 0000000..ca786b2
--- /dev/null
+++ b/tests/test_process_probe.py
@@ -0,0 +1,46 @@
+"""What the native smokes are told when the host will not answer.
+
+An empty process list and a refused ``ps`` look identical to a caller that
+does not distinguish them, and they mean opposite things: one says the child
+was retired, the other says nobody looked. A sandbox that denied ``/bin/ps``
+is what made this worth stating.
+"""
+
+from __future__ import annotations
+
+import os
+import sys
+from typing import Any
+
+import pytest
+
+from tests.hanly_fixtures.process_probe import PROBE_UNAVAILABLE, PROCESS_ROWS_PROGRAM
+
+
+def _probe() -> dict[str, Any]:
+    """Load the inventory the way the smoke children do: as source, not import."""
+
+    namespace: dict[str, Any] = {}
+    exec(PROCESS_ROWS_PROGRAM, namespace)  # noqa: S102 - this is the fixture's contract
+    return namespace
+
+
+def test_this_host_lists_the_process_asking_the_question() -> None:
+    rows = _probe()["process_rows"]()
+
+    pids = {int(row.split(None, 1)[0]) for row in rows if row.split()}
+    assert os.getpid() in pids
+
+
+def test_a_probe_tool_that_is_not_there_is_never_an_empty_inventory() -> None:
+    namespace = _probe()
+
+    with pytest.raises(namespace[PROBE_UNAVAILABLE], match="is not on this host"):
+        namespace["_rows_from"](["hanly-no-such-probe"], list)
+
+
+def test_a_probe_that_refuses_is_never_an_empty_inventory() -> None:
+    namespace = _probe()
+
+    with pytest.raises(namespace[PROBE_UNAVAILABLE], match="status 3"):
+        namespace["_rows_from"]([sys.executable, "-c", "raise SystemExit(3)"], list)
diff --git a/tests/test_qt_bootstrap.py b/tests/test_qt_bootstrap.py
index 107feb9..3efc9f0 100644
--- a/tests/test_qt_bootstrap.py
+++ b/tests/test_qt_bootstrap.py
@@ -233,3 +233,16 @@ def test_the_platform_plugin_is_checked_before_the_application_exists(
     qt_bootstrap.ensure_qt_application()
 
     assert order == ["verify", "qapplication"]
+
+
+def test_a_session_with_no_screen_is_reported_rather_than_reached_into() -> None:
+    """pywebview reads the primary screen's geometry while creating its window
+    and never checks that there is one, so the failure arrives from inside that
+    library with Qt's fatal "no screens available" above it."""
+
+    with pytest.raises(ControlCenterUnavailable, match="no usable screen"):
+        qt_bootstrap.verify_primary_screen(lambda: None)
+
+
+def test_an_ordinary_screen_is_accepted_without_comment() -> None:
+    qt_bootstrap.verify_primary_screen(lambda: object())
`````

### 8.5 `13de683` — fix: read this platform's own maxrss unit when sampling memory

`````diff
diff --git a/.github/workflows/build.yml b/.github/workflows/build.yml
index d786a08..1b01ec7 100644
--- a/.github/workflows/build.yml
+++ b/.github/workflows/build.yml
@@ -51,7 +51,6 @@ jobs:
       # which machine it died on. The crash this exists for is a native library
       # meeting a CPU that does not implement what it was compiled to use.
       - name: Record the host fingerprint
-        id: fingerprint
         shell: bash
         run: >
           python tools/native_host_fingerprint.py
@@ -88,7 +87,6 @@ jobs:
       # Torch is probed only once it exists, and in a child of its own: the
       # import is one of the things that ends a packaging run outright.
       - name: Record what the installed runtime reports
-        id: runtime_fingerprint
         shell: bash
         run: >
           python tools/native_host_fingerprint.py
@@ -100,7 +98,6 @@ jobs:
       # A bundle that works and cannot name the source that produced it is not
       # release evidence, however green the rest of the job is.
       - name: Resolve the product version this build must carry
-        id: source_version
         shell: bash
         run: echo "SOURCE_VERSION=$(python tools/release_version.py)" >> "$GITHUB_ENV"
 
@@ -235,11 +232,13 @@ jobs:
           && steps.dictionary.outcome == 'success' }}
         shell: bash
         env:
+          RUNNER_PLATFORM: ${{ matrix.platform }}
           HANLY_REQUIRE_PACKAGED: "1"
           HANLY_PACKAGED_APP: ${{ env.SMOKE_APP }}
         run: |
+          set -euo pipefail
           display=""
-          if [ "${{ matrix.platform }}" = "linux" ]; then display="xvfb-run -a"; fi
+          if [ "$RUNNER_PLATFORM" = "linux" ]; then display="xvfb-run -a"; fi
           $display python -m pytest --suite packaged
 
       - name: Verify the release archive exists
diff --git a/benchmarks/dev/probes.py b/benchmarks/dev/probes.py
index 425c5ca..e383c89 100644
--- a/benchmarks/dev/probes.py
+++ b/benchmarks/dev/probes.py
@@ -12,6 +12,7 @@ import functools
 import json
 import math
 import os
+import sys
 import time
 from collections.abc import Callable, Mapping, MutableSequence, Sequence
 from datetime import datetime, timezone
@@ -317,6 +318,12 @@ class StageProbe:
     run = __call__
 
 
+#: ``getrusage`` does not agree with itself across platforms: Linux reports
+#: ``ru_maxrss`` in KiB and the BSDs, macOS included, report it in bytes.
+#: Assuming KiB everywhere read 39 MiB of resident memory as 39 GiB.
+_MAXRSS_BYTES_PER_UNIT = 1 if sys.platform == "darwin" else 1024
+
+
 class ProcessSampler:
     """Write bounded process CPU/RSS observations to a CSV stream or path."""
 
@@ -367,8 +374,7 @@ class ProcessSampler:
             if _resource is None:
                 return None, None
             usage = _resource.getrusage(_resource.RUSAGE_SELF)
-            # Unix reports KiB; keep the field name honest for the fallback.
-            return None, int(usage.ru_maxrss) * 1024
+            return None, int(usage.ru_maxrss) * _MAXRSS_BYTES_PER_UNIT
         except Exception:
             return None, None
 
diff --git a/benchmarks/dev/tests/test_probes.py b/benchmarks/dev/tests/test_probes.py
index f89499d..287b60d 100644
--- a/benchmarks/dev/tests/test_probes.py
+++ b/benchmarks/dev/tests/test_probes.py
@@ -5,12 +5,14 @@ from __future__ import annotations
 import csv
 import io
 import json
+import sys
 import zipfile
 from pathlib import Path
 from typing import Any
 
 import pytest
 
+from benchmarks.dev import probes
 from benchmarks.dev.package_composition import analyze_package
 from benchmarks.dev.probes import (
     ProcessSampler,
@@ -315,3 +317,24 @@ def test_package_analyzer_keeps_posix_symlink_targets_out_of_tree_totals(
 
     assert report["file_count"] == 1
     assert report["total_bytes"] == len(b"target")
+
+
+def test_the_rusage_fallback_reads_this_platform_s_own_maxrss_unit() -> None:
+    """``getrusage`` does not agree with itself: Linux reports ``ru_maxrss`` in
+    KiB and macOS in bytes. Assuming KiB on macOS read 39 MiB as 39 GiB, which
+    is a plausible-looking number in a CSV nobody reads twice."""
+
+    expected = 1 if sys.platform == "darwin" else 1024
+
+    assert probes._MAXRSS_BYTES_PER_UNIT == expected
+
+
+def test_the_fallback_sample_is_a_believable_resident_size() -> None:
+    """Whatever the unit, the answer has to be this process's own memory."""
+
+    sampler = ProcessSampler(io.StringIO(), process=None)
+
+    _cpu, rss = sampler._read_sample(None)
+
+    assert rss is not None
+    assert 1 << 20 < rss < 8 * (1 << 30), rss
diff --git a/docs/execution/checkpoints/han-43-44-superqa.md b/docs/execution/checkpoints/han-43-44-superqa.md
index 5987260..688b97f 100644
--- a/docs/execution/checkpoints/han-43-44-superqa.md
+++ b/docs/execution/checkpoints/han-43-44-superqa.md
@@ -16,7 +16,7 @@
 | --- | --- | --- | --- | --- |
 | HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and standalone `--disk-image` in the smoke harness. | `pytest tests/test_packaging.py tests/test_ci_workflows.py tests/test_host_fingerprint.py` 153 passed; full `pytest` 1275 passed / 3 skipped; ruff + mypy clean. | |
 | HAN-43 | Implemented | Native and packaged cases routed into `tests/native/{shared,macos,windows}` and `tests/packaged/shared`; `--suite portable\|native\|packaged` selection that excludes a suite before its modules import; `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn capability skips into failures in the jobs that own them; `ci.yml` gains three source-native jobs and `build.yml` gives up the duplicated portable suite, lint, and types. | Collected node IDs compared before/after: every case has an owner (`--suite` totals 1286 + 1 skipped, and the two Windows-only cases are now OS-routed rather than collected-and-skipped on macOS). `pytest --suite native` 35 passed on this host; full `pytest` 1286 passed / 1 skipped; ruff + mypy clean. | |
-| Super QA | Pending | | | |
+| Super QA | In progress | SUPERQA-005: `--expect-version` in the smoke harness plus build commit / source version in the artifact record. SUPERQA-002: `verify_primary_screen` between Qt initialization and pywebview window creation. SUPERQA-004: the embedded process inventory raises `ProcessInspectionUnavailable` instead of returning nothing, and both consumers report it as unavailable rather than as a retired child. | The stale `dist/macos/Hanly.app` on this machine reports `hanly`/`hanly-app` `0.1.3` against a `0.5.0` tree; `smoke_packaged_runtime.py --expect-version 0.5.0` now exits 1 on it, naming both packages. `pytest --suite native` 37 passed. | |
 
 ## HAN-43 routing inventory
 
@@ -47,6 +47,18 @@ behavior (xcb plugin, display) is exercised by the shared cases on the Linux job
 | `worker close` became a reported stage | A crash while releasing native handles used to be attributed to the last provider stage | Implemented. The worker report now carries one extra stage | If a consumer parses the stage list positionally |
 | `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |
 
+## SUPERQA-001-006 dispositions
+
+| ID | Outcome | Evidence |
+| --- | --- | --- |
+| SUPERQA-001 | pending fresh-build validation | |
+| SUPERQA-002 | Implemented | |
+| SUPERQA-003 | Not reproduced | |
+| SUPERQA-004 | Not reproduced (environment), hardened | |
+| SUPERQA-005 | Confirmed and now enforced | |
+| SUPERQA-006 | pending fresh-build measurement | |
+
 ## Next action / blockers
-- HAN-43: route native cases into `tests/native/**` and `tests/packaged/**`, add suite
-  selection, and rebuild the CI job layout.
+- Build the macOS artifact from this branch with the 3.10 packaging interpreter,
+  then run the packaged suite, the native UI confirmations, and the SUPERQA-006
+  measurements against it.
diff --git a/tests/packaged/shared/test_packaged_desktop.py b/tests/packaged/shared/test_packaged_desktop.py
index e0fc87b..ab9ba0f 100644
--- a/tests/packaged/shared/test_packaged_desktop.py
+++ b/tests/packaged/shared/test_packaged_desktop.py
@@ -165,6 +165,9 @@ def test_the_frozen_control_center_opens_and_answers_its_own_page(
 
     assert report.get("ok") is True, failures or str(report)
     assert {stage.get("name") for stage in recorded} == {
+        # Importing Qt WebEngine is its own stage: a frozen build can die there
+        # before a window exists at all.
+        "window host",
         "main window",
         "document",
         "controls",
`````

### 8.6 `c6ef4bc` — chore: record the HAN-43, HAN-44 and Super QA handoff

`````diff
diff --git a/docs/execution/checkpoints/han-43-44-superqa.md b/docs/execution/checkpoints/han-43-44-superqa.md
index 688b97f..1e16e5f 100644
--- a/docs/execution/checkpoints/han-43-44-superqa.md
+++ b/docs/execution/checkpoints/han-43-44-superqa.md
@@ -3,9 +3,12 @@
 ## Session
 - Branch / base SHA: `codex/han-43-44-superqa` from `main` at `5f7eb2af68ab7883ec5f43525e00fd325867fd49`
 - Interpreter / OS / display and process-inspection availability: `.venv` Python 3.13.11,
-  macOS arm64 (Darwin 25.6.0). `/bin/ps` is permitted in this session, unlike the
-  sandbox that produced `superqa.md`. Visible-desktop availability is checked per native
-  run and recorded with the result.
+  macOS 26.6.2 arm64 (Darwin 25.6.0). This session has a **visible window server**,
+  `/bin/ps` is permitted, and a KRDICT database plus the EasyOCR weights are present —
+  none of which the sandbox that produced `superqa.md` had.
+- Packaging interpreter: a disposable Python 3.10.20 environment built from
+  `packaging/release-constraints.txt`, outside the repository. It is the interpreter
+  `build.yml` uses, not `.venv`.
 - Scope: HAN-44, HAN-43, SUPERQA-001–006
 - Linear: not reachable from this session (the MCP Linear server is unauthenticated).
   No issue state was changed and no comment was posted. Status progression for HAN-43
@@ -14,51 +17,98 @@
 ## Checkpoints
 | Patch | State | Main changes | Check and result | Commit |
 | --- | --- | --- | --- | --- |
-| HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and standalone `--disk-image` in the smoke harness. | `pytest tests/test_packaging.py tests/test_ci_workflows.py tests/test_host_fingerprint.py` 153 passed; full `pytest` 1275 passed / 3 skipped; ruff + mypy clean. | |
-| HAN-43 | Implemented | Native and packaged cases routed into `tests/native/{shared,macos,windows}` and `tests/packaged/shared`; `--suite portable\|native\|packaged` selection that excludes a suite before its modules import; `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn capability skips into failures in the jobs that own them; `ci.yml` gains three source-native jobs and `build.yml` gives up the duplicated portable suite, lint, and types. | Collected node IDs compared before/after: every case has an owner (`--suite` totals 1286 + 1 skipped, and the two Windows-only cases are now OS-routed rather than collected-and-skipped on macOS). `pytest --suite native` 35 passed on this host; full `pytest` 1286 passed / 1 skipped; ruff + mypy clean. | |
-| Super QA | In progress | SUPERQA-005: `--expect-version` in the smoke harness plus build commit / source version in the artifact record. SUPERQA-002: `verify_primary_screen` between Qt initialization and pywebview window creation. SUPERQA-004: the embedded process inventory raises `ProcessInspectionUnavailable` instead of returning nothing, and both consumers report it as unavailable rather than as a retired child. | The stale `dist/macos/Hanly.app` on this machine reports `hanly`/`hanly-app` `0.1.3` against a `0.5.0` tree; `smoke_packaged_runtime.py --expect-version 0.5.0` now exits 1 on it, naming both packages. `pytest --suite native` 37 passed. | |
+| HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and a standalone `--disk-image` in the smoke harness. | Focused: 153 passed across `test_packaging`, `test_ci_workflows`, `test_host_fingerprint`. Bundle gates below. | `3e05574` |
+| HAN-43 | Implemented | Native and packaged cases routed into `tests/native/{shared,macos,windows}` and `tests/packaged/shared`; `--suite portable\|native\|packaged` selection that excludes a suite before its modules import; `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn capability skips into failures in the jobs that own them; `ci.yml` gains three source-native jobs and `build.yml` gives up the duplicated portable suite, lint, and types. | Collected node IDs compared before/after: every case has an owner; the only two not collected on this host are the Windows-only pair, now OS-routed instead of collected-and-skipped. `pytest --suite native` 37 passed, 0 skipped. | `17c841a` |
+| Super QA | Implemented | `--expect-version` plus the build commit and source version in the artifact record (005); `verify_primary_screen` between Qt initialization and pywebview window creation (002); the embedded process inventory raises `ProcessInspectionUnavailable` rather than returning nothing, and both consumers report it as unavailable rather than as a retired child (004); the benchmark RSS fallback reads this platform's own `ru_maxrss` unit. | A fresh macOS bundle was built from this branch with the 3.10 packaging environment and validated end to end — see the dispositions below. | `ce94fe4`, `af44fd7`, `13de683` |
 
 ## HAN-43 routing inventory
 
 | File | Disposition |
 | --- | --- |
 | `tests/integration/test_packaged_desktop.py` | → `tests/packaged/shared/`; stale-bundle and missing-bundle skips now fail under `HANLY_REQUIRE_PACKAGED` |
-| `tests/integration/test_control_center_layout.py` | → `tests/native/shared/`; capability check no longer imports Qt in the parent |
+| `tests/integration/test_control_center_layout.py` | → `tests/native/shared/`; the capability check no longer imports Qt in the parent |
 | `tests/integration/test_control_center_lifecycle.py` | → `tests/native/shared/`; the macOS identity case → `tests/native/macos/test_control_center_identity.py`. The POSIX-signal case stays shared: POSIX is not one OS |
 | `tests/integration/test_desktop_startup.py` | → `tests/native/shared/` |
 | `tests/integration/test_lookup_process_spawn.py` | → `tests/native/shared/` |
 | `tests/integration/test_webengine_startup.py` | → `tests/native/shared/`; the Windows abort case → `tests/native/windows/test_webengine_arguments.py`; the child program → `tests/hanly_fixtures/webengine_probe.py` |
 | `tests/test_qt_popup_window.py` | → `tests/native/shared/` (real Qt widgets); the Cocoa panel case → `tests/native/macos/test_popup_panel.py`; the zero-pointer guard is a pure platform decision and moved to `tests/test_popup.py` |
 | `tests/test_hover_exit_qt.py`, `tests/test_qt_hover_scheduler.py` | → `tests/native/shared/`: both build a real `QApplication` and run a real event loop, which is what kept `PyQt6` in the portable collection |
-| `tests/test_control_center.py` | the WebEngine-ordering case → `tests/native/shared/test_webengine_startup.py`, now in a child: the production guard refuses once any `QApplication` exists, so it was passing on collection order |
+| `tests/test_control_center.py` | the WebEngine-ordering case → `tests/native/shared/test_webengine_startup.py`, now in a child: the production guard refuses once any `QApplication` exists, so it had been passing on collection order |
 | `tests/test_app_update_handoff.py` | split. Rendered-script decisions stay portable; the executing cases → `tests/native/shared/test_update_handoff_native.py`, the Windows rollback → `tests/native/windows/`, the macOS rollback → `tests/native/macos/`; shared scaffolding → `tests/hanly_fixtures/update_handoff.py` |
 | `tests/test_hotkeys.py`, `tests/test_hotkeys_darwin.py` | stay portable: both drive doubles (`_Listener`, `_FakeCarbon`), never a real registration |
-| `tests/hanly_fixtures/process_probe.py` | stays; consumers updated by the Super QA patch |
+| `tests/hanly_fixtures/process_probe.py` | stays; rewritten by the Super QA patch to refuse an empty inventory |
 
 `tests/native/linux/` is deliberately absent: no case is Linux-only. Linux-native
-behavior (xcb plugin, display) is exercised by the shared cases on the Linux job.
+behavior (the xcb plugin, the display) is exercised by the shared cases on the Linux job.
+
+## SUPERQA-001–006 dispositions
+
+| ID | Outcome | Evidence |
+| --- | --- | --- |
+| SUPERQA-001 | **Not reproduced** on a visible session; diagnostics kept for the case that remains | Fresh bundle, `--self-check ui`: `ok: true`, exit 0, 2.54 s wall — window host 0.1 ms, main window 2,069 ms, document 883 ms, 4 controls rendered, bridge answered `EasyOCR`. Source `python -m hanly_app --self-check ui` likewise passes. The abort in `superqa.md` belonged to the screenless child it was reported in. HAN-44's markers now name the stage when it does happen |
+| SUPERQA-002 | **Fixed now** | `verify_primary_screen` runs after `ensure_qt_application` and before pywebview creates the window, raising `ControlCenterUnavailable`. Both branches covered portably with an injected probe; a real session's screen covered by `tests/native/shared/test_qt_screen.py`. It cannot prevent an abort *inside* `QApplication` — that case stays with the stage markers, and the README says so |
+| SUPERQA-003 | **Not reproduced** | The whole popup suite runs on this visible Cocoa session: `tests/native/shared/test_qt_popup_window.py` (7 cases) and `tests/native/macos/test_popup_panel.py`, including `hides_when_inactive(winId()) is False` across a show/hide cycle. No adapter change was made, and none is evidenced |
+| SUPERQA-004 | **Not reproduced** (this host permits `/bin/ps`) and **hardened** | The embedded inventory now raises `ProcessInspectionUnavailable` for a missing tool, a denial, a timeout, or a non-zero exit; both consumers report it as unavailable rather than as a retired child. Darwin handoff retested for real with compiled builds and LaunchServices: `tests/native/macos/test_update_handoff_darwin.py` and the shared native handoff cases pass. No production updater logic was changed |
+| SUPERQA-005 | **Confirmed, then fixed** | The `dist/macos/Hanly.app` on this machine reported `hanly`/`hanly-app` `0.1.3` against a `0.5.0` tree. `smoke_packaged_runtime.py --expect-version 0.5.0` exits 1 on it and names both packages. The fresh build reports `0.5.0` for both, and `dist/reports/hanly-artifact-*.json` now carries the build commit and source version |
+| SUPERQA-006 | **Measured; no regression, residual cost recorded** | See the table below |
+
+### SUPERQA-006 measurements
+
+Fresh macOS build from this branch: embedded Python 3.10.20, torch 2.14.0,
+EasyOCR 1.7.2, Kiwi 0.23.2, PyQt6 6.11.0.
+
+| Metric | Now | `superqa.md` (stale 0.1.3 artifact) |
+| --- | ---: | ---: |
+| Frozen worker self-check, wall clock (warm) | 7.74 s | 9.32 s |
+| Lookup worker construction (cold first touch / warm) | 7,863 / **4,277** ms | 5,555 ms |
+| OCR (cold / warm) | 3,047 / **1,800** ms | 1,907 ms |
+| Morphology (cold / warm) | 1,881 / **1,300** ms | 1,154 ms |
+| Dictionary | **3–4** ms | 136 ms |
+| Frozen UI self-check, wall clock | **2.54 s** | aborted |
+| Source warm lookup, 192x48 ROI, 40 samples | **p50 29.8 ms / p95 30.7 ms** | not measured |
+| RSS with providers resident, 20 s idle | **834.9 MiB, flat** | not measurable |
+| `Hanly.app` tree | 1,342,418,115 B (4,906 files) | ~1.3 G |
+| macOS ZIP | 560,323,613 B | 534 M |
+| macOS DMG | 637,255,977 B | 608 M |
+
+Largest families: Torch 484.7 MB, Qt/PyQt6/QtWebEngine 387.4 MB, Kiwi 124.0 MB,
+OpenCV 123.6 MB, EasyOCR weights 99.2 MB.
+
+Process lifecycle, from the real spawned child: one lookup child while ready
+(one pid), `children_after_retire: []`, `children_after_close: []`, a new
+generation after waking a retired engine, and none of `easyocr`, `torch`, or
+`kiwipiepy` imported in the shell.
+
+**Residual cost:** worker construction still dominates the first lookup after a
+retirement — about 4.3 s frozen and warm. That is the price the approved policy
+already charges (`LookupPreload.WHEN_CAPTURE_STARTS` loads at Start;
+`manual_lookup.IDLE_TIMEOUT_SECONDS` retires an idle manual session after 60 s),
+and the warm path is 30 ms. Nothing was changed for it.
+**Revisit trigger:** a reported user-visible delay on the first lookup after an
+idle retirement, or any change to the `LookupPreload` default.
 
 ## Observations for future review
 | Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
 | --- | --- | --- | --- |
-| `ci.yml` job names changed: `windows tests (py3.10)` is gone, replaced by `native (windows)`, `native (macos)`, `native (linux)` | The Windows job was a duplicate full suite; the three native jobs are the explicit owner of native coverage | **Needs a human decision**: branch protection or any required-check list naming the old job must be updated. `quality (py<version>)` is unchanged on purpose | Before the next merge that relies on required checks |
-| `build.yml` no longer runs the portable suite, ruff, or mypy | `ci.yml` owns them explicitly, and `ci.yml` runs on every push including a tag push | Release eligibility now depends on CI for the tag rather than on the build job repeating it. `release.yml` still requires a successful build run | If a release is ever cut from a tag whose CI run did not pass |
 | Per-OS runner behaviour of the new `build.yml` failure graph is unproven | The conditions are checked by a local scenario replay in `tests/test_ci_workflows.py`, not by Actions | Implemented; pending CI confirmation. No push authorization in this run | The next `workflow_dispatch` or tag build |
-| `worker close` became a reported stage | A crash while releasing native handles used to be attributed to the last provider stage | Implemented. The worker report now carries one extra stage | If a consumer parses the stage list positionally |
+| `ci.yml` job names changed: `windows tests (py3.10)` is gone, replaced by `native (windows)`, `native (macos)`, `native (linux)` | The Windows job was a duplicate full suite; the three native jobs are the explicit owner of native coverage | **Needs a human decision**: branch protection or any required-check list naming the old job must be updated. `quality (py<version>)` is unchanged on purpose | Before the next merge that relies on required checks |
+| `build.yml` no longer runs the portable suite, ruff, or mypy | `ci.yml` owns them explicitly and runs on every push, tag pushes included | Release eligibility now leans on CI for the tag rather than on the build job repeating it. `release.yml` still requires a successful build run | If a release is ever cut from a tag whose CI run did not pass |
+| `worker close` became a reported stage, and `window host` another | A crash while releasing native handles used to be attributed to the last provider stage, and a Qt WebEngine import failure to no stage at all | Implemented. The worker report carries one extra stage and the UI report one more | If a consumer parses the stage list positionally |
 | `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |
+| The benchmark RSS fallback read macOS bytes as kibibytes | `getrusage` reports `ru_maxrss` in KiB on Linux and in bytes on the BSDs; the first idle sample read 39 MiB as 39 GiB | Fixed now, with a focused test. Developer instrumentation only; nothing in `packages/` uses it | If `psutil` becomes a declared dependency and the fallback stops being reached |
+| The manual-session idle retirement (60 s) was not timed live | Process-level retirement is proven by the real spawned child; the 60 s expiry is covered by `tests/test_manual_lookup.py` with an injected scheduler | Deferred to a human desktop session | The manual pass below |
 
-## SUPERQA-001-006 dispositions
+## Native evidence still owed to a human session
 
-| ID | Outcome | Evidence |
-| --- | --- | --- |
-| SUPERQA-001 | pending fresh-build validation | |
-| SUPERQA-002 | Implemented | |
-| SUPERQA-003 | Not reproduced | |
-| SUPERQA-004 | Not reproduced (environment), hardened | |
-| SUPERQA-005 | Confirmed and now enforced | |
-| SUPERQA-006 | pending fresh-build measurement | |
+The automated native suite covers desktop startup to `ready`, Control Center
+open/close/reopen through the real window and the real child, the frozen window
+and its bridge, the popup window contract, the Cocoa panel property, real
+process retirement, and the Darwin update handoff. These need a person at the
+keyboard and were **not** performed: capture start/stop, ROI and target
+selection, hotkey lookup, popup retention and dismissal against a real target
+application, a resource update through the Control Center, quit, and relaunch on
+a disposable profile.
 
 ## Next action / blockers
-- Build the macOS artifact from this branch with the 3.10 packaging interpreter,
-  then run the packaged suite, the native UI confirmations, and the SUPERQA-006
-  measurements against it.
+- None. The bundle is at its Review Handoff,
+  `docs/execution/review-handoffs/han-43-44-superqa.md`. Phase B not started.
diff --git a/docs/execution/review-handoffs/han-43-44-superqa.md b/docs/execution/review-handoffs/han-43-44-superqa.md
new file mode 100644
index 0000000..885a6f0
--- /dev/null
+++ b/docs/execution/review-handoffs/han-43-44-superqa.md
@@ -0,0 +1,130 @@
+# HAN-43 / HAN-44 / Super QA Review Handoff
+
+## Bundle
+
+- Member issues: HAN-44 (packaging smoke diagnostics), HAN-43 (platform-specific
+  test restructuring), plus the bounded follow-ups SUPERQA-001–006 from
+  `superqa.md`
+- Implementation ecosystem: Claude Opus 5, directly
+- Date: 2026-09-13
+- Branch: `codex/han-43-44-superqa`, five commits on top of `5f7eb2a`. Nothing
+  pushed; Linear untouched (the MCP server is unauthenticated in this session)
+
+## Implemented
+
+- **Stage progress markers.** `--self-check` writes one flushed JSON line per
+  stage boundary on stderr, covering provider construction, OCR, morphology,
+  dictionary, closing the worker, the Qt WebEngine import, the window, and each
+  page probe. The harness reconstructs `current_stage` from them.
+- **A host fingerprint collector**, `tools/native_host_fingerprint.py`: OS and
+  build, CPU model and vendor, core counts, the build interpreter, and — from a
+  subprocess of its own — what Torch reports about the CPU.
+- **A per-product failure graph in `build.yml`.** Every check states the product
+  it needs, so a failed smoke no longer skips the rest; a `hanly-diagnostics-*`
+  artifact is uploaded whether or not the run succeeded.
+- **Three selectable test suites.** `--suite portable|native|packaged`, excluding
+  a suite before its modules import, with native cases routed into
+  `tests/native/{shared,macos,windows}` and `tests/packaged/shared`.
+- **CI ownership split.** `ci.yml` keeps the portable Python matrix and gains one
+  source-native job per platform; `build.yml` drops the duplicated portable
+  suite, lint, and types, and gains the packaged suite against its own bundle.
+- **Capability honesty.** `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn
+  every capability skip into a failure in the job that exists to exercise it.
+- **Frozen artifact identity.** `--expect-version` makes a bundle report the
+  source version that built it; the artifact record carries the build commit.
+- **A primary-screen check** between Qt initialization and pywebview's window
+  creation, and a process inventory that refuses to answer an empty list when
+  the host will not say what is running.
+
+## Main expected behavior
+
+A failed packaging run now names the stage the process was inside, the machine
+it ran on, and every check that could still be made — `current_stage: ocr; exit:
+ILLEGAL_INSTRUCTION (0xC000001D)` rather than a bare status. A frozen bundle
+that reports a version other than the tree's fails the gate. Each test suite
+runs on the machine it needs, and a native or packaged job that cannot exercise
+its capability fails rather than passing quietly.
+
+## Architecture / seams touched
+
+- `hanly_app.self_check` and `hanly_app.qt_bootstrap` / `control_center_host`
+  (CA-INV-03/04: the guard is a desktop concern, and the engine is untouched).
+- No engine file changed. No provider, `LookupPipeline`, `ResourceManager`, or
+  contract was touched, and no new seam was introduced.
+- `tools/` and `.github/workflows/` are tooling, outside both packages.
+- One developer-instrumentation fix in `benchmarks/dev/probes.py`.
+
+## Relevant files / diff areas
+
+- `packages/hanly-app/src/hanly_app/`: `self_check.py`, `qt_bootstrap.py`,
+  `control_center_host.py`
+- `tools/`: `native_host_fingerprint.py` (new), `smoke_packaged_runtime.py`
+- `.github/workflows/`: `build.yml`, `ci.yml`
+- `conftest.py` (new, repository root), `tests/conftest.py`,
+  `tests/native/**`, `tests/packaged/**`, `tests/hanly_fixtures/`
+  (`capabilities.py`, `process_probe.py`, `update_handoff.py`,
+  `webengine_probe.py`)
+- `benchmarks/dev/probes.py`
+- `packaging/README.md`, `docs/CODE-MAP.md`, `CLAUDE.md`
+
+## Implementation-side validation already run
+
+| Check | Result |
+| --- | --- |
+| `python -m pytest` | 1300 passed, 1 skipped (an opt-in real-EasyOCR KRDICT case) |
+| `python -m ruff check packages packaging tests tools benchmarks` | clean |
+| `python -m mypy packages packaging tests tools benchmarks` | clean, 216 files |
+| `python -m pytest --suite native` | 37 passed, 0 skipped, on a visible macOS session |
+| `python -m pytest --suite packaged` with `HANLY_REQUIRE_PACKAGED=1` | 3 passed against the freshly built bundle |
+| Collected node IDs, before vs. after the routing | every case has an owner; only the two Windows-only cases are not collected on macOS, by design |
+| Fresh macOS build (3.10.20 packaging environment, release constraints) | ZIP, DMG and `Hanly.app` produced; reconstruction, disk image, and inventory all clean |
+| Frozen worker smoke with `--expect-version 0.5.0` | passed; both packages report `0.5.0` |
+| The same check against the stale `0.1.3` bundle on this machine | exits 1, naming both packages |
+| Frozen `--self-check ui` | passed in 2.54 s: window, document, four controls, bridge |
+| SUPERQA-006 measurements | recorded in the ledger; no regression against the stale-artifact figures |
+
+The ledger, `docs/execution/checkpoints/han-43-44-superqa.md`, carries the
+routing inventory, the six dispositions, and the measurement tables.
+
+## Known limitations / intentionally unvalidated areas
+
+- **No CI run.** The `build.yml` failure graph and the three native jobs are
+  checked by a local scenario replay of the step conditions, not by Actions.
+  Nothing was pushed, and no run confirms them.
+- **Windows and Linux native evidence is absent.** `tests/native/windows/` was
+  never collected here, and the Linux job's xvfb display is unexercised.
+- **Job names changed.** `windows tests (py3.10)` no longer exists. Branch
+  protection or any required-check list naming it needs a human decision; no
+  repository setting was touched.
+- **`build.yml` no longer repeats the portable gates**, so release eligibility
+  now leans on CI for the tag.
+- **SUPERQA-001, 003 and 004 did not reproduce here** and no fix was made for
+  them. They were environment-bound in the original report, and this session had
+  the screen, the window server, and the `ps` that one lacked.
+- **The screen guard cannot prevent an abort inside `QApplication` itself.** It
+  runs after construction; that case is covered only by the stage markers.
+- **No human desktop pass.** Capture start/stop, ROI and target selection,
+  hotkey lookup, popup retention and dismissal against a real application, a
+  resource update through the Control Center, quit, and relaunch on a disposable
+  profile were not performed.
+- The idle-retirement timeout (60 s) was not timed live.
+
+## Suggested review targets
+
+- The `build.yml` step conditions: `!cancelled() && steps.X.outcome ==
+  'success'` is the pattern, and the scenario replay in
+  `tests/test_ci_workflows.py` is a model of Actions rather than Actions.
+- `read_progress` and `_describe_exit` in `tools/smoke_packaged_runtime.py` —
+  particularly nested stages and a run that emits a marker and then nothing.
+- Whether `tests/conftest.py` plus the root `conftest.py` really exclude a
+  suite before any of its modules import, on Windows as well as here.
+- The two stages added to the self-check report (`worker close`, `window host`)
+  and any consumer that reads the stage list positionally.
+- `verify_primary_screen`'s placement: whether anything else reaches Qt geometry
+  before it, and whether the shell's own paths want the same check.
+- `tests/hanly_fixtures/update_handoff.py`: the scaffolding moved out of a test
+  module, and whether the portable half still covers what it used to.
+
+## Review assignment
+
+Human-selected after implementation. Not started.
`````

### 8.7 `1f8354a` — fix: record the two host fingerprint fields the issue names

`````diff
diff --git a/tests/test_host_fingerprint.py b/tests/test_host_fingerprint.py
index 5355ae7..1e0bcba 100644
--- a/tests/test_host_fingerprint.py
+++ b/tests/test_host_fingerprint.py
@@ -42,6 +42,7 @@ WINDOWS_RECORDS = {
         "Caption": "Microsoft Windows Server 2022 Datacenter",
         "Version": "10.0.20348",
         "BuildNumber": "20348",
+        "OSArchitecture": "64-bit",
     },
     "cpu": {
         "Name": "AMD EPYC 7763 64-Core Processor",
@@ -125,6 +126,10 @@ def test_windows_reads_one_cim_query_for_both_groups() -> None:
     operating_system, cpu = windows_facts(lambda _: json.dumps(WINDOWS_RECORDS))
 
     assert operating_system.values["build"] == "20348"
+    # The OS bitness and the processor architecture are different questions,
+    # and a heterogeneous runner fleet can disagree on both.
+    assert operating_system.values["architecture"] == "64-bit"
+    assert cpu.values["architecture"]
     assert cpu.values["model"] == "AMD EPYC 7763 64-Core Processor"
     assert cpu.values["vendor"] == "AuthenticAMD"
     assert cpu.values["physical_cores"] == 2
@@ -208,6 +213,9 @@ def test_this_host_reports_the_fields_a_crash_report_needs() -> None:
     assert group("build_interpreter")["version"] == ".".join(
         str(part) for part in sys.version_info[:3]
     )
+    # The frozen/not-frozen context is stated rather than left to be assumed:
+    # this tool runs from source, and the self-check answers for the bundle.
+    assert group("build_interpreter")["frozen"] is False
     assert "torch" not in document
 
 
diff --git a/tools/native_host_fingerprint.py b/tools/native_host_fingerprint.py
index fbebf14..26124d5 100644
--- a/tools/native_host_fingerprint.py
+++ b/tools/native_host_fingerprint.py
@@ -235,6 +235,9 @@ def windows_facts(run: TextRunner) -> tuple[Facts, Facts]:
     operating_system.record("name", field_of("os", "Caption"))
     operating_system.record("product_version", field_of("os", "Version"))
     operating_system.record("build", field_of("os", "BuildNumber"))
+    # The operating system's own bitness, which is not the processor's:
+    # ``cpu.architecture`` answers that one.
+    operating_system.record("architecture", field_of("os", "OSArchitecture"))
 
     cpu = _portable_cpu()
     cpu.record("model", field_of("cpu", "Name"))
@@ -299,6 +302,9 @@ def _build_interpreter() -> dict[str, object]:
         "version": platform.python_version(),
         "implementation": platform.python_implementation(),
         "executable": sys.executable,
+        # Always false in a packaging job, and stated rather than assumed: the
+        # frozen side of the comparison is the self-check's own report.
+        "frozen": bool(getattr(sys, "frozen", False)),
     }
 
 
`````

### 8.8 `ba87cce` — chore: record the acceptance check against the issues themselves

`````diff
diff --git a/docs/execution/checkpoints/han-43-44-superqa.md b/docs/execution/checkpoints/han-43-44-superqa.md
index 1e16e5f..d4f9777 100644
--- a/docs/execution/checkpoints/han-43-44-superqa.md
+++ b/docs/execution/checkpoints/han-43-44-superqa.md
@@ -10,9 +10,11 @@
   `packaging/release-constraints.txt`, outside the repository. It is the interpreter
   `build.yml` uses, not `.venv`.
 - Scope: HAN-44, HAN-43, SUPERQA-001–006
-- Linear: not reachable from this session (the MCP Linear server is unauthenticated).
-  No issue state was changed and no comment was posted. Status progression for HAN-43
-  and HAN-44 is pending human action.
+- Linear: connected mid-session. HAN-43 and HAN-44 were read directly only after
+  implementation — the work was built against the patch plan's summary of them. Both
+  were re-checked against their real acceptance criteria afterwards; the two fields
+  that were missing are closed in `1f8354a`, and the one scope note (no native hotkey
+  coverage exists to route) is in the handoff.
 
 ## Checkpoints
 | Patch | State | Main changes | Check and result | Commit |
@@ -96,6 +98,8 @@ idle retirement, or any change to the `LookupPreload` default.
 | `worker close` became a reported stage, and `window host` another | A crash while releasing native handles used to be attributed to the last provider stage, and a Qt WebEngine import failure to no stage at all | Implemented. The worker report carries one extra stage and the UI report one more | If a consumer parses the stage list positionally |
 | `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |
 | The benchmark RSS fallback read macOS bytes as kibibytes | `getrusage` reports `ru_maxrss` in KiB on Linux and in bytes on the BSDs; the first idle sample read 39 MiB as 39 GiB | Fixed now, with a focused test. Developer instrumentation only; nothing in `packages/` uses it | If `psutil` becomes a declared dependency and the fallback stops being reached |
+| No native hotkey coverage exists to route | HAN-43 names hotkeys as a pain area, but `test_hotkeys.py` and `test_hotkeys_darwin.py` drive doubles and never register a real hotkey | Reported, not written: new coverage rather than restructuring | If a hotkey regression reaches a release again |
+| `tests/native/linux/` is absent | No case is Linux-only; an empty suite is a gate that asked nothing | Deliberate. HAN-43 names Linux-specific suites, so this reading is worth a second opinion | When a genuinely Linux-only case appears |
 | The manual-session idle retirement (60 s) was not timed live | Process-level retirement is proven by the real spawned child; the 60 s expiry is covered by `tests/test_manual_lookup.py` with an injected scheduler | Deferred to a human desktop session | The manual pass below |
 
 ## Native evidence still owed to a human session
diff --git a/docs/execution/review-handoffs/han-43-44-superqa.md b/docs/execution/review-handoffs/han-43-44-superqa.md
index 885a6f0..c64edcb 100644
--- a/docs/execution/review-handoffs/han-43-44-superqa.md
+++ b/docs/execution/review-handoffs/han-43-44-superqa.md
@@ -7,8 +7,8 @@
   `superqa.md`
 - Implementation ecosystem: Claude Opus 5, directly
 - Date: 2026-09-13
-- Branch: `codex/han-43-44-superqa`, five commits on top of `5f7eb2a`. Nothing
-  pushed; Linear untouched (the MCP server is unauthenticated in this session)
+- Branch: `codex/han-43-44-superqa`, seven commits on top of `5f7eb2a`. Nothing
+  pushed
 
 ## Implemented
 
@@ -86,6 +86,48 @@ its capability fails rather than passing quietly.
 The ledger, `docs/execution/checkpoints/han-43-44-superqa.md`, carries the
 routing inventory, the six dispositions, and the measurement tables.
 
+## Acceptance criteria, checked against the issues themselves
+
+The issues were read directly only after implementation; the work was built
+against the patch plan's summary of them. Re-checked afterwards, line by line.
+
+**HAN-44** — all four required updates are met.
+
+| Required update | Evidence |
+| --- | --- |
+| 1. Independent post-build smokes continue after one fails | Per-step `!cancelled() && steps.X.outcome == 'success'`; five scenario replays in `tests/test_ci_workflows.py`; no `continue-on-error` anywhere, asserted |
+| 2. Diagnostics retained on a failed job | `hanly-diagnostics-<platform>` uploads on `!cancelled()` with every report the issue lists, plus PyInstaller `warn-*`/`xref-*` and both smokes' captured stdout/stderr. Release products stay success-only |
+| 3. Compact cross-platform host fingerprint | `tools/native_host_fingerprint.py`, persisted for all three platforms. Every field the issue names is present |
+| 4. `stage_started` persisted before native work | Flushed marker per stage; the failure line is `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)`; completed-stage timings unchanged on success |
+
+Two fields the issue names were missing on the first pass and were added in
+`1f8354a`: the frozen/not-frozen context, and the Windows `OSArchitecture` the
+CIM query already selected and then discarded.
+
+**HAN-43** — every stated goal is met, with one scope note.
+
+Shared portable tests stay shared; native tests sit under OS suites; packaging
+smoke is split where behaviour differs; contracts are tested once and adapters
+per platform; no `sys.platform` branching was introduced; no suite is duplicated
+per OS; build and fast CI are separate; native jobs run in parallel with no
+`needs` and `fail-fast: false`.
+
+Of the six pain areas the issue says to start with, five are routed: frozen
+packaging smoke, Control Center lifecycle, subprocess/process probes, Qt/native
+dependencies, and updater handoff. **Hotkeys are the exception, and not because
+they were skipped**: `test_hotkeys.py` and `test_hotkeys_darwin.py` drive
+doubles (`_Listener`, `_FakeCarbon`, a patched `sys.platform`) and never touch a
+real registration, so they are correctly portable and there was nothing to
+route. The gap is that **no native hotkey coverage exists at all** — no test
+registers a real Carbon hotkey on macOS or a real pynput one on Windows or
+Linux. Writing that is new coverage rather than restructuring, so it was not
+done here.
+
+`tests/native/linux/` is also absent: no case is Linux-only today. The issue
+names Linux-specific suites, so this is a deliberate reading of "avoid
+duplicating the entire test suite per OS" plus "do not create empty suites", and
+is worth a second opinion.
+
 ## Known limitations / intentionally unvalidated areas
 
 - **No CI run.** The `build.yml` failure graph and the three native jobs are
`````
