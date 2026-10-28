import { useEffect, useRef } from "react";
import "../../styles/villageScene.css";
import "../../styles/mascotPolish.css";

const ASSET_ROOT = "/design/media/assets/";
const CANVAS_SIZE = 512;
const ZZZ_FRAME_MS = 500;

type Pose = "idle" | "working" | "sleep";

interface SpriteCycle {
  frames: readonly string[];
  durations: readonly number[];
}

const spriteCycles: Record<Pose, SpriteCycle> = {
  idle: {
    frames: [1, 2, 3, 4, 5, 6].map(
      (frame) => `mascot/idle/frame-${String(frame).padStart(2, "0")}.png`,
    ),
    durations: [360, 180, 180, 220, 180, 360],
  },
  working: {
    frames: [1, 2, 3, 4, 5, 6].map(
      (frame) => `mascot/working/frame-${String(frame).padStart(2, "0")}.png`,
    ),
    durations: [360, 180, 180, 220, 180, 360],
  },
  sleep: {
    frames: [1, 2, 3, 4, 5, 6, 7, 8].map(
      (frame) => `mascot-rig/sleeping-v2.4/frames/frame-${String(frame).padStart(2, "0")}.png`,
    ),
    durations: Array(8).fill(250) as number[],
  },
};

const zzzFrames = [1, 2, 3, 4].map(
  (frame) => `${ASSET_ROOT}effects/zzz/frame-${frame}.png`,
);
const heart = `${ASSET_ROOT}extras/bubble-heart-v1.png`;
const imageCache = new Map<string, Promise<HTMLImageElement | null>>();

function loadImage(path: string): Promise<HTMLImageElement | null> {
  const url = `${ASSET_ROOT}${path}`;
  let pending = imageCache.get(url);
  if (!pending) {
    pending = new Promise((resolve) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => resolve(null);
      image.src = url;
    });
    imageCache.set(url, pending);
  }
  return pending;
}

function frameAt(elapsed: number, durations: readonly number[]): number {
  const cycleLength = durations.reduce((sum, duration) => sum + duration, 0);
  let remaining = Math.max(0, elapsed) % cycleLength;
  let frame = 0;
  while (
    frame < durations.length - 1 &&
    remaining >= (durations[frame] ?? Number.POSITIVE_INFINITY)
  ) {
    remaining -= durations[frame] ?? 0;
    frame += 1;
  }
  return frame;
}

function poseForActivity(activity: string): Pose {
  if (activity === "stopped") return "sleep";
  if (activity === "preparing" || activity === "running") return "working";
  return "idle";
}

export interface MascotProps {
  activity: string;
}

export function Mascot({ activity }: MascotProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const balloonRef = useRef<HTMLImageElement>(null);
  const pose = poseForActivity(activity);
  const cycle = spriteCycles[pose];

  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const balloon = balloonRef.current;
    const context = canvas?.getContext("2d");
    if (!stage || !canvas || !balloon || !context) return;
    const drawingContext: CanvasRenderingContext2D = context;
    const balloonElement: HTMLImageElement = balloon;

    const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frames: (HTMLImageElement | null)[] = [];
    let zzz: (HTMLImageElement | null)[] = [];
    let frameIndex = -1;
    let zzzIndex = -1;
    let started = performance.now();
    let pausedAt: number | null = null;
    let timer: number | undefined;
    let intersects = true;
    let disposed = false;

    function canAnimate(): boolean {
      return !disposed && !document.hidden && intersects && !motionPreference.matches;
    }

    function draw(index: number): void {
      const image = frames[index];
      if (!image) return;
      if (frameIndex === index) return;
      frameIndex = index;
      drawingContext.imageSmoothingEnabled = false;
      drawingContext.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
      drawingContext.drawImage(image, 0, 0, CANVAS_SIZE, CANVAS_SIZE);
    }

    function showZzz(index: number): void {
      if (pose !== "sleep" || zzzIndex === index) return;
      const image = zzz[index];
      if (!image) return;
      zzzIndex = index;
      balloonElement.src = image.src;
      balloonElement.style.translate = `0 ${-index}px`;
    }

    function tick(): void {
      timer = undefined;
      if (!canAnimate()) return;
      const elapsed = performance.now() - started;
      const index = frameAt(elapsed, cycle.durations);
      draw(index);
      if (pose === "sleep") showZzz(Math.floor(elapsed / ZZZ_FRAME_MS) % zzzFrames.length);

      // Wake for an actual sprite change rather than checking every display frame.
      const total = cycle.durations.reduce((sum, duration) => sum + duration, 0);
      const boundary = cycle.durations.slice(0, index + 1).reduce((sum, duration) => sum + duration, 0);
      const frameDelay = boundary - (elapsed % total);
      const balloonDelay = pose === "sleep" ? ZZZ_FRAME_MS - (elapsed % ZZZ_FRAME_MS) : frameDelay;
      timer = window.setTimeout(tick, Math.max(16, Math.min(frameDelay, balloonDelay)));
    }

    function pause(): void {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
      if (pausedAt === null) pausedAt = performance.now();
    }

    function resume(): void {
      if (!canAnimate()) return;
      if (pausedAt !== null) {
        started += performance.now() - pausedAt;
        pausedAt = null;
      }
      if (timer === undefined) tick();
    }

    function handleVisibility(): void {
      if (document.hidden || !intersects || motionPreference.matches) pause();
      else resume();
    }

    function handleMotionPreference(): void {
      if (motionPreference.matches) {
        pause();
        started = performance.now();
        draw(0);
        showZzz(0);
      } else {
        resume();
      }
    }

    const intersectionObserver =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver((entries) => {
            intersects = entries[0]?.isIntersecting ?? true;
            handleVisibility();
          });
    intersectionObserver?.observe(stage);
    document.addEventListener("visibilitychange", handleVisibility);
    motionPreference.addEventListener("change", handleMotionPreference);
    balloonElement.src = pose === "sleep" ? (zzzFrames[0] ?? "") : heart;
    balloonElement.style.translate = "0 0";

    void Promise.all([
      Promise.all(cycle.frames.map(loadImage)),
      Promise.all(zzzFrames.map((path) => loadImage(path.replace(ASSET_ROOT, "")))),
    ]).then(([loadedFrames, loadedZzz]) => {
      if (disposed) return;
      frames = loadedFrames;
      zzz = loadedZzz;
      started = performance.now();
      draw(0);
      showZzz(0);
      resume();
    });

    return () => {
      disposed = true;
      pause();
      intersectionObserver?.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
      motionPreference.removeEventListener("change", handleMotionPreference);
    };
  }, [cycle, pose]);

  return (
    <div
      ref={stageRef}
      className="mascot-stage"
      data-activity={activity}
      data-pose={pose}
      aria-hidden="true"
    >
      <canvas
        ref={canvasRef}
        className="sprite-canvas"
        width={CANVAS_SIZE}
        height={CANVAS_SIZE}
      />
      <img
        ref={balloonRef}
        className="mascot-balloon"
        src={pose === "sleep" ? zzzFrames[0] : heart}
        alt=""
        draggable={false}
      />
    </div>
  );
}
