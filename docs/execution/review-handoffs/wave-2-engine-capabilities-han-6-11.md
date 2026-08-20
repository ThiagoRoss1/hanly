# Wave 2 Engine Capabilities Review Handoff

## Bundle

- Member issues: HAN-6, HAN-7, HAN-8, HAN-9, HAN-10, HAN-11
- Implementation ecosystem: GPT — Sol orchestrator with direct Luna xhigh workers
- Date: 2026-08-20

## Implemented

- PaddleOCR 3.7 adapter with normalized ROI input, OCR results, explicit model configuration, and injected-engine testing.
- Kiwi morphology adapter returning normalized token analyses without leaking Kiwi objects.
- Reproducible KRDICT XML-to-SQLite build path with a versioned schema and indexes.
- Read-only KRDICT runtime provider returning normalized dictionary entries.
- Quad-aware WordResolver for selecting the sole OCR segment under an engine-level target point.
- Local ResourceManager for availability, readability, version, checksum, schema, compatibility, and composition-facing validated paths/configuration.

## Main expected behavior

The Wave 2 engine branches can now turn normalized inputs into OCR, morphology, dictionary, resolution, and resource-state outputs through UI-independent seams. The KRDICT branch builds and consumes the same read-only SQLite contract, and concrete providers receive explicit configuration or paths without depending on ResourceManager.

## Architecture / seams touched

- `OCRProvider`, `MorphologyProvider`, and `DictionaryProvider` concrete adapter boundaries.
- `ROIImage`, `OCRResult`, `TokenAnalysis`, `DictionaryEntry`, and `ResourceMetadata` normalized contracts.
- `WordResolver` Quad hit testing and normal no-result behavior.
- `ResourceManager` local-resource boundary and explicit composition handoff.
- CA-INV-02/03/05/07/09/13 and DAG-INV-01/03/07/09/13/14/16.

## Relevant files / diff areas

- `packages/hanly/src/hanly/paddleocr_provider.py`
- `packages/hanly/src/hanly/kiwi_provider.py`
- `packages/hanly/src/hanly/krdict_build.py`
- `packages/hanly/src/hanly/krdict_provider.py`
- `packages/hanly/src/hanly/word_resolver.py`
- `packages/hanly/src/hanly/resource_manager.py`
- Corresponding `tests/test_*` files for those six modules.

## Implementation-side validation already run

- Worker-focused provider/build/resolver/resource tests, Ruff, and mypy checks passed before convergence.
- `.venv\Scripts\python.exe -m pytest` -> 95 passed.
- `.venv\Scripts\python.exe -m ruff check packages tests` -> passed.
- `.venv\Scripts\python.exe -m mypy packages tests` -> no issues in 24 source files.

## Known limitations / intentionally unvalidated areas

- PaddleOCR model loading and real Korean inference were not run; normalization used injected Paddle-compatible result shapes to avoid model downloads and heavyweight inference in the implementation phase.
- KRDICT processing was exercised with deterministic small XML inputs; no production KRDICT dump or database artifact was downloaded or committed.
- Current execution evidence is Windows/Python 3.13 only; cross-platform runtime and packaging behavior remains for its later DAG capabilities.
- Concrete PaddleOCR/Kiwi imports are lazy and the current environment supplies their runtimes; distribution dependency policy was not expanded in this bundle.
- No LookupPipeline or desktop integration was attempted; those remain downstream capabilities.

## Suggested review targets

- PaddleOCR 3.7 result-shape normalization and explicit model-name/path configuration against a real cached Korean model.
- KRDICT XML field coverage and schema compatibility against the approved production source format.
- WordResolver ambiguity policy and Quad boundary behavior as inputs to LookupPipeline.
- ResourceManager status classification, manifest ergonomics, and separation from provider construction/update delivery.
- Whether concrete-provider dependency metadata should be introduced before independent `hanly` distribution is exercised.

## Post-Bundle Review Outcome

- Reviewer: Claude (Opus 5)
- Review ecosystem: Claude, reviewing a Codex-implemented bundle
- Date: 2026-08-20
- Status: Closed, including a follow-up manual-review cleanup pass. Windows scope. Two real defects found and fixed; real Korean OCR and morphology verified end to end. Nine considerations deferred with explicit revisit triggers.

Gates after the review: **100 passed, Ruff clean, mypy clean across 26 source
files.** Note that `tmp_path` tests need `--basetemp` pointed somewhere writable
on this machine — see the environment item below.

### Fixed now

