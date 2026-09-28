# Text acquisition diagnostic baseline

**Date:** 2026-09-21
**Plan:** `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`
**Bundle:** A (Waves 1–2)
**Checkpoint:** `docs/execution/checkpoints/text-acquisition-diagnostics-2026-09-20.md`

The first reproducible measurement of Hanly's text-acquisition path. Every
quantitative table below is derived from retained raw run files named here; the
prose is interpretation and limits.

**Read the evidence classes literally.** *Measured* was observed on this machine
in a run identified below. *Derived* was computed from retained raw samples.
*Unavailable* means the tool could not read it and says so. *Not yet run* means
nobody has run it. Nothing here is estimated, and no absent value is a zero.

---

## 1. What this baseline does and does not establish

It establishes that real lookups can be followed end to end, including two
silent failures from a human-operated production hover session, and that OCR can
be measured apart from the rest of the pipeline on a repeatable corpus.

It does **not** establish an accuracy claim for Hanly, because the scored corpus
is eight synthetic samples rendered from one font on one machine and the live
session has no complete ground-truth labelling. It does not establish anything
about Windows or an external display. And it does not, on its own, justify any
backend decision: the Apple Vision selection was made on 2026-09-20 from
separate evidence, and what follows measures rather than replaces that decision.

## 2. Environment

| | |
|---|---|
| Platform | macOS 26.6.2, arm64 (Apple silicon) |
| Python | 3.13.11 (`.venv`) |
| Display | one internal display, 1408×881 logical, no external display attached |
| `hanly` / `hanly-app` | 0.5.3 |
| EasyOCR | 1.7.2 |
| Torch | 2.13.0 |
| Resolved product backend | `auto → vision` |
| `psutil` | **not installed**, so current RSS is unavailable throughout |

## 3. Corpus composition and provenance

| | |
|---|---|
| Committed corpus (`benchmarks/fixtures/ocr/manifest.json`) | **0 cases** |
| Local corpus used for the measurements below | 8 cases, all `local_synthetic` |

The committed corpus is empty for two separate and deliberate reasons, both
recorded in `benchmarks/fixtures/ocr/README.md`.

**No Korean face with a redistributable licence is installed here.** The
generator names Noto Sans KR (OFL-1.1). This machine has only Apple's
`AppleSDGothicNeo.ttc` and `AppleGothic.ttf`. The generator refuses to
substitute a face, because a mislabelled font turns every measurement into a
measurement of something else.

**The existing Korean fixture is not accuracy evidence.**
`tests/hanly_fixtures/assets/korean_reading_roi.png` is marked
`"benchmark": false` in its own metadata and exists as a correctness-regression
input. Scoring a backend against it and calling the number an accuracy
measurement is exactly the overfitting the plan warns about.

The measured corpus was therefore generated locally from Apple SD Gothic Neo
(sha256 `e33989af92c53dd2…`), which the tooling marks `local_synthetic`. A
committed manifest refuses such a case, which is why it stayed local.

| Tag | Cases |
|---|---|
| synthetic | 8 |
| light | 7 |
| dark | 1 |
| medium_text | 5 |
| small_text | 2 |
| large_text | 1 |
| punctuation | 3 |
| mixed_script | 1 |
| scaled | 1 |
| compressed | 1 |
| blurred | 1 |

All eight carry expected text, an expected pointer, and an expected surface
word. None carries annotated regions, so detection precision and recall report
`not_applicable` throughout — they are not zero.

## 4. Measured OCR campaigns

Command shape (`--warmup 1 --samples 3`, so one cold pass, one warm-up and three
warm passes per case; 40 passes per campaign, 24 of them scored):

```bash
.venv/bin/python -m benchmarks.dev ocr-campaign \
  --mode <mode> --backend <backend> \
  --manifest artifacts/benchmarks/corpus/manifest.json \
  --warmup 1 --samples 3
```

