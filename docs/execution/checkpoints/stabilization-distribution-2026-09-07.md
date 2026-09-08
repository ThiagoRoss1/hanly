# Hanly stabilization/distribution — living execution ledger and handoff

## Authority and baseline

- Approved [stable plan](../stabilization-distribution-2026-09-07-plan.md).
- Baseline HEAD: `194a4b2939551986f611607e6b73489d7b50e75b`.
- Pre-existing change: untracked `artifacts/`; preserve, do not claim ownership.
- Plan lives directly in docs/execution alongside the repository's existing plans;
  there was no separate plans directory.
- C0 documentation is created before any implementation code or Luna dispatch.
- Astra orchestrates; A/B are workstreams, fresh bounded Luna xhigh workers allowed.
- Ecosystem change (human, 2026-09-07): implementation moved to Claude. Opus is
  the orchestrator and default executor and may implement cohesive tasks directly;
  Sonnet subagents only for genuinely independent bounded work. "Luna A/B" now
  reads as workstreams A/B. The worker-configuration gate below is historical and
  no longer applies: no model self-identification gate, no added orchestration.
- Human amended the worker gate on resumption: request gpt-5.6-luna/xhigh explicitly;
  stop only for rejection/unavailability or authoritative contradictory metadata.
  Generic worker self-identification is not authoritative; its limitation is
  recorded once below and does not block accepted dispatches.
- Astra alone edits this ledger. No full plan duplication or separate reports.

## Task/checkpoint status

| Task | Owner | Status | Checkpoint | Dependency / next executable step |
|---|---|---|---|---|
| C0 | Astra | COMPLETE | C0 | Both Markdown files verified before dispatch |
| Worker identity gate | Astra | COMPLETE | Before implementation | Human amendment permits accepted explicit configuration; no self-identification gate |
| A1 TLS | Luna A | COMPLETE | C-TLS | Verified-context implementation; 4 focused tests passed |
| A2.1 not-ready | A (Opus) | COMPLETE | C-NOT-READY | Refusal path implemented; 69 focused tests passed |
| A2.2 retry/ownership | A (Opus) | COMPLETE | C-RETRY | Admission, ownership and stale-watcher guards; 51 passed |
| A2.3 timing | A (Opus) | COMPLETE | C-STARTUP | Phase timings on a fake clock; 21 passed |
| A3 frozen models | A (Opus) | COMPLETE | C-MODELS | Packaged weights, downloads off; 29 passed |
| B1 bundle/build inputs | B (Opus) | COMPLETE | C-BUNDLE | App bundle, weight helper, pinned inputs; 30 passed |
| B2 updater | B (Opus) | COMPLETE | C-UPDATER | Bundle-aware install/extraction; 78 passed |
| B3 artifacts/release | B (Opus) | COMPLETE | C-RELEASE | Seven-asset release from native tools; 86 passed |
| B4 smoke adaptation | B (Opus) | COMPLETE | C-VALIDATION | Reconstructed-app smokes; 39 passed |
| Integration/handoff | Opus | COMPLETE | C-HANDOFF | Lightweight review done; handoff written; STOP |

## Meaningful entries

### A1 — verified shared HTTPS context

- Phase/task/owner/status: creation / A1 / implement_a1 (Luna xhigh) / COMPLETE.
- Files: packages/hanly-app/pyproject.toml, app update_service.py,
  tests/test_update_service.py.
- Change/why: certifi direct dependency and explicit verified HTTPSHandler using
  certifi.where(); retain HTTPS-only redirect handler, injected opener and timeout.
- Check: `.venv\Scripts\python.exe -m pytest tests/test_update_service.py -k "https or redirect or default_opener"`.
- Result: 4 passed, 37 deselected; no correction cycle. Real frozen TLS NOT_RUN.
- Discovery: B1 must collect certifi data; no shared networking redesign needed.
- Next: A2.1 not-ready action behavior, separate from retry/ownership/timing.

### B1 - a real macOS application and explicit build inputs

- Phase/task/owner/status: creation / B1 / B (Opus) / COMPLETE.
- Files: packaging/hanly-desktop.spec, packaging/release-constraints.txt (new),
  tools/prepare_easyocr_models.py (new), tools/build_package.py,
  packaging/README.md, .github/workflows/build.yml, tests/test_packaging.py.
