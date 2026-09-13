# HAN-43 / HAN-44 / Super QA Review Handoff

## Bundle

- Member issues: HAN-44 (packaging smoke diagnostics), HAN-43 (platform-specific
  test restructuring), plus the bounded follow-ups SUPERQA-001–006 from
  `superqa.md`
- Implementation ecosystem: Claude Opus 5, directly
- Date: 2026-09-13
- Branch: `codex/han-43-44-superqa`, seven commits on top of `5f7eb2a`. Nothing
  pushed

## Implemented

- **Stage progress markers.** `--self-check` writes one flushed JSON line per
  stage boundary on stderr, covering provider construction, OCR, morphology,
  dictionary, closing the worker, the Qt WebEngine import, the window, and each
  page probe. The harness reconstructs `current_stage` from them.
- **A host fingerprint collector**, `tools/native_host_fingerprint.py`: OS and
  build, CPU model and vendor, core counts, the build interpreter, and — from a
  subprocess of its own — what Torch reports about the CPU.
- **A per-product failure graph in `build.yml`.** Every check states the product
  it needs, so a failed smoke no longer skips the rest; a `hanly-diagnostics-*`
  artifact is uploaded whether or not the run succeeded.
- **Three selectable test suites.** `--suite portable|native|packaged`, excluding
  a suite before its modules import, with native cases routed into
  `tests/native/{shared,macos,windows}` and `tests/packaged/shared`.
- **CI ownership split.** `ci.yml` keeps the portable Python matrix and gains one
  source-native job per platform; `build.yml` drops the duplicated portable
  suite, lint, and types, and gains the packaged suite against its own bundle.
- **Capability honesty.** `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn
  every capability skip into a failure in the job that exists to exercise it.
- **Frozen artifact identity.** `--expect-version` makes a bundle report the
  source version that built it; the artifact record carries the build commit.
- **A primary-screen check** between Qt initialization and pywebview's window
  creation, and a process inventory that refuses to answer an empty list when
  the host will not say what is running.

## Main expected behavior

A failed packaging run now names the stage the process was inside, the machine
it ran on, and every check that could still be made — `current_stage: ocr; exit:
ILLEGAL_INSTRUCTION (0xC000001D)` rather than a bare status. A frozen bundle
that reports a version other than the tree's fails the gate. Each test suite
runs on the machine it needs, and a native or packaged job that cannot exercise
its capability fails rather than passing quietly.

## Architecture / seams touched

- `hanly_app.self_check` and `hanly_app.qt_bootstrap` / `control_center_host`
  (CA-INV-03/04: the guard is a desktop concern, and the engine is untouched).
- No engine file changed. No provider, `LookupPipeline`, `ResourceManager`, or
  contract was touched, and no new seam was introduced.
- `tools/` and `.github/workflows/` are tooling, outside both packages.
- One developer-instrumentation fix in `benchmarks/dev/probes.py`.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/`: `self_check.py`, `qt_bootstrap.py`,
  `control_center_host.py`
- `tools/`: `native_host_fingerprint.py` (new), `smoke_packaged_runtime.py`
- `.github/workflows/`: `build.yml`, `ci.yml`
- `conftest.py` (new, repository root), `tests/conftest.py`,
  `tests/native/**`, `tests/packaged/**`, `tests/hanly_fixtures/`
  (`capabilities.py`, `process_probe.py`, `update_handoff.py`,
  `webengine_probe.py`)
- `benchmarks/dev/probes.py`
- `packaging/README.md`, `docs/CODE-MAP.md`, `CLAUDE.md`

## Implementation-side validation already run

| Check | Result |
| --- | --- |
| `python -m pytest` | 1300 passed, 1 skipped (an opt-in real-EasyOCR KRDICT case) |
| `python -m ruff check packages packaging tests tools benchmarks` | clean |
| `python -m mypy packages packaging tests tools benchmarks` | clean, 216 files |
| `python -m pytest --suite native` | 37 passed, 0 skipped, on a visible macOS session |
| `python -m pytest --suite packaged` with `HANLY_REQUIRE_PACKAGED=1` | 3 passed against the freshly built bundle |
| Collected node IDs, before vs. after the routing | every case has an owner; only the two Windows-only cases are not collected on macOS, by design |
| Fresh macOS build (3.10.20 packaging environment, release constraints) | ZIP, DMG and `Hanly.app` produced; reconstruction, disk image, and inventory all clean |
| Frozen worker smoke with `--expect-version 0.5.0` | passed; both packages report `0.5.0` |
| The same check against the stale `0.1.3` bundle on this machine | exits 1, naming both packages |
| Frozen `--self-check ui` | passed in 2.54 s: window, document, four controls, bridge |
| SUPERQA-006 measurements | recorded in the ledger; no regression against the stale-artifact figures |

