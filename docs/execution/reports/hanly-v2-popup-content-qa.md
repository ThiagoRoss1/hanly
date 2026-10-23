# Hanly V2 UI and popup-content follow-up

Status: language-contract corrections and the Lab packaged smoke path are implemented. Both native grants were restored for the unchanged final package. A follow-up reproduced cursor-contaminated Lab captures and corrected fixture pointer ownership; the same packaged app now completes the 24-word and 153-target story sets without presentation failures. This is not full native or linguistic acceptance. No Phase B deep review, push or merge. Branch `design/hanlyV2`, initial commit `0554d96`. The previous uncommitted `hanly-v2-post-redesign-qa.md` is preserved separately. Earlier blocked statuses and native failure counts below are historical; see the reproduction section at the end.

## Current outcome — 2026-10-22

- Product changes: bounded two-word context, punctuation-preserving direct selection and corrected raw-token candidate indices (`1bc29e7`). Lab diagnostics and parity tests: `509729b`, `f2aeefd`. The human deferred alternative analyses/UI; no OCR tuning, backend/model change, spelling correction or dictionary additions.
- Source-gold popup corpus remains **11/12**; grammar **702/706 headwords**, with all **76/76 constructions** passing. Known ambiguity and sense-order limitations remain, independently of dictionary coverage.
- Native packaged smoke after the fixture correction: **24/24** word and **153/153** story presentation decisions passed. The earlier **1/1** held-target result remains separate. These are finite lifecycle checks, not a general semantic accuracy score.
- All fourteen originally failed targets return expected KRDICT headwords through real Vision → selection → Kiwi → KRDICT on corrected, owned fixture recaptures. The reproduction section distinguishes byte-matched native inputs from other recaptures and the failures that did not recur. The correction changes Lab only; no product recognizer, capture adapter, language contract or sealed package changed.
- Native popup expansion/content could not be newly inspected through CUA: the tool exposes the Control Center, not the nonactivating dictionary panel separately. Historical native presentation and six-real-model React checks remain distinct evidence. Windows/Linux native acceptance remains outstanding.
- Latest portable gate: **2,748 passed, 2 skipped, 1 known strict xfail**, 125.20s. Focused raster/stress/trace-only checks: **26 passed**. Ruff passed across all requested roots; mypy passed in **370 files**. Earlier Lab, frontend/model and sealed-package build evidence below remains separate; this continuation changes Lab only.

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

In the authored sentence `먹지를 깔고 써요`, selected `먹지를` resolves to 먹다/동사 instead of the source-supported 먹지/명사. Observed analysis is 먹/VV + 지/EC + 를/JKO; lookup tries 먹지를, 먹지 and 먹다, then accepts the verb. The paired prohibition `밥을 먹지 마세요` correctly resolves the verb and construction. A six-case follow-up confirmed neighbor context already reaches Kiwi, and that top-10 noun alternatives occur both for the desired carbon-paper reading and for a valid verbal `가지를 않는다` control. Alternative presence alone is therefore insufficient. The current morphology contract exposes a single analysis; a ranked selection policy would need broader contrast evidence and review. No word-specific correction, new backend or dictionary spelling correction was added. Revisit with a broader authored ambiguity corpus before claiming a safe fix. Evidence: ignored `pc003a-resolution-experiment.md` and `.json`.

## Linguistic adjudication — Luna source worker

Official KRDICT entries support the expected words and constructions, including [손님](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=71279), [먹다](https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo=58272), [-고 있다](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=72238), [먹지](https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo=54828) and [-지](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=78636). Per-case sources are recorded in the fixture; expanded adjudication is in ignored `linguistic-sources.md`.

Naver denied the available web reader and Papago could not be accessed through it. A separate background browser attempt found no available browser surface and stopped; no login or security bypass was attempted. No Papago/Naver comparison is claimed. Ambiguous senses remain ordered as KRDICT provides them; customer-context 손님 and progressive/resultative -고 있다 checks require the relevant sense to be present rather than pretending the first sense is a context-ranked translation.

## Native UI and permission investigation — coordinator

The actual rebuilt debug bundle is `apps/desktop/src-tauri/target/debug/bundle/macos/Hanly.app`. Native checks confirmed Region expansion and visible invalid-width feedback with Capture settings closed, both Updates disclosures, hover activation selection, shortcut editor cancellation, Appearance persistence, log search/filter/refresh and short-window scrolling. The window was resized from 1060×760 to approximately 730×560 and restored. In the short window, the compact rail footer and lower Appearance controls remained reachable by scrolling. Native screenshots are under `artifacts/lab/runs/20261021-popup-campaign/native/`.