- Change/why: macOS wraps the existing COLLECT in BUNDLE("Hanly.app") with
  io.github.thiagoross1.hanly, plist versions read from installed hanly-app
  metadata, and ad-hoc signing; Windows and Linux keep their onedir layout.
  PackageLayout now answers what each platform builds, so callers stop
  rebuilding the convention. The spec collects the two inputs a frozen build
  cannot fetch - the certifi store and both EasyOCR weights - and refuses to
  build without the weights. The fixed helper fetches exactly those two files
  over HTTPS with one bounded request each, verifies EasyOCR's published MD5,
  extracts only the expected member, and reuses a file that already matches.
  Blanket PyQt6 dynamic-library collection and the redundant manual Torch
  collect_all are gone; Kiwi, the explicit imports and the uncertain surfaces
  stay. The three release inputs are pinned in one constraints file the build
  workflow installs with.
- Check: pytest tests/test_packaging.py
- Result: 30 passed. One correction: the existing spec test asserted
  collect_dynamic_libs was present, which the approved cleanup removes; it now
  asserts the opposite alongside the new coverage.
- Discovery: the weights are ~100 MB of build input, so .gitignore now excludes
  the asset directory, and package-data still ships only Control Center assets.
- Next: B2 bundle-aware updater.

### B2 - the macOS update unit is the application bundle

- Phase/task/owner/status: creation / B2 / B (Opus) / COMPLETE.
- Files: app_update.py, paths.py, tests/test_app_update.py,
  tests/test_application.py.
- Change/why: one small internal layout value now carries the asset name,
  archive format, payload root and the program's relative path, so the
  installer reads an installation's shape instead of testing for macOS at each
  step. installation_root resolves the .app, not Contents/MacOS. The macOS
  asset is the ZIP; the DMG is never an update input. The download is proved
  against SHA256SUMS before anything is unpacked, then unpacked with ditto -
  Python's zipfile writes a symlink out as a regular file, which produces a
  bundle that no longer launches - behind a preflight that reads the archive's
  own table of contents: every member inside the expected bundle, no traversal,
  and no link (resolved textually against its own location, parents included)
  pointing out of it, with containment re-checked on what was written. A staged
  bundle must carry Hanly's identity and a structural signature before it is
  moved. Staging, the bounded wait, replacement and rollback are unchanged, and
  the handoff script relaunches the bundle's own program. Configuration beside
  the executable is no longer discovered inside a .app: that is the signed
  bundle an update replaces.
- Check: pytest tests/test_app_update.py tests/test_application.py
- Result: 78 passed, 3 pre-existing platform skips. One correction: a link case
  written as an escape (../../escape from Contents/Resources) actually stays
  inside the bundle; it was replaced with one that really leaves.
- Discovery: 0.1.1 macOS installations cannot self-update to this layout - the
  asset they look for no longer exists, so they report the new version and say
  the installation updates itself outside Hanly. The one-time manual DMG
  migration is documented in packaging/README.md.
- Next: B3 native artifacts and exact release products.

### B3 - native artifacts and the exact seven release assets

- Phase/task/owner/status: creation / B3 / B (Opus) / COMPLETE.
- Files: tools/build_package.py, tools/release_build.py,
  .github/workflows/build.yml, .github/workflows/release.yml,
  packaging/README.md, tests/test_packaging.py, tests/test_release_build.py,
  tests/test_ci_workflows.py.
- Change/why: macOS produces two products from the one built application -
  ditto --keepParent writes the ZIP the updater installs, hdiutil writes the
  DMG a person downloads - and neither modifies the application. A failing
  native tool is reported with what it said rather than ignored. The release
  contract is now four application products plus the KRDICT pair and
  SHA256SUMS: seven assets, six payload digests. Every producer and consumer
  moved together - build verification, artifact identity (now one entry per
  product), upload lists, both stage and finalize allowlists, the sums loop and
  the publication check. Approval, tag/commit resolution, resource
  carry-forward and validate-only behaviour are untouched, and reports are
  still evidence rather than products.
- Check: pytest tests/test_packaging.py tests/test_ci_workflows.py tests/test_release_build.py
- Result: 86 + 31 passed; no correction cycle. Native tools were mocked; no
  archive, image, or release was produced.
- Discovery: a cross-module regression now asserts the builder, the release
  contract and the updater name the same products, and that the disk image is
  never among the updater's inputs.
- Next: B4 packaged smoke adaptation.

### B4 - the smokes check what is actually published

- Phase/task/owner/status: creation / B4 / B (Opus) / COMPLETE.
- Files: tools/smoke_packaged_runtime.py, .github/workflows/build.yml,
  packaging/README.md, tests/test_packaging.py,
  tests/integration/test_packaged_desktop.py.
