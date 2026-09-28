# OCR corpus fixtures

`manifest.json` is the committed corpus: images that may live in Git and be
compared across machines. `generator.json` describes the synthetic samples that
would populate it.

## Why the committed corpus is currently empty

Two separate reasons, both deliberate.

**The existing Korean fixture is not accuracy evidence.**
`tests/hanly_fixtures/assets/korean_reading_roi.png` is marked
`"benchmark": false` in its own metadata and exists as a correctness-regression
input. Scoring an OCR backend against it and calling the number an accuracy
measurement would be exactly the overfitting the benchmark plan warns about.

**No Korean face with a redistributable licence is installed here.** The
generator names Noto Sans KR (OFL-1.1). This machine has only Apple's
`AppleSDGothicNeo.ttc` and `AppleGothic.ttf`, whose licence does not permit
redistributing derived rasters. `synthetic_ocr.resolve_font` therefore refuses
to render rather than substituting a face and mislabelling every sample.

## Populating it

Install Noto Sans KR into any of the searched font directories, then generate:

```powershell
python -m benchmarks.dev ocr-corpus-generate
```

Samples rendered from a non-redistributable face are still usable locally: they
become `local_synthetic` cases, which corpus validation refuses to accept in a
committed manifest.

## Private cases

Real frozen captures are somebody's screen. They stay in a `local` manifest
under the gitignored `artifacts/benchmarks/` tree, and corpus validation refuses
to load a `local_private` case from a committed manifest or to accept an
absolute path in one.
