# Concrete Hanly V1 Runtime Review Handoff

## Bundle

- Member issue: HAN-15
- Implementation ecosystem: GPT — Sol orchestrator with direct Luna xhigh workers
- Date: 2026-08-20

## Implemented

- An additive `hanly_app.runtime` composition root beside the existing
  generic factory-injection seam.
- JSON runtime-configuration loading with strict required Paddle detection,
  recognition, and KRDICT resources.
- Manifest-directory-relative `ResourceManager` semantics for resource paths
  and version files; relative values without an explicit base are rejected.
- ResourceManager-validated Paddle model directories, model-name
  configuration, and KRDICT database path supplied explicitly to the current
  concrete providers.
- Worker-owned factories for `PaddleOCRProvider`, `KiwiProvider`, and
  `KRDICTProvider`, routed through the existing `LookupWorker`, `JobExecutor`,
  `LookupPipeline`, and `LookupController` path.
- A repository-owned `tools/dev_lookup.py` rig that loads an image through
  Pillow, performs one bounded controller lookup, stops the runtime, and emits
  the normalized result, context, error, and diagnostics as JSON.
- Optional concrete-runtime dependency extras, keeping the base engine and
  lightweight CI path free of Paddle and Kiwi installations.
- A small committed KRDICT-shaped Korean source subset and documented build to
  a gitignored SQLite development artifact.
- A canonical relative-path runtime manifest with paired Paddle model names and
  directories. `enable_mkldnn=false` is an explicit development-manifest
  setting, not a shipped provider default.

## Main expected behavior

Loading a valid runtime manifest validates every declared local resource before
composition. Starting the returned controller constructs PaddleOCR, Kiwi, and
KRDICT only on its executor thread; lookup uses the existing pipeline; stopping
the controller closes the worker-owned KRDICT connection on that same thread.
Neither `ResourceManager` nor the providers acquire a dependency on the other.

The official harness can run fully offline after the named Paddle model
directories and generated KRDICT database exist locally. It does not reproduce
OCR, morphology, or dictionary stage sequencing.

## Architecture / seams touched

- Generic `hanly_app.composition` factory seam: retained unchanged.
- Application composition root: `hanly_app.runtime`.
- Runtime lifecycle: `LookupController -> JobExecutor -> LookupWorker -> LookupPipeline`.
- Local resource boundary: `ResourceManifest -> ResourceManager -> validated path/configuration`.
- Development I/O only: Pillow image loading and JSON result serialization in
  `tools/dev_lookup.py`.
- Engine-to-app dependency direction remains one way: `hanly-app -> hanly`.

## Relevant files / diff areas

- `packages/hanly/src/hanly/resource_manager.py`
- `packages/hanly/pyproject.toml`
- `packages/hanly-app/src/hanly_app/runtime.py`
- `tools/dev_lookup.py`
- `packages/hanly-app/src/hanly_app/__init__.py`
- `packages/hanly-app/pyproject.toml`
- `packages/hanly-app/README.md`
- `resources/dev/runtime.json`
- `resources/dev/krdict/krdict-mini.xml`
- `tests/test_resource_manager.py`
- `tests/test_runtime.py`
- `tests/test_dev_lookup.py`
- `.gitignore`

## Implementation-side validation already run

- Focused ResourceManager checks: 10 passed; focused Ruff and mypy clean.
- Focused concrete composition/integration checks: 23 passed; focused Ruff and
  mypy clean.
- Focused development-harness checks: 20 passed; focused Ruff and mypy clean.
- Bundle gates after convergence: **160 passed, Ruff clean, mypy clean across 41
  source files**.

### Real offline provider/controller evidence

The official harness was run with:

- image: `tests/hanly_fixtures/assets/korean_reading_roi.png`
- target: `(40, 25)` in ROI-local pixels
- detection model: `C:\Users\Thiago\.paddlex\official_models\PP-OCRv5_mobile_det`
- recognition model: `C:\Users\Thiago\.paddlex\official_models\korean_PP-OCRv5_mobile_rec`
- dictionary: generated `resources/dev/krdict/krdict.sqlite3`
- PaddleX source check disabled for the offline development run through
  `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`

