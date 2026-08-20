# Bundle Workflow Optimization Review

> **Superseded (2026-08-20).** This document describes the earlier execution
> model, in which every issue passed through a Sol -> Terra -> Luna hierarchy with
> per-issue review and a deep consolidated review inside the implementation run.
> The current workflow is defined in `docs/execution/05-execution-plan.md` and
> `docs/architecture/04-agent-execution-flow.md`: Sol dispatches Luna directly,
> Terra is optional, implementation-side checks are lightweight, and deep review
> is a separate human-triggered phase. Kept as historical context only.

## Previous workflow problem

The previous default repeated a complete selection, Sol → Terra → Luna execution, broad validation, consolidated review, and human checkpoint for every Linear issue. That was safe but disproportionately expensive for small setup/configuration work, risk spikes, tightly related branches, and direct dependency chains. It also repeated context loading and broad checks that are more informative at a natural convergence boundary.

## HAN analysis

All 33 Hanly issues, their acceptance criteria, priorities, milestones, states, and blocker relationships were reviewed. The issues remain correctly granular and should not be merged.

- **Setup/configuration:** Repository Foundation (HAN-1, complete) is a small root capability. Similar narrow configuration work benefits from focused validation rather than a full-project ceremony of its own.
- **Risk spikes:** HAN-2 and HAN-3 are non-blocking evidence tasks. They may share one review checkpoint when jointly authorized, while each still answers its own risk question and records platform limitations.
- **Core support:** HAN-4 is a substantial shared contract gate; HAN-5 is a small support capability that can progress alongside it without becoming a blocker.
- **Parallel engine work:** HAN-6 through HAN-11 expose several useful parallel provider, data, resolver, and resource workstreams. HAN-8 → HAN-9 is an internal chain; HAN-12 and HAN-13 are later convergence/gate work that deserves integrated review.
- **Desktop foundation and parallel capabilities:** HAN-14 is a meaningful gate. HAN-15 through HAN-18 contain parallel desktop branches with different dependencies; HAN-19 is their manual-lookup convergence.
- **Hover and update branches:** HAN-20 → HAN-21 → HAN-22 → HAN-23 forms a natural internal progression after its external gates. HAN-24 → HAN-25 is a separate resource/update chain that may run alongside hover when ready.
- **Major convergence:** HAN-26 integrates the desktop branches and warrants isolated, substantial review.
- **Packaging/release:** HAN-27 through HAN-29 are coordinated parallel capabilities; HAN-30 is broad validation. HAN-31 and HAN-32 are deliberate release/human gates and must not be crossed merely to enlarge a bundle.
- **Future research:** HAN-33 remains isolated, optional, and outside V1 execution.

These are grouping characteristics, not a static bundle catalog. Actual membership must be derived at execution time from live readiness, dependencies, convergence, useful parallelism, and the human authorization boundary.

## Validation analysis

The acceptance criteria already prescribe appropriate focused evidence. The avoidable overhead was rerunning the entire project gate and full hierarchy after every small issue, not the tests themselves.

Each HAN now receives validation proportional to its change: structural checks for configuration/docs, focused provider or component tests, and evidence sufficient to answer a spike. A failing local invariant still stops affected dependent work immediately. Broader unit/integration suites, static checks, builds, regression checks, cross-component behavior, and convergence acceptance are consolidated at bundle completion when they provide stronger combined evidence.

No existing test or acceptance criterion was removed or weakened.

## New execution model

- **Bundle formation:** An execution bundle is a temporary orchestration/review grouping derived from the DAG and live Linear graph. It may contain related parallel branches or an internal dependency chain, but it does not replace issues or cross a major gate without explicit authorization.
- **Internal waves:** Root members begin from native `READY` work. A dependent member becomes `BUNDLE-READY` only when external blockers are satisfied and validated predecessors inside the authorized bundle are sufficient for dependent work. This does not alter Linear blockers or imply human approval.
- **Luna parallelism:** Terra targets approximately three to five Luna xhigh workstreams when three to five genuinely independent workstreams exist. The count remains variable; artificial splitting and idle workers are prohibited.
- **Per-HAN validation:** Every member retains its scope, acceptance criteria, focused validation, and proportional local review.
- **Bundle validation:** At convergence, broader integration/regression/build/static validation establishes that the combined changes work together.
- **Review:** Terra consolidates and validates the bundle once; Sol performs one general review of the consolidated bundle. Additional review remains available for high-risk work.
- **Human checkpoint:** All review-ready bundle members move to `In Review` together and execution stops. The human may approve all or selected members or request changes.
- **Linear lifecycle:** Intermediate issues are not marked `Done` to unlock work. `Done` remains human-controlled. Native blockers are reevaluated only after approved issues become `Done`.

## Files / Linear changes

Changed:

- `docs/execution/05-execution-plan.md` — authoritative operational bundle workflow.
- `docs/architecture/04-agent-execution-flow.md` — issue/bundle execution-unit, GPT orchestration, parallelism, and consolidated-review semantics.
- `docs/architecture/visual/Hanly Agent Execution Flow.html` — synchronized visual companion for the changed execution semantics.
- `CLAUDE.md` — concise pointer to the bundle rules in `05`.
- `docs/execution/reports/bundle-workflow-optimization-review.md` — this analysis.

Unchanged:

- All product/runtime/component/DAG semantics and issue blocker relationships.
- All issue scopes, acceptance criteria, priorities, milestones, and labels.

No Linear changes were made. Dynamic membership plus concise issue comments/checkpoints during an active run is lighter and more truthful than permanent speculative bundle labels or parent issues.

## Safety comparison

The optimized model preserves every issue acceptance criterion, real blocker, local failure gate, architecture boundary, worker-model rule, and human authority rule. It improves integration confidence by placing broad validation at natural convergence points while retaining focused early checks needed to unlock dependent work. Human `Done` approval, Git authorization, and authorization for the next bundle remain separate decisions.

The reduction is limited to duplicated context loading, duplicated Sol/Terra cycles, redundant broad checks, and unnecessary human interruptions—not to necessary testing or review.

## Remaining risks or ambiguities

- `BUNDLE-READY` is not a native Linear state. Active runs must record membership and internal evidence clearly enough to resume without treating it as human approval.
- Oversized bundles can dilute review quality; the orchestrator must prefer a smaller natural convergence boundary when the combined change is no longer reviewable.
- Parallel workers sharing files can create coordination conflicts; Terra must split only genuinely independent work and consolidate before bundle validation.
- Platform-specific spikes and release validation remain limited by actual platform availability; bundling does not manufacture missing evidence.

## Recommendation

The optimized workflow is ready for the next real execution run after human review. The next run should explicitly authorize either one issue or one dynamically derived bundle and stop at that unit's human checkpoint.
