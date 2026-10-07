# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Project state

Hanly is a Korean popup-dictionary desktop app: hover over Korean text anywhere
on screen and a dictionary popup explains the word. Version 1.0.0 is Hanly V1 —
two independently installable packages (`hanly`, the
engine; `hanly-app`, the desktop), frozen builds for Windows, macOS and Linux,
an in-place updater, and CI.

Where to read:

- `docs/CODE-MAP.md` maps entry points, the lookup pipeline, provider seams and
  the KRDICT build/read/deliver paths onto real files. Read it first to find
  something.
- `docs/architecture/01`–`03` and the `DECISION-*` records are the approved
  architecture; `04` is the agent execution flow.
- `docs/execution/05-execution-plan.md` is the operational manual for V1 work.
- Linear is the live source for issue status, blockers, priorities and `READY`
  work; the repository and tests are the implemented, verifiable state.

## Execution workflow

`05-execution-plan.md` is **authoritative for Hanly V1 execution** and takes
precedence over generic skill ceremony. Do not invoke `executing-plans`,
`subagent-driven-development`, or generic JIT-planning/review/TDD chains when
they would add a second plan, decomposition layer, mandatory reviewers,
re-review loops, or duplicate checkpoints and reports — unless the human asks.

Execution has two separate phases. **Phase A** (implementation) ends at one
Review Handoff in `docs/execution/review-handoffs/` and stops. **Phase B** (deep
review) starts only on explicit human authorization, with a human-chosen
reviewer. An implementation run never turns itself into a deep review.

`04`, `05`, `docs/execution/CONTEXT.md`, `checkpoints/` and `review-handoffs/`
are V1 scaffolding and may be archived after V1; `01`–`03` are not.

## Readability and comments

- Separate distinct logical steps in a function with a blank line; keep
  tightly related statements together.
- When a function mixes independent responsibilities, prefer three to five
  clearly named private helpers over one dense block.
- Comments explain intent, invariants, library quirks and *why* — never what
  the code already says. One line where possible, up to five for genuinely
  complex behavior.
- Docstrings state a contract and purpose, not implementation details or usage
  examples. Operational instructions and history belong in `docs/`, a handoff
  or a README.

## Commands

```bash
python -m pytest                     # the full local gate
python -m ruff check packages packaging tests tools lab
python -m mypy packages packaging tests tools lab
```

`--suite portable` (no Qt, Torch or display), `--suite native` (`tests/native/`,
real desktop runtime and window server) and `--suite packaged`
(`tests/packaged/`, a frozen bundle) select by the machine a case needs;
`packaging/README.md` has the details. The venv (`.venv/`) runs Python 3.13,
but the code targets **3.10+** — no newer-only syntax or APIs.

Run the desktop as a user does: `hanly` or `python -m hanly_app`. Run it under
observation with `python -m lab` (you drive) or `python -m lab tour` (the lab
drives and scores); each writes a visual report under `artifacts/lab/runs/`. A first
launch writes the per-user `runtime.json` and provisions `krdict` from
`HANLY_KRDICT_DB` or `data/generated/krdict.sqlite3` (see `data/README.md`).
`resources/dev/` is benchmark-only configuration for `--runtime-config`.

To use Lab evidence, read the compact summary first (`summary.md` or
`campaign.md`), then check its provenance (start-time commit, clean or dirty,
observed backend), the baseline (`python -m lab baseline`) and the
comparison's compatibility before trusting any explanation. Open
`report.json` or `events.jsonl` only when the summary is not enough. Reports are
rebuilt under the current scoring rules, so a rebuilt verdict can differ from
the recorded one; the recording itself never changes. `lab/README.md` has the
details.

## Runtime rules that are easy to break

- **One entry point:** `hanly_app.cli:main`. The `hanly` script,
  `python -m hanly_app` and the frozen executable all call it, and
  `tests/test_packaging.py` fails if a second one appears. It calls
  `multiprocessing.freeze_support()` first because spawned children re-enter a
  frozen build through it.
- **Three processes:** the persistent shell (Qt Widgets, tray, hotkeys,
  capture, hover, popup, settings, updates, session log, the one event loop)
  imports neither Qt WebEngine nor the OCR runtime. `control_center/process.py`
  spawns the window and `lookup/process.py` spawns the providers, both with
  `multiprocessing.get_context("spawn")`; `lookup/transport.py` is the only
  channel. `lookup/preload.py` runs inside the lookup child, never in the shell.
