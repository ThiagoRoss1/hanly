# Hanly Desktop

The official Tauri/React migration workspace. This is an **incomplete development
foundation**, not the distributable Hanly product yet. The production `hanly`
command still runs the existing desktop while its replacements gain parity.
The single migration checkpoint is
[`desktop-tauri-migration.md`](../../docs/execution/checkpoints/desktop-tauri-migration.md).

## Current boundary

Rust owns three native windows, tray/reopen, a restricted per-window command
bridge and a private supervised Python service. React renders the Control
Center, popup and selector routes using the incumbent visual assets/tokens.
Python owns settings and diagnostics. The service currently answers handshake,
state, settings and logs; capture, lookup, permissions, resources, update
transactions and region selection return explicit unavailable errors.
No Qt or heavy provider runtime is imported by this service startup.

`service.hello` confirms protocol compatibility, not lookup readiness. Request
frames are capped at 1 MiB, requests at 32 pending, event snapshots are coalesced,
and disconnects resolve outstanding calls. The native root derives caller labels;
frontend code cannot impersonate another window or choose a process/file path.
Clipboard access is a bounded write-only logs action through Rust.

## Development

Use the repository `.venv` with the editable `hanly` and `hanly-app` packages,
Node 22.12+ and Rust 1.90+. Production packaging must eventually bundle Python;
the development launch deliberately uses `.venv`, never a production Node backend.
From this directory:

```sh
npm ci --cache /private/tmp/hanly-npm-cache
npm run check
npm test
npm run test:ui
npm run build
PATH="$HOME/.cargo/bin:$PATH" cargo test --manifest-path src-tauri/Cargo.toml --locked
PATH="$HOME/.cargo/bin:$PATH" cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets --locked -- -D warnings
PATH="$HOME/.cargo/bin:$PATH" cargo fmt --manifest-path src-tauri/Cargo.toml --check
```

For a native development launch with a disposable profile on macOS/Linux:

```sh
XDG_CONFIG_HOME=/private/tmp/hanly-desktop-profile PATH="$HOME/.cargo/bin:$PATH" npm run tauri -- dev
```

Windows uses a disposable `LOCALAPPDATA` directory instead. Close hides the
Control Center; Open Hanly in the tray reopens it; Quit Hanly stops the root and
its service. The Vite server is developer-only. To embed the production frontend
in a debug executable while retaining the development Python service:

```sh
npm run build
PATH="$HOME/.cargo/bin:$PATH" cargo build --manifest-path src-tauri/Cargo.toml --features custom-protocol --locked
XDG_CONFIG_HOME=/private/tmp/hanly-desktop-profile ./src-tauri/target/debug/hanly-desktop
```

## Remaining release work

`bundle.active` is intentionally false until the Python runtime, providers,
models, resources, native helper and identity stamp have a verified bundle
layout. Release-mode Rust expects the fixed sibling `hanly-service` executable
(`hanly-service.exe` on Windows); that payload is not built yet. Do not treat
`tauri build --no-bundle` as an installable or functional release.

Current production Qt/Qt WebEngine/pywebview adapters and tests remain until
replacement parity passes. The updater has not been replaced by a Tauri plugin.
Native focus, non-activation, popup retention, monitor/DPI behavior, packaged
identity, updater transition, Lab attribution and Windows/Linux acceptance
remain migration gates, not guarantees from these API-level checks.

Setup follows the official [Tauri capabilities](https://v2.tauri.app/security/capabilities/),
[sidecar packaging](https://v2.tauri.app/develop/sidecar/),
[clipboard adapter](https://v2.tauri.app/plugin/clipboard/),
[Vite integration](https://v2.tauri.app/start/frontend/vite/), and
[Tailwind Vite installation](https://tailwindcss.com/docs/installation/using-vite)
documentation. Stable dependencies were resolved from the registry and their
exact versions recorded in `package-lock.json` and `src-tauri/Cargo.lock`.
