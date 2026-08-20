# Hanly V1 Operational Execution Plan

## Purpose

This is the thin orchestration manual for executing Hanly Desktop V1. It does not redefine architecture, duplicate the implementation DAG, or replace Linear. Default execution scope is one Linear issue at a time; never continue into another issue without explicit authorization.

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

## Start and READY selection

1. Read `CLAUDE.md`.
2. Inspect the current Hanly project in Linear.
3. Read the selected issue and the architecture sections relevant to it. Always consult `03-implementation-dag.md` for readiness, dependencies, waves, convergence, and blocker semantics, and `04-agent-execution-flow.md` for execution, delegation, review, authority, and worker-policy semantics.
4. Select only an issue whose real Linear blockers are satisfied and whose state is `Todo`.
5. Use priority only to choose between simultaneously READY issues. Priority never bypasses a blocker.
6. Do not invent dependencies from milestone or wave numbering; absence of an approved blocker preserves potential parallelism.
7. Respect any explicit human issue, wave, or checkpoint boundary even when other work is READY.

## Default one-issue execution loop

1. Confirm the issue is genuinely READY and within the authorized scope.
2. Create a concise JIT plan for that issue only.
3. Move the issue to `In Progress` when active JIT planning/implementation begins.
4. Implement only the selected issue scope and its approved acceptance criteria.
5. Run the issue's required tests, checks, and manual validation.
6. Run the internal agent review flow from `04-agent-execution-flow.md`.
7. Correct findings and repeat validation/internal review until the work is ready for the human.
8. Move the issue to `In Review` and stop for mandatory human review.
9. Do not mark the issue `Done`.
10. If the human requests changes, return it to `In Progress`, apply the changes, repeat validation/internal review, return it to `In Review`, and stop again.
11. Move the issue to `Done` only after explicit human approval of completion. Approval does not itself authorize an agent to commit, push, or merge.
12. After approval, update Linear, reevaluate real dependencies, identify newly READY issues, and move newly actionable work to `Todo` when appropriate.
13. Stop unless continued execution has been explicitly authorized.

## Linear lifecycle

- `Backlog`: blocked, deferred, future, or intentionally not actionable.
- `Todo`: READY; all real blockers are satisfied.
- `In Progress`: the issue is actively being JIT-planned and/or implemented; inspection, readiness checks, and context loading alone do not require this transition.
- `In Review`: internal review has passed and human review is pending.
- `Done`: the human has explicitly approved completion.

Internal review catches defects before handoff; it neither replaces human review nor authorizes `Done`. Linear blocker relationships—not conversation memory, priority, or wave numbers—govern READY/BLOCKED state.

## Issue-local JIT planning

A JIT plan contains only the detail needed to execute the current READY issue safely: likely files, bounded steps, relevant interfaces/contracts, tests and validation, issue-specific risks, and applicable architecture constraints.

It must not plan future issues, redesign later waves, speculate about unapproved work, expand Architecture V1, or add abstractions for hypothetical reuse. If planning exposes an architecture conflict, stop, report it, and wait for explicit human approval before changing any architecture source of truth.

## Agent execution and review

`04-agent-execution-flow.md` is the authority; this plan adds no topology.

- GPT execution keeps Sol as top-level orchestrator, Terra as the tech-lead/decomposition layer where applicable, and Luna as delegated implementation workers when useful.
- Any GPT Luna worker must be instantiated under the model/reasoning policy in `04`. If Luna with `xhigh` reasoning cannot be instantiated, stop that delegation and report the limitation; never silently substitute Sol, Terra, or another configuration unless the human explicitly authorizes it for that run.
- Claude follows its execution path in `04` without a cross-provider meta-orchestrator.
- Either ecosystem follows the same issue scope, Linear lifecycle, validation, internal review, checkpoint, and human-approval rules.

## Checkpoints and stop conditions

Use `docs/execution/checkpoints/` only for concise state that must survive a pause or context loss.

- **Human review checkpoint:** every transition to `In Review`; execution stops.
- **Wave/convergence checkpoint:** after a meaningful boundary, create a short summary only when it adds durable value beyond Linear.
- **Explicit checkpoint:** stop at the human's named issue, wave, milestone, or boundary even if more work is READY.
- **Manual interruption:** stop whenever the human requests it and leave durable state coherent.

Also stop on a genuine new blocker, architecture conflict, failed required validation, unavailable required agent/model configuration, unsafe tool/environment failure, or completion of the authorized issue scope. Do not create a checkpoint file for every trivial action.

Execution authorization is bounded by the human's command. Never infer permission to continue beyond the explicitly authorized issue, wave, checkpoint, milestone, or execution boundary.

## Reports

Use `docs/execution/reports/` for durable evidence with value after context loss, debugging, validation, or human review—for example significant validation, investigation, cross-platform, or agent-runtime findings.

Do not automatically create a report for every issue. Prefer Linear comments/status updates and concise execution output for routine work. Reports support but never override Architecture V1, Linear state, or issue acceptance criteria.

## Pause and resume

Resume from durable state, not conversation memory:

1. Read `CLAUDE.md`.
2. Inspect the current Linear project and issue state.
3. Read the current issue and relevant architecture sources.
4. Read only relevant checkpoint/report artifacts, if any.
5. Continue from the actual repository, validation, and Linear state without restarting completed work or inferring `Done`.

## Failure and governance

For implementation, validation, tool, dispatch, or environment failure: identify the cause, preserve useful evidence, and retry only when technically justified. Do not silently change architecture, provider/model policy, dependencies, or acceptance criteria; do not present incomplete work for human approval.

Add or update a Linear blocker only when evidence establishes a genuine blocker. Avoid speculative issues. Agents may propose architecture changes, but Architecture V1 changes require explicit human approval.

Agents may inspect, plan, edit, implement, test, and review. By default, final commit, push, and merge remain human actions; agents commit, push, or merge only when explicitly authorized. Issue approval does not itself provide that authorization.

## Example execution instructions

- `Execute the next READY Hanly issue.`
- `Continue Hanly execution until the end of Wave 2, stopping at every In Review checkpoint.`
- `Resume from the current Linear state and execute only HAN-6.`
- `Execute until the Manual Hotkey Lookup checkpoint.`
- `Stop after Wave 4.`

These commands define authorization boundaries; the architecture, current Linear state, and selected issue remain authoritative.
