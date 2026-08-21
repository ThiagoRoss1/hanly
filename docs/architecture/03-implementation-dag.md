# Hanly Implementation DAG

Textual companion to the approved [Hanly Implementation DAG](visual/Hanly%20Implementation%20DAG.html) diagram.

## Purpose

This is the master implementation plan for Hanly Desktop V1. It defines implementation waves, capabilities, blockers, parallel work, convergence points, critical-path relationships, and milestones. Nodes are capabilities or milestones, not individual files or pre-expanded task lists.

An edge in this DAG represents a real implementation blocker unless documented as a deliberate project gate.

The deliberate gate that validates the engine independently before desktop work must be preserved. A separate concrete-runtime gate then turns the implemented provider capabilities into the official repository-owned PaddleOCR + Kiwi + KRDICT runtime before desktop interaction capabilities consume it. Absence of an edge means work may be parallelized when its stated inputs are available; it does not make the work mandatory to parallelize.

## Wave 0 — Repository Foundation

### Repository Foundation

- **Goal:** Establish the root monorepo with the `hanly` and `hanly-app` packages, Python 3.10+, pyproject configuration, test scaffolding, linting, type checking, and minimal CI.
- **Dependencies:** None; this is the root node.
- **Blocks:** `Core Contracts` and therefore every V1 implementation branch.
- **Parallelism:** None at the DAG root.
- **Convergence:** None.
- **Acceptance criteria:** Both package locations and the baseline test, lint, type-check, and minimal-CI paths exist and preserve `hanly-app → hanly`.

## Early non-blocking risk-reduction work

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.** These spikes discover constraints early but do not block the V1 critical path unless their evidence later leads to a human-approved DAG change.

### Desktop threading/lifecycle spike

- **Goal:** Validate the intended main-thread and UI-loop assumptions for PyQt6, pywebview, tray / lifecycle integration, and worker execution, especially on macOS.
- **Dependencies:** `Repository Foundation`.
- **Blocks:** Nothing by default; this is explicitly non-blocking risk discovery.
- **Parallelism:** May run from Wave 1 onward while engine work proceeds.
- **Convergence:** None. Findings inform later desktop planning without automatically changing its dependencies.
- **Acceptance criteria:** A minimal experiment records the viable UI-main-thread, event-loop, shutdown, tray, and worker interaction constraints on the platforms exercised.

### Packaging feasibility spike

- **Goal:** Prove that a minimal PaddleOCR / PaddlePaddle application can be packaged sufficiently to reveal major Windows, macOS, and Linux constraints early.
- **Dependencies:** `Repository Foundation`.
- **Blocks:** Nothing by default; this is explicitly non-blocking risk discovery and not production packaging.
- **Parallelism:** May run early beside the engine waves and before Wave 10 becomes expensive.
- **Convergence:** None. Findings inform packaging and CI planning without automatically changing the critical path.
- **Acceptance criteria:** A minimal packaging experiment records platform-specific dependency, artifact, startup, and model-loading constraints that could affect later PyInstaller work.

## Wave 1 — Core Foundations

### Core Contracts

- **Goal:** Define `ROIImage` / `PixelFormat`, `Point` / `Quad` / `BoundingBox`, `OCRResult`, `TokenAnalysis`, `DictionaryEntry`, `LookupResult`, `ResourceMetadata`, the `OCRProvider`, `MorphologyProvider`, and `DictionaryProvider` interfaces, plus base errors / status.
- **Dependencies:** `Repository Foundation`.
- **Blocks:** All parallel engine capabilities in Wave 2.
- **Parallelism:** This capability is the shared prerequisite that unlocks Wave 2 parallelism.
- **Convergence:** Its contracts later converge with provider and resolver work in `LookupPipeline`.
- **Acceptance criteria:** Provider and engine work can depend on normalized contracts without importing UI or concrete external-library objects. `LookupResult` can conceptually discriminate successful, normal empty / not-found / unusable, and processing-error outcomes and carry useful partial or diagnostic information without freezing exact Python enum names.