The ledger, `docs/execution/checkpoints/han-43-44-superqa.md`, carries the
routing inventory, the six dispositions, and the measurement tables.

## Acceptance criteria, checked against the issues themselves

The issues were read directly only after implementation; the work was built
against the patch plan's summary of them. Re-checked afterwards, line by line.

**HAN-44** — all four required updates are met.

| Required update | Evidence |
| --- | --- |
| 1. Independent post-build smokes continue after one fails | Per-step `!cancelled() && steps.X.outcome == 'success'`; five scenario replays in `tests/test_ci_workflows.py`; no `continue-on-error` anywhere, asserted |
| 2. Diagnostics retained on a failed job | `hanly-diagnostics-<platform>` uploads on `!cancelled()` with every report the issue lists, plus PyInstaller `warn-*`/`xref-*` and both smokes' captured stdout/stderr. Release products stay success-only |
| 3. Compact cross-platform host fingerprint | `tools/native_host_fingerprint.py`, persisted for all three platforms. Every field the issue names is present |
| 4. `stage_started` persisted before native work | Flushed marker per stage; the failure line is `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)`; completed-stage timings unchanged on success |

Two fields the issue names were missing on the first pass and were added in
`1f8354a`: the frozen/not-frozen context, and the Windows `OSArchitecture` the
CIM query already selected and then discarded.

**HAN-43** — every stated goal is met, with one scope note.

Shared portable tests stay shared; native tests sit under OS suites; packaging
smoke is split where behaviour differs; contracts are tested once and adapters
per platform; no `sys.platform` branching was introduced; no suite is duplicated
per OS; build and fast CI are separate; native jobs run in parallel with no
`needs` and `fail-fast: false`.

Of the six pain areas the issue says to start with, five are routed: frozen
packaging smoke, Control Center lifecycle, subprocess/process probes, Qt/native
dependencies, and updater handoff. **Hotkeys are the exception, and not because
they were skipped**: `test_hotkeys.py` and `test_hotkeys_darwin.py` drive
doubles (`_Listener`, `_FakeCarbon`, a patched `sys.platform`) and never touch a
real registration, so they are correctly portable and there was nothing to
route. The gap is that **no native hotkey coverage exists at all** — no test
registers a real Carbon hotkey on macOS or a real pynput one on Windows or
Linux. Writing that is new coverage rather than restructuring, so it was not
done here.

`tests/native/linux/` is also absent: no case is Linux-only today. The issue
names Linux-specific suites, so this is a deliberate reading of "avoid
duplicating the entire test suite per OS" plus "do not create empty suites", and
is worth a second opinion.

## Known limitations / intentionally unvalidated areas

- **No CI run.** The `build.yml` failure graph and the three native jobs are
  checked by a local scenario replay of the step conditions, not by Actions.
  Nothing was pushed, and no run confirms them.
- **Windows and Linux native evidence is absent.** `tests/native/windows/` was
  never collected here, and the Linux job's xvfb display is unexercised.
- **Job names changed.** `windows tests (py3.10)` no longer exists. Branch
  protection or any required-check list naming it needs a human decision; no
  repository setting was touched.
- **`build.yml` no longer repeats the portable gates**, so release eligibility
  now leans on CI for the tag.
- **SUPERQA-001, 003 and 004 did not reproduce here** and no fix was made for
  them. They were environment-bound in the original report, and this session had
  the screen, the window server, and the `ps` that one lacked.
- **The screen guard cannot prevent an abort inside `QApplication` itself.** It
  runs after construction; that case is covered only by the stage markers.
- **No human desktop pass.** Capture start/stop, ROI and target selection,
  hotkey lookup, popup retention and dismissal against a real application, a
  resource update through the Control Center, quit, and relaunch on a disposable
  profile were not performed.
- The idle-retirement timeout (60 s) was not timed live.

## Suggested review targets

- The `build.yml` step conditions: `!cancelled() && steps.X.outcome ==
  'success'` is the pattern, and the scenario replay in
  `tests/test_ci_workflows.py` is a model of Actions rather than Actions.
- `read_progress` and `_describe_exit` in `tools/smoke_packaged_runtime.py` —
  particularly nested stages and a run that emits a marker and then nothing.
- Whether `tests/conftest.py` plus the root `conftest.py` really exclude a
  suite before any of its modules import, on Windows as well as here.
- The two stages added to the self-check report (`worker close`, `window host`)
  and any consumer that reads the stage list positionally.
- `verify_primary_screen`'s placement: whether anything else reaches Qt geometry
  before it, and whether the shell's own paths want the same check.
- `tests/hanly_fixtures/update_handoff.py`: the scaffolding moved out of a test
  module, and whether the portable half still covers what it used to.

## Review assignment

Human-selected after implementation. Not started.
