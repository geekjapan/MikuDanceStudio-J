# PMM 0001 saved as 0002 (`--mds-script`)

One script per scene of `../../pmm1/` (its README describes the scenes):
the C++ application loads the 0001 file (`LoadSceneFile`, which reads it with
`src/io/pmm_load_v1.cpp`) and saves the scene as 0002 (`SaveSceneFile`).
The saved PMMs are the oracle for the 0001 reader of `mds-formats`: a Rust
load of the 0001 file and save as 0002 must give the same bytes. The runner
and the script language are those of `../../script/README.md`; `answer file`
is in `../README.md`.

| Script | Input | Notes |
|---|---|---|
| `v1_rig.txt` | `v1_rig.pmm` | Loads with no question. |
| `v1_scene.txt` | `v1_scene.pmm` | Queues `.\cube.x` and `.\sphere.x` (below). |
| `v1_multi.txt` | `v1_multi.pmm` | Queues `.\cube.x`. |
| `v1_noparent.txt` | `v1_noparent.pmm` | Loads with no question. |
| `v1_edge.txt` | `v1_edge.pmm` | Loads with no question. |

The lane stages `../../pmm1/*` and `inputs/*` next to the exe
(`script_run.ps1 -Dir script2\pmm1`).

## The accessories, the wave, and the picture

`v1_scene.pmm` and `v1_multi.pmm` name their accessories by bare file names
(`cube.x`, `sphere.x`). The accessory loader opens a path only when it holds
a backslash, so the 0001 loader shows "xファイルが見つかりません" and
"アクセサリファイル(<name>)が見つかりません" for each one and opens a file dialog, as
it would for a user. The scripts answer those dialogs with `.\cube.x` and
`.\sphere.x` (`answer file`), and `messages.tsv` lists the boxes. The saved
0002 files hold those paths.

`inputs/` holds stand-ins, so every load the scenes ask for succeeds:
`cube.x` and `sphere.x` are copies of `../../script/inputs/tri.x`,
`voice.wav` (the wave of `v1_scene.pmm`) is a copy of
`../../script/inputs/tone.wav`, and `bg.bmp` (its background picture) is a
generated 2x2 24-bit BMP of 70 bytes.

## Outputs

`expected/<script>/` holds `manifest.tsv`, `messages.tsv` where boxes were
answered, the 0002 PMM, and its `.emm`, which holds the absolute paths of the
staged files on the host. Each 0002 PMM reads and writes back byte for byte
through `mds-formats roundtrip`.

Build: commit `164147f` of branch `w2-script2` on `nanoha-lan` (Windows, x64
Release, VS 2022), run 2026-10-26 with
`script_run.ps1 -Dir script2\pmm1` (see `../../script/README.md` for the
`runtask.ps1` line). Two runs gave identical bytes for every file.

## Files

| File | sha256 |
|---|---|
| `expected/v1_edge/manifest.tsv` | `62807c6bab22fdea00d9c1d71be4a6cbe848adaba7c381dcc6af83dc8c223871` |
| `expected/v1_edge/v1_edge.emm` | `0794325430057e20f9b3acbec8bba69546ed1f526bb7fa1f726e48835c9c9e86` |
| `expected/v1_edge/v1_edge.pmm` | `f0e654330d9f184ea9faafb20ebbb454c02b15ec8af716e637ededb008152836` |
| `expected/v1_multi/manifest.tsv` | `fdfa7463fd6b279371ea1e7f93fe1bdc39134d5cf7e7cd302dac21a9a83b181c` |
| `expected/v1_multi/messages.tsv` | `c1059530269bb4ff9f926b6e10fe6ba26e7b36210e46630619cb0b2fe6451a11` |
| `expected/v1_multi/v1_multi.emm` | `e06a9778db78bee1b271692bdb4241b2f01f518e1948dfd11a7a0ae4cca308c7` |
| `expected/v1_multi/v1_multi.pmm` | `1f0895c8408e210e44ea53a6d977da2fe3cdffd5e64c80f7985cf655ce4d11e6` |
| `expected/v1_noparent/manifest.tsv` | `d44b906f5c357252c28d91941d60ff280debf71bba21fe08c9dac7cc9ec532d0` |
| `expected/v1_noparent/v1_noparent.emm` | `0794325430057e20f9b3acbec8bba69546ed1f526bb7fa1f726e48835c9c9e86` |
| `expected/v1_noparent/v1_noparent.pmm` | `d80f68a6be66525fcbc749c756716209497529f7ef442ec66d60364f5138f35e` |
| `expected/v1_rig/manifest.tsv` | `2ceb9441f7f180755aabdda47b6f067c120e6a3c87b782224f139966de859950` |
| `expected/v1_rig/v1_rig.emm` | `9e51f902e855ac34caf0cbfa54c207f343252dc6f5f44bb0066b76a854af5592` |
| `expected/v1_rig/v1_rig.pmm` | `ae064bf634aeddf9581924456e3c5ac647fff29ba87e0a0dda0d7797e12bed44` |
| `expected/v1_scene/manifest.tsv` | `53a7050b79d57ba3a2879a420ab9d838cd1156fc0c7fe3693c4f578f42b8acf3` |
| `expected/v1_scene/messages.tsv` | `1806597951dea8e62b70a0e6a5f59cb1d81f6f6107846c939eb56b902dfa2391` |
| `expected/v1_scene/v1_scene.emm` | `641c58ba77e3bf26c9e04b5246947369c018d846de431eb11de0ac58c2cc6c3a` |
| `expected/v1_scene/v1_scene.pmm` | `2663c50465d48821f111e3c5ee8209022332cb65b3eb6093be86d90f4be5d379` |
| `inputs/bg.bmp` | `7a9f3419a01af0bc1d4c013e76ae93340b92695659455b68d92f85abe5aa71b1` |
| `inputs/cube.x` | `3d444ec4a9e9dbeea26c27b36b59cc091149802e9e8fe154e4458cfabe46840c` |
| `inputs/sphere.x` | `3d444ec4a9e9dbeea26c27b36b59cc091149802e9e8fe154e4458cfabe46840c` |
| `inputs/voice.wav` | `b4a06f168ffa5e83e28aecf46896a6d5387ab7445dfbcbc172710ceb9c9c5e2c` |
| `v1_edge.txt` | `4d8c966b2fbe694c6c2a2b1b819e8b0bbbf0b19254a5a86ab56aec22308be3ba` |
| `v1_multi.txt` | `750ac2ec929e24d94fac761a81f1af300e5455642edb18736dec2092a44710e7` |
| `v1_noparent.txt` | `c9e28f3b5a8df8fa3001937b99a51470c85d34172dc9c386c3cdf76e77a30d0a` |
| `v1_rig.txt` | `44a9fc482b4f160985a313f74079373cdc393e9f6204e53166534f0f3e52c7cf` |
| `v1_scene.txt` | `0813d1f6a276ce86ab341b1b5b6b230ab42e9f134b282c71b2c0301c88baabf5` |
