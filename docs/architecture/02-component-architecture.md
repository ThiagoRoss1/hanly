# Hanly Component Architecture

Textual companion to the approved [Hanly Component Architecture](visual/Hanly%20Component%20Architecture.html) diagram.

## Purpose

This view defines module ownership, responsibilities, interfaces, seams, adapters, and allowed dependency direction for the V1 monorepo. It is not a runtime sequence or an implementation plan.

## High-level boundary

The governing package rule is:

```text
hanly-app → hanly
hanly → NEVER depends on hanly-app
```

`hanly` is the reusable, client-independent engine. It contains OCR orchestration, Korean linguistic analysis, dictionary lookup, local resource understanding, and UI-independent contracts. It contains no windows, mouse hooks, hotkeys, tray behavior, PyQt6, pywebview, or desktop lifecycle logic.

`hanly-app` is the desktop client. It owns OS integration, capture, desktop lifecycle, asynchronous job execution, UI, settings, and remote resource delivery. Hanly Desktop V1 is the engine's first client, not the definition of the engine itself. The end-user desktop product may still be presented as Hanly while the internal dependency direction remains `hanly-app → hanly`.

### Engine reuse and distribution

The `hanly` engine is expected to be independently distributable as the Python package `hanly`, including through PyPI (`pip install hanly`), so developers can consume it without Hanly Desktop. This is a concrete initial distribution and consumption model, not Hanly's entire architectural identity, and the exact public Python API is not designed here.

Direct Python library users, other Hanly applications, developer tools, CLI-style clients, backend services, future HTTP/API wrappers, browser-related backends or integrations, and other projects may consume the engine where appropriate. These are possible consumers, not promised integrations or new V1 deliverables. Client- and transport-specific concerns such as routes, request / response transport, authentication, server lifecycle, OpenAPI, and web frameworks remain outside the engine core.

Reusable does not mean generic for every possible use case and does not require a plugin framework or abstractions for hypothetical universality. Python is the initial implementation and distribution environment, not a permanent architectural constraint. Performance-critical internals may later use native implementations or extensions behind clear public contracts when justified, without selecting a native language or speculative native seams now.

## Hanly engine

### Contracts and models

The engine owns shared conceptual models. They contain no UI logic and no external-library objects:

- `ROIImage` / `PixelFormat`: normalized, library-independent OCR input. Raw bytes plus an explicit format, so no PIL, NumPy, Qt, or EasyOCR object crosses the seam.
- `Point` / `Quad`: OCR geometry as four float corner points, preserving tilted and rotated text.
- `BoundingBox`: axis-aligned rectangle derived from a `Quad` when a rectangle suffices.
- `OCRResult`: normalized recognized text, confidence, and quadrilateral geometry.
- `TokenAnalysis`: normalized token, lemma / dictionary form, morphology, and part-of-speech analysis.
- `DictionaryEntry`: normalized dictionary result.
- `LookupResult`: UI-independent result containing what a client needs to handle a successful lookup, a normal empty / not-found / unusable outcome, or a processing error when appropriate. It may carry useful partial or diagnostic information. A status/result discriminator is required conceptually, but its exact Python representation is not fixed here.
- `ResourceMetadata`: normalized local resource identity, version, state, and compatibility metadata.

These contracts are used by providers, `WordResolver`, and `LookupPipeline`. External-library-specific types must be converted before crossing the provider seam.

### Provider abstractions and adapters

Each provider interface is an engine seam. Concrete adapters satisfy those interfaces:

| Provider interface | Contract | Initial adapter(s) | External dependency |
| --- | --- | --- | --- |
| `OCRProvider` | `ROIImage` in; normalized `OCRResult[]` out, in reading order | `EasyOCRProvider` (V1) | EasyOCR |
| `MorphologyProvider` | Korean text in; `TokenAnalysis` out | `KiwiProvider` | Kiwi / kiwipiepy |
| `DictionaryProvider` | Dictionary-form lookup in; normalized `DictionaryEntry` data out | `KRDICTProvider` | Processed KRDICT in local, read-only SQLite |

> **Current OCR decision (2026-08-26):** `EasyOCRProvider` is V1's only OCR implementation. The Paddle adapter, backend selector, managed Paddle model resources, and Paddle-only recognition-first hover fast path were removed at the human's direction. First launch provisions only `krdict`; EasyOCR owns its model storage. `OCRProvider` remains the one provider seam for a future approved second adapter. The 2026-08-24 decision and its operational snapshot are historical and superseded.

