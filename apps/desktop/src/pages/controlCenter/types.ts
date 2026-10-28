import type { DesktopMethod } from "../../services/desktopBridgeCore.ts";

export type RunCommand = (
  method: DesktopMethod,
  params?: Record<string, unknown>,
  pendingKey?: string,
) => Promise<unknown>;

export type SaveSettings = (
  changes: Record<string, unknown>,
) => Promise<unknown>;

export type IsPending = (key: string) => boolean;
