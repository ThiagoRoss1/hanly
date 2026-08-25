# OCR Latency, Recognition Defects, and Post-V1 Roadmap

Status: research report. Not approved architecture. Records measurements taken
on 2026-08-24 and the plan derived from them.

Machine for every number below: Windows 10 `10.0.19045`, 8 logical cores,
Python 3.13.11, EasyOCR 1.7.2 / Torch 2.13.0+cpu, `torch.set_num_threads(4)`.
One machine, one fixture. These are engineering measurements, not a benchmark
campaign.

## 1. Why this exists

PaddleOCR was replaced with EasyOCR as the active V1 backend because Paddle
"remained perceptibly disruptive even after optimization". EasyOCR is lighter
and faster, but the popup still does not feel immediate, and hovering a word
often produces nothing. This report separates those two complaints into their
real causes, records what was measured, and fixes the order of work.

## 2. The latency budget

Per hover, measured end to end:

| Stage | Time | Share |
| --- | --- | --- |
| Hover dwell (`hover_delay_ms`) | 150 ms | 52% |
| Screen capture (MSS) | 16.6 ms | 6% |
| **OCR** | **~120 ms** | **42%** |
| Token selection | 0.04 ms | — |
| Morphology (Kiwi) | 0.17 ms | — |
| Dictionary (KRDICT) | 0.17 ms | — |
| Popup render (PyQt6) | 0.14 ms | — |
| **Total** | **~287 ms** | |

Kiwi, KRDICT, and the Qt popup together account for **0.5 ms — 0.2% of the
delay**. They are not a performance concern and should not be investigated as
one. Only two levers exist: the dwell and the OCR call.

PyTorch is not the per-hover cost either; the forward pass is. Torch's price is
paid elsewhere: ~4.5 s import, ~1 GB RSS, ~391 MB of the frozen package.

### 2.1 Inside the OCR call

At the real 200x100 capture size, `readtext` splits as:

| Phase | Time |
| --- | --- |
| CRAFT detection | 96.7 ms |
| CRNN recognition | 38.8 ms |

**Detection is ~88% of OCR cost** — and it is the language-agnostic half.

### 2.2 Latency scales with ROI pixel area

| ROI | Pixels | Latency |
| --- | --- | --- |
| 160x40 | 6k | 74.9 ms |
| 192x48 | 9k | 83.2 ms |
| 260x64 | 16k | 96.7 ms |
| 200x100 | 20k | 122.2 ms |
| 320x120 | 38k | 149.0 ms |
| 400x160 | 64k | 220.3 ms |

Roughly linear in area, with a ~65 ms floor from model overhead.

### 2.3 Tuning levers that do not work

Every one of these was measured and rejected:

| Attempt | Result |
| --- | --- |
| Hangul `allowlist` | No latency change; output still wrong |
| `mag_ratio=1.5` | +54 ms; output still wrong |
| `mag_ratio=2.0` | +170 ms; output still wrong |
| 3x LANCZOS pre-upscale | +434 ms; confidence 0.74, output still wrong |
| EasyOCR `recognize()` on the full ROI | 39 ms but garbage (`뼈오오다`, conf 0.002) — it needs a tight line crop, not the whole ROI |
| Paddle `enable_mkldnn=true` (HAN-35) | 13/13 `ERROR`, oneDNN `ConvertPirAttribute2RuntimeAttribute` unimplemented |
| Paddle thread limits (HAN-35) | 185 → 165 ms only, with a runtime warning |

## 3. Two diagnosed defects

### 3.1 Cause A — recognition misreads poison the whole word

EasyOCR never reads `책을` correctly. Across every configuration tried it
returns `책올`, `책울`, or `객올`. The vowel `ㅡ` is read as `ㅗ`/`ㅜ`.

`WordResolver` returns the whole whitespace-delimited eojeol, so the misread
goes to Kiwi intact. Kiwi's behavior on each variant:

```
'책을' -> 책/NNG, 을/JKO           first lemma 책   -> FOUND
'책올' -> 책/NNG, 오/VV, ᆯ/ETM     first lemma 책   -> FOUND
'책울' -> 책울/NNG                  first lemma 책울 -> NOT_FOUND
```

`LookupPipeline` uses `lemmas[0]`, so `책올` still recovers to `책` but `책울`
does not. Which variant comes out depends on how the ROI happens to crop, and
the ROI re-centers on every cursor move — **that is why the popup appears and
disappears as you move within one word.**

Kiwi is working correctly. The dictionary is not the problem (both `책` and
`읽다` are present in the dev database). This is a recognition-quality ceiling
and only a better or fine-tuned model fixes it.

### 3.2 Cause B — uniform character width creates dead zones

`_word_at_target` maps a point along the line quad with
`int(fraction * len(text))`, assuming every character has equal advance width.

Measured sweep across the recognized line `'책올 읽습니다:'` spanning x=[9,159]:

```
x=  0 -> None
x= 12 -> '책올'
x= 48 -> None      <- 20px dead zone
x= 68 -> '읽습니다:'
x=160 -> None
```

150 px / 8 characters = 18.75 px per slot, but the rendered space is ~6 px and
the trailing punctuation is similarly narrow. The mapping drifts by about one
slot, so the real `읽` glyph falls inside the *space's* hit slot (returns
`None`) while the visual gap falls inside `읽`'s slot (returns the word). The
user-reported symptom — "hovering 읽 does nothing, hovering the gap works" —
is exactly this inversion.

Pure geometry defect. No model involved. Fixable on its own.

### 3.3 Cause C — overlapping line quads were treated as ambiguity

`WordResolver` returned `None` whenever more than one region contained the
target, which the pipeline reports as `UNUSABLE`. On a dense paragraph that
fires constantly: EasyOCR emits line quads that overlap vertically wherever
lines are tightly set.

Measured on rendered 200x100 ROIs, counting sample points by how many quads
contain them:

| ROI | Regions | Points in exactly 1 quad | Points in >1 quad |
| --- | --- | --- | --- |
| One line | 1 | 280 | **0** |
| Three loosely spaced lines | 4 | 564 | **0** |
| Three tightly spaced lines | 4 | 359 | **23** |

The tight case emitted `'읽습니다.'` at y=[6,30] and `'책은'` at y=[27,43] — a
three-pixel overlap that swallows any cursor near the line boundary. This is
what made the popup work in a chat *input* box (one loose line) and fail in the
chat *answer* (a dense paragraph), and what made it flip between runs once ROI
snapping quantized the capture.

Resolution now picks the line the point sits furthest inside, measured as a
fraction of that line's own height, with area breaking a nesting tie and
provider reading order breaking the rest. Only zero hits still return `None`.
This changes a documented resolver behavior and is recorded here deliberately.

### 3.4 Cause D — a lone syllable is below the detector's floor

Reported from the desktop: hovering `책` standing alone gave `UNUSABLE`, while
`책이`, `책을`, `책은`, and `책 추천` all gave `SUCCESS` in the same font on the
same screen.

Detection of a lone `책`, measured across renderings:

| Condition | Detected |
| --- | --- |
| size 14, 16, 18, 20 — light or dark background, any position | **no** |
| size 22, 28, 36 | yes |
| `책이` at size 18 (two syllables) | yes |

So the floor is the glyph *box*, not isolation, contrast, or position: CRAFT
needs roughly 22 px, and a second syllable clears it by doubling the box width.
Screen UI text sits at 14–20 px, right underneath.

Only two knobs together recover it — `mag_ratio=2.0` **and** `min_size=4`.
Neither alone does anything:

| Options | Lone `책`, sizes 14–20 |
| --- | --- |
| default | not detected |
| `min_size=4` | not detected |
| `mag_ratio=2.0` | detected at size 20 only |
| `mag_ratio=2.0` + `min_size=4` | **detected at every size** |

