import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

// Integer-grid redraws of the supplied stepped panel and scalloped cloud.
const root = "apps/desktop/public/design/media/assets/panels";
const colors = ["#493263", "#c1a7e9", "#f0e6ff", "#fffaf4"];

function inside(x, y, points) {
  let covered = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [ax, ay] = points[i];
    const [bx, by] = points[j];
    if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) covered = !covered;
  }
  return covered;
}

function borderLayers(width, height, points) {
  let mask = Array.from({ length: height }, (_, y) =>
    Array.from({ length: width }, (_, x) => inside(x + 0.5, y + 0.5, points)));
  const pixels = Array.from({ length: height }, () => Array(width).fill(null));

  for (const color of colors) {
    const next = mask.map((row, y) => row.map((on, x) => {
      if (on) pixels[y][x] = color;
      // Erode a single square pixel to keep every rim the same thickness.
      return on && [-1, 0, 1].every((dy) => [-1, 0, 1].every((dx) => mask[y + dy]?.[x + dx]));
    }));
    mask = next;
  }
  return pixels;
}

async function writeSlices(name, pixels, columns, rows, reference) {
  const directory = path.join(root, name, "nine-slice");
  await mkdir(directory, { recursive: true });
  const labels = [["top-left", "top", "top-right"], ["left", "center", "right"], ["bottom-left", "bottom", "bottom-right"]];
  let y = 0;
  for (let row = 0; row < 3; row++) {
    let x = 0;
    for (let column = 0; column < 3; column++) {
      const width = columns[column];
      const height = rows[row];
      const palette = new Map();
      for (let py = 0; py < height; py++) {
        let px = 0;
        while (px < width) {
          const color = pixels[y + py][x + px];
          const start = px++;
          while (px < width && pixels[y + py][x + px] === color) px++;
          if (color) palette.set(color, (palette.get(color) ?? "") + `M${start},${py}h${px - start}v1h${start - px}Z`);
        }
      }
      const artwork = [...palette].map(([fill, d]) => `<path fill="${fill}" d="${d}"/>`).join("");
      const label = labels[row][column];
      await writeFile(path.join(directory, `${label}.svg`),
        `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" shape-rendering="crispEdges"><title>Hanly ${name}: ${label}</title>${artwork}</svg>\n`);
      x += width;
    }
    y += rows[row];
  }
  await writeFile(path.join(directory, "source.json"), JSON.stringify({
    reference, method: "Integer-grid redraw; mirrored contours; three one-pixel rim bands; flat interior; no cast shadow",
    palette: [...new Set(pixels.flat().filter(Boolean))], columns, rows,
  }, null, 2) + "\n");
}

const panel = borderLayers(64, 80, [
  [8, 0], [56, 0], [56, 2], [60, 2], [60, 4], [62, 4], [62, 8], [64, 8],
  [64, 72], [62, 72], [62, 76], [60, 76], [60, 78], [56, 78], [56, 80],
  [8, 80], [8, 78], [4, 78], [4, 76], [2, 76], [2, 72], [0, 72],
  [0, 8], [2, 8], [2, 4], [4, 4], [4, 2], [8, 2],
]);
for (let y = 0; y < 34; y++) {
  for (let x = 0; x < 64; x++) {
    if (panel[y][x] === colors[3]) panel[y][x] = y < 32 ? "#b5a9fb" : "#9474cc";
  }
}
await writeSlices("panel-popup-clean-v2", panel, [16, 32, 16], [34, 30, 16], "Hanly Design Lab V2.4.1 panel-popup-v1.svg");

const cloudQuarter = [
  [0, 24], [2, 24], [2, 18], [4, 18], [4, 14], [8, 14], [8, 10],
  [14, 10], [14, 8], [18, 8], [18, 4], [22, 4], [22, 2], [28, 2],
  [28, 0], [38, 0], [38, 2], [42, 2], [42, 4], [46, 4], [46, 6],
  [50, 6], [50, 4], [56, 4], [56, 6], [60, 6], [60, 8], [62, 8],
];
const cloudTop = [...cloudQuarter, ...cloudQuarter.slice(0, -1).reverse().map(([x, y]) => [124 - x, y])];
const cloudOutline = [...cloudTop, ...cloudTop.slice().reverse().map(([x, y]) => [x, 96 - y])];
await writeSlices("panel-cloud-clean-v2", borderLayers(124, 96, cloudOutline), [31, 62, 31], [24, 48, 24], "Hanly Design Lab V2.4.1 panel-cloud-v2.svg");
