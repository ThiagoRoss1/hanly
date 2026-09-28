# Final text acquisition review — 2026-09-22

## Verdict: Changes required

The branch delivers a useful shared language pipeline and native text acquisition
on macOS and Windows. Six narrow review fixes are committed. Do **not merge yet**:
read/refinement can combine different text snapshots, UIA can accept an incorrect
cursor prefix, and dispatcher rejection can consume a hover without fallback.
Fresh Windows OCR-fallback and frozen-artifact evidence is also missing. These
are concrete follow-up implementation/validation tasks, not a request to repeat
the entire review campaign.

## Scope, environment and time

One reviewer reviewed `4f9547b..9962505`: 22 commits, 144 changed files,
+38,058/-1,733. Initial branch was `visual/interface-update`; HEAD and local
upstream were `9962505a9e6dbd5dca2eae8a24ab2cb15249d9be`, with the required
ancestry. No additional product commits existed. The worktree had two preexisting
untracked review instruction files, rather than being entirely clean; they were
preserved and excluded from commits. The six commits below extend the reviewed
product state through `a592108`.

Host: macOS 26.6.2 arm64, CPython 3.13.11 in `.venv`. This was not a Windows or
Linux execution environment. Review began approximately 09:05 UTC, stopped for
usage limits after approximately 15–20 active minutes, and resumed at 17:22 UTC.
The long interruption is excluded from active-review time. Review and convergence finished around 17:31 UTC: approximately 25–30 active
minutes total, within the one-hour limit; this includes drafting the report
while the final gates ran. The prescribed guide, repository rules,
architecture 01–04, execution manual, master plan and routed handoffs were read;
previous acceptance was used to route inspection, not as independent proof.

## Delivered behavior and architecture

Native AX/UIA runs off the UI thread and reports acquisition-neutral `DirectText`.
The shared policy selects a Korean run and checks security, elapsed time, cursor,
source containment and exact retained bounds. A valid `TextSelection` goes through
the same `LanguagePipeline` as OCR. A valid direct dictionary miss is terminal:
it does not rerun OCR. Ordinary current refusals route to capture/OCR once;
stale requests are discarded rather than sent through fallback. Unsupported
platforms retain OCR. Direct success does not construct or call OCR.

Dependency direction remains `hanly-app -> hanly`. UIA, COM, AX acquisition and
Qt lifecycle stay in the app; `LanguagePipeline` is constructible with morphology
and dictionary providers alone. Platform factories select only their own adapter.
Portable import/composition/routing tests passed. The language boundary remains
public and client-independent; clearing stale components corrected one public
contract defect without changing this design.

Invariant **list rows**, rather than incidental diagram citations, match the
Markdown IDs 1:1 and in order: RF 13, CA 16, DAG 18, AEF 22. No authoritative
architecture or diagram was rewritten. There is existing prose drift: the
EasyOCR-only statement in architecture/repository guidance does not describe the
branch's approved campaign behavior, which preserves macOS automatic Vision
selection. Reconcile that decision history with the human when updating
architecture; this review does not silently approve a new architecture.

## AX / UIA / shared-policy comparison

| Boundary | macOS AX | Windows UIA | Shared behavior / evidence limit |
|---|---|---|---|
| Availability | Accessibility permission, platform-local imports | COM worker apartment, platform-local imports | No provider on other hosts; unavailable means OCR |
| Security before reading | Role and now secure **subrole** checked on read and refinement | Password must be explicitly false; offscreen must be false, including refinement | Secure native outcome has no text/bounds; native refusal follows existing OCR policy, not a global prohibition on screen capture |
| Index units | UTF-16 converted at adapter boundary | Prefix text decoded to Python indices; code-point and UTF-16 narrowing candidates | Mixed text/emoji covered; incorrect matching prefix remains open |
| Precise geometry | `AXBoundsForRange` for selected run | Text-range rectangles for selected run | Exact bounds, enclosure and pointer containment required; missing bounds falls back |
| Native timeout | AX messaging budget shorter than overall budget | Connection/transaction setters request 50 ms and must succeed | 40 ms service deadline authoritative, including pending work and late completion |
| Lifecycle | No COM hooks; acquisition on worker | Bind/release on same worker; owned apartment balanced | One worker/one watcher; failed binding refuses instead of reading unbound |
| Snapshot coherence | Re-hits element/re-reads line for bounds | Re-hits element/re-reads line for bounds | Neither ties refinement to original content; open merge-blocking defect |
| Platform evidence | Current Mac native suite below | Prior Windows checkpoint plus portable boundary tests and 59 fake cases now | No new real-Windows claim, no new mixed-DPI or elevated-target claim |

