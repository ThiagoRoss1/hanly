# App health lab — Mac Review Handoff

## Bundle

- Scope: whole-app lab foundation; local cases `UI-UPD-03` and `MAC-START-04`.
- Implementation ecosystem: Codex on macOS arm64, Python 3.13.11; 2026-10-01.
- Branch: `lab/app-health`; implementation head `432b466`. Local commits only.
- Resume: [execution prompt](../plans/app-health-lab-2026-10-01.md),
  [checkpoint](../checkpoints/app-health-lab-2026-10-01.md),
  [evidence report](../reports/app-health-lab-2026-10-01.md).

## Implemented

- Sixteen fixed coverage scenarios with isolated profiles/workspaces, bounded
  execution and typed `passed`/`failed`/`unavailable`/`not_run` results.
- Safe JSON/HTML timings, sampled aggregate RSS and owned process timelines;
  no durable raw child output, screen content or arbitrary exception messages.
- Update labels retain their DOM across progress polls and animate only on a
  text change; normal/reduced-motion behavior is measured in real Chromium.
- Mac window host disables Qt's foreground transformation before creating its
  application, retaining the existing Accessory policy afterward.

## Main expected behavior

`python -m benchmarks.dev app-lab list` explains coverage. `app-lab run` executes
selected fixed scenarios and reports under gitignored benchmark runs. Missing
evidence, inspection denial, skipped prerequisites, unfinished output and forced
child cleanup cannot pass. No scenario updates the everyday installation.

## Architecture / seams touched

Developer orchestration stays in `benchmarks/dev/app_lab/`; `psutil` is declared
in dev extras only. Production changes are confined to Control Center busy-view
rendering/CSS and Mac host initialization order. Public engine contracts, desktop
entry point, provider selection, lookup transport and updater apply logic remain
unchanged. No generic plugins, dashboard or new production configuration surface.

## Relevant files / diff areas

- `benchmarks/dev/app_lab/`, `benchmarks/dev/cli.py` and its developer tests.
- `packages/hanly-app/src/hanly_app/control_center/host.py` and
  `packages/hanly-app/src/hanly_app/assets/control_center/control_center.js` /
  `control_center.css`.
- `tests/native/shared/test_update_stage_animation.py`,
  `tests/test_control_center_host.py` and developer dependency declarations.
- Eight implementation commits; the evidence report records the authorized
  message-only hash mapping. No squashing or code change accompanied rewording.

## Implementation-side validation already run

- Portable: 2,391 passed, 2 skipped; native: 125 passed.
- Strengthened real motion-duration cases: 2 passed; lab contracts: 26 passed.
- Ruff and mypy clean (312 files); Python 3.10 syntax parsing passed.
- Source startup/identity/lifecycle, UI/capture/hover/settings, coordinator,
  POSIX helper and resource cases: outcomes and evidence labels in the report.
- Fresh Mac build, original stamp `e15204df2d14aa0ecefc6ec5a7d9a8b93ab69efc`:
  ZIP and DMG each reconstruct to all 7,342 manifest entries, pass signature
  verification and all four packaged checks with that SHA required.
- `e15204d` and message-corrected `20af3eb` have identical trees; neither the
  artifact's stamp nor earlier run metadata was relabeled.

## Known limitations / intentionally unvalidated areas

- Windows install loop and owned empty directory are not diagnosed. POSIX
  apply tests use simulated builds, not a whole real-release update.
- The source child's transient identity was reproduced and causally corrected.
  The standalone frozen UI-check process still samples Foreground → UIElement;
  passing page/bridge checks do not prove normal frozen shell → child identity.
  Observe that actual path before declaring the Mac startup report fully closed.
- Human live hover, mixed-DPI/multiple displays and actual Python 3.10 runtime
  remain unrun. Some coverage uses injected services; labels make that explicit.
- RSS aggregates pytest and descendants; sampling can miss short events and
  inferred roles cannot separate every spawned Python child.
- PyInstaller collected `psutil` transitively; no developer lab modules were
  found in the analysis. Runtime extras unchanged does not mean frozen contents
  unchanged. Dependency pruning requires separate packaging review authority.
