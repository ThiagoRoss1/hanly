# Hanly V2 UI and popup-content follow-up

Status: campaign in progress, 2026-10-22. Implementation and bounded QA only; no Phase B deep review, push or merge. Branch `design/hanlyV2`, initial commit `0554d96`. The previous uncommitted `hanly-v2-post-redesign-qa.md` is preserved separately.

## UI implementation — Luna worker and native consolidation

The three custom disclosures (Region, Dictionary and resources, Update activity) had a `grid-rows-[0fr]` utility overriding the open-state CSS in the base layer. Removing the competing utility restores their visible expansion. Region coordinate validation now appears inside Region instead of closed Capture settings and clears when the user edits coordinates or changes capture mode.

Native inspection additionally exposed a Region action overlapping the 34px title strip, a validation banner touching the bottom rim, and resource footer text touching its frame. Insets now keep those elements inside the artwork. Commit: `ea849c4`.

All six routes were explored in the browser at 720×560 and 1150×560, including light/dark, Normal/Compact navigation, update progress/failure and missing-permission states. Computed open tracks measured 242px, 121px and 60px for Region/resources/activity. These are browser observations with controlled data, not native capture acceptance. Detailed worker coverage: `artifacts/lab/runs/20261021-popup-campaign/browser-ui/coverage.md`.

## Popup data and Lab — Luna worker

Commit `7cd1191` adds `python -m lab popup-content`: real Kiwi → local KRDICT → the production popup presentation model, with source-gold assertions, provenance, compact scores and full ignored evidence. It runs no OCR, capture, desktop or native window. Known wrong answers count as failures and produce a nonzero command exit.

The 12 authored cases cover noun particles, past/polite endings, contractions and irregulars, 하다 derivation, multi-sense entries and grammatical constructions. Checks cover lemma, KRDICT entry/POS, Hanja, vocabulary level, sense hashes, Read as roles and applicable constructions. Dictionary text is hash-pinned in tracked fixtures; readable sampled definitions remain in ignored evidence. The first sense check verifies dictionary order, not contextual sense ranking. This finite set cannot establish complete Korean accuracy.

Learner-facing analysis now names XSV as “verb-forming suffix.” Reviewed VX forms receive auxiliary verb/adjective labels; unresolved VX forms retain the broader “auxiliary” label rather than asserting a false category.

Recorded run: [popup-content summary](../../../artifacts/lab/runs/ff757924-a7f4-4037-85dc-8c4855690b9e/summary.md), **11/12 passed**, KRDICT `20260819-v1`, Darwin arm64, dirty `0554d96` source. The pytest corpus keeps the remaining correct expectation as a strict xfail; the standalone campaign reports the miss as a failure.

Follow-up commit `8a7d276` stores the exact production-serialized popup model in ignored results and adds an opt-in React integration check. A fresh [real-provider run](../../../artifacts/lab/runs/6a515d3f-eb00-4ae9-af50-998aee04792c/summary.md) retained the same 11/12 outcome. Six of those actual models passed through the real `PopupPage` component, covering noun/verb POS pairs, past tense, auxiliary and XSV roles, component glosses, progressive and prohibition constructions. Event delivery is simulated in jsdom; it does not prove WebKit/native geometry or acquisition. Reproduction is documented in `lab/README.md`.

### Open linguistic defect: carbon-paper noun

In the authored sentence `먹지를 깔고 써요`, selected `먹지를` resolves to 먹다/동사 instead of the source-supported 먹지/명사. Observed analysis is 먹/VV + 지/EC + 를/JKO; lookup tries 먹지를, 먹지 and 먹다, then accepts the verb. The paired prohibition `밥을 먹지 마세요` correctly resolves the verb and construction. Replacing the morphology guard with an unconditional dictionary noun fallback would risk that paired case and other ambiguous forms. No word-specific correction, new backend or dictionary spelling correction was added. Revisit with a context-aware language-resolution design and a broader ambiguity corpus before claiming a safe fix.

## Linguistic adjudication — Luna source worker

Official KRDICT entries support the expected words and constructions, including [손님](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=71279), [먹다](https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo=58272), [-고 있다](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=72238), [먹지](https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo=54828) and [-지](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=78636). Per-case sources are recorded in the fixture; expanded adjudication is in ignored `linguistic-sources.md`.

Naver denied the available web reader and Papago could not be accessed through it. A separate background browser attempt found no available browser surface and stopped; no login or security bypass was attempted. No Papago/Naver comparison is claimed. Ambiguous senses remain ordered as KRDICT provides them; customer-context 손님 and progressive/resultative -고 있다 checks require the relevant sense to be present rather than pretending the first sense is a context-ranked translation.

## Native UI and permission investigation — coordinator

