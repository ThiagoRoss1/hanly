# Clean panel v2

Editable nine-slice SVG redraw of the supplied stepped panel from Hanly Design
Lab V2.4.1. The original PNG assets remain unchanged.

The source's content slice included a lavender bottom band, stepped white
patches and raster color variation. Those became visible interior stains under
the dark-theme filter. This version uses uniform cream content and lavender
title fills. The outline is now redrawn on an integer pixel grid, with mirrored
top/bottom and left/right corner geometry, three consistent one-pixel rim bands
and no cast shadow, texture noise or exterior fringe.

The rendered corners use a 16px grid. The title slice is 34px tall and the bottom
slice is 16px tall; both corner contours have identical eight-pixel steps.
`nine-slice/source.json` records the reference, palette and slice geometry.
There are no embedded raster images, fractional coordinates, filters or external
SVG dependencies. The application applies its existing night palette filter.

To regenerate both clean frames from their editable integer-grid definitions:

```sh
node tools/design/build_clean_frames.mjs
```

The Control Center uses this variant through `--skin-panel-slices`; button,
cloud, window and dictionary popup artwork are separate assets.
