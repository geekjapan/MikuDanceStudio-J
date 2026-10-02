# Toon/Sphere pixel cascade and offscreen acceptance

The first shader pixel cascade is implemented, but the DX11 model renderer is
not enabled. The initial WARP comparison passes point sampling but remains
blocked under linear sampling. Follow-up comparison on the same hardware GPU
passes both filters for the synthetic fixtures below. These results do not replace
real PMM batch acceptance.

## Contract

`src/render/shaders/model_material_pixel.hlsl` takes the already lit diffuse
color and three explicit texture coordinates. Resources are bound by logical
stage, using `MaterialTextureLayout`: Toon, optional Base, optional Sphere.
Sphere moves into stage 1 when Base is absent. RGB uses component-wise multiply
or saturated add; Alpha always multiplies, including additive Sphere. No sRGB
conversion is applied in this probe. The shader expects supported, contiguous
stages and Modulate/Add operations; it is not a general DX9 combiner emulator.

Alpha testing converts the resulting Alpha to a byte with
`floor(saturate(alpha) * 255 + 0.5)` before comparing the byte reference.
Direct comparison of floating Alpha against `reference / 255` originally
produced different discard masks under linear sampling. The explicit byte
comparison removes those large differences in this fixture, without hiding
the remaining sampling/quantization differences.

`EvaluateMaterialTextureCascade` supplies a platform-independent mathematical
reference; `MaterialAlphaTest` defines the same byte comparison. The reference
rejects unsupported combiners and invalid samples. It does not claim to emulate
DX9 intermediate fixed-function precision or native texture filtering.

Lighting formulas, normal-derived Toon/Sphere coordinates, UV1, fog, specular
addition, stencil, shadows and MME are outside this pixel probe. The test supplies
UVs for all stages and white diffuse; the earlier matrix/normal transport test
remains separate. Real model integration must combine and validate both stages.

## Probe and current results

`rhi_d3d11_material_pixel_test` renders the same 32x32 quad through DX9 HAL
fixed-function stages and a DX11 WARP pixel shader. Targets are non-MSAA RGBA8;
DX9 BGRA readback is swizzled before comparison. DX9 pretransformed vertices
include the half-pixel adjustment. Depth, lighting and fog are disabled.

The authored 2x2 textures exercise Toon alone, Base, Sphere multiply/add without
Base, and Base plus Sphere multiply/add. Each layout runs unblended, Alpha test
`GreaterEqual 128`, and source-Alpha blending over transparent black. Blend
factors apply to both RGB and Alpha, matching DX9 without separate Alpha blend.
Fractional Alpha comes from Toon; the other textures have opaque Alpha. RGB
texels use 0/255 endpoints; arbitrary fractional RGB and multiple translucent
texture stages need additional fixtures before broader acceptance.

On both x64 and x86:

| Sampling / variant | Layouts | Result | Maximum channel error |
| --- | ---: | --- | ---: |
| Point / unblended | 6 | Exact | 0 |
| Point / Alpha test | 6 | Exact | 0 |
| Point / blend | 6 | Exact | 0 |
| Linear / unblended | 6 | Blocked | 1 |
| Linear / Alpha test | 6 | Blocked | 1 |
| Linear / blend | 6 | Blocked | 2 |

Every point-filter pixel also matches the portable cascade reference. This
prevents identical blank or incorrect targets from passing by mutual agreement.
The current linear reports and target bytes are identical between architectures.
DX9 HAL and DX11 WARP are different execution engines; the measured precision
boundary still needs isolation between sampling, fixed-function cascade and
target/blend conversion. A uniform rounding bias cannot explain all observed
differences, so no output bias or tolerance has been added.

Default CTest runs the 18 exact point cases. `--linear` explicitly runs all 36
cases and returns **2** if any pixel differs. Device unavailability returns 77
(CTest skip), other errors return 1. Local acceptance used actual devices and
had no skips. Evidence is under `exports/rhi-material-pixel-{x64,x86}/final`,
with a report and both raw RGBA targets per case.

```powershell
cmake --build build-x64/build --config Release --target rhi_d3d11_material_pixel_test
ctest --test-dir build-x64/build -C Release -R '^rhi_d3d11_material_pixel$' --output-on-failure
build-x64/build/Release/rhi_d3d11_material_pixel_test.exe --linear exports/rhi-material-pixel-x64/final
python tools/analyze_rhi_material_pixels.py exports/rhi-material-pixel-x64/final --output exports/rhi-material-pixel-x64/summary.json
```

