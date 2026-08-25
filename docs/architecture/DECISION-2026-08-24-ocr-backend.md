# Decision: EasyOCR replaces PaddleOCR as V1's OCR backend

Date: 2026-08-24. Status: approved by the human owner and implemented.

Supersedes the earlier V1 scope decision recorded in `01`, `02`, and `03` that
EasyOCR was out of scope and `PaddleOCRProvider` was V1's only OCR
implementation. Affects `RF-INV-10` and `DAG-INV-13`.

## Why PaddleOCR came off the default path

Not correctness. PaddleOCR was the more accurate adapter and still is. It came
off because of what it cost to run.

**It was perceptibly disruptive in use.** The complaint that started this was
that the machine felt heavy whenever OCR ran. HAN-35 measured warm OCR at
**184.6 ms p50** (238.1 ms p95) on the development host, against ~120 ms for
EasyOCR on the same fixture and machine.

**The obvious remedies were tried and failed.** `enable_mkldnn=true` produced
13/13 `ERROR` results — Paddle's oneDNN path raised
`ConvertPirAttribute2RuntimeAttribute is unimplemented` on this stack. Thread
limiting moved 185 ms to 165 ms while the runtime itself warned about the
configuration. Neither made the cost acceptable, and both are recorded in
`docs/execution/reports/han-35/results-and-decisions.md`.

**Its footprint is large and mandatory.** The Paddle family contributes
385.5 MB to the frozen artifact (HAN-35 INV-039), and PaddleOCR requires two
managed model resources that first-run provisioning must download and validate
before the desktop can start. EasyOCR resolves its own models through its
storage directory, so an EasyOCR install provisions only `krdict`.

## What was accepted in exchange

EasyOCR is faster but weaker. It misreads `책을` as `책올`/`책울` in every
configuration tried, including Hangul allowlists, `mag_ratio` upscaling to 3x,
and LANCZOS pre-upscaling; confidence scores are far lower (0.29–0.55), so no
`confidence_threshold` tuned against Paddle carries over, and none is
configured. Its detector also needs roughly 22 px of glyph height, which a lone
Hangul syllable at normal UI size does not reach, handled by a slower
second-pass retry rather than by slowing every lookup.

This trade was made deliberately: responsiveness now, accuracy later through a
domain fine-tune on the `HanlyOCR` research track. The measurements, the
rejected tuning levers, and the deferred items are in
`docs/execution/reports/ocr-latency-and-roadmap.md`.

## What did not change

The provider seam absorbed the swap with **no contract change**. `OCRProvider`,
`LookupPipeline`, `WordResolver`, the normalized contracts, capture, the popup,
cancellation, and request-currency validation were all untouched. That the
backend could be replaced by adding one adapter and one configuration value is
evidence the seam was drawn in the right place.

`PaddleOCRProvider` is retained, tested, and selectable through
`"ocr_backend": "paddle"`, together with the recognition-first hover fast path
that only Paddle supplies. Removing it is not part of this decision.

## Consequences to carry forward

- Release manifests must carry `krdict`, and may advertise both backends'
  assets; `UpdateService` reports only resources the local manifest declares.
- Frozen builds now collect Torch **and** Paddle, so package size grows before
  it shrinks. Removing Paddle is the trigger for that reduction.
- No frozen artifact has been built or run against this backend.
