# Hanly stabilization/distribution — approved implementation plan

Status: approved for bounded implementation on 2026-09-07. This materializes the
revised plan and final user adjustments; it does not authorize release or deep review.

## Authority and goal

Fix verified TLS access, preparation/retry behavior, frozen EasyOCR delivery,
startup diagnostics, and macOS distribution/update layout with small changes.

Workflow: PLAN → CREATE → ESSENTIAL CHECK → INTEGRATE → LIGHT IMPLEMENTATION
REVIEW → HANDOFF → STOP.

The user's bundle instructions override conflicting workflow ceremony in
CLAUDE.md, generic skills, and architecture 04. Use
[04-agent-execution-flow.md](../architecture/04-agent-execution-flow.md) for
roles, human authority, shallow Luna delegation, implementation/review separation,
and handoff. Do not use 05-execution-plan.md as operational authority. Preserve
product boundaries in architecture 01–03 and CLAUDE.md: hanly-app → hanly,
provider interfaces, worker-owned providers/SQLite, no heavy UI-thread work,
and one CLI entry point.

## Bounded evidence and decisions

Inspected startup/runtime/status/diagnostics, GitHub fetcher, updater/paths,
EasyOCR configuration, PyInstaller spec/hooks, build/release workflows and
helpers, and existing packaged smokes/tests. No exhaustive graph investigation.

- The real frozen macOS 0.1.1 log confirms GitHub metadata TLS verification
  failure during KRDICT first-run provisioning. Retry repeats that failure.
  It does not contain the separately reported not-ready lifecycle traceback
  and does not prove overlapping attempts or ownership races.
- Both supplied macOS/Windows CI logs show successful frozen worker and UI
  smokes, KRDICT provisioning, and detection/recognition model downloads.
  CI success does not disprove the user's TLS failure.
- Shared _https_opener has no explicit CA context. certifi plus a verified
  HTTPSHandler is the bounded fix; keep HTTPS-only redirects/timeouts.
- Start/resume can require a missing controller; dispatch wraps the expected
  rejection as a lifecycle failure. Retry checks thread liveness, which leaves
  admission/queued-activation gaps. Cleanup currently logs timeout and continues.
- EasyOCR 1.7.2 needs craft_mlt_25k.pth and korean_g2.pth for Hanly's Korean CPU
  configuration. Bundle those directly. Keep a fixed two-model build helper;
  no separate model manifest or runtime resource subsystem.
- Current macOS output is COLLECT/onedir, not BUNDLE. Its updater assumes an
  executable-parent installation root and flat executable layout.
- PyInstaller app links/metadata must survive macOS archive/extraction. Keep
  path/link safety at this security boundary, without a generic archive engine.
- Current release is three app archives/six total assets. New release is four
  app products/seven total assets, using exact allowlists.
- Blanket Qt dynamic-library collection and redundant manual Torch collection
  justify coarse cleanup. Upstream collection remains broad. Successful smokes
  mean optional hidden-import errors are not new standalone blockers.
- CI used EasyOCR 1.7.2, PyInstaller 6.22.2, hooks-contrib 2026.7. Pin these three
  release inputs only; this is not comprehensive dependency reproducibility.
- Mac/Windows archives were approximately 501/574 MB. No immediate size crisis
  was established. SciPy SDK warnings require later signature/load validation.

## Scope

Required: TLS, clean not-ready behavior, bounded retry/resource ownership,
real macOS app, bundle-aware updater, matching release products.

Targeted robustness: bundled OCR weights, simple startup timing, adaptation of
existing isolated worker/UI smokes, manual migration guidance from 0.1.1.

Small packaging changes: explicit CA/model input, redundant Torch and blanket
Qt collection removal, three release-input pins.

Deferred: Linux tar extractor changes (no supplied failing artifact evidence),
new startup self-check/lifecycle framework, automatic translocation detection,
general archive/resource/cache frameworks, aggressive Torch/Qt exclusions,
uncertain EasyOCR/Torchvision pruning, comprehensive dependency locks,
third-party warning/deprecation cleanup, broad application refactoring,
architecture redesign, alternate OCR/HanlyOCR/browser work, installer frameworks,
and 0.9 mega cleanup. Developer ID/notarization is later separately authorized work.

