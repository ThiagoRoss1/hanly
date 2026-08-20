# Hanly Worker Context

One-page constraint sheet for ordinary implementation work. It replaces reading
`01`–`04` in full for work that does not change a seam.

> **V1 execution scaffolding.** This file exists to build V1 efficiently and may
> be archived or removed once it is no longer operationally useful. It is not
> product architecture.

**This file is a derived index, not a source of truth.** `docs/architecture/01`–`04`
own every rule below. If this sheet and an architecture document disagree, the
architecture document wins and this sheet is defective — report it.

## Read the full document when

- the issue changes a module seam, provider interface, or package dependency;
- the issue is Gate tier (see `05-execution-plan.md`);
- an invariant below is unclear, contested, or appears to block the work;
- you are proposing an architecture change.

Otherwise the constraints below are sufficient.

## The three rules that break the project silently

1. `hanly-app → hanly`. `hanly` must **never** import `hanly-app`.
2. Library objects (PaddleOCR, Kiwi, SQLite) never cross a provider seam. Normalize
   to `ROIImage` in and `OCRResult` / `TokenAnalysis` / `DictionaryEntry` out first.
   OCR geometry is a `Quad` of four float points; `BoundingBox` is derived from it.
3. Heavy processing never runs on the UI thread.

## Runtime invariants (`01-runtime-flow.md`)

- **RF-INV-01** OCR does not detect hover; `MouseObserver` / `HoverController` own hover.
- **RF-INV-02** Capture happens before OCR.
- **RF-INV-03** Morphology and dictionary lookup happen before popup presentation.
- **RF-INV-04** The popup receives an already processed, UI-independent `LookupResult`.
- **RF-INV-05** PaddleOCR, Kiwi, KRDICT are adapters behind provider interfaces, never direct `LookupPipeline` dependencies.
- **RF-INV-06** Heavy processing does not run on the UI thread.
- **RF-INV-07** Superseded request results may be discarded after cursor movement.
- **RF-INV-08** Hanly does not visually modify the target app except via popup and region-selection overlays.
- **RF-INV-09** Full-monitor mode is not continuous full-screen OCR; hover prefers a cursor ROI.
- **RF-INV-10** `PaddleOCRProvider` is the V1 implementation; `LookupPipeline` couples only to `OCRProvider`.
- **RF-INV-11** Desktop lookup is bounded / latest-wins; final request-currency validation is mandatory.
- **RF-INV-12** `LookupResult` models success, normal non-success, and error without exceptions for non-success.

## Component invariants (`02-component-architecture.md`)

- **CA-INV-01** `hanly-app` may depend on `hanly`.
- **CA-INV-02** `hanly` must never depend on `hanly-app`.
- **CA-INV-03** The engine contains no UI or desktop-lifecycle logic.
- **CA-INV-04** UI modules never depend directly on PaddleOCR, Kiwi, KRDICT, or SQLite.
- **CA-INV-05** `LookupPipeline` depends on interfaces and normalized contracts only.
- **CA-INV-06** Heavy processing runs through `JobExecutor` / a worker.
- **CA-INV-07** `ResourceManager` owns local resource state, not remote update UX.
- **CA-INV-08** `UpdateService` may depend on remote systems; the engine works without GitHub Releases.
- **CA-INV-09** External-library objects do not cross provider seams.
- **CA-INV-10** `hanly` stays reusable without speculative client modules now.
- **CA-INV-11** `MouseObserver` observes; `HoverController` decides; neither performs OCR.
- **CA-INV-12** `PopupController` consumes a completed `LookupResult`.
- **CA-INV-13** Composition wiring injects validated resource paths into providers; providers and `LookupPipeline` never depend on `ResourceManager`.
- **CA-INV-14** Desktop lookup is bounded / latest-wins with final currency validation.
- **CA-INV-15** `LookupResult` models success, normal non-success, and error outcomes.

## DAG invariants that constrain execution (`03-implementation-dag.md`)

- **DAG-INV-02** Engine functionality is validated before desktop integration.
- **DAG-INV-04/05** Manual Hotkey Lookup precedes automatic hover and stays a V1 feature.
- **DAG-INV-06** Basic Control Center exists before final hover integration.
- **DAG-INV-08** `UpdateService` / `ResourceFetcher` never depends on UI.
- **DAG-INV-11** Nodes are capabilities, not files or exhaustive task lists.
- **DAG-INV-16** Korean fixtures are small deterministic test inputs, not the HanlyOCR benchmark.
- **DAG-INV-17** The lifecycle and packaging spikes are non-blocking risk discovery.

The remaining DAG invariants describe dependency structure; Linear carries that
structure operationally, so consult `03` directly when readiness is in question.

## Authority

Agents may edit, implement, test, check, and propose. Commit, push, merge, and
approved architecture changes are human actions unless explicitly delegated.

Implementation-side checks exist to enable safe forward progress, not to prove
correctness exhaustively. Deep review is a separate, human-triggered phase; an
implementation run ends at the Review Handoff. See `05-execution-plan.md`.

A post-bundle reviewer may apply cheap defensive hardening at a public boundary.
Other findings are recorded as Fixed now, Deferred (with a revisit trigger), or
Dismissed — never silently dropped.

## Commands

```bash
python -m pytest
python -m ruff check packages tests
python -m mypy packages tests
```
