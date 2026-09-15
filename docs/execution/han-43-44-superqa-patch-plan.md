# HAN-43, HAN-44, and Super QA — Claude execution plan

Prepared 2026-09-13. **Planning only; implementation and testing belong to Claude.**

Execute the three parts below in one Claude session and one branch, in the listed order: **HAN-44 → HAN-43 → Super QA**. Diagnostics come first so the restructuring and native follow-ups produce useful failure evidence. These are three separately checked patch areas within one bundle, not three independent execution runs.

## Scope and evidence

- [HAN-44 — Improve packaging smoke diagnostics and failure visibility](https://linear.app/hmx-gen-projects/issue/HAN-44/improve-packaging-smoke-diagnostics-and-failure-visibility): four required diagnostic improvements; High priority.
- [HAN-43 — Restructure platform-specific smoke/build tests](https://linear.app/hmx-gen-projects/issue/HAN-43/restructure-platform-specific-smokebuild-tests): portable/native/build separation; Medium priority.
- [superqa.md](../../superqa.md): existing investigation and six findings. Follow its evidence and bounded follow-up order; do not repeat the broad QA audit.

Both Linear issues were Backlog, related to each other, with no blocking relationships or comments when read. The human explicitly selected both for this bundle, superseding their earlier separate scheduling. Recheck for newly introduced real blockers before implementation.

Planning checkout: local `main`, HEAD and locally recorded `origin/main` both `5f7eb2af68ab7883ec5f43525e00fd325867fd49`. This was a local comparison, not a fresh remote fetch. `superqa.md` was the only untracked file before this plan was added. Its evidence is older: source `900dba1` / v0.5.0, but the tested bundle reported v0.1.3. Do not reset to that historical commit or treat that bundle as current release evidence.

Read `CLAUDE.md`, `docs/CODE-MAP.md`, architecture `01`–`04`, and `docs/execution/05-execution-plan.md` before executing. This is the bundle plan required by `05`; do not add another plan, mandatory reviewer chain, or repeated QA cycle. Proposed tiers: HAN-44 Standard, HAN-43 Gate (CI coverage convergence), Super QA Gate (native UI and artifact validation). Claude is the direct executor by default.

### Start: local branch and session record

1. Inspect `git status --short --branch`, `git branch --show-current`, and `git rev-parse HEAD main`. Preserve all existing user work. If another branch is active, inspect before switching; never discard changes to satisfy this plan.
2. From the actual local `main`, create **`codex/han-43-44-superqa`** with `git switch -c codex/han-43-44-superqa main`. Use the current checkout, not a fresh clone, remote checkout, or clean worktree: the uncommitted QA report and this plan must carry over. Do not pull, reset, clean, or stash them away. If the branch already exists, inspect whether this is a resume; never overwrite it.
3. Create **`docs/execution/checkpoints/han-43-44-superqa.md`** before code changes. Use the short template below. Update it after each meaningful patch/checkpoint, not after every command. Include this plan, the unchanged QA report, and the ledger in the first patch commit so the context is durable.
4. Recheck Linear readiness; use the normal `Todo` / `In Progress` progression for each issue when actionable and active, then `In Review` only at the completed handoff. Do not mark `Done`, invent blockers, or create a Super QA parent issue. Keep Super QA findings granular in the ledger. Do not send unsolicited Linear comments or other messages; draft any proposed status summary in the ledger unless the human authorizes posting it.
5. Confirm `.venv` is the intended local interpreter and the available native display/process capabilities. Use Python 3.10-compatible code. No baseline full-suite rerun is necessary: use the existing logs and run focused checks for changed behavior.

```markdown
# HAN-43 / HAN-44 / Super QA session updates

## Session
- Branch / base SHA:
- Interpreter / OS / display and process-inspection availability:
- Scope: HAN-44, HAN-43, SUPERQA-001–006

## Checkpoints
| Patch | State | Main changes | Check and result | Commit |
| --- | --- | --- | --- | --- |
| HAN-44 | Pending | | | |
| HAN-43 | Pending | | | |
| Super QA | Pending | | | |

## Observations for future review
| Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
| --- | --- | --- | --- |

## Next action / blockers
- Exact next step; omit when complete.
```

Use `Implemented`, `Validated`, `Environment-blocked`, `Not reproduced`, or `Deferred` precisely. Do not imply a deep review has occurred. Record each commit SHA in the next ledger update; no amend loop just to put a commit's own hash inside itself.

### Commit policy — explicitly authorized by the human

Commit **after every coherent patch**, following its focused checks. Normally one commit for HAN-44, one for HAN-43, and one or more for the bounded Super QA fixes. Do not combine everything into one final commit or create empty commits for unconfirmed defects.

Titles must start with `fix:`, `feat:`, or `chore:` and briefly name the update. Bodies contain only brief main-topic bullets, for example:

```text
fix: preserve packaging smoke diagnostics on failure

- Updates host fingerprints and self-check stage reporting.
- Fixes skipped independent smokes and missing failure artifacts.
```

Use only applicable `- Updates ...` / `- Fixes ...` bullets; do not invent a fix to fill a template. **No `Co-authored-by:`, `Co-authorized by Claude`, Claude attribution, generated-by footer, or other agent credit anywhere in any commit message.** Disable automatic attribution for these commits without changing the user's global Git configuration. Inspect the exact message before committing and the resulting message afterward. Stage explicit paths, inspect the staged diff, and exclude generated bundles, logs, caches, and unrelated work. A final documentation-only commit may record the handoff. No push, tag, release, or merge is authorized here.

## Part 1 — HAN-44: make one failed packaging run informative

### Incident and current implementation

A Windows smoke died with `STATUS_ILLEGAL_INSTRUCTION (0xC000001D)`; a rerun passed. CPU/ISA differences remain a hypothesis, not a diagnosis. Recent code already names Windows fatal statuses and enables `faulthandler`; retain that work.

`.github/workflows/build.yml` already has three OS matrix entries with `fail-fast: false`. The missing independence is inside each job: default success conditions skip later smokes and the sole artifact upload after a failure. macOS archive reconstruction, DMG verification, and inventory currently share one step. `self_check._stage` records outcomes only after actions return, and `tools/smoke_packaged_runtime.py` receives no started-stage evidence after a native abort.

### Execute

1. Give prerequisite steps stable IDs and apply explicit post-build conditions. Use `always()` with successful prerequisite outcomes and a cancellation guard; do not use blanket `continue-on-error`. Keep required failed steps red. Split the coupled macOS reconstruction/DMG/inventory work enough that a bad DMG does not suppress a valid ZIP's worker/UI checks.

   | Check | Actual prerequisite |
   | --- | --- |
   | Resolve/reconstruct application | Successful application/product build; ZIP available on macOS |
   | Inventory | Resolved application |
   | Worker smoke | Resolved application and generated smoke dictionary |
   | UI smoke | Resolved application and usable display; no worker dependency |
   | DMG inspection / archive existence and size / artifact identity | Their own produced files; no smoke dependency |
   | Diagnostic upload | Always when evidence exists, including failed builds |
   | Release-product upload | All required checks successful |

   Keep artifact existence guards honest: absent required products must still be reported as failures. `run_build` currently includes archive creation; do not treat a failed freeze as a usable application. Avoid a general workflow orchestration framework.

2. Add a separate, failure-safe diagnostics upload per platform, retaining worker/window reports, inventory/product/identity reports, the host fingerprint, and available PyInstaller warning/build output from `dist/.pyinstaller/<platform>/`. Retain bounded stdout/stderr evidence when JSON is absent. Keep current release artifact names and their consumer contract intact; inspect `.github/workflows/release.yml`, `tools/release_build.py`, and `tests/test_release_build.py` before changing artifact contents. Diagnostic artifacts must not become release products.

3. Add a small tooling-owned host-fingerprint collector, preferably `tools/native_host_fingerprint.py`. Write base OS/version/build, architecture, CPU model/vendor, logical cores, optional physical cores, Python, and collection context early. Supplement with Torch version and available CPU/backend capability information after dependencies install. Use bounded OS probes: Windows CIM, macOS `sysctl`/`sw_vers`, Linux `/proc/cpuinfo` and OS metadata. Missing optional fields carry an unavailable reason, not fabricated defaults. Do not dump environment variables or machine-wide process inventories.

   Keep Torch probing in a bounded subprocess so an import crash cannot erase the base fingerprint or prevent independent smokes. Label build-interpreter information separately from frozen-runtime information; reuse self-check version data for the latter. Do not import Torch into the persistent desktop shell for diagnostics.

4. Before every `_stage` action, emit a structured `stage_started` marker and flush it. A prefixed JSON line on **stderr** is sufficient and leaves the existing final stdout JSON parser intact. Emit matching completion events so the harness can distinguish completed work from the active stage, including nested UI probes. Parse markers from the full captured stream before truncating diagnostic tails. Preserve completed-stage timing/details and the final JSON shape; add `current_stage`/progress evidence without replacing existing results.

   Cover provider construction, OCR, morphology, dictionary, and Qt window startup. If native cleanup or version probing can run outside those stages, give it an explicit marker too; never blame the last successful OCR stage for a later cleanup crash. Preserve exit status, timeout, stderr, and `faulthandler` output. A crash before any marker remains explicitly unknown. No crash recovery or retries.

5. Update the harness's failure description to combine the active stage with the existing exit decoder, e.g. `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)`. Keep progress collection inside self-check/tooling paths, with no alternate desktop entry point and no engine changes.

### Focused acceptance and checkpoint

- Extend the existing packaging/self-check tests around `tests/test_packaging.py`: marker survives a deliberately terminated child, successful JSON still parses, completed timings remain, and stage plus fatal status/timeout are shown correctly. Use a tiny helper subprocess for the crash case, not a real crashing OCR workload.
- Check workflow prerequisite cases: worker failure still permits UI/archive/identity; dictionary failure skips worker but permits UI; reconstruction failure does not suppress independent DMG evidence; build failure suppresses dependent smokes; diagnostic upload remains reachable and required failure remains red. Validate conditions with focused workflow tests or a small scenario check; do not call YAML parsing alone proof of Actions behavior.
- Run the fingerprint on the available host and exercise other platform parsers with fixtures. Actual per-OS runner evidence remains a native validation item.
- Update `packaging/README.md` for diagnostic outputs. Record checkpoint and commit, suggested title: **`fix: preserve packaging smoke diagnostics on failure`**.

## Part 2 — HAN-43: separate portable contracts from native execution

### Problem and chosen structure

Today `ci.yml` runs the entire suite on Linux across Python 3.10–3.13 and again on Windows 3.10. `build.yml` repeats the full suite/lint/types with the runtime extra installed before freezing. Optional imports and host capabilities therefore change which native tests run inside otherwise shared jobs. No separate macOS source-native CI job exists.

Keep portable tests shared. Separate only tests that genuinely execute OS/native behavior; a mocked Darwin API test can remain portable. Do not copy the whole suite into three directories.

### Execute

1. Make a short routing inventory in the existing ledger for the affected files: `tests/integration/test_{packaged_desktop,control_center_layout,control_center_lifecycle,webengine_startup,desktop_startup,lookup_process_spawn}.py`, `tests/test_qt_popup_window.py`, `tests/test_hotkeys*.py`, `tests/test_app_update_handoff.py`, and `tests/hanly_fixtures/process_probe.py`. Identify pure versus real-native cases before moving anything.
2. Keep ordinary engine/unit/contract/tooling tests in their current locations and `benchmarks/dev/tests` in its existing location. Use this bounded layout for the native cases:

   ```text
   tests/native/shared/          # real Qt/child-process behavior shared across OSes
   tests/native/windows/         # actual Windows adapters and handoff behavior
   tests/native/macos/           # Cocoa, LaunchServices, Darwin-specific behavior
   tests/native/linux/           # X11/platform-plugin and Linux-native behavior
   tests/packaged/shared/        # frozen worker/UI contracts, one implementation
   tests/packaged/<os>/          # only genuinely distinct product/native checks
   tests/hanly_fixtures/         # shared deterministic helpers
   ```

   Do not create empty suites or gratuitously move portable files. Extract native cases from mixed files, preserving pure parametrized tests of platform decisions. Avoid new generic test bodies full of `sys.platform` branches; small platform fixtures/adapters are appropriate.
3. Provide explicit portable/native/packaged suite selection, registered pytest markers where useful, and OS selection **before incompatible native modules import**. A marker deselected after module import is insufficient. Keep `python -m pytest` as the documented full local gate; add explicit selection for fast CI. Adapt fixture scope, asset paths, imports, and moved node references without weakening assertions. Offscreen Qt tests may exercise widget contracts but cannot satisfy a visible native-window gate.
4. In `ci.yml`, keep the fast shared Python-version matrix for portable coverage/lint/types. Replace the duplicate full Windows suite with independent Windows/macOS/Linux source-native jobs using the actual runtime dependencies and required OS libraries/display setup. Run shared native contracts plus the host's native cases in each applicable job. Use `fail-fast: false`; do not make native jobs wait for other OS jobs or for a frozen build.
5. Keep the deliberate `build.yml` dispatch/tag workflow and its three parallel platform builds. Remove redundant full portable-suite/lint/type execution from packaging jobs once its owner is explicit in CI. Retain build-specific prerequisite checks, real frozen worker/UI checks, and published-product checks. Preserve HAN-44's failure graph and diagnostics. Do not make a release eligible without required quality/native/build evidence: preserve existing release gates and document any branch-protection check-name changes for the human; do not silently edit repository settings.
6. Required native/build jobs must fail or explicitly block when their dependencies, display, artifact, or process inspection are missing. Local unsupported-environment skips need precise reasons and cannot count as acceptance. Remove stale-bundle compatibility skips from required packaged validation. Do not globally skip macOS, popup, updater, or WebEngine coverage to make CI green.

### Focused acceptance and checkpoint

- Compare collected test cases before/after routing, accounting for moved node IDs. Every affected case has an owner; no coverage silently disappears and no portable suite is cloned per OS.
- Prove portable selection does not import real GUI/native dependencies. Prove each native selection includes shared cases plus its OS cases and that missing required capabilities cannot yield an all-skipped green gate.
- Run the affected portable tests and available native cases once. Verify updated workflow syntax, dependency ownership, and the retained HAN-44 failure scenarios only where this refactor changes them.
- Update test commands in `packaging/README.md` and relevant repository guidance; update `docs/CODE-MAP.md` only for changed paths. Record routing and unavailable-host checks in the ledger. Commit, suggested title: **`chore: separate portable native and packaged test suites`**.

## Part 3 — Super QA: close evidence gaps and fix confirmed native boundaries

### Findings and bounded dispositions

| Finding | What the existing log establishes | Work in this patch |
| --- | --- | --- |
| SUPERQA-001 | Frozen UI aborts during Qt construction in a screenless/sandboxed session; no final JSON | Preserve stage/exit evidence through HAN-44; validate source and freshly built UI on a visible macOS desktop; fix only a reproduced boundary defect |
| SUPERQA-002 | pywebview receives no primary screen and reaches unsafe geometry access | Add a narrow no-screen guard after successful Qt bootstrap and before webview window creation; validate an ordinary screen still works |
| SUPERQA-003 | Cocoa popup aborts at the Objective-C bridge in that environment | Verify visible-screen behavior; if reproduced, correct native-window readiness/bridge usage without losing non-activation |
| SUPERQA-004 | Sandbox denies `ps`; lifecycle/leak and Darwin handoff evidence is unavailable | Report inspection unavailable accurately in the harness; verify real process retirement and updater handoff outside that sandbox |
| SUPERQA-005 | Tested bundle says v0.1.3 while tested source says v0.5.0 | Fresh build from this branch and enforce source/package/artifact identity agreement |
| SUPERQA-006 | Old frozen artifact has expensive cold worker startup and large disk footprint | Measure current cold/warm/residency/size once after UI works; compare existing evidence before selecting any runtime change |

### Execute

1. **Establish current artifact identity (005) before accepting new frozen evidence.** Inspect `tools/release_version.py`, package manifests, PyInstaller metadata collection, and existing identity reports. Extend the existing smoke/build verification to compare both frozen package versions with the expected source product version; record build commit and archive hashes in artifact identity. Version mismatch or missing required identity must fail the required gate. Do not “fix” the report by hardcoding `0.5.0`, changing the report to match an old bundle, or bumping versions without a release request. A hash of the archive is useful evidence but does not alone prove its source commit.
2. **Handle the known no-screen boundary (001/002).** In `hanly_app/qt_bootstrap.py` / `control_center_host.py`, check for a usable primary screen after Qt successfully initializes and before pywebview reaches geometry/window creation. Raise/report the existing `ControlCenterUnavailable` condition. Add focused missing-screen and normal-screen tests. A check after `QApplication` construction cannot prevent an abort inside its constructor: retain the HAN-44 parent diagnostics for that case and do not claim universal graceful recovery. Do not select an alternate GUI backend or pin/downgrade Qt/pywebview unless visible-screen evidence actually establishes an incompatibility.
3. **Validate and, if necessary, fix the Cocoa bridge (003).** Run the relocated popup-native checks in a normal visible macOS session. Current `QtPopupView._keep_visible_when_inactive` already guards `darwin` and the `cocoa` platform; do not repeat that fix. If the fault persists, isolate whether `winId()` has a real native window at construction or the typed selector call is wrong. Prefer applying the property once the native window exists, with a narrowly guarded readiness result, over replacing the whole adapter. Never message an arbitrary/offscreen handle or expect Python `try/except` to catch an Objective-C abort. If the optional native adjustment is unavailable, report it and keep safe Qt behavior; explicitly verify non-activation and inactive visibility before claiming the feature preserved.
4. **Distinguish unavailable inspection from success (004).** Update `tests/hanly_fixtures/process_probe.py` and its consumers to report permission denial, missing probe tools, and timeout as inspection unavailable, never as an empty process list or a proven leak. Reuse an existing supported process API only if it preserves required PID/parent/command information; no new process-management framework. Local unsupported environments may skip with the reason; required native jobs must remain unsuccessful when they cannot verify retirement.

   Retest Darwin `app_update_handoff.py` with a real executable fixture bundle and functioning LaunchServices/`/bin/ps`, not the synthetic unusable apps from the report. Preserve PID ownership, candidate cleanup, rollback, and unrelated-process safety. Do not change the production updater's process logic solely because a test sandbox denied `ps`; only make a narrowly evidenced change if the real packaged path reproduces it.
5. **Build and validate the actual changed artifact.** Use the canonical `tools/prepare_easyocr_models.py`, `tools/build_package.py --platform macos`, and smoke commands documented in `packaging/README.md`. Use the intended packaging interpreter/constraints and isolated profile. Build the small dictionary with `tools/build_smoke_krdict.py`; do not depend on an incidental cache or a network release. Test the reconstructed ZIP's application and verify the DMG, not just an old `dist/macos/Hanly.app`. Record source/frozen versions, interpreter versions, commit, hashes, and diagnostics. Keep build outputs ignored.
6. **Run only the missing native confirmations (001–004).** In a visible, unsandboxed macOS session, run source `python -m hanly_app --self-check ui`, the fresh packaged UI/worker smokes, popup, Control Center layout/lifecycle/WebEngine, lookup-process retirement, desktop startup, and Darwin updater handoff. Use the moved paths from Part 2. Bound each child run with the existing timeouts and capture stage/exit evidence. One successful frozen worker does not prove UI health. After UI passes, exercise launch, Control Center open/close/reopen, runtime status, settings, capture start/stop, ROI/target selection, hotkey lookup, popup retention/dismissal, resource update, quit, and relaunch once with a disposable profile.
7. **Close the performance observation (006) without reopening optimization research.** Read `docs/execution/review-handoffs/han-40-packaged-size.md`, `han-41-idle-performance.md`, and `docs/execution/reports/ocr-latency-and-roadmap.md`. Using existing benchmark tooling, record current cold startup, a warm lookup, worker PID reuse across nearby lookups, retirement after the configured idle policy, RSS after close/retirement, and bundle/archive sizes. The historical 5.55s worker startup / 1.9s OCR / 1.3G bundle are stale-artifact observations, not new SLAs. If current behavior matches the approved policy, record the residual cost and a revisit trigger. If it demonstrates an actual lifecycle regression, fix that narrow regression and check it; do not change preload/idle defaults, Torch dispatch, OCR models, or dependency versions speculatively.

### Acceptance and checkpoint

- All six IDs have an explicit evidence-backed outcome in the ledger. Identity enforcement and missing-screen/inspection diagnostics have focused regression checks. Any confirmed popup/update/runtime fix has a check of the behavior it changes.
- Visible UI, non-activation, process retirement, and update handoff need real native evidence. If the session cannot obtain the required display/process capabilities, finish independent code work and record the exact blocked checks; do not repeat the same failing environment or declare the bundle fully validated. No speculative native fix substitutes for that evidence.
- Commit each coherent Super QA patch after its relevant check; suggested titles include **`fix: validate packaged artifact identity`**, **`fix: report unavailable native UI and process capabilities`**, and a precise popup title only if a popup fix is actually needed. Keep the existing QA report unchanged; put new evidence in the session record.

### Bundle convergence and stop

1. Run the mechanical gates once at convergence using `.venv` (or its activated `python`):

   ```bash
   python -m pytest
   python -m ruff check packages packaging tests tools benchmarks
   python -m mypy packages packaging tests tools benchmarks
   ```

   Record passes, failures, skips, and environment blocks separately. Include the explicit native/packaged commands established in Part 2 where the default command cannot exercise them. Reuse focused checks already run; rerun only affected checks after a correction. No broad test-audit loop.
2. Verify HAN-44 failure behavior, HAN-43 coverage ownership, and the fresh artifact/UI findings together. Windows/Linux native/build acceptance needs the corresponding hosts; local parser tests do not establish it. Without push/remote-run authorization, record pending CI confirmation precisely rather than pushing or tagging to manufacture it.
3. Consolidate the ledger with commit references, six finding dispositions, and remaining native/CI limitations. Inspect the final diff and all commit messages for scope and the **no attribution** requirement.
4. Write one handoff at **`docs/execution/review-handoffs/han-43-44-superqa.md`**, using `TEMPLATE.md` through its Review assignment section only. Include implemented behavior, seams/files touched, checks and limitations, and suggested review targets. State **human-selected review; Phase B not started**. Commit this final documentation with `chore:` and the required concise bullets.
5. Move completed, materially accepted implementation members to `In Review`; keep blocked/incomplete work accurately labeled. Do not claim release readiness if required native evidence is missing. Stop at the handoff. No merge, publication, new bundle, or self-authorized deep review.
