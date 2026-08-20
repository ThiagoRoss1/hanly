# Hanly V1 Operational Execution Plan

## Purpose

This is the thin orchestration manual for executing Hanly Desktop V1. It does not redefine architecture, duplicate the implementation DAG, or replace Linear. The normal orchestration unit is an execution bundle when multiple related issues share a useful capability or convergence boundary; a single issue remains the correct unit for isolated, substantial, or high-risk work. Never continue beyond the human-authorized issue or bundle.

## Sources of truth

Read and apply these sources according to their ownership:

- [`CLAUDE.md`](../../CLAUDE.md): current repository state, commands, and base project guidance.
- [`01-runtime-flow.md`](../architecture/01-runtime-flow.md): runtime behavior and concurrency constraints.
- [`02-component-architecture.md`](../architecture/02-component-architecture.md): ownership, package boundaries, dependency direction, and component responsibilities.
- [`03-implementation-dag.md`](../architecture/03-implementation-dag.md): waves, structural order, real blockers, parallelism, convergence, and gates.
- [`04-agent-execution-flow.md`](../architecture/04-agent-execution-flow.md): ecosystem roles, delegation, internal review, human authority, commit/push/merge policy, and GPT worker model policy.
- Linear: live issues, blocker relationships, milestones, priority, type, and execution status.
- The repository and tests: implemented and verifiable state.

When sources differ in purpose, use the source that owns the decision. Do not turn this document, a checkpoint, or a report into a competing source of truth.

## Start and execution-unit selection

1. Read `CLAUDE.md`.
2. Inspect the current Hanly project in Linear.
3. Read the candidate issues and relevant architecture sections. Always consult `03-implementation-dag.md` for readiness, dependencies, waves, convergence, and blocker semantics, and `04-agent-execution-flow.md` for execution, delegation, review, authority, and worker-policy semantics.
4. Identify root `READY` issues: their real blockers are satisfied and their Linear state is `Todo`.
5. Select either one issue or derive a candidate bundle from root `READY` work plus related descendants whose only unsatisfied blockers are inside that bundle.
6. Use real dependencies, component relationships, useful parallelism, and a natural capability or convergence boundary. Never group by consecutive issue numbers, cross a major architecture gate merely to enlarge a bundle, or make a bundle too large for meaningful human review.
7. Use priority only to choose between simultaneously eligible roots. Priority never bypasses a blocker.
8. Record the authorized member issues, internal dependency order, focused per-issue validation, bundle validation, and stop boundary before implementation begins.
9. Respect the human's explicit issue, bundle, wave, or checkpoint boundary even when other work is eligible.

An **Execution Bundle** is a temporary orchestration and review grouping. It does not merge issues, change their scope or acceptance criteria, remove blockers, or become a competing architecture plan. The human may authorize an explicitly named bundle or command execution of the next dynamically derived bundle.

## Single-issue execution

1. Confirm the issue is `READY` and authorized, then create its concise JIT plan.
2. Move it to `In Progress` when active JIT planning or implementation begins.
3. Implement only its scope and run focused validation appropriate to its changes.
4. Run proportional internal review, correct findings, and repeat required validation.
5. Move it to `In Review` and stop for human review.
6. If changes are requested, return it to `In Progress`; after correction and review, return it to `In Review` and stop again.
7. Move it to `Done` only after explicit human approval. Then reevaluate real Linear dependencies, identify newly READY issues, move newly actionable work from `Backlog` to `Todo` when appropriate, and stop unless another execution unit is separately authorized.

## Bundle execution and internal progression

