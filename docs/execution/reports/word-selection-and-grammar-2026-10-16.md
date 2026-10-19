# Hover word selection and Korean grammar coverage (2026-10-16)

Mac evidence only. These runs are Apple Silicon results for the recognizers
they name, and none of them is Windows evidence. The Windows continuation is
`windows-word-selection-continuation.md`.

**Review qualification (2026-10-16):** the tables below preserve the original
recorded counts. They predate later classifier corrections and the complete
transport/cache review. They are historical offline evidence, not acceptance
of the current packaged desktop. In particular, the old direct-text grammar
harness called the engine directly and could not detect neighboring context
being lost on the real lookup pipe; that defect is fixed by the review.

## How it was measured

- **`python -m lab grammar`:** the language stage alone (Kiwi and KRDICT),
  over the reviewed 108-case corpus `lab/fixtures/korean/grammar.json`.
  - The original corpus scored 688 hovers. Review found one omitted final
    syllable (`g106`, 을), so the corrected corpus scores 690.
  - Both acquisition forms are scored: the whitespace-delimited word OCR
    resolves, and the Korean run accessibility text yields.
  - Expected headwords and constructions are verified against KRDICT before
    scoring.
- **`python -m lab word-selection`:** Lab-authored three-line pages.
  - Sizes 14, 20 and 28 px; light and dark; normal and display-edge placement.
  - Hovers on the first, middle and last syllable of every word of the middle
    line.
  - The crop is the desktop's own (`_centered_region`, 200 × 100, 32 px grid,
    clipped to the page), and the real lookup worker runs on it.
  - Misses are classified against exact glyph geometry: whether the selected
    line is the hovered line is decided by vertical overlap, not by text.
