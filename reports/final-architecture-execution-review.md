# Hanly V1 Architecture & Execution Review

Review date: 2026-08-19. Review-only; no reviewed file, Linear issue, or code was modified.

## Overall result

`PASS WITH MINOR NOTES`

Architecture V1 (`01`–`04`), the operational execution plan (`05`), the four HTML companions, and the Linear
project are mutually consistent. The full Linear blocker graph reproduces the authoritative DAG edge for edge,
including every sensitive relationship named in the review scope. All four invariant lists map 1:1 and in order
between Markdown and HTML (`RF-INV-01…12`, `CA-INV-01…15`, `DAG-INV-01…17`, `AEF-INV-01…19`), and all six
`[ACCEPTED]` items from `REVIEW-2026-08-18.md` are reflected on both sides.

The reusable-engine / PyPI clarification added architectural and distribution intent only. It introduced no V1
deliverable, no plugin framework, no HTTP responsibility inside the engine, and no native-architecture commitment.

The notes below are three minor wording/ambiguity items and two informational observations. None of them is a
contradiction between approved decisions, and none blocks the freeze.

## Reviewed sources

Repository guidance:
- `CLAUDE.md`

Architecture (authoritative):
- `docs/architecture/01-runtime-flow.md`
- `docs/architecture/02-component-architecture.md`
- `docs/architecture/03-implementation-dag.md`
- `docs/architecture/04-agent-execution-flow.md`
- `docs/architecture/REVIEW-2026-08-18.md` (consulted for `[ACCEPTED]` items only)

Execution:
- `docs/execution/05-execution-plan.md`
- `docs/execution/reports/01-agent-runtime-smoke-test.md` (consulted as evidence for Finding 2)

Visual companions (unescaped and read as rendered content):
- `docs/architecture/visual/Hanly Runtime Flow.html`
- `docs/architecture/visual/Hanly Component Architecture.html`
- `docs/architecture/visual/Hanly Implementation DAG.html`
- `docs/architecture/visual/Hanly Agent Execution Flow.html`

Linear (project `Hanly Desktop V1`, team `Hanly`):
- 33 issues, `HAN-1`…`HAN-33`, with milestones Wave 0 – Wave 11, `Early Non-blocking Risk Reduction`, and
  `Future / Non-V1 — HanlyOCR`.
- Full blocker graph inspected via issue relations (`blocks` / `blockedBy` / `relatedTo`).
- Workflow states available: `Backlog`, `Todo`, `In Progress`, `In Review`, `Done` (plus `Canceled`, `Duplicate`).
- Current state: `HAN-1 Repository Foundation` is the only `Todo`; all other issues are `Backlog`.

## Findings

### 1. `03` describes the Build Matrix ← Packaging edge as a dependency, while its own diagram and Linear treat it as informational

- **Severity:** minor (ambiguity)
- **Sources:** `docs/architecture/03-implementation-dag.md` (Wave 10, `GitHub Actions Build Matrix`);
  `Hanly Implementation DAG.html`; Linear `HAN-27`, `HAN-28`, `HAN-29`
- **Issue:** The Markdown lists Build Matrix dependencies as "`Desktop V1 Integration` and the packaging
  definition", which reads as two blockers, while the adjacent parallelism and convergence clauses, the HTML
  companion (the Packaging → Build Matrix connector is explicitly labelled "artifact conventions · informational"),
  and Linear (`HAN-28`/`HAN-29` are `blockedBy` `HAN-26` only, with `HAN-27` as `relatedTo`) all treat Wave 10 as
  three parallel branches sharing artifact conventions.
- **Why it matters:** A strict reading of the sentence would serialize Wave 10 behind complete packaging and
  contradict the DAG's own stated parallelism. Linear currently encodes the correct semantics.
- **Change required before freeze:** No. Optional one-clause clarification in `03` if the phrasing is to be frozen
  as-is. Linear needs no change.

### 2. GPT worker policy covers "cannot instantiate Luna xhigh" but not "cannot verify Luna xhigh"

- **Severity:** minor (ambiguity, execution policy)
- **Sources:** `docs/architecture/04-agent-execution-flow.md` (GPT worker model policy);
  `docs/execution/05-execution-plan.md` (Agent execution and review);
  `docs/execution/reports/01-agent-runtime-smoke-test.md`