1. Create one concise bundle plan containing member issues, internal waves/workstreams, issue-local acceptance and validation, bundle-level validation, risks, and the human checkpoint.
2. Move a member to `In Progress` only when it is actively being JIT-planned or implemented. Context loading and readiness inspection alone do not change state.
3. Implement and validate each member against its own scope. Record focused validation and internal review results without marking it `Done`.
4. A dependent member becomes **`BUNDLE-READY`** when every blocker outside the bundle is satisfied and every predecessor inside the bundle has met its acceptance criteria sufficiently for dependent work, with focused validation passing. `BUNDLE-READY` is an execution convention, not a Linear status or human approval.
5. A failed local invariant, required check, or predecessor acceptance criterion blocks affected internal progression immediately. Do not defer it to bundle validation.
6. Use internal waves until all members reach the bundle convergence boundary. Intermediate members may remain `In Progress`; use concise Linear comments or a durable checkpoint when needed to record internal completion truthfully.
7. Run the broader bundle validation needed to establish integration, then Terra consolidation and Sol top-level review under `04`.
8. Correct findings and repeat affected focused and bundle validation until the consolidated bundle is ready.
9. Move all review-ready bundle members to `In Review` and stop at one human bundle checkpoint. Do not mark them `Done`.
10. If the human requests changes, return affected members to `In Progress`, correct and revalidate the affected scope and integration, then return the bundle to `In Review`.
11. After explicit human approval, move only the approved members to `Done`, reevaluate native Linear dependencies, move newly actionable issues from `Backlog` to `Todo` when appropriate, and stop. Bundle approval does not authorize the next bundle or any Git action.

Human review may approve the whole bundle or only specific members. Partial approval must remain visible in issue states and must not be used to bypass a rejected or unresolved dependency.

## Validation proportionality

Per-issue validation is focused on what that issue changed and the directly affected behavior. Configuration and documentation changes receive appropriate structural or consistency checks; providers receive focused unit/provider tests; spikes gather enough reproducible evidence to answer their stated risk rather than production-grade exhaustive testing. Do not manufacture large test suites or repeat every broad project gate solely because each issue has its own Linear lifecycle.

At bundle convergence, run the broader tests, integration checks, static checks, builds, regressions, cross-component checks, and acceptance scenarios relevant to the combined changes. Necessary early tests remain early; no failing invariant or unsafe dependency is deferred merely to reduce repetition.

## Linear lifecycle

- `Backlog`: blocked, deferred, future, or intentionally not actionable.
- `Todo`: READY; all real blockers are satisfied.
- `In Progress`: the issue is actively being JIT-planned and/or implemented; inspection, readiness checks, and context loading alone do not require this transition.
- `In Review`: internal review has passed and human review is pending.
- `Done`: the human has explicitly approved completion.

Promote an issue from `Backlog` to `Todo` when its real Linear blockers are satisfied and the work is genuinely actionable now. Work that is deliberately future, optional, or non-V1 stays in `Backlog` even with no blocker, and promotion never removes, adds, or edits a blocker relationship.

Internal review catches defects before handoff; it neither replaces human review nor authorizes `Done`. Linear blocker relationships—not conversation memory, priority, or wave numbers—govern native READY/BLOCKED state. `BUNDLE-READY` never overrides an external blocker and never changes a native blocker relationship; it only records that a validated predecessor inside the same authorized bundle is sufficient for internal progression.

Keep Linear as the granular live tracker. By default, do not create bundle parent issues, repurpose wave milestones, alter blockers, or maintain speculative future bundle objects. During an active bundle, record membership and internal state with the lightest durable mechanism that remains clear—normally concise issue comments and, when pause/resume needs it, one checkpoint. A persistent bundle label is justified only if a stable recurring grouping later proves useful.

## Issue-local JIT planning

A JIT plan contains only the detail needed to execute the current authorized issue or bundle safely: likely files, bounded steps, relevant interfaces/contracts, focused issue validation, bundle validation where applicable, risks, internal dependencies, and applicable architecture constraints.

It must not plan work outside the authorized unit, redesign later waves, speculate about unapproved work, expand Architecture V1, or add abstractions for hypothetical reuse. If planning exposes an architecture conflict, stop, report it, and wait for explicit human approval before changing any architecture source of truth.

## Agent execution and review

`04-agent-execution-flow.md` is the authority; this plan adds no topology.

