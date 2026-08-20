# Hanly V1 Operational Execution Plan

## Purpose

This is the thin orchestration manual for executing Hanly Desktop V1. It does not redefine architecture, duplicate the implementation DAG, or replace Linear. The normal orchestration unit is an execution bundle when multiple related issues share a useful capability or convergence boundary; a single issue remains the correct unit for isolated, substantial, or high-risk work. Never continue beyond the human-authorized issue or bundle.

V1 is already extensively planned. This plan therefore optimizes for **building V1 efficiently**, not for repeatedly proving tiny changes correct before enough product exists to justify that cost. Deep review is preserved — as a separate, human-triggered phase — rather than executed continuously during implementation.

> **V1 execution scaffolding.** This document, `04-agent-execution-flow.md`, `CONTEXT.md`, `checkpoints/`, `review-handoffs/`, and any temporary execution ledger exist to build V1. They may be archived, consolidated, or removed after V1. Product architecture that still accurately documents the implemented system (`01`, `02`, and `03` where still true) is not scaffolding and is not marked for removal.

## Sources of truth

Read and apply these sources according to their ownership:

- [`CLAUDE.md`](../../CLAUDE.md): current repository state, commands, and base project guidance.
- [`01-runtime-flow.md`](../architecture/01-runtime-flow.md): runtime behavior and concurrency constraints.
- [`02-component-architecture.md`](../architecture/02-component-architecture.md): ownership, package boundaries, dependency direction, and component responsibilities.
- [`03-implementation-dag.md`](../architecture/03-implementation-dag.md): waves, structural order, real blockers, parallelism, convergence, and gates.
- [`04-agent-execution-flow.md`](../architecture/04-agent-execution-flow.md): ecosystem roles, delegation, review phases, human authority, commit/push/merge policy, and GPT worker model policy.
- [`CONTEXT.md`](CONTEXT.md): derived one-page constraint sheet. Ordinary workers read it instead of `01`-`04` in full; it never overrides the architecture documents it indexes.
- Linear: live issues, blocker relationships, milestones, priority, type, and execution status.
- The repository and tests: implemented and verifiable state.

When sources differ in purpose, use the source that owns the decision. Do not turn this document, a checkpoint, a handoff, or a report into a competing source of truth.

## Two execution phases

Hanly execution has exactly two phases, and they are separate runs.

```text
PHASE A — IMPLEMENTATION (this run)
authorized bundle
→ implementation
→ lightweight implementation-side checks
→ bundle mechanical gates
→ implementation-side consolidation
→ Review Handoff
→ STOP

PHASE B — POST-BUNDLE REVIEW (a separate, human-triggered run)
human selects reviewer and ecosystem
→ deep review against repository, handoff, architecture, acceptance criteria
→ prioritized findings
→ human decision and any authorized corrections
```

**An implementation run must never turn itself into a deep review session.** Producing the handoff ends the implementation run. Phase B begins only on explicit human authorization, and the human chooses who performs it.

## Start and execution-unit selection

1. Read `CLAUDE.md`.
2. Inspect the current Hanly project in Linear.
3. Read the candidate issues and the relevant architecture. Consult `03-implementation-dag.md` for readiness, dependencies, waves, convergence, and blocker semantics, and `04-agent-execution-flow.md` for roles, delegation, review phases, and authority.
4. Identify root `READY` issues: their real blockers are satisfied and their Linear state is `Todo`.
5. Select either one issue or derive a candidate bundle from root `READY` work plus related descendants whose only unsatisfied blockers are inside that bundle.
6. Use real dependencies, component relationships, useful parallelism, and a natural capability or convergence boundary. Never group by consecutive issue numbers, cross a major architecture gate merely to enlarge a bundle, or make a bundle too large for meaningful human review.
7. Use priority only to choose between simultaneously eligible roots. Priority never bypasses a blocker.
8. Record the authorized member issues, their execution tier, internal dependency order, implementation-side checks, bundle gates, and stop boundary before implementation begins.
9. Respect the human's explicit issue, bundle, wave, or checkpoint boundary even when other work is eligible.
10. Before dispatching any worker, confirm the authoritative interpreter (`.venv`) and that every tool the bundle needs is installed. An evidence run made with the wrong interpreter or a missing tool is not evidence and has to be repeated in full.

An **Execution Bundle** is a temporary orchestration and handoff grouping. It does not merge issues, change their scope or acceptance criteria, remove blockers, or become a competing architecture plan. The human may authorize an explicitly named bundle or command execution of the next dynamically derived bundle.

## Execution tiers