- **Issue:** Both documents require stopping and reporting when Luna with `xhigh` reasoning *cannot be
  instantiated*, and forbid silent fallback. Neither addresses the case the smoke test actually produced: workers
  were requested as Luna `xhigh`, no fallback was observed, and the runtime model/reasoning metadata was not
  exposed, so the result was recorded as `UNVERIFIED`.
- **Why it matters:** The no-silent-substitution rule is the point of the policy, and the recorded evidence shows
  the environment may not be able to prove compliance. Without a stated rule, an agent must choose between
  proceeding on an unverified assumption and stopping on an unproven limitation.
- **Change required before freeze:** No for Architecture V1. Recommended for Execution Workflow V1: one sentence
  in `04` (with `05` continuing to defer to it) stating whether unverifiable instantiation is treated as a
  reportable limitation, as acceptable when no fallback is detected, or as requiring explicit human authorization.

### 3. `CLAUDE.md` does not route to `05` or to Linear, and still describes the pre-execution repository state

- **Severity:** minor (navigation gap)
- **Sources:** `CLAUDE.md`; `docs/execution/05-execution-plan.md`
- **Issue:** `05` designates `CLAUDE.md` as the first thing read on start and on resume, but `CLAUDE.md` neither
  mentions `docs/execution/` nor names Linear as the live operational state. Its "Project state" section still
  describes the repository as "the approved architecture (`docs/architecture/`) plus three exploratory spike
  scripts".
- **Why it matters:** An agent entering through `CLAUDE.md` alone — the entry point `05` itself prescribes — would
  not discover the operational plan or the Linear project. `05` currently only works when invoked by name.
- **Change required before freeze:** No. Recommended: a short pointer in `CLAUDE.md` to `docs/execution/05-execution-plan.md`
  and to Linear as live operational state. This is a repository-guidance edit, not an architecture change.

### 4. Engine PyPI distribution is stated as intent but never scoped in or out of V1

- **Severity:** informational
- **Sources:** `docs/architecture/02-component-architecture.md` ("Engine reuse and distribution"); `CLAUDE.md`;
  `docs/architecture/03-implementation-dag.md` (Wave 10); Linear (`HAN-27`…`HAN-29`)
- **Issue:** `02` states the engine "is expected to be independently distributable as the Python package `hanly`,
  including through PyPI". `03` Wave 10 and Linear cover only PyInstaller desktop packaging and GitHub Releases;
  no engine-publication capability exists anywhere. No document says explicitly that engine publication is outside
  V1 delivery.
- **Why it matters:** The conservative and, in this reviewer's reading, correct interpretation is already settled
  by ownership: `03` and Linear define V1 scope, and neither contains such a deliverable, so `02` is expressing a
  property the architecture must preserve rather than a release commitment. Flagged only because the clarification
  is new and the boundary is stated implicitly.
- **Change required before freeze:** No.

### 5. `01` places the Control Center in the startup chain; `03` builds it later and gates only final hover integration

- **Severity:** informational
- **Sources:** `docs/architecture/01-runtime-flow.md` (startup step 7); `docs/architecture/03-implementation-dag.md`
  (`DAG-INV-06`, Wave 5 D, Wave 6, Wave 7)
- **Issue:** `01` lists "Prepare or open the Control Center" between desktop services and `READY`. `03` places
  `Basic Control Center` outside the Manual Hotkey Lookup convergence and makes it the gate only before final
  `Hover Lookup Integration`.
- **Why it matters:** No contradiction — `01` describes the completed V1 runtime and `03` describes incremental
  build order, and `DAG-INV-06`, `HAN-18`, and `HAN-19` all state the narrower gate explicitly. Noted only because
  a reader could otherwise infer the Control Center is a runtime prerequisite for any lookup.
- **Change required before freeze:** No.

## Cross-document consistency

**01 ↔ 02.** Coherent. The runtime sequence in `01` crosses exactly the seams `02` owns: providers behind
`OCRProvider` / `MorphologyProvider` / `DictionaryProvider`, `WordResolver` on conceptual engine data,
`LookupPipeline` producing a UI-independent `LookupResult`, `LookupController` / `JobExecutor` owning request
currency and off-UI-thread execution, and `PopupController` consuming a finished result. Bounded/latest-wins
execution with a mandatory final currency check appears identically in `RF-INV-11` and `CA-INV-14`; the
three-outcome `LookupResult` in `RF-INV-12` and `CA-INV-15`; the composition boundary in `RF-INV-05` /
`CA-INV-13`. `01` startup initializes `ResourceManager` before providers, which is the composition wiring
`CA-INV-13` prescribes, not a provider → `ResourceManager` dependency. Desktop-only V1 assumptions hold in both;
neither introduces browser, mobile, or transport concerns.