Two additional native dialog issues were corrected in `6363f6a`: `p-6` overrode the title-strip inset, and keyboard Tab escaped the modal into the background theme control. The rebuilt app now has clear title/body separation, forward/reverse Tab wrapping and Escape focus restoration to Select area. Safari's pointer activation required explicitly focusing the trigger before opening the modal. Native AX observations and the keyboard regression passed.

Further native checks exercised invalid/valid hover-delay feedback and restoration, fixed-monitor selection and restoration, fullscreen entry/exit, runtime Retry (Preparing → Ready, capture stopped), and diagnostics export. Export produced a parseable JSON with one own-service log record. These observations do not include clearing the real user's logs or changing OCR backend.

The user completed the macOS Accessibility authentication. System Settings shows Hanly enabled, but the source-development service still reports Screen Recording and Accessibility missing after Recheck/restart. Pressing Start capture returns the explicit permission-required message and leaves capture stopped. This blocks current end-to-end hover/OCR/popup acceptance.

The service performs permission checks, and this debug app starts it through `.venv/bin/python -m hanly_app.service`. The debug root also has an ad-hoc, build-specific code identity. A root/service identity mismatch or stale build grant is consistent with the observations; exact live TCC attribution is unproven. See ignored `native/permission-identity-diagnosis.md`. No TCC database, signing identity, capture method, installed application or broad Python/Terminal grant was changed to bypass the blocker. A properly frozen-service package under normal OS grants remains a separate acceptance check.

To prepare that comparison without replacing current output, the official macOS product was built in the attached isolated worktree `/Users/thiago/.codex/worktrees/hanly-v2-packaged-qa/hanly`, at `f724fef`. Its `dist/macos/Hanly.app` contains the frozen service, identifies build UUID `818eb2c4-72e0-4118-80c5-31720d9e3815`, version 1.1.0 and arm64, and passed inventory plus deep/strict signature verification. Existing production weights were copied locally; no model download or backend change occurred. Normal packaging used the existing ad-hoc policy. The package was subsequently exercised without installation. Its inventory, signature and native window/React bridge smoke check passed (`native/packaged-window.json`, exit 0, `frozen=true`, `frontend_ready=true`). The initial self-check snapshot precedes native capability delivery and lists only auto/EasyOCR; the normal runtime-ready app exposes Apple Vision and reports it configured. The diagnostic `torch: not installed` means missing distribution metadata in this frozen report, not proof that Torch payload is absent; no Torch/OCR import or recognition acceptance is claimed.

A separate [180.6-second packaged Lab session](../../../artifacts/lab/runs/20261022-050223-run/summary.md) used a disposable profile. Runtime reached Ready, KRDICT was compatible, and three shortcuts registered. Permissions remained 0/2 after Recheck. Start capture displayed the required-access message and stayed stopped; capture, OCR and lookup counts stayed zero. Native screenshot and AX evidence are in `native/packaged-permissions.png` and `packaged-capture-refused.txt`. The session exited 0 with zero surviving or forcibly terminated children; a process check confirmed no frozen root/service remained. The pre-existing terminal-launched source instance was left untouched. The installed app and user profile were not replaced.

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
| Frozen package inventory / signature / native window bridge | Passed; exact isolated build, not installed-app or OCR acceptance |
| Existing grammar corpus | 698/706 headwords match; 74/76 construction checks; remaining rows retained as failures |
| Native capture/hover/OCR | Blocked by in-app permission preflight in debug and frozen app |

The first portable run had two process-inventory failures caused by sandbox denial of `ps`; all five tests in that module passed outside the sandbox, then the complete stable portable gate passed with the required process access. The two skips are optional provider/resource environments, not converted failures. Existing native and packaged suites have not been relabeled as portable success.

The sandboxed Lab launch also failed before startup. Repeating the explicit `.app` launch with LaunchServices/process access produced [a completed 60.9-second run](../../../artifacts/lab/runs/20261021-220845-run/summary.md): no dropped events, host peak 108.6 MiB, family peak 503.7 MiB and mean sampled family CPU 13.5%. These samples include startup and idle UI, with capture stopped and observed OCR backend “none.” They are not steady-state lookup latency or an improvement claim. Existing registered baselines are tour/stress recordings, so no incompatible performance comparison was made.

