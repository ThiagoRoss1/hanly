import type { DesktopServiceStatus, HanlyState } from "../contracts/desktop.ts";

export interface DesktopStateModel {
  state: HanlyState | null;
  connectionError: string | null;
  serviceStatus: DesktopServiceStatus | null;
}

export type DesktopStateAction =
  | { type: "state-received"; payload: unknown }
  | { type: "service-status"; payload: DesktopServiceStatus }
  | { type: "connection-error"; message: string }
  | { type: "clear-error" };

export const initialDesktopState: DesktopStateModel = {
  state: null,
  connectionError: null,
  serviceStatus: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasStringFields(value: unknown, fields: readonly string[]): boolean {
  return isRecord(value) && fields.every((field) => typeof value[field] === "string");
}

function isCaptureRegion(value: unknown): boolean {
  return isRecord(value)
    && Number.isInteger(value.left)
    && Number.isInteger(value.top)
    && Number.isInteger(value.width)
    && Number.isInteger(value.height)
    && Number(value.width) > 0
    && Number(value.height) > 0;
}

function isCaptureTarget(value: unknown): boolean {
  return isRecord(value)
    && Number.isInteger(value.index)
    && typeof value.name === "string"
    && isCaptureRegion(value.bounds);
}


function isRuntimeResource(value: unknown): boolean {
  return isRecord(value)
    && typeof value.id === "string"
    && (value.kind === undefined || typeof value.kind === "string")
    && (value.status === undefined || typeof value.status === "string")
    && (value.version === undefined || value.version === null || typeof value.version === "string")
    && (value.compatible === undefined || typeof value.compatible === "boolean")
    && (value.diagnostics === undefined || Array.isArray(value.diagnostics) && value.diagnostics.every((item) => typeof item === "string"));
}

function isPermissionItem(value: unknown): boolean {
  return isRecord(value)
    && typeof value.id === "string"
    && typeof value.label === "string"
    && typeof value.state === "string"
    && typeof value.granted === "boolean"
    && typeof value.requirement === "string"
    && (value.restart_note === undefined || typeof value.restart_note === "string");
}

export function isHanlyState(value: unknown): value is HanlyState {
  if (!isRecord(value)) return false;
  const app = value.app;
  const config = value.config;
  const runtime = value.runtime;
  const updates = value.updates;
  const permissions = value.permissions;

  if (!hasStringFields(app, ["state", "activity", "detail", "capture_mode", "target"])) return false;
  if (!isRecord(app) || typeof app.capture_running !== "boolean" || !Array.isArray(app.targets) || !app.targets.every(isCaptureTarget)) return false;
  if (app.region !== null && !isCaptureRegion(app.region)) return false;

  if (!isRecord(config) || typeof config.hover_delay_ms !== "number" || typeof config.capture_monitor !== "number" && config.capture_monitor !== null) return false;
  if (!hasStringFields(config, [
    "capture_hotkey", "capture_mode", "hotkey", "hover_activation", "hover_hotkey",
    "lookup_preload", "ocr_backend", "popup_default_size", "technical_details", "theme",
  ])) return false;
  if (typeof config.popup_enabled !== "boolean" || typeof config.update_checks_enabled !== "boolean") return false;
  if (config.capture_region !== null && !isCaptureRegion(config.capture_region)) return false;

  if (!isRecord(runtime) || (typeof runtime.ocr_provider !== "string" && runtime.ocr_provider !== null)) return false;
  if (runtime.app_version !== null && typeof runtime.app_version !== "string") return false;
  if (!Array.isArray(runtime.ocr_backends) || !runtime.ocr_backends.every((item) => typeof item === "string")) return false;
  if (!Array.isArray(runtime.resources) || !runtime.resources.every(isRuntimeResource) || !Array.isArray(runtime.diagnostics) || !runtime.diagnostics.every((item) => typeof item === "string")) return false;
  if (!isRecord(runtime.hover_delay_bounds) || typeof runtime.hover_delay_bounds.min !== "number" || typeof runtime.hover_delay_bounds.max !== "number") return false;
  if (!hasStringFields(runtime.status, ["phase", "stage", "message"]) || !hasStringFields(runtime.engine, ["state", "message"])) return false;
  if (!isRecord(runtime.hotkeys) || !Object.values(runtime.hotkeys).every((item) => typeof item === "string") || (typeof runtime.log_path !== "string" && runtime.log_path !== null)) return false;

  if (!isRecord(updates) || typeof updates.available !== "boolean" || typeof updates.status !== "string" || typeof updates.message !== "string") return false;
  if (updates.resources !== undefined && (!Array.isArray(updates.resources) || !updates.resources.every((item) => isRecord(item) && typeof item.id === "string"))) return false;
  if (updates.activity !== undefined && (!Array.isArray(updates.activity) || !updates.activity.every((item) => isRecord(item) && (item.at === undefined || typeof item.at === "number") && (item.message === undefined || typeof item.message === "string")))) return false;
  if (!isRecord(permissions) || typeof permissions.supported !== "boolean" || !Array.isArray(permissions.items) || !permissions.items.every(isPermissionItem)) return false;
  return true;
}

export function desktopStateReducer(model: DesktopStateModel, action: DesktopStateAction): DesktopStateModel {
  if (action.type === "state-received") {
    if (!isHanlyState(action.payload)) {
      return { ...model, connectionError: "Hanly returned an incomplete desktop state." };
    }
    return { ...model, state: action.payload, connectionError: null };
  }
  if (action.type === "service-status") {
    return {
      ...model,
      serviceStatus: action.payload,
      connectionError: action.payload.state === "failed"
        ? action.payload.message || "The Hanly desktop service stopped unexpectedly."
        : action.payload.state === "ready" ? null : model.connectionError,
    };
  }
  if (action.type === "connection-error") return { ...model, connectionError: action.message };
  return { ...model, connectionError: null };
}
