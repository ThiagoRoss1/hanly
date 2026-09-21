# Wave 7 — OCR alternatives and HanlyOCR: research verdict

Status: research report. **Not approved architecture, and it changes nothing.**
Authorized as evidence-only on 2026-09-21.

Scope limits observed: no PaddleOCR, no production OCR provider, no backend
selector, no resource-provisioning or package-composition change, no model
downloaded or trained, no benchmark result promoted into production, and the
shipped EasyOCR/Vision composition is untouched.

## Method

The existing Wave 2 corpus, metrics, run store and staged comparison format
were reused unchanged. Both shipped backends were re-run through the existing
`benchmarks.dev ocr-campaign` path against the locally generated 8-case
manifest, one warmup and three samples per case, `ocr-only` mode.

```bash
.venv/bin/python -m benchmarks.dev ocr-corpus --manifest artifacts/benchmarks/corpus/manifest.json
.venv/bin/python -m benchmarks.dev ocr-campaign --backend vision  --mode ocr-only \
    --warmup 1 --samples 3 --manifest artifacts/benchmarks/corpus/manifest.json
.venv/bin/python -m benchmarks.dev ocr-campaign --backend easyocr --mode ocr-only \
    --warmup 1 --samples 3 --manifest artifacts/benchmarks/corpus/manifest.json
```

Machine: macOS 26.6.2, Python 3.13.11, one display. Raw runs stay under the
gitignored `artifacts/benchmarks/runs/` root and are not committed.

## What the incumbents measure at

8 cases × 3 samples = 24 scored observations per backend, 0 errors each.

| | Apple Vision | EasyOCR |
|---|---|---|
| Target surface correct | **1.000** | **0.375** |
| Hangul syllable error rate | **0.000** | 0.215 |
| Character error rate | **0.000** | 0.177 |
| Target region recall | 1.000 | 1.000 |
| False empty | 0.000 | 0.000 |
| Warm p50 | 23.0 ms | 25.7 ms |
| Warm p95 | 27.2 ms | 40.4 ms |
| Cold p50 | 25.0 ms | 30.6 ms |
| Cold p95 | 261.7 ms | 97.0 ms |
| Peak RSS growth | **45.8 MB** | **1,010.4 MB** |
| Peak RSS | 113.5 MB | 1,052.2 MB |
| Model shipped | none — part of macOS | downloaded on first use |

**Region recall is 1.000 for both.** Detection is not the differentiator; the
entire gap is recognition, which reproduces the diagnosis already recorded for
the 2026-09-20 backend decision rather than discovering something new.

## Verdict: change nothing now

**Hanly should not pursue another OCR model or HanlyOCR at present.** Three
reasons, in order of weight:

1. **The incumbent is at the ceiling of the available evidence.** Vision scores
   1.000 with a zero error rate on every case in this corpus. A candidate cannot
   be shown to beat it here, so any comparison run today would measure the
   corpus rather than the model. Adding one would be benchmark overfitting on
   eight synthetic renders.
2. **The measured deficit is EasyOCR's, and it is a platform-coverage problem
   rather than a model-selection problem.** 0.375 is poor, and it is what
   Windows and Linux users get. But choosing a replacement needs cross-platform
   measurements this repository does not have, and the corpus that would justify
   it does not exist yet.
3. **A second resident engine costs what the first one already costs.** EasyOCR
   alone peaks at ~1.05 GB RSS. Hanly retires that child deliberately; adding a
   second heavy engine to evaluate in production would undo work already done.

## This verdict conceals no shared-pipeline defect

Wave 5 found that Safari/WebKit and Discord/Electron expose no usable text range
on macOS, so web and chat content still reaches OCR. That is an **acquisition**
gap in the accessibility layer, not an OCR-model gap, and no OCR candidate would
address it. It is recorded in the Wave 5 checkpoint and belongs to Wave 6's
browser evaluation, not here.

The whole-form and component work in this campaign is downstream of recognition
and equally unaffected by backend choice.

## Exactly what would justify revisiting HanlyOCR

Each of these is missing today. A future authorization should require them
before a candidate is evaluated at all:

- **Dataset.** A corpus of *real screen captures*, not only synthetic renders,
  with per-case provenance, across fonts, sizes, weights, subpixel rendering,
  dark and light backgrounds, and at least the three desktop platforms. The
  current corpus is 8 locally generated images using one Apple system font.
- **Labeling.** Target-word level ground truth with the cursor position, so
  `target_surface_correct` means the same thing across candidates, plus an
  agreed treatment of the batchim classes EasyOCR loses.
- **Cross-platform measurement.** Windows and Linux numbers for any candidate
  and for EasyOCR on the same corpus. Vision is macOS-only, so a candidate's
  value is decided entirely off this machine.
- **Licensing.** Model weights and training-data terms compatible with Hanly's
  redistribution, recorded as metadata in the run store rather than assumed.
- **Budget.** A stated package-size and RSS ceiling for a second engine, given
  the ~1 GB the current one occupies while resident.
- **Training rights**, if fine-tuning rather than adopting a model.

`docs/execution/reports/ocr-latency-and-roadmap.md` remains the historical
measurement record; this report does not supersede it and adds no production
decision.
