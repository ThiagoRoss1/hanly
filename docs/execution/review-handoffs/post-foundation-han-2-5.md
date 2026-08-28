# Post-Foundation HAN-2–5 Review Handoff

## Bundle

- Member issues: HAN-2, HAN-3, HAN-4, HAN-5
- Implementation ecosystem: Codex GPT; Sol orchestration with one Terra coordination layer and delegated workers requested as Luna xhigh. Runtime worker identity was not independently exposed.
- Date: 2026-08-20

## Implemented

- HAN-2: Windows desktop threading/lifecycle evidence harness and durable findings report covering worker execution, bounded shutdown, PyQt6, pywebview, and tray-library availability.
- HAN-3: Windows PaddleOCR/PaddlePaddle packaging-feasibility harness and durable findings report, including a disposable PyInstaller build/launch experiment.
- HAN-4: immutable normalized engine contracts, lookup/resource statuses and invariants, provider protocols, base errors, and public `hanly` exports.
- HAN-5: small deterministic Korean OCR/morphology/dictionary/resolver fixtures, including a static Korean PNG ROI with purpose metadata and loading tests.

## Main expected behavior

- Engine consumers can import normalized models and provider interfaces directly from `hanly` without UI or concrete-provider dependencies.
- Contract construction rejects invalid bounding boxes, invalid OCR confidence, and inconsistent success/error/resource states while allowing UI-independent partial lookup context.
- Ordinary tests can consume the Korean normalized examples and static ROI fixture without treating them as an OCR benchmark.
- The two standalone Windows spike harnesses record actionable lifecycle and packaging constraints without becoming production desktop or packaging implementations.

## Architecture / seams touched

- Public `hanly` contract and provider-interface surface.
- `LookupResult` success, normal non-success, error, diagnostics, and optional normalized context.
- `hanly-app → hanly` package direction; no desktop/UI dependency was added to the engine.
- Non-blocking lifecycle/packaging risk evidence and small implementation-support fixtures.

## Relevant files / diff areas

- `packages/hanly/src/hanly/contracts.py`
- `packages/hanly/src/hanly/providers.py`
- `packages/hanly/src/hanly/errors.py`
- `packages/hanly/src/hanly/__init__.py`
- `tests/test_core_contracts.py`
- `tests/test_provider_interfaces.py`
- `tests/test_korean_fixtures.py`
- `tests/fixtures/`
- `spikes/desktop_threading_lifecycle.py`
- `spikes/packaging_feasibility.py`
- `docs/execution/reports/han-2-desktop-threading-lifecycle-spike.md`
- `docs/execution/reports/han-3-packaging-feasibility-spike.md`

## Implementation-side validation already run

- `.\.venv\Scripts\python.exe -m pytest` → 40 passed.
- `.\.venv\Scripts\python.exe -m ruff check packages tests` → passed.
- `.\.venv\Scripts\python.exe -m mypy packages tests` → no issues in 12 source files.
- HAN-2 Windows evidence run and HAN-3 disposable packaging experiment are recorded reproducibly in their durable reports.

## Post-Bundle Review Outcome

- Reviewer: Claude (Opus 5)
- Review ecosystem: Claude, reviewing a Codex-implemented bundle
- Date: 2026-08-20
- Status: Complete for Windows scope. macOS/Linux deferred to real macOS validation.

Gates re-run against the repository after the review: **61 passed, Ruff clean,
mypy clean across 14 source files.** This supersedes the pre-review figures
recorded above.

### Fixed now

- **HAN-3's recorded blocker did not reproduce.** Both PaddleOCR models were complete all along (4.9 MB det + 13.9 MB rec); the original `WinError 5` was environmental. Root cause of the skipped evidence was a 30 s import bound — cold `paddleocr` import on Windows exceeds it. Raised to 180 s, and PaddleOCR now constructs and loads the local Korean models **offline in ~7 s**.
- **PaddleOCR model-name pinning.** PaddleOCR 3.7.0 defaults to `PP-OCRv6_medium_det` and rejects a v5 model directory unless the model *name* is passed alongside it. Provider construction and `ResourceManager` validation must pin the name, not just the path; a library upgrade can move the default ahead of cached assets.
- **HAN-2 lifecycle evidence made real.** Two observations could never be false (an identifier captured on the main thread compared against the main thread) and the probe used `QCoreApplication`, which has no widget layer. Replaced with a real `QApplication`, a frameless always-on-top popup widget, a worker-thread result delivered to a main-thread slot via Qt signal, tray availability, and a shutdown worker that records whether it actually observed the stop request.
- **Windows display evidence added.** Per-monitor DPI awareness confirmed; a monitor sits at **x = -1920**, so negative virtual-desktop origins are real here and capture must reconcile against the virtual desktop. WebView2 runtime detection added (present, 151.0.4129.93).
- **Contract invariants corrected.** Only `SUCCESS` may carry entries (a test had enshrined the opposite); `VALID` resources cannot be marked incompatible; dictionary entries require a headword and at least one definition.
- **`py.typed` and package-data added** — the engine is intended for direct consumption and was shipping its annotations invisibly to downstream type checkers.
- **`spikes/` brought into Ruff and mypy scope**, which immediately surfaced three real type errors; all fixed.
- **Test fixture package renamed** to `hanly_fixtures`, removing a collision with the `fixtures` distribution on PyPI.
- **Provider protocol checks strengthened** — `runtime_checkable` `isinstance()` verifies method names only, so mypy-checked assignments now verify the signatures.
- **OCR seam refinement** (separately authorized): typed `ROIImage` input replacing `object`, `Quad` of four float points replacing lossy integer rectangles, reading order stated in the provider contract.
- **`ROIImage` public-boundary hardening** — a non-`PixelFormat` value now raises `TypeError("pixel_format must be a PixelFormat")` instead of leaking a `KeyError` from an internal lookup table. No coercion of strings.