## Contracts

- App name: Hanly.app; display name: Hanly.
- Proposed identifier io.github.thiagoross1.hanly was presented as a decision;
  approval of this revised plan establishes this implementation value.
- macOS executable: Contents/MacOS/hanly-desktop.
- Version fields derive from tag-validated hanly-app metadata; no invented version bump.
- Model location: package-relative hanly_app/assets/easyocr_models/.
- Weights: craft_mlt_25k.pth and korean_g2.pth.
- Frozen model downloads disabled, including old persisted download settings.
- Do not modify/manage user_network_directory unless inspected EasyOCR 1.7.2
  actually requires it with packaged downloads disabled. Record concrete evidence
  before making any such change.
- Mutable config/resources remain outside the signed app; source behavior stays reasonable.
- macOS updater ZIP: hanly-desktop-macos.zip; human download: hanly-desktop-macos.dmg.

## DAG and worker ownership

```text
C0 — approved baseline, docs, ownership/contracts
├─ Workstream A: A1 → A2.1 → A2.2 → A2.3 → A3
└─ Workstream B: B1 → B2 → B3
                 A1–A3 + B1–B3 → B4
                                  → Astra light integration review
                                  → ledger/handoff → STOP
```

Astra orchestrates two useful direct workstreams using gpt-5.6-luna with xhigh.
A/B are ownership streams, not persistent agents; fresh bounded Luna per task
is allowed. No Terra, agent orchestrators, mandatory reviewers, or worker quota.

Worker configuration gate (human amendment on resumption): explicitly request
gpt-5.6-luna with xhigh. Stop if dispatch rejects/unavailability is reported or
authoritative runtime metadata shows another configuration. A worker's generic
natural-language self-identification is not authoritative model metadata: record
its inability to independently verify exact model/effort once in the ledger and
continue after successful dispatch. Never silently substitute another model.

A owns application/runtime/startup/status/diagnostics, runtime hook, app dependency
declaration. B owns spec, paths/updater, build/release tooling/workflows and
test_packaging.py. Shared tests are edited serially. B4 follows all A work.
Astra alone writes the ledger; workers send concise results, not report files.

## Task contracts

For every meaningful unit: create → one cheapest meaningful focused check →
record result → continue. A failed check permits one reasoned local correction
and one rerun of that same check. Continued failure or material expansion is
BLOCKED. Independent work may continue; dependent work waits. Optional cleanup
may be DEFERRED. No retry-until-green or unbounded network retries.

### A1 — Explicit verified TLS

Owner A; prerequisite C0; parallel with B.
Files: app update_service.py, app pyproject.toml, tests/test_update_service.py.
Mini-tasks: declare certifi; create ssl.create_default_context(cafile=certifi.where());
attach HTTPSHandler to current opener; retain HTTPS-only redirects, timeouts,
error translation and injected opener. Coordinate CA data collection with B1.
Check: targeted context/handler regression (roots, verification, redirect policy).
Complete/checkpoint: shared production channel uses verified context and focused
check passes; frozen network validation remains pending. Block if the narrow fix
cannot pass after its one correction; no alternate transport/certificate bypass.

### A2.1 — Normal not-ready actions

Owner A; prerequisite A1 for sequencing, not a new functional dependency;
parallel with B1–B3. Files: application.py, control_center.py, Control Center JS,
tray wiring only as needed, directly related tests.
Mini-tasks: disable Start/Resume outside READY; recheck on Qt-owned execution;
return/display a normal rejection; never mark rejected capture running; retain
settings/diagnostics/quit. Do not suppress unexpected lifecycle errors.
Check: focused deterministic not-ready/accepted-action regression.
Complete/checkpoint: normal preparing action produces no lifecycle traceback and
no false capture state. Block if a broad lifecycle change is required.

### A2.2 — Retry and runtime ownership

