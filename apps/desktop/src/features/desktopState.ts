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

export function isHanlyState(value: unknown): value is HanlyState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<HanlyState>;
  return Boolean(state.app && state.config && state.runtime && state.permissions);
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
