# Hanly V1 Freeze Readiness Review

Review date: 2026-08-20. Review-only; no reviewed source, no Linear issue, and no code was modified.

## Overall result

`PASS WITH NON-BLOCKING NOTES`

All three minor findings from `final-architecture-execution-review.md` are resolved. `01`–`04`, their four HTML
companions, `05`, `CLAUDE.md`, and the 33-issue Linear project remain mutually consistent, and no contradiction,
stale source-of-truth relationship, Markdown ↔ HTML semantic drift, or Linear ↔ DAG mismatch was found. Two
informational notes remain; neither affects execution safety and neither blocks the freeze.

## Previous findings status

### 1. Wave 10 — Build Matrix vs Packaging — **RESOLVED**

`03` now reads: Build Matrix depends on `Desktop V1 Integration` alone, with the packaging definition and shared
artifact conventions as *alignment inputs*; parallelism reads "may proceed alongside Packaging and Release
Infrastructure"; Release Infrastructure explicitly consumes conventions "without waiting for Packaging to
complete". This matches the HTML companion (the Packaging → Build Matrix connector is labelled
"artifact conventions · informational", Release Infrastructure marked "PARALLEL FROM DESKTOP V1") and Linear
(`HAN-28` `blockedBy` `HAN-26` only; `HAN-27` and `HAN-29` are `relatedTo`). Full Packaging completion no longer
reads as a blocker. See Note 1 for a wording-only observation.

### 2. GPT worker `UNVERIFIED` runtime case — **RESOLVED**

`04` GPT worker model policy now states the case directly: when Luna `xhigh` is requested, no fallback is detected,
and runtime metadata cannot independently verify model or reasoning, the result is reported as `UNVERIFIED` —
"neither verified success nor evidence of fallback", never silently converted to `PASS`; execution proceeds only
where the current human-approved policy permits, and stops for human authorization when verified model identity is
required. The HTML companion carries the same block (`metadata unavailable → UNVERIFIED`, `UNVERIFIED ≠ PASS or
detected fallback`, plus the human-authorization clause). `05` continues to defer to `04` and adds no competing
rule. This matches the evidence in `01-agent-runtime-smoke-test.md`, whose recorded outcome was exactly this case.

### 3. `CLAUDE.md` routing to `05` and Linear — **RESOLVED**

`CLAUDE.md` "Project state" now names `docs/execution/05-execution-plan.md` as the operational execution manual,
requires reading it together with `docs/architecture/` before executing V1 work, and designates Linear as the live
operational source for status, blockers, priorities, milestones/waves, and `READY` work — while keeping the
repository and tests as implemented and verifiable state. The `05` → `CLAUDE.md` → `05` entry loop now closes.

## Final consistency check

**Architecture 01–04.** Consistent. Runtime ordering in `01` crosses exactly the seams `02` owns; bounded /
latest-wins execution with a mandatory final request-currency check appears identically as `RF-INV-11`, `CA-INV-14`,
`DAG-INV-15`; three-outcome `LookupResult` as `RF-INV-12`, `CA-INV-15`; composition-wiring boundary as `CA-INV-13`,
`DAG-INV-14`. `MouseObserver` observes / `HoverController` decides / neither performs OCR holds in `01`, `02`
(`CA-INV-11`) and Wave 7. `ResourceManager` remains mandatory but off the `LookupPipeline` dependency path in both
`02` and `03`. `04` consumes DAG/Linear state and does not redefine blockers.

**04 ↔ 05.** `05` remains a thin operational layer: it states outright that `04` is the authority and "adds no
topology", and owns only READY selection, the `Todo → In Progress → In Review → Done` lifecycle, one-issue scope,
JIT-planning bounds, checkpoints, reports, pause/resume, and stop conditions. The worker-policy paragraph in `05`
restates the no-silent-substitution rule and defers the rest to `04`, including the newly added `UNVERIFIED` case.

**CLAUDE.md ↔ execution workflow.** Correct routing in both directions; no duplicated authority. `CLAUDE.md` still
defers architecture authority to `docs/architecture/*.md` and keeps commit/merge authority human.

**DAG ↔ Linear.** Consistent. 33 issues, `HAN-1`…`HAN-33`, milestones Wave 0 – Wave 11 plus `Early Non-blocking
Risk Reduction` and `Future / Non-V1 — HanlyOCR`. Verified this pass: `HAN-1` blocks `HAN-2`…`HAN-5` and is
`blockedBy` nothing; `HAN-12` `blockedBy` `HAN-4`, `HAN-6`, `HAN-7`, `HAN-9`, `HAN-10` and **not** `HAN-11`;
`HAN-19` `blockedBy` `HAN-12`, `HAN-14`, `HAN-15`, `HAN-16`, `HAN-17` and **not** `HAN-18`; `HAN-22` `blockedBy`
`HAN-18`, `HAN-19`, `HAN-20`, `HAN-21`; `HAN-25` `blockedBy` `HAN-11`, `HAN-18`, `HAN-24`; `HAN-28` `blockedBy`
`HAN-26` only with `HAN-27`/`HAN-29` `relatedTo`; `HAN-30` `blockedBy` `HAN-26`…`HAN-29` and blocking `HAN-31`.
`HAN-1 Repository Foundation` is the only `Todo`; every other issue is `Backlog`; `HAN-33` (HanlyOCR) carries no
relations. Milestones and priorities group and tie-break only.

