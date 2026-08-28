# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Hanly is a Korean OCR popup-dictionary desktop app (hover over Korean text anywhere on screen → dictionary popup). The repository contains the minimal Wave 0 Python foundation: root tooling configuration, independently installable `hanly` and `hanly-app` packages, baseline tests, and CI.

`docs/CODE-MAP.md` maps entry points, the lookup pipeline, the provider
seams, and the KRDICT build/read/deliver paths onto real files; read it
first when you need to find something. Architecture V1 lives in
`docs/architecture/`, and `docs/execution/05-execution-plan.md` is the
operational execution manual; read both before executing Hanly V1 work. Linear is the live operational source for issue status, blockers, priorities, milestones / waves, and `READY` work, while the repository and tests remain the implemented and verifiable state. Execution may use one issue or a dynamically derived, human-authorized bundle as defined in `05`; Linear issues and acceptance criteria remain granular.

## Execution workflow precedence

`docs/execution/05-execution-plan.md` is **authoritative for Hanly V1 execution** and takes precedence over generic plan-execution skill ceremony. Skills may assist execution; they must not redefine its orchestration or review lifecycle.

Do not invoke `executing-plans`, `subagent-driven-development`, or generic JIT-planning/review/TDD skill chains for Hanly work when they would add a second execution plan on top of the bundle plan, another decomposition layer, mandatory per-task reviewers, mandatory re-review loops, duplicate progress reports, duplicate checkpoints, or duplicate validation. Invoke them only when the human explicitly asks, or when the specific work genuinely needs what they provide.

Execution runs in two separate phases. **Phase A (implementation)** ends at a Review Handoff in `docs/execution/review-handoffs/` and stops; implementation-side checks exist to enable safe forward progress, not to prove correctness exhaustively. **Phase B (deep review)** is a separate run that begins only on explicit human authorization, with the human choosing the reviewer and ecosystem. Never let an implementation run turn itself into a deep review session. A reviewer may apply cheap defensive hardening at a public boundary; every other finding is recorded in the handoff as Fixed now, Deferred (with a revisit trigger), or Dismissed.

`04`, `05`, `docs/execution/CONTEXT.md`, `checkpoints/`, and `review-handoffs/` are V1 execution scaffolding and may be archived or removed after V1. `01`-`03` are product architecture and are not.

## Readability and comments

Separate distinct logical steps inside a function with a blank line, and keep tightly related statements together — blank lines mark phases, they are not inserted between every statement.

When one function mixes independent responsibilities (normalization, validation, configuration merging, object construction), prefer a few clearly named private helpers over one dense block. Aim for three to five meaningful helpers, not one-line fragments.

Comments explain non-obvious intent, invariants, external-library quirks, or *why* — never what the code already says. Keep them to one line where possible, two or three when needed, and up to five only for genuinely complex behavior.

Docstrings state a class's or function's contract and purpose. They do not restate implementation details already visible in the body, and they are not the place for usage examples that belong in a README.

Longer operational instructions, historical context, and debugging rationale belong in `docs/`, a review handoff, or a `README` — not in source comments.

## Commands

The Wave 0 quality gates are:

```bash
python -m pytest
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```

Run the desktop the way a user does:

```bash
hanly            # or: python -m hanly_app
```

A first launch writes `%LOCALAPPDATA%/Hanly/runtime.json` and provisions
`krdict`. Until the GitHub release exists, that comes from an already-built
local database: `HANLY_KRDICT_DB`, or `data/generated/krdict.sqlite3` in a
source checkout. Build one with the commands in `data/README.md`.
`resources/dev/` is benchmark-only configuration; `--runtime-config` points
the desktop at one.

**There is one entry point.** `hanly_app.cli:main` is it. The installed `hanly`
script, `python -m hanly_app`, and the packaged executable all call that one
function, and `tests/test_packaging.py` fails if a
second way to start the desktop appears. `application.py` owns `run_desktop`
and the composition; it is not an entry point. `ocr_preload` imports EasyOCR
before Qt; `first_run` provisions resources on a launch with no configuration.

Developer-only benchmark instrumentation lives under `benchmarks/dev/`,
including its tests (`benchmarks/dev/tests/`, collected by pytest) and the
unwired hover HUD widgets (`benchmarks/dev/hud/`). Nothing dev-only
belongs in `packages/`.

The venv (`.venv/`, gitignored) runs Python 3.13 and already has `easyocr`, `torch`, `kiwipiepy`, `pillow`, `numpy`. The architecture targets Python **3.10+**, so don't rely on 3.13-only syntax.

## Architecture

Read `docs/architecture/01`–`04` before changing anything structural. The big picture:

**Two packages, one direction.** `hanly-app → hanly`; `hanly` must *never* import `hanly-app`. `hanly` is the reusable, client-independent engine (OCR orchestration, Korean linguistics, dictionary lookup, resource validation, contracts), intended for direct consumption and independent distribution as a Python package, including through PyPI. Hanly Desktop V1 is its first client; `hanly-app` owns everything desktop: OS integration, capture, hotkeys, tray, PyQt6 popup, pywebview Control Center, worker execution, updates. Keep future client and transport concerns outside the engine, do not turn possible consumers into V1 scope or a generic plugin framework, and treat Python as the initial environment rather than a permanent implementation constraint.

