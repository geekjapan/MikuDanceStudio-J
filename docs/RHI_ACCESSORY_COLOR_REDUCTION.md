# Accessory vertex-lighting color reduction

The [explicit Z diagnostic](RHI_DX11_EXPLICIT_Z.md) left one RGBA8 pixel at
`(430,234)` in the smaller captured viewport. Isolating triangle 197 now places
that residual upstream of interpolation: supplying the same colors to DX9 and
DX11 gives identical RGBA32F and RGBA8 images. Supplying native constant-normal
lighting measurements also reproduces the entire original DX9 triangle image
in both formats. This is a diagnostic substitution; production still uses DX9.

## Measurement and controls

The archived untextured accessory has position/normal/UV vertices, directional
lighting, material specular RGB zero and diffuse alpha one. Triangle 197 uses
indices `9324,9326,9327`; its top vertex is clipped by the viewport. Diagnostic
policy 3 fixes combined X/Y, fused W and fused Z from the preceding experiment.
Visibility/history controls are removed: depth, stencil, blending and alpha test
are disabled and culling is disabled. Geometry, world/view/projection matrices,
normals, material and lights otherwise retain their archived values.

`tests/accessory_color_fixture.hpp` performs these checks on NVIDIA TITAN Xp,
DX9 HAL hardware vertex processing and DX11 Hardware, single sampling:

1. Stream output captures actual DX11 clip positions and diffuse vertex colors
   using the adapter's converted lighting constants and diagnostic vertex shader.
2. Independent DX11 raster output must match the optional adapter's RGBA8 image.
   Its pixel shader returns untextured `COLOR0`; the input signature retains the
   model shader's register ordering. Both RGBA8 and RGBA32F targets are measured.
3. DX9 and DX11 programmable passthrough consume the same three float4 clip
   positions and float4 colors. DX11 center compensation must preserve its
   original image and high-precision output, including clipping.
4. A generated triangle holds each source normal constant in turn. Original
   world/view transforms, material and directional lighting remain; an
   orthographic projection gives constant W and avoids clipping. Directional
   diffuse color is position-independent, and zero material specular removes
   viewer dependence. Every covered RGBA32F pixel in each patch must be identical.
5. Those measured colors are fed into both passthroughs with the original clip
   positions. Both complete images must match original native lighting in both
   formats. Native and DX11 original renders and shared-color renders repeat
   three times, comparing every pixel.

RGBA32F values are raster observations, **not captures of native DX9 vertex
registers**. Constant-normal patches and the full-image substitution check
establish the color dependency. The tests have not yet identified which normal,
light-factor or material-color arithmetic operation introduces the difference.

## Observed results

| Original input and viewport | Covered pixels | RGBA8 different pixels | RGBA32F different pixels |
|---|---:|---:|---:|
| x64 archive, `(565,25,1032,774)` | 3216 | 0 | 2798 |
| x86 archive, `(274,25,670,503)` | 1386 | 1 | 1386 |
| x64 executable, identical x86 archive and viewport | 1386 | 1 | 1386 |

For each input, original DX11 colors yield zero differences between APIs in
both formats. Native measured colors yield zero differences against the
original native image, across both APIs and formats. All three constant-normal
patches are spatially constant. Three repeat captures are exact.

Only source vertex 9326 has different constant-normal color results:

| Channel | Native measured float bits | DX11 SO float bits | DX11 minus native ULP |
|---|---:|---:|---:|
| R | 1056593525 | 1056593524 | -1 |
| G | 1057965704 | 1057965705 | +1 |
| B | 1062289233 | 1062289234 | +1 |

At `(430,234)`, native blue before RGBA8 output is
`0.22167965769767761`, while DX11 blue is `0.22167970240116119` (three float ULP).
The measured bytes are respectively 56 and 57. Both APIs reproduce either
outcome when given the corresponding common colors. Thus final conversion
exposes an earlier color difference; these controls do not justify changing
the quantizer or introducing a fitted color offset.

Thirteen CSV/image artifacts from x64 and x86 executions using **identical x86
input and viewport** match byte for byte. The existing architecture-specific
archives have different vertex-buffer hashes and different viewports; they are
not themselves evidence for an architecture-only color defect.

`tools/analyze_accessory_color.py` checks archive geometry versions, 253 saved
state entries, matrices, selected indices, preceding policy-3 clip captures,
CSV float bits against saved full images and the original application residual.
Material/light values come from the archived snapshot; the old application log
does not independently record their full numeric values. Measurement returns
zero when all harness controls pass. Analysis retains original RGBA8 acceptance:
x64 returns zero, and the smaller viewport returns **32** for its remaining
pixel. No application activation is implied by successful control substitution.

## Reproduce

```powershell
cmake --build build-x86/build --config Release --target rhi_d3d9_replay_conversion_test
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-color exports/rhi-real-dx11-reduction-normals-x86 exports/shadow-prefix-dx11-x86 exports/accessory-color/x86
python tools/analyze_accessory_color.py exports/rhi-real-dx11-reduction-normals-x86 exports/shadow-prefix-dx11-x86 exports/accessory-color/x86
# Repeat with the x64 executable and x64 input directories.
# For the architecture control, run the x64 executable with both x86 inputs.
```

Private fixtures, images, CSV and JSON remain ignored under
`exports/accessory-color/`. Logs are `exports/accessory-color-{x64,x86}.log`,
`accessory-color-analysis-{x64,x86}.log`, `accessory-color-x64-x86-input.log`,
`accessory-color-analysis-x64-x86-input.log`, `accessory-color-architecture.log`,
and `accessory-color-focused-{x64,x86}.log`.

The asset-free `rhi_shared_color_hardware` CTest generates constant, gradient
and clipped-gradient triangles. It checks shared input across two output
formats and three repeats: 18 exact comparisons per architecture. Nine focused
CTest checks pass per architecture, including existing replay, viewport and
explicit-Z checks. These checks validate the harness and core contracts;
the original smaller-viewport material still fails zero-difference acceptance.

Next, observe the normalized normal, light direction, diffuse factor and each
material-color term separately. Fixed arithmetic candidates should be checked
against independent generated normals/materials before retesting this triangle.
Measured vertex colors remain evidence, rather than a production lighting input.

The subsequent [lighting rounding reduction](RHI_LIGHTING_ROUNDING.md) performs
those measurements and identifies material multiplication/accumulation order
for the affected vertex, while retaining independent normal/facing failures.
