# Clean compact plaque v2

The compact runtime card uses the clean panel's mirrored stepped outline with
no title strip. It replaces the older ornate frame and inset rectangular paper
layer. The interior is a uniform fill inside the three one-pixel rim bands;
there are no textures, offset shadows or separate background patches.

Corners render at their native 16x16 pixel grid, matching the main clean panel.
Regenerate with `node tools/design/build_clean_frames.mjs` from the repository
root. Slice geometry and palette are recorded in `nine-slice/source.json`.
