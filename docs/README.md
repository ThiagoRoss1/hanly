# Hanly documentation

Start with what you need to do. Everything not listed as current is kept as
provenance: dated, and labelled **Historical** at the top where it could be
mistaken for a live instruction.

## Current

| Document | Use it for |
|---|---|
| [`CODE-MAP.md`](CODE-MAP.md) | Where things are: entry points, the lookup pipeline, provider seams, the dictionary, the updater, and a file index |
| [`architecture/01`–`03`](architecture/) | The approved architecture: runtime flow, components, implementation DAG. Authoritative over everything else here |
| [`architecture/DECISION-*`](architecture/) | Approved decisions that amend `01`–`03`; the latest OCR decision is `DECISION-2026-09-22-ocr-backend.md` |
| [`architecture/visual/`](architecture/visual/) | Diagram companions to `01`–`04`, kept 1:1 with their invariant lists |
| [`execution/first-release-plan.md`](execution/first-release-plan.md) | The release operator's runbook |
| Root, `packaging/`, `tools/`, `data/`, `benchmarks/dev/` READMEs | Installing, building, releasing, the dictionary, and measurement |

## V1 execution scaffolding

Kept while V1 is being finished; may be archived afterwards.

| Document | Use it for |
|---|---|
| [`architecture/04-agent-execution-flow.md`](architecture/04-agent-execution-flow.md) | Agent roles, review phases, human authority |
| [`execution/05-execution-plan.md`](execution/05-execution-plan.md) | How a bundle is executed, handed off and reviewed |
| [`execution/CONTEXT.md`](execution/CONTEXT.md) | One-page constraint sheet derived from `01`–`04`; a test keeps its invariant lists in sync |
| [`execution/review-handoffs/`](execution/review-handoffs/) | One handoff per implementation run, with its later review outcome |
| [`execution/checkpoints/`](execution/checkpoints/) | Pause/resume ledgers |
| [`execution/plans/`](execution/plans/) and the plan files at the root of `execution/` | Human-authorized plans and briefs; executed ones are history |
| [`execution/reports/`](execution/reports/) | Durable evidence: investigations, measurements, audits |

## History

`architecture/REVIEW-2026-08-18.md` still grades architecture findings (see its
note). Older decisions, plans, reports and handoffs record how the product got
here; read them for *why*, and the current documents above for *what is*.