Owner A; prerequisite A2.1; parallel with B1–B3.
Files: startup.py, application.py, runtime_status.py and focused tests.
Mini-tasks: require FAILED for retry; atomically reserve PREPARING under existing
lock; preserve liveness guard and existing attempt/shutdown handling. Existing
status spans queued activation/provider load; no new attempt state machine or
completion protocol. Stop replacement on cleanup timeout and retain pending
cleanup ownership. Use a small current-runtime identity/cancellation guard at
publication so a retired watcher cannot overwrite current status.
Check: narrow deterministic admission/cleanup/stale-publication regressions.
Complete/checkpoint: no overlapping retry, no replacement over owned resources,
no stale readiness. Block if this needs wider concurrency architecture.

### A2.3 — Lightweight startup timings

Owner A; prerequisite A2.2; parallel with B1–B3.
Files: diagnostics, bootstrap/CLI/preload/runtime hook, startup/runtime/first_run,
composition/window visibility seams only as needed; focused timing tests.
Mini-tasks: log phase, monotonic duration, outcome and attempt where applicable:
Python bootstrap/preload; Qt/WebEngine; window visible; config/KRDICT preparation;
EasyOCR, Kiwi, KRDICT construction; OCR prewarm; READY. Preserve one small early
preload record until diagnostics opens, without a buffering framework or duplicate
cost claims. Preserve preload ordering on all OSes; Windows protection is required.
Check: fake-clock timing regression, no native initialization.
Complete/checkpoint: named timing seams logged without changing behavior. Block if
timing requires a metrics/tracing subsystem or broad composition rewrite.

### A3 — Packaged EasyOCR configuration

Owner A; prerequisite A2.3 and model-path contract; parallel with B.
Files: runtime.py, relevant first-run handling/comments, runtime tests.
Mini-tasks: resolve package-relative weights; frozen downloads false even for old
settings; require both files; keep source/developer behavior and EasyOCRConfig
seam. Unsupported frozen models fail without downloads. Respect the explicit
user_network_directory constraint above.
Check: fixture frozen/source/missing-model regression, no model construction.
Complete/checkpoint: frozen path uses supplied weights and cannot download.
Block if the reader requires a larger delivery architecture.

### B1 — Real app and explicit build inputs

Owner B; prerequisite C0; integrate A1 dependency before completion; parallel A.
Files: packaging spec, tools/build_package.py, packaging docs/tests. Small additions:
tools/prepare_easyocr_models.py and packaging/release-constraints.txt.
Mini-tasks: BUNDLE(coll) on macOS, retain Windows/Linux layout; normal plist and
derived versions; default ad-hoc signing; explicit certifi/weight data. Fixed helper
has only two URLs/names/checksums, verified HTTPS, bounded requests, checked reuse,
extraction of only the expected files. No reader construction/model downloads
during implementation tests. Upstream MD5 matches expected content, not a claim of
cryptographic authenticity. Pin easyocr==1.7.2, pyinstaller==6.22.2,
pyinstaller-hooks-contrib==2026.7 in release installs; preserve compatibility ranges.
Remove blanket PyQt library and redundant manual Torch collection; keep mandatory
Kiwi, explicit imports and uncertain surfaces. No experimental exclusion lists.
Check: small synthetic model/archive and mocked layout/spec tests per meaningful unit.
Complete/checkpoint: supported app and explicit inputs coded, coarse cleanup/pins
recorded; no native validation claimed. Block model-integrity failures; defer
optional pruning that needs trial builds.

### B2 — Minimal bundle-aware updater

Owner B; prerequisite B1; parallel remaining A.
Files: app_update.py, paths.py, updater/path tests.
Mini-tasks: one small internal layout value for asset/format/payload root/executable
relative path; valid .app installation-root resolution; macOS ZIP selection;
SHA256 before extraction. macOS-only native ZIP helper with member/link preflight,
including link-parent traversal; preserve metadata and verify containment after.
Validate app identity/executable and structural signature before handoff. Reuse
staging, bounded wait, replace and rollback; relaunch macOS app path and preserve
Windows/Linux behavior. Keep mutable configuration outside the bundle.
No Linux extractor change, generic archive engine, translocation detector,
elevation, relocation or startup-health rollback. Unwritable installs fail cleanly.
Document one-time manual DMG migration from old 0.1.1 updater.
Check: synthetic app/ZIP/platform layout regressions with native calls mocked;
retain rollback assertions. Complete/checkpoint: .app is macOS update unit.
Block if secure extraction/replacement exceeds this bounded adaptation.

