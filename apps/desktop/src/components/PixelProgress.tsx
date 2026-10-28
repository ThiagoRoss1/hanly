import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

/** A measured artwork track with real progress semantics and no slider thumb. */
export function PixelProgress({ fraction }: { fraction: number | null }) {
  const track = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const element = track.current;
    if (!element) return;
    const measure = () => setWidth(element.getBoundingClientRect().width);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, []);

  return (
    <div
      ref={track}
      className="track"
      role="progressbar"
      aria-label="Update progress"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={fraction === null ? undefined : Math.round(fraction * 100)}
      data-indeterminate={fraction === null}
      style={{ "--track-pixels": `${width || 400}px` } as CSSProperties}
    >
      <div className="track-fill" style={{ width: fraction === null ? undefined : `${fraction * 100}%` }} />
    </div>
  );
}
