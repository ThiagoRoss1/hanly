# HAN-43, HAN-44 and Super QA — implementation review report

> **Historical:** sections 1–7 preserve the review findings. Section 8 lists
> the eight commits; its duplicated diff was removed on 2026-09-29. Current
> behavior is documented in `docs/CODE-MAP.md` and `docs/architecture/`.

**Prepared:** 2026-09-13
**Branch:** `codex/han-43-44-superqa`, eight commits on top of `main` at `5f7eb2a`
**Executor:** Claude Opus 5, directly (Phase A only)
**Plan followed:** `docs/execution/plans/2026-09-13-han-43-44-superqa.md`
**Status:** implementation complete; stopped at the Review Handoff. Phase B not started.
Nothing pushed, nothing merged, no tag.

This document exists for a later reviewer. It is not the session ledger
(`docs/execution/checkpoints/han-43-44-superqa.md`) and not the Review Handoff
(`docs/execution/review-handoffs/han-43-44-superqa.md`); it repeats what those
two carry only where a reviewer would otherwise have to open them. The diff
it once embedded is available in Git history instead.

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

The per-commit diffs remain available in Git history at the eight commits listed above. They are omitted here because they duplicate the repository and obscure the review findings.
