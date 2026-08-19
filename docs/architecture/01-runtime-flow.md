# Hanly Runtime Flow

Textual companion to the approved [Hanly Runtime Flow](visual/Hanly%20Runtime%20Flow.html) diagram.

## Purpose

This view defines how the Hanly V1 desktop application starts and how an automatic hover lookup moves from cursor observation to a Korean dictionary popup. It describes runtime ordering, state, concurrency, and the interfaces crossed during a lookup.

It does not define package ownership, implementation sequencing, browser or mobile behavior, DOM integration, subtitle processing, or HanlyOCR research.

> **Decision update:** The approved visual diagram predates a later V1 scope decision. EasyOCR is no longer part of V1. `OCRProvider` remains an abstraction, with `PaddleOCRProvider` as the V1 implementation. Provider configurability remains an architectural capability for possible future implementations.

## Startup flow

Startup is ordered as follows:

1. **Start Hanly.**
2. **Load Configuration.** Desktop and processing choices needed for initialization become available.
3. **Initialize Resource Manager.** `ResourceManager` locates and validates the local resources needed by the configured runtime:
   - OCR models are available;
   - processed KRDICT data is available;
   - the SQLite database is present, readable, and schema-compatible;
   - required application assets are present.
4. **Initialize Providers.** The provider categories may initialize in parallel:
   - `OCRProvider`: the configured V1 implementation is `PaddleOCRProvider`.
   - `MorphologyProvider`: Kiwi / kiwipiepy is the initial implementation.
   - `DictionaryProvider`: KRDICT backed by read-only SQLite is the initial implementation.
5. **Initialize Lookup Pipeline.** `LookupPipeline` orchestrates target resolution, linguistic analysis, and dictionary lookup through provider contracts. It never references PaddleOCR, Kiwi, or KRDICT directly.
6. **Initialize Desktop Services.** Global hotkey, mouse observer, capture service, and system tray become available.
7. **Prepare or open the Control Center.** Its HTML, CSS, and JavaScript interface is presented through pywebview.
8. **Enter `READY`.** Hanly is loaded and can activate capture and lookup behavior.

Provider initialization is the startup convergence point: the configured OCR adapter, morphology adapter, and dictionary adapter must be available before `LookupPipeline` can serve lookups. The desktop services and Control Center are then prepared before the application reports `READY`.

## Manual lookup flow

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

The Runtime Flow diagram does not contain a separate manual-hotkey sequence. The approved Implementation DAG identifies the intended vertical slice as:

```text
cursor over word
→ hotkey
→ capture ROI
→ JobExecutor
→ LookupPipeline
→ LookupResult
→ popup
```

This establishes that manual lookup crosses the same capture, worker, engine, result, and popup seams used by hover lookup. The Implementation DAG also requires manual lookup to precede automatic hover integration and remain a V1 feature.

> **Open clarification:** The Runtime Flow diagram does not specify the manual path's request-state rules, capture-mode preconditions, or exact trigger-to-capture lifecycle. Those details must not be inferred from the hover flow without an approved clarification.

## Hover lookup flow

Hover lookup begins from `READY` while capture mode is active:

1. `MouseObserver` detects global cursor movement and position.
2. When the cursor stops, `HoverController` starts its debounce / hover delay.
3. After the delay, `HoverController` checks whether the cursor is still valid.
   - If it is not valid, the attempt is cancelled and observation resumes.
   - If it is valid, Hanly reads the current cursor position.
4. `CaptureService` captures a small region of interest (ROI) around the cursor. It does not continuously capture and OCR the full screen.
5. The lookup job is submitted to a worker. Everything from OCR through construction of the result runs off the UI thread.
6. `OCRProvider` receives the image / ROI and returns `OCRResult[]`. Each result contains recognized text, confidence, and a bounding box / coordinates.
7. `WordResolver` combines the OCR results, their bounding boxes, and cursor context to choose the text segment relevant to the hover.
8. `MorphologyProvider` analyzes that Korean segment and produces relevant tokens, lemma / dictionary form, morphology, and part of speech where available.
9. `DictionaryProvider` looks up the lemma. The initial adapter is KRDICT backed by read-only SQLite; the V1 target is Korean-to-English data plus the metadata needed by the popup.
10. `LookupPipeline` builds a UI-independent `LookupResult`. It can describe a successful lookup, a normal empty / not-found / unusable outcome, or a processing error when appropriate, with useful partial or diagnostic information for the client.
11. Before presentation, the app checks whether the request is still current.
    - A superseded request is discarded because the cursor may have moved while worker processing was in progress.
    - A current request continues to presentation.