The pair costs 123.7 ms → 330.2 ms, 2.7x, which is worse than Paddle and
cannot be the default. It runs as **one retry**, only when the first pass read
nothing at the cursor — `EMPTY`, or `UNUSABLE` with no resolved text. Text that
was read and then rejected (no Hangul, no lemma) is never retried, because
reading it again more slowly cannot change the answer.

Measured end to end after the change:

| Hover | Before | After |
| --- | --- | --- |
| lone `책` | `EMPTY` / `UNUSABLE` | **`SUCCESS`, 489 ms** |
| `책이` / `책을` / `책은` | SUCCESS | SUCCESS, 92–107 ms |

The retry provider shares the primary's `easyocr.Reader` rather than building a
second one, and has its own OCR cache, so a repeated hover over the same lone
syllable costs nothing.

### 3.5 Ruled out

- **Dictionary coverage.** `책` is one of the two seeded entries, and `책이`
  resolving to lemma `책` proves the lookup path for it works. `UNUSABLE` is
  reported before the dictionary is consulted; a missing word is `NOT_FOUND`.
- **Kiwi.** Never reached in the failing case.
- **Bold text and low image quality.** Bold, blur, and downscaling were tested
  at several strengths. They degrade recognition (`책올`, `척음`, `책음`) but
  the status stays `NOT_FOUND`; they do not produce `UNUSABLE`.

### 3.6 Audit of the capture -> Kiwi -> KRDICT chain

Prompted by two live observations: `책꽂이` reported as `책`, and `책읽는`
answering for the wrong part of the word.

**Cursor alignment is correct.** Grid snapping moves the captured region but
must not move the cursor relative to it. Verified by marking one screen pixel
and checking where it lands in the ROI, across `roi_grid` 1 and 32 and cursor
positions on both sides of a grid boundary: the reported target equalled the
marked pixel's position in all twelve cases. Covered by a regression test.

**`책꽂이` is not a morphology or lookup problem.** Kiwi returns it as a single
token `책꽂이/NNG`, so the pipeline looks it up unchanged and correctly reports
`NOT_FOUND` against the two-entry dev database. The reduction to `책` happened
in OCR. Same for `책상`, `책방`, `공책`, `책벌레` - the analyzer does not split
compounds.

**`책읽는` exposes a real design gap.** Kiwi analyzes it as
`책/NNG, 읽/VV, 는/ETM`, and `LookupPipeline` looks up `lemmas[0]`, so pointing
at `읽` answers with `책` - a confident, wrong definition rather than a
non-success. The pipeline's own diagnostic already names the cause: it "does
not re-target inside a segment".

Closing it needs the cursor's character offset to reach morpheme selection:

- `TokenAnalysis` would carry the token's `start` and `length`. Kiwi supplies
  both today (`Token.start`, `Token.len`) and `KiwiProvider` discards them.
- `WordResolver` would report where inside the resolved word the target fell.
  `_character_index` already computes exactly this and throws it away.
- `LookupPipeline` would select the token whose span contains that offset,
  falling back to the first lemma when no adapter supplies offsets.

This changes the `TokenAnalysis` contract and the `TargetResolver` return
shape, so it is recorded here as a proposal rather than applied.

**A rejected fix, recorded so it is not retried.** Trying the whole surface
form before its morphemes was implemented and reverted. It fixes neither
observation - a compound already arrives whole - and it overturns the
deliberate decision covered by
`test_pipeline_looks_up_only_the_first_usable_lemma_and_reports_not_found`.

## 4. Backend comparison

