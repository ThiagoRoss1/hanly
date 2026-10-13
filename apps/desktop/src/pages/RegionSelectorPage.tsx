import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { desktopRequest, markFrontendReady } from "../services/desktopBridge.ts";
import { listenToDesktopEvents } from "../services/desktopEvents.ts";
import { normalizeDesktopError } from "../services/desktopBridgeCore.ts";
import type { CaptureRegion, DesktopRegionEvent } from "../contracts/desktop.ts";

interface PointerPoint {
  x: number;
  y: number;
}

interface SelectionBox extends CaptureRegion {}

function normalizedBox(start: PointerPoint, end: PointerPoint): SelectionBox {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  return {
    left: Math.round(left),
    top: Math.round(top),
    width: Math.round(Math.abs(end.x - start.x)),
    height: Math.round(Math.abs(end.y - start.y)),
  };
}

export function RegionSelectorPage() {
  const [selection, setSelection] = useState<SelectionBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [desktop, setDesktop] = useState<DesktopRegionEvent | null>(null);
  const origin = useRef<PointerPoint | null>(null);

  useEffect(() => {
    document.documentElement.dataset.regionSelector = "true";
    let active = true;
    let unlisten: (() => void) | null = null;

    void listenToDesktopEvents({
      onRegion: (event: DesktopRegionEvent) => {
        if (active) {
          setDesktop(event);
          setSelection(null);
          setError(null);
          origin.current = null;
        }
      },
    }).then(async (dispose) => {
      if (!active) {
        dispose();
        return;
      }
      unlisten = dispose;
      await markFrontendReady("region_selector");
    }).catch((reason: unknown) => {
      if (active) setError(normalizeDesktopError(reason).message);
    });

    return () => {
      active = false;
      unlisten?.();
      delete document.documentElement.dataset.regionSelector;
    };
  }, []);

  const cancel = useCallback(async () => {
    await desktopRequest("cancel_region").catch((reason: unknown) => {
      setError(normalizeDesktopError(reason).message);
    });
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        void cancel();
      }
    };
    const onContextMenu = (event: MouseEvent) => {
      event.preventDefault();
      void cancel();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("contextmenu", onContextMenu);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("contextmenu", onContextMenu);
    };
  }, [cancel]);

function pointFromEvent(event: PointerEvent<HTMLElement>): PointerPoint {
    const bounds = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  function startSelection(event: PointerEvent<HTMLElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
    const start = pointFromEvent(event);
    origin.current = start;
    setSelection(normalizedBox(start, start));
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveSelection(event: PointerEvent<HTMLElement>) {
    if (!origin.current) return;
    setSelection(normalizedBox(origin.current, pointFromEvent(event)));
  }

  async function finishSelection(event: PointerEvent<HTMLElement>) {
    if (!origin.current) return;
    const region = normalizedBox(origin.current, pointFromEvent(event));
    origin.current = null;
    setSelection(region);
    if (region.width < 2 || region.height < 2) {
      setSelection(null);
      return;
    }

    setError(null);
    try {
      await desktopRequest("confirm_region", {
        region,
        coordinate_space: "overlay_logical",
        scale_factor: window.devicePixelRatio,
      });
    } catch (reason) {
      setError(normalizeDesktopError(reason).message);
    }
  }

  const boxStyle = selection ? {
    left: `${selection.left}px`,
    top: `${selection.top}px`,
    width: `${selection.width}px`,
    height: `${selection.height}px`,
  } : undefined;
  const instruction = error ?? (desktop
    ? `Drag across ${desktop.monitors.length} ${desktop.monitors.length === 1 ? "display" : "displays"} · Esc or right-click to cancel`
    : "Drag across the screen · Esc or right-click to cancel");

  return (
    <main
      aria-label="Select a screen region"
      className="region-screen"
      data-monitor-count={desktop?.monitors.length ?? 0}
      onPointerDown={startSelection}
      onPointerMove={moveSelection}
      onPointerUp={(event) => void finishSelection(event)}
    >
      {desktop?.image && <img alt="" aria-hidden="true" className="region-backdrop" src={desktop.image} />}
      <div aria-hidden="true" className="region-selection" data-active={Boolean(selection)} style={boxStyle}>
        {selection && (
          <span className="region-selection-size">{selection.width} × {selection.height}</span>
        )}
      </div>
      <section aria-live="polite" className="region-instructions">
        <div className="region-instruction-copy">
          <div className="region-instruction-title">Choose where Hanly reads</div>
          <div className="region-instruction-hint">{instruction}</div>
        </div>
        <button className="btn btn-sm btn-quiet region-cancel" onClick={() => void cancel()} type="button">
          Cancel
        </button>
      </section>
    </main>
  );
}
