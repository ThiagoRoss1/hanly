# Review Handoff: HAN-19 Manual Hotkey Lookup

## Review State

- Linear issue: HAN-19 — Manual Hotkey Lookup (First Runnable Alpha Slice)
- Implementation state: complete for Phase A review, with a focused review pass applied (see Applied Review Fixes)
- Intended Linear state after handoff: In Review
- Scope boundary: HAN-19 only; no hover, resource-update, startup-shell, popup-polish, or later UI work was pulled forward
- Git operations: no commit, push, or merge performed
- Next step: human alpha testing via the deterministic manual check below

## Implemented Slice

- Added target-point-to-word resolution inside PaddleOCR line-level regions while preserving true quadrilateral hit testing and the containing region's confidence evidence.
- Modelled the resolver seam as the engine-side `TargetResolver` protocol, which the desktop `word_resolver_factory` already substitutes against, and kept an explicit reduction diagnostic for a segment that still holds several words.
- Added the public manual desktop composition from the existing `HanlyRuntime` seam through the existing bounded `LookupController`.
- Shared one explicit Qt dispatcher between the global hotkey service and result delivery.
- Wired the lookup action to real cursor position, `CaptureService`, the worker-owned lookup path, and the existing Qt popup.
- Kept capture and popup work on the UI thread, provider construction and lookup work on the controller worker, latest-result-wins behavior, and non-blocking shutdown.
- Added the supported developer command `python tools/dev_alpha.py`.
- Made that command build the missing gitignored mini KRDICT database from the committed XML fixture, discover only already-installed PaddleX models, disable remote model-source checking, and print a readiness/hotkey message.
- Kept that repository-local preparation in `tools/`, outside the shipped `hanly-app` package.
- Disabled PaddleOCR's optional document/orientation helper models in the canonical development config so the V1 path requires only the owned detection and Korean-recognition resources.

## Main Files

- `packages/hanly/src/hanly/word_resolver.py`
- `packages/hanly/src/hanly/lookup_pipeline.py`
- `packages/hanly-app/src/hanly_app/manual_lookup.py`
- `packages/hanly-app/src/hanly_app/composition.py`
- `packages/hanly-app/src/hanly_app/__init__.py`
- `tools/dev_alpha.py`
- `tools/dev_resources.py`
- `resources/dev/runtime.json`
- `tools/README.md`
- `tests/test_word_resolver.py`
- `tests/test_lookup_pipeline.py`
- `tests/test_engine_e2e.py`
- `tests/test_manual_lookup.py`
- `tests/test_dev_alpha.py`
- `tests/test_app_composition.py`

The execution context's mechanical commands were also aligned with the repository/CI scope by including `tools` in Ruff and mypy.

## Evidence

### Automated-Test-Backed

- Corner-order invariance: every rotation and both winding directions of an
  axis-aligned quad, and every rotation of a tilted quad, resolve the same
  target to the same word (`tests/test_word_resolver.py`). This covers the
  demonstrated `TR→BR→BL→TL` case that previously returned the wrong word.
- Target narrowing before morphology, and the multi-word reduction diagnostic
  firing only for a segment that really holds several words
  (`tests/test_lookup_pipeline.py`).
- Real Kiwi and real KRDICT over a line-level OCR region
  (`tests/test_engine_e2e.py`).
- Resolver substitution through the public composition seam
  (`tests/test_app_composition.py`).
- UI-thread dispatch, latest-result-wins, non-success delivery, and
  non-blocking shutdown for `create_manual_lookup`
  (`tests/test_manual_lookup.py`).
- Startup failure closing the popup and capture service, with `shutdown()`
  still idempotent afterwards (`tests/test_manual_lookup.py`).
- `create_qt_manual_lookup` constructing one `QtResultDispatcher` and sharing
  that same instance with both the hotkey service and the lookup controller,
  run offscreen through the existing `pytest.importorskip` Qt seam
  (`tests/test_manual_lookup.py`). This is the composition the alpha runs, and
  it was previously covered by manual evidence only.
- Local resource preparation: building a missing database, not rebuilding an
  existing one, discovering the PaddleX cache without editing the caller's
  config, and reporting missing models or sources
  (`tests/test_dev_alpha.py`).

### Real/Manual-Evidence-Backed

These paths need real models, a real display, and a real global hotkey, so
they are verified by running them rather than by automated tests.

