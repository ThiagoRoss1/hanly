import { useEffect, useRef } from "react";
import "../../styles/villageScene.css";

const WORLD_WIDTH = 192;
const WORLD_HEIGHT = 960;
const ASSET_ROOT = "/design/media/";
const TRANSITION_MS = 1500;

type PointBounds = readonly [number, number, number, number];
type LayerCondition = "both" | "day" | "night";
type LayerMotion = "none" | "cloud-drift" | "tree-sway" | "twinkle";

interface VillageLayer {
  id: string;
  bounds: PointBounds;
  condition: LayerCondition;
  motion: LayerMotion;
  day: string;
  night: string;
}

function starLayer(id: string, bounds: PointBounds): VillageLayer {
  return {
    id,
    bounds,
    condition: "night",
    motion: "twinkle",
    day: "assets/environment/v2.1-textures/star-day_png.png",
    night: "assets/environment/v2.1-textures/star-night_png.png",
  };
}

const layers: readonly VillageLayer[] = [
  {
    id: "sky",
    bounds: [0, 0, WORLD_WIDTH, WORLD_HEIGHT],
    condition: "both",
    motion: "none",
    day: "assets/rails/v2.1/village/day/sky.png",
    night: "assets/rails/v2.1/village/night/sky.png",
  },
  {
    id: "cloud-0",
    bounds: [-30, 195, 175, 70],
    condition: "both",
    motion: "cloud-drift",
    day: "assets/environment/v2.1-textures/cloud-day_png.png",
    night: "assets/environment/v2.1-textures/cloud-night_png.png",
  },
  {
    id: "cloud-1",
    bounds: [80, 304, 155, 62],
    condition: "both",
    motion: "cloud-drift",
    day: "assets/environment/v2.1-textures/cloud-day_png.png",
    night: "assets/environment/v2.1-textures/cloud-night_png.png",
  },
  starLayer("star-0", [25, 85, 18, 18]),
  starLayer("star-1", [83, 155, 18, 18]),
  starLayer("star-2", [165, 220, 18, 18]),
  starLayer("star-3", [34, 320, 18, 18]),
  {
    id: "mountains",
    bounds: [-90, 416.1522, 370, 67.6955],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/mountains-day_png.png",
    night: "assets/environment/v2.1-textures/mountains-night_png.png",
  },
  {
    id: "back-trunk",
    bounds: [35, 506.4157, 95, 97.1686],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/trunk-day_png.png",
    night: "assets/environment/v2.1-textures/trunk-night_png.png",
  },
  {
    id: "back-canopy",
    bounds: [-10, 393.8898, 210, 182.2205],
    condition: "both",
    motion: "tree-sway",
    day: "assets/environment/v2.1-textures/evergreen-canopy-day_png.png",
    night: "assets/environment/v2.1-textures/evergreen-canopy-night_png.png",
  },
  {
    id: "mid-garden",
    bounds: [-15.245, 630, 230.49, 200],
    condition: "both",
    motion: "tree-sway",
    day: "assets/environment/v2.1-textures/evergreen-canopy-day_png.png",
    night: "assets/environment/v2.1-textures/evergreen-canopy-night_png.png",
  },
  {
    id: "house-upper",
    bounds: [12, 565.1058, 132, 139.7884],
    condition: "both",
    motion: "none",
    day: "assets/environment/environment-house-tall-v2-normalized-native.png",
    night: "assets/environment/environment-house-tall-v2-normalized-night-native.png",
  },
  {
    id: "garden-upper",
    bounds: [-12, 661.0491, 215, 97.9018],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/ground-rail-day_png.png",
    night: "assets/environment/v2.1-textures/ground-rail-night_png.png",
  },
  {
    id: "blossom-trunk",
    bounds: [85, 689.144, 75, 76.712],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/trunk-day_png.png",
    night: "assets/environment/v2.1-textures/trunk-night_png.png",
  },
  {
    id: "blossom-canopy",
    bounds: [50, 638.4238, 190, 118.1523],
    condition: "both",
    motion: "tree-sway",
    day: "assets/environment/v2.1-textures/blossom-canopy-day_png.png",
    night: "assets/environment/v2.1-textures/blossom-canopy-night_png.png",
  },
  {
    id: "house-lower",
    bounds: [25, 762.981, 145, 129.0379],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/house-low-day_png.png",
    night: "assets/environment/v2.1-textures/house-low-night_png.png",
  },
  {
    id: "garden-lower",
    bounds: [-5, 857.1875, 210, 95.625],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/ground-rail-day_png.png",
    night: "assets/environment/v2.1-textures/ground-rail-night_png.png",
  },
  {
    id: "lamp-lower",
    bounds: [15, 833.8678, 23, 92.2644],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/lamp-day_png.png",
    night: "assets/environment/v2.1-textures/lamp-night_png.png",
  },
  {
    id: "rail-frame",
    bounds: [0, 0, WORLD_WIDTH, WORLD_HEIGHT],
    condition: "both",
    motion: "none",
    day: "assets/environment/v2.1-textures/rail-frame-day_png.png",
    night: "assets/environment/v2.1-textures/rail-frame-night_png.png",
  },
  {
    id: "house-upper-windows",
    bounds: [0, 0, WORLD_WIDTH, WORLD_HEIGHT],
    condition: "night",
    motion: "none",
    day: "assets/rails/v2.1/village/night/layers/house-upper-windows.png",
    night: "assets/rails/v2.1/village/night/layers/house-upper-windows.png",
  },
  {
    id: "house-lower-windows",
    bounds: [0, 0, WORLD_WIDTH, WORLD_HEIGHT],
    condition: "night",
    motion: "none",
    day: "assets/rails/v2.1/village/night/layers/house-lower-windows.png",
    night: "assets/rails/v2.1/village/night/layers/house-lower-windows.png",
  },
  {
    id: "lamp-lower-glass",
    bounds: [0, 0, WORLD_WIDTH, WORLD_HEIGHT],
    condition: "night",
    motion: "none",
    day: "assets/rails/v2.1/village/night/layers/lamp-lower-glass.png",
    night: "assets/rails/v2.1/village/night/layers/lamp-lower-glass.png",
  },
  {
    id: "lighting-and-shadows",
    bounds: [0, 0, WORLD_WIDTH, WORLD_HEIGHT],
    condition: "both",
    motion: "none",
    day: "assets/rails/v2.1/village/day/lighting-and-shadows.png",
    night: "assets/rails/v2.1/village/night/lighting-and-shadows.png",
  },
];

