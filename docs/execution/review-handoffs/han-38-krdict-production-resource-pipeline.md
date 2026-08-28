# HAN-38 KRDICT Production Resource Pipeline Review Handoff

Date: 2026-08-25  
Implementation status: **complete and technically ready for human review; no release mutation performed**

1. **Linear issue:** HAN-38 — KRDICT Production Database & Resource Pipeline.

2. **Implementation plan:** `docs/execution/HAN-38-krdict-production-database-resource-pipeline-plan.md`. It records the full-source discovery that raw KRDICT `LexicalEntry` IDs are reused and the approved correction.

3. **Files changed/moved:** Added `tools/krdict/` (`source.py`, `inspect.py`, `schema.sql`, `build_seed.py`, `validate_seed.py`, `package_resource.py`), `packages/hanly/src/hanly/krdict_schema.py`, `.github/workflows/build-krdict-resource.yml`, `data/README.md`, shared normalized fixtures, and focused `tests/krdict/` coverage. Relocated inspector coverage from `tests/test_inspect_krdict.py` to `tests/krdict/test_inspect.py`, then removed the obsolete `tools/inspect_krdict.py` entry point. Updated KRDICT provider/build/resource manager, app update/bootstrap/coordinator/application seams, release workflow/producer manifest wiring, developer resources/docs, Zstandard dependencies, and affected tests/configuration.

4. **Final schema:** Eleven normalized tables: `entries`, `lemmas`, `senses`, `translations`, `examples`, `word_forms`, `categories`, `related_forms`, `syntactic_patterns`, `sense_relations`, and `resource_metadata`. `entries.id INTEGER PRIMARY KEY` is the sole entry identity; raw `(source, source_id)` is intentionally non-unique. Child FKs use internal `entry_id`/`sense_id` only. Raw relation `target_source_id` values are not FKs. No occurrence or synthetic external identity was added.

5. **Exact real build command:**

   ```powershell
   .venv\Scripts\python.exe tools\krdict\build_seed.py "data\source\전체 내려받기_한국어기초사전_xml_20260819.zip" --output data\generated\krdict.sqlite3 --source-date 2026-08-19 --resource-version 20260819-v1 --build-date 2026-08-25
   ```

   The corrected full build completed in 36.591 seconds.

6. **Official source:** `전체 내려받기_한국어기초사전_xml_20260819.zip`, source date `2026-08-19`, 11 XML members, SHA-256 `266e50d1ad10b6b6ae8c0e9f7244a9df129f32069e599b5d652ccaa5db7110fe`. The archive was not modified.

7. **Source scan:** 56,555 `LexicalEntry` elements, 76,833 `Sense` elements, 75,145 English translations, and seven illegal `0x08` bytes replaced in memory only.

8. **Every table row count:** `entries` 56,555; `lemmas` 56,555; `senses` 76,833; `translations` 75,145; `examples` 657,968; `word_forms` 93,702; `categories` 50,891; `related_forms` 23,045; `syntactic_patterns` 28,008; `sense_relations` 32,790; `resource_metadata` 7.

9. **Indexes:** Nine explicit indexes were created after loading: `idx_entries_source_source_id` (non-unique), `idx_lemmas_written_form_entry`, `idx_lemmas_entry_id`, `idx_word_forms_written_form_entry`, `idx_word_forms_entry_id`, `idx_translations_sense_language`, `idx_categories_entry_id`, `idx_related_forms_entry_id`, and `idx_sense_relations_sense_id`.

10. **ANALYZE:** Completed after index creation; validation found 14 `sqlite_stat1` rows.

11. **SQLite size:** 92,508,160 bytes (`data/generated/krdict.sqlite3`, local and gitignored).

12. **Zstandard size:** 27,352,629 bytes (`data/generated/krdict-20260819-v1.sqlite3.zst`, local and gitignored).

13. **Compression ratio:** `0.2956780137017102` (29.57% of the SQLite size).

14. **Distributed asset SHA-256:** `62748d8a37dab9bc3c551672cf4cebde3ea7dc1abb6f5f404e11e99db64b9ab9`.

15. **Resource identity:** schema version `1`, resource version `20260819-v1`, asset `krdict-20260819-v1.sqlite3.zst`, source date `2026-08-19`, advertised entry count 56,555. The producer manifest carries checksum, compressed size, schema version, expected entry count, source date, kind, version, and asset name.

16. **Production validation:** Completed in 29.914 seconds. `PRAGMA integrity_check = ok`; foreign-key violations `0`; source/database entry, sense, and English-translation counts match; all eleven tables, seven metadata rows, nine indexes, primary lemmas, schema/user version, and analyzed statistics pass. Duplicate raw source IDs are reported as valid source data: 53,671 distinct IDs, 1,160 reused IDs, maximum reuse 86.

17. **Query plans/timings:** Primary lemma uses covering `idx_lemmas_written_form_entry` (0.061 ms average); word form uses covering `idx_word_forms_written_form_entry` (0.065 ms); raw source-ID candidates use covering `idx_entries_source_source_id` (0.060 ms); entry senses use covering `sqlite_autoindex_senses_2` (0.061 ms); English translations use `idx_translations_sense_language` (0.063 ms); first example uses `sqlite_autoindex_examples_1` (0.060 ms).

18. **Hardcoded real records:** Literal raw-source expectations cover `가` (source ID 27733, two senses, translations, phrases/sentences/dialogue), `첨성대` (600265), conjugation/category/pattern-rich `첨예하다` (77500), `첨예화` RelatedForm (77504), and `첩` SenseRelation including camelCase `homonymNumber` zero (77519). Regression ID `77610` proves all four distinct entries sharing the raw ID are preserved.

19. **OCR → Kiwi → DB:** A deterministic OCR result (`책을 읽습니다.`) passed through real Kiwi and the production database to exact `읽다` metadata and all nine English definitions. The committed PNG fixture also passed through real EasyOCR 1.7.2, real Kiwi 0.23.2, and production KRDICT in the supported local environment. Combined real-record/pipeline run: 7 passed; only upstream Torch deprecation/CPU pin-memory warnings were emitted.