| Run ID | Backend | Mode |
|---|---|---|
| `5b18673a-1648-4af1-a7a3-66c2966a7ac5` | Vision | ocr-only |
| `74e187fb-360a-4990-9edc-0ca6ddd3bf4f` | EasyOCR | ocr-only |
| `2a74fd7b-37b3-4029-bd40-ef568a92da0f` | EasyOCR | detection-only |
| `858a61e2-350a-4a3a-ae44-f48c3fa80a0d` | EasyOCR | recognition-only |

Raw per-pass records are in each run's `samples.jsonl`; every number below
regenerates from them.

### 4.1 Correctness — *derived* from 24 warm passes per campaign

| Metric | Vision | EasyOCR |
|---|---|---|
| Exact complete-string match | **1.00** | **0.00** |
| Character error rate (NFC) | **0.000** | **0.177** |
| Hangul syllable error rate | **0.000** | **0.215** |
| Correct target surface word | **1.00** | **0.375** |
| Target-containing region recall | 1.00 | 1.00 |
| False-empty rate | 0.00 | 0.00 |
| Repeated-input variance | 0.00 | 0.00 |
| Detection precision / recall | `not_applicable` | `not_applicable` |

Both backends always returned a region containing the pointer, and neither was
ever unstable across repeats. The gap is entirely in what the region said.

### 4.2 Latency — *derived*, nearest-rank over retained raw durations

| Campaign | cold p50 | cold p95 | warm p50 | warm p95 | warm n |
|---|---|---|---|---|---|
| Vision ocr-only | 24.1 ms | 208.0 ms | **21.3 ms** | 68.8 ms | 24 |
| EasyOCR ocr-only | 32.5 ms | 94.1 ms | **27.1 ms** | 40.8 ms | 24 |
| EasyOCR detection-only | 33.3 ms | 46.2 ms | 27.5 ms | 42.1 ms | 24 |
| EasyOCR recognition-only | 33.8 ms | 52.8 ms | 28.8 ms | 45.1 ms | 24 |

Cold p95 is one sample by construction (eight cold passes, one per case) and is
dominated by first-inference setup. These are small images on an idle machine
and are not an SLA.

A staged EasyOCR pass over the real frozen ROI split as detection 74.7 ms,
recognition 43.5 ms, normalization 0.02 ms (§5.2).

### 4.3 Memory — peak *measured*, current *unavailable*

Peak RSS comes from `resource.getrusage`, which needs nothing extra. Current RSS
needs `psutil`, which is not installed, so baseline, initialized and steady RSS
report themselves unavailable rather than reporting zero.

| Campaign | peak RSS | growth over the campaign |
|---|---|---|
| Vision ocr-only | 114.7 MB | **49.6 MB** |
| EasyOCR ocr-only | 984.7 MB | **945.2 MB** |
| EasyOCR detection-only | 953.7 MB | 913.3 MB |
| EasyOCR recognition-only | 946.2 MB | 906.6 MB |

Roughly a **19× difference in peak growth** for the same eight images in the
same process. This is one measurement on one machine and is not a product memory
budget.

### 4.4 Per-case EasyOCR failures — *measured*

Every warm pass of every case, Vision: correct. EasyOCR:

| Case | Expected | EasyOCR read | CER | Target word right? |
|---|---|---|---|---|
| syn-light-small-plain | `떨어뜨렸어요` | `떨어뜨렇어요` | 0.167 | no |
| syn-light-large-plain | `떨어뜨렸어요` | `떨어뜨로어요` | 0.167 | no |
| syn-light-medium-plain | `책을 읽습니다.` | `책올 읽습니다:` | 0.250 | no |
| syn-dark-medium-plain | `책을 읽습니다.` | `책올 읽습니다` | 0.250 | no |
| syn-light-scaled-down | `한국어 사전을 찾습니다` | `한국어 사전온 찾습니다` | 0.083 | yes |
| syn-light-compressed | `한국어 사전을 찾습니다` | `한국어 사전올 찾습니다` | 0.083 | yes |
| syn-light-blurred | `한국어 사전을 찾습니다` | `한국어 사전올 찾습니다` | 0.083 | yes |
| syn-light-mixed-script | `Hanly 버전 2.0 설치` | `위리7\|커 버전 2.0 설치` | 0.333 | no |

