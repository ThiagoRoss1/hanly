# Hanly Agent Execution Flow

Textual companion to the approved [Hanly Agent Execution Flow](visual/Hanly%20Agent%20Execution%20Flow.html) diagram.

## Purpose

This view defines how an authorized `READY` issue or execution bundle becomes executed, reviewed, human-approved, integrated work. An execution bundle is a temporary orchestration and review grouping of related Linear issues; it does not replace those issues, their acceptance criteria, or their blocker relationships. This flow consumes implementation dependencies from the Implementation DAG and Linear; it does not redefine application architecture or implementation blockers.

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

Each issue remains a granular Linear tracking and acceptance unit. Within an explicitly authorized bundle, focused validation may unlock a dependent bundle member without an intermediate human checkpoint; broader integration validation and consolidated review occur before the bundle reaches the Human Review Gate. The bundle ends at that gate, and authorization never carries into the next bundle.

A dependent member whose blockers outside the bundle are satisfied, and whose predecessors inside the bundle have met their acceptance criteria with focused validation passing, is **`BUNDLE-READY`**. This is an execution convention only: it is not a Linear status, it never overrides an external blocker or alters a blocker relationship, and it is not human approval. `05-execution-plan.md` owns its operational rules.

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
↓
Terra
↓
Luna xhigh workers
↓
internal review / verification
↓
Terra consolidation and validation
↓
Sol general review
```

### GPT worker model policy

When the GPT execution path delegates implementation work to Luna workers, the required worker configuration is the Luna model family with `xhigh` reasoning effort. Sol remains the top-level orchestrator, and Terra remains the tech-lead / decomposition layer where applicable; implementation workers intended as Luna must actually be instantiated as Luna with `xhigh` reasoning.

Do not substitute Sol workers merely because the top-level orchestrator is Sol. If the current Codex environment cannot instantiate Luna with `xhigh` reasoning, that delegation step must stop and the limitation must be reported explicitly to the human. The system must not silently fall back to Sol `xhigh`, Terra, or another worker configuration. The human may explicitly authorize a different worker configuration for a specific run.

If Luna `xhigh` is requested and no fallback is detected, but runtime metadata cannot independently verify the actual model or reasoning, report the result as `UNVERIFIED`. This is neither verified success nor evidence of fallback: do not claim verification or silently convert it to `PASS`. Execution may proceed only when the current human-approved policy permits it; if verified model identity is required for that run, stop and request human authorization.

This is an execution-policy requirement, not an architecture dependency.

### Sol — Orchestrator

Sol is the top-level GPT orchestrator. Sol reads project context, interprets the Implementation DAG, reads `READY` Linear work, derives the authorized issue or bundle boundary, organizes any internal execution waves, distributes units of work, tracks results, and returns failed work for correction. A bundle normally uses one Sol orchestration and top-level review cycle rather than repeating the hierarchy for every member. Sol does not need to implement tasks directly.

### Terra — Tech Lead

Terra receives work already planned by Sol and leads the execution team. Terra understands the objective and technical context, may decompose already-planned work further when useful, distributes subtasks, coordinates focused validation and internal bundle progression, and consolidates the integrated result. Terra is not primarily a worker expected to write all code alone.

### Luna xhigh workers

Luna xhigh agents implement bounded subtasks such as implementation, tests, investigation, refactoring, and related documentation. Their count varies with task complexity and independence. When a bundle exposes three to five genuinely independent workstreams, Terra should target approximately three to five parallel Luna xhigh workers. This is a target, not a quota: do not create artificial workstreams, and do not default to one worker when useful parallelism exists.

### Internal review and consolidation

Each issue receives focused implementation validation and local review proportional to its risk. Internal review may inspect implementation details, find bugs, validate tests, detect inconsistencies, and request corrections before consolidation. Terra then gathers the bundle results, resolves internal inconsistencies, runs the broader integration validation required at the convergence boundary, and confirms readiness for top-level review.

Sol performs general review of the consolidated issue or bundle against the authorized scope, architecture, every member's acceptance criteria, tests, regressions, dependencies, and repository integration. Sol reviews the consolidated result rather than necessarily every worker action or line.

If review fails, work returns to Terra and the team for another execution / correction cycle. If it passes, it proceeds to the Human Review Gate.

## Claude execution ecosystem

The approved semantic topology is:

```text
Opus 5
├── direct execution
└── optional Sonnet subagents
```

### Opus 5 — Orchestrator and default executor

Opus 5 is both the top-level Claude orchestrator and the default direct executor. It reads project context, interprets the Implementation DAG, reads `READY` Linear work, selects ready work, plans execution, implements directly when appropriate, reviews results, and coordinates optional subagents.

`Opus 5 → direct execution → review` is a valid default path. Delegation is not mandatory.

### Optional Sonnet subagents

Opus 5 may use a variable number of Sonnet subagents for parallel subtasks, investigation, isolated implementation, tests, review, or context / resource economy. Their results return to Opus 5. Team size and topology remain flexible according to the work.

### Internal review and consolidation

Before final review, Opus 5 may review the work directly or use a subagent, run tests, consolidate delegated results, and request corrections. Opus 5 then performs general review against architecture, task requirements, acceptance criteria, tests, regressions, and repository state.

If review fails, another execution / correction cycle begins. If it passes, the result proceeds to the Human Review Gate. This deliberately flatter flow is the intended default, not an incomplete hierarchy.

## Human review gate

The GPT and Claude paths converge at the same human gate for the completed issue or bundle. The human:

- reads the changes;
- understands the code and decisions;
- runs or tests the work when appropriate;
- checks behavior;
- may reject it and return it to the active ecosystem;
- decides whether the work enters the project.

A rejection starts another execution / correction cycle in the already active ecosystem. Approval permits integration to proceed.

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
→ focused per-issue validation and internal progression
→ bundle integration validation and consolidation
→ top-level ecosystem review
→ human review and approval
→ acceptance / completion decision
→ Linear state update
→ newly unblocked READY work
→ next separately authorized execution unit
```