20. **First-run/resource/update coverage:** Missing-resource provisioning, healthy startup, optional availability checks, six user-facing phases, compressed-size/checksum-before-decompression, corrupt Zstandard/SQLite, schema/count/source-date mismatches, staging cleanup, atomic activation, previous-resource preservation, rollback, runtime teardown/rebuild bracketing, and persisted installed versions are covered. Focused HAN-38/resource group passed 121 tests with one opt-in integration skip; the explicit integration run passed separately.

21. **Repository gates:** `.venv\Scripts\python.exe -m pytest` → 616 passed, 1 opt-in EasyOCR test skipped in 20.65 seconds. `.venv\Scripts\python.exe -m ruff check packages packaging tests tools benchmarks` → all checks passed. `.venv\Scripts\python.exe -m mypy packages packaging tests tools benchmarks` → success in 142 source files. `git diff --check` passed; output contained only expected LF/CRLF conversion notices.

22. **GitHub Actions producer:** Added a manual, read-only `build-krdict-resource.yml` accepting an explicit HTTPS `source_url` and SHA-256. It downloads and verifies the source in the runner, then builds, validates, packages, and uploads only the `.sqlite3.zst`, producer manifest, and validation report; the source is neither committed nor uploaded. It cannot publish. `release.yml` remains manual/human-gated and now consumes exactly one canonical KRDICT Zstandard asset plus the producer manifest, with no Paddle resource reactivation. All workflow YAML and structural contract tests pass.

23. **Real-source irregularities:** Raw source IDs are reused (including ID 77610; maximum reuse 86), so `(source, source_id)` cannot be unique. Seven `0x08` bytes require streaming sanitization. Relation metadata uses both `homonym_number` and camelCase `homonymNumber`; the parser normalizes both while preserving explicit zero. Raw relation targets remain ambiguous external references when multiple entries share an ID.

24. **Upload readiness:** Yes. The resource is technically ready to be uploaded as a GitHub Release asset with its producer manifest. Actual workflow dispatch, tag, and release publication still require explicit human authorization.

25. **Mutation confirmation:** No commit, push, merge, tag, release, or workflow dispatch was performed. Generated/source/report artifacts remain gitignored. Pre-existing unrelated dirty-tree work (including HAN-35, `.claude/`, benchmark, capture-overlay/HUD files) was preserved.

## Review focus

- Confirm the non-unique external source-ID contract and internal-only FK identity are maintained end to end.
- Inspect producer-to-release manifest/asset wiring and the checksum-before-decompression/atomic activation boundary.
- Verify optional update version persistence occurs before runtime reload and that first-run failures preserve the last valid resource.
- Compare literal real-record expectations to the official XML rather than deriving expected values from production parser code.

## Deep review — 2026-08-26

Verdict: the pipeline is correct and ready to ship. Seven defects were fixed,
the tooling was simplified, and the whole producer path was re-run end to end.

### Reproduction evidence

The full production pipeline was re-executed after every change:

- `build_seed.py` on the official ZIP: 32.3 s, 56,555 entries, identical row
  counts, SHA-256 `f0d179d0a8679c833b706b50e9850419fab9b0d824c365bd5171b8c2185ef7d7`
  — byte-identical to the database this handoff describes.
- `validate_seed.py`: all checks pass with the same counts, indexes, plans, and
  reuse statistics (53,671 distinct source IDs, 1,160 reused, maximum 86).
- `package_resource.py`: asset SHA-256
  `62748d8a37dab9bc3c551672cf4cebde3ea7dc1abb6f5f404e11e99db64b9ab9` — identical
  to item 14 above.
- Entry `600265` was transcribed independently from the raw XML member and
  matches the literal test expectation exactly, trailing definition space and
  English-only `Equivalent` filtering included.
- Live provider spot checks on the production database: `읽다`, `책`, `하다`
  resolve in 2–4 ms; the word-form path resolves `먹어` to `먹다`.
- `load_runtime` reports `all_valid` against a freshly built database when given
  an explicit runtime configuration path.
- Gates: `pytest` 615 passed / 1 skipped, `ruff` clean, `mypy` clean
  (139 files, three files fewer than before).

### Fixed now

1. **The engine imported repository tooling.** `hanly/krdict_build.py` imported
   `tools.krdict.build_seed`, which does not exist in any `hanly` wheel, so the
   independently distributable engine had a broken public function. The facade
   is deleted; test fixtures build through `tools.krdict` directly, and
   `test_package_boundary.py` now fails on any `tools` import inside the engine,
   not just `hanly_app`.
2. **A blocking, discarded network call on every healthy launch.**
   `provision_runtime_config` ran `UpdateService(...).check_for_updates()`,
   threw the result away, and swallowed errors — costing a GitHub round trip
   plus a full resource re-validation (4.5 s cold on the 92 MB database) before
   the window appears. `UpdateCoordinator` already performs the same check
   asynchronously, so the call is removed and the docstring's original promise
   restored.
3. **Cross-module private import.** `application.py` imported
   `_persist_resource_version`; it is now `persist_resource_version`.
4. **Dead configuration field.** `SchemaSpec.metadata_table` was added and then
   made unreachable by the `schema is KRDICT_SCHEMA` early return in
   `_validate_schema`. The field is gone, and `KRDICT_SCHEMA` is reduced to its
   name and version — `krdict_schema.validate_krdict_connection` owns the
   contract in one place instead of two.
5. **`KRDICT_SCHEMA_MARKER` was dead** after the normalized schema replaced the
   two-table format. Removed.
6. **The old developer configurations could never validate.** The former
   mini-fixture configs pinned `"version": "development"` while their builder
   wrote `resource_version = "development-v1"`, so the old explicit launch
   path failed with `krdict is outdated`. The EasyOCR-only cleanup removed those
   configs, the mini XML builder, and their dedicated test; normal startup now
   provisions the production database, while machine-local explicit configs are
   documented separately.
