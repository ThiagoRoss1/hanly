# Hanly Agent Execution Flow

Textual companion to the approved [Hanly Agent Execution Flow](visual/Hanly%20Agent%20Execution%20Flow.html) diagram.

## Purpose

This view defines how an authorized `READY` issue or execution bundle becomes executed, handed off, human-approved, integrated work. Execution runs in two separate phases: an implementation run that ends at a Review Handoff, and a later, human-triggered post-bundle review run. An execution bundle is a temporary orchestration and review grouping of related Linear issues; it does not replace those issues, their acceptance criteria, or their blocker relationships. This flow consumes implementation dependencies from the Implementation DAG and Linear; it does not redefine application architecture or implementation blockers.

## Inputs and sources of truth

Agents read the prepared project execution context before work starts:

- product and V1 scope;
- architecture documentation, including Runtime Flow, Component Architecture, and Implementation DAG;
- approved ADRs when they exist;
- repository instructions and relevant skills / configuration;
- the repository and tests as the executable state of the project;
- the Linear project and tasks.

The source-of-truth responsibilities are distinct:

- Architecture documentation defines approved runtime behavior, module seams, dependencies, and invariants.
- The Implementation DAG structurally defines capabilities, dependencies, blockers, waves, convergence points, and milestones.
- Linear materializes the DAG as operational tasks, status, priorities, blockers, and `READY` work.
- The repository and tests contain the implemented and verifiable state.
- The human is the authority for ecosystem selection, acceptance, approved architecture changes, and—by default—final commit, push, and merge.

Only work whose dependencies are satisfied is `READY`. Agent Execution Flow determines how that work is executed; it does not change why work is ready or blocked. A human-authorized bundle may contain internal dependency chains, but an issue may progress internally only after its blockers outside the bundle are satisfied and its predecessors inside the bundle have passed focused validation. That internal progression is not human approval and does not make any issue `Done`.

## Execution units

The authorized unit of work may be one substantial or isolated Linear issue, or an execution bundle of related issues. Bundles are formed dynamically from current `READY` work, real dependencies, component relationships, useful parallelism, and natural convergence boundaries. They are never inferred from consecutive issue numbers and must not cross a major architecture gate merely to enlarge the batch.

The amount of orchestration, delegation, and checking applied to a unit scales
with its risk and seam impact. `05-execution-plan.md` owns those execution tiers
and the operational rules of both phases; this document owns the roles,
authority, and topology they draw from.

### The two phases

```text
PHASE A — IMPLEMENTATION
authorized issue / bundle
→ implementation
→ lightweight implementation-side checks
→ bundle mechanical gates
→ implementation-side consolidation
→ Review Handoff
→ STOP at the Human Review Gate

PHASE B — POST-BUNDLE REVIEW (separate run, human-triggered)
human selects the reviewer and ecosystem
→ deep review
→ prioritized findings
→ human decision and any authorized corrections
```

An implementation run never promotes itself into a deep review session, and
never begins Phase B on its own authority.

Each issue remains a granular Linear tracking and acceptance unit. Within an explicitly authorized bundle, implementation-side checks may unlock a dependent bundle member without an intermediate human checkpoint; the bundle mechanical gates and implementation-side consolidation occur before the bundle reaches the Human Review Gate. The bundle ends at that gate, and authorization never carries into the next bundle.

A dependent member whose blockers outside the bundle are satisfied, and whose predecessors inside the bundle have met their acceptance criteria with implementation-side checks passing, is **`BUNDLE-READY`**. This is an execution convention only: it is not a Linear status, it never overrides an external blocker or alters a blocker relationship, and it is not human approval. `05-execution-plan.md` owns its operational rules.

## Ecosystem selection

The human manually selects one active execution ecosystem for the unit of work, considering availability, limits / tokens, preference, and where relevant context already exists.

GPT and Claude are independent, equivalent entry paths. There is:

- no meta-orchestrator above Sol and Opus 5;
- no automatic routing engine;
- no Sol dispatch of Claude agents;
- no Opus dispatch of GPT agents;
- no mandatory cross-provider review, although the human may request one;
- no fixed number of workers or subagents.

The ecosystem choice is made again for each next authorized issue or execution bundle.

## GPT execution ecosystem

The approved semantic topology is:

```text
Sol
├── Luna xhigh worker
├── Luna xhigh worker
├── Luna xhigh worker
├── ...
└── optional Terra, when materially useful
     └── Luna xhigh workers
↓
implementation-side checks
↓
bundle mechanical gates
↓
Sol implementation-side consolidation
↓
Review Handoff
```

Sol dispatches Luna xhigh workers **directly** by default. Terra is an optional
layer, not a step every bundle passes through.

### GPT worker model policy

When the GPT execution path delegates implementation work to Luna workers, the required worker configuration is the Luna model family with `xhigh` reasoning effort. Sol remains the top-level orchestrator; implementation workers intended as Luna must actually be instantiated as Luna with `xhigh` reasoning.

Do not substitute Sol workers merely because the top-level orchestrator is Sol. If the current Codex environment cannot instantiate Luna with `xhigh` reasoning, that delegation step must stop and the limitation must be reported explicitly to the human. The system must not silently fall back to Sol `xhigh` or another worker configuration. The human may explicitly authorize a different worker configuration for a specific run.

If runtime metadata cannot independently confirm the worker configuration, record that once in the execution ledger and continue. Do not convert it into a verification claim, a review finding, or a per-run reporting ritual. If verified model identity is genuinely required for a run, the human states that at authorization.

This is an execution-policy requirement, not an architecture dependency.

### Sol — Orchestrator

Sol is the top-level GPT orchestrator. Sol reads project context, interprets the Implementation DAG, reads `READY` Linear work, derives the authorized issue or bundle boundary, organizes any internal execution waves, distributes units of work directly to Luna workers, tracks results, returns blocking defects for correction, and owns the implementation-side consolidation and Review Handoff at the end of the bundle. A bundle normally uses one Sol orchestration cycle rather than repeating any hierarchy per member. Sol does not need to implement tasks directly.

When runtime concurrency is limited, Sol spends the available slots on implementation workers.

### Terra — optional tech lead

Terra is **optional**. Sol uses it only when additional technical decomposition,
coordination, or integration judgment materially helps the authorized bundle —
for example when several workers modify a tightly coupled seam, when non-trivial
integration conflicts are expected, when significant decomposition would benefit
from a tech-lead layer, or when Sol judges that Terra adds more value than one
additional implementation slot.

Do not insert Terra merely because the GPT ecosystem was selected, and do not
treat Terra as mandatory for any tier of work, Gate tier included.

When Terra is used, it receives work already planned by Sol, may decompose it
further, distributes subtasks, coordinates internal bundle progression, and
consolidates the integrated result. Terra is not primarily a worker expected to
write all code alone.

### Luna xhigh workers

Luna xhigh agents implement bounded subtasks such as implementation, tests, investigation, refactoring, and related documentation. Their count varies with task complexity and independence. When a bundle exposes three to five genuinely independent workstreams, whoever is dispatching should target approximately three to five parallel Luna xhigh workers. This is a target compatible with runtime concurrency limits, not a quota: do not create artificial workstreams, and do not default to one worker when useful parallelism exists.

### Implementation-side checks and consolidation

Each member receives implementation-side checking proportional to its risk. Its
purpose is to enable safe forward progress and to stop a defective member from
unblocking dependent work — not to prove correctness exhaustively. A worker
normally self-checks its own task against its acceptance criteria, the invariants
it directly touches, and a focused functional or smoke check. A separate reviewer
during implementation is used only when Sol judges that specific work risky
enough to need one; it is not the default for any tier.

Sol then runs the bundle mechanical gates once and performs the
implementation-side consolidation: authorized scope implemented, acceptance
criteria materially satisfied, touched architecture respected, worker outputs
integrating coherently, gates acceptable, no obvious or blocking defect left. Sol
does not perform hidden-bug hunting, subtle-regression analysis, edge-case
inspection, broad architectural audit, or test-sufficiency judgment here — that
is Phase B.

Blocking defects are corrected before the bundle proceeds. When the bundle is
coherent, Sol writes the Review Handoff and execution stops at the Human Review
Gate.

## Claude execution ecosystem

The approved semantic topology is:

```text
Opus 5
├── direct execution
└── optional Sonnet subagents
```

### Opus 5 — Orchestrator and default executor