Ceremony scales to the work; acceptance criteria never do. Every issue keeps its Linear scope, acceptance criteria, and human approval regardless of tier — the tier selects only how much machinery is spent reaching them.

The orchestrator proposes a tier per member in the bundle plan; the human may override it at authorization. When a member turns out to touch a seam, contract, or invariant that other issues depend on, raise its tier immediately and say so.

### Light

Configuration, documentation, test fixtures, risk spikes, and other work with no runtime seam and a small diff.

- One worker executes directly. No decomposition layer, no separate reviewer.
- Context: `CLAUDE.md`, the Linear issue, [`CONTEXT.md`](CONTEXT.md), the touched files.
- Checks: the cheapest useful evidence that the change works.
- Record: one concise Linear comment. No report file.

### Standard

One component, provider, or capability implemented behind an already defined seam.

- One worker executes it and self-checks. A separate reviewer is added only when the orchestrator judges this specific work risky enough to need one.
- Context: Light context plus the architecture section owning the seam it implements.
- Checks: focused happy-path behavior plus the specific invariants the change directly touches.
- Record: Linear comment, and a ledger line when pause/resume needs it. No report file.

### Gate

Convergence points, integration capabilities, shared-contract definitions, and architecture-sensitive work — including `Core Contracts`, `Engine E2E Validation`, `Desktop Foundation`, `Manual Hotkey Lookup`, `Desktop V1 Integration`, and `V1 Validation`.

- More workers where genuinely independent workstreams exist; an optional coordination layer where integration judgment materially helps. Neither is mandatory.
- Context: the full relevant architecture documents.
- Checks: the intended integration path runs, plus the bundle mechanical gates.
- Gate tier raises the care taken with architecture and integration. It does not by itself require a separate reviewer per member, and it does not pull deep review into the implementation run.

## Skills precedence

This execution plan is authoritative for Hanly V1 execution. Generic execution skills — `executing-plans`, `subagent-driven-development`, generic JIT-planning or review chains, generic TDD ceremony — must not override or duplicate it.

Do not invoke a generic skill for Hanly work when it would add another execution plan on top of the bundle plan, another decomposition layer, mandatory per-task reviewers, mandatory re-review loops, duplicate progress reports, duplicate checkpoints, or duplicate validation. Invoke it only when the human explicitly asks for it, or when the specific work genuinely needs what it provides.

Skills may assist execution. They may not redefine its orchestration or review lifecycle.

## Implementation-side validation

**Implementation-side validation exists to enable safe forward progress, not to exhaustively prove correctness.** Its questions are:

- Does it run, import, or load, as applicable?
- Does the intended primary behavior work?
- Does it satisfy its acceptance criteria materially enough to continue?
- Does it respect the architecture, seam, contract, or dependency it directly touches?
- Is there an obvious or blocking defect that makes further implementation unsafe?

Run only the cheapest useful check for the kind of work: configuration parses or its command works; contracts and models construct and behave as intended; a provider satisfies its focused happy path; a fixture can be consumed; a spike answers its stated risk question; an integration runs its intended path.

**Do not spend more implementation-side validation or review effort than is proportional to the behavior and risk introduced.** Implementation-side checking does not exist to hunt hidden bugs exhaustively, inspect every implementation detail, run broad regression analysis after every issue, manufacture synthetic tests for trivial configuration or data changes, re-review tiny diffs, prove standard-library or framework behavior, or run a QA phase inside the implementation run. Those belong to Phase B.

Do not require RED→GREEN TDD for fixtures, constants, declarative data, risk spikes, trivial configuration, or tiny glue changes, unless that specific task genuinely benefits from it. Test what the code decides, not what the language guarantees.

A blocking defect found during implementation is still corrected immediately, before dependent work proceeds. That is forward-progress safety, not review.

## Bundle mechanical gates

Mechanical gates cost machine time rather than reasoning tokens, so they stay — but they run **once per bundle at convergence**, not after every member:

```bash
python -m pytest
python -m ruff check packages tests
python -m mypy packages tests
```

Add build, packaging, import, or smoke-integration checks where the bundle's changes make them relevant. Summarize results in one or two lines. A passing mechanical check needs no prose analysis; only failures need explanation.

## Implementation-side consolidation

At the end of an implementation bundle, the top-level orchestrator verifies only enough to hand off coherent work:

- the authorized scope was implemented;
- acceptance criteria appear materially satisfied;
- the architecture and contracts directly touched were respected;
- worker outputs integrate coherently;
- bundle mechanical gates are acceptable;
- no obvious or blocking defect remains.

