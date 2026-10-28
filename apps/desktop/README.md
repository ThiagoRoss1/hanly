# Hanly Desktop

The official desktop is a Tauri native root with React-owned Control Center,
popup, and capture-area windows. Rust owns the native event loop, tray, global
shortcuts, platform adapters, and supervised-process lifecycle. A private
versioned JSONL bridge connects it to the Qt-free Python desktop service; that
service retains capture, hover and lookup policy, settings, resource
provisioning, diagnostics, and the existing verified updater. OCR, Kiwi, and
KRDICT run in the isolated lookup child. The reusable `hanly` engine remains
independent of desktop code.

The bridge caps frames at 1 MiB and concurrent requests at 32. Rust derives the
calling window's identity and authorizes each method before dispatch. The
service and lookup child use bounded private pipes; the product starts no Node
server. Selection snapshots stay transient in memory, and neither tracing nor
logs contain recognized text or screen pixels.

The installed product keeps the `io.github.thiagoross1.hanly` bundle ID, V1
settings and resource paths, and the `hanly-desktop` executable name. Its
Python service is packaged under `resources/hanly-service/` on Windows and
Linux, or `Contents/Resources/hanly-service/` inside `Hanly.app`. The build
inventory rejects missing provider inputs and Qt, WebEngine, pywebview, or
pystray runtime payloads.

## Source development

Use Python 3.10+, Node 22, and Rust 1.99. Install the engine before the desktop
package, then build the React assets and a debug native root with its embedded
frontend:

```sh
python -m pip install --upgrade pip
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]"
npm ci --prefix apps/desktop
npm run --prefix apps/desktop check
npm test --prefix apps/desktop
npm run --prefix apps/desktop test:ui
npm run --prefix apps/desktop build
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
cargo build --manifest-path apps/desktop/src-tauri/Cargo.toml --features custom-protocol --locked
```

The source `hanly` command and `python -m hanly_app` forward supported options
to that existing debug executable. The debug root starts the checkout's
`.venv` Python service. There is no automatic compile, second Python UI, or Qt
fallback. `HANLY_DESKTOP_EXECUTABLE` can point the Python command at another
already-built native executable.

For the live Vite development workflow only, use `npm run tauri -- dev` from
this directory after installing frontend dependencies. This command uses a
local development server; it is not the product's user launch path.

`npm run preview:mock` opens `preview.html`, which renders the React views in
a browser against fixture state through Tauri's `mockIPC`. Choose a view with
`?view=popup|region_selector`, a popup with `&sample=school|long|refusal` and
`&theme=light|dark`. Control Center styling can be inspected with
`&platform=windows` and `&permissions=unsupported`; these only alter preview
fixtures. The popup's measured size appears in the tab title. Use Safari for
WebKit-faithful metrics. It checks layout and content only: native frames,
clipping, focus, shortcuts and permissions need the real desktop app. Vite
builds only `index.html`, so the preview never ships.

The pixel interface uses the supplied artwork under `public/design/`. Appearance
preferences are stored by the Python settings service: `app_font` and `popup_font`
independently select `pixel` or `normal` text (app default `pixel`, popup default
`normal`), and
`sidebar_layout` is `normal` or `compact`
(default `normal`). Older settings files receive those defaults. Windows at
760 logical pixels or narrower also use the compact rail. System theme follows
the desktop; scene and mascot animation pause when hidden or reduced motion is
requested.

The Control Center shell lives in `src/pages/ControlCenterPage.tsx`; each of its
six sections is a separate module in `src/pages/controlCenter/`. Shared controls
live in `src/components/controlCenter/`, popup presentation in
`src/components/popup/`, and the village renderer and layer order in
`src/components/village/`. Layout, spacing and type sizes use Tailwind utilities.
The focused pixel styles own palette variables, nine-slice artwork, native
range parts and responsive artwork fitting; the legacy interface cascade is
removed. Saving one preference keeps unrelated controls and the scene mounted.

On macOS the Control Center reserves a 40px overlay titlebar above the pixel
frame, retaining the native close, minimize and fullscreen controls with clear
space around them. Its blank top strip after the controls drags only the
Control Center window. Windows and Linux retain their native titlebars.
The Windows client is transparent beneath the original ornamental frame. The Windows popup disables native shadows to avoid the extra white system border on a frameless window.
Popup focus, native placement and measurement are independent
of this Control Center decoration.

Buttons retain their jewel artwork behind padded content, alongside the slider
and popup frame artwork. The runtime panel, cloud and compact plaque use the
editable clean SVG variants under
`public/design/media/assets/panels/`. Their shared generator is
`tools/design/build_clean_frames.mjs` at the repository root. Source changes
require rebuilding the embedded frontend/native executable and restarting the
app; an already-open debug app keeps displaying its previous frontend build.

The development preview additionally accepts `font=pixel|normal`,
`app_font=pixel|normal`,
`navigation=compact`, `activity=stopped|armed|running|preparing|error`,
`permissions=missing`, and `update=downloading|failed`. These are fixture states,
not native acceptance evidence. The popup preview implements the same
measure-before-presentation exchange as the host, with fixture layout bounds.

The `dev` and `runtime` dependency sets install no Python UI framework.

## Build and validate the product

Build the complete product on its target operating system:

```sh
npm ci --prefix apps/desktop
python tools/prepare_easyocr_models.py
python tools/build_package.py
```

`tools/build_package.py` embeds the build identity, freezes the Python service,
stages native updater resources, generates an active Tauri bundle
configuration, builds the Tauri root, verifies the resulting product, and
creates the existing platform archives and update metadata. The checked-in
Tauri config keeps standalone bundling disabled because its resource paths
exist only during this coordinated build. Do not use a standalone Tauri bundle
as the installable product.

The official layouts and preserved updater flow are documented in
[`packaging/README.md`](../../packaging/README.md). Run the gates on the host
that can execute them:

```sh
python -m pytest --suite portable
python -m pytest --suite native
HANLY_REQUIRE_PACKAGED=1 python -m pytest --suite packaged
```

The native suite needs the desktop runtime, display, EasyOCR weights, and a
KRDICT fixture. The packaged suite needs the freshly built native root and
Python service; its UI cases use an isolated appcopy and profile. Windows
process-family and updater acceptance must run on Windows. Linux WebKitGTK and
portable-package acceptance must run on Linux. A Mac build or cross-compiled
binary does not establish those platform results. See the
[migration checkpoint](../../docs/execution/checkpoints/desktop-tauri-migration.md)
for the current implementation evidence and remaining native gates.