- Change/why: the inventory reads a bundle's split collection (Frameworks and
  Resources, with or without _internal) as well as a onedir tree, finds the
  program wherever the platform keeps it, and now names the two inputs a frozen
  build cannot fetch. On macOS the build reconstructs the application out of
  the published ZIP with ditto and runs the existing worker and UI smokes
  against that, and mounts the DMG read-only to report what it holds, always
  unmounting. No new self-check mode and no second lifecycle: the isolated
  HOME, configuration, cache and working directory are the existing harness,
  and the worker smoke still runs cold.
- Check: pytest tests/test_packaging.py
- Result: 39 passed. One correction: the shared native-tool double wrote its
  last argument as a file, which is wrong for an extraction whose last argument
  is an existing directory.
- Discovery: the integration gate needed no path of its own once it asks the
  layout and the shared executable lookup.
- Next: lightweight integration review.

### C-HANDOFF - lightweight integration review

- Phase/task/owner/status: integration / review / Opus / COMPLETE.
- Scope: implemented scope only - CA and model paths, readiness and ownership,
  bundle layout/extraction/relaunch, the exact release contract, and obvious
  blockers. Not a deep review; Codex performs that separately.
- Verified by inspection and cheap checks:
  - certifi's collected data lands at certifi/cacert.pem and the weights at
    hanly_app/assets/easyocr_models/*.pth, which is exactly what the frozen
    runtime resolves (__file__-relative, the same directory the Control Center
    assets already load from) and what the inventory now requires.
  - `from PyInstaller.building.osx import BUNDLE` imports cleanly on Windows;
    the macOS-only utilities inside it are guarded by is_darwin.
  - PyInstaller signs the assembled bundle deeply, which is what produces
    Contents/_CodeSignature/CodeResources - the seal the updater requires.
  - Builder, release contract and updater agree on the four products, and the
    ZIP the updater takes unpacks to the payload root ditto --keepParent writes.
- Cheap defensive hardening applied at that boundary: PyInstaller only *warns*
  when it cannot sign a bundle, which would ship an application Hanly's own
  updater refuses; the macOS build now sets
  PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1 and the inventory reports a
  missing bundle signature.
- Checks: ruff over packages/packaging/tools/tests (all passed); mypy over the
  fifteen changed modules (no issues); pytest over the thirteen focused test
  modules for this bundle - 349 passed, 3 pre-existing platform skips.
- Next: human acceptance, then the separate Codex deep review. STOP.

### A2.1 - a not-ready capture action is ordinary news

- Phase/task/owner/status: creation / A2.1 / A (Opus) / COMPLETE.
- Files: control_center.py (RUNTIME_NOT_READY, capture_ready seam),
  application.py (can_start_capture, one Qt-side start/resume recheck, tray
  wiring, refusal handling in request_capture), tray.py (ready_provider gating
  Start/Resume), control_center.js (Start disabled outside READY),
  tests/test_control_center.py, tests/test_application.py.
- Change/why: Start reached _require_controller() inside a dispatched callback,
  so an ordinary "still preparing" became a wrapped lifecycle failure with a
  traceback. The bridge now asks the composition whether a runtime exists before
  touching anything, the Qt-side callback rechecks and reports a refusal rather
  than a fault, and no surface marks capture running for a refused action.
- Check: pytest tests/test_control_center.py tests/test_application.py tests/test_tray.py
- Result: 69 passed, no correction cycle.
- Discovery: DesktopApplication._started made a post-retry Start call resume() on
  a NEW controller, which the controller silently ignores; the session now
  chooses start or resume from the controller's real state.
- Next: A2.2 retry admission and runtime ownership.

### A2.2 - retry admission and runtime ownership

- Phase/task/owner/status: creation / A2.2 / A (Opus) / COMPLETE.
- Files: startup.py, runtime_status.py, application.py, tests/test_startup.py,
  tests/test_runtime_status.py, tests/test_application.py.
- Change/why: retry() now requires a failed status and takes the single
  preparation slot atomically under the existing lock. Thread.is_alive() is false
  until a thread is started, so the old liveness guard left a window in which two
  retries could both be admitted; a reservation closes it. A release whose
  providers do not let go keeps ownership of them, is waited for again on the
  next release, and stops the retry instead of composing a replacement over open
  models and SQLite handles. A readiness watcher belonging to a retired runtime
  is silenced by a generation guard at publication.
- Check: pytest tests/test_runtime_status.py tests/test_application.py tests/test_startup.py
- Result: 51 passed, no correction cycle.
- Discovery: three existing retry tests retried a successful attempt; they now
  report the failure the readiness watcher would publish before retrying.
- Next: A2.3 startup timings.

### A2.3 - lightweight startup timings

- Phase/task/owner/status: creation / A2.3 / A (Opus) / COMPLETE.
- Files: diagnostics.py (StartupTimeline), ocr_preload.py (one pending preload
  measurement), cli.py, application.py, startup.py, runtime.py, composition.py,
  control_center_host.py, tests/test_diagnostics.py, tests/test_app_composition.py.
- Change/why: each named phase is written to the session log with its monotonic
  duration, outcome, and attempt where one applies: OCR preload, Qt bootstrap,
  resources, previous runtime, lookup providers, the three provider constructions
  and their prewarms, plus two elapsed milestones (window visible, runtime ready).
  The packaged runtime hook preloads before the log exists, so that one
  measurement waits in ocr_preload and is claimed exactly once - only the first
  import is measured, so a cached second call cannot re-claim it. No behaviour
  changed and preload still precedes Qt on every OS.
- Check: pytest tests/test_diagnostics.py tests/test_app_composition.py
- Result: 21 passed on a fake clock; no native runtime was initialized.
- Discovery: the prepared runtime already crosses into the worker thread, so it
  carries the timeline (one optional HanlyRuntime field) instead of a new
  parameter on the manual-lookup composition.
- Next: A3 packaged EasyOCR configuration.

### A3 - packaged EasyOCR configuration

- Phase/task/owner/status: creation / A3 / A (Opus) / COMPLETE.
- Files: runtime.py (PACKAGED_MODEL_DIRECTORY, PACKAGED_MODEL_FILES, frozen
  override), first_run.py (comment only), tests/test_runtime.py.
- Change/why: a frozen build resolves hanly_app/assets/easyocr_models/, requires
  both weights, and forces download_enabled false even when an older runtime.json
  stored a user model directory with downloads on. A source checkout is
  untouched, and the EasyOCRConfig seam is unchanged.
- Check: pytest tests/test_runtime.py tests/test_first_run.py tests/test_easyocr_runtime.py
- Result: 29 passed, no correction cycle.
- Evidence for the user_network_directory constraint (inspected
  .venv/Lib/site-packages/easyocr, 1.7.2): Reader.__init__ always does
  Path(self.user_network_directory).mkdir(parents=True, exist_ok=True) and
  appends it to sys.path, but it defaults to MODULE_PATH + "/user_network" where
  MODULE_PATH is ~/.EasyOCR/ unless EASYOCR_MODULE_PATH or MODULE_PATH is set - a
  writable user location, never inside the app bundle. It is read only for a
  custom recog_network, and Hanly uses "standard". EasyOCR 1.7.2 therefore does
  NOT require it with downloads disabled, so it is left alone.
- Evidence for B1 weights (same source, easyocr/config.py): craft_mlt_25k.pth
  md5 2f8227d2def4037cdb3b34389dcf9ec1 from
  releases/download/pre-v1.1.6/craft_mlt_25k.zip; korean_g2.pth md5
  befecf7b1ca2fffb5af814a51443682d from releases/download/v1.3/korean_g2.zip.
  Both are checked against the extracted .pth, and a mismatch with downloads
  disabled raises rather than refetching.
- Next: workstream B, starting at B1.

### C0 - documentation baseline

- Phase/task/owner/status: preparation / C0 / Astra / COMPLETE.
- Files touched: stable plan and this ledger only.
- What/why: materialized the approved revised plan and final adjustments as a
  stable execution reference; created separate living recovery status as requested.
- Focused validation: read baseline with git status/rev-parse; verify documentation
  exists before dispatch. No code tests/builds performed.
- Discovery: existing plans live directly under docs/execution; baseline includes
  untracked artifacts/ and no implementation changes.
- Next executable step: verify the two Markdown files exist; dispatch identity-only
  bounded Luna xhigh workers, ask "Who are you ? Whats your model", await answers.

## Recovery state

- Last checkpoint: C-HANDOFF. Every task in the bundle is COMPLETE and the run
  has stopped, as the plan requires, before commit, review, or release.
- Historical entries below record the superseded worker-identity gate.
- Earlier state: A1 and B1 active on separate owned file sets.
- Historical identity block resolved by explicit human amendment, not by a new
  verified-identity claim. Prior generic answers document the limitation once.
- Next executable step: dispatch A1/B1 explicitly as gpt-5.6-luna with xhigh;
  record focused outcomes before advancing each dependent branch.

### Resumption — human-amended configuration gate

- Phase/task/owner/status: preparation / configuration gate / Astra / COMPLETE.
- Files: existing plan gate paragraph and this ledger; neither document recreated.
- Change/why: human authorized continuing after successful explicit dispatch when
  workers cannot independently confirm exact configuration. Historical replies below
  remain the one record of that limitation; they are not routing evidence.
- Check: baseline status still only pre-existing artifacts/ and the two C0 docs.
- Next: release A1/B1 with explicit Luna/xhigh settings; stop on actual dispatch
  rejection or authoritative conflicting metadata. No fallback substitution.
- Dispatch result: /root/implement_a1 and /root/implement_b1 accepted with
  model=gpt-5.6-luna, reasoning_effort=xhigh, fork_turns=none. No rejection or
  authoritative conflicting configuration returned. Both tasks released.

### Worker identity gate — execution stopped

- Phase/task/owner/status: pre-implementation / identity gate / Astra / BLOCKED.
- Files touched: this ledger only after C0; no implementation files changed.
- Dispatches: /root/luna_a1, /root/luna_b1, /root/luna_identity_retry. Each call
  explicitly set model=gpt-5.6-luna, reasoning_effort=xhigh, fork_turns=none.
  The tool accepted those arguments, but returned no independent actual-model
  metadata. All prompts prohibited tools/file reads/implementation before identity.
- Question: "Who are you ? Whats your model".
- Initial A answer: "My runtime context identifies me as based on GPT-5.
  My reasoning-effort setting is not exposed to me, so I can't verify it."
- Initial B answer: "The available runtime context identifies my model family
  as GPT-5. My exact reasoning-effort setting is not exposed to me, so I can't
  verify it."
- Fresh explicit retry answer: "I'm Codex, an agent based on GPT-5. My runtime
  does not expose an exact model variant or reasoning-effort setting, so I
  can't verify those."
- Result: the required self-identification as Luna xhigh could not be established.
  This is an identity-verification limitation, not proof of a wrong backing model.
  Workers were stopped and no implementation authorization sent to them.
- Focused validation: both requested Markdown artifacts exist (17,461 and 3,101
  bytes at C0 verification); git status then showed only those new docs plus the
  pre-existing artifacts/. No code tests/builds run.
- Why stopped: explicit user instruction requires stopping/reporting when workers
  cannot be correctly identified after redispatch; no fallback model authorized.
- Exact next step: human/runtime resolution of the identity gate, then identity-only
  dispatch and release of A1/B1 if successful. All later tasks remain NOT_STARTED.

## Deferred findings / validation

See stable plan for scope exclusions. Full tests/lint/type checks, native builds,
real TLS/frozen clean-user smokes, app signatures, ZIP/DMG reconstruction, updater
E2E, Gatekeeper/desktop READY and Linux artifact compatibility are NOT_RUN.

## Human Review Handoff

Implementation is complete and the run has stopped. Nothing is committed,
pushed, merged, released, or transitioned in Linear. The deep review is a
separate run by Codex; this section is what it starts from.

### Files and areas changed

Engine package (`packages/hanly`): untouched.

Application (`packages/hanly-app/src/hanly_app/`):

- `update_service.py`, `pyproject.toml` - verified TLS context (A1).
- `control_center.py`, `application.py`, `tray.py`,
  `assets/control_center/control_center.js` - not-ready capture actions (A2.1).
- `startup.py`, `runtime_status.py`, `application.py` - retry admission,
  runtime ownership, stale-watcher guard (A2.2).
- `diagnostics.py`, `ocr_preload.py`, `cli.py`, `application.py`, `startup.py`,
  `runtime.py`, `composition.py`, `control_center_host.py` - startup timings (A2.3).
- `runtime.py`, `first_run.py` - packaged EasyOCR configuration (A3).
- `app_update.py`, `paths.py` - bundle-aware updater and installation root (B2).

Packaging and tooling: `packaging/hanly-desktop.spec`,
`packaging/release-constraints.txt` (new), `packaging/README.md`,
`tools/prepare_easyocr_models.py` (new), `tools/build_package.py`,
`tools/release_build.py`, `tools/smoke_packaged_runtime.py`,
`.github/workflows/build.yml`, `.github/workflows/release.yml`, `.gitignore`.

Tests: `tests/test_update_service.py`, `test_control_center.py`,
`test_application.py`, `test_startup.py`, `test_runtime_status.py`,
`test_diagnostics.py`, `test_app_composition.py`, `test_runtime.py`,
`test_app_update.py`, `test_packaging.py`, `test_release_build.py`,
`test_ci_workflows.py`, `tests/integration/test_packaged_desktop.py`.

### What was implemented, and why

The eight task entries above carry the reasoning per unit. In one line each:
GitHub metadata is read through an explicitly verified certifi context; a
capture action that arrives before a runtime exists is refused as ordinary news
rather than surfacing as a lifecycle traceback; retry answers a failure only,
takes its slot atomically, keeps ownership of resources that did not close, and
cannot be reported on by a retired watcher; each startup phase writes its
duration and outcome to the session log; a frozen build reads bundled weights
and cannot download; macOS builds, publishes, installs and updates a real
`Hanly.app`; the release is the exact seven assets; and the packaged smokes run
against the application reconstructed from what was actually published.

### Focused validation already performed

- Per unit, the cheapest meaningful check named in the plan; every result is in
  the entry above. Three focused checks needed one reasoned correction and one
  rerun (B1, B2, B4) and passed on the rerun, plus two lint fixes. Nothing was
  retried further, and no check was skipped.
- Integration pass: `ruff check packages packaging tools tests benchmarks`
  (clean), `mypy` over the fifteen changed modules (clean), and
  `pytest` over the thirteen focused test modules - 349 passed, 3 skipped
  (pre-existing platform skips in `test_app_update.py`).

### Blocked or deferred

- Nothing is BLOCKED. Everything in the approved scope was implemented.
- Deferred exactly as the plan defines it: Linux extractor changes, a startup
  self-check or lifecycle framework, translocation detection, generic
  archive/resource/cache frameworks, aggressive Torch/Qt exclusion lists,
  EasyOCR/Torchvision pruning, comprehensive dependency locks, third-party
  warning cleanup, broader refactoring, and the 0.9 cleanup. Developer ID and
  notarization remain separately authorized work.
- `user_network_directory` was deliberately not touched; the EasyOCR 1.7.2
  evidence for that decision is recorded in the A3 entry.

### Expensive validation NOT run

Full `pytest`/`ruff`/`mypy` gates as CI runs them; any PyInstaller build; any
ditto, hdiutil, or codesign invocation; the DMG and ZIP reconstruction against
real artifacts; real TLS against GitHub; a clean-user KRDICT provisioning; real
provider construction or OCR; actual desktop READY; updater end-to-end;
a release dry run; and Linux artifact compatibility. Every macOS-native path in
this bundle is implemented against mocked runners and is NOT_RUN on hardware.
On a Mac the later matrix still owes
`codesign --verify --deep --strict --verbose=4 Hanly.app`, a real Safari
download that launches without Terminal or xattr work, and confirmation that a
0.1.1 installation reports the manual migration rather than a broken update.

### Notable risks, and where Codex should look

1. macOS extraction and link safety (`app_update.extract_application_bundle`
   and its preflight): the textual link resolution, the containment re-check,
   and the assumption that ditto is the right and sufficient unpacker.
2. Bundle-relative resolution: `PACKAGED_MODEL_DIRECTORY` is `__file__`-relative
   while the Control Center uses `importlib.resources.files`; both land in the
   same place under PyInstaller, and the inventory now checks both bundle
   layouts, but only a real build proves it.
3. The signature gate: an installed update requires
   `Contents/_CodeSignature/CodeResources`, so a build whose signing silently
   failed would ship an application that can never update itself. The build now
   sets `PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1`; whether that is enough is
   worth a second opinion.
4. Retry admission and ownership (`startup.py`, `_DesktopSession.release`):
   the reservation, the pending-cleanup list that now raises, and the
   generation guard are concurrency changes reasoned about rather than raced.
5. Two readiness gates coexist by design: the page and tray offer Start only in
   READY, while the bridge and session refuse it only when no runtime has been
   composed. The narrow window between them is a supported start.
6. The release lane changed in several files at once; the cross-module
   regression asserts they agree, but the workflows themselves are only
   validated as text.
7. Startup timings cross into worker-thread provider construction through one
   optional `HanlyRuntime` field; the log lines are new output on a hot path
   that is otherwise unchanged.
