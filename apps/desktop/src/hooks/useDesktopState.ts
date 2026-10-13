import { useCallback, useEffect, useReducer, useState } from "react";
import type { HanlyState } from "../contracts/desktop.ts";
import { desktopRequest, getState, markFrontendReady } from "../services/desktopBridge.ts";
import { listenToDesktopEvents } from "../services/desktopEvents.ts";
import { normalizeDesktopError, type DesktopMethod } from "../services/desktopBridgeCore.ts";
import { desktopStateReducer, initialDesktopState, isHanlyState } from "../features/desktopState.ts";

function errorText(error: unknown): string {
  return normalizeDesktopError(error).message;
}

function isUpdating(state: HanlyState | null): boolean {
  const update = state?.updates;
  return Boolean(update?.cancellable) || [
    "checking", "preparing", "inspecting", "downloading", "verifying",
    "unpacking", "installing", "validating",
  ].includes(update?.status ?? "");
}

export function useDesktopState(view: "control_center") {
  const [model, dispatch] = useReducer(desktopStateReducer, initialDesktopState);
  const [refreshing, setRefreshing] = useState(false);
  const { state, connectionError, serviceStatus } = model;

  const acceptState = useCallback((next: unknown) => {
    dispatch({ type: "state-received", payload: next });
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      acceptState(await getState());
    } catch (error) {
      dispatch({ type: "connection-error", message: errorText(error) });
    } finally {
      setRefreshing(false);
    }
  }, [acceptState]);

  const runCommand = useCallback(async <T,>(method: DesktopMethod, params: Record<string, unknown> = {}) => {
    try {
      const result = await desktopRequest<T>(method, params);
      if (isHanlyState(result)) acceptState(result);
      return result;
    } catch (error) {
      throw normalizeDesktopError(error);
    }
  }, [acceptState]);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | null = null;

    void listenToDesktopEvents({
      onState: acceptState,
      onServiceStatus: (status) => {
        dispatch({ type: "service-status", payload: status });
      },
    }).then((dispose) => {
      if (!active) dispose();
      else unlisten = dispose;
    }).catch((error: unknown) => {
      if (active) dispatch({ type: "connection-error", message: errorText(error) });
    }).then(async () => {
      if (!active) return;
      try {
        await markFrontendReady(view);
        acceptState(await getState());
      } catch (error) {
        if (active) dispatch({ type: "connection-error", message: errorText(error) });
      }
    });

    return () => {
      active = false;
      unlisten?.();
    };
  }, [acceptState, view]);

  const runtimePending = [state?.runtime.status?.phase, state?.app.activity]
    .some((phase) => phase === "preparing" || phase === "stopping");

  useEffect(() => {
    if (!runtimePending && !isUpdating(state)) return;
    const timer = window.setInterval(() => {
      void getState().then(acceptState).catch((error: unknown) => {
        dispatch({ type: "connection-error", message: errorText(error) });
      });
    }, 900);
    return () => window.clearInterval(timer);
  }, [acceptState, runtimePending, state]);

  return { state, connectionError, serviceStatus, refreshing, refresh, runCommand };
}
