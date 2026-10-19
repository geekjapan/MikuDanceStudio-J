# Fixed-matrix normal dot and normalization precision

The [lighting rounding probes](RHI_LIGHTING_ROUNDING.md) matched the native
normal-matrix coefficients but retained mixed-normal differences. Holding that
matrix fixed now isolates the next boundary: explicit X/Y/Z fused accumulation
matches native transformed normals. With those raw float bytes fixed, the
native and DX11 hardware reciprocal-square-root and normalization multiply
agree. Higher mathematical precision is not an equivalent replacement for
the measured hardware `rsqrt`. Production rendering remains unchanged.

## Inputs and measurement boundaries

`tests/normal_precision_fixture.hpp` runs on NVIDIA TITAN Xp with DX9 HAL hardware
vertex processing and DX11 Hardware, single-sample 64x64 RGBA32F output. It
re-observes all nine native normal-matrix coefficients with signed-axis lights
before collecting the new data. The coefficients must equal the preceding
rounded world/view combination and double inverse-transpose result.

Fifteen normals consist of the three real triangle-197 normals, the six fixed
independent normals from the preceding experiment, and six new fixed normals.
Cases 0-5 are calibration; cases 6-14 are holdout. The added inputs include a
short vector and different lengths/signs. No GPU residual chooses their values.
All inputs are nonzero; zero-length/denormal/extreme-range behavior is outside
this experiment. The experiment holds one verified world/view normal matrix,
and does not establish matrix preparation for other transforms.

Native fixed-function signed-axis responses observe the raw and normalized
normal components, while a white directional-light/material control observes
facing. Constant-normal triangles have constant W and no clipping. Every
covered float pixel must have the same value, and every native draw repeats
three times on the same device. These are controlled raster observations,
**not access to private native fixed-function vertex registers**.

Separate native programmable shaders expose raw normal, squared length,
reciprocal square root, normalized normal and facing through `TEXCOORD0` and a
passthrough pixel shader. The TEXCOORD route preserves signed float results.
Saved shader disassembly verifies the intended instructions:

| Native stage | `dp3` | `rsq` | `nrm` |
|---|---:|---:|---:|
| Raw transformed normal | 3 | 0 | 0 |
| Squared length | 4 | 0 | 0 |
| Reciprocal square root | 4 | 1 | 0 |
| Normalized normal | 4 | 1 | 0 |
| Facing | 4 | 0 | 1 |

The compiler folds the facing-only normalization into legacy `nrm`. The
separate normalized-output shader retains `dp3 / rsq / mul`, so the intermediate
measurements independently check that boundary. Native programmable and fixed
function agree in **45/45 raw components, 45/45 normalized components and 15/15
facing observations**. Shader instructions are observed, rather than inferred
solely from the HLSL expression.

DX11 stream output captures seven expressions across six fixed policies: raw
normal, normalized normal, squared length, reciprocal square root, toward-light
vector, facing and unclamped material color. Each shader executes twice, with
bit-exact output checks. Independent normals are batched in a point-list SO
draw; raster interpolation does not affect DX11 observations. Baseline raw,
normalized and facing outputs for the preceding nine cases must equal the
saved earlier observations. The reusable native renderer must also reproduce
the earlier fixed-function axis/facing responses.

## Fixed policies and results

All policies consume the same verified matrix. Policies 1-5 change only the
normal transform/normalization expressions in the test-local shader source.

| Policy | Normal transform | Normalization |
|---|---|---|
| 0 | Original HLSL matrix `mul` | Original `normalize` |
| 1 | Sequential fused X/Y/Z dot | Original `normalize` |
| 2 | Sequential fused X/Y/Z dot | Builtin squared-length dot, `rsqrt`, float multiply |
| 3 | Sequential fused X/Y/Z dot | Fused squared-length dot, `rsqrt`, float multiply |
| 4 | Sequential fused X/Y/Z dot | Fused squared length, one double Newton refinement of `rsqrt`, float multiply |
| 5 | Sequential fused X/Y/Z dot | Fused squared length, float `1/sqrt`, float multiply |

Sequential fused dot means a rounded X product followed by Y and Z fused-like
product/add steps, rounding to float after each. The test shader implements
each step with double product/add then float conversion. Actual GPU raw values
are checked against CPU `std::fma`/the fixed CPU definition: **225/225 values**
over five candidates and fifteen normals. This tested double construction is
not asserted to implement correctly rounded float FMA for every possible input.

Results are identical in both architecture runs:

| Policy | Raw exact /45 | Normalized exact /45 | Squared length exact /15 | Reciprocal exact /15 | Facing exact /15 | Holdout normalized exact /27 |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 41 | 38 | 12 | 12 | 13 | 25 |
| 1 | 45 | 45 | 15 | 15 | 15 | 27 |
| 2 | 45 | 45 | 15 | 15 | 15 | 27 |
| 3 | 45 | 45 | 15 | 15 | 15 | 27 |
| 4 | 45 | 37 | 15 | 12 | 13 | 19 |
| 5 | 45 | 37 | 15 | 12 | 13 | 21 |