- Remote CI is unverified: this branch has not been pushed.

## Suggested review targets

Check PID reuse/cleanup ownership, denied-observation semantics, bounded output
and privacy, refresh-state transitions/cancel controls, host initialization
order, frozen versus source identity, and catalog evidence labels. Review the
changed code without interpreting a passing helper test as update acceptance.

## Review assignment

Human-selected Claude review after implementation continuations. Not started.
This document prepares review; it does not report a Phase B verdict.

## Windows implementation continuation prompt

Resume the approved lab implementation on a real Windows machine. First read
`AGENTS.md`, `CLAUDE.md`, `docs/CODE-MAP.md`, architecture `01`–`04`, execution
`05`, and the linked prompt/checkpoint/report above. Inspect branch, worktree,
recent commits and interpreter. Reuse the fetched `lab/app-health` branch and
preserve changes/history; ask if it is absent. Do not start Phase B review.

1. Prepare the documented developer environment and editable engine/desktop
   packages. Run baseline portable/native/Ruff/mypy gates and attribute failures
   independently; do not dismiss them because an older Windows run failed.
   Start with `python -m benchmarks.dev app-lab list`.
2. Expand `WINDOWS-UPDATE`, currently an explicit unimplemented scenario, with
   actual native/packaged checks. Establish owned isolated old/new installations,
   profiles and controlled update artifacts/origin. Never update the everyday
   installation or mutate public releases/tags. If no safe existing update-source
   seam is available, document it and obtain a narrow human decision before
   adding production configuration.
3. Reproduce `WIN-UPD-01` and `WIN-UPD-02`: record source/target build identities
   and find the first failing transition across plan, download, verification,
   staging, helper, apply, relaunch, acknowledgement and cleanup. Identify the
   empty directory's actual transaction/helper owner; its name is not proof of
   ownership or the root cause. Keep private paths out of normal reports.
4. Change the demonstrated cause and rerun the identical isolated update.
   Require the target build to launch once, acknowledge and stop offering the
   same update. Verify cancellation, failure/rollback and cleanup separately,
   touching only owned paths. Record observed stage outcomes and timing, not
   an invented pass based on mocks.
5. Validate broader Windows startup/quit/reopen, Control Center tabs/actions,
   stage animation/reduced motion, capture, hover, UIA/OCR fallback, popup,
   settings/resources and packaged identity. Use existing tests and narrow
   seams; developer instrumentation remains outside `packages/`.
6. Run proportional focused checks as fixes land, then full Windows gates and
   a fresh Windows build. Require its actual full source SHA in packaged checks:

   ```bash
   python -m pytest --suite portable
   python -m pytest --suite native
   python -m ruff check packages packaging tests tools benchmarks
   python -m mypy packages packaging tests tools benchmarks
   python tools/build_package.py --platform windows
   python -m benchmarks.dev app-lab run --scenario BUNDLE-IDENTITY --scenario BUNDLE-WINDOW --scenario BUNDLE-WORKER --bundle dist/windows/hanly-desktop --expected-commit <full-build-source-sha>
   ```

   Confirm the output layout from `packaging/README.md` and the actual build,
   rather than blindly using a stale path. Skips/unavailable checks are not
   passes. Frozen self-checks alone do not prove a successful real update.
7. Normal tracing persists no recognized text/pixels. Freeze is memory-only;
   private capture persistence requires explicit Export beneath the gitignored
   benchmark root. Keep live EasyOCR evidence distinct from staged replay.
   Preserve update/profile isolation throughout every failure path.
8. Update the existing checkpoint with evidence and exact next actions. Write
   English Windows evidence and a Review Handoff; stop there. Commit tested
   fixes/features or small bundles separately with `feat:`, `fix:`, `chore:` or
   `docs:` and action-bullet bodies, configured human author and no attribution
   trailers. No rewrite, push, merge, tag or release is authorized. If session
   limits approach, checkpoint before stopping; never claim unfinished work done.
