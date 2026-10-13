import { invoke } from "@tauri-apps/api/core";
import type { DiagnosticsExport, HanlyState, LogSnapshot } from "../contracts/desktop.ts";
import {
  createDesktopBridge,
  type DesktopMethod,
  type DesktopParams,
} from "./desktopBridgeCore.ts";

const bridge = createDesktopBridge(invoke);

export function desktopRequest<T = unknown>(
  method: DesktopMethod,
  params: DesktopParams = {},
): Promise<T> {
  return bridge.request<T>(method, params);
}

export const getState = () => desktopRequest<HanlyState>("get_state");

export const getLogs = () => desktopRequest<LogSnapshot>("get_logs");

export const clearLogs = () => desktopRequest<LogSnapshot>("clear_logs");

export const exportDiagnostics = () => desktopRequest<DiagnosticsExport>("export_diagnostics");

export async function updateSettings(changes: Record<string, unknown>): Promise<HanlyState | undefined> {
  return desktopRequest<HanlyState | undefined>("update_settings", { changes });
}

export function markFrontendReady(view: "control_center" | "popup" | "region_selector") {
  return desktopRequest("frontend_ready", { view });
}
