export type DesktopMethod =
  | "get_state"
  | "get_logs"
  | "frontend_ready"
  | "update_settings"
  | "set_hover_delay"
  | "set_hotkey"
  | "start_capture"
  | "stop_capture"
  | "set_capture_mode"
  | "set_target"
  | "set_region"
  | "select_region"
  | "select_capture_area"
  | "confirm_region"
  | "cancel_region"
  | "grant_permission"
  | "popup_measure"
  | "refresh_permissions"
  | "retry_runtime"
  | "check_for_updates"
  | "install_application_update"
  | "install_update"
  | "cancel_update"
  | "open_release_notes"
  | "clear_logs"
  | "export_diagnostics"
  | "copy_text"
  | "quit"
  | "popup_close"
  | "popup_expand"
  | "popup_geometry";

export type DesktopParams = Record<string, unknown>;
export type InvokeCommand = <T>(
  command: string,
  args?: Record<string, unknown>,
) => Promise<T>;

export class DesktopBridgeError extends Error {
  readonly code: string;
  readonly details?: unknown;

  constructor(
    message: string,
    code = "DESKTOP_BRIDGE_ERROR",
    details?: unknown,
  ) {
    super(message);
    this.name = "DesktopBridgeError";
    this.code = code;
    this.details = details;
  }
}

export function normalizeDesktopError(error: unknown): DesktopBridgeError {
  if (error instanceof DesktopBridgeError) return error;
  if (error instanceof Error) {
    return new DesktopBridgeError(error.message, "DESKTOP_BRIDGE_ERROR", error);
  }
  if (typeof error === "string") {
    try {
      const parsed: unknown = JSON.parse(error);
      if (parsed && typeof parsed === "object")
        return normalizeDesktopError(parsed);
    } catch {
      return new DesktopBridgeError(error);
    }
    return new DesktopBridgeError(error);
  }
  if (error && typeof error === "object") {
    const item = error as {
      code?: unknown;
      message?: unknown;
      details?: unknown;
    };
    return new DesktopBridgeError(
      typeof item.message === "string"
        ? item.message
        : "Hanly could not complete that action.",
      typeof item.code === "string" ? item.code : "DESKTOP_BRIDGE_ERROR",
      item.details,
    );
  }
  return new DesktopBridgeError("Hanly could not complete that action.");
}

export function createDesktopBridge(invokeCommand: InvokeCommand) {
  return {
    async request<T>(
      method: DesktopMethod,
      params: DesktopParams = {},
    ): Promise<T> {
      try {
        return await invokeCommand<T>("desktop_request", { method, params });
      } catch (error) {
        throw normalizeDesktopError(error);
      }
    },
  };
}
