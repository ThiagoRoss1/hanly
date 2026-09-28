# Final cross-platform review execution prompt

> **Status (2026-09-22): executed.** This is the preserved review scaffolding
> for the final text-acquisition review. The review ran as `fabceb8..9b80ad4`
> (the Linux mypy failure described here was fixed locally in `fabceb8`, still
> to be confirmed by remote CI), and its outcome is
> `docs/execution/reports/final-text-acquisition-review-2026-09-22.md`. The
> follow-up correction bundle is recorded in
> `docs/execution/review-handoffs/final-correction-bundle-2026-09-22.md`.
> Statements below describe the branch as it stood before that review.

Perform the final cross-platform review of Hanly's
`visual/interface-update` branch.

Use one reviewer and keep the entire run within approximately 60 minutes. This
should be deep and decisive, but not an unlimited forensic exercise. Reserve
the final 10–15 minutes for the durable report and commits. Do not begin new
exploratory work after that boundary.

This is the final review of the completed macOS and Windows text-acquisition
campaign. It is also authorized to fix the current Linux CI mypy failure and
cheap, demonstrated defensive defects found during review.

Do not push, merge, rewrite history, begin DOM integration, add another OCR
provider, or redesign unrelated product areas.

## Read first

Read this orientation guide completely before exploring the repository:

`docs/execution/plans/final-branch-review-guide-2026-09-22.md`

It contains the 22-commit timeline, review/evidence map, runtime diagrams,
high-risk file/test map, open hypotheses, and minute-by-minute checkpoints.
Use it to avoid reconstructing completed history. It is not authoritative over
`AGENTS.md`, architecture, or the execution manual.

Then read, in the order routed by the guide:

1. `AGENTS.md`
2. `docs/CODE-MAP.md`
3. `docs/architecture/01` through `04`
4. `docs/execution/05-execution-plan.md`
5. the text-acquisition master plan
6. the selected handoffs named by the guide

Do not reread every historical execution artifact.

## Starting state

Expected state:

- branch: `visual/interface-update`
- required product baseline: `9962505`
- `HEAD` may be `9962505` or one later documentation-only commit containing
  this prompt and its review guide
- base: `4f9547b`
- Windows UIA implementation: `73b7372`
- clean worktree

Verify branch, worktree, remote tracking and ancestry first. Confirm that
`9962505` is an ancestor of `HEAD`. Treat a later commit containing only the
guide and prompt as review scaffolding, not product scope. If other commits
follow `9962505`, inspect and explicitly include them. Never reset, rebase,
amend, squash, reorder or replace history.

Review the complete range `4f9547b..9962505`, using previous accepted reviews
as routing evidence rather than proof. Prioritize:

1. Windows UIA and COM lifecycle;
2. shared asynchronous direct-text service;
3. macOS/Windows parity and OCR fallback;
4. privacy and secure-field behavior;
5. dictionary whole-form/component correctness;
6. live-production versus staged OCR evidence;
7. packaging, platform imports and CI;
8. popup/request-currency integration.

The earlier visual redesign needs integration/regression inspection, not a new
aesthetic review.

## First correction: Linux CI mypy

Ubuntu CI currently reports:

```text
packages/hanly/src/hanly/vision_provider.py:135:
  Unused "type: ignore" comment [unused-ignore]
  Cannot find implementation or library stub for module named "Foundation"
  [import-not-found]

packages/hanly/src/hanly/vision_provider.py:158:
  Unused "type: ignore" comment [unused-ignore]
  Cannot find implementation or library stub for module named "objc"
  [import-not-found]
```

The inline ignores cover `import-untyped`, while Linux reports
`import-not-found`; `warn_unused_ignores` is intentional.

Fix this narrowly before the main audit:

- use a precise mypy override or equivalently narrow typing solution for the
  optional `Foundation` and `objc` platform modules;
- remove inline ignores that become unnecessary;
- do not enable global missing-import suppression;
- do not hide unrelated errors;
- preserve the runtime `VisionProviderError` when pyobjc is unavailable;
- run focused Vision tests and mypy;
- record that remote Linux CI must confirm the fix after a later push.

Commit only this correction as:

`fix: type optional vision framework imports`

Use author Thiago Rossi and no attribution trailers.

## Architecture and shared behavior

Confirm:

- dependency direction remains `hanly-app -> hanly`;
- `hanly` imports no Qt, AX, UIA, COM or desktop lifecycle;
- `LanguagePipeline` is constructible without OCR;
- native providers normalize into acquisition-neutral contracts;
- native and OCR paths converge only through `TextSelection` and the shared
  language computation;
- direct success avoids OCR construction/calls;
- a valid direct-text dictionary miss does not invoke OCR;
- every current refusal reaches OCR exactly once;
- stale or superseded work never reaches lookup or presentation;
- only one platform-native provider runs on its own OS;
- unsupported platforms retain OCR behavior;
- architecture Markdown and visual invariant IDs remain synchronized.

## Shared concurrency boundary

Review the final `DirectTextService`, not merely its previous race counts:

- one worker and one watcher;
- one active and at most one pending job;
- no spin after deadline;
- callback failures cannot kill the worker;
- no callbacks while internal locks are held;
- timeout/completion, supersession/completion and close/completion races deliver
  once;
- close is idempotent and cannot self-join;
- shutdown during native work is bounded;
- destroyed Qt/application state cannot receive late callbacks;
- blocked providers cannot accumulate threads or jobs;
- dispatcher failure cannot leave hover handled without fallback;
- clocks are monotonic;
- errors and traces contain no recognized text.

Judge explicitly whether a pending job not being watched until the worker
picks it up is acceptably bounded on Windows by the 50 ms native floor. Do not
dismiss it because it predates Windows.

Use deterministic events/barriers for any new race reproduction.

## Windows UIA native review

Treat `text_acquisition_uia.py` as unsafe native code.

### COM and ABI

Verify against Windows ABI/authoritative definitions where needed:

- GUID, POINT, VARIANT and SAFEARRAY layouts on supported x86-64;
- calling conventions and every used vtable slot;
- signed `HRESULT` handling;
- specifically, whether the positive `_RPC_E_CHANGED_MODE` constant can match
  the signed `ctypes.c_long` return from `CoInitializeEx`;
- correct ownership when COM was already initialized in another apartment;
- balanced `CoInitializeEx` / `CoUninitialize`;
- all interface `Release` paths;
- BSTR / `SysFreeString` ownership;
- `VariantClear` and SAFEARRAY cleanup;
- null interfaces and failed HRESULTs;
- checking timeout-setter failures rather than assuming success;
- no released interface crosses a thread;
- `bind_worker()` / `release_worker()` always execute on the service worker and
  cannot leave a half-bound provider.

If a hook raises, decide whether continuing with an unbound provider is safe.
Verify macOS is unchanged when hooks are absent.

### UIA text and geometry

Inspect and adversarially test:

- `RangeFromPoint` returning nearest text;
- `_cursor_index`, `_span_offsets`, `_narrowed`, and `_rect_for_point`;
- code-point versus UTF-16 candidate offsets;
- repeated text where both candidate strategies can return the requested text
  at different occurrences;
- shorter matching prefixes;
- emoji, surrogate pairs, combining marks, punctuation and multiline text;
- exact word bounds, source-range enclosure and pointer containment;
- 4,096-character refusal;
- negative origins, fractional rectangles and rounding;
- disappearing/off-screen elements.

Refusal is preferable to a wrong word, but confirm refusal actually reaches
OCR rather than silently ending lookup.

### Security and deadlines

Confirm password/protected/access-denied state is checked before any sensitive
text-pattern read and secure outcomes contain neither text nor geometry.

The common deadline is 40 ms and UIA's minimum accepted native timeout is
50 ms. Verify that:

- the watcher remains authoritative;
- post-40 ms native answers never publish;
- the worker stays bounded until COM returns;
- later requests fall back safely;
- shutdown cannot wait indefinitely;
- no code claims synchronous COM cancellation;
- the measured 50 ms floor reflects real HRESULT behavior.

Do not trigger UAC during this review.

## macOS parity

Using current code and Mac-native tests, verify:

- AX remains off the UI thread;
- UTF-16 conversion stays at the adapter boundary;
- mixed text and emoji narrow correctly;
- `AXBoundsForRange` belongs to the selected Korean run;
- missing exact bounds falls back to OCR;
- native and overall deadlines remain distinct;
- dispatcher/late-answer hardening remains intact;
- Wave 6 did not weaken Mac selection or lifecycle.

The final report must contain a concise AX/UIA/shared-policy comparison.

## Language, popup, OCR and privacy

Sample and verify:

- exact-surface and reconstructed whole-form selection;
- maximum five deduplicated dictionary queries;
- POS/commonality homograph ordering;
- cursor fallback for `초대받았어요` without inventing `초대받다`;
- wrong-join protection such as `고소득층`;
- useful versus misleading component display;
- overlap and grammatical/missing-gloss semantics;
- popup compact/expanded/sticky/copy and retained target behavior;
- production OCR evidence remains distinct from staged replay;
- Wave 7 made no provider/selector/package change;
- Freeze is memory-only;
- only explicit Export persists private pixels/text under the ignored artifact
  root;
- normal traces, source labels, timeout/errors and Git history contain no real
  screen or accessibility text.

Keep documented form-versus-sense, component-density, mixed-DPI and corpus-size
limits honest. Do not implement semantic disambiguation or UI redesign here.

## Windows gate discrepancies

Do not automatically accept "same as baseline." Classify the Windows handoff's:

1. Torch `c10.dll` failures;
2. POSIX `resource` collection;
3. machine-specific benchmark manifest;
4. stale editable version `0.5.2`;
5. oversized pytest IDs hitting Windows environment limits;
6. stale packaged bundle failure;
7. 26 Windows mypy/POSIX-stub errors.

For each, state whether it is a product defect, test-infrastructure defect,
stale environment, unavailable capability, or dismissed; whether CI reproduces
it; whether it weakens OCR-fallback evidence; the smallest possible fix; and
whether it blocks merge.

Inspect GitHub checks for `9962505` if available. The supplied Linux mypy log is
authoritative even if the Mac cannot reproduce absent pyobjc modules.

## Tests and one-hour budget

Use existing evidence rather than repeating every historical benchmark.

Prioritize focused tests for Vision imports, direct-text service/routing,
platform isolation, Mac native acquisition, language components/whole forms,
privacy and packaging. Then run one convergence pass:

```bash
python -m pytest --suite portable
python -m pytest --suite native
python -m pytest --suite packaged
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```

Run the unfiltered suite only to resolve a discrepancy or if time remains.
Never fabricate a Windows-native rerun from macOS.

Follow the guide's checkpoints:

- T+10: CI typing fix and state established;
- T+32: UIA/COM and concurrency verdict drafted;
- T+45: integration/privacy/packaging disposition captured;
- T+50: no new investigations; report must exist;
- T+60: stop and report uncertainty.

## Fix authority

You may fix:

- the specified Linux mypy failure;
- demonstrated P0/P1 correctness, privacy, lifecycle or native-boundary bugs;
- cheap defensive hardening with a failing regression or direct reproduction;
- inaccurate handoff claims.

For code fixes: demonstrate, fix narrowly, rerun affected tests, and commit each
logical boundary separately. Record substantial changes as proposed work rather
than rushing them into the hour.

Do not implement DOM/browser extensions, another OCR provider, semantic Korean
disambiguation, popup redesign, speculative DPI transforms, or unrelated
cleanup.

Use Thiago Rossi as author, concise project-style subjects, and no attribution
trailers. Never amend or squash.

## Final report and outcome

Create and use this file as the review ledger from early in the run:

`docs/execution/reports/final-text-acquisition-review-2026-09-22.md`

Include:

1. range, environment and elapsed time;
2. verdict: Accept, Accept with hardening, Changes required, or Blocked by
   missing evidence;
3. delivered product behavior;
4. independently reproduced claims;
5. AX/UIA/shared fallback matrix;
6. architecture/public-contract verdict;
7. concurrency/native-lifecycle verdict;
8. language/component and popup verdict;
9. OCR/research verdict;
10. privacy/security verdict;
11. CI and test results;
12. findings ordered by severity;
13. Fixed now;
14. Deferred with triggers;
15. Dismissed with evidence;
16. proposed fixes, likely files and impact;
17. remaining platform/manual evidence;
18. merge readiness and exact next actions;
19. review-created commits;
20. confirmation that nothing was pushed or merged.

Use a compact findings table with severity, component, evidence, impact,
status, proposed action and revisit trigger.

Append only a short final-review verdict and pointer to the report in:

`docs/execution/review-handoffs/wave-6-windows-2026-09-22.md`

Do not duplicate the full report in the handoff.

Commit the report and handoff update separately as:

`docs: record final text acquisition review`

End with the verdict, most important findings, fixes/commits, gates, merge
recommendation and remaining actions. Do not push, merge, or begin another
review cycle.