A [300.5-second native UI session](../../../artifacts/lab/runs/20261021-222957-run/summary.md), dirty `7cd1191`, finished with no dropped events: host peak 115.4 MiB, family peak 542.6 MiB, sampled mean family CPU 12.7%. It included modal keyboard checks, hover-delay and monitor settings, fullscreen and an unconfigured-runtime update check. Capture/OCR/lookup remained zero. Source edits and a new build occurred during observation; the running process retained its launch build. This is a bounded observation, not a controlled regression benchmark.

The [extended debug observation](../../../artifacts/lab/runs/20261021-224317-run/summary.md) started at 2026-10-22 01:43 UTC on `8a7d276` (documentation dirty), using the same debug bundle and a disposable profile. Requested duration was 3h15m, but the app exited normally after **4,648.8 seconds (77.5 minutes)**; this is not a completed 3h15m soak. The run recorded 12 events, zero drops, exit 0 and zero surviving/forced children. Host peak was 109.4 MiB, family peak 474.4 MiB and sampled mean family CPU 11.2%. A permission-required capture-start refusal occurred near its end; acquisition/OCR/lookup counts are zero. The reason the app exited before the requested duration is not established by the recording. Source changed to documentation commit `f724fef` during observation.

During it, a session-log clear and zero-record diagnostics export passed in the verified disposable profile. Native day→night samples at 728–1,239ms and after settling showed no blank panel or tree/house overlay in those frames. The isolated package build ran concurrently around 01:53–02:00 UTC, so those process samples have background host-load confounding. No controlled performance comparison is claimed.

## Existing grammar corpus — follow-up workers and coordinator

The existing `lab grammar` command completed over 114 authored cases and 706 syllable targets: OCR-shaped selections matched 351/353 headwords, direct-shaped selections 347/353. This command runs Kiwi/KRDICT only; its “ocr” column is an input-shape simulation, not OCR or screen capture. Parts were named in 119/119 checks per form, auxiliary senses in 15/15, and constructions in 37/38. Evidence: [grammar summary](../../../artifacts/lab/runs/20261021-popup-campaign/grammar/summary.md). The older grammar runner has no embedded source stamp; coordinator launch context was `f724fef`, documentation dirty, around 02:05 UTC, and is weaker provenance than the new popup-content campaign.

Ten failed rows remain across four cases; no gold was relaxed or score converted to a pass:

| Case | Observed gap | Disposition / revisit condition |
|---|---|---|
| g092, `한국어를 할 수 있어요` | Two construction misses; lemma 하다 is correct. `할 / 수 / 있어요` exceeds one following eojeol. | Known context bound. KRDICT [explicitly supports the gold construction](https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=86664&nation=eng&nationCode=6). Revisit with an approved bounded-context change and contrast tests; do not infer unseen 있다. |
| g094, `하늘을 나는 새` | Four lemma misses: 나다 instead of intended 날다. | Existing fixture explicitly requires sentence disambiguation beyond current hover input. Revisit with a broader ambiguity corpus and trusted context policy. |
| g099, `(학교)에` | One direct-only miss on 에; OCR-shaped whole token returns 학교. | Direct acquisition isolates a Hangul run; punctuation separates the particle. Revisit whole-token versus cursor-local selection policy and precise native range bounds. |
| g100, `'사랑'이라는` | Three direct-only misses on the following 이/라/는; whole-token path returns 사랑. | Same acquisition divergence. Dictionary legitimacy of a standalone grammatical entry does not settle the app policy. Preserve the current gold until that policy is explicitly decided. |

Luna workers traced these results to the production acquisition/context seams and checked official KRDICT sources. A proposed Lab-only whitespace-token change was rejected because it would hide actual direct-acquisition behavior. No sentence-context expansion, word-specific resolver override, OCR correction or backend tuning was made. Detailed ignored evidence: `grammar-adjudication.md` and `pc003a-resolution-experiment.md`.

## Timing, final state and remaining acceptance