The actual rebuilt debug bundle is `apps/desktop/src-tauri/target/debug/bundle/macos/Hanly.app`. Native checks confirmed Region expansion and visible invalid-width feedback with Capture settings closed, both Updates disclosures, hover activation selection, shortcut editor cancellation, Appearance persistence, log search/filter/refresh and short-window scrolling. The window was resized from 1060×760 to approximately 730×560 and restored. In the short window, the compact rail footer and lower Appearance controls remained reachable by scrolling. Native screenshots are under `artifacts/lab/runs/20261021-popup-campaign/native/`.

Two additional native dialog issues were corrected in `6363f6a`: `p-6` overrode the title-strip inset, and keyboard Tab escaped the modal into the background theme control. The rebuilt app now has clear title/body separation, forward/reverse Tab wrapping and Escape focus restoration to Select area. Safari's pointer activation required explicitly focusing the trigger before opening the modal. Native AX observations and the keyboard regression passed.

Further native checks exercised invalid/valid hover-delay feedback and restoration, fixed-monitor selection and restoration, fullscreen entry/exit, runtime Retry (Preparing → Ready, capture stopped), and diagnostics export. Export produced a parseable JSON with one own-service log record. These observations do not include clearing the real user's logs or changing OCR backend.

The user completed the macOS Accessibility authentication. System Settings shows Hanly enabled, but the source-development service still reports Screen Recording and Accessibility missing after Recheck/restart. Pressing Start capture returns the explicit permission-required message and leaves capture stopped. This blocks current end-to-end hover/OCR/popup acceptance.

The service performs permission checks, and this debug app starts it through `.venv/bin/python -m hanly_app.service`. The debug root also has an ad-hoc, build-specific code identity. A root/service identity mismatch or stale build grant is consistent with the observations; exact live TCC attribution is unproven. See ignored `native/permission-identity-diagnosis.md`. No TCC database, signing identity, capture method, installed application or broad Python/Terminal grant was changed to bypass the blocker. A properly frozen-service package under normal OS grants remains a separate acceptance check.

## Mechanical checks and process observation

| Check | Result |
|---|---|
| Final portable Python gate | 2,709 passed, 2 skipped, 1 strict known xfail |
| Ruff, full requested roots | Passed |
| mypy, full requested roots | Passed, 368 files |
| React UI | 54 passed; 1 opt-in integration skip by default; jsdom, no native canvas/pixel acceptance |
| Exact real-data React integration | Passed, six observed popup models; simulated IPC |
| Node bridge | 12 passed |
| Lab command/classification/identity tests | 57 passed |
| Frontend typecheck/build and debug app bundle | Passed |
| New real-provider popup content campaign | 11/12; known noun/verb misresolution remains failed |
| Native capture/hover/OCR | Blocked by in-app permission preflight |

The first portable run had two process-inventory failures caused by sandbox denial of `ps`; all five tests in that module passed outside the sandbox, then the complete stable portable gate passed with the required process access. The two skips are optional provider/resource environments, not converted failures. Existing native and packaged suites have not been relabeled as portable success.

The sandboxed Lab launch also failed before startup. Repeating the explicit `.app` launch with LaunchServices/process access produced [a completed 60.9-second run](../../../artifacts/lab/runs/20261021-220845-run/summary.md): no dropped events, host peak 108.6 MiB, family peak 503.7 MiB and mean sampled family CPU 13.5%. These samples include startup and idle UI, with capture stopped and observed OCR backend “none.” They are not steady-state lookup latency or an improvement claim. Existing registered baselines are tour/stress recordings, so no incompatible performance comparison was made.

A [300.5-second native UI session](../../../artifacts/lab/runs/20261021-222957-run/summary.md), dirty `7cd1191`, finished with no dropped events: host peak 115.4 MiB, family peak 542.6 MiB, sampled mean family CPU 12.7%. It included modal keyboard checks, hover-delay and monitor settings, fullscreen and an unconfigured-runtime update check. Capture/OCR/lookup remained zero. Source edits and a new build occurred during observation; the running process retained its launch build. This is a bounded observation, not a controlled regression benchmark.

A longer process observation with periodic native UI checks started at 2026-10-22 01:43 UTC on `8a7d276` (documentation dirty), using the same exact debug bundle and a disposable profile. Run: `artifacts/lab/runs/20261021-224317-run/`, requested duration 3h15m. It is still running; no final duration, stability verdict or native capture acceptance is claimed yet.

## Timing and remaining coverage

The campaign began at 2026-10-21 19:57 UTC. A System Settings computer-use call blocked for about 4h48m and returned around 00:47 UTC. That interval is not active QA. The requested four hours of active testing have not yet been completed; continued work must distinguish real testing from blocked or idle wall time.

Remaining: continued distinct UI coverage/longer observation and final handoff. The real profile was restored byte-equivalently as parsed JSON and rechecked after the last restart; capture is stopped. Native reader focus, word-to-popup hover retention, captured-text accuracy, Windows/Linux/DPI and official packaged-app acceptance remain unverified on this host/session. OCR backend comparison/tuning stays deferred to the user's later branch.