Two patterns, both independently reproducing what
`docs/execution/reports/ocr-latency-and-roadmap.md` already recorded.

**The batchim is the failure.** `떨어뜨렸어요 → 떨어뜨렇어요` is the exact `ㅆ`
past-tense loss that report names, reproduced here at a different size and font.
`을 → 올/온` is the same class: the final consonant is misread while the rest of
the syllable is correct. This is a semantic failure, not a cosmetic one — `읽다`
and a wrong batchim are different dictionary entries.

**The Korean-only model reads Latin badly.** `Hanly → 위리7|커` is the
`korean_g2` character set doing what a Korean-only model does with Latin. It
matters because real Korean UI text sits beside product names and version
numbers.

Three of eight cases still selected the right target word despite a CER above
zero: the error fell outside the word under the pointer. That is exactly why the
plan insists transcription and target selection are scored separately.

### 4.5 Mode separation — *measured*

`detection-only` drops the recognized text by construction. Its transcription
metrics therefore report `not_applicable` for all 24 warm passes, and it reports
`target_region_recall` 1.00, which is the only thing it actually measured. An
earlier revision of this tooling scored those metrics anyway and reported a
character error rate of 1.00 for a transcription it never attempted; that was a
defect in the benchmark and was corrected.

Vision exposes no separately addressable detector, so `detection-only` and
`recognition-only` refuse it rather than fabricating one.

## 5. Measured real frozen lookup

### 5.1 One complete real hover (macOS, 2026-09-21)

Exported to `artifacts/benchmarks/runs/w17-frozen-1/` (gitignored). Real
`CaptureService` at `DEFAULT_ROI_GRID`, real Apple Vision, real Kiwi, real
KRDICT, `skip_flat_rois=true`, real hover runtime, real microscope. The
committed Korean fixture was displayed on screen with the human's authorization
so a real hover had Korean text to land on; the pointer was never moved.

| Stage | What the frozen record says |
|---|---|
| Pixels | 200×100 RGB_888, 60 000 bytes, keyed digest `da77b774199acee6` |
| ROI / grid | ideal `(269,175,200,100)` → snapped on grid 32 → `(256,160,200,100)`; actual == desired, not clipped |
| Cursor | requested `(369,225)` == effective, not clamped; ROI-local `(113,65)`; edge distances L/T/R/B `113/65/86/34` |
| Gate | ran, RGB_888, first-channel row delta, steps 3/3, threshold 32, target 8, observed 8, **passed**, early exit |
| Caches | full-result miss; OCR cache consulted, miss |
| Provider | Vision executed; no skip reason |
| Normalized OCR | one region `책을 읽습니다.` @ 0.500 |
| Selected region | index 0, contains target |
| Resolver | fraction `0.6688` → character 5 → span `[3,8]` → surface `읽습니다.`, `region_start` 3, `cursor_index` 2; weights `[1.0, 1.0, 0.35, 1.0, 1.0, 1.0, 1.0, 0.35]` |
| Kiwi | `읽`/VV→`읽다`, `습니다`/EF, `.`/SF; one candidate `읽다` over `[0,4)` |
| KRDICT | query `읽다`, 1 entry, found |
| Retained | screen `(321,209,98,30)`, protected `(317,205,106,38)`, scale 1.0 |
| Outcome | `SUCCESS`, `missing=[]` |

**Independent cross-check of the ROI → screen transform.** A separate
full-screen Vision pass located `읽습니다.` at `(321,210)-(418,240)`. The frozen
retained rectangle, derived through the entirely different capture-origin plus
`word_region` path, is `(321,209)-(419,239)`. They agree to one pixel, which is
the resolution of the axis-aligned advance-weight estimate.

### 5.2 Staged EasyOCR replay of the same ROI — *measured*

