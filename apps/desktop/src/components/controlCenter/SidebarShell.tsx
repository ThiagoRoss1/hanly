import { useRef, type ReactNode } from "react";
import { VillageScene } from "../village/VillageScene.tsx";

export function SidebarShell({
  children,
  compact = false,
  dark,
  disabled = false,
  onToggleTheme,
}: {
  children: ReactNode;
  compact?: boolean;
  dark: boolean;
  disabled?: boolean;
  onToggleTheme: () => void;
}) {
  const contentRef = useRef<HTMLDivElement>(null);

  return (
    <aside className={`sidebar relative z-0 flex w-[268px] min-w-0 flex-none flex-col overflow-x-hidden overflow-y-auto px-4 pt-[18px] pb-4${compact ? " is-compact" : ""}`}>
      <VillageScene
        dark={dark}
        disabled={disabled}
        onToggleTheme={onToggleTheme}
        contentRef={contentRef}
      />
      <div ref={contentRef} className="sidebar-content relative z-[1] flex min-h-full flex-none flex-col">
        {children}
      </div>
    </aside>
  );
}