## Findings, ordered by severity

Severity reflects consequence, not a claim that every failure was seen in a live
application. “Reproduction” below uses deterministic synthetic provider data.

| ID / severity | Component and evidence | Impact | Status | Proposed action / revisit trigger |
|---|---|---|---|---|
| F1 / P1 | AX secure subrole omitted; two regressions failed before fix | A password control whose role is `AXTextField` could have native text read | Fixed `2e094df` | Confirm secure controls on current Mac build before release |
| F2 / P1 | UIA unknown password accepted; security not rechecked during refinement; portable regressions | Sensitive/denied state could reach text patterns | Fixed `9318106` | Real Windows password/access-denied smoke after follow-up build |
| F3 / P1 | UIA same-length content mutation between read and refine returns DIRECT with old text; AX has same code structure | Lookup/retained rectangle can describe different content or elements | **Deferred; blocks merge** | Bind refinement to original text and element/range identity; refuse mutations; `text_acquisition.py`, AX/UIA adapters and tests; implement before merge |
| F4 / P2 | `_cursor_index` accepts shorter matching prefix; synthetic `초대받았어요` at index 2 reports index 1 and DIRECT | Cursor-selected dictionary component can be wrong within the same accepted run | **Deferred; blocks merge** | Verify endpoint/pointer correspondence, not only `startswith`; refusal when unverifiable; UIA adapter/tests, before merge |
| F5 / P2 | Dispatcher raises after accepted submission: handled=True, captures=0, lookups=0 | Current hover disappears without OCR fallback | **Deferred; blocks merge** | Reliable UI-thread dispatch/recovery contract and deterministic rejection test; `hover_lookup.py`, Qt dispatcher/service integration, before merge |
| F6 / P2 | Pending deadline unobserved while worker blocked; new event-based regression | Later hover could wait indefinitely despite advertised 40 ms budget | Fixed `59a8c54` | Keep pending timeout and completion-clock regressions |
| F7 / P2 | Bind error previously allowed reads; positive changed-mode HRESULT, ignored timeout setter failure, setup cleanup gaps | Unsafe/half-bound native use and unbounded legacy calls | Fixed `59a8c54`, `9318106` | Windows COM regression run before merge |
| F8 / P2 | ASCII source label passed regex and reached trace | Custom source could leak content into supposedly content-free diagnostics | Fixed `a592108` | Whitelist only known acquisition routes |
| F9 / P2 | Early language result retained previous lexical components; failing regression | Old lexical evidence could accompany current non-success | Fixed `e707501` | Public-context regression retained |
| F10 / P2 | Authoritative Ubuntu mypy log: optional imports unresolved/unused ignores | CI red | Fixed locally `fabceb8`; Linux unconfirmed | Remote Ubuntu checks after separately authorized push |
| F11 / P2 | Windows torch and stale frozen-bundle failures unresolved | OCR fallback cannot be claimed deployable from UIA-only successes | **Missing evidence; blocks merge recommendation** | Fresh Windows environment, forced production fallback, current frozen build; details below |
| F13 / P2 | Existing Mac bundle passes packaged gate despite source stamp `cb2d437`, dated Sept 15; gate compares package versions only | Same-version stale build can appear to validate current source | Deferred evidence/test hardening | Assert expected source commit/build stamp in frozen gate; require fresh artifacts before merge recommendation |
| F12 / P3 | `_narrowed` stops at first matching text even if its rectangle misses pointer | An ambiguous repeated occurrence can refuse despite a later valid candidate | Deferred | Prefer candidate with verified containing bounds; add ambiguous dual-candidate test with F3/F4; ordinary false refusal safely uses OCR |

### Reproductions and proposed larger fixes