Opus 5 is both the top-level Claude orchestrator and the default direct executor. It reads project context, interprets the Implementation DAG, reads `READY` Linear work, selects ready work, plans execution, implements directly when appropriate, checks results, coordinates optional subagents, and owns the implementation-side consolidation and Review Handoff.

`Opus 5 → direct execution → handoff` is a valid default path. Delegation is not mandatory.

### Optional Sonnet subagents

Opus 5 may use a variable number of Sonnet subagents for parallel subtasks, investigation, isolated implementation, tests, review, or context / resource economy. Their results return to Opus 5. Team size and topology remain flexible according to the work.

### Implementation-side checks and consolidation

Opus 5 may check members directly or use a subagent, run the bundle mechanical
gates, consolidate delegated results, and require correction of blocking defects.
It then performs the same implementation-side consolidation defined for Sol,
under the same limit: forward-progress safety and coherent handoff, not deep
review.

When the bundle is coherent, Opus 5 writes the Review Handoff and execution stops
at the Human Review Gate. This deliberately flatter flow is the intended default,
not an incomplete hierarchy.

## Human review gate

The GPT and Claude paths converge at the same human gate for the completed issue or bundle, carrying the Review Handoff. The human:

- reads the changes and the handoff;
- understands the code and decisions;
- runs or tests the work when appropriate;
- checks behavior;
- decides whether deep review is wanted now, later, or not at all — and who performs it;
- may reject the work and return it to the active ecosystem;
- decides whether the work enters the project.

A rejection starts another execution / correction cycle in the already active ecosystem. Approval permits integration to proceed.

## Post-bundle review

Deep review is a separate execution phase. The implementation run must not start
it; it begins only on explicit human authorization, and the human selects the
reviewer — Claude reviewing a Codex-created bundle, Codex reviewing a
Claude-created bundle, the same ecosystem in a fresh run, another agent
configuration, the human alone, or a deliberate decision to defer.

Cross-provider review is supported and often valuable, because a reviewer with
different execution context catches different defects and the token cost spreads
across ecosystems. It remains **optional**; no rule requires any ecosystem to
review another's work.

The reviewer receives the repository and diff, the Review Handoff, the relevant
architecture sources, and the relevant Linear acceptance criteria. It may then do
the work implementation deliberately skipped: hidden-bug hunting, regression
analysis, architecture and seam auditing, edge-case inspection, identification of
missing validation, test recommendations, and correctness, security, lifecycle,
or concurrency concerns where relevant. This phase may be deliberately slower
than implementation.

The reviewer may apply cheap defensive hardening directly — a small, obvious,
low-risk fix at a public or important internal boundary that turns obscure misuse
into a clear contract error without changing architecture or broadening scope.
Everything else is a finding, classified as **Fixed now**, **Deferred** (valid but
premature, with a stated revisit trigger), or **Dismissed**, and appended as one
concise outcome section to the bundle's existing handoff. The reviewer does not
become a second implementation orchestrator; corrections beyond cheap hardening
happen only under a separately authorized run.

Its output is concise findings prioritized by importance, returned to the human.
Broader system-level validation remains at the convergence capabilities the
Implementation DAG already defines and is not replaced by this phase. At final V1
validation, still-unresolved deferred items are re-evaluated against the completed
V1 rather than implemented wholesale. `05-execution-plan.md` owns these operational
rules.

## Architecture change authority

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

Agents may identify architecture problems and propose architecture changes. When asked, they may draft an ADR or an architecture-documentation patch for human review. They must not silently redefine approved architecture.

A change to the approved architecture source of truth becomes authoritative only after human approval. This architecture-governance gate is separate from commit, push, and merge authority: human approval of a proposed architecture decision does not itself authorize an agent to commit, push, or merge it.

## Commit, push, and merge authority

> By default, final commit, push, and merge authority remains human. Agents only commit, push, or merge when explicitly instructed by the human.

Human approval of completed work establishes acceptance; it does not itself authorize an agent to commit, push, or merge.

Without that explicit instruction, agents may still:

- edit files;
- write code;
- run tests;
- inspect and analyze the repository;
- review;
- correct;
- prepare changes.

Automatic commit, push, or merge is not part of the approved flow.

## Linear execution loop

