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