**F3:** Use `_Control`, `_Bridge`, `_point` from the existing Windows test doubles.
Start with synthetic `초대`; wrap `bridge.element_at` to replace `control.text`
with same-length `사과` on the second call. Inject that bridge and call
`DirectTextCoordinator(UIAutomationTextProvider()).acquire(_point(0))`.
Observed: `outcome=direct`, selection differs from current text, zero live fake
handles. `_narrowed` validates against the newly read line, not the original
selection. AX `_span_bounds` similarly converts original offsets against a new
line. This is a content-currency defect even when hover/request IDs are current.

Proposed fix: carry a bounded adapter-owned snapshot/token or expected content
through refinement, including element identity, and refuse if it cannot be
validated. Keep native objects confined to the worker and release them on every
path. Preserve the engine seam. Cover same-length replacement, element
replacement, security transition and mutation between intermediate reads. This
is broader than a cheap local guard and was not rushed into this review.

**F4:** On `_Control('초대받았어요')`, replace only the prefix range's `text_of`
answer for `[0:2]` with `초`; leave the full line, narrowed word and geometry
correct. Acquiring at `_point(2)` returns DIRECT with cursor index 1 instead of 2.
Whole-run containment cannot detect that error. The reproduction injects an
inconsistent provider; it does not establish that Chrome currently truncates
prefixes. The public native boundary nevertheless claims conservative refusal.
Add endpoint consistency/character geometry evidence or refuse unverifiable
answers. Do not infer cursor position by dividing a word rectangle.

Repeated `🙂초대 초대🙂` at both occurrences passed synthetic code-point and
UTF-16 providers with no live handles. Existing cases cover emoji, punctuation,
multiline, invalid spans, nearest ranges, negative/fractional boxes and oversized
lines. Two strategies matching different occurrences under provider-specific
clamping/grapheme semantics remain insufficiently tested. Combining-mark
provider semantics require additional native evidence; no universal Unicode
character-unit equivalence is claimed. `_narrowed`'s first-match return is safe
against a non-containing rectangle because common validation refuses it, but
can lose coverage (F12).

**F5:** Use the existing routing `_Service(UNSUPPORTED)` and `_hover_runtime`,
replace runtime dispatcher with one that raises, start a direct request, then
deliver its outcome. Observed: handled=True, captures=0, lookups=0. The real
service catches callback errors, preserving its thread but losing this request.
Recover through an alive UI-thread mechanism; do not capture or manipulate Qt
from the native worker. Explicitly distinguish active-runtime dispatch failure
from intentional shutdown suppression. Tests must cover both.

## Concurrency and native-lifecycle verdict

The service uses one worker and one watcher, one active and at most one pending
job. Superseded pending work is replaced, not accumulated. Delivery has a latch
under the condition and invokes callbacks outside that lock. The review added
pending-deadline observation, deadline enforcement at completion even if the
watcher has not run, and failed-bind refusal. Exceptions become type-only FAILED
outcomes. A watcher with no unanswered jobs waits instead of spinning.
Deterministic event/clock regressions failed before correction and pass now.

The prior claim that a 50 ms UIA floor bounds a pending job was **not acceptable**:
it is a per-call timeout in a multistep acquisition, setter failure was ignored,
and legacy untimed client fallback existed. Pending jobs now time out independently
of a blocked worker. Expired work is not subsequently sent into the provider.
Late native answers cannot publish after the service deadline. No synchronous
COM cancellation is claimed.

Close is idempotent, avoids self-join and uses bounded joins (up to five seconds
per other thread). A stuck native call may leave the daemon worker alive until
it returns; orderly COM cleanup occurs on that worker, not from the UI thread.
The closed check and callback call are not one indivisible action: a callback
already leaving the service can race close. Application currency/shutdown guards
suppress stale lookup/presentation, and Qt callback errors cannot kill the worker.
Thus “no callback invocation can ever race destroyed application state” is too
strong; F5 still needs the explicit dispatcher lifecycle contract. The passing
race tests establish their exercised orderings, not a formal proof of all
interleavings.