7. **`tools/inspect_krdict.py` could not run as a script** (`from
   tools.krdict.inspect import main` with `tools/` first on `sys.path`), was
   untested, and was referenced by nothing. Deleted.

### Simplified (behavior preserved)

- `_insert_entry` collapsed from ten hand-written INSERT blocks to one SQL
  statement table plus an `_insert_children` helper that assigns the same
  deterministic primary keys. Proven equivalent by the byte-identical rebuild.
- The eight-line `sys.path` bootstrap, duplicated in four CLIs, is three lines
  each and now states *why* it exists (`tools/krdict/inspect.py` shadows the
  standard library `inspect`).
- `_configure_utf8_output`, duplicated in three CLIs, is now
  `tools.krdict.configure_utf8_output`.
- Three `# noqa: E402` comments were dead — ruff does not emit E402 after a
  `sys.path` edit. Removed.
- `KRDICTSource` tracked sanitized bytes through delta arithmetic; it now keeps
  one per-member base and still reports accurate counts mid-iteration.
- `_children` matched element names through the *attribute* normalizer, which
  also strips underscores; it now uses `_name`, like the values it compares.
- The release path now consumes the manifest emitted by
  `tools/krdict/package_resource.py`, keeping producer metadata in one place.
- `RemoteManifest.from_payload`'s optional-integer loop is an `_optional_integer`
  helper, and `_is_zstd_resource` is evaluated once per install.
- `validate_seed` dropped the `functools.partial` / `_execute_all` indirection.
- `tests/krdict/test_real_records.py` replaced four misindented inline
  comprehensions per record with a `_rows` helper.
- The official source misspells `subjectCategiory` (63 occurrences, verified);
  a one-line comment now says so, since the code looks like a typo.

### Deferred — needs a human decision

- **Startup validation costs ~4.5 s cold on the 92 MB resource**, dominated by
  `PRAGMA quick_check` reading the entire file (3.73 s measured);
  `validate_krdict_connection` adds 0.25 s, the new `PRAGMA foreign_key_check`
  0.13 s, and the unpinned SHA-256 of the whole database 0.19 s. This is
  pre-existing logic that only became expensive when the resource grew from a
  fixture to a real dictionary, and it still runs on every launch (bootstrap
  and `load_runtime`). Revisit when startup latency is measured: the deep check
  belongs on the first launch after an install, not on every start.
- **Staged KRDICT installs validate twice** — `ResourceManager._validate_schema`
  calls `validate_krdict_connection`, then `_validate_staged` calls it again to
  apply the manifest's entry count and version. Threading the expectations
  through the first call would halve it. Revisit with the item above.
- **`_decompress_zstd` has no output bound.** The checksum is verified before
  decompression, so a bomb requires a compromised release manifest, but a
  `max_output_size` derived from the frame content size would close it.
- **The former release-manifest tool and dedicated test were orphaned.** They
  were removed; `package_resource.py` is the single producer-manifest writer,
  and `tests/krdict/test_package_resource.py` plus workflow and
  `RemoteManifest` compatibility coverage exercise the consumer contract.
- **`tools/krdict/inspect.py` imports six private names from `source.py`**, and
  its `SubjectField/subject` probe never matches the official source, so
  `category` is always null in compact output. Cosmetic for a developer tool.
- **A `record_install` failure is reported as an install failure** even though
  the resource is already activated. The version self-heals from schema
  metadata on the next validation, so the window is narrow.
- **Real-record and real-pipeline tests only run locally**, since the database
  is gitignored. `HANLY_REQUIRE_REAL_KRDICT=1` turns the skip into a failure;
  they pass locally against the production database.

### Dismissed

- `subjectCategiory` is not a bug — it is the official source's spelling.
- `(source, source_id)` non-uniqueness is honored end to end: the index is
  non-unique, every child FK uses internal ids, the validator compares database
  multiplicities against the source scan, and entry 77610 is a literal
  regression.
- Version persistence ordering is correct: `record_install` runs before
  `after_install` rebuilds the runtime.
- No release mutation was performed during this review. The generated artifacts
  written during reproduction live in the session scratchpad, not in `data/`.

## PaddleOCR removal and normal-run wiring — 2026-08-26

Directed by the human after the review above: EasyOCR is the only OCR backend,
`hanly run` must work like a normal launch, and the mini XML dictionary is gone.
Same logic, same architecture, less of it.

### The defect that started it

The former explicit development configuration returned only `책` and `읽다`
because it pointed at the two-entry mini fixture rather than the 56,555-entry
production database. That development configuration was never wired to the real
resource, so every lookup outside the fixture legitimately missed; the config
and mini fixture have since been removed.

### `hanly run` now provisions the real dictionary

`provision_runtime_config` installs KRDICT from an already-built local database
before it considers the release channel: `HANLY_KRDICT_DB`, or
`data/generated/krdict.sqlite3` when running from a source checkout. It does this
through a `ResourceFetcher` that serves the file, so staging, checksum
verification, schema validation, atomic activation, and version recording remain
exactly the code that a real download runs. No new install path was added.

A configuration written before this change still declares two Paddle model
directories, and every declared resource must be valid to start. Bootstrap now
drops those declarations (and the `paddle` / `ocr_backend` keys) from an existing
manifest, so an installed user launches without hand-editing JSON.

Measured on this machine: first run provisions in 3.3 s and installs the real
56,555-entry database; later launches validate in 4.7 s (see the deferred
`quick_check` item above) and `load_runtime` reports `all_valid`. Real vocabulary
resolves through Kiwi and KRDICT — 컴퓨터, 학교, 아름답다, 친구, 책, 읽다.

### PaddleOCR removed

