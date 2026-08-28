# HAN-35 Benchmark Results and Decisions

Date: 2026-08-23  
Revision under test: `24ed285bd8cc33390875917d602a3a8526e77128` plus
the uncommitted HAN-35 harness and CLI workflow  
Environment: Windows 10 `10.0.19045`, Python 3.13.11, 8 logical CPUs,
17.11 GB RAM, CPU-only PaddlePaddle

## Measurement boundary

These are local development-runtime results on one machine and one retained
Korean correctness fixture. They are not OCR-accuracy corpus results, low-end
hardware results, frozen-package results, cross-platform runtime results, or an
SLA. Raw evidence is gitignored under `artifacts/benchmarks/`; every run carries its
own metadata and must not be merged across configurations.

## Corrected resident-provider baseline

Run: `a3d8b6cc-e815-4b3a-ba8e-7744318df8a7`  
Scenario: 192x48 fixture, `enable_mkldnn=false`, one cold inference, two
warm-ups, 30 warm samples  
Correctness: 33/33 expected `SUCCESS` / `읽습니다.` / `읽다`

| Stage | Warm p50 | Warm p95 | Min | Max |
| --- | ---: | ---: | ---: | ---: |
| OCR | 184.58 ms | 238.08 ms | 175.28 ms | 251.10 ms |
| Token selection | 0.04 ms | 0.06 ms | 0.04 ms | 0.09 ms |
| Morphology | 0.17 ms | 0.25 ms | 0.16 ms | 0.25 ms |
| Dictionary | 0.17 ms | 0.27 ms | 0.14 ms | 0.29 ms |
| Total pipeline | 185.39 ms | 238.84 ms | 176.12 ms | 251.86 ms |

The provider set was constructed once. Cold construction/first use remains
separate: runtime validation 31.28 ms, Paddle provider construction 8.815 s,
first OCR 277.26 ms, first Kiwi analysis 3.303 s, first dictionary lookup
2.75 ms, and first total pipeline 3.584 s. `KiwiProvider()` itself is lazy, so
reporting only constructor time would incorrectly hide its first-use cost.

### Invalidated instrumentation run

Run `a9a20637-bdbd-434d-b67d-abf7a8eae6f9` forced an OS `fsync` after every
stage from inside the total timer, producing a false 4.425 s warm outlier.
That run is retained but excluded from conclusions. The corrected ledger still
flushes each JSONL record immediately and disables per-stage `fsync`; the choice
is recorded in metadata. This was a harness fix, not a Hanly optimization.

## ROI-size sensitivity

All scenarios retained the transformed target and produced the same expected
OCR text, selected span, lemma, dictionary entry, and success status. Ten warm
samples per variant are directional only.

| ROI | Run | Warm p50 | Warm p95 | Correct warm samples |
| --- | --- | ---: | ---: | ---: |
| 160x48 cropped | `d75b7fb1-76fc-44fd-949a-d5d6a14d540e` | 177.54 ms | 229.71 ms | 10/10 |
| 192x48 source | corrected baseline above | 185.39 ms | 238.84 ms | 30/30 |
| 200x100 padded | `6b150a6a-a1af-481e-ad65-5aa6102eb8e8` | 162.06 ms | 179.57 ms | 10/10 |
| 300x150 padded | `dc3a85c3-a730-43f8-920f-27be259c4dc7` | 229.90 ms | 336.02 ms | 10/10 |

Decision: retain the existing practical 200x100 capture default. The one image
does not justify a smaller accuracy-risking ROI or a new dynamic-sizing
algorithm. Add a representative corpus before treating ROI size as an OCR
accuracy conclusion.

## CPU/runtime knobs

| Variant | Run | Result |
| --- | --- | --- |
| MKLDNN false, unconstrained | corrected baseline | 30/30 correct; 185.39 ms p50, 238.84 ms p95 |
| MKLDNN true | `843ce577-6a66-4259-810f-ba8ac39aa0fc` | 13/13 `ERROR`: Paddle oneDNN `ConvertPirAttribute2RuntimeAttribute` is unimplemented on this stack |
| OMP/MKL/OpenBLAS threads = 1 | `1a91f1df-89aa-479e-a370-f0e93066ccb8` | 10/10 correct; 170.55 ms p50, 274.61 ms p95 |
| OMP/MKL/OpenBLAS threads = 4 | `b255d5f5-e6b5-424d-9597-bd9fb9e0cb94` | 10/10 correct; 165.39 ms p50, 187.10 ms p95; Paddle emitted a caution about non-optimized/data-parallel and OpenBLAS behavior |

Decision: keep the production runtime's explicit `enable_mkldnn=false`. Do not
hard-code a thread limit from ten samples on one CPU, especially when the
runtime itself warned about the four-thread configuration. A larger repeated
matrix on target hardware is the trigger.

## Capture and hover

### Real desktop capture

`artifacts/benchmarks/desktop-capture.json` measured the current cursor near a
display edge, so the 200x100 request correctly clipped to 101x51 pixels.

| Stage | Samples | p50 | p95 | Max |
| --- | ---: | ---: | ---: | ---: |
| Monitor enumeration | 100 | 0.02 ms | 0.02 ms | 2.40 ms |
| MSS capture/normalization | 30 | 16.62 ms | 18.53 ms | 18.64 ms |