`tools/dev_lookup.py` processed the committed Korean fixture through the real
`PaddleOCR → Kiwi → KRDICT` path with confidence `0.9820699691772461`. Paddle
returned one tilted line region — `p1=(6,7)`, `p2=(151,10)`, `p3=(150,39)`,
`p4=(6,37)` — containing `책을 읽습니다.`. Two target points in that same quad
produced distinct successful lookups, unchanged from before the review fixes:

| Target | Selected text | Kiwi lemma | KRDICT result |
| --- | --- | --- | --- |
| `(40, 25)` | `책을` | `책` | `책` — `book` |
| `(100, 25)` | `읽습니다.` | `읽다` | `읽다` — `to read` |

Both results had empty diagnostics and flowed through the existing
`LookupController` and `LookupPipeline`.

`resources/dev/krdict/krdict.sqlite3` was deleted and rebuilt from
`krdict-mini.xml` through the moved `tools/dev_resources.py`, which also
discovered both models in the existing local PaddleX cache and removed its
disposable effective config afterwards. No download path was used.

`python tools/dev_alpha.py` then started from that clean state, constructed the
real PaddleOCR detection and Korean-recognition models from the discovered
cache, registered the hotkey, and reached the Qt event loop with:

```text
Hanly dev alpha ready. Point at Korean text and press Ctrl+Shift+Space.
```

`_default_alpha_runner` itself remains manual-evidence-backed. Covering it
automatically would require driving a real `QApplication` event loop, a real
capture backend, and a real global hotkey listener; that machinery would be
brittle and disproportionate, and the composition it wires is now covered
directly by the `create_qt_manual_lookup` test above.

The popup rendering of these lookups is manual-evidence-backed and is what the
deterministic manual check below exercises.

## Mechanical Gates

Run once after convergence from `.venv`:

```text
python -m pytest                           215 passed
python -m ruff check packages tests tools   All checks passed
python -m mypy packages tests tools         Success: 54 source files
```

`git diff --check` also completed without whitespace errors.

## Applied Review Fixes

A focused review pass ran before human alpha testing. Its findings were applied
here; no later issue was started and no commit was made.

### Fixed

1. **Corner-order assumption in `WordResolver` (engine correctness).**
   `_horizontal_fraction` derived the text axis from `points[0]/[3]` and
   `points[1]/[2]`, which silently assumes the quad starts at its top-left
   corner. `Quad` guarantees corner order only as "the order the provider
   reported them, conventionally clockwise" — the starting corner is not part
   of that contract. A quad reported `TR→BR→BL→TL` is equally valid and
   returned the wrong word with no error, because `_contains` is
   order-independent and still reported a hit.

   `_text_axis` now derives the axis from the quad's shape alone: of the two
   opposite edge pairs, the shorter pair caps the ends of a text line, and
   those two edge midpoints define the axis. Shape leaves reading direction
   ambiguous by 180 degrees, so V1's left-to-right Korean assumption orders the
   two caps. That assumption is stated in the resolver, where it belongs; the
   public `Quad` contract was deliberately **not** tightened to preserve the
   old implementation. Tilted-quad support is unchanged.

2. **`ManualLookupRuntime.start()` stranded acquired resources.** A failing
   `register()` marked the runtime `_closed` before popup and capture cleanup,
   so the caller's follow-up `shutdown()` returned at the closed guard and
   those resources were never released. Startup failure now rolls back through
   the ordinary `shutdown()` path, which stays idempotent.

3. **Inaccurate action diagnostic.** Every `_handle_action` failure was
   reported as `screen capture failed`, including a cursor-read or
   lookup-submission failure. The failing stage is now named accurately.

### Deleted Unnecessary Abstractions

- **`_ResultForwarder`.** It existed to defer the popup past controller
  construction, justified by avoiding `QtPopupRuntime`'s internal dispatcher —
  a path this composition never uses. `QtPopupTrigger` depends only on
  `PopupController(QtPopupView(parent))`, so the popup is now built first and
  passed straight to `create_lookup_controller`. The class, its mutable
  `set_target`, and its unreachable not-ready `RuntimeError` are gone. A small
  `_as_result_handler` adapter remains for one real reason: `QtPopupTrigger.open`
  returns a `PopupPosition` that the controller's `ResultHandler` discards.

- **The duck-typed resolver fallback in `LookupPipeline._resolve_target`.**
  `getattr(self._word_resolver, "resolve_target", None)`, the tuple-shape
  validation, and the `narrowed` flag are removed. Repository evidence showed
  resolver substitution *is* an intentionally supported seam — `LookupWorker`,
  `create_lookup_worker_factory`, `HanlyRuntime`, and `test_app_composition`
  all thread a `word_resolver_factory` through — so the seam is now modelled
  honestly by a small engine-side `TargetResolver` protocol rather than removed
  or replaced by hypothetical flexibility. That also deleted
  `composition.ResolverFactory`'s `Any` and its `cast(WordResolver, ...)`, and
  two `# type: ignore[arg-type]` suppressions in the tests, so mypy now checks
  this seam for the first time.

