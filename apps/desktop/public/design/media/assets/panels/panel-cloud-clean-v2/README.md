# Clean cloud v2

Integer-grid SVG redraw of the supplied Hanly Design Lab V2.4.1 scalloped cloud.
The cloud silhouette retains stepped lobes, with mirrored horizontal/vertical
contours, three one-pixel rim bands and a uniform cream interior. Texture noise,
interior lavender patches and the pink offset shadow are removed. Original
gallery files are preserved.

Corner slices render at their native 31x24 grid. Straight stretches carry solid
colors, with no embedded raster, anti-aliasing gradients or cast shadows. Each
SVG uses `crispEdges`; `source.json` records the palette and slice geometry.

Regenerate with `node tools/design/build_clean_frames.mjs` from the repository
root. The normal runtime card uses this artwork; compact navigation retains its
separate small framed plaque.
