# HAN-35 Deferred and Future Inventory

Date: 2026-08-23  
Repository revision: `24ed285bd8cc33390875917d602a3a8526e77128`  
Status: Phase C dispositions final for this technical pass; human/external
triggers remain open where named.

## Disposition vocabulary

Every item uses exactly one HAN-35 class:

1. **resolve now in this pass**
2. **create a dedicated Linear issue**
3. **keep deferred with a concrete trigger**
4. **obsolete / no longer relevant**
5. **already resolved during V1**

`Resolve now` means HAN-35 must collect the named evidence and make the final
decision. It does not pre-authorize a production change. Phase D may implement
only small changes whose evidence and expected benefit are recorded first.

## Source coverage

Every tracked file under `docs/execution/review-handoffs/` and
`docs/execution/reports/` was inspected. Template/process-only files are listed
so a later session can reproduce the coverage audit.

| Source | Relevant inventory contribution |
| --- | --- |
| `review-handoffs/README.md` | process only; no product finding |
| `review-handoffs/TEMPLATE.md` | template only; no product finding |
| `review-handoffs/post-foundation-han-2-5.md` | geometry, image layout, confidence, provider errors, DPI, frozen/runtime constraints |
| `review-handoffs/wave-2-engine-capabilities-han-6-11.md` | SQLite ownership, Paddle defaults, resolver ambiguity, resource APIs, real KRDICT, extras, typing |
| `review-handoffs/engine-convergence-han-12-13.md` | confidence matching, optimized-Python assertion, target-to-token behavior |
| `review-handoffs/desktop-foundation-han-14.md` | callback locking/visibility, aliases, worker typing |
| `review-handoffs/concrete-runtime-han-15.md` | extras, aliases, Paddle option timing, module layout |
| `review-handoffs/desktop-capabilities-han-16-18.md` | monitor enumeration, aggregate monitor fallback, backend direction |
| `review-handoffs/manual-hotkey-lookup-han-19.md` | proportional line mapping and repeated-capture trigger |
| `review-handoffs/automatic-hover-han-20-23-34.md` | native bootstrap, SIGINT, manual UX, hover recovery/performance |
| `review-handoffs/resource-desktop-convergence-han-24-26.md` | validation cost, typing inventory, archive safety, provenance, platform/manual checks |
| `review-handoffs/wave-10-packaging-release-han-27-29.md` | frozen diagnostics, artifact selection, package composition, application metadata |
| `review-handoffs/final-v1-beta-han-30-36-37.md` | bootstrap channel/install location, model layout, final human gate |
| `reports/han-2-desktop-threading-lifecycle-spike.md` | Windows-only lifecycle/DPI/tray and event-loop evidence limits |
| `reports/han-3-packaging-feasibility-spike.md` | Paddle collection/import order and non-Windows evidence limits |
| `reports/han-34-control-center.md` | Control Center bridge/Qt coexistence evidence |
| `reports/bundle-workflow-consistency-review.md` | execution-process findings only; no product finding |
| `reports/bundle-workflow-optimization-review.md` | superseded execution-process findings only |
| `reports/post-foundation-execution-process.md` | execution-process findings only |

## Inventory