| | |
|---|---|
| Live (Vision, the production backend) | `책을 읽습니다.` @ 0.500 |
| Staged EasyOCR replay, same ROI bytes | `책올 읽습니다.` @ 0.562 |
| `compare_to_live` | `matches=False` — `region 0 text: '책을 읽습니다.' vs '책올 읽습니다.'` |
| Retained crop | 296×64 grayscale, the exact recognizer input |
| Timings | detection 74.7 ms, recognition 43.5 ms, normalization 0.02 ms |

The divergence is surfaced as a finding; the live Vision result stays
authoritative. The staged crops are labelled `comparison_replay` and are never
attributed to the provider pass that actually produced this lookup's output.

Note that the replay confidence (0.562) is *higher* than the live confidence
(0.500) on the answer that is wrong. Confidence did not distinguish them.

### 5.3 Human-operated production hover — *measured*

Run `ef2c1ffc-3746-4b94-a40a-680b7e9e29c3` used the real macOS activation,
capture, Vision, Kiwi, KRDICT, popup, freeze, and export path for 300 seconds.
Ten lookups completed: eight visible `SUCCESS` results and two suppressed
`UNUSABLE` results. Eight unique lookups were explicitly exported beneath the
run directory; repeated actions against the same lookup reused its existing
private directory.

| Metric | Measured value |
|---|---:|
| Hover opportunities / captures / completed | 10 / 10 / 10 |
| Visible success / suppressed unusable | 8 / 2 |
| Hover-to-visible-popup p50 / p95 | 397.4 / 1118.6 ms |
| Dwell p50 / p95 | 158.2 / 158.9 ms |
| Capture p50 / p95 | 51.5 / 114.1 ms |
| OCR p50 / p95 | 173.1 / 462.5 ms |
| Total pipeline p50 / p95 | 178.0 / 471.9 ms |

The two real failures are `frozen-9` and `frozen-10`. Both 200x100 exported
ROIs visibly contain Korean beneath the recorded cursor. In both cases the gate
ran and passed, the OCR cache missed, and the production Vision provider
executed. Its normalized output contained only the nearby numbered-list markers
(`6.`/`7.`/`8.` and `1.`/`2.` respectively), with zero Hangul regions. Target
resolution consequently reported `no_candidate_contains_target`; morphology and
dictionary were correctly not reached, and presentation correctly suppressed
the `UNUSABLE` result.

These exports carry no staged EasyOCR attachment. Their live Vision result is
the authoritative evidence.

**The omission is not Korean-specific, and right-edge truncation is not the
discriminator.** The Phase B review established both, and neither is a leading
hypothesis any more. A row-ink profile of `frozen-10` shows Vision also dropped
the complete, unclipped **Latin** line `do Hanly:`; everything it returned
across both failures is a short bold left-margin numeral, and everything it
dropped is proportional body text of either script. And `frozen-8` *succeeded*
on Hangul regions that also run to the ROI edge (x=66-198 of 200), so truncation
is common to the successes and the failures. Vision exposes no separate detector
boxes, so the run cannot distinguish region omission from recognition omission;
the nearer open variables are ROI/grid offset and clipped partial lines.

The successful glued-word exports prove a separate behavior: OCR preserved the
strings and cursor mapping selected different Kiwi candidates (`초대`, `받다`,
or `깨뜨리다`) by position. KRDICT has no `초대받다` lemma. A policy that treats
the entire surface as that compound is therefore a language/dictionary decision,
not part of the silent OCR failure classification.

## 6. Failure classification from real evidence

Two real failing hovers have now been captured and enter at the **live production
OCR-output stage**. The gate passed, Vision executed on uncached pixels containing
the target Korean, and the normalized result omitted every Hangul region. The
resolver, morphology, dictionary, and presentation are downstream and behaved
consistently with that omission.

This does not yet select a correction. Vision exposes no separately addressable
detector, and the fixed ROI cuts the longer surrounding lines. One controlled
same-case input-context experiment must distinguish OCR-internal omission from
ROI-context sensitivity before Wave 3 changes product behavior.