### B3 — Native artifacts and exact release products

Owner B; prerequisites B1–B2; parallel remaining A.
Files: build_package.py, build.yml/release.yml, release_build.py, tests/operator docs.
Mini-tasks: ditto ZIP and hdiutil DMG from same signed app; preserve metadata/links
and do not alter signed app. Update explicit outputs/uploads/size/identity lists,
stage/final allowlists, classification and sums. Preserve approval, tag/commit
checks, resource carry-forward and validate-only behavior. Reports are not products.
Seven assets: windows ZIP, macos DMG, macos ZIP, linux tar.gz, one
krdict-<version>.sqlite3.zst, hanly-resources.json, SHA256SUMS (six payload digests).
Three platform jobs. DMG is never updater input; no extra legacy Mac product.
Check: exact-product regression and mocked archive commands.
Complete/checkpoint: every producer/consumer agrees. Block native-tool/size problems
for later validation; no iterative pruning.

### B4 — Adapt existing packaged smokes

Owner B; prerequisites A1–A3/B1–B3.
Files: smoke_packaged_runtime.py, build workflow and existing packaging tests.
Mini-tasks: .app executable/data lookup, CA/model inventory; reuse isolated HOME,
config/cache/cwd; worker smoke has no supplied runtime config/KRDICT seed/model cache.
Reconstruct final ZIP and DMG, structurally verify both; existing worker/UI smokes
run against a reconstructed app. No new CLI self-check mode or second lifecycle.
Report worker/provider success accurately; actual desktop READY remains later
human/platform validation. Check: temp-directory/fake-process tests only.
Complete/checkpoint: new final-distribution path expressible in existing harness;
native runs explicitly NOT_RUN. Block/defer extension requiring another framework.

## Checkpoints and recovery

C0 baseline/docs/contracts; C-TLS A1; C-NOT-READY A2.1; C-RETRY A2.2;
C-STARTUP A2.3 (A2 complete); C-MODELS A3; C-BUNDLE B1; C-UPDATER B2;
C-RELEASE B3; C-VALIDATION B4; C-HANDOFF Astra review/handoff.
Independent branches may finish in either order. Update the one ledger after
meaningful units, not trivial edits. Resume from its exact next executable step,
checking recorded files/baseline drift instead of replaying completed validation.

Living recovery/handoff: [ledger](checkpoints/stabilization-distribution-2026-09-07.md).
Entries: phase, task/mini-task ID, owner/status, files, what/why, focused command,
result, relevant discovery, exact next step. Statuses: NOT_STARTED, IN_PROGRESS,
COMPLETE, BLOCKED, FAILED, DEFERRED. COMPLETE means code/focused check, not release
readiness. No duplicated full plan, per-worker reports or patch files.

## Validation and final boundary

Creation: only named essential checks; no full pytest/Ruff/mypy, PyInstaller,
DMG build, model download, expensive smoke or cross-platform experiment.
Astra conducts one lightweight integrated review of implemented scope, CA/model
paths, readiness/ownership, layout/extraction/relaunch, exact release contracts,
and obvious blockers. No deep audit, reviewers, convergence loops or full gates.

Later separately authorized CI/human validation: full suites/lint/types; native
Windows/macOS/Linux builds; final ZIP/DMG reconstruction/signatures; verified TLS
and clean-user KRDICT/provider initialization; actual desktop READY; updater E2E;
release dry-run with exact assets/sums; Linux link/update compatibility. On Mac:
codesign --verify --deep --strict --verbose=4 Hanly.app. Successful spctl is not
required for unnotarized ad-hoc builds. Real Safari download/manual override must
eventually launch without Terminal/xattr/nested approvals; CI does not prove this.

Rollback boundaries: reject bad staged bundle before replacement; preserve current
replacement-failure rollback (not runtime-health rollback); revert optional pruning
independently; cleanup timeout blocks replacement; old 0.1.1 Mac requires manual
migration. Promote SciPy warnings only for concrete signature/runtime failures.

After creation/checks/Astra review, finish the one living handoff and STOP.
No automatic commit, push, merge, release, Linear Done, next bundle, expensive
validation, or post-bundle deep review. Human acceptance remains separate.
