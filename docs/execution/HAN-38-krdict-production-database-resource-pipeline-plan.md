# HAN-38 KRDICT Production Database & Resource Pipeline Implementation Plan

## Authorization and execution boundary

- Linear issue: HAN-38 — KRDICT Production Database & Resource Pipeline.
- Execution tier: Gate. This issue converges the KRDICT build/provider branch, local resource validation, remote delivery, first-run startup, and release production.
- Authoritative flow: [`docs/architecture/04-agent-execution-flow.md`](../architecture/04-agent-execution-flow.md) and its synchronized HTML companion.
- Operational manual: [`docs/execution/05-execution-plan.md`](05-execution-plan.md).
- Implementation phase only: implement, run focused checks, run the bundle/project gates once, run the real integration evidence, write exactly one review handoff, move HAN-38 to `In Review`, and stop for human review.
- Human gate: do not commit, push, merge, tag, publish a release, dispatch a production workflow, or mark HAN-38 `Done` without explicit human authorization.

## Goal

Produce a deterministic, normalized SQLite resource from the official KRDICT ZIP, package it as a checksummed Zstandard release asset, install/update it through the existing ResourceManager and UpdateService seams, and prove exact dictionary behavior through the active EasyOCR → Kiwi → KRDICT pipeline.

## Completion status

Implementation and verification completed on 2026-08-25. All nine phases below were executed, including the approved non-unique source-ID correction, the real production build/package, the supported EasyOCR integration run, and the repository gates. Review evidence is recorded in `docs/execution/review-handoffs/han-38-krdict-production-resource-pipeline.md`; HAN-38 remains subject to the human review/release gate.

## Fixed inputs and constraints

- Canonical source: `data/source/전체 내려받기_한국어기초사전_xml_20260819.zip`.
- Source archive SHA-256 observed before implementation: `266e50d1ad10b6b6ae8c0e9f7244a9df129f32069e599b5d652ccaa5db7110fe`.
- Source facts to verify, not infer from filenames: 11 XML members, 56,555 `LexicalEntry` elements, 76,833 `Sense` elements, DTD 16, no namespaces, and seven illegal `0x08` bytes sanitized only in memory.
- `source_date = 2026-08-19`, `resource_version = 20260819-v1`, `schema_version = 1`, asset `krdict-20260819-v1.sqlite3.zst`.
- English only for V1: map source label `영어` to `en`; preserve every English Equivalent lemma/definition exactly and retain repeated source rows.
- Preserve current provider/engine contracts, the `hanly-app -> hanly` dependency direction, ResourceManager local ownership, UpdateService remote ownership, and EasyOCR as the default V1 backend.
- No FTS, migrations, JSON flattening, audio/multimedia, synthetic Portuguese, non-English imports, contextual WSD, Paddle reactivation, updater redesign, or second manifest system.

### Approved source-identity correction (2026-08-25)

The first full canonical-archive build proved that raw KRDICT `LexicalEntry` IDs are not unique: 56,555 entries contain 53,671 distinct `source_id` values, with 1,160 IDs reused and a maximum reuse count of 86. ID `77610`, for example, identifies the base word `첫` and multiple distinct idiom entries. HAN-38 was paused at the constraint failure and the human approved this fixed correction:

- `entries.id` is the only unique identity for an individual Hanly entry.
- `entries.source_id` preserves the raw KRDICT ID exactly, including reuse.
- `UNIQUE(source, source_id)` is removed and replaced by the non-unique `idx_entries_source_source_id` lookup index.
- Child FKs continue to use only internal `entry_id`/`sense_id`; raw `target_source_id` fields remain non-FK external references and may resolve to multiple candidates.
- No occurrence discriminator, synthetic external ID, or additional identity layer is introduced.
- Validation reports total entries, distinct source IDs, reused source-ID count, and maximum reuse; duplicate source IDs are valid source data.

## File map

### Create

- `data/README.md` — local source/generated/report directory policy and exact developer commands.
- `tools/krdict/__init__.py` — package marker only.
- `tools/krdict/schema.sql` — the exact eleven-table schema without post-load indexes.
- `tools/krdict/source.py` — small shared ZIP/XML streaming primitives, direct-scope field readers, source counters, and in-memory `0x08` sanitization.
- `tools/krdict/inspect.py` — relocated inspector CLI and compact/manual source inspection.
- `tools/krdict/build_seed.py` — deterministic batch builder, metadata writer, post-load indexes, `ANALYZE`, and atomic output replacement.
- `tools/krdict/validate_seed.py` — source/database parity, relational/integrity/schema/index/query-plan validation, benchmarks, and JSON report output.
- `tools/krdict/package_resource.py` — Zstandard packaging, SHA-256, size/ratio metadata, and local manifest artifact generation.
- `.github/workflows/build-krdict-resource.yml` — explicit, non-publishing resource producer that accepts an HTTPS `source_url` and `source_sha256`, downloads and verifies the source in the runner, and emits the release-consumer artifact shape without committing or uploading the source archive.
- `packages/hanly/src/hanly/krdict_schema.py` — runtime schema/version/table/index constants and shared read-only database validation.
- `tests/krdict/` focused fixture, parser, schema, builder, validator, packager, provider, real-record, and pipeline coverage.