**Markdown ↔ HTML.** Synchronized. `RF-INV-01…12`, `CA-INV-01…15`, `DAG-INV-01…17`, `AEF-INV-01…19` each appear in
the companion 1:1 and in the same order, with matching meaning. `04`'s companion carries the GPT worker model
policy including the `UNVERIFIED` clauses, the "NOT PART OF THIS FLOW" negations (no meta-orchestrator, no
cross-provider dispatch, no mandatory cross-provider review, no automatic Git operations, no fixed agent counts),
the human review gate, the separate acceptance-vs-Git block, and the architecture-change human gate. `03`'s
companion carries both non-blocking spikes, Korean Test Fixtures as non-blocking support, the ResourceManager side
track, the pre-hover Control Center gate, the informational Wave 10 connector, and HanlyOCR as future/non-blocking.
Only previously noted cosmetic differences persist ("UI Threading / Lifecycle Spike" vs "Desktop Threading /
Lifecycle Spike"; compressed Wave 10–11 headings; compressed `AEF-INV-18` wording). None is semantic drift.

**Reusable engine / distribution intent.** Clear and unchanged in scope. `hanly-app → hanly` with no reverse
dependency (`CA-INV-01`/`CA-INV-02`, `DAG-INV-01`, enforced in `HAN-1`, `HAN-12`, `HAN-14`). `02` names PyPI
(`pip install hanly`) as a concrete initial distribution model while explicitly not designing the public API;
HTTP/API, CLI, browser backends, and service consumers are listed as *possible consumers*, with routes, transport,
authentication, server lifecycle, OpenAPI, and web frameworks named as outside the engine core. Python is stated as
the initial implementation and distribution environment, not a permanent constraint, with native internals
permitted later behind public contracts and no native seam selected now. No plugin framework, registry, event bus,
DI container, additional OCR provider, or engine-publication capability appears in `03` or in the 33 Linear issues;
`HAN-1` explicitly forbids introducing them. V1 scope is unexpanded.

**Human authority / Git authority.** Distinct and consistent across `04`, `05`, and `CLAUDE.md`. Internal review
catches defects and never authorizes `Done`; `Done` requires explicit human approval; acceptance does not authorize
commit, push, or merge; architecture-change approval is a separate gate that likewise confers no Git authority;
automatic commit/push/merge is outside the approved flow. `AEF-INV-15` and the HTML acceptance block agree.

**Execution stop/resume semantics.** `05` bounds execution to the human's authorized issue/wave/checkpoint/milestone
and forbids inferring permission to continue; it stops at every `In Review`, on genuine new blockers, architecture
conflicts, failed validation, unavailable required agent/model configuration, and on unsafe tool/environment
failure. Resume reconstructs from `CLAUDE.md` → Linear → issue → architecture → only relevant durable artifacts,
explicitly "not conversation memory", and forbids inferring `Done`. Reports and checkpoints are described as
supporting evidence that "support but never override" Architecture V1, Linear state, or acceptance criteria.

## Remaining findings

### Note 1 — `03` Wave 10 Build Matrix dependency sentence is awkwardly phrased

- **Severity:** informational
- **Source:** `docs/architecture/03-implementation-dag.md`, Wave 10, `GitHub Actions Build Matrix`
- **Issue:** "The packaging definition and shared artifact conventions are alignment inputs, not a requirement for
  the Packaging capability to be complete." The intended meaning — Build Matrix is not blocked by complete Packaging
  — is unambiguous from the surrounding parallelism clause, the sibling Release Infrastructure sentence, the HTML
  companion, and `HAN-28`. The sentence alone reads slightly inverted.
- **Blocks freeze:** No. The semantics are settled in four independent places.

### Note 2 — `04`'s project-execution-context list does not name `05`

- **Severity:** informational
- **Sources:** `docs/architecture/04-agent-execution-flow.md` ("Inputs and sources of truth");
  `docs/execution/05-execution-plan.md`
- **Issue:** `04` lists product scope, architecture docs, ADRs, repository instructions/skills, repository and
  tests, and Linear — not the operational execution plan. The routing still closes correctly via `CLAUDE.md`, which
  `05` designates as the entry point and which now points to `05`, so no agent path misses it.
- **Blocks freeze:** No. Adding `05` to that list would be a convenience, and `04` deliberately owns semantics
  rather than operational procedure.

## Freeze decision

- **Is Architecture V1 ready to freeze?** Yes. `01`–`04` and their companions are internally coherent, mutually
  consistent, and complete against the approved decisions. No contradiction found.
- **Is Execution Workflow V1 ready to freeze?** Yes. The one previously outstanding recommendation (the
  `UNVERIFIED` worker case) is now stated in `04`, mirrored in its companion, and correctly deferred to by `05`.
- **Is Linear ready to begin HAN-1?** Yes. The blocker graph reproduces the DAG, `HAN-1` has no blockers, is the
  only `Todo`, and its scope, constraints, and acceptance criteria match the Wave 0 capability.
- **Are any changes required before execution starts?** No. Both remaining notes are informational.

## Final recommendation

Freeze Architecture V1 and Execution Workflow V1, and begin execution at `HAN-1`.