### Korean Test Fixtures

**Approved implementation-support capability.**

- **Goal:** Provide a small, shared set of deterministic Korean inputs used by the standard `tests/` suite for OCR, morphology, dictionary, and `WordResolver` tests.
- **Dependencies:** `Repository Foundation`; contract-shaped fixtures align with `Core Contracts` as those contracts stabilize.
- **Blocks:** Nothing. This is implementation support, not a critical-path subsystem.
- **Parallelism:** May be assembled alongside `Core Contracts` and extended narrowly as Wave 2 tests require.
- **Convergence:** Supports early validation of `PaddleOCR Provider`, `Kiwi Morphology Provider`, the KRDICT processing / provider branch, and `Word Resolver`.
- **Acceptance criteria:** Representative deterministic fixture inputs exist; ordinary automated tests under `tests/` can consume them; they cover the main engine/provider seams sufficiently for early development; and they are not intended to measure production OCR accuracy.

Keep the fixture count intentionally small. This capability adds no dataset-management infrastructure, fixture-generation pipeline, or testing framework. It is not the future HanlyOCR benchmark dataset and does not replace or block that research track.

## Wave 2 — Parallel Engine Capabilities

Wave 2 branches A–E share `Core Contracts` and have no approved dependencies on one another. They may run in parallel.

### A — PaddleOCR Provider

- **Goal:** Implement the primary V1 OCR adapter from `ROIImage` input to normalized `OCRResult[]` in reading order.
- **Dependencies:** `Core Contracts`.
- **Blocks:** `LookupPipeline`.
- **Parallelism:** May run in parallel with B–E.
- **Convergence:** `LookupPipeline`.
- **Acceptance criteria:** OCR results are normalized and no PaddleOCR objects leak through the `OCRProvider` seam.

> **Decision update:** The approved visual diagram predates a later V1 scope decision. EasyOCR is no longer part of V1. `OCRProvider` remains an abstraction, with `PaddleOCRProvider` as the V1 implementation. Provider configurability remains available for possible future implementations.

### B — Kiwi Morphology Provider

- **Goal:** Implement Korean linguistic analysis through kiwipiepy, including tokens, lemma, part of speech, and morphology.
- **Dependencies:** `Core Contracts`.
- **Blocks:** `LookupPipeline`.
- **Parallelism:** May run in parallel with A and C–E.
- **Convergence:** `LookupPipeline`.
- **Acceptance criteria:** `KiwiProvider` returns normalized `TokenAnalysis` data without exposing Kiwi-specific objects.

### C — KRDICT Processing / SQLite Build

- **Goal:** Process the KRDICT dump, generate the SQLite database, and define its schema and indexes.
- **Dependencies:** `Core Contracts`.
- **Blocks:** `KRDICTProvider`, then `LookupPipeline`.
- **Parallelism:** May run in parallel with A, B, D, and E; its runtime adapter follows the built data format.
- **Convergence:** The branch converges at `LookupPipeline` through `KRDICTProvider`.
- **Acceptance criteria:** A processed, indexed SQLite artifact exists in the format the read-only runtime adapter expects.

### KRDICTProvider

- **Goal:** Provide read-only runtime dictionary lookup over the processed KRDICT SQLite data.
- **Dependencies:** `Core Contracts` and `KRDICT Processing / SQLite Build`.
- **Blocks:** `LookupPipeline`.
- **Parallelism:** Belongs to branch C and may proceed once its data contract and schema are available.
- **Convergence:** `LookupPipeline`.
- **Acceptance criteria:** Runtime lookup returns normalized `DictionaryEntry` data and does not leak SQLite details.

### D — Word Resolver