Deleted: `hanly/paddleocr_provider.py`, `tests/test_paddleocr_provider.py`,
`resources/dev/runtime.json`, `resources/dev/runtime-easyocr.json`,
`resources/dev/krdict/krdict-mini.xml`, `tools/dev_alpha.py`,
`tools/dev_resources.py`, `tests/test_dev_alpha.py`.

Collapsed to one backend: the `OCRBackend` enum, `read_ocr_backend`, the
`ocr_backend` configuration key, `require_paddle_config`, `_ocr_factories`,
`_PADDLE_FIELDS`, `_paddle_config`, `_validated_paddle_config`,
`_configured_model_dir`, `_model_name`, and the model-root layout check are gone
from `runtime.py` (856 → 507 lines). `_resource_specs` no longer threads
`required_kinds`/`required_configurations` that only ever carried Paddle values.

The Paddle-only recognition-first hover fast path is gone from `composition.py`
(1073 → 860 lines): `TextRecognitionProvider`, `_PreparedOCRProvider`,
`_TracingTextRecognitionProvider`, `_crop_hover_roi`, `_HoverCrop`,
`_is_clear_hangul_token`, `_hover_lookup`, and the second pipeline it fed. Hover
and manual lookups now share the one `OCRProvider` seam.

`REQUIRED_RESOURCE_IDS` is `("krdict",)`, `RESOURCE_KINDS` names one resource,
the two managed model resources are gone from the release and packaging paths,
`DEFAULT_OCR_RUNTIME_MODULE` and `OCR_RUNTIME_MODULE` collapsed into one
constant, and `select_capture_area` no longer takes a backend to prepare.
Benchmarks, the PyInstaller spec, the runtime hook, the mypy overrides, and the
engine's optional dependency extra all name EasyOCR now.

### The developer rig is gone

`tools/dev_alpha.py` and `tools/dev_resources.py` existed to build the mini
dictionary and discover Paddle model directories. Both jobs are obsolete:
`hanly run` is the way to run the desktop, and `resources/dev/` is
benchmark-only configuration. `tools/dev_lookup.py` stays as the engine-only
lookup rig; `tools/README.md` was rewritten around the two commands that remain.

### Verification

- `pytest` 570 passed, 1 skipped; `ruff` clean; `mypy` clean over 134 source
  files (142 before this session's work).
- Ten files deleted; the tracked diff is +1,100 / −4,193 lines.
- The real startup path was exercised end to end against the user's own
  `%LOCALAPPDATA%/Hanly/runtime.json`: the stale Paddle manifest migrated, the
  production database installed, `load_runtime` reported `all_valid`, and
  `preload_ocr_runtime()` imported EasyOCR successfully.

### Follow-ups this created

- Authoritative architecture Markdown, synchronized HTML companions, and the
  2026-08-24 decision record now consistently identify EasyOCR as V1's only
  backend; historical Paddle text is marked superseded.
- An installed user whose configuration names `"ocr_backend": "paddle"` is
  migrated to EasyOCR silently. That is the intended one-way migration, not a
  choice the application still offers.

## Final cleanup and corrections — 2026-08-26

- **Shared lookup gate:** The shared `LookupPipeline` owns the Hangul-only gate:
  resolved OCR text must contain Hangul and may otherwise contain only
  whitespace or punctuation before Kiwi or KRDICT runs. Hover and manual
  lookup use this same pipeline; there is no Paddle recognition-only side path.
- **Startup validation:** The startup-validation optimization was deliberately
  reverted for correctness. The measured roughly 4.8-second production scan
  and repeated-validation opportunity are deferred. Revisit only with
  production-sized timing evidence and tests proving that full schema,
  metadata/count, source-date, integrity, and foreign-key checks still run on
  first install, recovery, and every resource-identity change; any reuse is
  tied to a verified immutable resource identity rather than mtime alone; and
  checksum-before-decompression, atomic activation, rollback, last-known-good
  preservation, version persistence, and runtime teardown/rebuild ordering are
  unchanged.
- **Producer and removals:** The producer workflow was remade around HTTPS
  `source_url` plus SHA-256 verification; it neither commits nor uploads the
  source archive and uploads only reviewable generated outputs. The orphaned
  `tools/build_release_manifest.py` and `tests/test_release_manifest.py` were
  deleted; `tools/krdict/package_resource.py` is the single producer-manifest
  writer, with package-resource, workflow, and `RemoteManifest` compatibility
  coverage retained.
- **Documentation and scope:** Authoritative Paddle references are synchronized
  as historical/superseded, with EasyOCR-only current authority in `CLAUDE.md`
  and architecture `01`–`03`. HAN-35 benchmarks and tests were not mass-deleted;
  they are separate referenced work. `.claude/` is now ignored while the local
  settings file remains untouched. No commit, push, merge, tag, release
  publication, or workflow dispatch was performed.

### Final review deferred

These were not changed because the user narrowed this correction to Hangul-only
behavior and cleanup.

1. **Update progress vocabulary:** `UpdateCoordinator`/Control Center uses
   `verifying`/`installing` while the UI expects `validating`, which can hide
   real install progress. Revisit before exercising or accepting resource-update
   UI.
2. **Empty Zstandard frame cleanup:** An empty-but-valid Zstandard frame may
   bypass temporary output cleanup. Revisit in the next UpdateService/resource
   hardening pass before release validation.

## Handoff review and simplification — 2026-08-28

Reviewed the staged HAN-38 + EasyOCR diff, closed both of the "Final review
deferred" items, and cut the duplication the diff left behind. Gates after the
work: `pytest` 562 passed / 1 skipped, `ruff` clean, `mypy` clean over 134
source files. The real startup path was exercised end to end against
`%LOCALAPPDATA%/Hanly/runtime.json` (`all_valid`), and `읽다`, `책`, `컴퓨터`,
`먹어` → `먹다`, `아름답다` resolve against the production database.

### Fixed now

1. **Update progress was invisible for two of four phases.**
   `UpdateCoordinator._progress_message` labelled `validating`, a phase
   `UpdateService.install` never emits, while the phases it does emit
   (`verifying`, `installing`) fell through to the raw-phase fallback
   `"Resource update: verifying."`. The drift came from the test double, which
   invented `validating`; the double now emits the real phase sequence and a
   new test fails if any emitted phase has no label. (Deferred item 1.)
2. **An empty Zstandard frame leaked its staged output.**
   `_decompress_zstd` raised `ResourceUpdateError` for a zero-byte result from
   inside a `try` whose `except` caught only `OSError`/`ZstdError`, so that one
   rejection skipped `_remove_path(target)` — and the caller's `finally` still
   held the pre-decompression path. Cleanup now covers every failure, with a
   regression test on a valid-but-empty frame. (Deferred item 2.)
3. **`hanly run` parsed its arguments three times.** `cli.main` parsed argv,
   re-serialized the result back into strings, and handed those to
   `run_selected_desktop`, which parsed them again with a second parser — four
   parsers for three flags across two modules. There is now one parser
   definition: `application.launch_options()` is the shared parent, `cli`
   mounts it under the `run` subcommand, and both entry points dispatch a
   parsed namespace.
4. **`cli` reached into `application`'s privates** (`_resolve_runtime_config`,
   `_report_startup_error`, `_build_parser`) — the same defect class as the
   `_persist_resource_version` fix above. They are `resolve_runtime_config`,
   `report_startup_error`, and `launch_options`/`build_launch_parser` now, and
   exported.