const swayPose = [0, 1, 1, 2, 0, -1, -2, -1] as const;
const starBrightness = [1, 1.025, 1.025, 1, 0.985, 0.985, 1, 1] as const;

const textureCache = new Map<string, Promise<HTMLImageElement | null>>();

function texture(path: string): Promise<HTMLImageElement | null> {
  const url = `${ASSET_ROOT}${path}`;
  let pending = textureCache.get(url);
  if (!pending) {
    pending = new Promise((resolve) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => resolve(null);
      image.src = url;
    });
    textureCache.set(url, pending);
  }
  return pending;
}

function paintLayer(
  context: CanvasRenderingContext2D,
  layer: VillageLayer,
  image: HTMLImageElement,
  alpha: number,
  phase: number,
  motion: boolean,
): void {
  const [left, top, width, height] = layer.bounds;
  if (alpha <= 0) return;

  const animate =
    motion && (layer.motion === "cloud-drift" || layer.motion === "tree-sway");
  if (!animate) {
    const brightness = layer.motion === "twinkle" ? starBrightness[phase] ?? 1 : 1;
    context.globalAlpha = alpha * brightness;
    context.drawImage(image, 0, 0, image.naturalWidth, image.naturalHeight, left, top, width, height);
    return;
  }

  context.globalAlpha = alpha;
  const frame = (phase + (layer.id.charCodeAt(layer.id.length - 1) || 0) % 3) % 8;
  const movementScale = layer.motion === "cloud-drift" ? 0.6 : 1.15;
  for (let band = 0; band < 8; band += 1) {
    const y0 = Math.round((band * height) / 8);
    const y1 = Math.round(((band + 1) * height) / 8);
    const weight = (7 - band) / 7;
    const offset = Math.round((swayPose[frame] ?? 0) * weight * movementScale);
    const sourceTop = (y0 / height) * image.naturalHeight;
    const sourceHeight = ((y1 - y0) / height) * image.naturalHeight;
    context.drawImage(
      image,
      0,
      sourceTop,
      image.naturalWidth,
      sourceHeight,
      left + offset,
      top + y0,
      width,
      y1 - y0,
    );
  }
}