The campaign began at 2026-10-21 19:57 UTC. A System Settings computer-use call blocked about 4h48m until 00:47 UTC; that was not active QA. Work was recorded again through approximately 02:05 UTC. Queued heartbeats and the subsequent usage-limit interval contain no additional hands-on evidence. The human resumed work around 07:59 UTC, when completed artifacts, package startup, actual native permissions, capture refusal, diagnostics and cleanup were checked. Four hours of active QA are **not established**. Automated sampling, builds, waits and blocked time are not relabeled as hands-on testing; finite available checks were exhausted without manufacturing repeated green runs.

The real user configuration was rechecked after the final packaged session and matches the initial parsed JSON. Capture never started in this campaign's observed native sessions. Lab-owned apps exited cleanly; the independently running source app was not modified or terminated. The continuation heartbeat is paused. The built frozen product remains in its attached isolated worktree for a later permission/acceptance session; ignored build output must be preserved before archiving it.

Native reader focus, word-to-popup hover retention, live captured-text accuracy, full frozen-provider execution and Windows/Linux/DPI remain unverified. Normal macOS grants must be established for the **exact built app/service identity** before live hover acceptance. The user must handle any OS authentication directly. No broad Python/Terminal grants, TCC resets, signing changes, installed-app replacement or security bypass were used. OCR comparisons/tuning remain deferred to the user's later branch.

Implementation-side closure uses the existing [redesign Review Handoff](../review-handoffs/hanly-v2-redesign.md); a human-selected Phase B review has not started. Local batch commits only; no push or merge.

## Authorized language-contract polish — 2026-10-22 (in progress)

The human approved a further bounded implementation batch after `ac692ec`.
Local commits `1bc29e7` and `509729b` contain the product fixes and Lab evidence
respectively. No dictionary entries, OCR models/backends or signing policy were
changed. This section supersedes the earlier context diagnosis and grammar score.

### Corrected information seams

- Direct acquisition now preserves a whitespace surface made entirely of Hangul
  and punctuation, including particles after a closing bracket/quote. It still
  requires the pointer to rest on Hangul, refuses secure/nearest/unproven reads,
  and requests precise native bounds for the complete returned span. Mixed
  scripts continue to narrow to the pointed Korean run. Lab direct cases now
  invoke this production coordinator over authored text and synthetic geometry,
  rather than maintaining an independent selection implementation.
- Existing context fields now carry at most two whole neighboring words and
  32 characters on each side, stopping at line/sentence boundaries. This makes
  `한국어를 할 수 있어요` available as a bounded analysis window and produces
  the dictionary-listed `-ㄹ 수 있다` construction. Over-budget words are omitted
  whole; target offsets remain relative to the original selected surface.
- A confirmed Kiwi adapter mismatch was corrected: candidates were built from
  the joined-suffix stream, but their token indices addressed that stream rather
  than the raw normalized tokens exposed in `MorphologyAnalysis`. Span mapping
  now makes these indices reference the actual returned token list. Real-Kiwi
  regressions cover `사과했어요 오늘 학교` and `공부했어요 오늘 학교`. This fixes
  contract consistency; it is not evidence that the two ambiguous lemmas changed.

### Current evidence

The final [grammar run](../../../artifacts/lab/runs/20261022-language-polish/grammar-final/summary.md)
now matches **702/706 headwords** (351/353 in each form), **76/76 construction
checks**, 238/238 required-parts checks and 30/30 auxiliary checks. All four
remaining headword misses are g094. The existing gold was not relaxed. Grammar
now writes source metadata and corpus/dictionary hashes beside the summary;
source was dirty `ac692ec` during this pre-commit gate.

The [popup-content run](../../../artifacts/lab/runs/20261022-language-polish/popup/b44decd7-00fb-48b0-ae3a-5bbc2baee8e6/summary.md)
remains **11/12 source-gold cases**, with six additional diagnostic contrasts
explicitly excluded from that denominator. Exact morphology call inputs and
normalized outputs, selected candidate, dictionary probes, stable entry IDs and
sense hashes distinguish an absent source entry from one that was returned or
available but not selected. Same-headword/POS homographs are distinguished by
entry identity. Dictionary definitions and full popup models remain in ignored
evidence, not product tracing or tracked fixtures.

Convergence checks passed: **2,727 portable tests, 2 skips, 1 strict known xfail**;
Ruff; mypy across **368 files**. Six actual popup models also passed the existing
React integration check (one targeted test, three unrelated tests skipped by
name filter). No frontend code changed in this batch.

### Remaining ambiguity and proposed next boundary