COM review against Microsoft's [SDK interface definitions](https://raw.githubusercontent.com/microsoft/win32metadata/main/generation/WinSDK/RecompiledIdlHeaders/um/UIAutomationClient.h)
confirmed all used vtable slots: IUIAutomation2 Release 2, ElementFromPoint 7,
connection/transaction timeout 61/63; Element property/pattern 10/16; TextPattern
RangeFromPoint 3; TextRange Clone/Expand/rectangles/text/move-unit/move-range
3/6/10/12/14/15. Windows x64 GUID is 16 bytes, POINT uses two 32-bit LONGs,
and VARIANT reserves its 24-byte x64 storage; SAFEARRAY is opaque and traversed
with OleAut APIs. Windows calling conventions and signed HRESULT handling were
inspected; macOS `ctypes.c_long` sizes are not Windows ABI execution evidence.

`RPC_E_CHANGED_MODE` is now signed correctly. S_OK/S_FALSE ownership is balanced;
changed-mode does not claim an apartment to uninitialize. This follows
[CoInitializeEx ownership rules](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex).
Failed setup disposes its client and owned apartment; only successfully timed
clients are retained. The worker-local slot is initialized before construction.
Normal interface, BSTR, VARIANT and SAFEARRAY cleanup paths were inspected, and
fake-handle balance passed; this is not a native heap-leak measurement.

Microsoft documents a default 20-second transaction timeout and its HRESULT
contract in [the timeout setter](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomation2-put_transactiontimeout).
The specific 50 ms minimum remains the prior Windows checkpoint's measurement,
not a fresh Mac measurement or a universal end-to-end bound. The signed and
setter-failure regressions verify handling, not that empirical minimum.
[RangeFromPoint](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationtextpattern-rangefrompoint)
may return nearby text, which is why actual bounds remain mandatory.

## Language, components and popup

Focused language/routing/composition/whole-form/component/real-KRDICT selection
passed 181 tests. Exact surface precedes reconstructed whole form; dictionary
probes remain capped at five and deduplicate misses as well as hits. POS and
commonality ordering remains a ranking heuristic, not sense disambiguation.
`초대받았어요` uses cursor-relevant `초대`/`받다` evidence without inventing a
KRDICT entry for `초대받다`; exact `고소득층` remains protected against a wrong
join. Overlap and grammatical/missing-gloss components are contextual form
evidence, not invented definitions. Known compound decomposition limitations
(e.g. `전우애`, `맏사위`) and component-density limits remain; no semantic model
or redesign was added.

Popup integration was sampled through portable and native Qt coverage: compact,
expanded, sticky/copy behavior, retained target, request currency and geometry.
The native convergence result below includes the real Qt window tests. It does
not constitute a new aesthetic review or Windows mixed-DPI certification.
The snapshot defect can still give retention a rectangle for changed content.

## OCR, research and privacy

Production OCR remains the fallback path, with existing macOS Vision behavior
and Windows EasyOCR. Staged diagnostic replay is not evidence of live capture,
worker dispatch or production latency. Wave 7 commit `b0851a8` changes only its
research report; it adds no provider, selector or package. The eight local
synthetic research items are too small and font-specific for a product-wide
accuracy claim. HanlyOCR remains a non-blocking research track.

