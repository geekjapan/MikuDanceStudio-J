# Explicit DX11 Z arithmetic validation

The [reduced overlap test](RHI_W_OVERLAP_DEPTH_REDUCTION.md) identified a
remaining Z-transform dependency after the fixed W candidate. Explicit DX11
Z arithmetic now runs in the diagnostic adapter and is checked through actual
GPU stream output. Fused Z matches all independent synthetic depth observations
and all 21 fixed real-PMM coordinates. The archived x64 accessory batch becomes
pixel-exact; x86 retains its previously isolated one-channel color difference.
**The application and production shaders still use their original paths.**

The [accessory color reduction](RHI_ACCESSORY_COLOR_REDUCTION.md) now isolates
the remaining smaller-viewport pixel to vertex-lighting colors. Shared colors
produce identical RGBA32F/RGBA8 images across APIs; native constant-normal colors
reproduce the original native triangle. The original color formula remains
unaccepted for that viewport, and no renderer is activated.

## Fixed policies and implementation

Policies 1 and 2 retain their preceding definitions. Three additional policies
hold policy 2's combined-matrix X/Y and fused W fixed, varying only Z:

| Policy | Diagnostic Z arithmetic |
|---|---|
| 2, baseline | Existing HLSL combined-matrix `mul` |
| 3 | Four sequential fused-like product/add steps, each rounded to float |
| 4 | Double products and left-to-right double accumulation, one float conversion |
| 5 | Separate float products and left-to-right float additions with `precise` |

CPU combined coefficients remain sequential float `(world * view) * projection`.
Original lighting, normals, material and texture-coordinate transforms are
unchanged. The existing diagnostic factory is extended to policies 3–5; it
exists only in the test executable, and requires double shader support.
There is no new public RHI policy or application activation switch.

Policy 3 reuses the tested double product/add followed by float conversion at
each step. Actual shader Z is compared against CPU `std::fma`. Double intermediates
are not claimed to implement correctly rounded float FMA for every possible
input. Policies 4 and 5 are also checked against their fixed CPU definitions;
the report retains any GPU/CPU mismatches, and such mismatches fail the diagnostic.

## Independent four-term Z geometry

`tools/generate_z_geometry.py` uses seed 20261005, distinct from the preceding
W geometry. Twelve triangles have nonzero object X/Y/Z, object W=1, and four
nonzero clip-Z coefficients. The generator selects CPU signature discrimination
and visible depths only; no GPU residual chooses or adjusts an input. Six cases
are assigned to calibration and six to holdout before GPU measurement.

Clip W is exactly 6 and constant, while clip X/Y are simple 6-scaled coordinates.
Thus Z arithmetic varies independently of W arithmetic. This is a custom
homogeneous transform, not a conventional PMM camera. Coordinates (36,46),
(20,42), (28,44) are fixed. Measured matrices and vertices must match the generated
binary fixture and JSON manifest byte for byte.

DX9 HAL hardware vertex processing and DX11 Hardware run on NVIDIA TITAN Xp,
with 64x64 single-sample RGBA8 and D24S8. Per architecture:

| Check | Result |
|---|---:|
| Actual GPU Z matches its CPU definition, each of policies 3/4/5 | 36/36 vertices |
| XY/W held bit-exact relative to policy 2, each policy | 36/36 vertices |
| Policy 2 depth equality interval matches native | 25/36 points |
| Policy 3 fused Z matches native | 36/36 points (18/18 calibration, 18/18 holdout) |
| Policy 4 double Z matches native | 34/36 points (16/18 calibration, 18/18 holdout) |
| Policy 5 separate float Z matches native | 25/36 points |
| Native programmable Z-only `dp4` matches original fixed function | 36/36 points |
| Shared fused-Z clip inputs agree across backends and with actual DX11 | 36/36 points |

GPU Z differs from baseline at 14/10/0 vertices for policies 3/4/5. The complete
experiment records 216 comparison pairs per architecture, including controls;
35 pairs differ, so it returns **32**, despite policy 3's local success.
Comparing the two architectures gives zero differences in 864 measured interval
endpoint values and in all 96 raw/final clip buffers.

Some independent depths are below 0.5, where float32 spacing is finer than the
D24 code spacing. Multiple constant reference floats can map to one equality
code. An initial unique-equality assertion correctly failed on that assumption.
The final probe records the first and last accepted `Equal` reference, verifies
the adjacent outside values fail, and repeats both boundaries three times.
Eighteen comparison rows per architecture contain more than one equality
reference. Agreement requires both interval endpoints, not just the first.
These bits are reference-plane input floats, **not raw D24 attachment bits**.

## Fixed real PMM coordinates and GPU bits

The same archived 232-triangle accessory geometry, matrices, original target
viewport, primary coordinates and additional coverage-selected points from the
preceding reduction are reused. Candidate policy 2's captured raw clip bytes
must equal the preceding experiment. Geometry hashes and matrix bytes are
checked against the saved native application log.

Per architecture and new policy, all **13,894 source-buffer Z values** match
the declared CPU arithmetic and all XY/W components remain bit-exact relative
to policy 2. These include vertices outside the selected triangle indices.
Policies 3/4/5 change Z in 1,868/2,917/0 entries respectively.