- **`importlib.import_module` + `getattr` + `cast` in `dev_alpha`.**
  `create_qt_manual_lookup` is now imported directly alongside `CaptureService`,
  `load_runtime`, and `QApplication` in the same lazy block, restoring static
  signature checking. Lazy importing is retained so the rig is importable
  without the runtime extra.

- **`_is_low_confidence`'s duplicate-text fallback.** With `resolve_target`
  returning the containing region, the no-region branch became unreachable.
  Confidence policy is now one comparison against the resolved region.

### Reviewed and Deliberately Kept

- **`isinstance(controller, LookupController)`.** No existing project seam
  covers what `ManualLookupRuntime` needs (`start`, `submit`, `invalidate`,
  `stop`); `popup.LookupStopper` covers only `stop`. A protocol was not invented
  for test convenience, so the concrete check stays.

- **`hanly.__all__`.** `TargetResolver` is exported from `hanly.word_resolver`,
  next to `WordResolver`, and not added to the engine's pinned public export
  surface. `test_public_export_surface_is_explicit` guards that surface
  intentionally.

### Dev-Tool / Package Boundary Decision

`tools/README.md` states that nothing under `tools/` ships, but the dev-only
preparation logic had been placed in `packages/hanly-app/src/hanly_app/`, where
it shipped with `hanly-app` while hardcoding `parents[4]` as the repository
root — correct only in an editable checkout.

`dev_resources.py` moved to `tools/dev_resources.py`, where its repository-root
resolution (`parents[1]`) is honest and its non-shipping status matches the
directory it lives in. Reusable behavior stayed in the package: database
construction remains `hanly.krdict_build`, and the module only prepares
repository-local paths around it. No packaging architecture was added and no
HAN-24 acquisition behavior was introduced.

The move broke `python tools/dev_alpha.py`, because a direct script run puts
`tools/` on the path rather than the repository root. The launcher now inserts
the repository root when it is executed as a script, so the one supported
startup command is unchanged and `tools.dev_alpha` stays importable for tests.

`manual_lookup` is now re-exported from `hanly_app.__init__` because it is a
real application composition API. `dev_resources` is not, and left the package
entirely.

## Deterministic Manual Check

1. Activate the repository virtual environment.
2. Optionally delete `resources/dev/krdict/krdict.sqlite3` to exercise automatic local preparation.
3. Run `python tools/dev_alpha.py` and wait for the readiness line.
4. Display the committed Korean fixture or any clear rendering of `책을 읽습니다.`.
5. Place the cursor on `책을` and press `Ctrl+Shift+Space`; expect the popup to show `책` / `book`.
6. Place the cursor on `읽습니다.` and repeat; expect `읽다` / `to read`.
7. Point at text absent from the mini dictionary and confirm the popup shows the normal not-found state.
8. Close the Qt application and confirm it returns promptly without a lingering hotkey listener.

## Preserved Boundaries and Triggers

- Paddle currently exposes one quad for the full Korean line, including its `text_word` metadata. HAN-19 therefore maps the cursor proportionally along the line's text axis and selects the whitespace-delimited span. That axis is now derived from the quad's shape, so the mapping no longer depends on which corner the provider reported first, and tilted lines are still supported. The real fixture proves the required V1 Korean case. The mapping still assumes roughly uniform character advance and left-to-right reading order. If later manual evidence shows materially wrong selection for variable-width or mixed-script lines, open a focused engine-correctness follow-up; do not fold that speculative expansion into this review.
- Monitor-enumeration/performance work remains deferred to the hover-capable flow that owns repeated capture behavior.
- Resource acquisition/update UX, application-shell startup, configurable hotkey UI, popup polish, hover mode, and continuous capture remain owned by their later DAG issues.
- The mini KRDICT database and discovered effective runtime config remain development-only generated artifacts, produced by repository tooling that does not ship.

Stop here for human alpha testing. Do not start the next implementation bundle from this handoff.

## Post-Bundle Review Outcome

- Reviewer: human
- Ecosystem: manual review and alpha test
- Date: 2026-08-22
- Status: approved and closed
- Fixed now: none required after the completed review cycle.
- Deferred considerations: the proportional line-mapping limitation remains deferred to its documented variable-width or mixed-script failure trigger.
- Dismissed: none recorded.