| | Paddle PP-OCRv5_mobile | EasyOCR 1.7.2 | MeikiOCR (reference) |
| --- | --- | --- | --- |
| Warm OCR p50 | 184.6 ms | ~120 ms | ~70–130 ms CPU / 15–30 ms GPU |
| Detection | (not split) | 96.7 ms | 20–30 ms CPU / 5–10 ms GPU |
| Recognition | (not split) | 38.8 ms | 50–100 ms CPU / 10–20 ms GPU |
| Fixture correctness | 30/30 | misreads `책을` | n/a (Japanese) |
| Runtime | paddlepaddle | PyTorch | **ONNX Runtime** |
| Cold construction | 8.8 s | 8.1 s | n/a |

Paddle was slower but correct; EasyOCR is faster but wrong on the hard
syllable. Neither backend has had a recognition-only hover fast path measured —
`PaddleTextRecognitionProvider` exists in the codebase but HAN-35 benchmarked
only the full det+rec path.

## 5. MeikiOCR / meikipop findings

Sources: `github.com/rtr46/meikiocr`, `github.com/rtr46/meikipop`.

meikipop is the Japanese hover-dictionary that inspired Hanly. It is **the same
stack as Hanly** — Python 3.10+, PyQt6, screen OCR, region selection — which
makes it a fair comparison target rather than an unreachable one.

Key findings:

- **It is not instant on CPU.** Its own benchmarks put total CPU inference at
  ~70–130 ms, the same range as EasyOCR. The "instant" feel comes from an
  NVIDIA GPU at 15–30 ms. The bar was never a magically light CPU model.
- **ONNX Runtime, no PyTorch.** This is why it is small and starts fast.
- **Two-stage detection + recognition**, with hard caps (max 64 text boxes, max
  48 characters per line) to bound worst-case cost.
- **Models are purpose-trained on Japanese video game text** — a domain
  fine-tune, not a general OCR model.
- **Apache 2.0 on both code and models.**
- Its detection is 3–5x faster than ours while its recognition is slower —
  the inverse of Hanly's profile, and detection is our bottleneck.

**The highest-value cheap experiment:** text *detection* is language-agnostic —
a box around a text line does not care whether it contains kana or Hangul.
MeikiOCR's ONNX detection model may work for Korean **as-is**, which would take
detection from 96.7 ms to ~25 ms with no training and a permissive license.
Pair it with a Korean recognizer and the OCR call could land near 60 ms.

## 6. Text acquisition tiers

Desktop text is not uniformly "just pixels". There are three tiers, and OCR is
only the last resort:

| Tier | Source | Latency | Accuracy | Covers |
| --- | --- | --- | --- | --- |
| 1 | DOM | ~0 ms | perfect | Browser extension |
| 2 | Accessibility APIs | 1–10 ms | perfect | Browsers, Electron, native apps |
| 3 | OCR | ~120 ms | imperfect | Games, images, video, canvas, PDFs |

### 6.1 Tier 2 — accessibility APIs per platform

**Windows — UI Automation (UIA).** The mature option. `IUIAutomation` +
`TextPattern` (`ITextProvider`) exposes a document's text and, critically,
`GetBoundingRectangles()` for any text range, so a screen point maps to a text
range via `ElementFromPoint` + `RangeFromPoint`. Chrome, Edge, Firefox, and
Electron all expose their content through UIA when accessibility is active
(Chromium may need `--force-renderer-accessibility` or activates it on demand).
Python access via `comtypes` or `uiautomation`. **Difficulty: moderate.** The
API is well documented and stable; the work is COM plumbing, per-app quirks,
and the fact that some apps expose text without usable per-character rects.

**macOS — NSAccessibility / AXUIElement.** `AXUIElementCopyElementAtPosition`
plus `kAXValueAttribute` / `AXBoundsForRange` is the analogue. Requires the
user to grant Accessibility permission in System Settings, which is a real
onboarding cost. Python access via `pyobjc`. **Difficulty: moderate**, plus a
permissions UX problem.

**Linux — AT-SPI2.** `pyatspi` / D-Bus, with `Accessibility_Text` interfaces
offering `getTextAtOffset` and `getCharacterExtents`. Coverage is good for
GTK/Qt apps but inconsistent elsewhere, and Wayland complicates global
coordinates. **Difficulty: high**, lowest payoff of the three.