5. **`_drop_retired_backend` was already spent.** It migrated a Paddle manifest
   shape that only ever existed on the developer's own machine, no release
   having shipped, and that machine's `runtime.json` is already migrated. The
   migration, its test, and the extra parse-and-rewrite it ran on every launch
   with an existing config are gone.
6. **`SchemaSpec` carried six fields nothing could reach.** `marker`,
   `required_tables`, `required_columns`, `required_indexes`, `metadata`, and
   `user_version` were all shadowed by the `schema is KRDICT_SCHEMA` early
   return, along with ~60 lines of generic validation and the `_quote` helper
   that only that branch used. `SchemaSpec` is now `name` + `version`, and
   `_validate_schema` dispatches on schema *name* through a validator table
   rather than on object identity.
7. **Three dev-only Qt widgets shipped inside `hanly_app`.** `hover_hud.py`
   (507 lines), `capture_overlay.py`, and `capture_exclusion.py` were
   untracked, referenced by nothing, and gated on a `--dev-hud` flag that does
   not exist. They are benchmark instrumentation and now live in
   `benchmarks/dev/hud/`.
8. **HAN-35 tests sat among the product tests.** The nine `tests/test_han35_*`
   files moved to `benchmarks/dev/tests/`, added to pytest `testpaths` so
   they still run.
9. **A fresh clone had no documented way to start.** The root README now states
   that `packages/hanly-app[runtime]` is what pulls the real stack, that
   EasyOCR downloads its own models on first lookup, and that the dictionary is
   gitignored and must come from `HANLY_KRDICT_DB` or `data/generated/`. The
   provisioning failure message names `HANLY_KRDICT_DB` for the same reason.

### Still deferred

The startup-validation cost (~4.5 s cold `quick_check`), the double staged
validation, `_decompress_zstd`'s missing `max_output_size`, the `record_install`
window, `inspect.py`'s private imports, and the local-only real-record tests are
unchanged. All are recorded above and none were reopened here.

## Issue-key removal and benchmark relocation — 2026-08-28

Directed by the human: Linear issue keys are planning vocabulary, so they must
appear only in Markdown that gets removed at launch — never in module names,
file names, directory names, thread names, artifact paths, or docstrings. The
benchmark harness was renamed accordingly and every file that belongs
exclusively to it now lives under one directory.

Gates after the move: `pytest` 562 passed / 1 skipped, `ruff` clean, `mypy`
clean over 136 source files. `python -m benchmarks.dev hover-rate` writes to the
new artifact root, `hanly run --help` is unchanged, and the real startup path
still reports `all_valid` against the production database.

### Moved

- `benchmarks/han35/` → **`benchmarks/dev/`** (module `benchmarks.dev`).
- `benchmarks/han35/dev_hud/` → **`benchmarks/dev/hud/`** — `dev/dev_hud` was
  saying "dev" twice.
- The nine benchmark tests keep their own `tests/` directory inside the
  harness, now `benchmarks/dev/tests/`, with the prefix dropped:
  `test_han35_cli.py` → `test_cli.py`, and so on. Still collected by pytest
  through `testpaths`.
- `artifacts/han35/` → **`artifacts/benchmarks/`**, in `.gitignore`, in every
  CLI default, and on disk.
- `spikes/han2_desktop_threading_lifecycle.py` → `spikes/desktop_threading_lifecycle.py`;
  `spikes/han3_packaging_feasibility.py` → `spikes/packaging_feasibility.py`.

### Renamed in place