Observed normalized result:

- status: `SUCCESS`
- OCR: `책을 읽습니다.` at confidence `0.9820699691772461`
- resolved/lookup lemma: `책`
- KRDICT entry: `책` / `book` / `명사`
- error: none

The result travelled through `LookupController` and the current
`LookupPipeline`; no disposable stage-orchestration script was used.

## Known limitations / intentionally unvalidated areas

- The committed KRDICT input is a deliberately small development subset, not a
  production KRDICT release. Resource fetching/updating remains HAN-24 work.
- The example manifest expects local model directories. The machine-specific
  manifest used for the real run is gitignored; no models or generated SQLite
  database are committed.
- Real evidence is Windows/Python 3.13 with PaddleOCR 3.7.0, PaddlePaddle 3.3.1,
  Kiwi 0.23.2, Pillow 12.3.0, and NumPy 2.3.5. Packaging and installer evidence
  remains downstream work.
- `enable_mkldnn=false` remains configurable and appears only in the
  development manifest because the known failure is machine-specific.
- Capture, popup, hotkey, hover, updater, installer, and resource-distribution
  behavior were not pulled into this bundle.

## Preserved V1 correctness issue

The target-point-to-token policy is intentionally unchanged. Real PaddleOCR
returns the fixture as one line-level region, and the current pipeline looks up
the first usable lemma. The official harness therefore surfaces this existing
diagnostic:

> Resolved segment '책을 읽습니다.' contains 5 usable lemmas; looked up the first
> ('책') because the target point selects a region rather than a token

This is not treated as a HAN-15 defect or solved by configuration. It remains a
required V1 correctness decision before HAN-19 can be considered functionally
complete.

## Suggested review targets

- Manifest-root path resolution and rejection of accidental process-CWD
  behavior.
- Model-name/directory pairing and passage of validated ResourceManager
  configuration into `PaddleOCRConfig`.
- Provider-factory deferral, especially KRDICT construction, lookup, and close
  on one worker thread.
- Absence of eager Paddle/PaddleOCR imports and preservation of the supported
  PaddleOCR-before-Paddle import path.
- Harness timeout, cleanup, normalized error/result serialization, and visible
  diagnostics.
- Optional dependency ranges and continued lightweight default install/CI path.
- Scope containment: no capture, popup, hotkey, updater, or target-token policy
  implementation.

## Post-Bundle Review Outcome

- Reviewer: Claude (Opus 5)
- Review ecosystem: Claude, reviewing a GPT-implemented bundle
- Date: 2026-08-21
- Status: Closed. The runtime works end to end against the real
  PaddleOCR/Kiwi/KRDICT stack. Two defects were found by running the code
  rather than reading it, and both are fixed with regression tests. A closeout
  pass then resolved three of the deferred items outright.

Gates after the readability pass: **163 passed, Ruff clean, mypy clean across 42
source files**, with the real offline run unchanged at
`SUCCESS | 책을 읽습니다. | 0.98207 | 책 → book`.

### Verified by running it, not by inspection

The real offline harness run reproduces exactly as the bundle claims, both
before and after the fixes below:

```text
status SUCCESS | ocr 책을 읽습니다. | conf 0.9820699691772461 | entry 책 ['book']
```

That single run is also the proof for the SQLite thread-affinity claim: the
KRDICT connection is constructed, queried, and closed on the executor thread,
and a real cross-thread close would have raised `sqlite3.ProgrammingError`
during `stop()`. It did not.

Import cost was measured, not assumed. After importing `hanly_app`,
`hanly_app.runtime`, and `tools.dev_lookup`, the only heavy
module present in `sys.modules` is stdlib `sqlite3`; `paddle`, `paddleocr`,
`paddlex`, `kiwipiepy`, and `PIL` are all absent. The lazy-import claim holds.

The 35 `PermissionError: [WinError 5]` errors seen on a bare `python -m pytest`
here are the known local `pytest-of-Thiago` ACL problem on this machine, not a
bundle defect. With `--basetemp` pointed elsewhere the suite is green.

### Fixed now

