import assert from "node:assert/strict";
import { test } from "node:test";
import { APP_ROUTES, resolveInitialRoute } from "../src/contracts/routes.ts";
import type { HanlyState } from "../src/contracts/desktop.ts";
import { desktopStateReducer, initialDesktopState } from "../src/features/desktopState.ts";
import { formatHotkey, hotkeyFromKeyboardEvent, validateHoverDelay } from "../src/features/settings.ts";

test("all native window views resolve to explicit React routes", () => {
  assert.equal(resolveInitialRoute(""), APP_ROUTES.controlCenter);
  assert.equal(resolveInitialRoute("?view=popup"), APP_ROUTES.popup);
  assert.equal(resolveInitialRoute("?view=region_selector"), APP_ROUTES.regionSelector);
  assert.equal(resolveInitialRoute("?view=unknown"), APP_ROUTES.controlCenter);
});

test("hover delay settings honor runtime bounds and whole milliseconds", () => {
  assert.deepEqual(validateHoverDelay("20", { min: 20, max: 2000 }), { valid: true, value: 20 });
  assert.deepEqual(validateHoverDelay("2000", { min: 20, max: 2000 }), { valid: true, value: 2000 });
  assert.equal(validateHoverDelay("19", { min: 20, max: 2000 }).valid, false);
  assert.equal(validateHoverDelay("50.5", { min: 20, max: 2000 }).valid, false);
});

test("shortcut capture keeps native key names in Hanly's stored format", () => {
  assert.equal(hotkeyFromKeyboardEvent({ key: "ArrowLeft", ctrlKey: true, shiftKey: false, altKey: false, metaKey: true }), "ctrl+cmd+left");
  assert.equal(hotkeyFromKeyboardEvent({ key: "Shift", ctrlKey: false, shiftKey: true, altKey: false, metaKey: false }), null);
  assert.deepEqual(formatHotkey("<ctrl>+<shift>+space"), ["ctrl", "shift", "space"]);
});

test("desktop state events validate full snapshots and keep service failures visible", () => {
  const state = {
    app: { state: "new", activity: "preparing", detail: "Starting.", capture_running: false, capture_mode: "full_monitor", target: "cursor", region: null, targets: [] },
    config: {
      capture_hotkey: "ctrl+shift+f10", capture_mode: "full_monitor", capture_monitor: null, capture_region: null,
      hotkey: "ctrl+shift+f9", hover_activation: "push_to_hover", hover_delay_ms: 80, hover_hotkey: "ctrl+shift+f8",
      lookup_preload: "when_capture_starts", ocr_backend: "auto", popup_enabled: true, popup_default_size: "compact",
      technical_details: "off", theme: "system", update_checks_enabled: true,
    },
    runtime: {
      ocr_provider: null, ocr_backends: ["auto", "easyocr"], app_version: "1.1.0", hover_delay_bounds: { min: 20, max: 2000 },
      resources: [], status: { phase: "idle", stage: "startup", message: "Starting." }, engine: { state: "sleeping", message: "Not loaded." },
      hotkeys: {}, log_path: null, diagnostics: ["Service: Hanly desktop service started."],
    },
    updates: { available: false, status: "idle", message: "" },
    permissions: { supported: false, items: [] },
  } satisfies HanlyState;
  const received = desktopStateReducer(initialDesktopState, { type: "state-received", payload: state });
  assert.deepEqual(received.state, state);
  assert.equal(received.connectionError, null);

  const failed = desktopStateReducer(received, {
    type: "service-status",
    payload: { state: "failed", code: "WORKER_EXITED", message: "The lookup service stopped." },
  });
  assert.equal(failed.connectionError, "The lookup service stopped.");
  assert.equal(failed.state, state);

  const invalid = desktopStateReducer(failed, { type: "state-received", payload: { app: {} } });
  assert.equal(invalid.state, state);
  assert.equal(invalid.connectionError, "Hanly returned an incomplete desktop state.");
});