**02 ↔ 03.** Coherent. Every `02` component maps to a `03` capability with matching ownership. `ResourceManager`
is mandatory but deliberately off the `LookupPipeline` dependency path in both, and `03`'s Engine E2E harness
supplying explicit test paths is precisely the `02` composition rule applied without a desktop client.
`UpdateService` obtains, `ResourceManager` understands, and neither depends on the Control Center. The engine
reuse clarification in `02` adds no node, branch, or wave to `03`.

**03 ↔ Linear.** The Linear blocker graph reproduces the DAG exactly. Verified edges:
`HAN-1` → `HAN-2`, `HAN-3`, `HAN-4`, `HAN-5`; `HAN-4` → `HAN-6`…`HAN-12`; `HAN-8` → `HAN-9`;
`HAN-12` blocked by `HAN-4`, `HAN-6`, `HAN-7`, `HAN-9`, `HAN-10` and **not** by `HAN-11`;
`HAN-12` → `HAN-13` → `HAN-14`; `HAN-14` → `HAN-15`…`HAN-18`, `HAN-19`, `HAN-20`, `HAN-21`, `HAN-24`;
`HAN-11` → `HAN-18`, `HAN-24`, `HAN-25`; `HAN-19` blocked by `HAN-12`, `HAN-14`, `HAN-15`, `HAN-16`, `HAN-17`
and **not** by `HAN-18`; `HAN-22` blocked by `HAN-18`, `HAN-19`, `HAN-20`, `HAN-21`; `HAN-22` → `HAN-23`;
`HAN-25` blocked by `HAN-11`, `HAN-18`, `HAN-24`; `HAN-26` blocked by `HAN-23`, `HAN-25`;
`HAN-26` → `HAN-27`, `HAN-28`, `HAN-29`, `HAN-30`; `HAN-30` blocked by `HAN-26`…`HAN-29`;
`HAN-30` → `HAN-31` → `HAN-32`. `HAN-33` (HanlyOCR) has no relations in either direction.
Milestones and priorities are used for grouping and tie-breaking only; no blocker is implied by wave or priority.
The single representational difference is Finding 1 (Packaging ↔ Build Matrix / Release Infrastructure recorded as
`relatedTo`), which matches the DAG's HTML companion and its parallelism clauses.

**04 ↔ 05.** Clean, non-overlapping. `04` owns semantic topology, review authority, architecture-change authority,
and the GPT worker model policy; `05` states outright that `04` is the authority and adds no topology. `05` owns
only operational procedure: READY selection, the `Todo` → `In Progress` → `In Review` → `Done` lifecycle, one-issue
scope, JIT planning bounds, checkpoints, reports, and resume-from-durable-state. Both keep human approval and
commit/push/merge as separate authorizations, and both state that issue approval does not confer Git authority.
The only shared gap is Finding 2, which sits in `04` with `05` correctly deferring.

