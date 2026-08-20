# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Hanly is a Korean OCR popup-dictionary desktop app (hover over Korean text anywhere on screen → dictionary popup). The repository contains the minimal Wave 0 Python foundation: root tooling configuration, independently installable `hanly` and `hanly-app` packages, baseline tests, and CI.

Architecture V1 lives in `docs/architecture/`, and `docs/execution/05-execution-plan.md` is the operational execution manual; read both before executing Hanly V1 work. Linear is the live operational source for issue status, blockers, priorities, milestones / waves, and `READY` work, while the repository and tests remain the implemented and verifiable state. Execution may use one issue or a dynamically derived, human-authorized bundle as defined in `05`; Linear issues and acceptance criteria remain granular.

## Commands

The Wave 0 quality gates are:

```bash
python -m pytest
python -m ruff check packages tests
python -m mypy packages tests
```

The root `test_*.py` files are **exploratory spikes, not pytest tests** — they are `__main__` scripts with Portuguese comments and no assertions. Don't wire them into a future `tests/` suite; the DAG's `Korean Test Fixtures` capability covers real test inputs.

The venv (`.venv/`, gitignored) runs Python 3.13 and already has `paddleocr`, `paddlepaddle`, `kiwipiepy`, `pillow`, `numpy`. The architecture targets Python **3.10+**, so don't rely on 3.13-only syntax.

## Architecture

Read `docs/architecture/01`–`04` before changing anything structural. The big picture:

**Two packages, one direction.** `hanly-app → hanly`; `hanly` must *never* import `hanly-app`. `hanly` is the reusable, client-independent engine (OCR orchestration, Korean linguistics, dictionary lookup, resource validation, contracts), intended for direct consumption and independent distribution as a Python package, including through PyPI. Hanly Desktop V1 is its first client; `hanly-app` owns everything desktop: OS integration, capture, hotkeys, tray, PyQt6 popup, pywebview Control Center, worker execution, updates. Keep future client and transport concerns outside the engine, do not turn possible consumers into V1 scope or a generic plugin framework, and treat Python as the initial environment rather than a permanent implementation constraint.

**External libraries live behind provider seams.** `OCRProvider`, `MorphologyProvider`, `DictionaryProvider` are engine interfaces; `PaddleOCRProvider`, `KiwiProvider`, `KRDICTProvider` are the V1 adapters. Library-specific objects must be normalized (`OCRResult`, `TokenAnalysis`, `DictionaryEntry`) before crossing a seam. `LookupPipeline` knows only the interfaces — never PaddleOCR, Kiwi, SQLite, or `ResourceManager`.

**Four boundaries that are easy to blur:**

- `LookupController` (app: request IDs, stale handling, bounded/latest-wins submission) vs `LookupPipeline` (engine: ROI → `LookupResult`). The controller may depend on the pipeline, never the reverse.
- `ResourceManager` (engine: *understands* local resources) vs `UpdateService`/`ResourceFetcher` (app: *obtains* remote resources, hands them over for validation). The engine must work without GitHub Releases.
- Providers do **not** depend on `ResourceManager`. Application/composition wiring asks `ResourceManager` for validated paths/config and passes them explicitly into provider constructors.
- `MouseObserver` observes; `HoverController` decides. Neither performs OCR — OCR never detects hover.

**Runtime shape.** Hover → debounce → cursor-validity check → **small ROI** capture (never continuous full-screen OCR) → worker/off-UI-thread → OCR → `WordResolver` → morphology → dictionary → `LookupResult` → **final request-currency check** → popup. Execution is bounded/latest-wins; cancellation is resource control, not the correctness gate — the currency check before presentation is mandatory. Hover delay is configurable, tuned empirically, initially ~80–250 ms (an experimental range, not an SLA).

`LookupResult` must model success, **normal non-success** (empty / not-found / unusable / low confidence), and processing errors — non-success is not an exception.

## Superseded decisions

- **EasyOCR is not part of V1.** `PaddleOCRProvider` is the only V1 OCR implementation; `OCRProvider` stays abstract so future adapters remain possible. `test_ocr_comparison.py` still benchmarks EasyOCR — it is a historical spike from before that decision, not current architecture. Don't cite it as evidence and don't "sync" the docs to it.
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