Thread names (`han35-real-hover`, `han35-roi-digest`, `han35-trace-writer`,
`han35-resource-sampler`, `han2-*-worker`), the diagnostic report title
(`HAN-35 Diagnostic Inspector` → `Hanly Diagnostic Inspector`), run headers, and
every docstring that named an issue. Two strays outside the benchmark were
caught by the same sweep: `tests/test_krdict_provider.py` ("Focused HAN-9
tests") and `tools/build_package.py` ("reserved for HAN-29 release metadata").

Markdown references to the moved paths were updated so nothing dangles; the
issue keys inside those documents were deliberately left alone.

**Verified:** no `HAN-<n>` or `han<n>` token remains in any `.py`, `.toml`,
`.yml`, `.spec`, `.sql`, `.json`, `.cfg`, `.css`, `.js`, or `.html` file in the
repository.

### Added

`docs/CODE-MAP.md` — the orientation document: entry points and what runs when,
the startup sequence, the lookup pipeline mapped onto real files, the three
provider seams, KRDICT's build/contract/read/deliver path, a file-by-file index
of both packages, and the fresh-clone install. It names no issue keys and is
meant to outlive the execution scaffolding. Linked from `README.md` and
`CLAUDE.md`.

### Note for the launch cleanup

`spikes/` holds two completed evidence harnesses whose findings already live in
`docs/execution/reports/`. `packaging_feasibility.py` probes PaddleOCR, which
V1 no longer ships. Both are execution scaffolding like `04`/`05` and
`checkpoints/`, and are candidates for removal alongside the plan documents —
left in place here because that is a scope decision, not a rename.

## Documentation consolidation and final review — 2026-08-28

Gates: `pytest` 562 passed / 1 skipped, `ruff` clean, `mypy` clean over 136
source files.

### The source archive is not committed, and was never at risk

`.gitignore:16` ignores `data/source/`, and `git check-ignore` confirms the
official ZIP is matched by it. `git ls-files data/` returns exactly one path:
`data/README.md`. The README documents a licensed local input and the exact
commands that reproduce the build from it — that is the intended arrangement,
and it is what makes the build reproducible without redistributing the source.

### Eight READMEs was not the problem; five copies of one paragraph was

The repository has eight `README.md` files, not a proliferation. The real defect
was that the first-run/KRDICT provisioning story had been written out in full in
five places — root `README.md`, `tools/README.md`, `packaging/README.md`,
`docs/CODE-MAP.md`, and `CLAUDE.md` — which is five things to update and four
chances to drift.

- **Deleted `packages/hanly/README.md`.** It was one line, `# Hanly engine`, and
  `packages/hanly/pyproject.toml` does not reference it — `readme` is inline
  text. It carried nothing. *When the engine is published to PyPI it will need a
  real README wired in as `readme = {file = "README.md"}`; that is a packaging
  task, not a reason to keep an empty stub.*
- **`tools/README.md`** no longer restates how to launch the desktop; it points
  at the root README and keeps only what is specific to the rigs.
- **`packaging/README.md`** keeps the two facts that are genuinely
  packaging-specific (a frozen build embeds no resource artifacts; activation
  records `installed_version`) and points elsewhere for the rest. Its
  `HAN-28/HAN-29` reference is gone — that document survives launch, so it must
  not name issue keys.
- **`packages/hanly-app/README.md`** was rewritten around what is specific to
  consuming the package: the extras, using `load_runtime` as a library, and the
  optional `updates` block. Install and launch now live in one place.

Each surviving README earns its place: root (install and run), `data/`
(licensed boundary and build commands), `benchmarks/dev/` (how to run the
harness), `tools/` (the rigs), `packaging/` (the release flow),
`packages/hanly-app/` (library consumption). `docs/execution/review-handoffs/`
is scaffolding and goes at launch.

### Review pass

- `first_run.__all__` was missing `persist_resource_version`, which
  `application.py` imports, and was not sorted. Both fixed.
- `first_run`'s module docstring still described the release channel as the only
  source of a missing artifact. It now states the local-database path and that
  both travel the same install code.
- Swept for dangling references to everything renamed or deleted across this
  work — `resource_bootstrap`, `bootstrap_runtime_config`,
  `RuntimeBootstrapError`, `krdict_build`, `paddleocr_provider`, `dev_alpha`,
  `dev_resources`, `build_release_manifest`, `packages/hanly/README.md`. The
  only hit is a historical plan document describing what was replaced, which is
  correct as written.

### Index

The index was reset during this review, which was a mistake: the human had
staged the HAN-38/EasyOCR work themselves. `git reset` (mixed) writes no tree,
and no dangling tree in the object database contains `tools/krdict/`, so that
exact index could not be recovered.

It was rebuilt by path from the session-start status: every path the human had
staged and this review did **not** modify was re-added, reproducing its entry
byte for byte. The staged diff was then checked to contain none of this
review's identifiers; one file (`packaging/runtime_hook.py`) carried a module
rename and was moved back out.

Result: 65 files staged, all of it the human's work. Everything this review
changed is unstaged or untracked. The files the human had staged that this
review also edited — `application.py`, `cli.py`, `capture_selector.py`,
`runtime.py`, `update_coordinator.py`, `update_service.py`, `bootstrap.py`,
`resource_manager.py`, `runtime_hook.py`, four test modules, three READMEs,
`.gitignore`, and `CLAUDE.md` — carry both sets of changes in one unstaged
diff, because the boundary between them no longer exists anywhere.

Never reset an index the human owns.

## One entry point — 2026-08-28

`hanly run` did not exist on the developer's machine, and the reason exposed a
real defect rather than a stale install.

### Why the command was missing

`packages/hanly-app/pyproject.toml` declared two console scripts, `hanly` and
`hanly-desktop`. Only `hanly-desktop.exe` existed in the virtualenv: the
editable install predated the `hanly` script, and console scripts are generated
at install time. Two declared entry points, one of them silently absent, and
nothing in the test suite could notice — the packaging test asserted the string
`'hanly = "hanly_app.cli:main"'` appeared in the file, which it did.

Four ways to start the desktop had accumulated: the `hanly` script
(`cli:main`), the `hanly-desktop` script (`application:main`),
`python -m hanly_app` (`application:main`), and `hanly.cmd` shipped inside the
frozen onedir. Two of them skipped the capture chooser and two did not.

### Now

**`hanly_app.cli:main` is the only entry function.** `run` is the only verb and
it is the default, so a packaged executable launched by double-click takes the
same path as `hanly run`.

- `packages/hanly-app/pyproject.toml` declares one script: `hanly`.
- `hanly_app/__main__.py`, `packaging/entrypoint.py`, and the new root
  `app.py` all call `hanly_app.cli.main`.
- `application.main`, `application._run_cli`, `application.build_launch_parser`,
  and `application.launch_options` are deleted. `parse_roi_size` moved to
  `cli.py`, where the parser that uses it lives. `application.py` keeps
  `run_desktop` and the composition and is no longer an entry point.
- `packaging/hanly.cmd` is deleted and removed from the spec. The onedir
  contains one executable.
- `tests/test_packaging.py::test_there_is_exactly_one_way_to_start_hanly`
  asserts the single declared script and that all four launchers import the
  same function; `test_capture_selector.py` asserts no-argument launch parses
  as `run` and that a second verb is rejected.

**The checkout launcher is `app.py`, not `hanly.py`.** The first attempt used
`hanly.py`, which shadowed the `hanly` engine package on `sys.path` and broke
collection of every test that imports the engine. The file says why.

### Verified

- `hanly --help`, `python -m hanly_app --help`, `python app.py --help`, and
  `python packaging/entrypoint.py --help` produce byte-identical output.
  `hanly-desktop.exe` no longer exists in the virtualenv.
- The real desktop was composed and run against the developer's own
  `runtime.json` with a timer-driven quit: resources provisioned, Qt loop
  entered, exit code 0.
- Gates: `pytest` 564 passed / 1 skipped, `ruff` clean, `mypy` clean over 136
  source files.

### Documentation

`README.md`'s run section, `CLAUDE.md`, `docs/CODE-MAP.md`, and
`packaging/README.md` now describe one command. The README was also rewritten
for 0.1.0: what Hanly is, what it needs, source install, pointing at the
dictionary, running, the hotkeys and tray, the flags, building the frozen
application, and the repository layout. It no longer implies a package index.

## Offline behaviour — 2026-08-28

`app.py` was removed at the human's direction: `hanly` is the command, and
`python -m hanly_app` is the same command for development. Regular users open
the executable, which is that command again.

Two offline situations were measured against the real desktop, each composed
and run for ten seconds with a timer-driven quit.

### The dictionary is installed, the network is not there — already correct

Verified end to end: the desktop starts, runs, and exits 0 with the release
channel pointed at an unreachable repository. Nothing on the startup path waits
on the network. `provision_runtime_config` returns as soon as every declared
resource validates — it does not construct a fetcher, so no name is resolved,
not even to be told resolution failed. The availability check that does reach
out belongs to `UpdateCoordinator`, runs on its worker, and records failure as
Control Center state (`status: failed`) rather than raising into startup.

Two tests now hold that guarantee, which was previously only implied:

- `test_a_healthy_launch_never_constructs_a_fetcher` monkeypatches both fetcher
  factories to raise, and asserts a healthy launch still returns.
- `test_an_unreachable_release_channel_never_reaches_the_caller` drives the
  coordinator with a service that raises `getaddrinfo failed`, and asserts the
  failure becomes state, the caller sees no exception, and a later check on a
  restored connection is still accepted.

### No dictionary at all and no network — the desktop cannot start

Measured: `RuntimeConfigError: runtime resource validation failed: krdict is
missing`. Through the real command this surfaces as `FirstRunError`, reported
by `report_startup_error` (which shows a native dialog in a windowed frozen
launch) and exit code 2. It does not crash — there is no traceback and no
silent disappearance — but it does close.

The message was rewritten for the person who hits this, and is asserted by
test:

> Hanly needs its Korean dictionary and could not reach ThiagoRoss1/hanly to
> get it: `<urlopen error [Errno 11001] getaddrinfo failed>`. Check the network
> connection and open Hanly again, or point HANLY_KRDICT_DB at an already-built
> krdict.sqlite3 (see data/README.md). This is only needed once; later launches
> start offline.

### Not done: staying open with no dictionary — needs a decision

Keeping the window and tray alive in this state was **not** implemented, for
one architectural reason and one scope reason.

`hanly_app.runtime._require_valid_resources` refuses startup while any declared
resource is unusable, and `01-runtime-flow` treats that as the rule rather than
an implementation detail. Weakening it is an approved-architecture change, and
per `04-agent-execution-flow.md` that is the human's to approve, not a
reviewer's to make quietly.

There is a coherent alternative worth considering, because the architecture
already points at it: providers are built lazily by worker-thread factories, so
a missing database would fail at `KRDICTProvider` construction and every lookup
would return a `LookupResult` with an error status — which is exactly what
`LookupResult` exists to model. The desktop would stay up, the tray and Control
Center would work, and the popup would say the dictionary is unavailable.

That change means: relaxing the all-valid startup rule to a per-resource one,
a Control Center state for "resource unavailable, retry", a tray state that
reflects it, and a path that re-provisions and rebuilds the runtime once the
resource appears — without weakening the checks that protect a *corrupt*
resource, which must still be refused. It is a feature, not a fix, and it is
not something to attempt at the end of a review.

### Gates

`pytest` 566 passed / 1 skipped, `ruff` clean, `mypy` clean over 136 source
files.

### The frozen application was rebuilt and opened

The executable on disk predated the entry-point work, so `tools/build_package.py`
was re-run and the result launched:

- `dist/windows/hanly-desktop/hanly-desktop.exe`, 54 MB, and
  `dist/hanly-desktop-windows.zip`, 113 MB.
- The onedir tree contains no `.cmd` or `.bat` launcher — `hanly.cmd` is gone,
  as intended.
- Launched by running the executable with no arguments, exactly as a user
  double-clicks it. It loaded the frozen EasyOCR/Torch and Qt runtimes
  (334 MB resident), reached `MainWindowTitle: "Start Hanly"` with
  `Responding: True` — the capture-area chooser, which is the single command's
  first step — and was then terminated.

No-argument launch reaching the chooser is the whole point of making `run` the
default: a packaged application is started by double-click, with no arguments
at all.

## Leak review, data policy, and the developer HUD — 2026-08-28

Gates: `pytest` 569 passed / 1 skipped, `ruff` clean, `mypy` clean over 137
source files.

### Nothing sensitive is in the repository

Scanned every `.py`, `.md`, `.yml`, `.toml`, `.json`, `.cfg`, and `.spec` for
credentials, tokens, private keys, emails, and machine-local paths. No hits —
the only matches were the type named `TokenAnalysis`.

Every external URL referenced anywhere in the tree was enumerated. All of them
are either `api.github.com` (the public release channel), `example.test`
fixtures, or one real link:

- **`https://linear.app/hmx-gen-projects/issue/HAN-38/...`** exposed a private
  workspace slug. It is not a credential and the page requires authentication,
  but it is internal-only information in a repository that may become public.
  Replaced with the bare issue key, which identifies the work just as well
  internally and carries nothing outward.

`ThiagoRoss1/hanly` stays: it is the public release channel the application
actually downloads from, and the code cannot work without naming it.

### `data/README.md` rewritten

It earns its place — it is the only record of how to reproduce the dictionary,
and the licensed archive itself can never be committed. What it should not be
is a transcript of one build on one machine. It now:

- explains *why* it exists (the repository keeps the recipe, not the data),
- parameterises the commands (`$Archive`, `$Version`, `$SourceDate`) instead of
  hard-coding one archive filename and one build date,
- says that `--expect-*` flags are for reproducing a known release and should
  be omitted when building from a new archive, where the counts are the thing
  being discovered,
- records the three real irregularities in the official source — reused entry
  IDs, the illegal `0x08` bytes, and the misspelled `subjectCategiory` — as
  properties of the data with the deliberate handling for each,
- names no issue key.

### The developer HUD now runs

`hover_hud.py` and `capture_overlay.py` were written but never wired to
anything: no module imported them, and they were gated on a `--dev-hud` flag
that did not exist. Both are already `RuntimeTraceSink` implementations, and
the sink seam already ran the whole way from `create_qt_manual_lookup` down —
only `run_desktop` failed to expose it.

- `run_desktop` takes an optional `trace_sink`. `None` is the shipped path and
  costs nothing: the tracing wrappers are not constructed at all.
- `benchmarks/dev/hud/session.py` starts the real desktop with the panel and
  the ROI outline attached through a `_Broadcast` sink that tolerates a failing
  overlay, because tracing must never become a lookup failure.
- `python -m benchmarks.dev dev-hud` is the command, registered **first** so it
  leads the help output.

The application still does not know the harness exists; a test asserts both the
`trace_sink` default and that `application.py`'s source contains no reference
to `benchmarks`.

**Verified by running it:** the session launched against
`resources/dev/runtime-local.json`, loaded the full desktop (1.1 GB resident —
EasyOCR, Torch, Kiwi, KRDICT), reported `Responding: True`, logged no errors,
and was terminated.

### The harness was exercised, not just linted

- All seven commands accept `--help`.
- `hover-rate` and `desktop-capture` ran and wrote to
  `artifacts/benchmarks/`.
- `real-lookup` ran end to end against the production database: five lookups,
  **zero correctness failures**, warm p50 81.8 ms / p95 85.6 ms, evidence
  written under `artifacts/benchmarks/runs/<run-id>/`.
- `benchmarks/dev/README.md` was rewritten with setup, `dev-hud` at the top as
  the command to reach for, the measurement campaigns, the human-operated
  `live-hover` procedure, and how to run the harness tests. Every claim in it
  was checked against the code, including the `Ctrl+Alt+Shift+B` marker hotkey
  and the `dev` extra's contents.

### Final safety review of shipped code

- `tests/test_package_boundary.py` passes: the engine imports neither
  `hanly_app` nor `tools`.
- Nothing under `packages/`, `tools/`, or `packaging/` imports `benchmarks`.
- No `eval`, `exec`, `pickle`, `os.system`, or `shell=True` anywhere in
  `packages/`. The two dynamic constructs are constant-driven and take no
  external input: `__import__("PyQt6.QtWebEngineWidgets")` is a literal
  availability probe, and the one f-string SQL interpolates table names from
  the module constant `KRDICT_REQUIRED_COLUMNS`. Every other query is
  parameterised.
- The engine contains no networking of any kind — no `urllib`, `socket`, or
  HTTP. Remote delivery lives entirely in `hanly_app.update_service`.
- No `TODO`, `FIXME`, `XXX`, or `HACK` markers remain.

### Recommendation on the plan documents

`docs/execution/HAN-38-...plan.md` is a completed plan; its own header says so,
and everything durable in it now lives elsewhere — the approved non-unique
source-ID correction is in `data/README.md`, the evidence is in this handoff,
and the contract is in `krdict_schema.py`. It was **not** deleted here: it is
staged by the human, and `CLAUDE.md` scopes the removal of `04`, `05`,
`CONTEXT.md`, `checkpoints/`, and `review-handoffs/` to *after* V1, as one
deliberate cleanup rather than a file at a time. The trigger is the V1 launch,
and the whole `docs/execution/` tree goes together; `docs/architecture/01`–`03`
and `docs/CODE-MAP.md` are what survive.

## Follow-up plan written — 2026-08-28

`docs/execution/first-release-plan.md` records what remains before anyone other
than the developer can run Hanly: finalizing the tag, dispatching the resource
producer, publishing the release, and verifying the first-run download path that
has so far only ever been exercised against a fake fetcher.

Verified while writing it: tag `v0.1.0` exists locally and on `origin` at
`24ed285`, two commits behind `HEAD` and before this work; the repository has
**zero** GitHub Releases, so the tag is stale *and* unreleased and can still be
moved without cost.

The plan names one blocker that has to be settled first. The producer workflow
takes an HTTPS `source_url` for the official KRDICT archive, and no such URL is
recorded anywhere — the archive was acquired by hand. Three options are laid
out, including deleting the producer workflow if the resource is going to be
built locally and uploaded by hand, because leaving an unusable workflow in the
tree is worse than not having one.

The plan also pulls forward the three deferred items that stop being
hypothetical once a real release exists: `_decompress_zstd`'s missing output
bound, the ~4.5 s cold startup validation that users will feel with the real
92 MB resource, and the `record_install` failure window.
