# Windows lab, updater and text-acquisition stress Review Handoff

## Bundle

- Member work: Windows continuation of the app-health lab (Phase 1: lab, app,
  `WIN-UPD-01`/`WIN-UPD-02`, frozen build) and a Windows text-acquisition stress
  campaign with corrections (Phase 2).
- Implementation ecosystem: Claude Code (Opus 5.5), Windows 10 Enterprise 19045,
  `.venv` CPython 3.13.11, EasyOCR 1.7.2.
- Date: 2026-10-02. Branch `lab/app-health`, `65e4968..` HEAD. Local commits only.
- Evidence: [`../reports/lab-windows-validation-and-stress.md`](../reports/lab-windows-validation-and-stress.md);
  resume state: [`../checkpoints/app-health-lab-2026-10-01.md`](../checkpoints/app-health-lab-2026-10-01.md).

## Implemented

Phase 1 (shipped code):
- `e8f51e0` Windows staging admits `.hanly-manifest.json`, the control file every
  Windows tree publishes (WIN-UPD-01); an abandoned install removes its empty working
  area (WIN-UPD-02); settling removes a transaction's challenge and answer.
- `7b61f19` A failed application install says why under the offer it returns to.

Phase 1 (lab and tests):
- `06b3792` Windows lab quit through the shell's handler; sampler attribution.
- `f89f3c2`, `7028aac`, `536c94d`, `d26831a` typing, ignore rule, test TEMP leaks.
- `05faed3` Windows frozen launch identity check (`BUNDLE-LAUNCH-IDENTITY-WIN`).
- `83d040b` `python -m lab check windows-update --mode install|cancel|rollback`.
- `9fe7c41` tour starts on the capture session the app began; pointer intervention;
  metadata start time.

Phase 2 (lab only):
- `f3e8329` `python -m lab stress` (1,158 seeded hovers, rule `stress-v1`, campaign
  report, InPrivate-Edge UIA segment, covering window, re-capture for replay).
- `b40e11d` hover/driver race; `python -m lab stress-replay`.
- `0f599dc`, `ab7110c` UIA window sizing; stale-popup rule.

## Main expected behavior

- A Windows differential update stages, the helper applies it, the new build
  acknowledges, the update is not offered again, and settling leaves no working area
  or challenge files. A failed install shows its reason.
- Every lab command works on Windows; tours and the stress campaign score real
  EasyOCR hovers; foreign windows and a moved pointer are handled.

## Architecture / seams touched

- `updates/manifest.py` (new `require_installable_path`), `updates/journal.py`,
  `updates/installer.py`, `updates/runner.py`; Control Center update panel JS/CSS.
