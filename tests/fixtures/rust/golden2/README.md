# golden2: shadows, accessories, skinning, the background, and the edge probe

Golden images of the C++ application for the rendering that `mds-render` does
not have yet (slice `render2`), and a probe of the values the C++ feeds its
edge thickness.

Rendered on the Windows host `nanoha-lan` (i9-12900K, RTX 3090, VS 2022 Build
Tools, x64 Release) by the app built at `55a19d9` with
`tools/windows/build.ps1`. The back buffer was 3072x1728, A8R8G8B8 (format 21),
8x multisampling. `tools/oracle/golden2.ps1` ran every scene twice in the
console session (`tools/windows/runtask.ps1`), and the two runs gave the same
bytes for every file. On the same build, `tools/oracle/frame_dump.ps1` still
gave the four hashes of `../golden/README.md`.

## Regenerating

The inputs (the scene PMMs, `skin_tex.pmx`, the textures, the two floor
accessories, and `background.png`) come from `gen_golden2.py`, which imports
`tools/fixtures/gen_fixtures.py` and `../skin/gen_skin.py`:

    python3 -I tests/fixtures/rust/golden2/gen_golden2.py --write   # or --check

The outputs come from the Windows host, from a checkout at `<checkout>`:

1. `tools\windows\build.ps1 -Root <checkout> -Testing OFF -Targets MikuDanceStudio`
2. `tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\golden2.ps1
   -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir>'`

`golden2.ps1` copies the models, textures, and accessories next to the exe,
runs `--mds-frame-dump` and `--mds-edge-probe` on each scene into `<Out>\run1`
and `<Out>\run2`, and the edge probe of `../swing600-golden.pmm` (frames 0,
150, 300, 599). It prints the size and sha256 of each file and exits 1 when a
run fails or the two runs differ. Copy `<Out>\run1\*` here. The frames of each
scene are listed in `golden2.ps1` and in `SCENES` of `gen_golden2.py`
(`gen_golden2.py --frames` prints them).