| Viewport | Fixed coordinates/triangles | Policy 2 matches | Fused Z matches | Double Z matches | Separate float Z matches |
|---|---:|---:|---:|---:|---:|
| x64 capture, (565,25), 1032x774 | 6 | 5/6 | 6/6 | 6/6 | 5/6 |
| x86 capture, (274,25), 670x503 | 15 | 13/15 | 15/15 | 15/15 | 13/15 |

At x64 (1220,505), triangle 135 returns to native reference 1065209263, equal
to triangle 227, restoring the original `LessEqual` surface choice. At x86
(427,338) and (381,340), triangle 231 returns to native 1065209328 and
1065209385, removing the policy-2 +1 step. Shared policy-3 clip inputs and actual
DX11 adapter observations agree on all 21 coordinates. The native Z-only `dp4`
controls also match all 21 original native observations.

The complete reduced diagnostics still return **32**: 3/36 pairs differ for
x64 and 6/90 for x86 because the original policy-2, separate-float and instruction
comparison controls remain in the report. No tolerance suppresses them.

These captured viewports differ in size and coordinates. The result does not
isolate process bitness as a cause or justify choosing a shader by architecture.

## Full archived accessory image comparison

The two original accessory draws, including their original shading and order,
are rendered anew for each policy. Native original/repeat viewport images must
equal the previously captured application image exactly. They do, as do the
candidate repeated images. Each policy also captures all fourteen existing
counterfactual controls.

| Path | x64 differing pixels | x86 differing pixels |
|---|---:|---:|
| Original production DX11 | 102 (7 with channel delta > 1) | 9 (8 with delta > 1) |
| Policy 2, combined XYZ plus fused W | 1, maximum delta 49 | 3, maximum delta 94 |
| Policy 3, explicit fused Z | **0** | **1**, maximum delta 1 |
| Policy 4, double Z | **0** | **1**, maximum delta 1 |
| Policy 5, separate float Z | 1, maximum delta 49 | 3, maximum delta 94 |

All fourteen x64 policy-3 and policy-4 control images match their respective
native images exactly. Their full batch diagnostics return **0**. x86 policy-3
and policy-4 still return **32**. The remaining pixel is (430,234), previously
reduced to triangle 197 alone: native RGBA (26,30,56,255), DX11 (26,30,57,255).
It survives disabled depth, while the measured depth intervals match. No new
large depth-related discrepancy is observed in these full batch images.

Both full source-buffer captures per policy comprise 27,788 vertex checks,
with duplicated buffer contents; they are not 27,788 distinct drawn vertices.
The analyzer independently checks geometry versions, archived state/matrix
provenance, actual GPU arithmetic, fixed XY/W, native original images and repeats.

## Meaning and next step

This supports the fixed fused-like Z/W transform hypothesis on these bounded
inputs and this driver. Fused Z survives independent geometry where double
accumulation fails two observations. It does not prove the exact native
fixed-function vertex bits or hardware instruction sequence, and does not
accept general scene history, another GPU, or MSAA.

Keep all new policies diagnostic-only. The next focused image check can isolate
triangle 197's blue-channel residual at (430,234), comparing vertex lighting
outputs and color interpolation/quantization while retaining the validated
depth inputs. A pixel-specific correction, tolerance or shader selected by
executable architecture would not establish compatibility. The original DX9
application path remains active.

## Reproduce and evidence

```powershell
python tools/generate_z_geometry.py exports/z-explicit/fixtures.bin
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --z-explicit-geometry exports/z-explicit/fixtures.bin exports/z-explicit/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --z-explicit-geometry exports/z-explicit/fixtures.bin exports/z-explicit/x86
python tools/analyze_z_explicit.py exports/z-explicit/x64 --fixtures exports/z-explicit/fixtures.bin --peer exports/z-explicit/x86

# Requires previously captured private PMM evidence; repeat for x86.
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --z-explicit-pmm exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 exports/z-explicit-pmm/x64
python tools/analyze_z_explicit.py exports/z-explicit-pmm/x64 --reference exports/shadow-prefix-dx11-x64 --archive exports/rhi-real-dx11-reduction-normals-x64
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-w-gpu exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 3
python tools/analyze_w_gpu_batch.py exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 3
```

Generated fixtures, original-source bytes/matrices, GPU raw/final clip captures,
threshold/verification CSV and analysis JSON remain ignored under
`exports/z-explicit/` and `exports/z-explicit-pmm/`. Full image evidence is under
each PMM reference's `accessory-w-gpu-{3,4,5}/` directory. Logs use
`exports/z-explicit-*`; private assets and images are not added to source control.

The new asset-free `rhi_explicit_z_shader_hardware` CTest uses a fixed independent
fixture with distinct fused/separate Z bits. It checks all three policies over
three fresh stream-output repetitions and rejects changes to XY/W. It supplements
the existing replay, viewport and shared-clip tests; a passing CTest does not
override the remaining x86 native image failure.

Both builds and sixteen focused CTest checks pass (eight per architecture),
recorded in `exports/z-explicit-final-build-{x64,x86}.log` and
`exports/z-explicit-focused-{x64,x86}.log`. The final synthetic/reduced probes
also repeat both equality-interval endpoints. No broad renderer activation or
scene/MSAA acceptance is inferred from these results.