- **Goal:** Resolve the relevant text / segment from `OCRResult`, its `Quad` geometry, and target / cursor context.
- **Dependencies:** `Core Contracts`.
- **Blocks:** `LookupPipeline`.
- **Parallelism:** May run in parallel with A–C and E.
- **Convergence:** `LookupPipeline`.
- **Acceptance criteria:** Resolution uses conceptual engine data only and has no UI, mouse-hook, or concrete OCR dependency.

### E — ResourceManager Core

- **Goal:** Locate, validate, and report on mandatory local V1 resources as `valid`, `missing`, `outdated`, or `incompatible`.
- **Dependencies:** `Core Contracts`.
- **Blocks:** `Concrete Hanly V1 Engine Integration`, `Basic Control Center`, `UpdateService / ResourceFetcher`, and `Resource / Update UI Integration`.
- **Parallelism:** May run in parallel with A–D. It continues on a side track and is not a `LookupPipeline` dependency in the approved DAG.
- **Convergence:** With `Desktop Foundation` and the implemented provider stack at `Concrete Hanly V1 Engine Integration`; with that concrete runtime at `Basic Control Center`; with `Desktop Foundation` at `UpdateService / ResourceFetcher`; and with both update service and Control Center at `Resource / Update UI Integration`.
- **Acceptance criteria:** Local resource availability, version, model / dictionary status, and compatibility can be reported without remote download or update UX. Application/composition wiring can obtain validated paths and configuration and supply them explicitly to concrete providers; providers do not need a direct `ResourceManager` dependency.

## Wave 3 — Engine Integration

### LookupPipeline

- **Goal:** Orchestrate `OCRProvider → WordResolver → MorphologyProvider → DictionaryProvider → LookupResult`.
- **Dependencies:** `Core Contracts`, `PaddleOCR Provider`, `Kiwi Morphology Provider`, the completed KRDICT provider branch, and `Word Resolver`.
- **Blocks:** `Engine E2E Validation` and the desktop lookup vertical slices.
- **Parallelism:** This is the engine convergence point; its inputs may be built in parallel, but the integrated pipeline waits for them.
- **Convergence:** A + B + C + D + contracts.
- **Acceptance criteria:** The pipeline produces a UI-independent `LookupResult` and depends on abstractions rather than PaddleOCR, Kiwi, SQLite, or `ResourceManager`.

### Engine E2E Validation

- **Goal:** Validate the reusable engine path `image → Hanly Engine → LookupResult` without desktop UI before application composition begins.
- **Dependencies:** `LookupPipeline`.
- **Blocks:** `Desktop Foundation` as a deliberate project gate.
- **Parallelism:** Runs after engine convergence; `ResourceManager Core` remains on its independent side track.
- **Convergence:** Validates the engine contracts and pipeline path independently of the desktop client.
- **Acceptance criteria:** The `hanly` engine functions independently of `hanly-app`. The harness may supply explicit test resource paths / configuration directly and may use deterministic seams; it is not the official repository-owned real-provider runtime composition, which is established after Desktop Foundation.

## Wave 4 — Desktop Foundation

### Desktop Foundation

- **Goal:** Establish the first `hanly-app` infrastructure: `DesktopController`, `ConfigManager`, `LookupController`, `JobExecutor` / worker, basic lifecycle, and the worker-owned composition seam.
- **Dependencies:** `Engine E2E Validation`.
- **Blocks:** `Concrete Hanly V1 Engine Integration`, Wave 5 desktop capabilities, `UpdateService / ResourceFetcher`, and later desktop integration.
- **Parallelism:** This shared foundation unlocks the concrete-runtime gate and the later desktop branches according to their explicit dependencies.
- **Convergence:** Establishes bounded worker execution and the application composition boundary; it does not yet supply the official real PaddleOCR + Kiwi + KRDICT runtime.
- **Acceptance criteria:** Basic app lifecycle works, `hanly-app` depends on `hanly` only in the allowed direction, and heavy processing does not run on the UI thread. `LookupController` and `JobExecutor` enforce a bounded / latest-wins policy so stale hover jobs cannot accumulate without bound; superseded work is cancelled or suppressed where reasonably possible, while final request-currency validation remains mandatory.

