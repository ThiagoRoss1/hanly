import { isTauri } from "@tauri-apps/api/core";
import type { ReactNode } from "react";

/** Reserve the macOS overlay titlebar while retaining the native window controls. */
export function NativeChrome({ children }: { children: ReactNode }) {
  const macOverlay = isTauri() && /Mac/.test(navigator.platform);

  if (!macOverlay) return children;

  return (
    <div className="native-mac-chrome relative h-full [&>.app]:pt-8!">
      <div
        aria-hidden="true"
        data-tauri-drag-region
        className="absolute inset-x-2 top-1 z-40 h-7 select-none"
      />
      {children}
    </div>
  );
}
