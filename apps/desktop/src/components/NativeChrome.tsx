import { isTauri } from "@tauri-apps/api/core";
import type { ReactNode } from "react";

/** Reserve the macOS overlay titlebar while retaining the native window controls. */
export function NativeChrome({ children }: { children: ReactNode }) {
  const macOverlay = isTauri() && /Mac/.test(navigator.platform);

  if (!macOverlay) return children;

  return (
    <div className="native-mac-chrome relative flex h-full flex-col bg-[#f6f0f8] pt-10 [html[data-mode=dark]_&]:bg-[#211d2b] [&>.app]:h-auto! [&>.app]:min-h-0 [&>.app]:flex-1">
      <div
        aria-hidden="true"
        data-tauri-drag-region
        className="absolute top-0 right-0 left-24 z-40 h-10 select-none"
      />
      {children}
    </div>
  );
}