- **Grayscale ROIs could never reach PaddleOCR.** `_to_paddle_image` built a
  two-dimensional array for `GRAYSCALE_8`, and PaddleX unpacks height, width and
  channels from the array it receives, so every grayscale ROI died with
  `not enough values to unpack (expected 3, got 2)` before inference. Since
  hover capture is the format most likely to be grayscale, this would have
  surfaced only at desktop integration. The single channel is now replicated to
  three without altering pixel values, and a parametrised regression test
  asserts all supported formats arrive as `(h, w, 3)` `uint8`.
- **Cross-thread lookups were reported as a corrupt database.** A SQLite
  connection belongs to the thread that opened it, so calling
  `KRDICTProvider.lookup` from a worker raised `sqlite3.ProgrammingError`, which
  the broad `except sqlite3.Error` turned into *"KRDICT database became
  unreadable during lookup"* — a message that sends a debugger after the file
  instead of the caller. The thread violation is now named directly. This is the
  error message only; the threading strategy itself is deferred below.
- **`_roi` test helper generalised** so it produces a byte count matching any
  `PixelFormat`, rather than only RGB and grayscale.
- **Regression coverage added for both fixes**, and final validation after the
  review is **100 passed, Ruff clean, mypy clean over 26 source files**.

### Verified against real runtimes

These were the handoff's top two unvalidated areas; both now have evidence.

- **Real Korean OCR through the provider seam.** Against the cached
  `PP-OCRv5_mobile_det` + `korean_PP-OCRv5_mobile_rec` models and the committed
  192x48 fixture, all three pixel formats return `'책을 읽습니다.'` at
  confidence **0.9821** in 0.14-0.26 s, with identical geometry
  (`BoundingBox(left=6, top=7, right=151, bottom=39)`), and `WordResolver`
  resolves the text at the quad centre. The `rec_polys` preference in
  `_normalize_v3_result` matches what PaddleOCR 3.7 actually returns.
- **Real Kiwi morphology.** `KiwiProvider` returns `읽` with lemma `읽다`
  (`VV`) for `읽습니다`, so the morphology-to-dictionary seam produces
  dictionary-shaped lemmas. `kiwipiepy`'s `Token.lemma` exists and is used
  correctly; `morphology` is always `None` because Kiwi exposes no such field.
- **KRDICT build and lookup** work on a KRDICT-shaped LMF `LexicalResource`
  document, not only the simplified `<dictionary>` fixture in the tests.

### Manual-review cleanup pass (2026-08-20)

A follow-up manual pass over five specific points. No new deep review was run.

Fixed now:

- **`KRDICTProvider.__exit__` typing.** `(self, _exc_type, _exc_value, _traceback)`
  left three untyped parameters — an `Any` hole in a public dunder of a
  `py.typed` package. Replaced with `def __exit__(self, *_exc_info: object) -> None`.
  `-> None` is retained so exceptions raised inside the `with` block still
  propagate. This is the only context manager in the repository.
- **`ResourceManifest.__iter__` type-ignore removed.** `_specs` is already
  `tuple[ResourceSpec, ...]`, so the annotation is simply
  `Iterator[ResourceSpec]`; the `no-untyped-def` suppression was hiding a type
  that needed no abstraction to express.
- **`ResourceManager.metadata` type-ignore removed.** The accessor genuinely has
  two shapes, so it is now annotated
  `Mapping[str, ResourceMetadata] | ResourceMetadata` rather than suppressed.
  `get_metadata` no longer delegates through it — both read a small private
  `_metadata_for` helper — so the single-record path stays precisely typed
  without `@overload` or a cast.
- **`WordResolver._usable_quad` degeneracy threshold.** The exact
  `area_twice != 0.0` test disagreed with the scaled-epsilon tolerances used
  everywhere else in the module: `Quad` construction rejects a shape with no
  extent on an axis, but four nearly collinear points still pass and enclose
  only float noise, which the exact test called usable while `_contains` cannot
  meaningfully place a point inside it. Now `abs(area_twice) >
  _GEOMETRY_EPSILON * scale * scale`, scaled from the quad's own extent for the
  same reason the other tolerances are. Resolver policy is unchanged — a
  degenerate quad was already a normal no-result outcome. Two focused tests
  cover a near-collinear sliver and a thin-but-real quad.

Validation after this pass: **102 passed, Ruff clean, mypy clean over 26 source
files.**

Intentionally left as-is:

- **`# type: ignore[import-untyped]` on the `paddleocr` import.** The only
  remaining engine suppression, and it is justified: PaddleOCR ships no type
  information, so the ignore records a fact about the dependency rather than
  hiding a Hanly type. It should stay until PaddleOCR ships stubs.

### Deferred considerations

Deferred means the concern is valid, is not required for safe forward progress
now, and is intentionally postponed until its trigger provides better evidence.
Do not implement one merely because it is known. At the final V1 Deferred Review
Sweep each unresolved item is re-evaluated against the completed system: already
solved -> dismiss; still relevant to V1 -> address; genuinely future -> carry
forward explicitly.