**Verdict.** A Windows-only UIA fast path would make browsers and Electron apps
(including Claude web chat, Discord, most reading material that is not a game)
**instant and perfectly accurate**, falling back to OCR when UIA returns
nothing. That is a large user-visible win for one platform's worth of work.
It is a new OS-integration seam in `hanly-app` and is **deferred until after
V1**.

## 7. Fine-tuning plan (deferred)

The premise "any model can read text" is false for this domain. General OCR
models are trained mostly on photographs and scans; screen-rendered text at
12–16 px with antialiasing and subpixel hinting is a different distribution.
That mismatch is precisely the `을 → 올` failure.

Note on difficulty: Hangul is **not** a small-alphabet problem. There are
11,172 possible syllable blocks (~2,350 in common use), an output space
comparable to Japanese kanji. A jamo-level recognizer (24 classes) would be
tiny and fast, but jamo are visually fused inside a syllable block, so it is
harder than it sounds and is a research track, not a plan.

**What to train.** Start from a pretrained CRNN/CRAFT-style recognizer rather
than from scratch. Two viable entry points:

1. **EasyOCR's own recognition network.** `EasyOCRConfig` already carries
   `user_network_directory`, so a fine-tuned model drops in **without touching
   the provider or any contract**. Lowest integration risk.
2. **A MeikiOCR-shaped ONNX recognizer trained on Korean.** Higher ceiling
   (drops PyTorch entirely) and Apache 2.0 gives a working reference
   architecture, but more work.

Recommendation: **start with (1)**, because it is provable against the existing
seam in an afternoon, and only move to (2) if the ONNX detection experiment in
§5 already pays off.

**Training data.** Fully synthetic, no manual labeling. Render Korean text with
`trdg` or PIL across 20–30 Korean fonts x sizes x backgrounds x antialiasing
settings, and deliberately oversample the confusion pairs that fail today
(`을/올/울`, `그/고/구`). 200k–500k line crops is ample.

**Where and how long.**

| Phase | Effort |
| --- | --- |
| Synthetic data pipeline | ~half a day (AI-assisted) |
| Training harness + eval loop | ~half a day |
| Convergence from a pretrained checkpoint | 8–24 h on one rented GPU |
| Evaluation and iteration | 1–2 days |

Rent a GPU (RunPod / Vast / Colab), roughly **$0.30–0.80/h, so $10–20 total**.
CPU training is not feasible. AI assistance substantially accelerates the
*code*; it does not accelerate gradient descent.

**Precondition:** do not start until the evaluation corpus (§8) exists. Without
it there is no way to tell whether a fine-tune helped.

## 8. Evaluation corpus (prerequisite for any model work)

The dev dictionary currently holds **exactly two entries: `책` and `읽다`**.
That caps end-to-end testing, but it does not need to block OCR evaluation:
score **OCR text accuracy directly**, with no KRDICT involved, and keep a
smaller end-to-end set to prove the seams.

Corpus shape: 30–50 crops of `(image, expected_text, target_point,
expected_word)`, captured from where Hanly actually runs — Naver news, webtoon,
game dialogue, subtitles, PDF — at real screen scaling, deliberately including
small text, light-on-dark, and `ㅡ` vs `ㅗ`/`ㅜ` confusion pairs.

A headless script then runs every backend over the corpus and prints an
accuracy x latency table. This beats a hotkey model-switcher for *choosing* a
model (no hovering, reproducible, ~90 s); a hotkey switcher is worth building
only for the *feel* test between two finalists.

`benchmarks/han35/` already provides `prepare_roi`, a run store, and
statistics; this needs no new benchmark architecture.

## 9. Future implementations (post-V1)

**Browser extension.** The engine is already client-independent by design
(`hanly` never imports `hanly-app`). A port reads the DOM directly — Tier 1,
zero latency, perfect accuracy — and falls back to OCR only for `<img>` and
`<canvas>` content. The V1 architectural rule that keeps this cheap is that
transport and client concerns stay out of the engine.