Freeze remains in memory. Explicit Export is the persistence boundary for
private pixels/text, with validated destinations under the ignored benchmark
artifact root. Export strips internal evidence structurally from ordinary
summaries. Native exception outcomes contain type names; trace source labels now
use a closed whitelist (`ocr`, `accessibility`, otherwise `unknown`). A synthetic
ASCII-content regression failed under the prior regex and passes after the fix.
AX secure-field recognition now uses the documented
[secure subrole](https://developer.apple.com/documentation/applicationservices/kaxsecuretextfieldsubrole),
also verified in the local macOS SDK's `AXRoleConstants.h`.

Portable privacy/export tests passed. The scoped history/path inspection found
no tracked benchmark capture directory (`git log --all -- artifacts/benchmarks`
empty); ignore checks cover the export root. This is not a forensic guarantee
that every prose string across Git history was never seen on screen. Committed
fixtures/reports include Korean examples and historical explicitly exported
examples; no private user screen was captured for this review. No new recognized
screen/accessibility text was written to normal traces or this report: all new
reproduction text is synthetic.

## Windows gate discrepancies

“Same as baseline” explains origin, not acceptability. Actual remote checks were
unavailable: the GitHub connector returned no workflow runs for either the full
or short `9962505` SHA. That is **unknown status**, not green CI. The supplied
Ubuntu mypy failure is authoritative. CI configuration runs portable/lint/mypy
on Ubuntu Python 3.10–3.13, native tests on Windows/macOS/Linux, and frozen gates
in the build workflow; configuration is not an observed result.

| Discrepancy | Classification / CI exposure | OCR-fallback evidence | Smallest action | Merge consequence |
|---|---|---|---|---|
| 12 Torch `c10.dll` failures, WinError 1114 | Unresolved native runtime/environment failure; standalone import succeeding does not identify process-order cause. Windows native CI may expose related failures, but those benchmark cases run in Ubuntu quality | **Weakened**; successful UIA bypass does not prove OCR | Fresh installed environment, reproduce production child with OCR forced, isolate import order/DLL cause if it fails | Blocks evidence-based merge recommendation until fallback works |
| POSIX `resource` collection | Test-infrastructure portability: `peak_rss()` deliberately returns None without resource, test assumes positive value. Ubuntu normally has resource | Does not by itself break OCR | Platform-aware expectation or supported Windows memory measurement | Not a product merge blocker alone |
| Machine-specific benchmark manifest | Synthetic `/Users/someone/screenshots/a.png` test input, not proof of a real leaked manifest. Host path semantics produce different rejection text on Windows; containment still refuses outside root. Ubuntu does not reproduce | No demonstrated fallback impact | Validate PurePosixPath as well as PureWindowsPath/rooted forms; portable diagnostic assertion | Deferred test/path portability correction, not a privacy leak finding |
| Editable version 0.5.2 | Stale environment; source is 0.5.3, fresh CI install avoids this mismatch | Invalid version gate, not proof of OCR defect | Reinstall editable packages | Not independently blocking after reinstall |
| Oversized pytest IDs | Windows environment-variable limit in PYTEST_CURRENT_TEST; test infrastructure, not product | Can interrupt validation | Explicit short IDs included in `a592108`; rerun Windows portable tests | Fixed locally; Windows confirmation outstanding |
| Sept 15 frozen bundle failure | Stale artifact plus unresolved Torch runtime capability; not built from this branch. Build CI is the relevant gate, result unavailable | **Weakened**; neither success nor failure proves current artifact | Build current source, require packaged gate, verify identity and isolated-profile OCR | Fresh artifact/fallback evidence required before merge recommendation |
| 26 Windows mypy POSIX-stub errors | Type-check host/test portability mismatch; intended Ubuntu job differs. Not dismissed as baseline and not suppressed | No runtime failure follows solely from these errors | Narrow platform guards/stubs or explicit supported type-check host; keep Ubuntu clean | Not independently blocking if intended Linux typing passes; Linux CI still pending |

No fresh Windows execution, elevated-target/UAC test, 125/150/200% scaling or
mixed-monitor transition test occurred. Do not present fake-provider passes as
Windows-native validation. Mixed-DPI remains a documented release risk; no
speculative coordinate transform was added.

## Validation and fixes committed

| Check | Result |
|---|---|
| Focused Vision | Sandboxed: 24 passed, 2 skipped, 2 native recognition failures; same focused check with native-framework access: **27 passed, 1 skipped**. Host restriction diagnosed, no OCR behavior patch |
| Service / shared policy / routing after fixes | **92 passed**; event/clock deadline regressions demonstrated failing baseline |
| UIA new portable boundary tests | **15 passed**; security, HRESULT ownership and timeout failures covered |
| Existing UIA synthetic provider cases on Mac | **59 passed**, three real COM tests explicitly excluded |
| AX / common / platform focused group | **90 passed**; secure subrole regressions demonstrated failing baseline |
| Language / routing / components / real KRDICT group | **181 passed** |
| `python -m pytest --suite portable` | **2111 passed, 2 skipped**, 80.83 s |
| `python -m pytest --suite native` | **110 passed**, 126.95 s, on Mac |
| `python -m pytest --suite packaged` | **3 passed**, 12.29 s, against the existing **stale Mac bundle**; not validation of reviewed source |
| `python -m ruff check packages packaging tests tools benchmarks` | **All checks passed** |
| `python -m mypy packages packaging tests tools benchmarks` | **Success: 284 source files** on Mac; remote Ubuntu confirmation required |

The packaged gate used `dist/macos/Hanly.app`. Its embedded
`hanly_app/assets/hanly-build.json` says version 0.5.3, source
`cb2d437bbb7b856b0839c0a1907b0a3d96f54c27`, built
2026-09-15T20:44:55Z. `verify_frozen_identity()` checks package versions, not
source identity, so passing all three cases does not validate this branch or
its review fixes. Add a source/build identity assertion to the gate and rebuild
both supported native artifacts for current-source release evidence (F13).
No frozen artifact was rebuilt during this time-boxed review.

The project `.venv/bin/python` was used throughout. Native-framework execution
required leaving the filesystem sandbox. No unfiltered suite was necessary.
Local convergence logs are `/tmp/hanly-final-{portable,native,packaged}.log`;
they are ephemeral supporting output, not durable product evidence.

Each logical fix has its own commit, author Thiago Rossi, without attribution
trailers:

| Commit | Fixed now |
|---|---|
| `fabceb8` — `fix: type optional vision framework imports` | Precise Foundation/objc mypy overrides; removed unnecessary inline ignores; runtime missing-pyobjc error unchanged |
| `59a8c54` — `fix: enforce pending acquisition deadlines and worker readiness` | Pending watcher, completion deadline, failed-bind refusal, safe coordinator exception outcome |
| `9318106` — `fix: fail closed at the UIA native boundary` | Signed HRESULT; timed client required; setter/setup cleanup; explicit non-secure/non-offscreen state before reads/refinement |
| `2e094df` — `fix: refuse secure AX subroles before reading text` | Secure subrole recognized on both native paths |
| `e707501` — `fix: clear stale lexical components from lookup evidence` | Public language-context cleanup on early exits |
| `a592108` — `fix: restrict acquisition traces to known route labels` | Source whitelist and short parameter IDs |

The final separate documentation commit is `docs: record final text acquisition
review`; it contains this report and only a concise Windows-handoff addendum.
The two untracked instruction documents are intentionally not included.

## Deferred, dismissed and exact next actions

Deferred with explicit triggers: F3–F5 must be implemented and tested **before
merge**, F11 requires fresh Windows runtime/artifact evidence before recommending
merge, F12 belongs with the native range fix; F13 requires current-source artifact
identity validation before treating packaged results as branch evidence. Windows path/resource typing test
portability should be corrected when making Windows portable validation clean.
Architecture prose reconciliation requires human confirmation of the existing
approved decision trail. Semantic disambiguation, richer components, new OCR,
DOM integration and speculative DPI transforms remain outside this review.

Dismissed with evidence: no wrong UIA vtable slot or POINT signature was found;
no extra COM package is needed; no second language pipeline was introduced;
normal repeated text/emoji cases do not by themselves prove a duplicate-occurrence
bug; a single non-containing rectangle is safely refused by common policy; the
sandbox-only Vision failures disappeared with native framework access. None of
these dismissals clears F3/F4 or proves universal native memory safety.

1. Implement coherent native snapshots and cursor validation; include mutation,
   repeated-candidate and shorter-prefix regressions, plus AX parity.
2. Establish recoverable UI-thread delivery and shutdown semantics; demonstrate
   current refusal reaches OCR once on dispatcher recovery, while closed/stale
   work does not run capture or presentation.
3. On Windows, reinstall current source, run native/boundary tests, force an OCR
   fallback through the production child, and rebuild/test the frozen artifact
   with required capabilities and current source/build identity. Resolve any Torch
   failure; also rebuild the Mac artifact, whose local passing gate was stale.
4. Obtain passing Ubuntu quality checks for the optional-import correction after
   a separately authorized push. Record remaining mixed-DPI/manual limitations.
5. The human can then decide merge based on those specific fixes and results;
   this run neither pushes nor merges and does not begin another review cycle.

**Nothing was pushed, merged, amended, rebased, squashed or reordered.**