The orchestrator does **not** perform Phase B work here: no hidden-bug hunting, no subtle-regression analysis, no distant edge cases, no broad architectural audit, no exhaustive test-sufficiency judgment.

## Review handoff

Each implementation bundle normally produces exactly one concise handoff in [`review-handoffs/`](review-handoffs/), following [`review-handoffs/TEMPLATE.md`](review-handoffs/TEMPLATE.md).

**The handoff prepares the review; it does not perform it.** It must not contain review findings written as though a review already happened, restate the architecture, or duplicate Linear issue content. It is not a source of truth.

It records: bundle members and implementing ecosystem; what was implemented; the main expected behavior; architecture and seams touched; relevant file and diff areas; implementation-side validation already run and its concise results; known limitations and intentionally unvalidated areas; suggested review targets; and that the reviewer is human-selected.

Writing the handoff is the last act of the implementation run.

After a separately authorized post-bundle review runs, that same handoff receives one concise **Post-Bundle Review Outcome** section — reviewer, ecosystem, date, status, then `Fixed now`, `Deferred considerations`, and `Dismissed`. Do not create a separate routine review-report file, and do not let the handoff grow into an audit log. Deferred items are the part with a long life: they are what the deferred review sweep reads at final V1 validation.

## Post-bundle review

Phase B is a separate execution run and begins only on explicit human authorization. The human selects the reviewer: Claude reviewing a Codex-created bundle, Codex reviewing a Claude-created bundle, the same ecosystem in a fresh run, another agent configuration, the human alone, or deliberately deferring the review.

Cross-provider review is supported and often valuable — a reviewer with different execution context catches different defects, and it spreads token usage across ecosystems. **It is not mandatory, and no rule requires any particular ecosystem to review another's work.**

The reviewer receives the repository and diff, the Review Handoff, the relevant architecture sources, and the relevant Linear acceptance criteria. It may then do the deep work that implementation deliberately skipped: hidden-bug hunting, regression analysis, architecture and seam auditing, edge-case inspection, identification of missing validation, test recommendations, and correctness, security, lifecycle, or concurrency concerns where relevant.

This phase may be deliberately slower than implementation.

### Cheap defensive hardening

The reviewer may apply a small defensive fix directly, without a separate authorized run, when **all** of the following hold: it sits at a public or important internal boundary; it is obvious and low-risk; it changes no architecture and broadens no scope; it converts an obscure failure into a clearer contract or runtime error; it is materially cheaper to fix now than to record as deferred; and its validation is small and proportional.

*Cheap defensive hardening is welcome at public boundaries when it turns obscure misuse into a clear contract error without materially expanding the implementation.*

Typical: explicit runtime type validation at a public contract boundary, clearer handling of invalid caller input, a tiny invariant, or typing/package metadata the existing contract clearly already requires.

This is not permission for speculative abstractions, broad defensive programming, architecture redesign, large refactors, functionality added "just in case", or exhaustive validation. Anything that does not meet every condition above is a finding, not a fix.

### Classifying findings

Every finding ends in exactly one of three states:

- **Fixed now** — corrected during the review under the rule above.
- **Deferred** — the concern is valid, but it is not required for safe forward progress, current evidence does not justify implementing it, doing so now would be premature or overengineered, or a later component will supply better evidence. **Every deferred item states when it should be reconsidered.**
- **Dismissed** — considered and intentionally rejected, or no longer relevant.

The reviewer appends the outcome to the bundle's existing handoff and returns prioritized findings to the human. Anything beyond cheap hardening is implemented only under a separately authorized run.

### Deferred review sweep

At final V1 validation, the reviewer may collect the still-unresolved `Deferred considerations` from completed handoffs and, for each: compare it against the current repository, dismiss it if later work already solved it or made it obsolete, implement it only if it now matters for V1 correctness or maintainability, and leave genuinely post-V1 concerns deferred.

The sweep means *re-evaluate deferred items using the completed V1 as evidence* — never *implement every deferred item*. It uses the existing V1 validation work; it does not add a validation bundle after every implementation bundle or a new Linear structure.

## Deep validation at convergence points

Broader system-level validation belongs at the meaningful convergence points the DAG already defines — engine convergence and `Engine E2E Validation`, desktop integration convergence, and `V1 Validation` / release validation. Preserve those nodes and their acceptance criteria.

Do not create a mandatory validation bundle after every implementation bundle, and do not invent new Linear issues or alter the DAG to host validation. The per-bundle handoff and human-selected review are separate from, and do not replace, those deeper system validation stages.

## Artifact budget

Durable execution state lives in: Linear; one ledger per bundle under `checkpoints/` when pause/resume needs it; and one handoff per bundle under `review-handoffs/`.

