import assert from "node:assert/strict";
import { test } from "node:test";
import { createDesktopBridge, DesktopBridgeError } from "../src/services/desktopBridgeCore.ts";

test("desktop requests use the restricted native command envelope", async () => {
  const calls: Array<{ command: string; args?: Record<string, unknown> }> = [];
  const bridge = createDesktopBridge(async <T>(command: string, args?: Record<string, unknown>) => {
    calls.push({ command, args });
    return { phase: "ready" } as T;
  });

  const result = await bridge.request<{ phase: string }>("get_state");

  assert.deepEqual(result, { phase: "ready" });
  assert.deepEqual(calls, [{ command: "desktop_request", args: { method: "get_state", params: {} } }]);
});

test("settings changes stay inside the explicit update_settings request", async () => {
  let args: Record<string, unknown> | undefined;
  const bridge = createDesktopBridge(async <T>(_command: string, nextArgs?: Record<string, unknown>) => {
    args = nextArgs;
    return undefined as T;
  });

  await bridge.request("update_settings", { changes: { theme: "dark", popup_default_size: "expanded" } });

  assert.deepEqual(args, {
    method: "update_settings",
    params: { changes: { theme: "dark", popup_default_size: "expanded" } },
  });
});

test("structured native errors keep their code and message", async () => {
  const bridge = createDesktopBridge(async () => {
    throw { code: "SERVICE_NOT_READY", message: "Hanly is still preparing." };
  });

  await assert.rejects(
    bridge.request("start_capture"),
    (error: unknown) => error instanceof DesktopBridgeError
      && error.code === "SERVICE_NOT_READY"
      && error.message === "Hanly is still preparing.",
  );
});