- **SQLite threading strategy.** `KRDICTProvider` opens one connection with
  default thread affinity. The failure is now reported correctly, but the
  runtime ownership and threading strategy is deliberately undecided — per-thread
  connections, or `check_same_thread=False` with serialized access. *Revisit
  before Desktop Foundation / worker wiring needs KRDICT lookups off the creating
  thread, and decide from the actual desktop worker and lifecycle design rather
  than guessing now.*
- **PaddleOCR oneDNN / MKLDNN default.** On this Windows machine the default
  oneDNN path reproduces `(Unimplemented) ConvertPirAttribute2RuntimeAttribute
  not support [pir::ArrayAttribute<pir::DoubleAttribute>]`;
  `enable_mkldnn=False` works and is already configurable through
  `PaddleOCRConfig.extra_options`. *Revisit when concrete PaddleOCR provider
  defaults and packaging/runtime defaults are finalized. Do not hardcode a
  shipped policy from this one machine unless implementation evidence justifies
  it.*
- **WordResolver abutting-quad ambiguity.** Hit testing is boundary-inclusive
  and any count other than exactly one hit returns `None`, so a target on an
  edge shared by two adjacent quads resolves to nothing. *Revisit when real OCR
  geometry produces adjacent or shared-edge cases, or resolver behavior
  demonstrates an actual ambiguity. Do not invent additional geometry policy
  now.*
- **`ResourceManager` duplicated accessor pairs.** `validated_path` /
  `get_validated_path`, `configuration` / `get_configuration`, `metadata` /
  `get_metadata`, `statuses` / `metadata`, plus a `metadata()` that returns
  either a mapping or a single record behind a `type: ignore`. *Revisit when
  ResourceManager consumers exist and real public/internal API usage is visible;
  simplify only if the duplication remains.*
- **KRDICT production-dump field coverage.** The build path was exercised with
  small deterministic XML and an LMF-shaped document, not the real release.
  *Revisit when the production KRDICT dataset/schema is integrated or validated
  — current fixture/LMF evidence is not sufficient to design every production
  mapping now.*
- **Concrete-provider dependency extras.** `paddleocr` and `kiwipiepy` are
  lazily imported and absent from `hanly`'s declared dependencies, which is
  correct for an engine that must stay importable without them, but leaves
  installation undefined. *Revisit when the packaging/install experience for the
  PaddleOCR, Kiwi, and KRDICT providers is being defined; do not design optional
  dependency groups before concrete distribution requirements are known.*
- **Windows temporary-directory ACL / `WinError 5`.** Local environment
  evidence, not Hanly architecture: `tmp_path` tests error during collection
  unless `--basetemp` is redirected, e.g.
  `python -m pytest --basetemp=<writable dir>`. *Revisit only if it reproduces
  outside this machine or affects CI/build/test environments.*

- **PaddleOCR adapter `Any` boundary.** `Any` in
  `paddleocr_provider.py` is doing real work: it is the boundary where dynamic
  PaddleOCR and NumPy result shapes — dicts, wrappers, ndarrays, legacy tuples —
  arrive before being normalized into `OCRResult`, `Quad`, and `Point`.
  Tightening it now would need casts or Paddle-specific types leaking toward
  Hanly contracts, so it is intentional adapter-level technical debt rather than
  a defect. *Revisit at the post-V1 typing review, or sooner if PaddleOCR ships
  type information; the test of a good outcome is narrower types at the seam
  without Paddle types crossing it.*
- **Relative `ResourceSpec.version_file` and `path` semantics.** Both are only
  `expanduser()`-ed, so a relative value resolves against the process working
  directory. The two fields are at least consistent with each other, and no
  manifest base directory or resource-root concept exists in the architecture
  yet, so no base path was invented here. *Revisit when real resource packaging
  and on-disk layout are available — decide then whether relative entries are
  resolved from a manifest root, the resource directory, or are rejected
  outright.*

### Dismissed

- **Kiwi lemma correctness.** Raised on inspection because `kiwipiepy.Token`
  looked like it exposed no lemma, which would have made verb lookups fail.
  Checked against the real library: `Token.lemma` exists, the provider reads it,
  and `읽` correctly yields `읽다`. Not a defect.
- **`Quad` winding enforcement** (carried from the HAN-2/3 handoff).
  `WordResolver._contains` uses ray casting with an explicit boundary pass,
  which is winding-independent, so the earlier revisit trigger is satisfied
  without enforcing corner order.

## Review assignment

Human-selected. Review completed 2026-08-20 — see the Post-Bundle Review Outcome above.
