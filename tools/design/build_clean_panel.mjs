import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

// The editable source encodes its pixel palette as merged rectangular paths.
const [source, destination] = process.argv.slice(2);
if (!source || !destination) {
  throw new Error("Usage: node tools/design/build_clean_panel.mjs SOURCE.svg OUTPUT_DIRECTORY");
}

const original = await readFile(source, "utf8");
if (!/viewBox="0 0 1516 608"/.test(original)) {
  throw new Error("Expected the original 1516x608 editable panel source.");
}
const parts = [
  ["top-left", 0, 0, 106, 182], ["top", 106, 0, 1304, 182],
  ["top-right", 1410, 0, 106, 182], ["left", 0, 182, 106, 353],
  ["center", 106, 182, 1304, 353], ["right", 1410, 182, 106, 353],
  ["bottom-left", 0, 535, 106, 73], ["bottom", 106, 535, 1304, 73],
  ["bottom-right", 1410, 535, 106, 73],
];
const fills = [
  { box: [32, 44, 1454, 156], color: "#b5a9fb" },
  { box: [32, 182, 1454, 551], color: "#fffaf4" },
];

function intersect(a, b) {
  const result = [Math.max(a[0], b[0]), Math.max(a[1], b[1]),
    Math.min(a[2], b[2]), Math.min(a[3], b[3])];
  return result[0] < result[2] && result[1] < result[3] ? result : null;
}

function subtract(rectangle, cut) {
  const overlap = intersect(rectangle, cut);
  if (!overlap) return [rectangle];
  const [x0, y0, x1, y1] = rectangle;
  const [left, top, right, bottom] = overlap;
  return [[x0, y0, x1, top], [x0, bottom, x1, y1],
    [x0, top, left, bottom], [right, top, x1, bottom]]
    .filter(([x, y, endX, endY]) => x < endX && y < endY);
}

function pixelPath([x, y, right, bottom], offsetX, offsetY) {
  return `M${x - offsetX},${y - offsetY}h${right - x}v${bottom - y}h${x - right}Z`;
}

const palette = [];
for (const group of original.matchAll(/<g[^>]*fill="(#[0-9a-f]{6})"[^>]*>([\s\S]*?)<\/g>/gi)) {
  const color = group[1];
  const [red, green, blue] = color.slice(1).match(/../g).map((hex) => parseInt(hex, 16));
  // Remove the offset blush shadow: night filtering turned it into a boxy halo.
  if (red > 220 && green < 230 && blue < 235) continue;
  const rectangles = [];
  for (const shape of group[2].matchAll(/<path[^>]+d="([^"]+)"/g)) {
    const remaining = shape[1].replace(/M(-?\d+),(-?\d+)h(\d+)v(\d+)h-\d+Z/g,
      (_, x, y, width, height) => {
        const box = intersect([+x, +y, +x + +width, +y + +height], [0, 0, 1486, 579]);
        if (box) rectangles.push(...fills.reduce(
          (pieces, fill) => pieces.flatMap((piece) => subtract(piece, fill.box)), [box]));
        return "";
      });
    if (remaining.trim()) throw new Error("The source contains unsupported non-rectangular paths.");
  }
  palette.push({ color, rectangles });
}
if (!palette.length) throw new Error("No editable pixel palette found in source.");

await mkdir(destination, { recursive: true });
for (const [name, x, y, width, height] of parts) {
  const bounds = [x, y, x + width, y + height];
  const artwork = palette.map(({ color, rectangles }) => {
    const regions = rectangles.map((box) => intersect(box, bounds)).filter(Boolean);
    return regions.length ? `<path fill="${color}" d="${regions.map((box) => pixelPath(box, x, y)).join("")}"/>` : "";
  }).join("");
  const paper = fills.map(({ box, color }) => {
    const region = intersect(box, bounds);
    return region ? `<path fill="${color}" d="${pixelPath(region, x, y)}"/>` : "";
  }).join("");
  await writeFile(path.join(destination, `${name}.svg`),
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" shape-rendering="crispEdges"><title>Hanly clean panel v2: ${name}</title>${artwork}${paper}</svg>\n`);
}
await writeFile(path.join(destination, "source.json"), JSON.stringify({
  source: path.basename(source), sha256: createHash("sha256").update(original).digest("hex"),
  changes: ["Uniform content paper and title fill", "Removed offset shadow and raster fringe"],
  canvas: [1516, 608], fills, parts,
}, null, 2) + "\n");
