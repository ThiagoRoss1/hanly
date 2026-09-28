# Decision: Apple Vision is preferred on macOS; EasyOCR stays cross-platform

Date: 2026-09-22. Status: **approved by the human**. Supersedes the
"EasyOCR is V1's only OCR implementation" statements of the 2026-08-26 decision
in `01`, `02` and `03`; affects `RF-INV-10` and `DAG-INV-13`, whose IDs and
positions are unchanged.

The implementation predates this record: Vision was added at the human's
direction on 2026-09-20 (`d66a361`), and `CLAUDE.md` described it, but the
architecture documents were never synchronized. This record makes the approved
behaviour authoritative; it adds nothing to it.

## Decision

- Both OCR implementations sit behind `OCRProvider`. `LookupPipeline` knows only
  the seam.
- `VisionProvider` (Apple Vision, part of macOS, no model download) is the
  preferred production OCR provider on supported macOS.
- `EasyOCRProvider` remains Hanly's cross-platform implementation and the
  fallback wherever Vision is unavailable.
- The internal `ocr_backend` configuration selects `auto` (the default: Vision
  where the platform provides it, otherwise EasyOCR), `vision` or `easyocr`.
  `auto` is resolved in the shell; the lookup child receives a concrete choice.
- There is **no user-facing provider selection**. The Control Center may report
  which implementation is active; it does not offer a choice.
- PaddleOCR is not restored, and no further provider is added.

## Evidence, and how far it reaches

All measurements are from one macOS development machine.

| Source | Corpus | Accuracy | Latency |
|---|---|---|---|
| Spike, `checkpoints/lookup-and-popup-correction-2026-09-19.md` | 7 acceptance words carrying the `ㅆ` batchim | Vision **7/7** at 40 px (5/7 at 20 px); EasyOCR **0/7** at every resolution tried. Full pipeline 7/8 against 0/8 | Vision 25.5 ms, EasyOCR 72.3 ms |
| Wave 7, `reports/ocr-research-verdict-2026-09-21.md` | 8 synthetic cases × 3 samples, one Apple system font | Target surface correct **1.000** against **0.375**; syllable error 0.000 against 0.215 | Warm p50 23.0 against 25.7 ms, warm p95 27.2 against 40.4 ms |
| Mac Phase B re-run, `review-handoffs/mac-campaign-2026-09-21.md` | the Wave 7 corpus again | reproduced exactly | Warm 21.1/25.7 against 26.8/40.8 ms |

What this supports: materially better Korean accuracy, and faster **warm**
recognition, on the evaluated corpus. What it does not:

- The speed advantage is small at the warm median (about 10%) and clearer at
  p95. Vision's **cold p95 was worse** (261.7 against 97.0 ms): the first call
  pays to load the framework.
- The corpus is small, synthetic and single-font. It is not a product-wide
  accuracy claim, and it says nothing about Windows or Linux, where Vision does
  not exist.
- Vision also used far less memory (45.8 MB against 1,010.4 MB peak RSS growth
  in Wave 7, re-measured 47.6 against 889.6 MB). That is recorded, not the basis
  of the decision.

## Evidence discipline

Staged EasyOCR diagnostics (`benchmarks/dev`) reproduce `Reader.readtext()`
stage by stage for investigation. They are replay evidence: detector and crop
internals from a replay are never attributed to a production `readtext()` call,
and never to a live Vision invocation.

## Revisit

Only with a stronger, representative corpus -- real screen captures across
fonts, sizes, backgrounds and all three desktop platforms -- or a demonstrated
production regression in either implementation. HanlyOCR remains a separate,
non-blocking research track under the same condition.
