# Independent world/view transforms and real PMM image checks

The [fixed-matrix normal experiment](RHI_NORMAL_PRECISION.md) now has an
independent transform check. Twelve generated world/view pairs, six normals
per pair and a combined normal/material diagnostic match the native DX9
observations on NVIDIA TITAN Xp in both x64 and x86 builds. The combined
candidate also preserves zero pixel differences in the two archived real PMM
accessory draws and all fourteen single-sample image controls per architecture.
The application continues to render with its existing DX9 path.

## Inputs and observation boundaries

`tests/normal_transform_fixture.hpp` fixes twelve transform pairs before
measurement. They include translated uniform/nonuniform scales, an asymmetric
dyadic shear, decimal coefficients, world rotations, signed/permuted views,
near-unit diagonal views and general X/Y view rotations. Transform IDs 0-5
are calibration; IDs 6-11 are holdout. Six previously fixed nonzero normals
include a short vector, mixed signs and different lengths. No GPU residual is
used to choose or adjust an input.

The candidate combines world/view with sequential float rounding, computes
the inverse transpose of that already-rounded matrix in double, transforms
normals with sequential fused X/Y/Z dots and retains hardware `normalize`.
The color calculation uses the independently measured material/facing
product followed by diffuse/emissive and ambient fused additions. The original
portable matrix and dot expression are retained as comparison observations.
The double product/add followed by float conversion is the same tested
construction as the preceding probe, not a claim of correctly rounded float
FMA for every possible input.

The eight diagonal/permutation views allow exactly axial transformed probe
lights. Signed-axis diffuse responses therefore separately observe nine normal
matrix coefficients, transformed normals and normalized normals. For the four
general rotated views, inverse-view axis lights may have small off-axis
rounding. Those responses are compared as **effective normal/light results**;
they are not reported as separately recovered matrix coefficients.

Native fixed-function observations use single-sample 64x64 RGBA32F targets,
constant-normal, constant-W triangles and DX9 HAL hardware vertex processing.
Every covered pixel must have the same result and each observation repeats
three times. A CPU inverse places geometry in a known visible triangle; it
does not prepare the candidate normal matrix or substitute for GPU results.

Native programmable shaders separately expose raw normal, squared length,
reciprocal and normalized normal through signed float texture coordinates.
DX11 hardware stream output observes the corresponding expressions, toward
light, facing and color, with two identical captures. No native measurements
enter DX11 shader constants. These are raster and stream-output observations,
not access to private fixed-function registers.

## Independent results

The following counts hold separately for x64 and x86:

| Boundary | Original expression | Combined candidate |
|---|---:|---:|
| Directly observable matrix coefficients | 70/72 | 72/72 |
| Signed-axis raw normal components | 123/144 | 144/144 |
| Signed-axis normalized normal components | 121/144 | 144/144 |
| Actual directional facing | 60/72 | 72/72 |
| Material RGB after saturation | — | 216/216 |
| Signed-light facing, normalize on/off | — | 864/864 |

Native programmable raw and normalized components also match the candidate
in 216/216 observations each. Squared lengths and hardware reciprocals match
in 72/72 observations each. All 216 actual GPU raw components match the fixed
CPU fused-dot definition. Both calibration and holdout transforms pass every
declared comparison. General-view tests include actual world-space light
directions as well as the signed-light controls.

Signed-axis lighting cannot recover the sign bit of a zero matrix coefficient.
The analyzer explicitly treats signed zero as equivalent at that boundary;
finite nonzero results are compared by float bits. No numerical tolerance or
image-difference allowance is used.

## Real PMM diagnostic adapter

`tests/d3d11_normal_candidate_shader.hpp` shares its fused-dot HLSL with the
fixed-matrix probe. `CreateD3D11NormalCandidateDevice` exists only in the
diagnostic executable's separate adapter copy. It combines:

1. The previously held geometry policy 3: rounded combined X/Y, fused Z/W.
2. The verified material color order.
3. The rounded world/view normal matrix and fused X/Y/Z normal transform.

The normal diagnostic flag and matrix preparation are behind
`MDS_RHI_TEST_W_CANDIDATE`; the production factory exposes no activation path.
Vertex-color shadow inputs retain their existing handling. The existing
material-only diagnostic can still run with the normal flag disabled.