The earlier explanation for g094 was incomplete: actual recorded morphology
input already contains `하늘을 나는 새`. Raw and JOIN_V_SUFFIX best tokenizations
both select 나다; they do not disagree at this seam. Similarly, both streams
select the verb reading of `먹지를` in the carbon-paper case. The correct 날다
and 먹지 analyses occur at rank 3 in a bounded diagnostic request. This is
ranking evidence, not a probability or a safe automatic replacement rule.

A production alternative-analysis policy is **not implemented or approved**.
The smallest candidate proposal is an additive ordered set of normalized
analyses retaining the primary tokens/candidates unchanged, bounded to three
analyses and containing no Kiwi objects or purported confidence percentage.
A separate decision is still required on whether and how to select an alternate
or expose ambiguity to the reader. A dictionary-presence override is unsafe:
valid negative-verb contexts also admit noun alternatives. Existing evidence is
insufficient to derive a universal threshold. The ignored
`20261022-language-polish/kiwi-stream-comparison.{md,json}` records the contrast.

The new diagnostic branch case also illustrates a separate sense-selection
limit: 가지 (branch) exists and is returned by the dictionary, while the popup
leads with another 가지 noun entry (eggplant). This is not missing KRDICT data.
It remains visible in diagnostic observations rather than being silently counted
as a source-gold pass or addressed by a phrase-specific rule.

The official package rebuild at `509729b` succeeded (build UUID
`1ca07330-1018-4ee0-a0f1-b6591cf0c438`, version 1.1.0) and passed the frozen
inventory, native window/React bridge and version checks. It remains uninstalled
in the isolated packaging worktree. An additional test-only commit `f2aeefd`
adds two passing paired acquisition-to-language cases: authored normalized OCR
geometry goes through the real LookupPipeline/WordResolver, while the direct
path uses its production coordinator; both pass identical bounded text into
real Kiwi/local KRDICT and produce equal popup entries/construction. The direct
path makes zero OCR calls. Geometry and OCR text are authored, not recognized;
this is no native acquisition or recognizer acceptance. Final mypy includes 369
files. The two tests passed separately after the 2,727-test portable gate.

Native validation is waiting for the human to establish grants for the exact
package/service identity. A 600-second disposable-profile observation started
at 09:26 UTC (`20261022-062613-run`); before-grant native AX still shows both
permissions missing, capture stopped, runtime ready. The human was asked to
complete the normal macOS settings/authentication flow. No password, TCC reset,
broader Python/Terminal grant or signing workaround is used. The alternatives
proposal is also awaiting the human's explicit decision; it is not approved by
silence. No live capture, OCR or hover acceptance is claimed yet, and the final
Review Handoff update has not been written.


The 600-second native observation ended after **600.7s**, exit 0, zero dropped
events and zero surviving/forced children. There were no captures, OCR calls or
lookups. Host/family RSS peaks were 108.4/525.1 MiB and sampled family mean CPU
11.7%; this permission-wait session is not a lookup benchmark. The test-only
`f2aeefd` commit occurred during it; runtime code and the launched sealed build
were unchanged. Process cleanup was checked, the pre-existing source app was
left untouched, and real configuration still matches the initial snapshot.
Both human questions remain unanswered at this checkpoint. The final new-batch
handoff is pending; no automatic continuation is scheduled.

## Permission diagnosis superseding earlier hypotheses — 2026-10-22

The human explicitly deferred alternative analyses/UI and asked to investigate
the enabled-but-required permission discrepancy. Native inspection confirmed
Hanly and Codex Computer Use enabled in both System Settings panes. Both Hanly
rows' **Show in Finder** action reveals `/Applications/Hanly.app`, an older
installed copy. Normal launch of the final test package outside Lab still
reports 0/2. The installed app also reports 0/2 in an isolated 90-second comparison;
therefore different app paths alone do not explain the issue.

A read-only, three-minute unified security-log query filtered to Hanly then
provided decisive OS evidence: **Failed to match existing code requirement** for
both ScreenCapture and Accessibility. The stored requirement is cdhash
`06dee689bca860d986f10a4444d563793f67c29b`; installed code presents
`ea2fb29e085f8998ab3412003191e1902bbb3964`, and the final package presents
`3e2849c04a57b4b77f323e66d9c65e26d3325111`. The same entries attribute service
requests to the responsible Hanly app and use it as the authorization subject.
The separate-helper hypothesis is not the denial observed here: **stale signing
identity is confirmed**, and the app is reporting a genuine OS refusal.

