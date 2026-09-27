# Hanly identity sources

Nothing under `design/` is packaged. The shipped icons live in
`packages/hanly-app/src/hanly_app/assets/icons/` and `packaging/icons/`.

## Active identity: purple v1

Windows, Linux, the tray, the window face and the favicon use the purple B2
pixel-art family, integrated unchanged from the approved Windows package
(`hanly-windows-purple-assets-v1`). It recolors the pink family only; every
alpha mask is identical to `archive/pink-v1/`.

| Role | Hex |
| --- | --- |
| Primary lavender | `#C4BBEF` |
| Secondary light | `#C2B9ED` |
| Shadow purple | `#A599DE` |
| Dark outline | `#8171D0` |
| Pale highlight | `#DED8FA` |

macOS uses `source/macos/Hanly-macOS-v2.icon`, rendered in its `TintedLight`
appearance with Icon Composer's default tint (design generation 27) and baked
into static bitmaps, so the Dock, Cmd+Tab and Finder show purple in every
system appearance. That rendering matches the approved
`Hanly-macOS-v2-tinted-light.png` exactly. The shape is 824 px on a 1024 px
canvas, Apple's icon grid.

Regenerate `hanly-macos-icon.png` and `hanly.icns` with Xcode installed:

```bash
python design/identity/source/macos/build_macos_icon.py
```

## Archive

`archive/pink-v1/` holds the previous pink icons; its `MANIFEST.md` maps each
file back to its original path.
