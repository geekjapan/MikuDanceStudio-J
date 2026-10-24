# P2. MME shaders through vkd3d-shader and naga

Question. Can the shaders of MME effect files be compiled outside D3DX into a
form that wgpu accepts on Metal, Vulkan, and DX12?

Answer. The shader functions can. The effect framework around them cannot use
vkd3d-shader and needs a Rust parser.

## Setup

- `build.sh` builds vkd3d-shader 2.1 from the release tarball (sha256 in
  `vkd3d-2.1.sha256`) and installs `naga-cli` 30.0.1, inside
  `rust:1-trixie`.
- The corpus is ray-mmd at the commit in `ray-mmd.commit` (MIT license, 515
  `.fx` files) and the two MikuMikuDance standard effects
  `res/assets/skin_effect_sm2.fx` and `res/assets/skin_effect_sm3.fx`,
  converted from CP932 to UTF-8.
- `corpus.py` expands each `.fx` file, runs the vkd3d preprocessor, removes
  duplicate files by content, and finds every `compile <profile> <function>(...)`
  entry. An entry with arguments gets a wrapper function that passes the
  arguments to the `uniform` parameters. Each entry is compiled, checked with
  `spirv-val`, and written as WGSL, MSL, and HLSL by naga.
- `run_corpus.sh` runs the three modes below. `shaders-direct.tsv` lists the
  result per shader for the direct mode. Its paths start at `ray-mmd/` for the
  corpus and at `res/assets/` for the standard effects.

The script applies these source changes before compiling.

- Includes resolve against the directory of the top-level `.fx` file, then
  against the including file. Path parts match without case.
- Adjacent string literals are joined, and `technique` blocks are removed.
- With `SAMPLER_FIX=1`, `sampler2D` parameters become `sampler`.
- In vertex shaders, the `PointSize` output that vkd3d-shader always adds is
  removed from the SPIR-V before naga reads it.

## Results

490 unique effect files hold 1483 shader entries.

| Mode | SPIR-V valid | naga WGSL | naga MSL | naga HLSL | File |
|---|---|---|---|---|---|
| HLSL to d3dbc to SPIR-V | 1321 | 1321 | 1321 | 1321 | `results-d3dbc-nofix.txt` |
| Same, with `SAMPLER_FIX` | 1377 | 1377 | 1377 | 1377 | `results-d3dbc.txt` |
| HLSL to SPIR-V, with `SAMPLER_FIX` | 1413 | 1413 | 1413 | 1413 | `results-direct.txt` |

The direct mode passes 95.3% of the entries. These counts measure compiling
and validation. They say nothing about rendered images.

All 2303 includes resolved against the top-level directory. None needed the
fallback. One file includes `shader/CameraMotion.fxsub`, which the corpus
lacks.

## Failures in the direct mode

- 40 entries fail with E9022, `Unable to resolve I/O register type 0x1, index
  2`, in pixel shaders such as `VolumetricFogPS` in
  `Lighting/DiskLight/Default Ambient/disk_fog.fx`.
- 30 entries fail with E5027, `Infinities and NaNs are not allowed by the
  shader model`. The source is `pow(edgeLineColor, 2.2)` with a constant zero
  color in `Outline/Fixed Color x1/outline blue.fx`. Constant folding takes
  `log2(0)` and rejects the `-inf`.

The d3dbc modes also fail 36 entries with E9015, `Register r32 exceeds limits`,
because vkd3d-shader allocates more temporaries than the SM3 limit. The direct
mode has no such limit.

## Other findings

- `vkd3d-compiler -p fx_2_0` writes nothing for both standard effects. It stops
  with E5017 on `sampler_state` initializers and on pass state assignments such
  as `AlphaBlendEnable`, `CullMode`, `VertexShader`, and `PixelShader`.
- Without the string join, 863 entries fail with E5000 on `Script`
  annotations written as `"a;" "b;"`.
- A d3dbc compile carries a `CTAB` block. For `BufferShadow_PS` it lists
  `DefSampler`, `EgColor`, `LightDir`, `SpcColor`, `ToonColor`, `parthf`, and
  `transp`.

## What this does not show

- Image parity with MME on D3D9.
- Parameter reflection for the 36 entries whose d3dbc compile fails.
- Effect state, such as render states and sampler states, which the Rust
  effect parser must handle.

Paths in the scripts point at `/tmp/proto-mme`. They are throwaway prototype
scripts, kept as the record of what ran.
