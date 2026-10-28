export type Section =
  | "capture"
  | "permissions"
  | "shortcuts"
  | "appearance"
  | "updates"
  | "logs";

export const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "capture", label: "Capture" },
  { id: "permissions", label: "Permissions" },
  { id: "shortcuts", label: "Shortcuts" },
  { id: "appearance", label: "Appearance" },
  { id: "updates", label: "Updates" },
  { id: "logs", label: "Logs" },
];

export function sectionIcon(section: Section): string {
  if (section === "shortcuts") {
    return "/design/media/assets/icons/v2/icon-shortcuts-pixel.png";
  }

  const name = section === "capture" ? "capture-plant" : `icon-${section}`;
  return `/design/media/assets/icons/v2/${name}.png`;
}

export const PAGE_COPY: Record<Section, { kicker: string; description: string }> = {
  capture: {
    kicker: "Capture",
    description: "Choose where Hanly reads.",
  },
  permissions: {
    kicker: "Permissions",
    description: "The grants Hanly needs before it can read.",
  },
  shortcuts: {
    kicker: "Shortcuts",
    description: "What your keyboard does, and what the system accepted.",
  },
  appearance: {
    kicker: "Appearance",
    description: "How the Control Center and popup look.",
  },
  updates: {
    kicker: "Updates",
    description: "The app and its resources update separately.",
  },
  logs: {
    kicker: "Logs",
    description: "Runtime state and recent activity.",
  },
};