Failed internal, top-level, or human review loops back to execution / correction before Linear completion. Linear remains the operational source for task status and dependencies.

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

That later configuration must ensure that a worker assigned the `Luna xhigh` semantic role is actually instantiated with the intended model and configuration. This requirement does not select the technical mechanism now.

## Flexibility and execution invariants

- **AEF-INV-01 (diagram principle 1):** The active ecosystem determines the top-level orchestrator.
- **AEF-INV-02 (diagram principle 2):** The GPT ecosystem uses Sol as orchestrator.
- **AEF-INV-03 (diagram principle 3):** Terra acts as Tech Lead of the GPT execution team.
- **AEF-INV-04 (diagram principle 4):** Luna xhigh agents are the GPT workers.
- **AEF-INV-05 (diagram principle 5):** Terra may further decompose already-planned work when useful.
- **AEF-INV-06 (diagram principle 6):** GPT teams may use internal review agents before consolidation.
- **AEF-INV-07 (diagram principle 7):** The Claude ecosystem uses Opus 5 as orchestrator and default executor.
- **AEF-INV-08 (diagram principle 8):** Opus 5 may execute directly without delegation.
- **AEF-INV-09 (diagram principle 9):** Sonnet subagents are optional.
- **AEF-INV-10 (diagram principle 10):** Team size and decomposition may vary according to the authorized issue or bundle.
- **AEF-INV-11 (diagram principle 11):** Parallel execution is encouraged when dependencies permit it.
- **AEF-INV-12 (diagram principle 12):** Top-level orchestrators review consolidated issue or bundle results rather than necessarily every worker action.
- **AEF-INV-13 (diagram principle 13):** Failed review may trigger another execution or correction cycle.
- **AEF-INV-14 (diagram principle 14):** Agents may edit code, inspect repositories, run tests, and propose corrections.
- **AEF-INV-15 (diagram principle 15):** The human retains final approval and commit / push / merge authority.
- **AEF-INV-16 (diagram principle 16):** Linear remains the operational source for task status and dependencies.
- **AEF-INV-17 (diagram principle 17):** The workflow describes roles and responsibilities, not a fixed technical spawning mechanism.

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

- **AEF-INV-18:** Wording such as “may,” “when useful,” and “when appropriate” is intentional and must not be converted into mandatory delegation or team-size rules.
- **AEF-INV-19:** Agents may propose architecture changes, but approved architecture changes require human approval before becoming authoritative.