**External libraries live behind provider seams.** `OCRProvider`, `MorphologyProvider`, `DictionaryProvider` are engine interfaces; `EasyOCRProvider`, `KiwiProvider`, `KRDICTProvider` are the V1 adapters. Library-specific objects must be normalized (`OCRResult`, `TokenAnalysis`, `DictionaryEntry`) before crossing a seam. `LookupPipeline` knows only the interfaces — never EasyOCR, Kiwi, SQLite, or `ResourceManager`.

**Four boundaries that are easy to blur:**

- `LookupController` (app: request IDs, stale handling, bounded/latest-wins submission) vs `LookupPipeline` (engine: ROI → `LookupResult`). The controller may depend on the pipeline, never the reverse.
- `ResourceManager` (engine: *understands* local resources) vs `UpdateService`/`ResourceFetcher` (app: *obtains* remote resources, hands them over for validation). The engine must work without GitHub Releases.
- Providers do **not** depend on `ResourceManager`. Application/composition wiring asks `ResourceManager` for validated paths/config and passes them explicitly into provider constructors.
- `MouseObserver` observes; `HoverController` decides. Neither performs OCR — OCR never detects hover.

**Runtime shape.** Hover → debounce → cursor-validity check → **small ROI** capture (never continuous full-screen OCR) → worker/off-UI-thread → OCR → `WordResolver` → morphology → dictionary → `LookupResult` → **final request-currency check** → popup. Execution is bounded/latest-wins; cancellation is resource control, not the correctness gate — the currency check before presentation is mandatory. Hover delay is configurable, tuned empirically, initially ~80–250 ms (an experimental range, not an SLA).

`LookupResult` must model success, **normal non-success** (empty / not-found / unusable / low confidence), and processing errors — non-success is not an exception.

## OCR backend

**EasyOCR is the only OCR backend (2026-08-26).** PaddleOCR was removed at the
human's direction: the adapter, its recognition-first hover fast path, the
`ocr_backend` selector, and the two managed model resources are gone. A first
launch provisions only `krdict`, and the desktop constructs `EasyOCRProvider`.
Do not reintroduce a backend-selection seam or restore Paddle from an older
revision; `OCRProvider` remains the abstraction if a second adapter is ever
wanted again.

Measurements, the diagnosed defects behind the swap, and the deferred items are
in `docs/execution/reports/ocr-latency-and-roadmap.md`. Read it before changing
OCR behavior — several tuning levers there were measured and rejected.

- **HanlyOCR** (a custom/fine-tuned model) is a future, non-blocking research track. It never blocks the V1 critical path, and its benchmark corpus is distinct from the small `Korean Test Fixtures`.

## Architecture docs ↔ visual diagrams

`docs/architecture/*.md` is the **authoritative source of truth**. The four files in `docs/architecture/visual/*.html` are synchronized visual companions.

Each invariant list must map **1:1 and in the same order** between a Markdown file and its HTML companion — `RF-INV-*` (01), `CA-INV-*` (02), `DAG-INV-*` (03), `AEF-INV-*` (04). These IDs are cited across documents; renumbering one side silently breaks every cross-reference. This has already regressed once.

The HTML files are ~500 KB bundled JS pages, not readable markup — the page lives in an escaped JS string. To inspect one:

```python
s = open(path, encoding="utf-8").read()
t = s.replace('\\n', '\n').replace('\\"', '"')   # unescape
t = t[t.find('<div', t.find('@font-face')):]      # skip fonts/thumbnail preamble
```

Diagram semantics carry meaning in the CSS, so check styling, not just text: solid `#2c3138` lines are critical-path/blocker edges, thin `#b9bec4` are ordinary dependencies, dashed borders mark non-blocking or future work, and grid `grid-column` spans determine which nodes an edge actually terminates on. A node placed inside another node's border reads as containment; an edge stub that ends one wave early silently invents a blocker.

To edit a diagram, string-replace inside the escaped bundle (match `\"` and `\n` literally), assert the target string occurs exactly once, and diff against a backup afterward to confirm the change stayed local.

## Governance

Per `04-agent-execution-flow.md`: agents may propose architecture changes and draft ADRs or doc patches, but approved architecture changes require human approval before becoming authoritative — don't silently redefine an approved decision. Separately, **final commit and merge authority is human by default**; commit only when explicitly asked. Editing files, running tests, reviewing, and preparing changes need no such instruction.

`docs/architecture/REVIEW-2026-08-18.md` grades its findings A (fidelity defect), B (later approved decision — the *visual* is the stale side), and C (recommendation). Category C is binding only where marked `[ACCEPTED]`; everything else there is `[PROPOSED]` and not approved architecture.