| ID | Finding / original trigger | Current evidence | Final disposition |
| --- | --- | --- | --- |
| INV-001 | Quad winding/corner order might affect geometry. Revisit when point-in-quad depends on winding. | `WordResolver` uses winding-independent boundary/ray tests; later review dismissed it. | **already resolved during V1** |
| INV-002 | `ROIImage` assumed tight rows. Revisit when capture supplies padding. | MSS normalization emits exact tightly packed RGB bytes and real capture verified byte counts. | **already resolved during V1** |
| INV-003 | ROI origin/negative desktop coordinates might need to travel in the engine image. | `CaptureResult` owns screen geometry and an ROI-local target; real `-1920` monitor capture was verified. | **already resolved during V1** |
| INV-004 | OCR confidence lacked an application policy. | `LookupPipeline` and runtime config now support a per-region threshold while retaining OCR evidence. | **already resolved during V1** |
| INV-005 | OCR line grouping/metadata may be insufficient. | HAN-19 added proportional target-to-span mapping; the known limitation remains for variable-width/mixed-script text. | **keep deferred with a concrete trigger** — reproduce a materially wrong selection on real variable-width, mixed-script, vertical, or strongly tilted text. |
| INV-006 | Provider exception taxonomy may be too coarse. | Current stages normalize errors and no fallback policy consumes finer categories. | **keep deferred with a concrete trigger** — a recovery/fallback decision must require distinctions the current result/diagnostic cannot express. |
| INV-007 | Windows scaled/mixed-DPI display behavior is untested. | Current Windows monitors are 100%; no suitable environment exists in this run. | **keep deferred with a concrete trigger** — test on an actual 125%/150% or mixed-DPI layout. |
| INV-008 | Frozen PaddleOCR/Qt startup and native DLL ordering. | Local and Actions builds complete; development import ordering works. No current frozen artifact has been launched here. | **keep deferred with a concrete trigger** — launch the current frozen Windows artifact and complete a real OCR lookup. |
| INV-009 | pywebview and Qt event-loop coexistence. | The Windows development alpha and Control Center have shared the Qt/WebEngine path successfully. | **already resolved during V1** for Windows; cross-platform behavior remains under INV-045. |
| INV-010 | SQLite connection threading ownership. | Provider construction and close occur on the worker thread and are covered with real SQLite. | **already resolved during V1** |
| INV-011 | Paddle oneDNN/MKLDNN default fails on the development machine. | `enable_mkldnn=false` is a runtime option and current development config uses it. | **already resolved during V1**; reconsider only if defaults or Paddle behavior change. |
| INV-012 | Shared-edge/abutting OCR quads resolve ambiguously. | No real OCR sample has reproduced it. | **keep deferred with a concrete trigger** — retain a real OCR output with adjacent quads and a target on their shared boundary. |
| INV-013 | Duplicate `ResourceManager` accessors and controller/composition aliases. | Repository consumers use the canonical spellings, but the aliases are exported public compatibility surface at `v0.1.0`; removing them has no measured runtime benefit. | **keep deferred with a concrete trigger** — reconsider at an announced breaking API boundary or when a real consumer/maintenance conflict proves the aliases harmful. |
| INV-014 | Production KRDICT schema/content coverage. | Only the mini database is locally available. | **keep deferred with a concrete trigger** — validate an actual production KRDICT release artifact/schema. |
| INV-015 | Concrete-provider dependency extras/install shape. | Engine/app extras now separate base, runtime, concrete, and dev installs; packaging exists. | **already resolved during V1** |
| INV-016 | Local Windows temporary-directory ACL failure. | Fresh full suite passes without the historical redirect. | **obsolete / no longer relevant** unless it reproduces outside the old environment. |
| INV-017 | PaddleOCR adapter uses `Any` at its dynamic result boundary. | PaddleOCR still lacks useful stubs; normalized Hanly types do not leak Paddle objects. | **keep deferred with a concrete trigger** — PaddleOCR ships usable typing or a narrower local parser can remove `Any` without casts leaking outward. |
| INV-018 | Relative resource paths had unclear process-CWD semantics. | Runtime paths resolve relative to the config file and characterization tests cover decoy CWDs. | **already resolved during V1** |
| INV-019 | Confidence matching by text equality could miss normalized resolver text. | The resolver now returns the selected `OCRResult`; confidence is read directly from it. | **already resolved during V1** |
| INV-020 | `assert threshold is not None` is stripped under optimized Python. | The full pipeline test file passes under `python -O`; the assertion narrows a logically guaranteed value and is not a correctness gate. | **obsolete / no longer relevant** — reopen only if optimized execution produces a concrete behavioral failure. |
| INV-021 | Result callbacks execute while `LookupController` holds its lock. | Real development Qt popup rendering measured 0.14 ms p50 / 0.16 ms p95 in the warm hover campaign; no contention or stale-delivery failure reproduced. | **keep deferred with a concrete trigger** — a callback exceeds the UI frame budget, blocks concurrent submit/invalidate, or deadlocks under a retained reproduction. |
| INV-022 | Callback exceptions are swallowed and invisible. | HAN-35 added structured nullable request/fallback/error diagnostics and JSON/PNG/HTML artifacts without changing worker safety. | **already resolved during V1** for developer diagnosis; add production telemetry only when a support/recovery requirement names its sink and privacy policy. |
| INV-023 | Worker factory lost typing at composition boundary. | Provider-specific factory protocols and typed worker interfaces replaced the broad boundary. | **already resolved during V1** |
| INV-024 | A typoed Paddle option fails only when the worker constructs the provider. | Failure is loud but late; runtime config is not a general end-user editor. | **keep deferred with a concrete trigger** — manifest/provider options become user-authored or support incidents show late failures are harmful. |
| INV-025 | Flat package module layout may eventually become hard to navigate. | Modules are large but boundaries remain explicit; moving them is broad structural work. | **keep deferred with a concrete trigger** — a feature must require repeated cross-module edits or ownership becomes ambiguous enough to impede changes. |
| INV-026 | Capture re-enumerates monitors per lookup. | On the available two-monitor Windows host, 100 calls measured 0.02 ms p50/p95 (2.40 ms max), versus 16.62 ms capture p50. | **keep deferred with a concrete trigger** — a real backend/host shows enumeration p95 above 1 ms or profiling makes it a material share of hover latency. No cache is justified now. |
| INV-027 | MSS may expose the aggregate virtual desktop as a physical monitor on unusual layouts. | Normal dual-monitor layout is correct; no failing environment exists. | **keep deferred with a concrete trigger** — reproduce a phantom monitor on mixed-DPI/unusual layout. |
| INV-028 | Proportional line mapping assumes roughly uniform character advance. | Required Korean fixture works and a fresh real lookup selected `읽습니다.` correctly. | **keep deferred with a concrete trigger** — real incorrect token selection as specified by INV-005. |
| INV-029 | Hotkey/hover configuration previously applied only after restart. | `ManualLookupRuntime.apply_config` now rebinds the hotkey and updates hover delay live. | **already resolved during V1** |
| INV-030 | Fatal hover failure requires process restart. | No recovery-frequency or usability evidence exists. | **keep deferred with a concrete trigger** — a reproducible recoverable failure leaves hover disabled during a real session. |
| INV-031 | Development alpha opens Control Center at startup. | Production application lifecycle owns Control Center/tray; this is intentionally a dev-only affordance. | **obsolete / no longer relevant** as a production concern. |
| INV-032 | `check_for_updates()` performs full SQLite validation on each check. | Available-resource runtime validation measured 31.28 ms in the corrected baseline; the local KRDICT is a mini database, not production size. | **keep deferred with a concrete trigger** — repeat with the production KRDICT/release resources and change policy only if update-check validation becomes user-visible or materially exceeds its background budget. |
| INV-033 | External JSON parsing, JSON snapshot types, broad `object` seams, pywebview `getattr`, and side-effect import style. | Full mypy is clean across 110 source files; HAN-35 added typed benchmark/CLI boundaries and found no small production defect in the inventoried dynamic-library seams. | **already resolved during V1** for the current supported boundaries; reopen at a concrete unsafe cast/parser failure or when upstream stubs permit a narrower seam. |
| INV-034 | Archive extraction has no size or entry-count cap. | Checksums, trusted manifest, safe paths, and staging exist, but resource exhaustion remains possible. | **create a dedicated Linear issue** — security limits need explicit policy and adversarial archive tests beyond a small HAN-35 cleanup. |
| INV-035 | Artifact signing and application/resource provenance are incomplete. | Tags, checksums, HTTPS, and workflow provenance exist; cryptographic publisher authenticity does not. | **create a dedicated Linear issue** — supply-chain design and key ownership are larger than HAN-35. |
| INV-036 | Windowed Windows CLI diagnostics are discarded with `console=False`. | Native startup-error dialog now covers application bootstrap failures; `--help`/argument UX is still not a product CLI. | **keep deferred with a concrete trigger** — Phase C chooses a first-class CLI or a frozen command-line failure lacks an actionable GUI/log path. |
| INV-037 | Release workflow `find_resource` selects the first match. | Exact artifact-count checks cover the current one-asset-per-id contract. | **keep deferred with a concrete trigger** — resource variants or multiple matching assets become supported. |
| INV-038 | Frozen application cannot report its version/About/self-update metadata. | Not required by the current resource-only updater. | **create a dedicated Linear issue** if application self-update/About becomes planned; otherwise retain as post-V1 feature work. |
| INV-039 | Package is large and collection includes Paddle/PaddleX/Qt broadly. | Exact analysis confirms 1,771,099,850 bytes: PyQt6 557.1 MB, Torch family 390.8 MB, Paddle family 385.5 MB, and OpenCV 147.1 MB. The current frozen artifact was not available to prove exclusions safe. | **create a dedicated Linear issue** — draft a frozen package-slimming matrix for Torch/torchvision, broad Qt collection, PaddleX transitive modules, and OpenCV, requiring build/import/startup/real-OCR checks on every platform before exclusion. HAN-35 does not mutate Linear. |
| INV-040 | Bootstrap ignores a user-configured alternate release channel. | One default public channel exists; bootstrap and updater differ only after user customization. | **keep deferred with a concrete trigger** — a non-default channel becomes supported. |
| INV-041 | Bootstrap may persist versions beside a non-writable installed executable. | V1 is an extracted archive, not an installer. | **keep deferred with a concrete trigger** — introduce a per-machine/non-writable installer location. |
| INV-042 | First-run provisioning is synchronous without progress UI. | Real release resources remain unavailable; fake transport cannot establish download duration or frozen responsiveness. | **keep deferred with a concrete trigger** — time clean-profile provisioning with the real release assets; create the progress-UI issue if the frozen app appears hung or exceeds the human-accepted wait. |
| INV-043 | Model archive wrapper directories could pass generic directory validation. | Runtime now requires a file at each model resource root and tests cover empty/wrapped layouts. | **already resolved during V1** |
| INV-044 | Real-terminal SIGINT/Ctrl+C behavior was previously unresolved. | A controlled PTY development launch initialized the real providers and exited 1.17 seconds after Ctrl+C with no traceback; process status was 1, so graceful zero-status semantics remain unproven. | **keep deferred with a concrete trigger** — repeat against the packaged console command and retain expected exit-code/cleanup evidence; treat a hang, traceback, or unreleased resource as a defect. |
| INV-045 | macOS/Linux desktop runtime, Wayland, permissions, tray, capture, hotkeys, and DPI. | All three Actions builds complete, but only Windows development runtime is available. | **keep deferred with a concrete trigger** — run the frozen artifacts on their actual platforms; builds are not runtime evidence. |
| INV-046 | Native MSS/pynput alternatives. | Current MSS capture succeeds; 30 clipped 200x100 requests measured 16.62 ms p50 / 18.53 ms p95. No available Windows blocker justifies migration. | **keep deferred with a concrete trigger** — a supported OS/Wayland permission failure, capture p95 that materially breaks the latency budget, or backend abandonment. Any migration is a dedicated issue. |
| INV-047 | PyQt6 versus PySide6. | PyQt6 builds/tests pass and the real development popup reached visible state; migration offers no measured benefit and would expand packaging/licensing validation. | **already resolved during V1** — retain PyQt6 for V1; reconsider only through an approved binding ADR with concrete benefit. |
| INV-048 | Number and defaults of global hotkeys. | Production `ManualLookupRuntime` registers only the configurable lookup binding; start/pause defaults belong to the generic service seam and tray/Control Center own lifecycle UX. Collision/rebind tests pass. | **already resolved during V1** — one product global hotkey is deliberate; add another only through an explicit UX requirement. |
| INV-049 | Future CLI/terminal UX. | HAN-35 implements the approved `hanly run` session selector, Python console entry point, frozen Windows wrapper, executable dispatch, cancellation, and region/composition tests while preserving normal launch. | **already resolved during V1** for the technical implementation; interactive/frozen selection remains in the human checklist. |
| INV-050 | Broad readability cleanup could become an aesthetic refactor. | Focused review plus Ruff/mypy found no evidence-backed broad production cleanup; benchmark and CLI additions follow the repository rules. | **already resolved during V1** — no aesthetic sweep; future behavioral/structural work needs its own evidence. |
| INV-051 | Manual/frozen tray, Control Center, popup, hover, hotkey, update, first-run and repeat-launch checks. | Automated/development evidence exists; current frozen artifacts have not been exercised here. | **keep deferred with a concrete trigger** — complete the exact human artifact checklist in `baseline.md`. |

## Phase B evidence queues used

- Performance queue: INV-021, INV-026, INV-032, INV-039, INV-042, INV-046.
- Diagnostic/correctness queue: INV-005, INV-012, INV-022, INV-028, INV-030.
- Local lifecycle queue: INV-044 plus repeated start/stop, latest-wins,
  cancellation, shutdown-in-flight, and slow-provider scenarios.
- Static/decision queue: INV-013, INV-020, INV-033, INV-047, INV-048,
  INV-049, INV-050.
- External/manual queue: INV-007, INV-008, INV-014, INV-027, INV-045,
  INV-051.

Phase C completed the final disposition pass. Raw run identifiers and measured
values are linked from `results-and-decisions.md`; items requiring human,
frozen, production-resource, or other-platform evidence remain explicitly open.
