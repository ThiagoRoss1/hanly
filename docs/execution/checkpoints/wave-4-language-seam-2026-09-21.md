# Checkpoint — Wave 4 (Bundle C), acquisition-neutral language seam

**Master plan:** `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md` §8
**Authorized scope:** Bundle C — Wave 4 only. Waves 5–7 out of scope.
**Architecture approval:** granted by the human on 2026-09-21, in the terms
quoted in the Review Handoff. Wave 4 is the one bundle that requires it.
**Branch/worktree:** `visual/interface-update`, existing worktree reused. No
branch created, nothing committed.
**Interpreter:** `.venv/bin/python` (CPython 3.13.11).

Status: **complete.** Ends at the Wave 4 Review Handoff.

---

## Entry state

```
pytest -> 1936 passed, 2 skipped   (after the Wave 3 Phase B review)
ruff / mypy -> clean, 268 source files
```

## Work, in two logically separate parts

### Part 1 — documentation-only preflight

The Wave 3 Phase B review's deferred finding 2: the claim that exact doubling
was uniquely reliable did not survive equal-N testing. The issue-local spec now
carries the Phase B re-measurements (integers 1–6 at N=15, fractional sweep at
N=10–15), states that the earlier claim is withdrawn, and explains that 2 is the
smallest integer inside a wide basin rather than the only value that works.

No code changed in this part.

### Part 2 — the language seam

| Piece | Where |
|---|---|
| `TextSelection` — surface text, cursor index, inert `source` label | `hanly/contracts.py` |
| `LanguagePipeline` — Hangul policy, morphology, candidate selection, dictionary, result | `hanly/language_pipeline.py` (new) |
| `LookupPipeline` reduced to the pixel facade, delegating to it | `hanly/lookup_pipeline.py` |
| `lookup_selection` for a caller with no image | `hanly/lookup_pipeline.py` |
| Exports | `hanly/__init__.py` |

`LookupPipeline.lookup(image, target)` is unchanged in signature and behaviour.
It keeps what only pixels can decide — recognition, which region the pointer is
in, OCR confidence — and hands the rest to the shared stage. `LanguagePipeline`
is separately constructible from two providers, so a non-pixel client never has
to build a recognizer.

## Evidence

**Behavioural parity, real Kiwi and real KRDICT, 10 cases: 10/10 identical.**
Each case run twice — once as a direct `TextSelection`, once through the pixel
facade with the target aimed at the same character.

| Surface | idx | direct | via pixels |
|---|---|---|---|
| 초대받았어요 | 0 | SUCCESS `초대` | SUCCESS `초대` |
| 초대받았어요 | 3 | SUCCESS `받다` | SUCCESS `받다` |
| 읽습니다. | 0 | SUCCESS `읽다` | SUCCESS `읽다` |
| 떨어뜨렸어요 | 2 | SUCCESS `떨어뜨리다` | SUCCESS `떨어뜨리다` |
| 책을 | 0 | SUCCESS `책` | SUCCESS `책` |
| 예뻤어요 | 1 | SUCCESS `예쁘다` | SUCCESS `예쁘다` |
| 심심해서 | 0 | SUCCESS `심심하다` | SUCCESS `심심하다` |
| 없는말입니다 | 0 | SUCCESS `없다` | SUCCESS `없다` |
| `Hanly 2.0` | 0 | UNUSABLE | UNUSABLE |
| (whitespace) | 0 | UNUSABLE | UNUSABLE |

**The extraction costs nothing meaningful** (n=300 each):

| | p50 | p95 |
|---|---|---|
| `LanguagePipeline.lookup` | 164.2 µs | 244.5 µs |
| `LookupPipeline.lookup_selection` | 191.2 µs | 317.3 µs |
| `LookupPipeline.lookup` (full pixel path) | 236.9 µs | 345.2 µs |

The gap between the language stage and the full pixel path is OCR and target
resolution — the pixel work — not the delegation.

## Architecture synchronization

Appended, never renumbered, so no existing cross-reference moved:

- **RF-INV-13** in `01-runtime-flow.md`, plus a new section explaining where
  acquisition ends and language begins.
- **CA-INV-16** in `02-component-architecture.md`.

Both visual companions were updated by string-replacing inside the escaped
bundle. Verification, per `CLAUDE.md`:

- markdown and companion invariant IDs are **1:1 and in the same order** for
  both `RF-INV-*` (13 ids) and `CA-INV-*` (16 ids);
- each edit is **provably additive**: removing exactly the inserted row restores
  the pre-edit file byte-for-byte (+397 and +402 characters respectively).

`docs/CODE-MAP.md` names the new file, the `TextSelection` handoff point in the
flow diagram, and the rule that acquisition stops at `TextSelection`.

## Gates

```
pytest -> 1965 passed, 2 skipped   (entry: 1936 passed, 2 skipped)
ruff   -> All checks passed
mypy   -> Success, 270 source files
```

`tests/test_core_contracts.py::test_public_export_surface_is_explicit` was
updated for the two approved additions — it is the guard that would otherwise
have caught them, and it did.

## Exact commands

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check packages packaging tests tools benchmarks
.venv/bin/python -m mypy packages packaging tests tools benchmarks
```

## Privacy state

Unchanged. Wave 4 touched no capture, no export, no trace persistence, and no
artifact. The parity evidence used the real KRDICT database already present in
`data/generated/`, which is gitignored, and retained nothing.

## Files touched

Engine: `hanly/{contracts,language_pipeline,lookup_pipeline,__init__}.py`.
Tests: `tests/test_language_pipeline.py` (new), `tests/test_core_contracts.py`.
Docs: `docs/architecture/01-runtime-flow.md`,
`docs/architecture/02-component-architecture.md`,
`docs/architecture/visual/Hanly Runtime Flow.html`,
`docs/architecture/visual/Hanly Component Architecture.html`,
`docs/CODE-MAP.md`, `docs/execution/plans/wave-3-vision-input-scale-2026-09-21.md`
(preflight), this checkpoint, and the Wave 4 handoff.

`hanly-app` needed **no change**: the facade's signature is unchanged, so
`composition.py` constructs `LookupPipeline` exactly as before.

## Blockers

None.

## Exact next action

**Stop.** Wave 4 ends at
`docs/execution/review-handoffs/wave-4-language-seam-2026-09-21.md`.

Wave 5 (one native direct-text platform) is a separate bundle. It additionally
requires a platform choice, a real validation machine for that platform, and its
own authorization; nothing in this bundle opens it.