## Wave 5 — Concrete Runtime + Desktop Capabilities

`Concrete Hanly V1 Engine Integration` is the deliberate gate at the start of this wave. Capture, popup, hotkey, and Control Center work may proceed only after that concrete runtime exists. Once the gate is satisfied, the four desktop branches may run in parallel according to their own dependencies; Basic Control Center additionally requires `ResourceManager Core`.

### A — Concrete Hanly V1 Engine Integration

- **Goal:** Turn the already-implemented provider and engine capabilities into the first official, repository-owned concrete Hanly V1 runtime.
- **Dependencies:** `Desktop Foundation`, `ResourceManager Core`, `LookupPipeline`, and the completed PaddleOCR, Kiwi, and KRDICT provider branches.
- **Blocks:** `Capture Service`, `Basic Popup`, `Hotkey Service`, `Basic Control Center`, and `Manual Hotkey Lookup`.
- **Parallelism:** This is a convergence gate, not a parallel desktop branch.
- **Convergence:** `PaddleOCRProvider` + `KiwiProvider` + `KRDICTProvider` + `ResourceManager` + the worker-owned hanly-app composition layer.
- **Acceptance criteria:** A repository-owned composition root constructs the real providers from ResourceManager-validated current local paths/configuration; supported development dependencies are wired; an official minimal entrypoint/harness runs a real Korean `image/ROI → PaddleOCR → Kiwi → KRDICT → LookupResult` path without disposable review scripts or test-only manual provider construction.

This capability integrates only behavior already implemented by the current provider APIs. A small local/development resource path is sufficient. It does not own capture, popup, hotkeys, hover, target-point-to-token correction, production resource acquisition/update/distribution, packaging, or future provider capabilities.

### B — Capture Service

- **Goal:** Provide screen capture, monitor selection, cursor coordinates, ROI capture, and basic region support.
- **Dependencies:** `Concrete Hanly V1 Engine Integration` and `Desktop Foundation`.
- **Blocks:** `Manual Hotkey Lookup`.
- **Parallelism:** May run in parallel with C–E after the concrete-runtime gate.
- **Convergence:** `Manual Hotkey Lookup`.
- **Acceptance criteria:** The desktop client can capture a cursor-centered ROI and support the approved basic monitor / region choices.

### C — Basic Popup

- **Goal:** Provide `PopupController` and a borderless PyQt6 popup that positions and renders `LookupResult` with a reasonable V1 visual baseline.
- **Dependencies:** `Concrete Hanly V1 Engine Integration` and `Desktop Foundation`.
- **Blocks:** `Manual Hotkey Lookup`.
- **Parallelism:** May run in parallel with B, D, and E after the concrete-runtime gate.
- **Convergence:** `Manual Hotkey Lookup`.
- **Acceptance criteria:** The popup renders processed successful and normal non-success `LookupResult` states, does not depend on concrete engine providers, and resolves the UI-thread shutdown/dispatcher issue recorded by the Desktop Foundation review.

### D — Hotkey Service

- **Goal:** Register and unregister global hotkeys for lookup and capture-mode actions.
- **Dependencies:** `Concrete Hanly V1 Engine Integration` and `Desktop Foundation`.
- **Blocks:** `Manual Hotkey Lookup`.
- **Parallelism:** May run in parallel with B, C, and E after the concrete-runtime gate.
- **Convergence:** `Manual Hotkey Lookup`.
- **Acceptance criteria:** A global lookup trigger and capture-mode actions can reach desktop application orchestration.

### E — Basic Control Center