12. `PopupController` chooses a popup position from the cursor and available screen area.
13. The PyQt6 popup renders the completed `LookupResult` next to the cursor.
14. Mouse observation continues. The loop remains active until capture mode is paused or cancelled.

The hover delay is configurable and must be tuned empirically. Initial experimentation is expected around roughly `80–250 ms`; this is an experimental range, not a fixed performance SLA.

## Concurrency and worker constraints

- The OCR, resolution, morphology, dictionary, and result-building work runs through `JobExecutor` / a worker, not on the UI thread.
- OCR is explicitly treated as expensive and must never block the UI thread.
- The cursor may move while a job is running. A request identifier or equivalent current-request check is required so superseded results can be discarded before presentation.
- Desktop lookup execution is latest-wins / bounded: stale hover jobs must not accumulate in an unbounded queue. Superseded work should be cancelled or prevented from accumulating where reasonably possible, and cooperative cancellation may be checked between processing stages when supported.
- Cancellation is a resource-control mechanism, not the final correctness gate. Request currency must still be validated immediately before presentation.
- Provider initialization may occur in parallel, but all configured providers converge at `LookupPipeline` initialization.
- Hover observes cursor activity and captures a small ROI only after the debounce and stability check. It does not perform continuous full-screen OCR.
- A full-monitor capture mode describes the available capture area; it does not authorize continuous full-screen OCR for hover.

## Runtime invariants

- **RF-INV-01 (diagram rule 1):** OCR does not detect hover. Hover behavior belongs to `MouseObserver` and `HoverController`.
- **RF-INV-02 (diagram rule 2):** Capture happens before OCR.
- **RF-INV-03 (diagram rule 3):** Morphology and dictionary lookup happen before popup presentation.
- **RF-INV-04 (diagram rule 4):** The popup receives an already processed, UI-independent `LookupResult`.
- **RF-INV-05 (diagram rule 5):** PaddleOCR, Kiwi, and KRDICT are adapters behind provider interfaces; they are not direct dependencies of `LookupPipeline`.
- **RF-INV-06 (diagram rule 6):** Heavy processing does not run on the UI thread.
- **RF-INV-07 (diagram rule 7):** Results from superseded requests may be discarded after cursor movement.
- **RF-INV-08 (diagram rule 8):** During normal use, Hanly does not visually modify the target application except through its popup and temporary overlays needed for region selection.
- **RF-INV-09 (diagram rule 9):** Full-monitor mode does not imply continuous full-screen OCR; hover prefers an ROI near the cursor.

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

- **RF-INV-10:** The configured V1 OCR implementation is `PaddleOCRProvider`; `LookupPipeline` remains coupled only to `OCRProvider`, which preserves future provider configurability.
- **RF-INV-11:** Desktop lookup execution is bounded / latest-wins, while final request-currency validation remains mandatory before presentation.
- **RF-INV-12:** `LookupResult` represents successful, normal non-success, and processing-error outcomes without requiring every non-success to be an exception.

## Failure and state considerations

The approved flow defines these states and failure-relevant decisions without prescribing a broader error architecture:

- Local resources can fail validation because they are missing, unreadable, outdated, or schema-incompatible. Hanly must not claim `READY` before required runtime resources and providers are usable.
- An invalid cursor after the hover delay cancels the lookup attempt and returns to observation.
- A stale result is a normal concurrency outcome, not a result to display; it is discarded and observation continues.
- No usable OCR text, no resolvable Korean segment, no dictionary entry, or insufficient confidence are normal lookup outcomes that `LookupResult` must be able to represent. A processing failure may be represented as an error outcome when appropriate. Clients may receive useful partial or diagnostic information with these outcomes.
- The capture loop remains active until the user pauses or cancels capture mode.
- Popup placement must account for the cursor and available screen area.
- The diagram does not define retry, fallback, notification, or recovery policy for provider initialization or lookup failures.

> **Open clarification:** Startup failure presentation and recovery behavior are not specified by the approved Runtime Flow.