- **The same hovers on three engines:** `main` (pre-migration), `795fd7c`
  (migration, before this session's language changes) and `c7a81b3` (now).
  Each engine is extracted with `git archive`; the harness and pages are
  unchanged.

## What the reported truncation actually is

On Vision, at stride 2 (7,596 hovers):

| category | `main` | `795fd7c` | now |
|---|---|---|---|
| correct | 7,081 (93.2 %) | 7,081 (93.2 %) | **7,233 (95.2 %)** |
| wrong lexical choice | 222 | 222 | 72 |
| crop clipped the word | 111 | 111 | 134 |
| OCR misread | 143 | 143 | 118 |
| no result | 30 | 30 | 30 |
| OCR false space | 9 | 9 | 9 |

On EasyOCR, at stride 3 (5,076 hovers): `main` 66.9 % correct, now **69.1 %**.
Wrong lexical choices fall from 115 to 0. OCR misreads are 1,512 against
1,498, and crop clipping is 49 against 63.

### Findings

1. **The migration did not change offline word selection.** `main` and
   `795fd7c` give hover-for-hover identical results. The resolver, the crop
   rule and the engine behave the same before and after the Tauri migration.
   - If more truncation is seen live since the migration, it comes from what
     this harness does not exercise: live cursor coordinates and scaling,
     capture timing, direct (accessibility) text, or the popup.
   - Those need live runs, and on Windows the native DPI matrix.
2. **The wrong lexical component was the largest fixable cause, now mostly
   fixed** (`176e705`). It had several distinct mechanisms:
   - **The copula** opened its own unit, so 학생**입**니다 answered 이다.
   - **Surface-first lookup** took an unrelated listed word of another class:
     먹지 (carbon paper), 할 (割), 드릴, and 나는 listed as a form of 나다.
   - **No context:** 나는 before 가요 and the auxiliary in 먹고 있어요 were
     invisible without the neighbouring word.
   - **Korean fused to digits or emoji** was refused outright (2026년에).
3. **Crop clipping is real but small:** about 1.8 % of Vision hovers.
   - It happens only at a word's first or last syllable, never in the middle.
   - It is the shipped 200 px crop meeting the 32 px grid snap.
   - It is identical before the migration.
   - The "now" count is 23 higher only because narrowing moved mixed-script
     cases there from "misread"; misread plus clipped is 254 before and 252
     now.
4. **EasyOCR's dominant problem is recognition, not selection.** 29.5 % of
   hovers are misreads, evenly across first, middle and last syllables, so
   whole lines are misread. Selection fixes cannot recover characters never
   recognized.
5. **Remaining real lexical misses on Vision:**
   - 하늘을 **나는** 새 → 나다: Kiwi lemmatizes 날다 + 는 as 나다; this is a
     Kiwi limitation.
   - 뭉클해졌습니다 at 해 or 졌 → the auxiliary 지다 inside one word.
   - 고르고 → no entry on two hovers.
   - The harness first scored per-syllable expectations against the first
     syllable's answer; that accounted for 20 of the 72 and is fixed in
     `e68cca9`. The table keeps the original 72 rather than combining a
     corrected category with an uncorrected total. Raw observations were not
     overwritten, and the review did not re-run this 7,596-hover campaign.
     A second review fix checks wrong-line geometry before crediting matching
     text. Old observations lack the geometry needed for a full rescore.

### Not reproduced here, still to check live

- Logical and physical coordinate or DPI errors: the harness works in
  pixels.
- Stale results tied to an earlier pointer position: latest-wins and the
  final currency check are unchanged and covered by their tests, but not
  re-measured live in this session.

## Korean grammar coverage (`lab grammar`)

| | before | after |
|---|---|---|
| correct headword, OCR form (344 hovers) | 319 | **342** |
| correct headword, direct form (344 hovers) | 327 | **338** |
| constructions named (38) | 0 | **37** |
| auxiliary sense ranked first (15) | 6 | **15** |
| minibook targets, independent check (144) | 142 | **143** |

What is left:
- **Three-word construction:** 할 수 있다 is out of the one-word window.
- **Kiwi's 나다 for 날다:** as above.
- **Direct text splits at punctuation:** (학교)에 and '사랑'이라는, at the
  particle syllable.

The corpus expectations were written by the implementer to KRDICT headwords
and standard school grammar. **Independent human review is still pending.**

Review tightened four particle-combination expectations, added the omitted
`g106` syllable, and removed pronoun 나 as an acceptable answer to the flying
bird's 나는. The latter follows the
[National Institute of Korean Language's explanation of 날다 + 는](https://www.korean.go.kr/front/mcfaq/mcfaqView.do?mcfaq_seq=9072).
The new, separate strict run scores **343/345 OCR-form and 339/345 direct-form
headwords**, **37/38 constructions** and **15/15 auxiliary senses** in each
form. Particle checks now count only cases that actually require parts.
The denominator changed; the extra correct hover is coverage, not an accuracy
improvement. Evidence: `artifacts/lab/reviews/20261016-codex/grammar-strict-summary.md`.

## Consistency checks evaluated (not shipped)

- **The selected line touching the crop edge says nothing:** lines are wider
  than the 200 px crop on 88 % of hovers.
- **The resolved word touching the crop's side is informative:** on Vision it
  fires on 21 % of hovers, and 61 % of all misses are among them.
- **Candidate:** one re-capture at twice the width around the same pointer,
  only when the word touches the side.

| | Vision | EasyOCR |
|---|---|---|
| fired | 1,609 of 7,596 | 1,072 of 5,076 |
| misses recovered | 186 (of 363) | 78 (of 1,567) |
| correct answers disturbed | 4 | **15** |
| extra genuine OCR calls | 1,297 | 826 |
| added latency on those hovers, p50 / p95 | 41 / 74 ms | **106 / 231 ms** |

**Not promoted.** The recorded aggregate is positive on Vision, but on EasyOCR (Windows'
recognizer) it disturbs 15 correct answers and adds 106 ms at the median
where it fires. It must be measured natively on Windows before any decision.
A second pass over the same text was not used as verification: it cannot
recover characters OCR never read.

The old retry instrumentation included retry recognitions in first-pass OCR
counts, which could mislabel cached first passes as fresh. Review separated
those counts. Treat old first-pass latency selection as contaminated; the
retry's separately measured latency remains historical, not a new promotion
decision. New word-selection recordings use protocol v2, start-time source
identity/diff, dependency/font/dictionary/corpus identities and the provider
worker thread. They cannot be mixed with these old runs as if unchanged.

## Runs

- **Word selection:**
  - `20261016-215742` (Vision, now) and `20261016-220528` (EasyOCR, now);
  - `20261016-220841` (Vision, `795fd7c`);
  - `20261016-221146` (Vision, `main`) and `20261016-221740` (EasyOCR, `main`).
- **Grammar:** reports under `artifacts/lab/grammar/` (gitignored).
