export const WORLD_WIDTH = 192;
export const WORLD_HEIGHT = 960;
export const ASSET_ROOT = "/design/media/";

type PointBounds = readonly [number, number, number, number];
type LayerCondition = "both" | "day" | "night";
type LayerMotion = "none" | "cloud-drift" | "tree-sway" | "twinkle";

export interface VillageLayer {
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

// Array order is the painting order; later foreground pieces cover earlier ones.
export const VILLAGE_LAYERS: readonly VillageLayer[] = [
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

export const SWAY_POSE = [0, 1, 1, 2, 0, -1, -2, -1] as const;
export const STAR_BRIGHTNESS = [1, 1.025, 1.025, 1, 0.985, 0.985, 1, 1] as const;
