# Clean panel v2

Editable nine-slice SVG derivative of the supplied `panel-popup-v1.svg` from
Hanly Design Lab V2.4.1. The original PNG assets remain unchanged.

The source's content slice included a lavender bottom band, stepped white
patches and raster color variation. Those became visible interior stains under
the dark-theme filter. This version uses uniform cream content and lavender
title fills, retains the original outer pixel outline and bevel paths, and
removes the offset blush shadow and exterior fringe.

Slice dimensions and the 1516x608 source coordinate system are unchanged.
`nine-slice/source.json` records the source hash, flat fill bounds and crops.
There are no embedded raster images or external SVG dependencies.

To regenerate from the original editable source:

```sh
node tools/design/build_clean_panel.mjs /path/to/panel-popup-v1.svg \
  apps/desktop/public/design/media/assets/panels/panel-popup-clean-v2/nine-slice
```

The Control Center uses this variant through `--skin-panel-slices`; button,
cloud, window and dictionary popup artwork are separate assets.