**Markdown ↔ HTML.** All four companions are synchronized on substance.
`01`: `RF-INV-01…12` identical in order and meaning; startup, hover, decision points, ROI-not-full-screen, worker
boundary, and the pre-presentation currency check all present; EasyOCR is gone from the visual, with
`PaddleOCRProvider` shown as the sole V1 adapter behind an open abstraction. The absence of a manual-lookup
sequence in the HTML matches what `01` says about the diagram, and the open clarification is preserved rather than
invented around.
`02`: `CA-INV-01…15` identical in order; layers, adapters, external-dependency ownership, the `ResourceManager` →
composition → provider note, and the bounded/latest-wins worker note all present. The engine reuse / PyPI
paragraph has no visual counterpart, which is not drift — it adds no invariant, and the diagram's
"reusable for browser / CLI / service clients" banner carries the same non-committal sense as `CA-INV-10`.
`03`: `DAG-INV-01…17` identical in order; waves, gates, both non-blocking spikes, Korean Test Fixtures as
non-blocking support, the ResourceManager side track, the pre-hover Control Center gate, and the HanlyOCR decision
branch as future/non-blocking all present. Cosmetic only: the HTML labels the spike "UI Threading / Lifecycle
Spike" where `03` and `HAN-2` say "Desktop Threading / Lifecycle Spike", and Waves 10–11 carry shortened headings.
`04` (recently synchronized): `AEF-INV-01…19` identical in order. The GPT worker model policy appears as its own
block (Luna workers, `xhigh` required, no silent Sol/Terra/other fallback, unavailable → stop and report, different
configuration requires explicit human authorization for that run). Opus 5 direct execution is shown as a valid
default with optional Sonnet subagents; the "NOT PART OF THIS FLOW" block negates a meta-orchestrator, cross-provider
dispatch, mandatory cross-provider review, automatic Git operations, and fixed agent counts. The human gate,
the separate acceptance-vs-Git block, and the architecture-change human gate are all present and correctly
distinguished. Only harmless compression noted: the context panel lists "repository instructions" without
restating "the repository and tests as the executable state".

## Reusable engine / distribution review

- **Engine remains client-independent:** Yes. `hanly-app → hanly` with no reverse dependency
  (`CA-INV-01`/`CA-INV-02`, `DAG-INV-01`, enforced in `HAN-1`, `HAN-13`, `HAN-14` acceptance criteria).
  `LookupPipeline` stays UI-independent and unaware of `ResourceManager` and concrete libraries.
- **PyPI intent is clear:** Yes. `02` names the concrete initial model — the `hanly` package, installable from
  PyPI — while stating the public API is not designed there. `CLAUDE.md` carries the same wording. See Finding 4
  for the one implicit boundary.
- **Python is not made a permanent architectural identity:** Yes. `02` states explicitly that Python is the
  initial implementation and distribution environment, not a permanent constraint, and permits later native
  internals behind public contracts without selecting a language or seam now.
- **Future HTTP/API/CLI/browser use remains external/optional:** Yes. These are listed as possible consumers, not
  promised integrations, and routes, transport, authentication, server lifecycle, OpenAPI, and web frameworks are
  named as outside the engine core. No engine module, DAG node, or Linear issue exists for any of them.
- **V1 scope remains unchanged:** Yes. No HTTP API, CLI, browser client, plugin SDK, native rewrite, additional OCR
  provider, or package ecosystem appears in `03` or in the 33 Linear issues. `02` explicitly disclaims a plugin
  framework and abstractions for hypothetical universality; `HAN-1` explicitly forbids speculative plugin,
  registry, event-bus, DI-container, browser, or multilingual architecture. `PaddleOCRProvider` remains the sole
  V1 OCR implementation and HanlyOCR remains an unconnected future track.

## Freeze readiness

- **Is Architecture V1 ready to freeze?** Yes. `01`–`04` and their companions are internally coherent, mutually
  consistent, and complete against the approved decisions. No contradiction was found.
- **Is Execution Workflow V1 ready to freeze?** Yes, with the recommendation in Finding 2. `05` is a thin
  orchestration layer that defers correctly to `03` and `04`, and its lifecycle matches the states that actually
  exist in Linear. The unverifiable-worker case is an ambiguity in `04`'s policy, not a defect in `05`.
- **Is Linear sufficiently aligned to begin HAN-1?** Yes. The blocker graph matches the DAG, `HAN-1` has no
  blockers and is the only `Todo`, and its scope and acceptance criteria match the Wave 0 capability.
- **Are any changes required before execution starts?** No. All findings are minor or informational and none
  blocks starting `HAN-1`.

## Final recommendation

Freeze Architecture V1 and Execution Workflow V1, and begin execution at `HAN-1`.

Smallest optional follow-ups, in priority order, all human-approved edits and none blocking:

1. Add one sentence to `04`'s GPT worker model policy covering *unverifiable* Luna `xhigh` instantiation
   (Finding 2), and leave `05` deferring to it.
2. Add a pointer in `CLAUDE.md` to `docs/execution/05-execution-plan.md` and to Linear as live operational state
   (Finding 3).
3. If `03` is to be frozen verbatim, soften the `GitHub Actions Build Matrix` dependency line so the packaging
   definition reads as a shared convention rather than a blocker (Finding 1). No Linear change is needed.

No Linear change and no architecture change is required.
