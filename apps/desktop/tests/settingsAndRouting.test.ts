import assert from "node:assert/strict";
import { test } from "node:test";
import { APP_ROUTES, resolveInitialRoute } from "../src/contracts/routes.ts";
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

test("desktop state events replace snapshots and keep service failures visible", () => {
  const state = {
    app: {},
    config: {},
    runtime: {},
    permissions: {},
  };
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