The provider seam remains available for a future approved implementation, but V1 composition constructs `EasyOCRProvider` directly and has no backend selector. `LookupPipeline` knows only `OCRProvider`, not the concrete OCR implementation. Likewise, it does not know Kiwi, KRDICT, or SQLite.

### WordResolver

`WordResolver` chooses the relevant Korean text or segment from normalized `OCRResult` values, their `Quad` geometry, and target / cursor context. It hit tests against the four detected corners rather than an inflated rectangle, so tilted text resolves correctly; the derived `BoundingBox` remains available for coarse checks. Its inputs remain conceptual engine data: it has no PyQt6, global mouse-hook, or popup responsibilities.

### LookupPipeline

`LookupPipeline` is the engine's primary lookup orchestrator:

```text
input
→ OCRProvider
→ WordResolver
→ MorphologyProvider
→ DictionaryProvider
→ LookupResult
```

Its interface hides concrete OCR, morphology, dictionary, database, and UI implementations. It depends on contracts and provider abstractions only.

### ResourceManager

`ResourceManager` understands local resources. It:

- locates required local resources;
- validates availability and readability;
- validates versions;
- validates schema compatibility;
- validates hashes / checksums;
- provides validated paths, configuration, and `ResourceMetadata` to application/composition wiring;
- reports resource states such as `valid`, `missing`, `outdated`, or `incompatible`.

Application/composition wiring obtains validated resource paths and configuration from `ResourceManager` and supplies each concrete provider with the explicit resources it requires during construction or configuration. Providers therefore do not need to depend directly on `ResourceManager`. `LookupPipeline` remains unaware of resource location and depends only on provider interfaces and normalized contracts.

The V1 plan distinguishes four ownership layers: provider and engine implementations live in `hanly`; HAN-15 establishes the official ResourceManager-backed EasyOCR + Kiwi + KRDICT runtime composition in application wiring; later desktop capabilities consume that runtime for interaction and presentation; and still-later update/distribution capabilities acquire and deliver resources. Concrete composition does not move provider policy into UI code or pull remote resource delivery forward.

`ResourceManager` has no UI, GitHub Actions, download-progress, or update-UX responsibility. This composition responsibility does not prescribe a dependency-injection framework or introduce a new facade.

## Hanly desktop application

### Desktop lifecycle

`DesktopController` coordinates desktop lifecycle only: startup, shutdown, starting capture, pausing / resuming capture, opening the Control Center, and quitting. It contains no linguistic logic.

`ConfigManager` owns desktop / client configuration such as hotkeys, hover delay, capture mode, monitor / region selection, OCR implementation status, theme, popup preferences, and update preferences. Application configuration remains distinct from engine-processing configuration; the engine receives only the processing values it needs.

### Input and capture

- `MouseObserver` observes global cursor movement and position and emits events to `HoverController`.
- `HoverController` owns debounce, hover delay, cursor stability, and the decision to start a lookup. It performs no OCR.
- `CaptureService` captures screenshots and ROIs. Hover prefers a small ROI around the cursor over continuous full-screen OCR.
- `HotkeyService` registers and handles global hotkeys for manual lookup, start / pause capture, and future actions.

### Lookup execution

`LookupController` owns application/runtime lookup state: request identifiers, stale-request handling, current cursor / context, bounded latest-wins job submission, receiving `LookupResult`, and forwarding a current result to the popup.

`JobExecutor` / worker runs OCR, `LookupPipeline`, and other potentially blocking operations off the UI thread. It must prevent stale hover work from accumulating in an unbounded queue and should cancel or suppress superseded work where reasonably possible. Cooperative cancellation may be observed between processing stages when supported; final request-currency validation remains mandatory before presentation.

```text
LookupController → JobExecutor / Worker → LookupPipeline
```

### User interface

- `PopupController` receives a completed `LookupResult`, decides placement, and owns popup lifecycle.
- The PyQt6 popup renders successful and normal non-success result states. It knows nothing about EasyOCR, Kiwi, or KRDICT.
- The Control Center uses pywebview with HTML, CSS, and JavaScript. It exposes capture start / stop, target / region selection, settings, application and resource status, dictionary status, OCR implementation status, update controls, diagnostics, preferences, hover delay, and hotkeys. JavaScript contains no linguistic logic and talks to Python through the pywebview bridge.
- `TrayService`, initially using pystray, exposes application status, pause / resume, opening the Control Center, and quit.