- **Goal:** Establish the pywebview HTML/CSS/JavaScript interface for capture start / stop, target / region selection, basic settings and app state, local resource status, current OCR provider, update controls, hover delay, and hotkeys.
- **Dependencies:** `Concrete Hanly V1 Engine Integration`, `Desktop Foundation`, and `ResourceManager Core`.
- **Blocks:** Final `Hover Lookup Integration` and `Resource / Update UI Integration`.
- **Parallelism:** May run beside B–D once all of its dependencies are satisfied. It is the inserted planning capability after Hotkey Service, tracked operationally as HAN-34.
- **Convergence:** With the hover runtime before final hover integration; with `UpdateService / ResourceFetcher` and `ResourceManager Core` at `Resource / Update UI Integration`.
- **Acceptance criteria:** The Control Center shows real resource availability, model / dictionary version and compatibility state; it contains no linguistic logic.

## Wave 6 — Manual Hotkey Lookup

### Manual Hotkey Lookup

- **Goal:** Deliver the first full desktop vertical slice and retain it as a V1 feature.
- **Dependencies:** `Concrete Hanly V1 Engine Integration`, `Capture Service`, `Basic Popup`, `Hotkey Service`, `LookupPipeline`, and the desktop foundation that hosts them.
- **Blocks:** Automatic hover integration; it deliberately validates the complete desktop stack first.
- **Parallelism:** This is a convergence point, not an independent parallel branch.
- **Convergence:** Already-wired concrete engine + capture + popup + hotkey.
- **Acceptance criteria:** `cursor over word → hotkey → capture ROI → JobExecutor → the established concrete LookupPipeline → LookupResult → popup` works end to end with heavy work off the UI thread. The target-point-to-token correctness issue is resolved and verified with real providers before this capability is accepted; HAN-19 does not reconstruct provider/resource composition.

### Operational Linear mapping for Wave 5–6

- HAN-15 — Concrete Hanly V1 Engine Integration.
- HAN-16 — Capture Service.
- HAN-17 — Basic Popup.
- HAN-18 — Hotkey Service.
- HAN-34 — Basic Control Center, inserted after HAN-18 and intentionally not a Manual Hotkey Lookup blocker.
- HAN-19 — Manual Hotkey Lookup.

## Wave 7 — Automatic Hover Runtime

Wave 7 may proceed in parallel with Wave 8 once each branch's inputs exist.

### Mouse Observer

- **Goal:** Monitor the global cursor and publish position / movement events.
- **Dependencies:** `Desktop Foundation`.
- **Blocks:** `Hover Controller` and `Hover Lookup Integration`.
- **Parallelism:** May be developed alongside other ready work, including the Wave 8 update branch.
- **Convergence:** `Hover Lookup Integration`.
- **Acceptance criteria:** Cursor monitoring is separate from OCR and hover decisions.

### Hover Controller

- **Goal:** Own debounce, configurable hover delay, cursor stability, lookup triggering, request identifiers, and stale-request handling.
- **Dependencies:** `Desktop Foundation` and cursor events from `Mouse Observer`.
- **Blocks:** `Hover Lookup Integration`.
- **Parallelism:** May overlap with other ready Wave 7 and Wave 8 work where dependencies allow.
- **Convergence:** `Hover Lookup Integration`.
- **Acceptance criteria:** It can cancel unstable attempts, identify superseded requests, avoid accumulating stale requests through the bounded / latest-wins desktop execution policy, and trigger lookup without performing OCR.

The hover delay is configurable and must be tuned empirically. Initial experimentation is expected around roughly `80–250 ms`; this is an experimental range, not a fixed performance SLA.

### Hover Lookup Integration

- **Goal:** Reuse the manual path for automatic hover: `hover trigger → capture ROI → worker → LookupPipeline → LookupResult → stale validation → popup`.
- **Dependencies:** `Manual Hotkey Lookup`, `Mouse Observer`, `Hover Controller`, and `Basic Control Center` as the approved pre-integration gate.
- **Blocks:** `Hover Lookup E2E`.
- **Parallelism:** It waits for its convergence inputs; it does not create a second lookup implementation.
- **Convergence:** Manual lookup path + automatic trigger/state + Control Center readiness.
- **Acceptance criteria:** Hover uses ROI capture, runs heavy work off the UI thread under a bounded / latest-wins policy, cancels or suppresses superseded work where reasonably possible, and presents only a `LookupResult` that passes final request-currency validation through the same desktop lookup path as manual lookup.