No TCC database, grant, signature, entitlement, installed file or product code
was changed. The installed comparison exited normally with no acquisition.
Detailed scoped evidence is in ignored `permission-copy-check/summary.md` and
`tcc-own-app.log`. A normal, user-approved refresh of only Hanly's permission
entries for the exact final package is the next step; any OS authentication is
for the human to complete. Do not rebuild that package after granting access.
The ad-hoc identity lifecycle and unclear running-copy information are product
workflow limitations; the evidence does not justify bypassing the probes,
weakening the signing requirement or granting broad Python/Terminal access.

### Authorized refresh result and current acceptance boundary

After explicit human approval and direct human authentication, only Hanly's
entries were removed and re-added through the normal macOS privacy UI, using
the exact final package. Both grants now read **granted inside Hanly**, including
after Recheck. The package was neither rebuilt nor re-signed. Evidence is in
ignored `permission-copy-check/final-build-granted.{txt,png}` and the two refreshed
Settings screenshots. This confirms the old authorization requirement was the
permission blocker; it does not by itself prove capture or hover correctness.

Native Start capture reached Running and engine ready. A 1,201.2-second packaged
Lab observation (`20261022-143258-run`) finished with exit 0 and zero drops, but
no hover/capture/OCR/lookup. The CUA call opening the owned Preview fixture blocked
for approximately 91.6 minutes despite a requested 15-second timeout; that gap
is not active QA. The Lab's automated tour independently rejected the production
package before launch because driven evidence is restricted to the checkout's
debug build. No privacy boundary was bypassed.

A second bounded observation (`20261022-160542-run`) has capture active on the
same package and a disposable profile. Targeted CUA clicks, drag and shortcut
did not produce global hover/native-input traces. A physical mouse check on the
owned g092 image was requested to distinguish automation delivery limitations
from a native observation defect. Popup, actual recognizer and acquisition
acceptance remain unclaimed pending that result. The final handoff is pending.

### Final native Lab coverage after the grant refresh

The human authorized continued unattended testing. An existing, non-prompting
Lab input preflight reported post-event access, listen-event access and AX trust
available; no additional grant was requested or changed. A subsequent normal
142.2-second observation (`20261022-165320-run`) recorded 178 pointer
opportunities, six small captures and two Vision calls. Neither call contained
Hangul; the current unusable result was suppressed and stale work was cancelled.
The short human reply cannot be correlated with a successful Korean popup in
that recording, so it is not counted as such.

Commit `1be34fd` adds **`lab tour --trace-only`**. It uses the existing Lab-owned
raster fixtures, ownership probes, real input driver and request-bound events,
while disabling recognized-content/geometry evidence and the private debug
observer. It emits separate lifecycle records rather than scored tour records.
Scored tours still require debug; trace-only rejects text retention and baseline
comparison. `--inspect-last` keeps the final fixture/app open until normal Quit.
This is a Lab-only extension; the sealed package, signature, production trace
contract and OCR behavior did not change.

| Run | Coverage | Observed result |
|---|---|---|
| `20261022-165956-tour` | 24 seeded words, 16/22/30/40 px, two page themes | 19 popup decisions passed; 5 `NOT_FOUND`; 29.0s, exit 2 |
| `20261022-170357-tour` | One 22px word, held for native inspection | 1 popup decision passed; 202.5s including inspection, exit 0 |
| `20261022-170917-tour` | 153 story targets, including particles, inflections and Latin refusals | 144 decisions passed; 7 `NOT_FOUND`, 2 `UNUSABLE`; 76.8s, exit 2 |

All three completed their planned target sets, observed Vision, recorded zero
drops and exited with no surviving or forcibly terminated children. Exit 2 is
the smoke failure status, not a desktop crash. No linguistic accuracy percentage
is derived from successful presentation. The word failures are w00004, w00008,
w00012, w00013 and w00024; four used 40px, one 16px. The story failures are k030,
k037, k041, k066, k080, k130, k131, k138 and k142. Correct authored selections
through local Kiwi/KRDICT returned the expected headwords in all fourteen cases;
ignored `smoke-missing-word-diagnostic.json` and
`story-missing-word-diagnostic.json` distinguish this from native recognition.