**Windows `paddle`-before-`paddleocr` `WinError 127` (`torch\lib\shm.dll`) remains a real packaging constraint** — not fixed, deliberately preserved as evidence. `paddleocr` first, then `paddle`, succeeds.

### Deferred considerations

- **Quad winding / corner-order enforcement** — order is documented as provider-reported and conventionally clockwise, but not enforced. *Revisit when `WordResolver` implements point-in-quad or other geometry math that depends on consistent winding.*
- **`ROIImage` stride / padding** — `data` is assumed tightly packed. *Revisit when a real capture adapter supplies non-packed image rows.*
- **ROI origin / virtual-desktop offset** — the origin does not travel with the normalized ROI; coordinate mapping currently belongs to the capture/pipeline layer. *Revisit when `CaptureService` or desktop coordinate mapping shows the origin must travel with the ROI.* Given the -1920 monitor above, treat this as likely rather than hypothetical.
- **OCR confidence threshold / fallback policy** — confidence stays on `OCRResult`; no aggregate, no threshold policy in the contracts. *Revisit when `LookupPipeline` or OCR orchestration policy is implemented.*
- **OCR reading grouping / line metadata** — provider-level reading order only, no grouping IDs. *Revisit when `WordResolver` demonstrates that provider reading order alone is insufficient.*
- **Provider error taxonomy and normalization** — `HanlyError → ProviderError` is kept as-is; no speculative subclasses. *Revisit when the concrete `PaddleOCRProvider`, Kiwi, and KRDICT providers expose real failure modes.* Questions to answer with that evidence: is it useful to distinguish provider domains (OCR vs morphology vs dictionary), or failure causes (unavailable / resource / input / execution)? Should external exceptions always be normalized into Hanly-owned exceptions before crossing the seam? What does `LookupPipeline` actually need in order to tell recoverable provider failure, normal non-success, fallback eligibility, and fatal error apart? The standing principle: external-library exceptions should not leak through the public provider boundary when they can be meaningfully normalized.
- **Windows DPI scaling** — both monitors here run at `device_pixel_ratio` 1.0, so 125%/150% and mixed-DPI layouts are unexercised. *Revisit during later desktop/platform validation on scaled displays.*
- **Frozen PaddleOCR startup** — the harness imports dynamically, so its frozen probe cannot demonstrate anything Paddle-specific; a bounded `--collect-all paddle` experiment is still owed. *Revisit at packaging (Wave 10), or sooner if desktop work needs a frozen OCR path.*
- **pywebview window/loop coexistence with Qt** — only backend selection was probed, not two event loops in one process. *Revisit at Desktop Foundation, before the Control Center is wired.*

### Dismissed

- **Aggregate confidence on `LookupResult`** — considered and rejected. Confidence belongs to the OCR evidence; collapsing several OCR confidences into an invented score would lose information and pre-empt pipeline policy.
- **"Korean recognizer model missing / incomplete"** — no longer relevant; the models are complete and load offline. Recorded in the HAN-3 report so a future reader does not re-derive it.

## Known limitations / intentionally unvalidated areas

- HAN-2 exercised Windows only. macOS/Linux, an actual pywebview window/event loop, and real shell/tray integration were not exercised.
- Scaled displays (125%/150%) and mixed-DPI multi-monitor layouts remain unexercised; both monitors here run at ratio 1.0. This is the main open Windows display risk.
- A real pywebview window/event loop coexisting with the Qt loop in one process is still unexercised; only backend selection was probed.
- HAN-3 exercised Windows only. macOS/Linux packaging remains unexercised.
- Frozen PaddleOCR startup remains unvalidated: the harness imports dynamically, so its frozen probe cannot show anything Paddle-specific, and a bounded `--collect-all paddle` experiment is still owed.
- The `--packaged-ocr-probe` path is still not independently exercised.
- The Korean raster fixture is deterministic implementation support, not OCR-accuracy evidence.
- Deep review has now been performed (see above); the four seam-design questions remain open pending a decision.

## Suggested review targets

- Public-contract ergonomics and whether the current invariants/context are appropriate for the Wave 2 providers and `WordResolver`.
- Provider protocol input/return shapes before concrete adapters depend on them.
- The Windows lifecycle evidence boundaries before Desktop Foundation planning.
- Paddle/PaddleOCR collection, native DLL/import order, and explicit local-model packaging strategy before production packaging work.
- Fixture usefulness for the first Wave 2 provider/resolver tests without expanding it into a benchmark corpus.

## Review assignment

Human-selected. Review completed 2026-08-20 — see the Post-Bundle Review Outcome above.