### Move/remove

- Move `tools/inspect_krdict.py` behavior to `tools/krdict/inspect.py`, update references, and remove the obsolete top-level entry point.
- Move `tests/test_inspect_krdict.py` coverage under `tests/krdict/`.
- Replace the legacy flattened `packages/hanly/src/hanly/krdict_build.py` builder contract; repository development callers and tests use the production tooling rather than retaining the obsolete two-table format.

### Modify

- `packages/hanly/src/hanly/krdict_provider.py` — normalized indexed lookup and ordered sense/English result mapping through the existing `DictionaryEntry` contract.
- `packages/hanly/src/hanly/resource_manager.py` — production KRDICT schema/metadata/count/foreign-key validation.
- `packages/hanly-app/src/hanly_app/update_service.py` — `.zst` staging/decompression, advertised size/schema/count validation, and unchanged atomic activation/rollback ownership.
- `packages/hanly-app/src/hanly_app/first_run.py` — mandatory KRDICT recovery and persisted independent resource version.
- `packages/hanly-app/src/hanly_app/update_coordinator.py` — user-facing download/verify/install phases using existing status primitives.
- `packages/hanly-app/src/hanly_app/application.py` — required-resource gate before runtime construction and healthy-resource update check without blocking startup on an optional update.
- `packages/hanly-app/src/hanly_app/runtime.py` — production KRDICT schema expectations without changing provider construction/thread ownership.
- `tools/README.md`, `resources/dev/runtime-local.json`, and affected existing tests — document the normal desktop launch and machine-local explicit configuration path.
- `.github/workflows/release.yml` and `tests/test_ci_workflows.py` — consume the resource producer's `.zst` output without publishing automatically.
- `tests/krdict/test_package_resource.py`, `tests/test_ci_workflows.py`, `tests/test_resource_manager.py`, `tests/test_update_service.py`, `tests/test_first_run.py`, `tests/test_update_coordinator.py`, `tests/test_application.py`, `tests/test_runtime.py`, `tests/test_krdict_provider.py`, `tests/test_engine_e2e.py`, `tests/test_easyocr_runtime.py`, and `tests/test_app_composition.py` — update and extend real contracts, including producer-manifest compatibility coverage.
- `pyproject.toml` and `packages/hanly-app/pyproject.toml` — Zstandard build/runtime dependency coverage.
- `.gitignore` — ignore `data/source/`, `data/generated/`, and `data/reports/` while retaining `data/README.md`.

## Exact database work

`PRAGMA foreign_keys = ON` is enabled for creation and validation. Every primary key is `INTEGER PRIMARY KEY`; no table uses `AUTOINCREMENT`.

| Table | Exact columns and constraints |
| --- | --- |
| `entries` | `id` as the sole unique row identity; `source NOT NULL`; non-unique raw `source_id NOT NULL`; `lexical_unit NOT NULL`; nullable `homonym_number`, `part_of_speech`, `vocabulary_level`, `origin`, `annotation` |
| `lemmas` | `id`; `entry_id NOT NULL`; `written_form NOT NULL`; nullable `variant`; `is_primary NOT NULL DEFAULT 0 CHECK IN (0,1)`; FK to `entries` with cascade |
| `senses` | `id`; `entry_id NOT NULL`; `source_sense_id NOT NULL`; `sense_order NOT NULL`; `korean_definition NOT NULL`; nullable `annotation`, `syntactic_annotation`; FK cascade; unique entry/source-sense and entry/order pairs |
| `translations` | `id`; `sense_id NOT NULL`; `language NOT NULL`; `lemma NOT NULL`; `definition NOT NULL`; FK cascade |
| `examples` | `id`; `sense_id NOT NULL`; `example_group NOT NULL`; `example_order NOT NULL`; nullable `type`; `text NOT NULL`; FK cascade; unique sense/group/order |
| `word_forms` | `id`; `entry_id NOT NULL`; `type NOT NULL`; nullable `written_form`, `pronunciation`; FK cascade |
| `categories` | `id`; `entry_id NOT NULL`; `type NOT NULL`; `value NOT NULL`; FK cascade |
| `related_forms` | `id`; `entry_id NOT NULL`; `type NOT NULL`; `written_form NOT NULL`; nullable `target_source_id`; FK cascade |
| `syntactic_patterns` | `id`; `sense_id NOT NULL`; `pattern_order NOT NULL`; `pattern NOT NULL`; FK cascade; unique sense/order |
| `sense_relations` | `id`; `sense_id NOT NULL`; `type NOT NULL`; `target_lemma NOT NULL`; nullable `target_source_id`, `target_homonym_number`; FK cascade |
| `resource_metadata` | `key TEXT PRIMARY KEY`; `value TEXT NOT NULL` |