- **`paddle.extra_options` could override a ResourceManager-validated model
  path, defeating the exact invariant this bundle exists to enforce.**
  `PaddleOCRConfig.to_engine_kwargs` applies `extra_options` *last*, so a
  manifest could route an arbitrary unvalidated directory straight to
  PaddleOCR. Confirmed empirically before the fix:

  ```text
  validated  : ...\models\det
  to Paddle  : C:/totally/unvalidated/path
  BYPASS: True
  ```

  `_paddle_config` now rejects any `extra_options` key that collides with an
  explicit paddle field. Unknown keys still pass through, which is deliberate —
  that is how `enable_mkldnn` and `cpu_threads` reach the library. Two
  regression tests cover both halves.

- **The development harness's `--timeout` did not bound anything.** On timeout
  the `finally` block called `controller.stop()`, whose default `wait=True`
  joins the executor thread that is still inside the unfinished stage. Measured
  against a worker hung for 20 s with a 1 s timeout, the harness did not return
  within 6 s. It now stops without waiting on the timeout path only — the
  successful path still joins normally — and returns in 1.0 s with
  `DevelopmentHarnessTimeout`. The existing timeout test passed throughout
  because its controller double returns immediately from `stop()`; the double
  now records the `wait` flag and both paths are asserted.

### Fixed in the closeout pass

- **`ResourceManager.validate()` no longer raises for anything.** The deferred
  finding below was resolved rather than carried: the contract already drew the
  line, and only the timing was wrong. `ResourceSpec.__post_init__` and
  `ResourceManifest.__init__` already refuse malformed input at construction,
  while every resource health problem inside `validate()` — missing, unreadable,
  wrong kind, bad schema, failed checksum, incompatible version — is caught and
  turned into status plus diagnostics. A base-less relative path is malformed
  input, so it is now rejected in `ResourceManager.__init__`, naming every
  offending resource and field at once, instead of aborting a scan part-way
  through. The in-scan guard stays as an unreachable net against the CWD
  fallback reappearing. The two categories are now stated on the class docstring
  and on `validate()`.

  Two focused tests cover the split: one asserts construction refuses the
  manifest and names all offenders, the other asserts a manifest mixing a valid
  resource with a missing one, a wrong-kind one, and a bad-checksum one reports
  four distinct statuses and raises nothing.

- **The `hanly` extras now have one source of pins.** `concrete` was a verbatim
  third copy of the ranges in `paddle` and `kiwi`; it is now
  `["hanly[paddle]", "hanly[kiwi]"]`. Installation semantics were verified
  unchanged with `pip install --dry-run`: base `hanly` still resolves to no
  dependencies at all, `hanly[kiwi]` still pulls no Paddle, and
  `hanly[concrete]` still resolves paddleocr, paddlepaddle, numpy, and
  kiwipiepy. The base install stays light and CI is untouched.

- **One unused alias removed.** `LookupController.submit_lookup = submit` had
  zero references anywhere in `packages`, `tests`, `tools`, or the docs, so it
  went with no consumer impact. `shutdown` and `close` were checked and kept —
  `shutdown` is required by the `LookupRuntime` protocol in
  `desktop_controller`, and both are genuinely used. The broader API cleanup
  stays deferred; this was not one.

### Deferred considerations

- **The extra *set* is still provisional even though its pins are now single
  source.** Whether `paddle` / `kiwi` / `concrete` is the right split, and
  whether `hanly-app`'s `runtime` / `dev` pair survives, depends on how the
  application is actually distributed. *Revisit when packaging and installer
  work (HAN-24 onward) makes the real install shapes concrete; do not let the
  base `hanly` install acquire dependencies in the meantime.*
- **Alias proliferation from earlier bundles.** `shutdown = stop`,
  `close = stop`, the `build_*` / `create_*` pairs in `composition`, and the
  `ResourceManager` accessor duplication all still have real consumers, so none
  is a zero-impact deletion. *Stays grouped with the existing API-surface item
  for the V1 deferred sweep.*
- **A typo'd or aliased paddle key surfaces only at provider construction.** The
  manifest forwards it, and PaddleOCR raises `ValueError: Unknown argument:
  enable_mkldn`, or reports that `det_model_dir` and `text_detection_model_dir`
  are mutually exclusive, when the worker builds. Loud, but late — after the
  runtime has started. *Revisit only if manifest authoring becomes user-facing;
  a fixed allowlist in the manifest would have to track PaddleOCR's kwargs.*