The last two commands currently return 2 as a strict failed comparison. The
analyzer independently recalculates counts/maxima from target bytes and records
the first differing pixel/channel. Repeat with the x86 build for architecture
comparison. Do not infer full GPU acceptance from portable resource CI.

The standalone five-test resource suite passes locally and on the user's Linux
server. [CI run 36795600447](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36795600447)
also passes all five tests on Windows, Linux and macOS, with no resource skips.
It includes the portable cascade/Alpha reference assertions, not native GPU
image comparison. The isolated source commit is
`ef840d49b8e8b4cb9b25865b13a1e32fe9a2f73a`; run metadata and logs are retained in
`out/resource-ci/pixel-cascade-remote-run.json` and
`exports/rhi-material-pixel-resource-ci.log`. Focused native CTest also passes
the matrix transport, pixel probe and material resources tests on x64/x86.

## Follow-up: isolate sampling and execution engine

The diagnostic now accepts `--precision constant`, `--precision translucent`
and `--precision gradient`. Constant RGB is `(97,143,211)` at every texel;
Alpha is respectively 255 or 128. Gradient texels have intermediate RGB values
and opaque Alpha. All three resource slots use the specified fixture, covering
multiple fractional RGB/Alpha stages, not just the previous endpoint colors.
Both filters run all six layouts and three output variants (36 cases per fixture).
These diagnostic cases compare backend bytes strictly; the original point
fixture retains its portable per-pixel oracle. The diagnostic does not require
the mathematical reference to reproduce native intermediate precision.

`--hardware` switches DX11 from WARP to the hardware device. The test records
DX9/DX11 adapter vendor/device IDs and rejects hardware tests on mismatched GPU
types. Local acceptance uses NVIDIA TITAN Xp, IDs `10de:1b02` for both APIs.
This validates that GPU, not other vendors or all driver revisions.

| Fixture (36 cases each) | DX9 HAL vs DX11 WARP | DX9 HAL vs DX11 hardware |
| --- | --- | --- |
| Original endpoint fixture | 18 exact / 18 blocked | 36 exact |
| Constant intermediate RGB, opaque Alpha | 36 exact | 36 exact |
| Constant intermediate RGB, Alpha 128 at each stage | 36 exact | 36 exact |
| Intermediate RGB gradient, opaque Alpha | 18 exact / 18 blocked (max 1) | 36 exact |

Results are identical on x64/x86. Reports and target bytes match between
architectures in every diagnostic directory. Hardware acceptance totals
144 exact cases per architecture. The independently verified summary is
`exports/rhi-material-precision-summary.json`; targets/reports are under
`exports/rhi-material-precision-{x64,x86}/{warp,hardware}/{pattern}`. Baseline
hardware evidence is stored under the hardware `baseline` directory.

The gradient fails with just Toon and no blending in WARP, while constant
textures pass with multiple stages and blending. Thus multiple-stage cascade
or blend is not necessary to trigger the difference. The same gradient passes
on DX11 hardware. This narrows the observed failure to texture filtering or
sample/output precision between execution engines; it does not prove WARP's
internal implementation or a portable rule to emulate every DX9 device.
No sampler/rounding workaround or shader change was applied for these results.

```powershell
build-x64/build/Release/rhi_d3d11_material_pixel_test.exe --precision gradient exports/rhi-material-precision-x64/warp/gradient
build-x64/build/Release/rhi_d3d11_material_pixel_test.exe --hardware --precision gradient exports/rhi-material-precision-x64/hardware/gradient
build-x64/build/Release/rhi_d3d11_material_pixel_test.exe --hardware --linear exports/rhi-material-precision-x64/hardware/baseline
ctest --test-dir build-x64/build -C Release -R '^rhi_d3d11_material_pixel' --output-on-failure
```

The first command returns 2; the next two return 0 on the tested GPU. Four
native CTests pass on each architecture, without skips: original WARP point
fixture, same-GPU hardware point/linear baseline, WARP constant fixture and WARP
translucent fixture. The known failing gradient measurement remains explicit,
not an accepted test with widened tolerance. Portable core files are unchanged
in this follow-up; the earlier three-platform CI evidence remains applicable
to that core, not to these added native tests.

## Next gate

The first real PMM independent batch now passes combined vertex/pixel shader
comparison with explicit diffuse-byte and sRGB MSAA resolve settings; see
[real batch acceptance](RHI_REAL_DX11_BATCH.md). It uses isolated color/depth
targets, so a larger batch and preceding scene history remain the next gate.
The application renderer stays on the existing DX9 path. WARP precision
differences remain a separate compatibility limit.