The native squared-length dot matches the fused CPU rule in 15/15 observations;
separate float products/additions match 14/15 and a double sum converted once
matches 13/15. Both nonmatching hypotheses include a holdout difference.

Policy 1 is sufficient for this matrix and these normals: once the transform
dot rounds like native, the existing hardware normalization matches. Explicit
length and multiply stages establish why; their success is not evidence that
all other drivers evaluate builtin `dot` and `normalize` identically.

## Shared raw input and reciprocal precision

A second control bypasses the normal transform using the exact raw float bytes
observed in the native programmable path. Both backends consume an identity
normal matrix. Raw components, squared length, hardware reciprocal and final
normalized components match in **45/45 channel observations per stage**.
Native fixed-function normalization with identity world/view independently
matches all 45 normalized components. The complete transformed and bypassed
normalization paths also match. No CPU prediction substitutes for GPU output.

Policy 4 refines the hardware reciprocal in double using:

```text
x         = double(rsqrt(lengthSquared))
error     = 1 - double(lengthSquared) * x * x
refined   = float(x + 0.5 * x * error)
```

Its actual GPU output matches the rounded mathematical `1/sqrt` value on all
15 tested lengths. However, native hardware reciprocal differs by one float
ULP in three holdout cases (7, 8 and 14):

| Case | Native reciprocal bits | Rounded mathematical bits |
|---|---:|---:|
| 7 | 1093214225 | 1093214224 |
| 8 | 1091783355 | 1091783356 |
| 14 | 1089839981 | 1089839982 |

Those differences change normalized components. Retaining the observed native
hardware reciprocal preserves compatibility on this device; refinement gives
a different target. `sqrt(double)` is not used as an assumed double-precision
GPU intrinsic. Policy 5 separately tests the actual float `1/sqrt` path, whose
disassembly is retained along with the other policies.

The independently observed light vector retains a separate caveat: its native
signed-axis responses and the explicitly captured shader vector differ in two
components by one ULP, depending on the observation expression. The current
15 facing observations still match under policies 1-3. The report retains the
vector difference and does not claim a universally bit-exact directional-light
contract. This task resolves the held-matrix normal dependency, not every
possible light-vector/compiler-context combination.

## Evidence, regression and next boundary

```powershell
cmake --build build-x86/build --config Release --target rhi_d3d9_replay_conversion_test
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --normal-precision exports/rhi-real-dx11-reduction-normals-x86 exports/normal-precision/x86
python tools/analyze_normal_precision.py exports/rhi-real-dx11-reduction-normals-x86 exports/normal-precision/x86 --previous exports/lighting-rounding/x86
# Repeat with the x64 build and x64 evidence paths.
```

`tools/analyze_normal_precision.py` verifies input membership, matrix continuity,
preceding native/SO observations, shader instructions, actual GPU dot arithmetic,
shared raw inputs and every float bit. Nonmatching original and alternative
policies remain in the report. The successful candidate report does not mark
the scene renderer accepted or activate an application path.

Private fixtures and measurements remain ignored under
`exports/normal-precision/{x64,x86}/`: `inputs.csv`, `matrix.csv`, `fixed.csv`,
`native_explicit.csv`, `gpu.csv`, `shared_raw.csv`, `toward.csv`, shader listings,
manifest and analysis JSON. Logs are `exports/normal-precision-{x64,x86}.log`,
`normal-precision-analysis-{x64,x86}.log`, and
`normal-precision-focused-{x64,x86}.log`.

The asset-free `rhi_normal_precision_hardware` CTest uses six generated normals
and an explicit test matrix. It checks fused raw dots and squared lengths
against CPU definitions, native normalized outputs, and 54 multiply observations
over three repeats. The matrix is numeric test input, not a private model asset.

The final focused CTest run passes **11/11 tests on x64 and 11/11 on x86**,
including the new hardware normal probe, lighting-order, explicit-Z, shared
color/depth, viewport, replay-conversion Hardware/WARP and model-replay tests.
The full private probe and analyzer also complete successfully on both builds.
Seven CSV files, the manifest and eleven shader listings are byte-identical
across architectures: all **19 artifacts** have matching SHA-256 hashes in
`exports/normal-precision-architecture.json`. This comparison covers the selected
input measurements; it does not assert that the complete private mesh archives
are identical.

Next, combine the validated diagnostic normal and material arithmetic and
test independently generated world/view transforms before retesting a broader
PMM capture. Device/epoch/resource contracts remain untouched, and a full-scene
or production migration requires its own image acceptance.

The [independent world/view transform checks](RHI_NORMAL_TRANSFORMS.md) now
validate twelve generated pairs, including six holdouts. The combined normal
and material diagnostic also preserves all fourteen real PMM image controls
in each architecture. Full scene and production acceptance remain separate.