**Games.** Already covered by the OCR path, since games expose nothing to Tier
1 or Tier 2. This is the case that justifies keeping OCR at all, and the case a
domain fine-tune helps most.

**Windows UIA fast path.** See §6.1. Largest desktop win available, deferred.

**Packaging weight.** The frozen package is **1,771,099,850 bytes**: PyQt6
557.1 MB, Torch family 390.8 MB, Paddle family 385.5 MB, OpenCV 147.1 MB.
Moving to ONNX Runtime would delete the Torch *and* Paddle contributions
(~776 MB) along with the 4.5 s import and most of the ~1 GB RSS. For weak
machines this matters more than any latency work in §10.

## 10. V1 plan — what is being implemented now

Ordered so each step is judged with the tool built in step 1, and so no step
depends on a model decision that has not been made. Steps 1–5 touch no model
and survive whichever backend eventually wins.

1. **Live dev HUD overlay.** Per-hover timeline: dwell → capture → OCR (live
   running indicator) → resolve → Kiwi → KRDICT → popup, with the resolved
   word, the status, and the reason for non-success (no text / no Hangul / dead
   zone / NOT_FOUND). Rolling history with p50 and cache-hit count. Consumes
   the trace events that already exist.
2. **Derive thread count from `os.cpu_count()`.** A hardcoded 4 oversubscribes
   a 2-core machine, which is the exact "computer feels heavy" symptom the
   backend swap was meant to remove.
3. **Fix `_word_at_target`.** Weight character advance by script instead of
   assuming uniform width. Removes the dead zones from §3.2.
4. **ROI grid-snapping + geometry cache.** The existing 32-entry cache is keyed
   on raw ROI bytes, and the ROI re-centers on the cursor, so it never hits
   while the mouse moves. Snapping the ROI origin to a grid makes small moves
   byte-identical, and caching OCR geometry in screen coordinates lets a cursor
   still inside a known quad skip capture and OCR entirely (~0.04 ms). This is
   the perceived-speed win: intra-line hovering goes from ~287 ms to ~0.
5. **Reduce dwell toward ~50 ms**, with a ~1 ms "is there text-like structure
   here" pre-gate so empty desktop costs nothing. Note that "run only when
   Hangul is detected" is not possible — detecting Hangul *is* the OCR — but
   the inverse (cheaply proving there is no text at all) is.

Then re-measure on the HUD and decide from what is observed.

### 10.1 Implemented on 2026-08-24

All five landed. Gates: 533 passed, Ruff clean, mypy clean across 121 files.

| Change | Where |
| --- | --- |
| `default_cpu_threads()` derives the Torch bound from `os.cpu_count()`, leaving one core for the desktop, capped at 4 | `hanly/easyocr_provider.py` |
| Per-script character advances replace uniform width in word targeting | `hanly/word_resolver.py` |
| `roi_grid` snapping, with the shift bounded to a quarter of the ROI | `hanly_app/capture.py` |
| `_CachingOCRProvider` keyed on ROI bytes, under the tracing wrapper | `hanly_app/composition.py` |
| `_TextPresenceGate`, opt-in via `skip_flat_rois` | `hanly_app/composition.py`, `hanly_app/runtime.py` |
| Default hover dwell 150 ms → 80 ms | `hanly_app/config.py` |
| A developer hover overlay was built and used for the diagnosis below, then removed from the shipped application | kept out of tree; the `runtime_trace` seam it consumed remains |

Measured after the change, EasyOCR backend, same fixture:

| Case | Before | After |
| --- | --- | --- |
| New ROI (what every cursor pixel used to produce) | ~146 ms | ~146 ms |
| Cursor moving across an already-recognized ROI | ~146 ms | **0.02–0.26 ms** |
| Flat ROI with the gate on | ~120 ms | ~0.3 ms |
| Word-gap dead zone on the fixture line | 20 px | 8 px |