Do not create per-worker reports, per-issue task or implementation reports, review or re-review reports, or duplicated diff descriptions. Do not commit `.diff` or patch files anywhere in the repository; Git already holds every diff, and a committed copy is a second, stale source of truth. Do not restate in an artifact what a Linear comment already records.

Prose costs the same tokens as code and is read again by every later agent. If an artifact will not be read after this bundle closes, do not write it.

## Single-issue execution

1. Confirm the issue is `READY` and authorized, then plan it as briefly as its tier warrants.
2. Move it to `In Progress` when active planning or implementation begins.
3. Implement only its scope and run its implementation-side checks.
4. Correct any blocking defect. Run the relevant mechanical gates once.
5. Write the review handoff, move the issue to `In Review`, and stop.
6. If the human requests changes, return it to `In Progress`; after correction, return it to `In Review` and stop again.
7. Move it to `Done` only after explicit human approval. Then reevaluate real Linear dependencies, identify newly READY issues, move newly actionable work from `Backlog` to `Todo` when appropriate, and stop unless another execution unit is separately authorized.

## Bundle execution and internal progression

1. Create one concise bundle plan: member issues, tiers, internal waves/workstreams, issue-local acceptance and checks, bundle gates, risks, and the stop boundary. This is the only plan; do not layer a second one on top of it.
2. Move a member to `In Progress` only when it is actively being planned or implemented. Context loading and readiness inspection alone do not change state.
3. Implement and check each member against its own scope. Record results without marking it `Done`.
4. A dependent member becomes **`BUNDLE-READY`** when every blocker outside the bundle is satisfied and every predecessor inside the bundle has met its acceptance criteria sufficiently for dependent work, with its implementation-side checks passing. `BUNDLE-READY` is an execution convention, not a Linear status or human approval.
5. A failed local invariant, required check, or predecessor acceptance criterion blocks affected internal progression immediately.
6. Use internal waves until all members reach the bundle convergence boundary. Intermediate members may remain `In Progress`; use concise Linear comments or one ledger when pause/resume needs it.
7. Run the bundle mechanical gates once, then the implementation-side consolidation above.
8. Correct blocking defects and rerun the affected gates.
9. Write one Review Handoff, move all handed-off members to `In Review`, and stop. Do not mark them `Done`, and do not begin Phase B.
10. If the human requests changes, return affected members to `In Progress`, correct and recheck the affected scope, then return the bundle to `In Review`.
11. After explicit human approval, move only the approved members to `Done`, reevaluate native Linear dependencies, move newly actionable issues from `Backlog` to `Todo` when appropriate, and stop. Bundle approval does not authorize the next bundle, Phase B, or any Git action.

Human review may approve the whole bundle or only specific members. Partial approval must remain visible in issue states and must not be used to bypass a rejected or unresolved dependency.

## Linear lifecycle

- `Backlog`: blocked, deferred, future, or intentionally not actionable.
- `Todo`: READY; all real blockers are satisfied.
- `In Progress`: the issue is actively being planned and/or implemented; inspection, readiness checks, and context loading alone do not require this transition.
- `In Review`: implementation is complete and handed off; human review — and any human-authorized deep review — is pending.
- `Done`: the human has explicitly approved completion.

`In Review` means the implementation phase finished and the work is available for review. It does not assert that a deep review happened. When a bundle reaches its handoff boundary, record that truthfully with a concise Linear comment naming the handoff and whether deep review has been requested, deferred, or not yet chosen. Do not invent new Linear statuses for the phase separation, and do not silently redefine `Done` or human approval.

Promote an issue from `Backlog` to `Todo` when its real Linear blockers are satisfied and the work is genuinely actionable now. Work that is deliberately future, optional, or non-V1 stays in `Backlog` even with no blocker, and promotion never removes, adds, or edits a blocker relationship.

Linear blocker relationships — not conversation memory, priority, or wave numbers — govern native READY/BLOCKED state. `BUNDLE-READY` never overrides an external blocker and never changes a native blocker relationship.

Keep Linear as the granular live tracker. By default, do not create bundle parent issues, repurpose wave milestones, alter blockers, or maintain speculative future bundle objects.

## Issue-local planning

A Light-tier member needs no plan of its own; the bundle plan is its plan. Otherwise a plan contains only the detail needed to execute the current authorized issue or bundle safely: likely files, bounded steps, relevant interfaces/contracts, its checks, risks, internal dependencies, and applicable architecture constraints.

