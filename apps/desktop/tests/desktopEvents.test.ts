import assert from "node:assert/strict";
import { test } from "node:test";
import type { DesktopEventName, DesktopEventPayloads } from "../src/services/desktopEventsCore.ts";
import { subscribeToDesktopEvents } from "../src/services/desktopEventsCore.ts";

test("desktop state and popup events reach only their matching handlers", async () => {
  const listeners = new Map<string, (payload: unknown) => void>();
  const received: string[] = [];
  const unregister: string[] = [];
  const register = async <Name extends DesktopEventName>(
    name: Name,
    callback: (payload: DesktopEventPayloads[Name]) => void,
  ) => {
    listeners.set(name, callback as (payload: unknown) => void);
    return () => unregister.push(name);
  };
  const dispose = await subscribeToDesktopEvents(register, {
    onState: () => received.push("state"),
    onPopup: (event) => received.push(event.type),
  });

  listeners.get("desktop-state")?.({});
  listeners.get("desktop-popup")?.({ type: "popup_hide", sequence: 4 });
  dispose();

  assert.deepEqual(received, ["state", "popup_hide"]);
  assert.deepEqual(unregister, ["desktop-state", "desktop-popup"]);
});

test("partial event setup is unwound when a listener cannot be installed", async () => {
  const disposed: string[] = [];
  let count = 0;
  const register = async <Name extends DesktopEventName>(
    name: Name,
    _callback: (payload: DesktopEventPayloads[Name]) => void,
  ) => {
    count += 1;
    if (count === 2) throw new Error("event channel unavailable");
    return () => disposed.push(name);
  };

  await assert.rejects(subscribeToDesktopEvents(register, { onState: () => undefined, onPopup: () => undefined }));
  assert.deepEqual(disposed, ["desktop-state"]);
});