Both fixture words now resolve — `책` at the line's left, `읽다` at its right —
where previously only the right-hand word did.

Two decisions worth recording. **The text-presence gate is opt-in, not
default:** turning it on unconditionally converted canned `SUCCESS` results
into `EMPTY` across the suite, which is the same silent-failure mode a
low-contrast real ROI would hit. **ROI snapping is also opt-in** at the
`CaptureService` seam, because exact centering is the honest general contract
and snapping exists only to serve the hover path's OCR cache; the desktop
composition passes `roi_grid=DEFAULT_ROI_GRID`.

Not yet observed: the live desktop loop under these changes. The HUD renders
correctly from a synthetic trace, but no hover session has been run by hand.

## 10.2 App integration (2026-08-24)

EasyOCR is now what the application ships, not an opt-in configuration.

| Change | Effect |
| --- | --- |
| `OCRBackend` default, `_ocr_backend` fallback, `DEFAULT_OCR_RUNTIME_MODULE` | A configuration naming no backend means EasyOCR; the pre-Qt native preload loads `easyocr` |
| `_default_runtime_payload` | A first launch writes an EasyOCR manifest declaring only `krdict`, with `skip_flat_rois` on |
| `REQUIRED_RESOURCE_IDS` replaces `REQUIRED_RESOURCE_KINDS` | Provisioning requires what the selected backend needs, not the Paddle three |
| `packaging/hanly-desktop.spec` | Collects `easyocr`/`torch`/`torchvision` beside the Paddle packages, skipping any that are absent |
| `resources/dev/runtime{,-local}.json` | Tagged `"ocr_backend": "paddle"` so the Paddle examples still mean Paddle |

PaddleOCR is retained and selectable: `runtime-local.json` still loads,
`require_paddle_config()` still works, and its adapter and tests are untouched.

Verified by composing the app the way a normal launch does:

```
pre-Qt preload module   : easyocr
first-run backend       : easyocr      resources: ['krdict']
bare config resolves to : easyocr
providers constructed   : ['EasyOCRProvider', 'KiwiProvider', 'KRDICTProvider']
hover fast path         : None         (PaddleOCR-only, correctly absent)
real lookup             : 303 ms  SUCCESS  lemma='읽다'
```

**Two defects found while integrating.**

`UpdateService.check_for_updates` iterated the *remote* manifest, so an EasyOCR
install was offered PaddleOCR model downloads that `install()` then refuses
("local manifest has no resource"). It now reports only resources the local
manifest declares. This was latent before the default changed.

`ResourceManifest` iterates `ResourceSpec` values and defines no
`__contains__`, so `resource_id in manifest` compares a string against specs
and is always `False`. The first version of the filter above used exactly that
and silently dropped every resource.

**Not verified:** a frozen build. The spec now names the EasyOCR packages, but
no PyInstaller run has been attempted, and package size will grow before it
shrinks (Torch is collected alongside Paddle until Paddle is removed).

## 11. Deferred, with triggers

| Item | Trigger to revisit |
| --- | --- |
| MeikiOCR ONNX detection model for Korean | Steps 1–5 land and hover still feels slow |
| Evaluation corpus (§8) | Before any model swap or fine-tune |
| Recognition fine-tune (§7) | Corpus exists and accuracy is the blocker |
| Windows UIA fast path (§6.1) | After V1 ships |
| Browser extension | After V1 ships |
| Drop PyTorch for ONNX Runtime | Package size or weak-machine RSS becomes the complaint |
| EasyOCR models as managed resources | Before any frozen release of this backend |
| Packaging spec hooks for EasyOCR/Torch | Before any frozen release of this backend |
| Paddle recognition-only fast path measurement | If Paddle is reconsidered |
| Seed full KRDICT | Independent of this work; end-to-end tests stay limited to `책`/`읽다` until then |