After human approval, Linear is updated according to the approved lifecycle: the applicable issue or bundle members are updated, approved work is marked when applicable, dependent work is unblocked, and newly ready tasks are identified. Any commit, push, or merge remains a separate human-controlled action unless explicitly delegated.

```text
authorized READY issue or execution bundle
→ execution in the human-selected ecosystem
→ implementation-side checks and internal progression
→ bundle mechanical gates and implementation-side consolidation
→ Review Handoff
→ human review, and optional human-authorized post-bundle review
→ acceptance / completion decision
→ Linear state update
→ newly unblocked READY work
→ next separately authorized execution unit
```

A blocking defect, or a human or post-bundle review finding the human decides to act on, loops back to execution / correction before Linear completion. Linear remains the operational source for task status and dependencies.

## Workflow vs technical agent configuration

This document defines semantic roles, authority, and execution responsibilities. It does not define how agents are technically instantiated.

The following belong to a later agent configuration and infrastructure layer and are deliberately not hardcoded here:

- `AGENTS.md`;
- `.agents`;
- `.codex`;
- `config.toml`;
- Claude subagent configuration;
- spawning commands;
- model-selection files;
- skills.

The Hanly execution plan is authoritative for Hanly V1 execution: generic execution skills may assist, but must not add a second execution plan, another decomposition layer, mandatory per-task reviewers, re-review loops, or duplicate reports, checkpoints, and validation on top of it.

That later configuration must ensure that a worker assigned the `Luna xhigh` semantic role is actually instantiated with the intended model and configuration. This requirement does not select the technical mechanism now.

## Flexibility and execution invariants

- **AEF-INV-01 (diagram principle 1):** The active ecosystem determines the top-level orchestrator.
- **AEF-INV-02 (diagram principle 2):** The GPT ecosystem uses Sol as orchestrator.
- **AEF-INV-03 (diagram principle 3):** Terra is an optional GPT tech-lead layer, used only when it materially helps the authorized bundle.
- **AEF-INV-04 (diagram principle 4):** Luna xhigh agents are the GPT workers.
- **AEF-INV-05 (diagram principle 5):** Terra may further decompose already-planned work when useful.
- **AEF-INV-06 (diagram principle 6):** GPT teams may use a separate review agent during implementation when risk justifies it; it is not the default.
- **AEF-INV-07 (diagram principle 7):** The Claude ecosystem uses Opus 5 as orchestrator and default executor.
- **AEF-INV-08 (diagram principle 8):** Opus 5 may execute directly without delegation.
- **AEF-INV-09 (diagram principle 9):** Sonnet subagents are optional.
- **AEF-INV-10 (diagram principle 10):** Team size and decomposition may vary according to the authorized issue or bundle.
- **AEF-INV-11 (diagram principle 11):** Parallel execution is encouraged when dependencies permit it.
- **AEF-INV-12 (diagram principle 12):** Top-level orchestrators consolidate the issue or bundle for handoff rather than inspecting every worker action.
- **AEF-INV-13 (diagram principle 13):** Failed review may trigger another execution or correction cycle.
- **AEF-INV-14 (diagram principle 14):** Agents may edit code, inspect repositories, run tests, and propose corrections.
- **AEF-INV-15 (diagram principle 15):** The human retains final approval and commit / push / merge authority.
- **AEF-INV-16 (diagram principle 16):** Linear remains the operational source for task status and dependencies.
- **AEF-INV-17 (diagram principle 17):** The workflow describes roles and responsibilities, not a fixed technical spawning mechanism.

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

- **AEF-INV-18:** Wording such as “may,” “when useful,” and “when appropriate” is intentional and must not be converted into mandatory delegation or team-size rules.
- **AEF-INV-19:** Agents may propose architecture changes, but approved architecture changes require human approval before becoming authoritative.
- **AEF-INV-20:** Implementation and deep review are separate execution phases. An implementation run ends at the Review Handoff and never begins post-bundle review on its own authority.
- **AEF-INV-21:** The human selects the post-bundle reviewer and ecosystem. Cross-provider review is supported but never mandatory.
- **AEF-INV-22:** A post-bundle reviewer may apply cheap defensive hardening at a boundary; every other finding is recorded as Fixed now, Deferred with a revisit trigger, or Dismissed, and never silently dropped.