Word/story median pointer-to-answer times were 109.6/123.9ms; cold maxima were
3197.3/3070.6ms. These are bounded observations, not a controlled performance
improvement. Registered baselines use the scored tour/stress mode; no baseline
comparison was made. The 527 story pointer movements retained inside shown
answers are incidental coverage, not an explicit expansion/crossing test.
CUA only exposed the Control Center for the held-target app; its native Window
menu also omitted the nonactivating panel. No popup policy was changed to make
automation easier. New visual expansion and direct-text acquisition acceptance
therefore remain unverified.

Lab regression: **658 passed, one known strict xfail**, plus the final focused
smoke/privacy tests **19 passed** after adding the inspection guard. Ruff across
all requested roots passed; mypy **370 files** passed. An initial Lab-only mypy
invocation found import-untyped errors because it omitted the source package
roots; the authoritative full-root command passed without relaxing typing.
No OCR comparisons or recognition/model tuning were performed. The five word
and nine story misses remain investigation inputs for that deferred workstream.

### Closure state

The final full portable gate passed **2,748 tests, 2 skips and 1 known strict
xfail** in 125.82 seconds after the Lab extension. Real user settings still
match the initial parsed JSON. Final process inventory found no running Hanly
root, frozen service or lookup worker; Lab cleanup reports zero survivors and
zero forced children. The final package remains at source `509729b`, build UUID
`1ca07330-1018-4ee0-a0f1-b6591cf0c438`; only the test harness/docs were changed
after its grants were refreshed. No rebuild/re-sign, installed-app replacement,
push, merge or Phase B review occurred. The continuation heartbeat stays paused.

Four hours of active QA have not been established. Automated sampling, account
limit gaps and the two blocked native-control calls are not active testing.
The latest human-authorized continuation covered the meaningful remaining
checks above and stops at the scoped acceptance limits, with current ambiguity,
native misses and panel-inspection limitations explicitly retained.


## Fourteen-target reproduction and fixture correction — 2026-10-22

Human authorized this separate Phase A continuation from `6260f6f` to reproduce
and correct the native misses. Implementation commit: `3f6e24d`. The final sealed app, its signature, settings,
permissions and production source were unchanged throughout this investigation.
Only the Lab fixture's pointer ownership, its regression assertion and measurement
protocol changed. No recognizer tuning, dictionary correction, provider/contract
extension or popup policy change was needed for these targets.

### Evidenced cause and correction

The full-desktop raster fixture used `ignore_mouse=True`. On this Mac it inherited
the covered Hanly Control Center's custom 32×32 cursor (hotspot 7×1), instead of
owning a normal native cursor. The cursor was composited into the small captured
ROI and covered Korean strokes. In the inspected 서해안 pair, only 322 pixels in
a 20×30 cursor rectangle differed from the cursor-free recapture. Vision then
recognized 서했안. The downstream stages received that incorrect text; this was
not a missing KRDICT entry or evidence of text being lost between providers.

Fresh unchanged-fixture runs reproduced ten of the fourteen misses: four words
and six story targets. Nine of their re-captured inputs matched the live OCR
input's BLAKE2b fingerprint exactly and reproduced the same outcome through the
production worker. The 카운터 failure recapture did not match the live fingerprint,
so its replay is illustrative rather than proof of the original bytes. 키스,
창밖으로, 선반에서 and 끊임없이 did not fail again before the correction; no exact
original frame was retained and their historical cause cannot be proved.

`TourPage` now creates its opaque fixture with `ignore_mouse=False`; the HUD
remains click-through. No cursor is hidden, painted over, moved by the product
or removed from an image. The same authored text, typography, target positions
and ROI geometry remain in place. The inherited `StressPage` receives the same
fix. The portable raster test now guards pointer ownership. Measurement protocol
`session-tauri-family-sampler-250ms-v4` prevents older `v3` timing/memory samples
from becoming a performance baseline for the changed fixture behavior.

### Native and semantic results

| Evidence | Words | Story |
|---|---:|---:|
| Original native decisions | 19/24 | 144/153 |
| Fresh reproduction, unchanged fixture | 20/24 | 147/153 |
| Counterfactual: fixture receives pointer events | 24/24 | 153/153 |
| Tracked correction with explicit target-image export | 24/24 | 153/153 |