interface SceneEngine {
  setTheme: (dark: boolean) => void;
  destroy: () => void;
}

function createScene(
  viewport: HTMLDivElement,
  canvas: HTMLCanvasElement,
  sun: HTMLImageElement,
  moon: HTMLImageElement,
  initialDark: boolean,
): SceneEngine {
  const renderingContext = canvas.getContext("2d", { alpha: false });
  if (!renderingContext) return { setTheme: () => undefined, destroy: () => undefined };
  const context: CanvasRenderingContext2D = renderingContext;

  const images = new Map<string, HTMLImageElement | null>();
  let light = initialDark ? 1 : 0;
  let target = light;
  let transitionFrom = light;
  let transitionStarted = 0;
  let phase = 0;
  let raf = 0;
  let timer: number | undefined;
  let pausedAt: number | null = null;
  let inViewport = true;
  let destroyed = false;
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");

  function syncCelestial(): void {
    sun.style.opacity = String(1 - light);
    moon.style.opacity = String(light);
  }

  function resize(): void {
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    if (!width || !height) return;

    const scale = Math.max(width / WORLD_WIDTH, height / WORLD_HEIGHT);
    const worldWidth = WORLD_WIDTH * scale;
    const worldHeight = WORLD_HEIGHT * scale;
    const x = (width - worldWidth) / 2;
    const y = (height - worldHeight) * 0.64;
    Object.assign(canvas.style, {
      width: `${worldWidth}px`,
      height: `${worldHeight}px`,
      left: `${x}px`,
      top: `${y}px`,
    });
    draw();
  }

  function draw(): void {
    if (destroyed) return;
    context.clearRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    context.fillStyle = light < 0.5 ? "#9cb9fc" : "#303c76";
    context.fillRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT);

    for (const layer of layers) {
      if (layer.condition === "day" || layer.condition === "both") {
        const dayImage = images.get(layer.day);
        if (dayImage) paintLayer(context, layer, dayImage, 1 - light, phase, isMoving());
      }
      if (layer.condition === "night" || layer.condition === "both") {
        const nightImage = images.get(layer.night);
        if (nightImage) {
          if (layer.condition === "both" && light > 0 && light < 1) {
            context.globalCompositeOperation = "lighter";
          }
          paintLayer(context, layer, nightImage, light, phase, isMoving());
        }
      }
      context.globalAlpha = 1;
      context.globalCompositeOperation = "source-over";
    }
    syncCelestial();
  }

  function isMoving(): boolean {
    return !motionPreference.matches;
  }

  function canAnimate(): boolean {
    return !destroyed && !document.hidden && inViewport && isMoving();
  }

  function transitionFrame(now: number): void {
    raf = 0;
    if (!canAnimate()) return;
    const amount = Math.min(1, (now - transitionStarted) / TRANSITION_MS);
    const eased = amount * amount * (3 - 2 * amount);
    light = transitionFrom + (target - transitionFrom) * eased;
    draw();
    if (amount < 1) raf = requestAnimationFrame(transitionFrame);
    else light = target;
  }

  function pause(): void {
    if (timer !== undefined) {
      window.clearInterval(timer);
      timer = undefined;
    }
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    if (pausedAt === null) pausedAt = performance.now();
  }

  function resume(): void {
    if (!canAnimate()) return;
    const now = performance.now();
    if (pausedAt !== null) {
      transitionStarted += now - pausedAt;
      pausedAt = null;
    }
    if (timer === undefined) {
      timer = window.setInterval(() => {
        if (!canAnimate()) return;
        phase = (phase + 1) % 8;
        draw();
      }, 300);
    }
    if (light !== target && !raf) raf = requestAnimationFrame(transitionFrame);
  }

  function setTheme(dark: boolean): void {
    const next = dark ? 1 : 0;
    if (next === target) return;
    transitionFrom = light;
    target = next;
    transitionStarted = performance.now();

    if (motionPreference.matches) {
      light = target;
      draw();
      return;
    }
    if (canAnimate()) resume();
    else pausedAt = performance.now();
  }

  function handleVisibility(): void {
    if (document.hidden || !inViewport || motionPreference.matches) pause();
    else resume();
  }

  const resizeObserver =
    typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
  resizeObserver?.observe(viewport);
  if (!resizeObserver) window.addEventListener("resize", resize);

  const intersectionObserver =
    typeof IntersectionObserver === "undefined"
      ? null
      : new IntersectionObserver((entries) => {
          inViewport = entries[0]?.isIntersecting ?? true;
          handleVisibility();
        });
  intersectionObserver?.observe(viewport);

  function handleMotionPreference(): void {
    if (motionPreference.matches) {
      pause();
      light = target;
      draw();
    } else {
      handleVisibility();
    }
  }

  document.addEventListener("visibilitychange", handleVisibility);
  motionPreference.addEventListener("change", handleMotionPreference);
  void Promise.all(
    [...new Set(layers.flatMap((layer) => [layer.day, layer.night]))].map(
      async (path) => images.set(path, await texture(path)),
    ),
  ).then(() => {
    if (!destroyed) draw();
  });
  resize();
  syncCelestial();
  resume();

  return {
    setTheme,
    destroy: () => {
      destroyed = true;
      pause();
      resizeObserver?.disconnect();
      if (!resizeObserver) window.removeEventListener("resize", resize);
      intersectionObserver?.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
      motionPreference.removeEventListener("change", handleMotionPreference);
    },
  };
}

