import { useEffect, useRef, type RefObject } from "react";
import {
  ASSET_ROOT,
  STAR_BRIGHTNESS,
  SWAY_POSE,
  VILLAGE_LAYERS,
  WORLD_HEIGHT,
  WORLD_WIDTH,
  type VillageLayer,
} from "./villageLayers";
import "../../styles/villageScene.css";

const TRANSITION_MS = 1500;
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
    const brightness = layer.motion === "twinkle" ? STAR_BRIGHTNESS[phase] ?? 1 : 1;
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
    const offset = Math.round((SWAY_POSE[frame] ?? 0) * weight * movementScale);
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
  content: HTMLElement | null,
): SceneEngine {
  const renderingContext = canvas.getContext("2d", { alpha: false });
  if (!renderingContext) return { setTheme: () => undefined, destroy: () => undefined };
  const context: CanvasRenderingContext2D = renderingContext;
  // Blend theme variants in isolation so night light cannot wash across scene layers.
  const layerCanvas = document.createElement("canvas");
  layerCanvas.width = WORLD_WIDTH;
  layerCanvas.height = WORLD_HEIGHT;
  const layerRenderingContext = layerCanvas.getContext("2d");
  if (!layerRenderingContext) return { setTheme: () => undefined, destroy: () => undefined };
  const layerContext: CanvasRenderingContext2D = layerRenderingContext;

  const images = new Map<string, HTMLImageElement | null>();
  let light = initialDark ? 1 : 0;
  let target = light;
  let transitionFrom = light;
  let transitionStarted = 0;
  let phase = 0;
  let raf = 0;
  let resizeFrame = 0;
  let timer: number | undefined;
  let pausedAt: number | null = null;
  let inViewport = true;
  let destroyed = false;
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");

  function syncCelestial(): void {
    sun.style.opacity = String(1 - light);
    moon.style.opacity = String(light);
    sun.style.transform = `translateY(${-190 * light}%) rotate(${-12 * light}deg)`;
    moon.style.transform = `translateY(${-190 * (1 - light)}%) rotate(${12 * (1 - light)}deg)`;
  }

  function resize(): void {
    const sidebar = viewport.parentElement;
    if (sidebar && content) {
      const style = window.getComputedStyle(sidebar);
      const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      // Measure controls, not scrollHeight: the scene itself contributes to overflow.
      viewport.style.height = `${Math.max(sidebar.clientHeight, content.offsetHeight + padding)}px`;
    }

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

    for (const layer of VILLAGE_LAYERS) paintThemeLayer(layer);
    syncCelestial();
  }

  function paintThemeLayer(layer: VillageLayer): void {
    if (layer.condition === "both") {
      layerContext.clearRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT);

      const dayImage = images.get(layer.day);
      if (dayImage && light < 1) {
        paintLayer(layerContext, layer, dayImage, 1 - light, phase, isMoving());
      }

      const nightImage = images.get(layer.night);
      if (nightImage && light > 0) {
        layerContext.globalCompositeOperation = "lighter";
        paintLayer(layerContext, layer, nightImage, light, phase, isMoving());
      }

      layerContext.globalAlpha = 1;
      layerContext.globalCompositeOperation = "source-over";
      context.drawImage(layerCanvas, 0, 0);
      return;
    }

    const isNight = layer.condition === "night";
    const image = images.get(isNight ? layer.night : layer.day);
    if (!image) return;

    const alpha = isNight ? light : 1 - light;
    paintLayer(context, layer, image, alpha, phase, isMoving());
    context.globalAlpha = 1;
    context.globalCompositeOperation = "source-over";
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

  function queueResize(): void {
    if (destroyed || resizeFrame) return;

    // Resizing the observed viewport during delivery creates a resize loop.
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = 0;
      if (!destroyed) resize();
    });
  }

  const resizeObserver =
    typeof ResizeObserver === "undefined" ? null : new ResizeObserver(queueResize);
  resizeObserver?.observe(viewport);
  if (content) resizeObserver?.observe(content);
  if (!resizeObserver) window.addEventListener("resize", queueResize);

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
    [...new Set(VILLAGE_LAYERS.flatMap((layer) => [layer.day, layer.night]))].map(
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
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      resizeObserver?.disconnect();
      if (!resizeObserver) window.removeEventListener("resize", queueResize);
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
  contentRef?: RefObject<HTMLElement | null>;
}

export function VillageScene({
  dark,
  onToggleTheme,
  disabled = false,
  contentRef,
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

    const engine = createScene(viewport, canvas, sun, moon, dark, contentRef?.current ?? null);
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
    <div
      className="village-scene pointer-events-none absolute inset-0 z-0 overflow-hidden bg-[#9cb9fc]"
      ref={viewportRef}
      aria-hidden="false"
    >
      <canvas
        ref={canvasRef}
        className="village-scene__canvas pointer-events-none absolute block max-w-none [image-rendering:pixelated]"
        width={WORLD_WIDTH}
        height={WORLD_HEIGHT}
        aria-hidden="true"
      />
      <button
        className="village-scene__celestial pointer-events-auto absolute top-2 right-[21px] z-[2] grid h-14 w-14 cursor-pointer place-items-center overflow-visible rounded-full border-0 bg-transparent p-0"
        type="button"
        aria-label={`Switch to ${nextMode} mode`}
        aria-pressed={dark}
        title={`Switch to ${nextMode} mode`}
        disabled={disabled}
        onClick={onToggleTheme}
      >
        <img
          ref={sunRef}
          className="village-scene__sun pointer-events-none absolute inset-0 block h-full w-full object-contain [image-rendering:pixelated] select-none"
          src={`${ASSET_ROOT}assets/environment/v2.1-textures/sun-day_png.png`}
          style={{ opacity: dark ? 0 : 1 }}
          alt=""
          draggable={false}
        />
        <img
          ref={moonRef}
          className="village-scene__moon pointer-events-none absolute inset-0 block h-full w-full object-contain [image-rendering:pixelated] select-none"
          src={`${ASSET_ROOT}assets/environment/v2.1-textures/moon-night_png.png`}
          style={{ opacity: dark ? 1 : 0 }}
          alt=""
          draggable={false}
        />
      </button>
    </div>
  );
}