- No change to provider seams, transport, entry point, currency check or OCR
  backends. All Phase 2 code is under `lab/`.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/updates/{manifest,journal,installer,runner}.py`,
  `assets/control_center/control_center.{js,css}`.
- `lab/session/{driver,page,runner,stress,stress_page,stress_driver,stress_scoring,stress_replay,browser_text,cover}.py`,
  `lab/report/campaign.py`, `lab/checks/{windows_update,catalog,runner,ui_probe}.py`,
  `lab/devtools.py`, `lab/cli.py`.
- `tests/test_app_update_hup.py`, `tests/packaged/windows/test_frozen_identity.py`,
  `tests/native/shared/test_update_stage_animation.py`, `lab/tests/test_{stress,lab_session}.py`.

## Implementation-side validation already run

- Portable 2,398 passed / 105 skipped; native 121 / 33; ruff clean; mypy clean for
  linux and darwin (on `ab7110c`, clean tree).
- Fresh Windows build of clean `9fe7c41` (build `9dc5e5af`): packaged 5/5 on the tree
  and on the reconstructed ZIP (6,834 manifest entries match), SHA required, skips
  forbidden; bundle checks 4/4. No shipped code changed after it.
- Real isolated update 0.9.0 → 1.0.0: install, cancel, rollback all pass.
- Standard tour 408/453, rerun 409/453 (all matched); stress campaign final 997/1,123
  with 0/210 false positives and 0 late/stale popups; 124/124 misreads reproduce in
  offline replay.

## Known limitations / intentionally unvalidated areas

- The fixed updater ran in a lab-hosted coordinator against real releases, not inside
  a released frozen build clicking Install update; installed 0.9.0/1.0.0 cannot
  receive the fix by any update (0.5.3 is affected too; release decision needed).
- One machine, two displays at 100 %; mixed DPI and scaling untested.
- OCR misreads (124) are characterized, not fixed. UIA direct-text timeouts were
  attributed to the lab sampler in Phase B (`24ac332`).
- The 22 win32-only mypy errors were fixed in Phase B (`938fa6c`).
- Friend's screenshot images were not available; only a language-stage diagnosis was run.

## Suggested review targets

- `require_installable_path`: that admitting the one control file cannot let a
  release write into `.hanly-update` or anywhere else unexpected.
- `runner.abandon` removing an empty working area and `_remove_challenge`'s
  name-shape guard.
- `stress_scoring` verdicts for negatives and the `stale_popup` definition.
- `browser_text`: the InPrivate window, the content-window guard, and process cleanup.

## Review assignment

Human-selected after implementation: Phase B by Claude Code (Opus 5.5), authorized
2026-10-02, paused once and resumed 2026-10-03. Outcome below.

## Phase B outcome

**Verdict: accepted as review-ready, not shipping- or migration-ready.** The Windows
implementation, updater corrections and stress evidence hold up after independent
checking and ten fixes. Acceptance does not resolve the release blockers: stranded
0.5.3/0.9.0/1.0.0 Windows clients (needs your decision) and the Mac checks that
need a Mac.

### Verified claims

- WIN-UPD-01 reproduces on pre-fix code and the fix admits only the exact control
  file; traversal, absolute/UNC, drive/stream, reserved device and working-area
  paths stay refused (now in any letter case on Windows and macOS).
- Manifest, hash and acknowledgement trust are unchanged; cleanup is ownership-based
  (challenge files only in this installation's own receipt directory); abandon,
  cancel and rollback leave no working area.
- Relaunch reaches the intended build and the update is not re-offered (isolated
  install); rollback restores the base build and re-offers (twice).
- Stress counts recomputed from `events.jsonl`: 1,158 planned = executed, no
  duplicate IDs; verdict totals as reported; the 35 unscored and the 124 OCR
  misreads explained at the OCR stage.
- Lab code is not in the bundle; the branch diff carries no images, artifacts or
  credentials.

### Defects found and fixed

`deb72a6` challenge cleanup ownership · `938fa6c` win32 typing · `7704dc8` (lab)
direct-text refusal completion · `8594257` (lab) Hangul in the bounded-output test
· `24ac332` (lab) sampler starved the shell → UIA deadline misses · `12b052c`
reserved names in any case · `0046cbc` Windows helper claim and startup waits ·
`38d9203` (lab) failure reasons and replay provenance · `16dde15` release outage
misreported as "install by hand" · `762c1c4` (lab) Edge hovered before it drew. Details and before/after evidence: the report's
Phase B section.

### Dismissed concerns

- "PowerShell freezes": measured as slow cold start under load (3–25 s), with the
  helper unchanged since 0.9.0; not a hang, Defender, profile or branch regression.
  The run seen as "over an hour" was still preparing (no transaction existed) and
  was interrupted; rollback runs took ~25 min because of the 600 s startup wait,
  now fixed.
- Replacing the PowerShell helper with a native one: not justified by the evidence
  (see report); revisit if a helper start exceeds 120 s or PowerShell is blocked by
  policy.
- UIA deadline as a product issue: a lab artifact; `DEFAULT_TIMEOUT_MS` unchanged.
- Omitting `.hanly-manifest.json` from releases: does not help legacy clients and
  would break integrity; not done.

### Deferrals (with revisit triggers)

Update failure text quoting local paths (error-presentation work) · real-release
proof of the fixed cleanup/helper waits (first release from this branch) · fail-fast
for a crashing build in the POSIX helper (next Mac helper change) · OCR misreads
(OCR-tuning bundle) · mixed DPI/scaling (other hardware) · Windows single instance
(product decision) · 누군가 missing from KRDICT · screenshot cases (original images).

### Exact outcomes

- Portable 2,415 passed / 105 skipped; native 123 / 33; ruff clean; mypy clean for
  win32, linux, darwin (at `16dde15`).
- Build `0b5c0920` from `16dde15`: packaged 5/5 on build and reconstructed ZIP
  (6,834 entries match); bundle checks 4/4.
- `windows-update` at `16dde15`: install, cancel, rollback ×2 all passed unmodified.
- Campaign `20261003-202512-stress` at `762c1c4`: 998/1,123 (88.9 %), 0/210 false
  positives, 125/913 missing or wrong, 0 stale/late; UIA Korean 39/40; replay
  123/123 (122/123 identical lines). Lab-hosted latency p50 135 ms (was 254 ms with
  the in-shell sampler).

### Legacy migration — human decision needed

Installed Windows 0.5.3/0.9.0/1.0.0 cannot update in place by any release-side
change that keeps integrity. Recommended: announce a one-time manual replacement
with the next release. Nothing about releases, tags or endpoints was changed.

### Mac checks still required

`UPDATE-APPLY-POSIX`, `tests/native/shared/test_update_posix_native.py`,
`MAC-IDENTITY`, packaged Mac `test_frozen_identity`, the stage-animation probe, and
one real Mac update exercising `deb72a6` and `12b052c`.

## Mac verification outcome (2026-10-05)

Claude Code (Opus 5.5) on macOS 26 arm64, `.venv` CPython 3.13.11, starting
from the recorded head `352e4ee` (verified live, clean). Evidence:
[`../reports/lab-mac-final-verification.md`](../reports/lab-mac-final-verification.md).

**Final verdict: accepted with deferred findings.** The first pass lost its
desktop session to idle sleep and the lock screen; the GUI checks it could not
run were completed later the same day on an unlocked session (see "GUI acceptance
completed" below), and all passed. Acceptance covers the scope listed here; it is
not a claim that the Mac app is free of defects.

### Accepted scope

- The shared Windows/Phase B changes cause no Mac regression. `deb72a6` is
  unreachable from a Mac transaction. `12b052c` only refuses more, and real Mac
  manifests still stage. `16dde15`'s confirmation path works against the real
  public release. The other changes are win32 branches.
- Gates: portable 2,519 passed / 2 skipped; native 125 passed / 0 skipped
  (Mac Control Center identity, both stage-animation probes, lifecycle, startup,
  25 POSIX helper cases); lab tests 345; ruff and mypy clean on 340 files.
  `lab check` UPDATE-APPLY-POSIX, UPDATE-COORDINATOR and RESOURCE-DELIVERY pass.
- Fresh build `f0c50a0b` from `352e4eef06cedc6c7b19a879527b7f7cff5e5b11` (shipped
  paths identical to `16dde15`). The build, its ZIP reconstruction and its DMG
  copy each match all 7,342 manifest entries and pass strict `codesign`. The DMG
  opens onto exactly `Hanly.app`. The packaged suite, with the SHA required, gives
  4 passed on each; `lab check` BUNDLE-IDENTITY/-WINDOW/-WORKER gives 3/3 on each
  reconstruction.
- Real isolated update. This checkout's updater upgraded an isolated published
  **0.9.0** Mac app to the **fresh HEAD build**, served with a real delta from a
  local release directory; identity was confirmed against the real public v0.9.0.
  The real C helper committed, the HEAD build acknowledged, the next launch settled,
  the tree matched 7,342 entries, and the update was not re-offered. Cancel left
  nothing. Rollback restored 0.9.0 exactly and re-offered it. The everyday
  profile and `/Applications/Hanly.app` were untouched. This proves the
  branch's updater and the HEAD build's acknowledgement, **not** the updater
  embedded in released 0.9.0/1.0.0.

### Confirmed findings and fixes

- `1fcd2c3` (lab): a terminal Ctrl+C killed the out-of-process sampler, leaving
  `process_samples: 0` beside a full `processes.jsonl` and a traceback. Fixed and
  regression-tested; the real group interrupt was rerun (89 = 89).
- No shipped-code defect found; no shipped code changed in this pass.

### Could not confirm (and where checked)

- Frozen launch identity and the tours were first blocked by the lock screen;
  both were completed later (below). Pre-`24ac332` tours such as
  `20261001-210808-tour` remain unusable as timing baselines.
- The updater embedded in a released app performing a Mac update: not attempted.

### Deferrals (revisit triggers)

- Mac update leaves `challenge-<id>.json` (+ `.ack`, or a pending receipt after
  rollback) in the per-user store. Pre-existing, about 0.5 KB per update. Revisit
  with the next POSIX helper or settling change, using `deb72a6`'s ownership guard.
- Crashing new build waits the full 600 s on Mac. Real-release confirmation:
  602.9 s. Revisit with the next Mac helper change (already deferred in Phase B).
- Helper counts a zombie parent as alive. Seen only through a harness pipe.
  Revisit if a supported launcher keeps Hanly's output pipe open.

### Human decision recorded

The human approved a **one-time manual replacement** for affected installed
Windows clients (0.5.3, 0.9.0, 1.0.0) to reach the corrected release. Manifests
and release tooling stay unchanged. Release announcements and publishing remain
human actions.

### GUI acceptance completed (2026-10-05, unlocked session)

On clean `6c3cf75` (shipped code still that of build `f0c50a0b`), Mac kept
awake with a temporary `caffeinate` only:

- `tests/packaged/macos/test_frozen_identity.py`, with `HANLY_REQUIRE_PACKAGED=1`,
  `HANLY_REQUIRE_NATIVE=1` and SHA `352e4eef06cedc6c7b19a879527b7f7cff5e5b11`:
  1 passed on the ZIP reconstruction, 1 passed on the DMG copy. The earlier
  skips are superseded.
- `lab check run --scenario BUNDLE-LAUNCH-IDENTITY` with that SHA: passed on
  both (`4e17104d`, `9d470ed5`).
- Standard Vision tour (seed 7, story 22 px, 300 words at 16/22/30/40 px,
  default dwell, built-in Retina 2408×1506, one display). No Mac standard tour
  existed after `24ac332`, so `20261005-053512-tour` was run as the comparable
  out-of-process-sampler baseline: 446/453 (98.5 %), 0 not scored.
  `20261005-053840-tour --baseline` it: 446/453, 453 matched, **0 changed
  verdicts**, popup median 142.8 → 141.3 ms.
- Quick tour `20261005-054216-tour`: 23/24, finished.
- Interrupted quick tour `20261005-054246-tour`: real Quartz pointer moves at
  15 s; `stopped_by_user after 20 of 24 planned`, exit 0, partial report with the
  not-comparable warning, no owned process left.
- `report --list`, rebuild by name, newest discovery, and rebuild with
  `--baseline`: all exit 0; the baseline's `summary.md`/`report.json` hashes were
  unchanged.
- Privacy: the four new recordings hold 950 tour results and 0 read-text keys;
  `fixture_text_retained` is false.
- No regression found; no code changed.

### Remaining before shipping

1. Push, CI (portable matrix, native jobs, build), the human's final Windows
   code review, then the release with the announced one-time Windows manual
   replacement. No push, merge, tag or release was done here.
2. Deferrals above stay open with their triggers.