It must not plan work outside the authorized unit, redesign later waves, speculate about unapproved work, expand Architecture V1, or add abstractions for hypothetical reuse. If planning exposes an architecture conflict, stop, report it, and wait for explicit human approval before changing any architecture source of truth.

## Agent execution

`04-agent-execution-flow.md` is the authority; this plan adds no topology.

- GPT execution keeps Sol as top-level orchestrator dispatching Luna xhigh workers **directly** by default. Terra is optional and used only when decomposition, coordination, or integration judgment materially helps the authorized bundle. Do not insert Terra merely because the GPT ecosystem was selected, and do not treat Terra as mandatory for Gate-tier work.
- When runtime concurrency is limited, spend the available slots on implementation workers.
- When three to five genuinely independent workstreams exist, target approximately three to five Luna xhigh workers. This is a target compatible with runtime limits, not a quota: do not create artificial workstreams, and do not default to one worker when useful parallelism exists.
- Any GPT Luna worker must be instantiated under the model/reasoning policy in `04`. If that configuration cannot be instantiated, stop the delegation and report it; never silently substitute another configuration unless the human authorizes it for that run. Do not report unverifiable runtime metadata as a finding — state it once and continue.
- Claude execution keeps Opus 5 as orchestrator and default direct executor, with optional subagents. There is no cross-provider meta-orchestrator.
- Either ecosystem follows the same bundle boundary, granular Linear lifecycle, proportional implementation-side checking, single handoff, checkpoint, and human-approval rules.

Separate reviewers during implementation are the exception, authorized case by case by the orchestrator for genuinely risky work — not the default for Light, Standard, or ordinary Gate members.

## Checkpoints and stop conditions

Use `docs/execution/checkpoints/` only for concise state that must survive a pause or context loss.

- **Handoff stop:** after the Review Handoff is written and members move to `In Review`, execution stops.
- **Convergence checkpoint:** after a meaningful boundary, create a short summary only when it adds durable value beyond Linear and the handoff.
- **Explicit checkpoint:** stop at the human's named issue, wave, milestone, or boundary even if more work is READY.
- **Manual interruption:** stop whenever the human requests it and leave durable state coherent.

Also stop on a genuine new blocker, architecture conflict, failed required gate, unavailable required agent/model configuration, unsafe tool/environment failure, or completion of the authorized scope. Do not create a checkpoint file for every trivial action.

Execution authorization is bounded by the human's command. Never infer permission to continue beyond the explicitly authorized issue, wave, checkpoint, milestone, or execution boundary — and never infer permission to begin Phase B.

## Reports

Use `docs/execution/reports/` only for durable technical evidence whose value exists independently of any later review — reproducible cross-platform findings, investigations, spike evidence.

Never create a report for routine worker activity, and never as a record that an issue was completed; Linear and the handoff carry that. Reports support but never override Architecture V1, Linear state, or issue acceptance criteria.

## Pause and resume

Resume from durable state, not conversation memory:

1. Read `CLAUDE.md`.
2. Inspect the current Linear project, active member issues, blockers, comments, and states.
3. Read the authorized bundle record or issue boundary and relevant architecture sources.
4. Read only relevant checkpoint, handoff, or report artifacts, if any.
5. Reconstruct which members are active, checked, `BUNDLE-READY`, blocked, or handed off from durable evidence.
6. Continue from the actual repository, validation, and Linear state without restarting completed work, inventing bundle membership, or inferring `Done`.

## Failure and governance

For implementation, validation, tool, dispatch, or environment failure: identify the cause, preserve useful evidence, and retry only when technically justified. Do not silently change architecture, provider/model policy, dependencies, or acceptance criteria; do not present incomplete work for human approval.

Add or update a Linear blocker only when evidence establishes a genuine blocker. Avoid speculative issues. Agents may propose architecture changes, but Architecture V1 changes require explicit human approval.

Agents may inspect, plan, edit, implement, test, and review. By default, final commit, push, and merge remain human actions; agents commit, push, or merge only when explicitly authorized. Issue or bundle approval does not itself provide that authorization.

## Example execution instructions

- `Execute the next READY Hanly issue.`
- `Derive and execute the next coherent Hanly bundle; stop at the review handoff.`
- `Execute HAN-6, HAN-7, and HAN-10 as one authorized bundle.`
- `Resume from the current Linear state and execute only HAN-6.`
- `Execute until the Manual Hotkey Lookup checkpoint.`
- `Review the Wave 2 bundle handoff.` (Phase B — separate authorization.)

These commands define authorization boundaries; the architecture, current Linear state, and selected issue or derived bundle remain authoritative. Authorization for one bundle never silently extends to the next, and authorization to implement is never authorization to review.