These are presentation/refusal decisions. All nine Latin story targets still
refuse correctly. Both full-plan fingerprints match their original recordings:
words `sha256:0223191848ae1a9b`, story `sha256:69edcd1bcde887d3`. This establishes
matched layout, not a valid performance comparison. All listed runs completed
with observed Vision; the final full-plan runs had zero dropped events, zero
surviving/forced children and normal app exit.

For semantic verification, only owned Lab ROIs were explicitly re-captured;
ownership was checked before and after capture and foreign occlusion refused.
Thirteen corrected recaptures matched the live OCR fingerprint. 카운터 initially
differed after the popup closed, so an isolated run captured it immediately after
the capture event, before presentation; that image matched too. Real local
Vision → production word selection → Kiwi → KRDICT replay of these fourteen
byte-matched native inputs returned every expected headword:

| Target | Expected headword | Reproduced contaminated output | Corrected replay |
|---|---|---|---|
| w00004 서해안 | 서해안 | 서했안 | Passed |
| w00008 광견병 | 광견병 | 광겼병 | Passed |
| w00012 체육복 | 체육복 | 체융복 | Passed |
| w00013 키스 | 키스 | Did not recur | Passed |
| w00024 속옷 | 속옷 | 속옻 | Passed |
| k030 창밖으로 | 창밖 | Did not recur | Passed |
| k037 선반에서 | 선반 | Did not recur | Passed |
| k041 골랐습니다. | 고르다 | 곯랐습니다. | Passed |
| k066 끊임없이 | 끊임없이 | Did not recur | Passed |
| k080 역사책을 | 역사책 | 염사책을 | Passed |
| k130 살아남을 | 살아남다 | 삻아남을 | Passed |
| k131 수 | 수 | No OCR candidate contains pointer | Passed |
| k138 카운터 | 카운터 | 칸운터; nonidentical failure recapture | Passed |
| k142 이름은 | 이름 | 9.듬는; Hangul gate refuses mixed selection | Passed |

The replay records exact morphology calls, normalized candidates and dictionary
probes. It is a separate production-worker execution with local real providers,
not recognized-text instrumentation inside the sealed app and not inspection of
the rendered popup. Context outside the target still contains recognition errors
in some small ROIs; these finite successes establish neither perfect OCR nor
correct contextual sense ordering.

Evidence root: `artifacts/lab/runs/20261022-native-miss-reproduction/` (ignored).
Original-byte word replay: `native-hover/`; story replay: `story-hover/`.
Corrected-byte replay: `verified-words/`, `verified-story/` (eight matching story
images), and `early-k138/`. Exploratory scripts and exported pixels/text remain
ignored; they do not enable production evidence retention.

Native run IDs:

- Reproduction: `20261022-231017-tour` and `20261022-231510-tour`.
- Counterfactual: `20261022-231959-tour` and `20261022-232046-tour`.
- Final full-plan verification: `20261022-232427-tour` and `20261022-232520-tour`.
- Matching isolated 카운터 input: `20261022-233152-tour` (1/1 decision).

Source provenance for these recordings is dirty `6260f6f`; the native package
remains the sealed `509729b` build described above. Exploratory recapture/replay
runs are not canonical benchmark baselines. No latency or memory improvement is
claimed. No additional OS grant, signing change, rebuild or installation occurred.

Final checks: full portable gate **2,748 passed, 2 skipped, 1 known strict xfail**
in 125.20s; focused raster/stress/trace-only checks **26 passed**; full-root Ruff
and mypy (**370 files**) passed; diff whitespace check passed. An initial
sandboxed gate had two failures because `ps` execution was forbidden. The five
process-probe tests then passed with normal host access, followed by the complete
passing host gate. No test expectation, typing rule or permission setting was
weakened. The final full-plan tours used the corrected fixture before its
measurement tag advanced to `v4`; the isolated matching-input run records `v4`.
No performance comparison is made across that boundary.

Final process inventory found no Hanly root/service/lookup. Real user settings
still match the initial parsed JSON. The prior untracked QA report is preserved;
the continuation heartbeat stays paused. The existing redesign Review Handoff
is updated last; local batch commits only, no push or merge.

Remaining acceptance is unchanged outside these finite targets: primary-analysis
ambiguities, contextual sense ordering, general cursor-occlusion robustness in
other applications, native direct-text behavior, full visual popup expansion and
focus/crossing inspection, Windows/Linux and DPI coverage. Four hours of active
QA are not claimed. This investigation does not start Phase B.
