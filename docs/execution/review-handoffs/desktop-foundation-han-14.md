# Desktop Foundation Review Handoff

## Bundle

- Member issue: HAN-14
- Implementation ecosystem: GPT — Sol orchestrator with direct Luna xhigh workers
- Date: 2026-08-20

## Implemented

- Typed desktop preferences and deterministic, atomically replaced JSON persistence through `AppConfig` and `ConfigManager`.
- Basic `DesktopController` lifecycle with explicit new, running, paused, and shutdown states.
- A single-thread `JobExecutor` that permits one running job and at most one replaceable pending job.
- `LookupController` request identifiers, invalidation, stale-result suppression, normalized worker errors, and a dispatch-aware final currency check.
- First application-side engine composition through provider factories and a worker-owned `LookupPipeline`.
- Worker-thread provider construction and teardown, including a real `KRDICTProvider` proof that keeps its SQLite connection on its owning thread.
- Public `hanly_app` exports for the new foundation seams.

## Main expected behavior

The desktop client can start a lookup runtime, submit `ROIImage` plus `Point` work without running engine processing on the caller thread, retain only the latest pending request, suppress results from superseded work, and validate request currency in the configured result-dispatch context immediately before handoff. Pausing invalidates current work; shutdown invalidates work, drains or cancels the bounded pending slot according to policy, and closes worker-owned providers on the worker thread.

## Architecture / seams touched

- `DesktopController` and the narrow `LookupRuntime` lifecycle protocol.
- `AppConfig` / `ConfigManager` desktop-only configuration ownership.
- `LookupController -> JobExecutor / Worker -> LookupPipeline`.
- Application-side provider composition without adding an engine dependency on `hanly-app` or `ResourceManager`.
- RF-INV-06/07/11, CA-INV-01/02/03/06/13/14, and DAG-INV-02/14/15.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/__init__.py`
- `packages/hanly-app/src/hanly_app/config.py`
- `packages/hanly-app/src/hanly_app/desktop_controller.py`
- `packages/hanly-app/src/hanly_app/job_executor.py`
- `packages/hanly-app/src/hanly_app/lookup_controller.py`
- `packages/hanly-app/src/hanly_app/composition.py`
- `tests/test_app_config.py`
- `tests/test_desktop_controller.py`
- `tests/test_job_executor.py`
- `tests/test_lookup_controller.py`
- `tests/test_app_composition.py`

## Implementation-side validation already run

- Lifecycle/config focused checks -> 15 passed; focused Ruff and mypy clean.
- Executor focused checks -> 7 passed; focused Ruff and mypy clean.
- Post-consolidation `.venv\Scripts\python.exe -m pytest` -> 146 passed.
- Post-consolidation `.venv\Scripts\python.exe -m ruff check packages tests` -> passed.
- Post-consolidation `.venv\Scripts\python.exe -m mypy packages tests` -> no issues in 37 source files after correcting one reported type-narrowing annotation.
- Final real-SQLite composition proof -> 2 focused composition tests passed; focused Ruff and mypy clean. This test-only addition was checked proportionally rather than repeating the full bundle gates.

## Known limitations / intentionally unvalidated areas

- Capture, popup, hotkeys, hover observation, Control Center, tray, and final desktop UX remain out of scope for this gate.
- A running OCR job is not forcibly interrupted. The bounded pending slot and mandatory result-currency check provide latest-wins behavior; cooperative stage cancellation remains a later optimization.
- `result_dispatcher` defaults to inline execution. A UI integration must inject its UI-thread dispatcher; the controller deliberately runs the final currency check inside the dispatched closure so a stale result queued for the UI is still suppressed.
- Provider construction is proven with normalized provider doubles and a real KRDICT SQLite adapter, but this bundle does not load production PaddleOCR models or initialize the full production resource manifest.
- `ConfigManager` is a foundation, not the completed Wave 9 configuration surface; monitor/region selection and final preference UX remain deferred.
- Startup failure presentation and recovery remain unspecified by the approved runtime flow and are not invented here.

## Preserved V1 correctness issue

The target-point-to-token selection policy is intentionally unchanged. `LookupRequest` carries the exact `Point` into `LookupPipeline`, but a multi-token OCR region may still reduce to its first morphology lemma. The existing diagnostic remains in place, and the issue is recorded on HAN-19 and in `engine-convergence-han-12-13.md`.

This must be resolved and verified before HAN-19 Manual Hotkey Lookup can be considered functionally complete. It is not a HAN-14 review blocker unless this bundle accidentally changes or obscures the existing behavior.

## Suggested review targets

- Latest-wins executor behavior during concurrent submit, shutdown, pending cancellation, and pending drain.
- Whether the dispatch-aware final currency check is sufficient for the next popup/UI-thread integration.
- Worker-owned provider construction and reverse-order teardown, especially the KRDICT SQLite ownership decision.
- Lifecycle idempotence and the boundary between pause invalidation and later capture-service state.
- Desktop-only configuration validation and atomic persistence behavior.
- Package dependency direction and absence of linguistic policy in `hanly-app`.

## Post-Bundle Review Outcome

- Reviewer: Claude (Opus 5)
- Review ecosystem: Claude, reviewing a Codex-implemented bundle
- Date: 2026-08-20
- Status: Closed, including a follow-up manual-review cleanup pass. Latest-wins and currency guarantees hold under stress. One open V1 runtime issue recorded — UI-thread shutdown against a blocking dispatcher — with its structural decision assigned to HAN-17 Basic Popup. Nothing in this review blocks the revised HAN-15 concrete-runtime gate.

Gates after the review: **147 passed, Ruff clean, mypy clean across 39 source
files.**

### Verified under stress, not by inspection

Drove `LookupController` with four concurrent submitter threads against a slow
worker:

```text
submitted=160  jobs actually run=2  delivered=[160]
```

160 submissions collapsed to 2 executed jobs and exactly one delivered result —
the newest request. Bounded, latest-wins, no stale delivery, no lost wakeups,
no hang. A second probe submitted, called `invalidate()` mid-flight, and
confirmed **0** results delivered afterwards. `RF-INV-07`, `RF-INV-11`,
`CA-INV-14` and `DAG-INV-15` hold under contention, which is the claim this
bundle most needed checked.

`ConfigManager.save` is textbook-correct: `mkstemp` in the destination
directory, `fsync`, `os.replace`, and best-effort cleanup on failure.

### Fixed now

- **The `result_dispatcher` contract is now explicit at the seam.** A dispatcher
  must post and return without waiting; a blocking marshal deadlocks shutdown.
  Documented on `ResultDispatcher` and on `stop()`, which is where HAN-17 popup
  and later desktop integration will read it. No behavior changed — see the deferred item for the
  decision this defers.

### Manual-review cleanup pass (2026-08-20)

A follow-up manual pass over a fixed list of points. No new deep review was run.

Fixed now:

- **The three `# type: ignore[arg-type]` suppressions in `LookupWorker` are
  gone.** Their cause was self-inflicted: `ProviderFactory = Callable[[], object]`
  meant the factories returned `object`, so mypy could not prove the providers
  matched the pipeline's parameters. Replaced with `OCRProviderFactory`,
  `MorphologyProviderFactory` and `DictionaryProviderFactory`, each naming the
  protocol it must produce. The provider protocols are structural, so every
  existing adapter and test double still satisfies them without inheriting
  anything — and mypy now genuinely verifies the composition boundary instead of
  being told to ignore it. The generic `ProviderFactory` alias remains for
  callers that describe a factory generically.
