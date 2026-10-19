# Directional lighting rounding reduction

The [accessory color reduction](RHI_ACCESSORY_COLOR_REDUCTION.md) isolated a
one-byte blue residual at `(430,234)` to vertex-lighting color. The next probes
separate transformed normals, normalization, diffuse facing and material color.
For the affected vertex, normalized normal and facing agree. Its color residual
comes from material multiplication order and fused color accumulation. A
diagnostic candidate follows the measured order; production rendering stays DX9.

## Native observations and shader stages

`tests/lighting_rounding_fixture.hpp` uses constant-normal, constant-W triangles
on NVIDIA TITAN Xp, DX9 HAL hardware vertex processing and DX11 Hardware, with
single-sample RGBA32F output. The original world/view matrices, material and
directional light come from the archived untextured accessory. Visibility and
history operations are disabled. Each native observation repeats twice and
every covered pixel must be constant.

Actual DX11 vertex stream output observes nine variants: original final color,
raw transformed normal, normalized normal, toward-light vector, facing,
ambient product, diffuse material/light product, diffuse contribution, and
unclamped color. Each variant exposes an existing expression; original final
color must match the uninstrumented shader. Bytecode may be cached in the test
process, but each observation creates shader objects, executes a fresh draw and
reads GPU output.

Twenty native material/light controls isolate original color, white diffuse
facing, diffuse-only color, emissive-only color, positive ambient-only color,
color without ambient, color without emissive, six signed-axis responses with
normalization, unnormalized facing, and six unnormalized signed-axis responses.
Signed-axis lights recover components of the transformed normal. Identity-world
axis normals independently observe the normalized light vector with the
original view matrix. These are controlled raster responses, not captures of
DX9's private fixed-function vertex registers.

Three real normals are followed by six fixed generated normals. The first
three generated normals are calibration; the last three are holdout, assigned
before measurement. Per architecture this records 324 shader stage values,
720 native color-channel measurements, and six light-axis responses.

## Color arithmetic and validation

With global ambient zero and one directional light, the measured color rule is:

```text
scaledMaterial = float(diffuseMaterial * facing)
withEmissive   = fused(lightDiffuse * scaledMaterial + emissive)
color          = saturate(fused(materialAmbient * lightAmbient + withEmissive))
```

The original HLSL groups `diffuseMaterial * lightDiffuse` before multiplying by
facing and groups the ambient/diffuse sum before adding the base color. Different
float rounding boundaries remain visible even when the light factor agrees.

Using native-measured facing, the declared rule predicts **189/189** native RGB
observations over nine normals and seven color controls. Using DX11 facing,
the same CPU rule matches **189/189** actual diagnostic GPU RGB results. These
are dependency tests: substituting native-facing measurements does not prove
the complete DX11 normal/lighting pipeline matches.

Six generated material palettes independently vary diffuse, ambient, emissive,
light diffuse and light ambient. Axial normals and lights give exactly 0.75
without normalization and exactly 1 with normalization. This keeps normal
precision out of the material test. The candidate matches **36/36** native RGB
results, with **18/18 calibration and 18/18 holdout**; the production formula
differs in six channels. Actual candidate GPU values also match the fixed CPU
definition. No measured native colors are used as candidate shader inputs.

`tests/d3d11_lighting_candidate_shader.hpp` rounds the initial material/facing
product explicitly. Each subsequent fused-like step uses double product/add
then conversion to float, checked against the fixed CPU definition. As in the
preceding Z diagnostics, this is not a universal correctly-rounded float-FMA
implementation for all possible inputs. The test backend exposes a separate
factory; its geometry retains policy 3's combined X/Y and fused Z/W. Neither
the production factory nor the application can enable this candidate.

## Remaining normal/facing boundary

Native and DX11 normalized light-axis responses are exact in **6/6** controls.
Among 27 normal components, raw transformed responses agree in 14 and normalized
responses agree in 17. The remaining component differences are one float ULP.

For real source vertex **9326**, raw normal X differs by one ULP, but its
normalized components all agree. Actual directional facing is exactly
`0.94280916452407837` in both pipelines. Correcting material color order therefore
addresses the observed pixel without altering this normal computation.

Generated normal cases 4 and 8 retain a one-ULP facing difference. Case 8 is a
holdout. The candidate still differs in 25 of the 189 color-control channels
when using its own facing; the original differs in 51. All 720 diagnostic
channels include axis/unnormalized probes as well: original/candidate differences
are 171/145. These failures remain recorded and prevent treating the color
candidate as a general replacement for native lighting.

`--lighting-matrix-axes` uses three object-axis normals and six signed-axis
lights, with normalization disabled, to observe the nine native normal-matrix
coefficients separately. DX11 GPU coefficients must equal the portable matrix
constants. This supplements the mixed-normal measurements without fitting them.