Decision: do not cache monitor enumeration; it is immaterial beside capture and
OCR here. Keep MSS/pynput behind their existing seams. Revisit on an affected
platform/permission environment or a materially slower backend.

### OCR invocation counts

`artifacts/benchmarks/hover-invocation-rate.json` drives the real `HoverController`
decision seam with a deterministic OCR-call sentinel at the stable-handler
boundary. It measures current trigger behavior, not OCR latency.

| Condition | Movement events / window | OCR invocations |
| --- | ---: | ---: |
| Idle | 0 / 1.00 s | 0 |
| Small jitter, all moves inside the dwell interval | 8 / 0.50 s | 1 after settling |
| Rapid movement across text | 12 / 0.70 s | 1 after settling |
| Repeated stable hover over the same word | 5 / 1.25 s | 5 |
| Stable movement across non-text points | 5 / 1.25 s | 5 |

Decision: current debounce prevents OCR during idle and collapses continuous
motion, but it intentionally has no same-word or negative-result cache. Do not
add one from synthetic counts alone: screen content can change beneath an
unchanged pointer. A cache proposal needs a validity model, real repeated-use
trace, and correctness tests.

### Dwell to popup visible

Run `ae6dff36-0c15-4242-995b-7106f5771d89` exercised the real hover timer,
resident `LookupController` worker, real providers, queued presentation, and an
actually visible development Qt popup. It is not frozen evidence.

- Worker/provider constructions: 1.
- Lookup/OCR invocations: 7 for 7 traces.
- Warm configured dwell 150 ms: observed 161.59 ms p50 / 184.03 ms p95.
- Warm popup render-to-visible: 0.14 ms p50 / 0.16 ms p95.
- Warm event-to-visible total: 440.51 ms p50 / 675.03 ms p95 (5 samples).
- Cold event-to-visible: 7.673 s, including provider construction/lazy first use.

The stage benchmark above supplies the correlated algorithm breakdown:
capture -> OCR -> token selection -> morphology -> dictionary. This development
visible trace supplies dwell, controller/dispatch overhead, and popup-visible
endpoint. Frozen paint/OS-compositor latency remains unavailable.

## Resident idle

Run `c8397b82-1fe8-4483-a278-a08ef47940d6` kept Paddle/Kiwi/KRDICT resident for
60 seconds before lookup. Across 240 samples, process CPU was 0% as reported by
psutil, RSS moved from 493,359,104 to 493,293,568 bytes (−65,536 bytes), and the
observed min/max span was also 65,536 bytes. The deterministic hover idle case
triggered zero OCR calls. No local idle drift or repeated initialization was
found.

## Package composition

Exact local static tree: 10,530 files, 1,771,099,850 bytes.

| Family | Bytes |
| --- | ---: |
| PyQt6 / Qt / QtWebEngine | 557,091,478 |
| Torch / torchvision family | 390,834,255 |
| Paddle / PaddleOCR / PaddleX | 385,456,589 |
| OpenCV | 147,108,040 |
| SciPy | 73,720,832 |
| NumPy | 28,083,176 |
| Pandas | 13,676,772 |

Decision: package slimming is the largest plausible distribution win, but
static size does not prove runtime necessity. Draft a dedicated issue and test
each candidate exclusion through clean builds, frozen launch, real OCR, Control
Center/Qt, and all three platforms. No exclusion is applied in HAN-35.

## Other final decisions

- Keep PyQt6 for V1; the real popup path and current builds work, and no
  migration benefit was measured.
- Keep one product global lookup hotkey. Start/pause remain tray/Control Center
  UX; the broader action enum is a reusable service seam.
- Keep public compatibility aliases at `v0.1.0`; removal has no performance
  value and belongs at a breaking boundary.
- Do not change callback lock scope: warm popup rendering was sub-millisecond
  and no contention/deadlock reproduced.
- Do not add update-validation caching from the 31.28 ms mini-resource result;
  repeat with production KRDICT and real release resources.
- The controlled development PTY exited 1.17 seconds after Ctrl+C without a
  traceback but returned status 1. Frozen/packaged console cleanup and expected
  exit-code evidence remain a human/external trigger.
- Implemented the separately approved `hanly run` session selector and Windows
  frozen wrapper. This is a product workflow, not a benchmark optimization.

## Dedicated issue drafts (not filed by this run)

1. Frozen package slimming matrix for Torch/torchvision, Qt collection,
   PaddleX transitives, OpenCV, SciPy/Pandas, warnings, and three-platform real
   runtime gates.
2. Archive extraction entry-count/uncompressed-byte/ratio limits with
   adversarial tests and an explicit policy.
3. Application/resource signing and publisher provenance with key ownership
   and rotation policy.
4. Application version/About/self-update only when that feature is approved.

## Technical conclusion

The benchmark supports no new performance mutation yet. The measured hot path
is OCR; the current 200x100 default, MKLDNN=false setting, monitor enumeration,
resident lifecycle, and UI paint path do not justify code changes on this
evidence. The highest-value next performance work is broader corpus/hardware
measurement and a separately validated frozen-package slimming effort.