### Hover Lookup E2E

- **Goal:** Validate automatic desktop lookup end to end.
- **Dependencies:** `Hover Lookup Integration`.
- **Blocks:** `Desktop V1 Integration`.
- **Parallelism:** May complete independently of the Wave 8 update branch until Wave 9 convergence.
- **Convergence:** The complete automatic-hover runtime.
- **Acceptance criteria:** Automatic hover lookup is functional end to end without continuous full-screen OCR or a duplicate lookup pipeline.

## Wave 8 — Update / Resource Delivery

This wave may run in parallel with Wave 7 once its own inputs exist.

### UpdateService / ResourceFetcher

- **Goal:** Query remote metadata, check for updates, download model / dictionary resources, report progress, and hand resources to `ResourceManager`.
- **Dependencies:** `ResourceManager Core` and `Desktop Foundation`. It has no UI dependency.
- **Blocks:** `Resource / Update UI Integration`.
- **Parallelism:** May run beside Wave 7 and does not wait for the Control Center.
- **Convergence:** With `Basic Control Center` and `ResourceManager Core` at `Resource / Update UI Integration`.
- **Acceptance criteria:** The non-UI module can use GitHub Releases or another configured source, report progress, and hand downloaded resources over for validation. It is not coupled to GitHub Actions or the Control Center.

### Resource / Update UI Integration

- **Goal:** Expose resource and update state and actions through the desktop interface.
- **Dependencies:** `Basic Control Center`, `UpdateService / ResourceFetcher`, and `ResourceManager Core`.
- **Blocks:** `Desktop V1 Integration`.
- **Parallelism:** This is the Wave 8 convergence point.
- **Convergence:** UI + remote resource delivery + local resource understanding.
- **Acceptance criteria:** The UI consumes the update service and validated resource state; the service remains usable without the UI.

## Wave 9 — Integration & Polish

### Desktop V1 Integration

- **Goal:** Integrate the V1 desktop lifecycle and minimum consistent experience, including tray behavior, completed `ConfigManager`, start / pause / resume capture, graceful shutdown, resource status, popup behavior, Control Center integration, error states, and basic diagnostics.
- **Dependencies:** `Hover Lookup E2E` and `Resource / Update UI Integration`.
- **Blocks:** Packaging, CI release artifacts, and final V1 validation.
- **Parallelism:** This is the convergence of the hover and update branches.
- **Convergence:** Hover E2E + resource/update UI integration.
- **Acceptance criteria:** The approved V1 lifecycle and integrations work together. This is polish of the minimum experience, not a full UI redesign.

## Wave 10 — Packaging / CI / Releases

### Packaging

- **Goal:** Package the desktop application with PyInstaller for Windows, macOS, and Linux.
- **Dependencies:** `Desktop V1 Integration`.
- **Blocks:** `V1 Validation` and release-candidate creation.
- **Parallelism:** May proceed alongside build-matrix and release-infrastructure work where their inputs allow.
- **Convergence:** V1 release artifacts.
- **Acceptance criteria:** Testable application packages can be produced for all three target operating systems.

### GitHub Actions Build Matrix

- **Goal:** Build Windows, macOS, and Linux artifacts in CI.
- **Dependencies:** `Desktop V1 Integration`. The packaging definition and shared artifact conventions are alignment inputs, not a requirement for the Packaging capability to be complete.
- **Blocks:** Cross-platform artifact validation and the release candidate.
- **Parallelism:** May proceed alongside Packaging and Release Infrastructure as shared artifact conventions become available.
- **Convergence:** V1 release artifacts.
- **Acceptance criteria:** The matrix produces testable artifacts for Windows, macOS, and Linux.