- **`ResultDispatcher` documentation condensed** to the two lines that carry the
  invariant: schedule and return without waiting, because blocking UI dispatch
  can deadlock executor shutdown. The full reproduction stays in the open V1
  runtime issue above.

Intentionally left as-is:

- **`ResolverFactory` stays `Callable[[], Any]` with a cast at the call site.**
  `WordResolver` is a concrete engine class rather than a protocol, so a
  resolver double cannot satisfy it structurally. Tightening this would mean
  introducing a resolver protocol in the engine seam, which is out of scope for
  a cleanup pass. The reason is now recorded in the code next to the alias.
- **`# type: ignore[import-untyped]` on the `paddleocr` import** — the only
  remaining engine suppression, justified because PaddleOCR ships no type
  information. It records a fact about the dependency rather than hiding a
  Hanly-owned type.
- **The result-dispatch lambda is correct and unchanged.** It is created after
  `result` is reassigned, closes over a frozen `LookupRequest`, and neither
  variable is mutated afterwards, so asynchronous dispatch cannot observe a
  stale capture. `cast` inside it is a no-op at runtime. Replacing it would be
  style churn.
- **`AppConfig` / `ConfigManager` need no change.** `from_dict` is a correct
  validated conversion boundary: it rejects non-mappings, ignores unknown keys
  so a newer client's settings file cannot stop an older client from starting,
  applies defaults for missing keys, and funnels type and value errors into one
  `ValueError`. `update(**changes)` remains the intended keyword API and
  rejects unknown fields explicitly. No `.env` or environment-variable path
  exists for user preferences, and none should be introduced — `AppConfig` plus
  the persisted settings file already owns hotkey, theme, and hover delay.

Validation after this pass: **147 passed, Ruff clean, mypy clean over 39 source
files.**

Optional final polish, not a defect:

- **Exception message capitalization** is mixed only because some messages begin
  with an identifier (`JobExecutor cannot be started again`, `PaddleOCR ...`,
  `KRDICT ...`) while the rest are lowercase. That is a consistent rule rather
  than drift, so no churn was applied. If a single house style is ever wanted,
  fold it into the V1 deferred sweep rather than touching strings now.

### Open V1 runtime issue

**UI-thread shutdown can deadlock against a blocking result dispatcher. This is
a V1 runtime issue, not post-V1 polish.**

Confirmed empirically, not theorised: with a dispatcher shaped like Qt's
`BlockingQueuedConnection`, a window-close handler calling `stop(wait=True)` on
the UI thread never returns. The UI thread blocks in `thread.join()` while the
worker blocks inside the dispatcher waiting for that same UI thread.

```text
stop(wait=True) returned within 4s: False
DEADLOCK CONFIRMED: UI thread blocked in join(); worker blocked in dispatcher
UI queue depth: 1
```

The seam has already been clarified — `ResultDispatcher` must post and return
without waiting, documented on the type and on `stop()` (see **Fixed now**). The
structural solution is deliberately **not** invented here.

Candidate directions:

1. **Require non-blocking result dispatch** as a hard contract, and make an
   integration that violates it fail visibly rather than hang.
2. **Drain or coordinate pending UI delivery during shutdown**, so the worker
   never waits on a UI thread that is itself waiting to stop.
3. **Call `stop(wait=False)` from the UI thread** and perform joining and
   teardown elsewhere.

Current leading expectation, not a decision: **a UI-thread shutdown should not
synchronously wait on a worker that may still need UI dispatch.** Which
mechanism enforces that is a question for the real integration — the exact
lifecycle must be validated once a genuine popup/UI dispatcher exists rather
than guessed from a test double.

No small implementation adjustment was applied beyond the seam documentation: a
blocking dispatcher cannot be detected from inside `stop()`, and anything
stronger would pre-empt the HAN-17 lifecycle decision.

*Trigger: must be resolved during HAN-17 Basic Popup, before any real UI
shutdown path is considered complete.*

### Deferred considerations

- **`on_result` executes while `LookupController._lock` is held.**
  `_deliver_if_current` checks currency and calls the sink inside the same
  `RLock`, which makes check-and-deliver atomic but couples hover submission to
  UI paint time. *Revisit when real UI callback/paint behavior exists; ensure
  slow UI delivery cannot unnecessarily block submit/hover latency.*
- **Executor callback exceptions are swallowed.** `_report_result` and
  `_report_error` catch and `pass` so a failing callback cannot strand the
  worker; with no logging story yet, a broken sink fails invisibly. *Revisit
  when the desktop logging/diagnostic story is wired.*
- **Alias proliferation** — `submit_lookup = submit`, `shutdown = stop`,
  `close = stop`. *Group with the existing API/accessor cleanup item for the V1
  deferred sweep, unless real consumers show a clearer API sooner.*
- **`worker_factory: Callable[[], Any]`** loses typing at the composition
  boundary this bundle introduces. Composition-boundary typing polish. *Tighten
  when the concrete worker type/interface stabilizes, or at the post-V1 typing
  sweep if still relevant.*

### Dismissed

- **Latest-wins during concurrent submit / shutdown / pending cancellation and
  drain.** Reviewed as a suggested target and stress-tested above. The pending
  slot is replaced under the condition variable, `shutdown(cancel_pending=False)`
  drains exactly one item, `submit` after shutdown raises rather than silently
  dropping, and the `finally` block always closes the worker and republishes
  terminal state. No defect found.
- **Worker-owned provider construction and reverse-order teardown.** Providers
  are built and closed on the executor thread, which is what keeps the
  `KRDICTProvider` SQLite connection on its owning thread. This is the correct
  resolution of the Wave 2 deferred threading item for the desktop path, and it
  is proven with a real SQLite adapter rather than a double.
- **Package dependency direction and linguistic policy.** `hanly-app` imports
  `hanly`; nothing reverses it, and no linguistic decisions leaked into the app
  layer. `CA-INV-01/02/03` hold.
- **The preserved target-point-to-token V1 issue.** Confirmed this bundle
  neither changes nor obscures it: `LookupRequest` carries the exact `Point`
  through to `LookupPipeline`, and the multi-token diagnostic still fires. It
  remains recorded on HAN-19 and in `engine-convergence-han-12-13.md`, unchanged
  by this review.

### Next bundle

Nothing in this review blocks HAN-15 Concrete Hanly V1 Engine Integration, the
revised next gate. The one open V1 runtime issue is scoped to HAN-17 Basic Popup,
where the UI dispatcher it concerns is first introduced. The target-point-to-token
issue remains owned by HAN-19.

## Review assignment

Human-selected. Review completed 2026-08-20 — see the Post-Bundle Review Outcome above.