- **Readiness is not residency:** `RuntimeStatus` says whether a lookup can
  happen; `LookupEngine.state` says whether providers are loaded;
  `config.LookupPreload` decides which a launch pays for.
- **Privacy:** tracing carries no recognized text and no pixels. Private
  evidence reaches disk only through the lab's explicit Export, or a
  `lab tour` over lab-authored pages it has verified it owns, under the
  gitignored `artifacts/lab/runs/`.
- Developer-only instrumentation lives under `lab/` (including its
  tests and the `dev-hud`); nothing dev-only belongs in `packages/`.

## Architecture boundaries

Read `docs/architecture/01`–`04` before changing anything structural.

- `hanly-app → hanly`, never the reverse. `hanly` is a client-independent
  engine meant for independent distribution; `hanly-app` owns everything
  desktop. Keep future clients and transports out of the engine and out of V1.
- External libraries sit behind `OCRProvider`, `MorphologyProvider` and
  `DictionaryProvider`; library objects are normalized (`OCRResult`,
  `TokenAnalysis`, `DictionaryEntry`) before crossing a seam. `LookupPipeline`
  knows only the interfaces.
- `LookupController` (app: request IDs, latest-wins, stale handling) may depend
  on `LookupPipeline` (engine), never the reverse. `ResourceManager` (engine)
  understands local resources; `UpdateService` (app) obtains remote ones.
  Providers never depend on `ResourceManager`. `MouseObserver` observes,
  `HoverController` decides, and OCR never detects hover.
- Hover → debounce → small ROI (never continuous full-screen OCR) → worker →
  lookup → **final request-currency check** → popup. Cancellation is resource
  control; the currency check is the correctness gate.
- `LookupResult` models success, ordinary non-success and processing errors;
  non-success is not an exception.

## OCR backends

Two backends behind `OCRProvider`: Apple Vision (preferred on macOS) and
EasyOCR (cross-platform and the fallback). PaddleOCR was removed at the human's
direction and must not return. `config.OCRBackend` is `auto` (default), `vision`
or `easyocr`; the Control Center offers it as the "Text recognizer" setting
(approved 2026-09-28). `auto` is resolved in the shell by
`HanlyRuntime.resolved_ocr_backend()` and the lookup child receives a concrete
choice, because probing a framework from a spawned process hangs. Do not add a
third backend, a plugin system, or dictionary-backed spelling correction.
The decision, evidence and revisit condition are in
`docs/architecture/DECISION-2026-09-22-ocr-backend.md`; read
`docs/execution/reports/ocr-latency-and-roadmap.md` before changing OCR
behavior. HanlyOCR is a future, non-blocking research track.

## Architecture docs ↔ visual diagrams

`docs/architecture/*.md` is authoritative; `docs/architecture/visual/*.html` are
synchronized companions. Invariant lists map **1:1 and in order** — `RF-INV-*`
(01), `CA-INV-*` (02), `DAG-INV-*` (03), `AEF-INV-*` (04) — and
`tests/test_architecture_invariants.py` enforces it. Never renumber one side.

The HTML files are ~500 KB bundles with the page in an escaped JS string:

```python
s = open(path, encoding="utf-8").read()
t = s.replace('\\n', '\n').replace('\\"', '"')   # unescape
t = t[t.find('<div', t.find('@font-face')):]      # skip fonts/thumbnail preamble
```

Diagram meaning lives in CSS: solid `#2c3138` edges are blockers, thin
`#b9bec4` ordinary dependencies, dashed borders non-blocking or future work, and
`grid-column` spans decide where an edge terminates. Edit by string-replacing
inside the escaped bundle, asserting the target occurs exactly once, and
diffing against a backup.

## Governance

Name a new branch or worktree for its actual workstream, not for the agent:
for example `lab/app-health`, `fix/windows-updater` or `v2/pixel-interface`.
Use a short descriptive slug and keep related phases on the same branch unless
the human requests isolation. A worktree uses that same workstream name; do not
create one per step. Do not add an automatic `codex/` or `claude/` prefix.

Agents may propose architecture changes and draft ADRs, but approved
architecture changes need human approval before becoming authoritative. Commit,
push and merge are human actions unless explicitly authorized; editing,
testing and preparing changes need no such instruction.
`docs/architecture/REVIEW-2026-08-18.md` grades findings A/B/C; category C binds
only where marked `[ACCEPTED]`.