export interface VillageSceneProps {
  dark: boolean;
  onToggleTheme: () => void;
  disabled?: boolean;
}

export function VillageScene({
  dark,
  onToggleTheme,
  disabled = false,
}: VillageSceneProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sunRef = useRef<HTMLImageElement>(null);
  const moonRef = useRef<HTMLImageElement>(null);
  const engineRef = useRef<SceneEngine | null>(null);

  useEffect(() => {
    const viewport = viewportRef.current;
    const canvas = canvasRef.current;
    const sun = sunRef.current;
    const moon = moonRef.current;
    if (!viewport || !canvas || !sun || !moon) return;

    const engine = createScene(viewport, canvas, sun, moon, dark);
    engineRef.current = engine;
    return () => {
      engine.destroy();
      if (engineRef.current === engine) engineRef.current = null;
    };
  }, []);

  useEffect(() => {
    engineRef.current?.setTheme(dark);
  }, [dark]);

  const nextMode = dark ? "day" : "night";

  return (
    <div className="village-scene" ref={viewportRef} aria-hidden="false">
      <canvas
        ref={canvasRef}
        className="village-scene__canvas"
        width={WORLD_WIDTH}
        height={WORLD_HEIGHT}
        aria-hidden="true"
      />
      <button
        className="village-scene__celestial"
        type="button"
        aria-label={`Switch to ${nextMode} mode`}
        aria-pressed={dark}
        title={`Switch to ${nextMode} mode`}
        disabled={disabled}
        onClick={onToggleTheme}
      >
        <img
          ref={sunRef}
          className="village-scene__sun"
          src={`${ASSET_ROOT}assets/environment/v2.1-textures/sun-day_png.png`}
          style={{ opacity: dark ? 0 : 1 }}
          alt=""
          draggable={false}
        />
        <img
          ref={moonRef}
          className="village-scene__moon"
          src={`${ASSET_ROOT}assets/environment/v2.1-textures/moon-night_png.png`}
          style={{ opacity: dark ? 1 : 0 }}
          alt=""
          draggable={false}
        />
      </button>
    </div>
  );
}