Separately, the EasyOCR failure on synthetic and frozen inputs enters at **OCR
recognition**, not detection and not the resolver. The evidence for that
attribution remains:

- detection-only reports target-containing region recall 1.00, so the detector
  found the right region every time;
- the resolver, given Vision's output for the same pixels, resolved the correct
  surface word;
- the staged replay retains the exact 296×64 crop that reached the recognizer,
  and that crop contains the correct glyphs;
- the errors are confined to final consonants inside otherwise correct
  syllables.

The EasyOCR result remains comparison/research evidence, not the production
failure and not a reason to alter backend selection.

## 7. Validation matrix

| Platform / configuration | Capture geometry | Cursor alignment | Freeze | OCR stages | DPI / external display |
|---|---|---|---|---|---|
| macOS Retina (internal) | **measured** | **measured** | **measured through real hotkeys** | Vision live **measured**; EasyOCR staged **measured separately** | not available |
| macOS external display | not available | not available | not available | not available | not available |
| Windows 100% | not available | not available | not available | not available | not available |
| Windows 125% | not available | not available | not available | not available | not available |
| Windows 150% | not available | not available | not available | not available | not available |
| Windows mixed DPI | not available | not available | not available | not available | not available |

No Windows machine and no external display were available to this run. Linux is
supported by the pixel architecture and is not claimed from this evidence.

## 8. Explicit unknowns

- **Vision substage unavailable.** The real failures are classified to live OCR
  output, but Vision exposes no raw detector evidence, so detection versus
  recognition cannot be claimed.
- **ROI-context causality unmeasured.** The Korean target pixels are present,
  but the surrounding long UI line extends beyond the fixed ROI. The identical
  case has not yet been repeated with full-line context as the only changed
  variable.
- **Current RSS unavailable.** `psutil` is not installed; only peak RSS is
  measured. Installing it would fill in baseline, initialized and steady RSS.
- **Committed corpus empty.** Everything in §4 is `local_synthetic` from one
  proprietary font on one machine and cannot be reproduced elsewhere from Git
  alone. Installing Noto Sans KR and running `ocr-corpus-generate` makes the
  corpus committable and the numbers comparable across machines.
- **No annotated regions**, so detection precision and recall are unmeasured.
- **Real-application coverage is narrow.** One browser/UI rendering supplied the
  live failures; chat, native-control, video/subtitle, game, webtoon, canvas and
  other raster surfaces remain unmeasured.
- **Gate false-negative rate unmeasured.** The metric exists; no campaign yet
  pairs gate observations with known-text ROIs.

## 9. Reproducing this

```bash
# Enumerate the committed corpus (empty, and says why).
.venv/bin/python -m benchmarks.dev ocr-corpus

# Render a corpus. Refuses unless a licensed Korean face is installed.
.venv/bin/python -m benchmarks.dev ocr-corpus-generate

# Score it. --backend vision | easyocr, --mode ocr-only | detection-only |
# recognition-only | frozen-replay.
.venv/bin/python -m benchmarks.dev ocr-campaign \
  --mode ocr-only --backend vision \
  --manifest <manifest> --warmup 1 --samples 3
```

Every campaign writes `metadata.json`, `corpus-inventory.json`,
`samples.jsonl` and `summary.json` under
`artifacts/benchmarks/runs/<run-id>/`. Each table in §4 regenerates from
`samples.jsonl` alone.

The §5 frozen lookup came from a scratchpad script driving the real composition,
because a `live-hover` session needs a human at the machine. The equivalent
interactive path is `live-hover` with `Ctrl+Alt+Shift+F` to freeze and
`Ctrl+Alt+Shift+E` to export.

## 10. Decisions this report does not make

No OCR-backend change is proposed. No memory ceiling, latency budget, or accuracy
threshold is proposed from one machine, eight synthetic images, and one narrow
live session. The live run now supplies a real OCR-stage failure, but no Wave 3
correction is selected until one controlled same-case experiment distinguishes
ROI-context sensitivity from provider-internal omission.