### Dismissed

- **Manifest-root path resolution.** Verified with a monkeypatched process CWD
  containing decoy files: relative paths resolve from the manifest directory,
  and a base-less relative path is rejected instead of silently reading the
  wrong file. No defect.
- **Model-name/directory pairing.** The pairing is enforced in three
  independent places — `_configured_model_dir` requires both and checks the dir
  against the declared resource path, `ResourceManager` carries the name as
  validated configuration, and `PaddleOCRConfig.__post_init__` rejects a
  directory without its name. Correct, and it is the fix for the PaddleOCR 3.7
  failure it was written for.
- **Unknown-key passthrough as a silent-misconfiguration risk.** Tested against
  the real library rather than reasoned about: PaddleOCR rejects both unknown
  kwargs and alias collisions. Recorded above as a *timing* concern only.
- **Provider deferral and worker ownership.** No provider is constructed in
  `load_runtime`; the lambdas close over validated values and run on
  the executor thread. Proven by the unit test's thread-identity assertions and
  by the real run.
- **`ResourceManager` / provider independence.** Providers take explicit paths
  and configuration; neither imports the other. The `CA-INV` direction holds,
  and `hanly` still never imports `hanly-app`.
- **Scope containment.** No capture, popup, hotkey, hover, updater, installer,
  or target-token policy code appears in the diff. `enable_mkldnn=false` lives
  only in the development manifest, and a test asserts it is omitted when the
  manifest does not set it.
- **No machine-specific data committed.** `resources/dev/runtime-local.json`,
  `resources/dev/models/`, and `resources/dev/krdict/*.sqlite3` are all
  gitignored; only the example manifest and the small Korean source subset are
  tracked.

### Preserved V1 correctness issue

The target-point-to-token issue is unchanged and now has its most direct
evidence yet — the official harness surfaces it on every real run:

> Resolved segment '책을 읽습니다.' contains 5 usable lemmas; looked up the first
> ('책') because the target point selects a region rather than a token

Confirmed still owned by HAN-19 and recorded in
`engine-convergence-han-12-13.md`. This review neither changes nor obscures it.

The UI-thread shutdown issue raised on the HAN-14 handoff is also untouched and
remains owned by HAN-17. The development rig calls `stop()` from its own main
thread with the default direct dispatcher, so it does not exercise that path and
does not pre-empt the lifecycle decision — the timeout fix above changes only
`wait`, not who stops whom.

### Naming and layout, applied after the review

Human-directed, on reading the bundle: the implementation had taken its names
from planning vocabulary rather than from what the code does.

- **`hanly_app.concrete_runtime` → `hanly_app.runtime`.** "Concrete" was a
  contrast word from the DAG node *Concrete Hanly V1 Engine Integration*, where
  it distinguished this from the abstract factory seam in `composition.py`. That
  contrast is meaningful in a plan and meaningless in a filename. With it:
  `ConcreteRuntime` → `HanlyRuntime`, `ConcreteRuntimeError` →
  `RuntimeConfigError`, `load_concrete_runtime` → `load_runtime`, and
  `tests/test_concrete_runtime.py` → `tests/test_runtime.py`.
- **"Manifest" → "runtime config" at this boundary.** The word suggested a web
  app manifest. `resources/dev/runtime-manifest.json` → `resources/dev/runtime.json`,
  the parameter is `config_path`, and the CLI flag is `--config`. The engine's
  own `ResourceManifest` keeps its name — it is a genuine inventory of resources
  and is a different thing.
- **The development rig left the shipped package.** `hanly_app.dev_harness` →
  `tools/dev_lookup.py` at the repository root, with `tools/README.md` carrying
  the instructions that were in the `hanly-app` README. Nothing in either
  package imports it, and it is a manual test rig rather than product code, so
  it no longer installs with the application. The `hanly-dev-lookup` console
  script is gone; the rig runs as `python tools/dev_lookup.py`. Names followed:
  `DevelopmentHarnessError` → `DevLookupError`, `DevelopmentHarnessTimeout` →
  `DevLookupTimeout`, `run_development_lookup` → `run_dev_lookup`.