### Release Infrastructure

- **Goal:** Support GitHub Releases, application artifacts, resource artifacts, and update metadata.
- **Dependencies:** `Desktop V1 Integration`; consumes shared packaging / artifact conventions where required without waiting for Packaging to complete.
- **Blocks:** End-to-end update/release validation and the release candidate.
- **Parallelism:** May proceed alongside build-matrix work when shared artifact conventions are available.
- **Convergence:** V1 release artifacts and update delivery.
- **Acceptance criteria:** The release channel can carry app artifacts, resource artifacts, and metadata consumed by the approved update flow.

## Wave 11 — Validation / Release Candidate / V1

### V1 Validation

- **Goal:** Validate engine correctness, OCR, Korean morphology, KRDICT lookup, `LookupResult` normal non-success states, manual lookup, hover lookup, bounded / latest-wins execution, resource management, updates, popup behavior, Control Center, startup / cold start, lookup latency, stale-request handling, packaging, and Windows/macOS/Linux artifacts.
- **Dependencies:** `Desktop V1 Integration` and the Wave 10 packaging / CI / release capabilities.
- **Blocks:** `V1 Release Candidate`.
- **Parallelism:** Validation areas may run in parallel, but all required evidence converges before the release candidate.
- **Convergence:** Functional, performance, resource, UX, and cross-platform release validation.
- **Acceptance criteria:** Every listed V1 area has been exercised against the produced release artifacts and the approved architecture invariants.

### V1 Release Candidate

- **Goal:** Produce the milestone candidate for human release evaluation.
- **Dependencies:** `V1 Validation`.
- **Blocks:** `Hanly Desktop V1`.
- **Parallelism:** None at the final milestone gate.
- **Convergence:** All critical-path validation.
- **Acceptance criteria:** The candidate has passed the approved V1 validation scope and is ready for the human release gate.

### Hanly Desktop V1

- **Goal:** Mark the terminal node of the V1 critical path.
- **Dependencies:** Approved `V1 Release Candidate`.
- **Blocks:** Nothing in this V1 DAG.
- **Parallelism:** Terminal milestone.
- **Convergence:** The full V1 critical path.
- **Acceptance criteria:** The approved release candidate is accepted as Hanly Desktop V1.

## Resource dependencies

The resource branch preserves these exact relationships:

- `Concrete Hanly V1 Engine Integration` depends on `Desktop Foundation`, `ResourceManager Core`, `LookupPipeline`, and the implemented concrete provider branches.
- `Concrete Hanly V1 Engine Integration` consumes current local/development resources; it does not acquire or update them.
- `Basic Control Center` depends on `Concrete Hanly V1 Engine Integration`, `Desktop Foundation`, and `ResourceManager Core`.
- `UpdateService / ResourceFetcher` depends on `ResourceManager Core` and `Desktop Foundation`.
- `UpdateService / ResourceFetcher` does not depend on the Control Center UI.
- `Resource / Update UI Integration` depends on and converges `Basic Control Center`, `UpdateService / ResourceFetcher`, and `ResourceManager Core`.
- `UpdateService / ResourceFetcher` obtains resources; `ResourceManager` understands and validates them.
- `ResourceManager Core` is mandatory for V1 but is not an approved dependency of `LookupPipeline` in this DAG.
- Application/composition wiring obtains validated paths and configuration from `ResourceManager` and supplies them explicitly to concrete providers. Providers do not require a direct `ResourceManager` dependency.
- Production resource acquisition, update, and distribution remain owned by `UpdateService / ResourceFetcher` and later delivery/release capabilities, not by the concrete-runtime gate.

## HanlyOCR research track

HanlyOCR is a separate, future, non-blocking research track. It runs beside the V1 critical path and never blocks it. Training from scratch is not the goal; fine-tuning or specializing an existing model is valid.

