# Pink identity v1 (archived)

The pink Hanly icons as they shipped at commit `0901b62`, kept so the switch to
the purple identity can be reversed exactly. Nothing here is packaged: the
package-data and PyInstaller globs only read
`packages/hanly-app/src/hanly_app/assets/icons/`.

To restore, copy each file back to its original path and revert
`hanly-macos-icon.png`'s size in `hanly_app.app_icon.MACOS_ICON_SIZE` to 1248.
Update the macOS geometry assertion in `tests/test_app_identity.py` to the
archived alpha bounds `(124, 124, 1124, 1124)` as well; keep the full-channel
runtime/bundle pixel comparison. Then rerun the identity and native Qt icon
tests and rebuild the package. Restoring assets alone leaves the purple
geometry assertion in place and correctly fails that test.

| Archived file | Original path | SHA-256 |
| --- | --- | --- |
| `app-icons/favicon.ico` | `packages/hanly-app/src/hanly_app/assets/icons/favicon.ico` | `83412a5933c22cd859a94989ffcbf2b165c08b5fa244af773465bff9f91af6ea` |
| `app-icons/hanly-icon-128.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-128.png` | `dcd52d2ed3dc2171e783f1199728277c66d3beb0db4a69f9276df0824d35bacb` |
| `app-icons/hanly-icon-16.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-16.png` | `45c25afc5bde37aab82325db3ccd997f435a5226789e7573ca64025265532e6d` |
| `app-icons/hanly-icon-24.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-24.png` | `532046e99f203802744a392e9ee2f47fdf4ace6d98a1dfd4c116dda89760a270` |
| `app-icons/hanly-icon-256.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-256.png` | `efd2a961911b88d903cbc36e5071315bd779a79c3730501f1126f34a1017fc54` |
| `app-icons/hanly-icon-32.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-32.png` | `3b363210f5db85bf14c3fac50cee3b5e3ef5962e97e0a8264fe62f56051d7535` |
| `app-icons/hanly-icon-48.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-48.png` | `465cb7b620e60e688ab6308a0a594eb11a923bc10e32aec2b8c1bb4d9f41cec5` |
| `app-icons/hanly-icon-512.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-512.png` | `fb2163744165af3808cd9cdbf671af9cae9d39056cd38fa1c6e8d76a7c5820c1` |
| `app-icons/hanly-icon-64.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-icon-64.png` | `e91ea7a8d8a670004c56cbeda94ecb1d3ecd5d83ef69f0b7df4cac48ab388367` |
| `app-icons/hanly-macos-icon.png` | `packages/hanly-app/src/hanly_app/assets/icons/hanly-macos-icon.png` | `2883c1bf2067c7537ff0c7714fbf0094020f612d5a828a8de8b6a46be0fbfd3c` |
| `app-icons/window-face-16.png` | `packages/hanly-app/src/hanly_app/assets/icons/window-face-16.png` | `3da059e06cbb34a035cb4b541ca5637411f64c54274b2b669a9cb062575f5482` |
| `app-icons/window-face-20.png` | `packages/hanly-app/src/hanly_app/assets/icons/window-face-20.png` | `b4c7c5f5a049785b64c0b2e30a6e3b2e174dbed44074c412055318cf52df181e` |
| `app-icons/window-face-24.png` | `packages/hanly-app/src/hanly_app/assets/icons/window-face-24.png` | `c9c08c1cf1b3afcc6e6138c78a93ec26c3e627db1e24fa92a686e83f8d11d61e` |
| `packaging/hanly.icns` | `packaging/icons/hanly.icns` | `f77d487194faf424255dcd46422670f84dcaa03bb8f2e953a2576daa045890bb` |
| `packaging/hanly.ico` | `packaging/icons/hanly.ico` | `f8e3c5ed33daed0df76c8d2aa2225eeb1e2453e7d936b30cf2745a781097010e` |
