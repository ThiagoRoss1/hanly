# Wave 6 Windows execution prompt

Execute this file as the complete authorization and instruction set for Wave 6.
This is a Phase A implementation run on a real Windows machine. Stop at the
Wave 6 Review Handoff. Do not begin Phase B, push, merge, or redesign the plan.

## 1. Required starting state

Work in the existing `visual/interface-update` branch and checkout. Do not
create another branch or worktree.

Before changing anything:

1. Read `AGENTS.md`, `docs/CODE-MAP.md`, `docs/architecture/01` through `04`,
   and `docs/execution/05-execution-plan.md`.
2. Read
   `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`,
   the Wave 4 handoff, and the complete macOS campaign checkpoint and handoff.
3. Inspect the worktree, branch, commit graph, Python interpreter, installed
   packages, Windows version, display topology, DPI state, integrity level, and
   available test applications.
4. Confirm that commit `45a22a7` is an ancestor of `HEAD`. This is the final
   reviewed macOS implementation boundary. It supersedes the older starting
   commit named in the original Wave 6 continuation section.
5. Confirm that the worktree is clean. If either check fails, stop and report
   the exact state rather than modifying or rebasing it.

Preserve every existing commit. Do not amend, squash, rebase, reset, reorder,
or replace history.

Use the repository's Windows Python 3.13 virtual environment. If setup is
needed, use the documented project installation flow:

```powershell
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]"
```

Use `HANLY_KRDICT_DB` or `data/generated/krdict.sqlite3` for the real dictionary.
Do not download or rebuild unrelated resources.

Create and maintain one concise checkpoint:

`docs/execution/checkpoints/wave-6-windows-2026-09-22.md`

Record the starting commit, environment, dependency choice, display/DPI facts,
available applications, implementation state, evidence, commands, results,
limitations, and next safe action.

## 2. Authorized scope

Implement Windows UI Automation as the second native direct-text source using
the already validated common contracts:

- `DirectText`
- `DirectTextProvider`
- `DirectTextCoordinator`
- `DirectTextService`
- `TextSelection`
- `LanguagePipeline`

The intended runtime is:

```text
stable pointer
  -> one bounded DirectTextService submission
  -> Windows UIA read away from the UI thread
  -> common permission/security/freshness/geometry/Korean validation
  -> valid: common LanguagePipeline
  -> refused/unsupported/ambiguous/error/timeout: existing OCR path
```

Implement the platform adapter at:

`packages/hanly-app/src/hanly_app/text_acquisition_uia.py`

It must satisfy the existing app-owned provider boundary and return normalized
`DirectText`. Keep validation policy in `text_acquisition.py`; do not duplicate
or weaken it inside the UIA adapter.

Add the Windows branch to `default_text_acquisition()` beside the existing
macOS branch. Do not change the user-facing lookup mode: direct text is
automatic and OCR fallback is invisible.

Do not implement:

- DOM or browser-extension integration;
- a local browser service;
- Linux accessibility;
- a generic acquisition/provider plugin registry;
- PaddleOCR, another OCR provider, or OCR selector changes;
- new public `hanly` contracts solely for platform or diagnostic data;
- unrelated popup, dictionary, morphology, ROI, capture, cache, or OCR changes.

If Windows proves that a narrow common-contract change is genuinely necessary,
document the evidence and smallest compatible change in the checkpoint before
making it. Preserve macOS behavior and tests.

## 3. UIA implementation requirements

Use the smallest reliable Windows UIA binding. Prefer existing/runtime-standard
facilities. If a new lightweight dependency such as `comtypes` is genuinely
necessary, document why direct `ctypes` is not maintainable, check its license
and package cost, add it only to the correct Windows/runtime and packaging
surfaces, and test the frozen/import path. Do not add a heavy accessibility or
computer-vision framework.

The adapter must:

- initialize COM correctly on the long-lived DirectTextService worker thread;
- use a background-compatible apartment model and balance initialization with
  teardown;
- obtain the element at the physical pointer location;
- refuse password, protected, unavailable, off-screen, stale, elevated, or
  inaccessible content before propagating text;
- use the appropriate UIA text pattern and range-from-point behavior;
- distinguish a containing range from the nearest range;
- read enough surrounding text to identify the Korean run under the pointer;
- return the cursor index in Python code-point units;
- return precise bounds for the selected/narrowed range in the same screen
  coordinate system as Hanly's pointer;