The evidence-driven sequence is:

1. Build a representative Korean OCR benchmark dataset.
2. Measure the PaddleOCR baseline.
3. Study OCR detection and recognition behavior.
4. Experiment with existing models.
5. Fine-tune a candidate model where justified.
6. Benchmark accuracy, latency, and model size.
7. Decide whether the result is sufficiently better to replace PaddleOCR.
   - **No:** continue using PaddleOCR.
   - **Yes:** introduce `HanlyOCRProvider`, optionally as the primary adapter in a future release.

PaddleOCR alone unblocks V1. `HanlyOCRProvider` is not a V1 dependency.

## Linear materialization model

This Implementation DAG is intended to be materialized into Linear before implementation begins.

The Linear project should preserve:

- capability nodes rather than premature file-level microtasks;
- issue dependencies and real blockers;
- deliberate project gates;
- `READY` / `BLOCKED` state;
- implementation waves;
- convergence points;
- parallel-ready work;
- milestones and the V1 critical path;
- the HanlyOCR track as optional and non-blocking.
- the early risk spikes as non-blocking work and the Korean fixtures as supporting test work.

Creating the Linear project and issues is a later bootstrap execution step. No Linear issues are created by this documentation task.

## Task-level planning

Detailed implementation plans are created just in time when a capability becomes `READY`. They should use the architecture and the current repository state to decompose only that ready capability into reviewable tasks. The DAG must not be expanded now into detailed plans for every future task.

## DAG invariants

- **DAG-INV-01 (diagram rule 1):** `hanly` remains independent from `hanly-app`.
- **DAG-INV-02 (diagram rule 2):** Reusable engine functionality is validated independently before desktop composition and interaction.
- **DAG-INV-03 (diagram rule 3):** Core contracts unlock parallel provider, resolver, and resource-manager work.
- **DAG-INV-04 (diagram rule 4):** Manual Hotkey Lookup precedes automatic hover.
- **DAG-INV-05 (diagram rule 5):** Manual Hotkey Lookup remains a V1 feature.
- **DAG-INV-06 (diagram rule 6):** Basic Control Center exists before final hover integration.
- **DAG-INV-07 (diagram rule 7):** `ResourceManager Core` is mandatory and developed early.
- **DAG-INV-08 (diagram rule 8):** `UpdateService / ResourceFetcher` is separate from `ResourceManager` and never depends on UI.
- **DAG-INV-09 (diagram rule 9):** PaddleOCR is sufficient to unblock V1.
- **DAG-INV-10 (diagram rule 10):** HanlyOCR research never blocks the V1 critical path.
- **DAG-INV-11 (diagram rule 11):** Nodes represent capabilities and milestones, not source files or exhaustive task lists.
- **DAG-INV-12 (diagram rule 12):** Nodes without dependency relationships communicate potential parallel execution.

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

- **DAG-INV-13:** `OCRProvider` remains abstract, `PaddleOCRProvider` is the only V1 OCR implementation, and provider configurability remains available for possible future implementations.
- **DAG-INV-14:** Application/composition wiring injects validated resource paths and configuration into concrete providers; neither providers nor `LookupPipeline` depend directly on `ResourceManager`.
- **DAG-INV-15:** Desktop lookup execution is bounded / latest-wins, with final request-currency validation required before presentation.
- **DAG-INV-16:** Korean Test Fixtures are small deterministic inputs for ordinary automated tests, distinct from the non-blocking HanlyOCR benchmark dataset.
- **DAG-INV-17:** The desktop lifecycle and packaging feasibility spikes are non-blocking risk-discovery capabilities unless their evidence leads to a later human-approved DAG change.
- **DAG-INV-18:** The official concrete PaddleOCR + Kiwi + KRDICT runtime is composed through ResourceManager-backed application wiring before capture, popup, hotkey, and manual-lookup capabilities consume it; later update/distribution work remains separate.