- **All five duplicate aliases deleted** rather than deferred, since the rename
  was the moment to do it: `build_worker_factory`, `build_lookup_controller`,
  `build_concrete_runtime`, `build_concrete_lookup_controller`, and
  `load_runtime_manifest`. Every function now has exactly one name. The
  `submit_lookup`/`shutdown`/`close` and `ResourceManager` accessor duplication
  from earlier bundles is untouched and stays on the deferred sweep.
- **The identical `runtime` / `dev` extras now differ meaningfully.** `runtime`
  is what the application needs (`hanly[concrete]`); `dev` is `runtime` plus
  Pillow, which only `tools/` uses.

`tools/` is covered by Ruff and mypy, and pytest gets `pythonpath = ["."]` so
the suite can import it as `tools.dev_lookup`.

Verified after the rename: **162 passed, Ruff clean, mypy clean across 42 source
files**, and the real offline run is unchanged —
`status SUCCESS | 책을 읽습니다. | 0.98207 | 책 → book`.

### Readability cleanup, applied after the closeout

Human-directed, scoped to readability only. No architecture, no API renames, no
behavior change.

- **`_resource_specs` split into named phases.** The loop was one dense block
  doing normalization, field validation, kind resolution, path handling,
  configuration merging, and construction. It now reads as phases backed by four
  helpers — `_resource_fields`, `_resource_kind`, `_resource_path_field`, and
  `_resource_configuration` — with the allowed-field set lifted to a module
  constant.

  Behavior was held fixed by characterization rather than by inspection: 38
  cases covering every success shape, every rejection, and seven multi-error
  inputs that pin which phase rejects first were captured from the original
  function and re-run against the refactored one. **0 differences**, including
  exact error-message text and precedence. One latent typing hole surfaced and
  was closed — the required-path branch previously returned `Path | None` into a
  field typed `str | PathLike[str]`.

- **Provider factories untouched.** `lambda: PaddleOCRProvider(...)`,
  `KiwiProvider`, and `lambda: KRDICTProvider(...)` are unchanged; KRDICT stays
  worker-owned because its SQLite connection is thread-affine.

- **Comments and docstrings reduced where they narrated code, kept where they
  carry "why".** The `runtime` module docstring dropped from 15 lines to 10 but
  still states the thread-ownership and lazy-import reasons; the deferred
  construction comment went from three lines to two; the `extra_options`
  comment from five to three. `tools/dev_lookup.py`'s module docstring dropped
  from 18 lines to 5, pointing at `tools/README.md` for usage, and the shutdown
  comment shortened to two lines that keep the invariant: joining a timed-out
  worker would make the bounded wait unbounded.

- **`tools/dev_lookup.py` stays.** It is an intentional development and
  debugging tool, not scheduled for deletion.

- **`CLAUDE.md` gained a short "Readability and comments" section** covering
  blank lines as phase markers, preferring a few named helpers over dense
  functions, comment length and purpose, docstrings as contracts, and keeping
  operational prose in docs or READMEs. The documented gate commands were also
  corrected to include `tools`.

No new deferred items came out of this pass.

### Open layout question, not addressed here

Every module currently sits flat in `packages/hanly/src/hanly/` and
`packages/hanly-app/src/hanly_app/`. Moving the rig to `tools/` is the first
split, not the plan. A real grouping pass — providers, contracts, desktop
integration, UI — is worth doing once the desktop capabilities exist and the
natural seams are visible, rather than guessing them now. *Recorded for the V1
deferred sweep; no issue created.*

### Next bundle

Nothing in this review blocks the next implementation bundle. The runtime is
real, runs offline, and is now protected against the one way a configuration
file could route around resource validation.

Both previously owned V1 issues are unchanged and were neither duplicated nor
solved here: target-point-to-token remains required before HAN-19 can be
considered functionally complete, and the UI-thread shutdown decision remains
owned by HAN-17. HAN-15 is closed.

## Review assignment

Human-selected. Review completed 2026-08-21 — see the Post-Bundle Review Outcome above.