`--accessory-normal-gpu` replays the archived two untextured accessory draws.
Their geometry, resource versions, transforms, materials, light and pipeline
states are held fixed. Fresh native original/repeat images must equal the
saved application capture. The fourteen image controls include original,
repeat, draw 2 alone, depth/specular/normalization disabled, six selected
triangles, reversed triangle order and strict depth comparison. Counterfactual
controls are diagnostics, not acceptance of edited native state.

| Architecture and saved viewport | Original/repeat pixel differences | All 14 controls |
|---|---:|---|
| x64 `(565,25,1032,774)` | 0 | zero differences |
| x86 `(274,25,670,503)` | 0 | zero differences |

The candidate images also equal the preceding material-only candidate in every
control. Thus this particular real batch remains exact; the independent
transform experiment supplies the broader normal validation rather than
claiming a new pixel improvement on an already exact image.

Each architecture verifies 27,788 actual GPU clip vertices against the held
geometry rule. Actual combined-adapter vertex-shader source and constants also
execute through instrumented stream output: clip values remain identical and captured vertex
colors repeat bit-for-bit. Both uploaded normal matrices are checked against
the declared arithmetic; referenced colors must be finite, in range and retain
material alpha. Archive geometry hashes, original state/matrix correspondence,
all control images and the preceding native images are independently checked by
`tools/analyze_w_gpu_batch.py --normals`.

This reuses an existing real PMM application capture and runs fresh native
batch controls; it does not claim a new whole-scene application run or acceptance
of every preceding draw. The experiment is single-sample. MSAA, zero/denormal
normals, extreme or singular transforms, multiple lights and other GPU/driver
families remain separate boundaries.

## Reproduction and evidence

```powershell
cmake --build build-x64/build --config Release --target rhi_d3d9_replay_conversion_test
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --normal-transforms exports/normal-transforms/x64
python tools/analyze_normal_transforms.py exports/normal-transforms/x64
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-normal-gpu exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
python tools/analyze_w_gpu_batch.py exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 3 --normals
# Repeat with x86 build and evidence paths.
```

The asset-free `rhi_normal_transforms_hardware` CTest runs all twelve transforms
and fails on any matrix, normal, reciprocal, facing, color or repeat mismatch.
It needs no private PMM/model fixture. The analysis script retains a coordinate
and float-bit record for every mismatch rather than relaxing comparisons.

Ignored evidence is stored in `exports/normal-transforms/{x64,x86}/` and
`exports/shadow-prefix-dx11-{x64,x86}/accessory-normal-gpu/`. The former contains
matrix inputs, signed-axis responses, programmable/SO values, native shader
listings, manifest and analysis JSON. The latter contains fourteen native and
candidate image pairs, held clip captures, actual shader color captures, normal
matrices and analysis JSON. Logs are `exports/normal-transforms-*.log` and
`exports/normal-batch-*.log`.

The final focused regression passes **12/12 CTests on x64 and 12/12 on x86**,
including the complete asset-free transform test, fixed-matrix normal test,
lighting order, shared color/depth, explicit Z, viewport and replay checks.
Both image analyzers also pass all fourteen controls. Ten independent-probe
artifacts (three CSV files, manifest, five native shader listings and analysis
JSON) are byte-identical across architectures; SHA-256 comparisons are recorded
in `exports/normal-transforms-architecture.json`. The real batch viewports and
complete private geometry archives are separate architecture captures and are
not claimed identical.

Next, use this diagnostic combination in the single-sample frozen scene prefix
and compare every draw, retaining unsupported-operation stops and the separate
MSAA acceptance item. An application backend switch still requires whole-path
image and lifecycle acceptance.

The subsequent [full-prefix diagnostic](RHI_SCENE_PREFIX_DIAGNOSTIC.md) now
captures all 49 selected draws and compares fifty boundaries. The x86 viewport
passes; the larger x64 viewport fails first at accessory draw 4. Same-archive
controls reproduce that failure in both executables and remove it by changing
only the viewport. A separate real ground capture explicitly blocks at its
line-list command. These results prevent treating the independent normal and
two-batch successes above as full scene acceptance.