- never estimate a word rectangle from character counts or a line rectangle;
- safely handle UTF-16 offsets, surrogate pairs, combining characters,
  multiline text, empty ranges, malformed providers, and disappearing windows;
- release COM/UIA objects and native allocations on all paths;
- convert expected UIA refusal into `None` or normalized safe outcomes rather
  than leaking native exceptions through the application;
- never place recognized text in errors, traces, checkpoint diagnostics, or
  ordinary logs.

Use Windows UIA's native properties as evidence, not as unquestioned truth.
`RangeFromPoint` may return the nearest text. Precise range geometry must
contain the pointer and must be enclosed by its source range before direct text
is accepted.

### Deadlines and lifecycle

The native call is already isolated from the UI thread by `DirectTextService`.
Preserve its one-active/one-pending latest-wins behavior, one-shot delivery,
watcher sleep behavior, shutdown semantics, and exactly-once OCR fallback.

Measure the real UIA call distribution before selecting or changing any native
timeout behavior. The common overall deadline remains authoritative. Never
claim that cancelling a Python future cancels a synchronous COM call.

If a UIA call cannot be interrupted safely, the bounded service must still:

- keep the UI responsive;
- publish no late result;
- avoid unbounded threads or queued calls;
- let current requests fall back to OCR once;
- close without an indefinite application hang.

Do not weaken the reviewed macOS behavior to accommodate Windows.

### Coordinates and DPI

Determine the actual coordinate spaces empirically before writing transforms.
Do not assume that UIA, `pynput`, Qt, MSS, and Win32 all report identical
coordinates.

Validate:

- current process DPI-awareness context;
- per-monitor-v2 behavior where available;
- 100%, 125%, 150%, and 200% scaling when the machine can provide them;
- a secondary display with a negative origin when available;
- mixed-DPI transitions between monitors;
- physical versus logical pointer coordinates;
- UIA bounding rectangles against the same point used by Hanly;
- retained range and popup anchoring near every screen edge.

Make only evidence-driven conversions. Platform coordinates remain in
`hanly-app`; they must not leak into `hanly`.

## 4. Security and privacy

Check secure/protected state before reading text whenever UIA exposes that
state. At minimum cover `UIA_IsPasswordAttribute`, unavailable patterns,
protected controls, and access denied by process integrity/UIPI.

Do not trigger UAC or elevate a process while the user is away. If a real
elevated-target check requires approval, record it as unavailable and retain a
deterministic boundary test.

Privacy requirements are unchanged:

- normal tracing contains only bounded acquisition labels, outcomes, safe
  reason types, and timing;
- secure controls carry no text or geometry beyond what is required to refuse;
- Freeze remains memory-only;
- only explicit Export may persist private screen/text artifacts under the
  existing gitignored benchmark root;
- do not export or commit real browser, Discord, password, or user-document
  content;
- use deterministic synthetic Korean fixtures for persisted test evidence.

Keep real production OCR evidence distinct from staged replay diagnostics.

## 5. Automated tests

Keep the existing platform-neutral tests passing unchanged unless Windows
demonstrates a real common-contract need:

- `tests/test_text_acquisition.py`
- `tests/test_text_acquisition_service.py`
- `tests/test_direct_text_routing.py`

Add focused Windows-native tests under `tests/native/windows/`, covering at
least:

- COM initialization and balanced teardown on the service worker;
- element/range acquisition at the pointer;
- password and protected-control refusal before text propagation;
- unsupported/missing text patterns;
- access denied and higher-integrity targets;
- `RangeFromPoint` returning nearest rather than containing text;
- exact range bounds and pointer containment;
- UTF-16 to Python-index conversion, including emoji and malformed offsets;
- pure Korean, mixed Latin/Korean, punctuation, whitespace, and multiline text;
- physical/logical coordinates and DPI transforms;
- negative monitor origins where testable;
- timeout, blocked call, late completion, supersession, dispatcher failure,
  service close, double close, and submit-after-close;
- exactly one OCR fallback for a current refusal;
- no OCR construction/call for direct success;
- no OCR call for a valid direct-text dictionary miss;
- no text in traces, exception details, or privacy artifacts;
- resource and COM object cleanup over repeated acquisition.

Use events, barriers, fake clocks, and controlled doubles for concurrency.
Avoid arbitrary timing assertions that will flake on CI.

Add import/platform tests proving:

- non-Windows hosts do not import Windows COM/UIA modules;
- `hanly` imports no Windows or desktop modules;
- macOS selection and its reviewed tests remain structurally unchanged;
- packaging includes any required Windows-only runtime module without adding it
  to macOS/Linux artifacts unnecessarily.

## 6. Real Windows validation

Use synthetic, non-sensitive Korean content. Suggested surfaces include:

- `초대받았어요`
- `떨어뜨렸어요`
- `깨뜨렸습니다`
- `가공식품`
- `Hello 초대받았어요`
- `🙂🙂초대받았어요`

Create deterministic local fixtures when useful. Do not install unrelated test
applications. Close applications and temporary fixtures opened for validation.

Record this coverage matrix, marking unavailable applications honestly:

| Surface | Required observation |
|---|---|
| Notepad or another native text control | direct text, exact word/range, cursor-sensitive result |
| Edge and/or Chrome Korean page | direct/fallback reason and correctness |
| iframe inside a Korean page | direct/fallback reason and frame behavior |
| Discord/Electron, if installed | direct/fallback reason without persisting private content |
| raster subtitle or image | OCR fallback |
| canvas/WebGL | OCR fallback unless UIA genuinely exposes containing semantic text |
| custom/inaccessible control | safe OCR fallback |
| secure/password control | refusal without reading or tracing content |

For every available target record:

- application and control type;
- direct or fallback reason;
- expected and actual selected surface/lemma;
- permission/integrity state;
- pointer and returned-range coordinate space;
- cold and warm sample counts, p50, p95, and maximum latency;
- whether the same target was safely compared with OCR.

Do not fabricate an application, permission, scale, monitor, or latency result.
If only one monitor or DPI scale is available, state that limitation and retain
automated transform coverage for the others.

The Windows browser result is evidence, not a mandate. Browser accessibility
working through UIA does not authorize DOM integration, and a browser failure
does not authorize a browser-specific workaround in this wave.

## 7. Completion criteria

Wave 6 is complete only when:

- Windows automatically uses valid containing UIA text;
- every refusal invisibly reaches the unchanged OCR path;
- a valid direct-text dictionary miss does not run OCR;
- current-request checks prevent stale presentation;
- the UI remains responsive during slow UIA calls;
- coordinate and integrity behavior are tested and honestly bounded by the
  available machine;
- native resource/COM lifecycle is controlled;
- the cross-platform direct/fallback matrix is recorded;
- macOS and engine contracts remain unchanged unless a proven Windows need is
  documented;
- privacy boundaries remain intact;
- proportional and full gates are green, or every unavoidable environmental
  limitation is explicitly recorded.

Run, using the authoritative Windows environment:

```powershell
python -m pytest --suite portable
python -m pytest --suite native
python -m pytest --suite packaged
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```

Run focused UIA, routing, privacy, packaging, and composition tests as work
progresses. If a dependency or packaging surface changes, build and smoke-test
the real Windows package before declaring completion.

Do not dismiss a failure as pre-existing without reproducing and attributing
it. Do not make unrelated fixes; record them with a revisit trigger.

## 8. Commits, checkpoint, and handoff

Keep implementation and documentation boundaries reviewable.

When code, tests, real evidence, and gates are complete, commit the product
boundary as:

`feat: add windows accessible text acquisition`

Use author Thiago Rossi. Add no Claude/co-author/collaborator attribution or
trailers. Do not amend any prior commit.

Create:

`docs/execution/review-handoffs/wave-6-windows-2026-09-22.md`

Follow the repository template and record:

- starting and ending commits;
- Windows version, architecture, Python, display/DPI and integrity state;
- binding/dependency and packaging decisions;
- implementation and contract changes;
- common and Windows-native tests;
- the real application coverage matrix;
- correctness and latency evidence;
- direct-versus-OCR fallback behavior;
- privacy verification;
- limitations and unavailable hardware/applications;
- exact review targets;
- confirmation that Phase B has not started.

Commit the checkpoint and Review Handoff separately as:

`docs: record windows text acquisition handoff`

If session limits approach, stop at the nearest coherent boundary, update the
checkpoint with exact worktree state, commands, results, blockers, and next
safe action, and leave incomplete work uncommitted. Do not rush, invent
evidence, or weaken a gate to finish.

End with a concise report to the human. Leave a clean worktree. Do not perform
Phase B review, push, merge, or start DOM work.