Five of the nine observed coefficients match the current portable constants.
`BuildShaderNormalMatrix` combines world/view in double, then computes its
inverse transpose in double. A fixed diagnostic instead combines world/view
with sequential float rounding, then passes that already-rounded matrix to the
same double inverse-transpose code. **All nine coefficients now match native**
in both architecture captures, including the tiny `(1,0)` cancellation term.
This identifies an intermediate matrix-rounding boundary for these transforms;
it does not establish the driver's inversion algorithm for arbitrary matrices.

Binding the rounded candidate matrix in DX11 improves mixed-normal agreement
from 14/27 to 23/27 raw components and from 17/27 to 20/27 normalized components.
Facing remains 7/9 exact: holdout case 8 becomes exact, while calibration case 3
develops a one-ULP difference and case 4 retains one. Combining it with the color
candidate gives 23/27 exact final RGB channels. Thus matching matrix coefficients
alone does not resolve the subsequent dot-product/normalization boundary. The
real affected vertex still has exact facing and color under either matrix.
The real batch candidate below **retains the original portable normal matrix**;
the matrix experiment is a separate diagnostic override.

## Real batch and regression checks

`--accessory-lighting-gpu` reuses the two archived draws and the original target
viewport. Geometry, material, lights, textures and render states remain
unchanged. The native original/repeat images must equal the saved application
capture. Fourteen controls compare fresh native images with diagnostic DX11
images, including depth disabled, specular disabled, normalization disabled,
selected triangles, reverse triangle order and strict depth comparison.

| Captured viewport | Original/repeat pixels different | All 14 control images |
|---|---:|---|
| x64 `(565,25,1032,774)` | 0 | exact |
| x86 `(274,25,670,503)` | 0 | exact |

Each run verifies 27,788 GPU clip vertices against the held policy-3 arithmetic
and original geometry/resource versions. Fresh native original images equal
the saved application images. The unchanged x86 policy-3 lighting baseline is
also rerun and still returns **32** for its original `(430,234)` pixel; the new
color arithmetic is the changed diagnostic input.

Private measurement CSV/JSON remain in `exports/lighting-rounding/{x64,x86}/`.
Real batch images and verified clip captures remain in
`exports/shadow-prefix-dx11-{x64,x86}/accessory-lighting-gpu/`.
`tools/analyze_lighting_rounding.py` checks fixed inputs, float bits, holdout
membership and GPU predictions. `tools/analyze_w_gpu_batch.py --lighting`
checks original resource versions, pipeline states, matrices, all captured
geometry-policy vertex bits, native application images, and all 14 images.
Successful isolated diagnostics do not accept a complete scene renderer.

```powershell
cmake --build build-x86/build --config Release --target rhi_d3d9_replay_conversion_test
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --lighting-rounding exports/rhi-real-dx11-reduction-normals-x86 exports/lighting-rounding/x86
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --lighting-matrix-axes exports/rhi-real-dx11-reduction-normals-x86 exports/lighting-rounding/x86
python tools/analyze_lighting_rounding.py exports/rhi-real-dx11-reduction-normals-x86 exports/lighting-rounding/x86
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-lighting-gpu exports/rhi-real-dx11-reduction-normals-x86 exports/shadow-prefix-dx11-x86
python tools/analyze_w_gpu_batch.py exports/rhi-real-dx11-reduction-normals-x86 exports/shadow-prefix-dx11-x86 3 --lighting
# Repeat with the x64 build and x64 input paths.
```

The asset-free `rhi_lighting_order_hardware` CTest checks the declared GPU
rounding boundaries against CPU `std::fma` in 18 comparisons over three repeats.
It also verifies exact native factors 0.75 and 1. Its success validates the
diagnostic arithmetic; it does not suppress the independent facing failures.

Both builds and ten focused CTest checks per architecture pass (20 total).
Seven input/CSV artifacts for selected normals, materials, shader stages,
axis probes and adjusted-matrix results are byte-identical between architectures.
Logs are `exports/lighting-rounding-{x64,x86}.log`,
`lighting-rounding-analysis-{x64,x86}.log`, `lighting-matrix-{x64,x86}.log`,
`lighting-batch-{x64,x86}.log`, `lighting-batch-analysis-{x64,x86}.log`,
`lighting-baseline-x86.log`, and `lighting-focused-{x64,x86}.log`.
`exports/lighting-architecture.json` records the cross-architecture checks.

The remaining work is to hold the observed normal-matrix coefficients fixed
and isolate the GPU normal dot product and normalization rounding, then verify
with independent world/view transforms before considering a general adapter
change. Color and matrix diagnostic observations remain separate from
application activation.

The [fixed-matrix normal precision experiment](RHI_NORMAL_PRECISION.md) now
isolates this boundary. Fused X/Y/Z transform dots with hardware normalization
match all fifteen tested normals, including nine holdouts. Shared raw input
separately verifies the reciprocal and multiply stages; double refinement
departs from native output in three holdouts. Independent transform and full
scene acceptance remain outstanding.