- GPT execution keeps Sol as top-level orchestrator, Terra as the tech-lead/decomposition and integration layer, and Luna as delegated implementation workers. A bundle normally uses one Sol → Terra orchestration/review cycle rather than repeating the hierarchy for every member.
- Any GPT Luna worker must be instantiated under the model/reasoning policy in `04`. If Luna with `xhigh` reasoning cannot be instantiated, stop that delegation and report the limitation; never silently substitute Sol, Terra, or another configuration unless the human explicitly authorizes it for that run.
- When three to five genuinely independent workstreams exist, Terra should target approximately three to five Luna xhigh workers. This is not a quota: do not create idle/artificial workers or split tightly coupled work, but do not default to one worker when useful parallelism exists.
- Claude follows its execution path in `04` without a cross-provider meta-orchestrator.
- Either ecosystem follows the same issue/bundle boundary, granular Linear lifecycle, proportional validation, consolidated review, checkpoint, and human-approval rules.

Worker/local review is proportional to each member's risk. Terra performs bundle integration and consolidation; Sol reviews the consolidated bundle against its authorized scope, architecture, every member's acceptance criteria, regressions, and integration. High-risk or architecture-sensitive work may receive additional review when justified.

## Checkpoints and stop conditions

Use `docs/execution/checkpoints/` only for concise state that must survive a pause or context loss.

- **Human review checkpoint:** after a single issue or all review-ready bundle members transition to `In Review`; execution stops.
- **Wave/convergence checkpoint:** after a meaningful boundary, create a short summary only when it adds durable value beyond Linear.
- **Explicit checkpoint:** stop at the human's named issue, wave, milestone, or boundary even if more work is READY.
- **Manual interruption:** stop whenever the human requests it and leave durable state coherent.

Also stop on a genuine new blocker, architecture conflict, failed required validation, unavailable required agent/model configuration, unsafe tool/environment failure, or completion of the authorized issue/bundle scope. Do not create a checkpoint file for every trivial action.

Execution authorization is bounded by the human's command. Never infer permission to continue beyond the explicitly authorized issue, wave, checkpoint, milestone, or execution boundary.

## Reports

Use `docs/execution/reports/` for durable evidence with value after context loss, debugging, validation, or human review—for example significant validation, investigation, cross-platform, or agent-runtime findings.

Do not automatically create a report for every issue. Prefer Linear comments/status updates and concise execution output for routine work. Reports support but never override Architecture V1, Linear state, or issue acceptance criteria.

## Pause and resume

Resume from durable state, not conversation memory:

1. Read `CLAUDE.md`.
2. Inspect the current Linear project, active member issues, blockers, comments, and states.
3. Read the authorized bundle record or issue boundary and relevant architecture sources.
4. Read only relevant checkpoint/report artifacts, if any.
5. Reconstruct which members are active, internally validated, `BUNDLE-READY`, blocked, or awaiting bundle validation from durable evidence.
6. Continue from the actual repository, validation, and Linear state without restarting completed work, inventing bundle membership, or inferring `Done`.

## Failure and governance

For implementation, validation, tool, dispatch, or environment failure: identify the cause, preserve useful evidence, and retry only when technically justified. Do not silently change architecture, provider/model policy, dependencies, or acceptance criteria; do not present incomplete work for human approval.

Add or update a Linear blocker only when evidence establishes a genuine blocker. Avoid speculative issues. Agents may propose architecture changes, but Architecture V1 changes require explicit human approval.

Agents may inspect, plan, edit, implement, test, and review. By default, final commit, push, and merge remain human actions; agents commit, push, or merge only when explicitly authorized. Issue approval does not itself provide that authorization.

## Example execution instructions

- `Execute the next READY Hanly issue.`
- `Derive and execute the next coherent Hanly bundle; stop when the bundle is In Review.`
- `Execute HAN-6, HAN-7, and HAN-10 as one authorized bundle.`
- `Resume from the current Linear state and execute only HAN-6.`
- `Execute until the Manual Hotkey Lookup checkpoint.`
- `Stop after Wave 4.`

These commands define authorization boundaries; the architecture, current Linear state, and selected issue or derived bundle remain authoritative. Authorization for one bundle never silently extends to the next.