### Resource delivery

`UpdateService` / `ResourceFetcher` obtains remote resources and update information. It may query remote metadata or a manifest, check availability, download resources, expose progress, and hand downloaded resources to `ResourceManager` for validation. GitHub Releases is the represented remote adapter.

```text
UpdateService / ResourceFetcher → ResourceManager
```

The update module is non-UI infrastructure. The Control Center may consume it, but it does not require the Control Center to exist.

## Important boundary distinctions

### LookupController vs LookupPipeline

`LookupController` is desktop application/runtime orchestration. It owns request currency, cursor context, worker submission, and result forwarding.

`LookupPipeline` is reusable engine lookup orchestration. It transforms an image / ROI and target context into a `LookupResult` through provider interfaces and `WordResolver`.

The app controller may depend on the engine pipeline; the engine pipeline never depends on the app controller.

### ResourceManager vs UpdateService

`ResourceManager` understands and validates local resources and compatibility.

`UpdateService` / `ResourceFetcher` obtains remote metadata and resources, reports delivery progress, and hands resources to `ResourceManager`.

```text
the engine understands resources
the app obtains resources
```

The engine must function without GitHub Releases. `ResourceManager` does not own remote update UX, and `UpdateService` does not decide local compatibility independently of `ResourceManager`.

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.** Application/composition wiring asks `ResourceManager` for validated paths and configuration, then supplies those values explicitly to concrete providers. Providers and `LookupPipeline` do not depend directly on `ResourceManager`.

### UI boundary

UI code consumes normalized contracts, chiefly `LookupResult` and resource/update state. It must not depend directly on EasyOCR, Kiwi, KRDICT, or SQLite, and library-specific objects must not leak into it.

## External dependency ownership

| External dependency | Owning adapter / module |
| --- | --- |
| EasyOCR | `EasyOCRProvider` |
| Kiwi / kiwipiepy | `KiwiProvider` |
| KRDICT | `KRDICTProvider` |
| SQLite (local, read-only at runtime) | `KRDICTProvider` |
| PyQt6 | `PopupController` / PyQt6 popup |
| pywebview | Control Center |
| pystray | `TrayService` |
| GitHub Releases | `UpdateService` / `ResourceFetcher` |

## Dependency invariants

- **CA-INV-01 (diagram invariant 1):** `hanly-app` may depend on `hanly`.
- **CA-INV-02 (diagram invariant 2):** `hanly` must never depend on `hanly-app`.
- **CA-INV-03 (diagram invariant 3):** The engine contains no UI-specific or desktop-lifecycle logic.
- **CA-INV-04 (diagram invariant 4):** UI modules never depend directly on EasyOCR, Kiwi, KRDICT, or SQLite.
- **CA-INV-05 (diagram invariant 5):** `LookupPipeline` depends on provider interfaces and normalized contracts, not concrete external libraries.
- **CA-INV-06 (diagram invariant 6):** Heavy processing runs through `JobExecutor` / a worker, never on the UI thread.
- **CA-INV-07 (diagram invariant 7):** `ResourceManager` owns local resource state and compatibility, not remote update UX.
- **CA-INV-08 (diagram invariant 8):** `UpdateService` may depend on remote systems; the engine does not require GitHub Releases to function.
- **CA-INV-09 (diagram invariant 9):** External-library objects do not cross provider seams.
- **CA-INV-10 (diagram invariant 10):** The architecture keeps `hanly` reusable for future non-desktop clients without adding speculative client modules now.

> **Derived from approved cross-document architecture; not stated directly in this visual diagram.**

- **CA-INV-11:** `MouseObserver` observes; `HoverController` decides when to request lookup; neither performs OCR.
- **CA-INV-12:** `PopupController` consumes a completed `LookupResult`; it does not orchestrate linguistic processing.
- **CA-INV-13:** Application/composition wiring injects validated resource paths and configuration into concrete providers; providers and `LookupPipeline` do not depend directly on `ResourceManager`.
- **CA-INV-14:** Desktop lookup execution is bounded / latest-wins, with final request-currency validation before presentation.
- **CA-INV-15:** `LookupResult` can model success, normal non-success, and processing-error outcomes without treating every non-success as an exception.