No `Data\` folder is next to the exe, so the app runs with its built-in
defaults, as for `../golden/`. The images are the picture-file output, 640x360,
as `../golden/README.md` describes.

## Scenes

Every scene runs with physics mode 0 (no calculation), so a pose is its keys.
The models blend normally. Scenes 1 to 5 use the orthographic camera of the
golden scene (yaw pi faces the fronts of the models) pitched down by 0.375
rad so the ground shows. With yaw pi, +x is on the left of the image.

| Scene | Frames | What it checks |
|---|---|---|
| `selfshadow` | 0, 30 | Self-shadow. `chain8.pmd` at x = +3 and `chain8.pmx` at x = -3, their upper bones curled toward the camera, over `shadow_floor.x` (8 units wide). The state and key 0 are mode 1 at distance 0.01125 (the app's default, range 8875); a key at frame 30 sets mode 2 at distance 0.005. Only `chain8.pmd` casts a visible shadow onto the floor. |
| `groundshadow` | 0, 30 | The projected ground shadow (view flag 1), with the shadow ambient at 0.5 and the translucent flag at 1 (the app's start-up value). A light key at frame 30 turns the light from (-0.5, -1, 0.5) to (0.5, -1, 0.25), so the shadows move. Self-shadow is off. |
| `accessory` | 0, 30 | `cube.x` (`../accessory/`, textured with `cube.bmp`) parented to bone 頭 of `chain8.pmx`, and `floor.x` on the ground. The model's root moves by 3 along x and turns by frame 30, and the cube follows. |
| `skin` | 0, 30 | `skin_tex.pmx` under a perspective camera: SDEF and BDEF vertices with bones 2 and 3 turned, and at frame 0 vertex morph `v0`, UV morph `uv`, and material morph `matmul` (0.5); at frame 30 `v1`, `uv` (0.5), `uv2`, `matadd`, and bone morph `bone`. Edge scale 2. |
| `background` | 0 | A background picture (`background.png`, 640x360, at scale 0.25) behind `chain8.pmx`. |
| `perspective` | 0, 30 | A perspective camera over three models at three depths. A second camera key at frame 30 moves it in (distance 45 to 30), turns it by 0.5 rad, and widens the view angle from 30 to 45. |

`*.edge.txt` is the edge probe of each scene at the same frames.
`swing600-golden.edge.txt` is the probe of the golden scene of `../golden/`.

## The edge probe

`--mds-edge-probe <pmm> <out> <frame>...` runs the setup and passes of
`--mds-frame-dump`, and at each requested frame writes the inputs and the
result of `PmdEdgeDistance` (`src/model/model_skinning.cpp`), which
`UpdateModelVertexBuffers` uses for the edge of every PMD and PMX model. The
format is in `src/tools/trace_mode.cpp`. Floats are `%.9g`, which reads back to
the same float.

What it shows:

- The distance in the formula is not the camera distance. It is from the
  model's bone 1 (bone 0 for a one-bone model), moved by its `matInit` and then
  by the frame world matrix (the camera target moved to the origin and the
  camera rotation applied), to `CameraPosition`, which is the camera target.
- `CameraFov` is the key's view angle in degrees, also under the orthographic
  camera. In the golden scene it is 30, and the edge is 0.01625 to 0.01921 per
  model (`swing600-golden.edge.txt`). `ORTHO_EDGE_FOV` in
  `rust/crates/mds-render/src/view.rs` was fitted to these images with the
  camera distance in the formula; with the probe's distance it is not needed.
- The golden scene of `../golden/` renders with self-shadow on: mode 1 at
  distance 8875.0 (the raw float; the app's own default is 0.01125) until
  frame 300, and mode 2 at 5000.0 from frame 300.

## Notes for render2

- The background picture is placed by the main window's viewport, not by the
  640x360 output. `PicBgOverlayRefresh` (`src/render/bg_overlay.cpp`) placed
  the quad at PMM load, and the frame dump's viewport refresh does not move
  it. On this host the main viewport was (259, 94)-(2544, 1378), so the quad
  is (258, 93)-(544.625, 254.664) in output pixels. The `picture` line of
  `background.edge.txt` records the inputs and the quad. The placement depends
  on the host's window geometry.
- The picture is drawn with a fan-shaped distortion toward its top-right
  corner. `WriteOverlayQuad` (`src/render/bg_overlay.cpp`) writes rhw for five
  of the six vertices and never for vertex 0, which stays 0 (the probe's six
  rhw values are 0 1 1 1 1 1). This looks like a port bug outside this slice.
  If it is fixed in the C++, regenerate `background-0.png`.
- The app loads a background picture at 1024x1024 through D3DX
  (`src/media/media_load.cpp`), so the picture is resampled before it is
  drawn.
- The app draws an accessory at 10 times its scale value, and lights it with
  a light ten times as bright as for models (`SetAccessoryLight`). The `.x`
  normals do not change the image. An accessory with no material list
  (`../accessory/normals_uv.x`) draws nothing.
- Under self-shadow, an accessory with the shadow flag is drawn by the effect
  path: the emissive part is scaled by the projected-shadow ambient (1.0 in
  every scene but `groundshadow`), and the shadow darkens the diffuse part
  (diffuse times the light's ambient) only.
- The model path of `skin_tex.pmx` in `skin.pmm` is `.\skin_tex.pmx`. The
  loader takes a model's texture directory from its path up to the last
  backslash (`src/model/pmd_load.cpp`); a bare file name keeps its first
  letter as the directory, and the texture does not load. The chain models
  keep bare names as in `../`, and their texture (`chain.png`) does not exist.
- `skin_tex.pmx` is `../skin/skin.pmx` with one texture (`skin_tex.bmp`, four
  colored quadrants) on every material, so that its UV morph shows.

## Files

| File | sha256 |
|---|---|
| `accessory-0.png` | `a194beaf970024b8e021353fed01f2a366aee9e63df92513b06c613976932e88` |
| `accessory-30.png` | `8add3276c3099c4e84a9ef677f581ee126181c348e31ea3718b02083a56d0926` |
| `accessory.edge.txt` | `e43816734fec167cdebd7ab8b941837bcba8254a8741b5c90267bf98ccaf8f3a` |
| `accessory.pmm` | `1999aa8468326af880725c55507aae3e842f2cb56526197533e4f70c685fd18d` |
| `background-0.png` | `022d2cfbb217525a155fa1c7b9dc76b64a2e9a418ed2956c9648e1e9e5f55fbd` |
| `background.edge.txt` | `ae18d92c9cbe592be2debaa0700b0c7a06b08277539bdb19d6de15d954cfb703` |
| `background.pmm` | `39ccdf20fe5f3a1539d7f4db58371ed2e34589bc1c095373e9a0a25c52b7e02b` |
| `background.png` | `5229108100e3f23c484371e339a2b4753bfb20163d9c1b255ed88d977d4f6086` |
| `cube.bmp` | `03d4440c5187c34b96419855ae59c95e680a3e6ee64e7a9eb459a6a7f72adb5e` |
| `floor.x` | `92cc8419313e62080f965c96670901172247715a8b3bb5be432de0d5a179faed` |
| `gen_golden2.py` | `ed30c8d72735a5c455c3c95d07b100e7f721b6001c046a64402c7c994b92a6e9` |
| `groundshadow-0.png` | `52f289d606cbd3c05127639c0606b3b2fe5f2c82d8e43202e45a5237ee7bb19f` |
| `groundshadow-30.png` | `a552bf547f309d8b447b7ebfa3c4d174bca1938aa2b9ee412ec16f9ecf05d445` |
| `groundshadow.edge.txt` | `9c8fe50342eda0e56bd9a7f088c3ca0246b25a378d086f08003f15486b914bee` |
| `groundshadow.pmm` | `7ced241949f6f1f4b9ce0b3b667a839615025b96e89dc921b94c3aab5e8a71f6` |
| `perspective-0.png` | `f9650fcb5e7a4a0e6641630c48171aa738a05d882e632007f286b6e35854f1ec` |
| `perspective-30.png` | `f95b4a111d6e47a4551d869fb03c680c98bfe7022edf8a332fd48648f93f19ea` |
| `perspective.edge.txt` | `eafe1eaf4ddc44eaf2abeaa0652fd5139f1b9064a2ed9f53293718350b760b57` |
| `perspective.pmm` | `84189b5a3823d055f8be18fc409fe94c3d148017616c3c17687274366bf21560` |
| `selfshadow-0.png` | `f8221a1d580936b8ebb1cc055551bac45828461fe14a1623303309482b8c10a2` |
| `selfshadow-30.png` | `676112eea1f08aceb417496df94d62cb2eb9b7acb34c44cb60ecb26694941282` |
| `selfshadow.edge.txt` | `daaf94eabe55367568b92a67d6cb37933a5043b3eb6164aba412d7555b25e0d2` |
| `selfshadow.pmm` | `92a5e88cf88503008db063980562c849acaa80e4468613fc4db2d162e8a76923` |
| `shadow_floor.x` | `adfd3e6fb4b552f6c38eb9b94bc8b75061270e7d24a4933694c73df02e58122c` |
| `skin-0.png` | `b2a5c0da74e192d85433a74504950636b6826970f06f37a97c04b92d7ab257c4` |
| `skin-30.png` | `ba2e8a493608fa0246c060dc14d16e6b3924979704d85fa23e9abfea29d9bab5` |
| `skin.edge.txt` | `64d44b3f7f92e27816fe51f54393c03d59fd6d44b17d832c1150e23b5e82dc1d` |
| `skin.pmm` | `5d9fd5109107f192eab2d50c194667bfbaf69ec18bb00502ae51de7c642dbab0` |
| `skin_tex.bmp` | `708f3534771b0d9c5b190205ccc6b6dac70ead99618dbc86c253761274f24260` |
| `skin_tex.pmx` | `4fc6322df25582ce85d9926915d87d90de6323a5d71ca81991e88f6c51f5a488` |
| `swing600-golden.edge.txt` | `57b50a40ae64ab7b97b6f0d946fdc7253215a91322e973b9f91c100f3dfa40e4` |
