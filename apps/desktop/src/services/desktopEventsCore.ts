import type {
  DesktopPopupEvent,
  DesktopServiceStatus,
  HanlyState,
} from "../contracts/desktop.ts";

export type DesktopEventName = "desktop-state" | "desktop-popup" | "desktop-service-status";
export type DesktopEventPayloads = {
  "desktop-state": HanlyState;
  "desktop-popup": DesktopPopupEvent;
  "desktop-service-status": DesktopServiceStatus;
};

export interface DesktopEventHandlers {
  onState?: (state: HanlyState) => void;
  onPopup?: (event: DesktopPopupEvent) => void;
  onServiceStatus?: (status: DesktopServiceStatus) => void;
}

export type EventRegistrar = <Name extends DesktopEventName>(
  name: Name,
  callback: (payload: DesktopEventPayloads[Name]) => void,
) => Promise<() => void>;

export async function subscribeToDesktopEvents(
  register: EventRegistrar,
  handlers: DesktopEventHandlers,
): Promise<() => void> {
  const unlisten: Array<() => void> = [];
  try {
    if (handlers.onState) {
      unlisten.push(await register("desktop-state", handlers.onState));
    }
    if (handlers.onPopup) {
      unlisten.push(await register("desktop-popup", handlers.onPopup));
    }
    if (handlers.onServiceStatus) {
      unlisten.push(await register("desktop-service-status", handlers.onServiceStatus));
    }
  } catch (error) {
    unlisten.forEach((dispose) => dispose());
    throw error;
  }
  return () => unlisten.splice(0).forEach((dispose) => dispose());
}
