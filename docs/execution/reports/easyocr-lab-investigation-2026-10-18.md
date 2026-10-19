# EasyOCR and native capture investigation — 2026-10-18

Implementation-side investigation authorized by the human on the existing
`desktop/tauri-migration` branch. This is not the queued deep commit review or
Windows acceptance. The product payload remains `b9124b4`; this follow-up
changes Lab tooling, tests and documentation only.

## Findings

### 1. The Korean model cannot emit some common Korean syllables

The actual EasyOCR 1.7.2 reader's `character` alphabet has 1,008 characters:
913 precomposed Hangul blocks plus 95 ASCII characters. Examples absent from
the model are `를`, `왔`, `었`, `했` and `쁜`. This matches the upstream
[`korean_g2` model configuration](https://github.com/JaidedAI/EasyOCR/blob/v1.7.2/easyocr/config.py).
It is a model output limitation, not a Kiwi, KRDICT, React or hover failure.

Of the unchanged 865 synthetic cases, 113 expected target tokens and 333 whole
lines contain Hangul outside that alphabet. All 113 impossible target tokens
fail in the new baseline. They account for 113 of its 315 strict token failures;
they do not explain the other 202. No threshold, second detector, beam search,
dictionary lookup or larger crop can make this output head emit an absent
class. Model work remains a separate future scope; no model was replaced or
downloaded here.

There is also a separate language mask: eleven Hangul classes present in the
model are absent from the Korean language file. None occurs in this corpus's
expected Korean lines or targets. Allowing the entire existing model alphabet
therefore changes no score in the diagnostic subset. This is not the cause of
the 113 impossible targets.

Evidence: local `observed-alphabet.json` derives both limitations from the
initialized reader, not only from a source-file assumption. It preserves the
affected case IDs and field names separately.

### 2. The old Lab campaign bypassed the product's CPU thread policy

`lab.cli._ocr_provider_factory` constructed `easyocr.Reader` directly and
injected it into `EasyOCRProvider`. The real adapter applies its Torch thread
bound only when it constructs the reader, so even `--cpu-threads` did not take
effect through this campaign path. This was a benchmark defect; product
construction already used the correct path.

The factory now creates one real product adapter and exposes that adapter's
reader to staged diagnostics. A regression checks single construction and
explicit/default thread configuration. New diagnostic runtime records confirm
`device=cpu` and four actual Torch threads. The earlier handoff's **MPS label
was incorrect**: `gpu=False` already selected CPU in those old campaigns.
Historical latency is not a controlled before/after performance baseline.

### 3. Additional inference options did not provide a safe general improvement

The same 120 images were selected deterministically by image ID, balanced
across fonts, without consulting previous OCR failures. Each variant received
two measured repetitions. This deliberately stresses fonts and is not a
population accuracy estimate. Product answers agreed between repetitions.

| Variant | Exact target tokens per 120 | Whole lines per 120 | Interpretation |
| --- | ---: | ---: | --- |
| Product, greedy decoder | 70 | 17 | Reference |
| Existing sensitive pass (`mag_ratio=2`, `min_size=4`) | 68 | 10 | Seven recovered targets, nine regressions; roughly twice the median latency |
| Beam search, width 5 | 66 | 13 | Four regressions, no recoveries |
| Annotated tight line boxes, no detector | 45 | 1 | Ground-truth crop diagnostic; tight crops can hurt recognition |
| Annotated line boxes with 10% height margin | 63 | 8 | Better than tight crops, still below product |
| Full existing model alphabet | 70 | 17 | No improvement on these images |
| Quantization disabled | 70 | 17 | No target or whole-line accuracy gain |

Oracle boxes contain only known geometry, never expected text supplied to the
recognizer. They are unavailable at runtime and **are not an accuracy upper
bound**: the recognizer is sensitive to crop margins. Their faster recognition
time does not justify removing detection from the product.

The staged replay matches the real normalized provider output on all 120
initial diagnostic images. Mean detector/recognizer work in that run was about
33.5/20.8 ms. This establishes the staged path's agreement and demonstrates
that detection is a significant cost; these host-specific means are not a
Windows latency budget.

No decoder, retry policy, allowlist, confidence threshold, model or production
OCR behavior was changed to improve a benchmark score. Original truths and
raw wrong answers remain intact.

### 4. The legacy macOS capture call returns after approximately 30 seconds

A bounded diagnostic repeatedly captures a 100×60 region covered initially by
an opaque, temporary Lab window. Existing capture access preflight is true.
Three unchanged MSS calls complete in **30.122, 30.023 and 30.016 seconds**.
This supersedes the earlier inference that the call hangs indefinitely: the
12-second probes genuinely timed out, but did not wait long enough to observe
the eventual return. The returned bytes were not all the expected white, so
neither timely nor correct real acquisition is accepted from this probe.

A native process stack locates the wait at:

```text
SLWindowListCreateImage
  → SLSWindowListCreateImageProxying (ScreenCaptureKit)
  → _dispatch_semaphore_wait_slow
```

The sampled XPC path also involves ReplayKit/replayd. This identifies where
the delay occurs; it does not prove why the OS proxy fails to answer promptly.
It is not EasyOCR inference: that diagnostic loads no OCR provider.

For comparison, the existing Lab-only ScreenCaptureKit helper captures the
same owned window successfully in about 0.53 seconds, with the expected white
center pixel. Unlike the MSS region call, this is a window-specific capture;
it is an API viability check, **not a like-for-like ROI latency benchmark**.
No screen images from this comparison were retained.

Apple marks
[`CGWindowListCreateImage` deprecated](https://developer.apple.com/documentation/coregraphics/cgwindowlistcreateimage)
and documents [ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
as the supported capture path. Changing the macOS adapter to bounded on-demand
ROI capture through that API is a concrete follow-up proposal. It was not
implemented: the human explicitly asked to preserve the capture method, and
architecture changes need approval. Windows capture would remain a separate
platform adapter. Moving the same blocking call to a thread alone is not a
demonstrated solution.

## Completed verification

- Three previously paused packaged window checks: **3 passed, 33.49 s**.
  They exercise React readiness, updater acknowledgement and native root/
  service ownership and retirement, using isolated profiles and disposable
  update installations. The identity check uses the canonical candidate.
- Full macOS native suite including Lab cursor/image fixtures: **88 passed,
  134.78 s**. The MSS fixture also passes independently in 31.30 s. A green
  pixel correctness test without a latency assertion does not disprove the
  separately measured capture delay.
- Full portable gate: **2,665 passed, 2 skipped**, with two process-inventory
  failures because the filesystem sandbox refused `ps`. The host-enabled
  five-case process-inventory rerun passes, including both failed cases.
  No test or production behavior was weakened to hide that environmental limit.
- Final focused Lab gate: **64 passed**. Ruff passes; mypy passes over 361 files.
  No Rust/frontend/product source changed, so the prior corresponding build
  and checks remain applicable.

The same-image full EasyOCR campaign, with the corrected factory and four
threads, is `1d9298af-2cde-454d-94e9-19b9867c552b`: **865 cases, 3,460 actual
calls** (cold, warm-up, two warm), zero execution errors. Strict token accuracy
remains **550/865 (63.58%)** and whole-line exact match remains **170/865** on
each warm repetition. Warm p50/p95 are about 59.7/116.8 ms. Peak process RSS is
about 995 MiB; this includes the provider process and its libraries, not only
model weights. These measurements overlap other validation work, including a
brief interrupted diagnostic; do not call them a clean performance comparison.

## Native application boundary still open

One real EasyOCR-driven stress session was attempted through the debug
LaunchServices app with an isolated profile and non-conflicting shortcuts:
`20261018-022721-stress`. Runtime readiness and the actual shortcut input were
acknowledged; starting capture explicitly failed with `permission_required`.
There is **no successful native OCR hover** in this run. The owned app was
stopped and cleaned up; no permissions were requested/reset to bypass the gate.

The diagnostic shell's true permission preflight does not grant the separately
responsible Hanly.app identity. The fresh packaged candidate is still build
`47462440`, payload `b9124b4`; `/Applications/Hanly.app` was not replaced and
the user's existing debug process was not stopped. Signing/keychains are
unchanged. No permission-persistence claim follows from these tests.

Remaining acceptance: grant/verify the intended final app identity with the
human present; resolve the slow legacy macOS capture path; exercise actual
hover/Expand/Collapse/Close and the original Codex border artifact; manual
shortcuts/tray checks; Windows DPI/acquisition and Windows/Linux native tests.
The queued human-selected commit review remains separate.

## Reproduction and evidence

Local evidence root: `artifacts/lab/reviews/20261018-easyocr-investigation/`.
`diagnostic-120`, `unquantized-120-v2` and `alphabet-padding-120` contain input
hashes, selected cases, effective runtime, model hashes, raw per-repetition
results, stage replays and compact summaries. `unquantized-120` was interrupted
to avoid concurrent OCR work and is not a completed result. Original 865-case
campaigns and baseline registrations were preserved, not replaced.

```bash
python -m lab.easyocr_audit \
  --manifest artifacts/lab/reviews/20261017-popup-retention/grammar-pages-v2/corpus.json \
  --output artifacts/lab/reviews/new-easyocr-audit \
  --limit 120 --samples 2 --cpu-threads 4
```

Additional diagnostic variants: `--variants product model-alphabet
line-oracle-padded`; quantization comparison: `--variants product
--no-quantize`. This runner refuses private screenshots, never overwrites an
existing evidence directory and downloads no model. Generated grammar truth
does not become an independently reviewed native text-detector oracle.
