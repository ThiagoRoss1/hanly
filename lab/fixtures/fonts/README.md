# Korean acquisition fixture fonts

These faces are test assets, not installed system fonts or Hanly runtime assets.
`manifest.json` pins the upstream commit, download URL, SHA-256 and license for
each file. The corresponding OFL license is retained beside every font.

| Face | Test role |
| --- | --- |
| Nanum Gothic | Normal UI text |
| Nanum Pen Script | Handwritten / comic-like text |
| Black Han Sans | Heavy display lettering |
| Galmuri11 | Pixel lettering |

`python -m lab grammar-pages --output artifacts/lab/grammar-pages` builds local
paired acquisition pages. Generated images, dictionary examples, ground truth
and source identities stay under that output directory. Glyph coverage is
checked before rendering; missing glyphs are explicit omissions, never silently
substituted. A handwritten face is only one controlled comic-like condition,
not evidence of accuracy on real comics.
