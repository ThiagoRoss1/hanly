import { listen } from "@tauri-apps/api/event";
import type { Event } from "@tauri-apps/api/event";
import {
  subscribeToDesktopEvents,
  type DesktopEventHandlers,
  type DesktopEventName,
  type DesktopEventPayloads,
} from "./desktopEventsCore.ts";

export function listenToDesktopEvents(handlers: DesktopEventHandlers): Promise<() => void> {
  return subscribeToDesktopEvents(
    async <Name extends DesktopEventName>(
      name: Name,
      callback: (payload: DesktopEventPayloads[Name]) => void,
    ) => listen(name, (event: Event<DesktopEventPayloads[Name]>) => callback(event.payload)),
    handlers,
  );
}