Required metadata rows are `schema_version`, `resource_version`, `source`, `source_date`, `build_date`, `entry_count`, and `sense_count`. The production command supplies a fixed `--build-date` so repeated builds of identical source and arguments remain deterministic.

Create only these nine explicit indexes after bulk insertion, then run `ANALYZE`:

1. `idx_entries_source_source_id` on `entries(source, source_id)` (non-unique)
2. `idx_lemmas_written_form_entry` on `lemmas(written_form, entry_id)`
3. `idx_lemmas_entry_id` on `lemmas(entry_id)`
4. `idx_word_forms_written_form_entry` on `word_forms(written_form, entry_id)`
5. `idx_word_forms_entry_id` on `word_forms(entry_id)`
6. `idx_translations_sense_language` on `translations(sense_id, language)`
7. `idx_categories_entry_id` on `categories(entry_id)`
8. `idx_related_forms_entry_id` on `related_forms(entry_id)`
9. `idx_sense_relations_sense_id` on `sense_relations(sense_id)`

## Implementation phases and test-first seams

### Phase 1 — Source streaming and exact hierarchy

- [ ] Move the inspector tests first and make imports fail against the not-yet-created `tools.krdict` modules.
- [ ] Add literal miniature official-hierarchy fixtures covering missing optionals, explicit homonym `0`, level `없음`, multiple Lemmas/Senses/Equivalents, example groups with multiple lines, pronunciations/conjugations/short forms, both category kinds, RelatedForm, SenseRelation, annotations, and syntactic patterns.
- [ ] Run the focused tests and verify the expected import/behavior failures.
- [ ] Implement direct-scope readers that never cross from entry metadata into Sense/Equivalent children, deterministic sorted ZIP-member streaming, and the counting sanitizing stream.
- [ ] Run the focused parser/inspector tests green, including archive byte-for-byte immutability.

### Phase 2 — Schema and deterministic builder

- [ ] Add failing schema/builder tests for all eleven tables, exact columns/constraints, exact nine indexes, reused raw source IDs, metadata, batch ordering, optional NULLs, explicit source values, deterministic logical/byte output, clean failed-build staging, and `ANALYZE` statistics.
- [ ] Implement `schema.sql` and a builder that inserts internal IDs in deterministic source order inside transactions, never commits per row, creates indexes after ingestion, runs `ANALYZE`, closes the database, and atomically replaces only a complete destination.
- [ ] Update development fixture creation and run the schema/builder tests green.

### Phase 3 — Validator and provider

- [ ] Add failing validator tests for `integrity_check`, `foreign_key_check`, required tables/metadata, supported schema, source/database count parity, source-ID reuse statistics, primary lemmas, English mapping, hierarchy isolation, known zero/NULL behavior, index existence, and indexed `EXPLAIN QUERY PLAN` output.
- [ ] Add failing provider tests proving lemma and word-form candidates use the intended indexes, homonyms remain separate candidates, and each candidate maps its ordered senses to the existing `DictionaryEntry.definitions` tuple.
- [ ] Implement shared runtime schema validation, production validator/benchmarks, and read-only provider queries without exposing SQLite rows or adding contextual sense ranking.
- [ ] Run focused validator/provider tests green.

### Phase 4 — Zstandard resource artifact and manifest

- [ ] Add failing package/manifest tests for deterministic `.zst` output, SHA-256, size/ratio fields, `source_date`, `schema_version`, `expected_entry_count`, asset naming, successful consumer parsing, and mismatch rejection.
- [ ] Add failing UpdateService tests for checksum-before-decompression, corrupt Zstandard rejection, decompression to sibling staging, schema/count/integrity/FK rejection, atomic activation, previous-resource preservation, cleanup, and rollback.
- [ ] Implement Zstandard packaging/decompression and the minimum compatible optional fields on the existing remote manifest contract.
- [ ] Run focused packaging/resource tests green.

### Phase 5 — First-run, update, and status sequencing

- [ ] Add failing tests for missing/corrupt first run, healthy startup, optional update availability, user-started replacement bracketing runtime teardown, and failure preservation.
- [ ] Implement the sequence: local KRDICT health gate → mandatory recovery if invalid → healthy-resource update check → runtime/provider initialization → ready.
- [ ] Emit existing progress primitives as `Preparing Hanly`, `Checking resources`, `Downloading Korean dictionary`, `Verifying`, `Installing`, and `Ready`; do not expose seed row counts to users.
- [ ] Run focused bootstrap/application/coordinator tests green.

