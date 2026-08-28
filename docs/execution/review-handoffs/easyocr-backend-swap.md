# EasyOCR Backend Swap Review Handoff

## Bundle

- Member issues: none — human-directed V1 OCR backend evaluation
- Implementation ecosystem: Claude Code (Opus 5), Windows 10 `10.0.19045`,
  Python 3.13.11, `.venv`, EasyOCR 1.7.2 / Torch 2.13.0+cpu
- Date: 2026-08-24

## Implemented

- `EasyOCRProvider` / `EasyOCRConfig` behind the existing engine `OCRProvider`
  seam, Korean-only and CPU-only, with EasyOCR's triples and NumPy arrays kept
  inside the adapter.
- `ocr_backend` selection (`paddle` | `easyocr`, default `paddle`) in the
  runtime configuration, consumed by `HanlyRuntime`.
- Backend-aware resource manifest: an EasyOCR runtime declares only `krdict`.
- Backend-aware pre-Qt native import via `preload_ocr_runtime(module_name=…)`.
- OCR provider warmup during worker construction, before the executor reports
  ready.
- `resources/dev/runtime-easyocr.json` for the evaluation run.

## Main expected behavior

Hover and manual lookup run capture → `EasyOCRProvider` → `WordResolver` →
Hangul gate → Kiwi → KRDICT → SUCCESS-only popup. No PaddleOCR object is
constructed, prewarmed, or executed, and the Paddle recognition-first hover
fast path does not run: `HanlyRuntime` supplies no
`hover_text_recognition_provider_factory` for this backend, so `LookupWorker`
takes its ordinary full-provider path for hover requests too.

## Architecture / seams touched

- `OCRProvider` (CA-INV-05, CA-INV-09) — a second adapter, contract unchanged.
- `LookupPipeline` — untouched; it still sees only the provider protocols.
- Application composition — `HanlyRuntime` chooses provider factories; provider
  construction stays deferred to the `JobExecutor` thread.
- `ResourceManager` — still the only local-resource authority; EasyOCR simply
  declares no managed model resource (see limitations).

## Relevant files / diff areas

- `packages/hanly/src/hanly/easyocr_provider.py` (new)
- `packages/hanly-app/src/hanly_app/runtime.py`
- `packages/hanly-app/src/hanly_app/composition.py` (OCR prewarm hook)
- `packages/hanly-app/src/hanly_app/bootstrap.py`,
  `packages/hanly-app/src/hanly_app/application.py`
- `benchmarks/dev/{cli,live_runner}.py` (`require_paddle_config`)
- `resources/dev/runtime-easyocr.json`, `pyproject.toml`
- `tests/test_easyocr_provider.py`, `tests/test_easyocr_runtime.py`,
  `tests/test_runtime.py`

## Implementation-side validation already run

- `python -m pytest` → 515 passed (45 new).
- `python -m ruff check packages packaging tests tools benchmarks` → clean.
- `python -m mypy packages packaging tests tools benchmarks` → clean, 120 files.
- Real runtime on the retained 192x48 Korean fixture, target (100, 24):
  `SUCCESS` / `읽습니다.` / `읽다`, 20/20 warm samples, warm total pipeline
  p50 80.1 ms (Paddle baseline 185.4 ms).
- Same fixture padded to the 200x100 capture default: `SUCCESS` / `읽다`,
  warm p50 119.0 ms (Paddle baseline 162.1 ms).
- Blank ROI → `EMPTY`, not an error.
- Initialization: runtime validation 4.4 ms, worker construction 8.1 s
  (`import easyocr` ~4.5 s, `Reader(['ko'])` ~2.0 s, Kiwi prewarm ~2.5 s),
  EasyOCR prewarm 30-44 ms, first lookup 114 ms.
- Process: RSS ~1.0 GB after ready; 16.5 CPU-seconds across 42 lookups with
  `cpu_threads=4`.

## Known limitations / intentionally unvalidated areas

- **Recognition quality regressed on the fixture's other word.** EasyOCR reads
  `책을` as `책울` (192x48) and `책올` (200x100). The measured target word is
  unaffected, and one image is not an accuracy result either way.
- **Confidence is much lower than Paddle's** — 0.547 at 192x48, 0.285 at
  200x100. No `confidence_threshold` is configured, so nothing is rejected
  today; any threshold tuned against Paddle would reject EasyOCR outright.
- **`cpu_threads` is a process-global `torch.set_num_threads` call.** The value
  4 in the dev config is an evaluation choice from ~12 samples on one 8-core
  CPU, not a tuned default. Measured trade-off at 200x100: 1 thread 307 ms,
  2 threads 179 ms, 4 threads 118 ms, 8 threads 105 ms, with total CPU rising
  from 8.9 s to 16.1 s across the same work.
- **EasyOCR models are not managed resources.** They resolve through EasyOCR's
  own storage directory (`~/.EasyOCR/model` by default) and, with
  `download_enabled` at its default, EasyOCR may fetch ~99 MB on a machine that
  lacks them. `ResourceManager`, `UpdateService`, and `first_run` are
  unchanged and still provision the Paddle manifest for a default first run.
- **Packaging is unchanged.** `packaging/hanly-desktop.spec` has no EasyOCR or
  Torch hooks; a frozen build of this backend has not been attempted.
- **Not exercised:** the live desktop loop (hover dwell, popup, tray, Control
  Center) under EasyOCR, multi-line and tilted ROIs, non-Korean screens beyond
  a blank ROI, and any platform other than this one.
- The 47.5 s worker construction seen on the very first cold process was not
  reproducible (8.1 s on repeat) and is attributed to first-load I/O.

## Suggested review targets

- `_in_reading_order`: the median-height line bucket is a deliberate
  simplification and can mis-split two regions straddling a bucket boundary.
- `_detection_parts` confidence clamping — whether silently clamping is the
  right boundary behavior, versus rejecting out-of-range scores.
- Dropping blank recognitions changes `region_count` telemetry relative to the
  Paddle adapter.
- `_prewarm_provider(ocr_provider, "ocr", …)` in `composition.py` now runs for
  every backend; `PaddleOCRProvider` has no `prewarm`, so it is a no-op there.
- Whether `read_ocr_backend` running before `load_runtime` in `run_desktop`
  leaves any startup-error path reading the configuration twice.

## Review assignment

Human-selected after implementation. Not started.