### Phase 6 — Explicit GitHub Actions producer

- [ ] Add failing structural workflow tests proving the producer is manual, never publishes, accepts an explicit HTTPS `source_url` plus SHA-256, verifies the source in the runner without committing or uploading it, runs builder/validator/packager, uploads the exact `.zst` plus manifest/report artifacts, and is consumable by `release.yml`.
- [ ] Implement `build-krdict-resource.yml` and adjust `release.yml` selection to `.sqlite3.zst` while preserving its human dispatch/tag/release gate.
- [ ] Run workflow/manifest tests green and parse every workflow as YAML.

### Phase 7 — Independent real-source regression and OCR integration

- [ ] Manually inspect raw XML for `가` source ID 27733, `첨성대` source ID 600265, one conjugation-rich verb, one relation-rich entry, and one multi-line dialogue group.
- [ ] Transcribe every V1-preserved value for those records as literal test-source expectations; do not compute expected values with parser/provider helpers.
- [ ] Query `data/generated/krdict.sqlite3` and assert exact rows, order, NULLs, forms, categories, translations, examples, patterns, and relations.
- [ ] Add a deterministic OCR-result → real Kiwi → production KRDICT test ending in exact literal dictionary assertions.
- [ ] Add and locally run a supported-environment real EasyOCR fixture → Kiwi → production KRDICT test; keep the database assertions exact and mark only the environment dependency when CI lacks model/runtime support.

### Phase 8 — Real production build and evidence

- [ ] Record the source hash, then run the exact builder command with fixed source/resource/build metadata.
- [ ] Run the production validator against the source ZIP and generated database, requiring 56,555 entries, 76,833 senses, seven sanitized bytes, clean integrity/FKs, metadata/count parity, and every required index.
- [ ] Package `krdict-20260819-v1.sqlite3.zst`, calculate SHA-256, and generate the local resource/manifest output.
- [ ] Record build/validation duration, all eleven table row counts, source-ID reuse statistics, SQLite and `.zst` sizes, compression ratio, `ANALYZE` evidence, representative query timings, and query plans for lemma, homonym candidates, word form, entry→senses, sense→English, and first example.
- [ ] Re-run the literal real-record and OCR/Kiwi/database tests against the completed database.

### Phase 9 — Convergence gates and handoff

- [ ] Run focused KRDICT/resource/startup/workflow/integration tests.
- [ ] Run `.venv\Scripts\python.exe -m pytest` once at convergence.
- [ ] Run `.venv\Scripts\python.exe -m ruff check packages packaging tests tools benchmarks`.
- [ ] Run `.venv\Scripts\python.exe -m mypy packages packaging tests tools benchmarks`.
- [ ] Run `git diff --check`, inspect `git status --short`, and verify generated/source artifacts remain untracked/ignored without disturbing pre-existing user changes.
- [ ] Create exactly `docs/execution/review-handoffs/han-38-krdict-production-resource-pipeline.md` with the requested 25-item evidence summary.
- [ ] Add one concise Linear handoff comment, move HAN-38 to `In Review`, leave it not-Done, and stop at the human review gate.

## Exact production commands and expected local artifacts

```powershell
.\.venv\Scripts\python.exe tools\krdict\build_seed.py `
  'data\source\전체 내려받기_한국어기초사전_xml_20260819.zip' `
  --output 'data\generated\krdict.sqlite3' `
  --source-date 2026-08-19 `
  --resource-version 20260819-v1 `
  --build-date 2026-08-25

.\.venv\Scripts\python.exe tools\krdict\validate_seed.py `
  'data\generated\krdict.sqlite3' `
  --source 'data\source\전체 내려받기_한국어기초사전_xml_20260819.zip' `
  --expect-entries 56555 `
  --expect-senses 76833 `
  --expect-sanitized-bytes 7 `
  --report 'data\reports\krdict-20260819-v1.json'

.\.venv\Scripts\python.exe tools\krdict\package_resource.py `
  'data\generated\krdict.sqlite3' `
  --output 'data\generated\krdict-20260819-v1.sqlite3.zst' `
  --resource-version 20260819-v1 `
  --source-date 2026-08-19 `
  --manifest 'data\generated\krdict-20260819-v1.resource.json'
```

Expected local-only outputs:

- `data/generated/krdict.sqlite3`
- `data/generated/krdict-20260819-v1.sqlite3.zst`
- `data/generated/krdict-20260819-v1.resource.json`
- `data/reports/krdict-20260819-v1.json`

The source archive and every generated output remain outside Git history. The repository retains only the reproducible recipe, runtime integration, tests, workflow, plan, and final review handoff.
