# Diagnostic DX11 fused-W candidate

The fixed hypothesis from [independent four-term W geometry](RHI_W_INDEPENDENT_GEOMETRY.md)
now runs in an actual DX11 vertex shader and in a test-only copy of the RHI
adapter. Synthetic depth comparisons pass for the candidate, but real PMM
images still differ. **No production shader or application renderer is switched.**

DX9 HAL hardware vertex processing and DX11 Hardware were measured on NVIDIA
TITAN Xp, on x64 and x86, with single sampling and D24S8. These observations
do not cover other drivers, MSAA, or general scene history.

## Implementation boundary

`tests/d3d11_w_candidate_shader.hpp` inserts a diagnostic b1 constant buffer
and W override into the generated production VS source. CPU code constructs
`(world * view) * projection` with sequential float32 matrix arithmetic. Each
W product and addition is computed in double in the shader, then converted
back to float after each term. Stream output is checked bit for bit against
CPU `std::fma`; passing that check is required before drawing.

This is a bounded candidate implementation, not a general proof that double
product/add is equivalent to correctly rounded float32 FMA for every input.
Double shader support is queried explicitly. Unsupported devices are rejected
rather than silently running a different arithmetic policy.

Two fixed policies are examined:

1. Preserve production staged X/Y/Z, replace W with the candidate.
2. Compute X/Y/Z with the CPU-combined matrix, then use the same W candidate.

Both retain the original world/view inputs for lighting, normals and texture
coordinates, and retain viewport center compensation after the override.
Neither changes native DX9 matrices, geometry, material, lights or states.
Policy 2 is a separate diagnostic; its broader transform change is not inferred
from the preceding W-only experiment.

`tests/rhi_d3d11_w_candidate_backend.cpp` compiles a separate adapter copy only
inside `rhi_d3d9_replay_conversion_test`. Its factory and replay symbols are
distinct from the production factory. The two conditional hooks in the adapter
are absent from ordinary compilation. There is no application activation switch.

## Synthetic GPU validation

The same twelve fixed nonzero-Z geometries and three coordinates are reused,
without fixture regeneration or new fitting. Each architecture records ten
paths, 360 threshold pairs, with fresh repeated threshold checks.

| Check, per architecture | Result |
|---|---:|
| Actual GPU W matches CPU fused bits | 36/36 vertices |
| X/Y/Z before center compensation remain unchanged, policy 1 | 36/36 vertices |
| Candidate final clip matches shared candidate passthrough | 36/36 vertices |
| Candidate DX11 depth threshold matches original native DX9 | 36/36 points |
| Original production DX11 threshold matches native | 25/36 points |
| Cross-architecture threshold differences, all ten paths | 0/720 values |

Calibration and holdout each match 18/18 candidate thresholds. Original native
thresholds are retained unchanged in the candidate path. The full diagnostic
still returns **32**: its other controls contain the same 42 nonmatching
threshold pairs as before. Candidate success does not suppress those failures.
The ruler values are float32 reference-plane inputs, not captured native W
bits or raw D24 values.

## Archived real PMM draws

Two original accessory draws are reconstructed from the archived geometry and
states: a two-triangle draw and the following 232-triangle draw. Each draw's
entire vertex buffer is captured, including vertices outside that draw's index
range: 13,894 entries per draw, **27,788 checks per architecture and policy**.

Every candidate GPU W matches CPU fused arithmetic. Policy 1 preserves all
pre-compensation X/Y/Z bits; policy 2 matches a separately captured combined-
matrix XYZ control. Both policies change W in 8,240 entries. Policy 2 changes
XYZ in 25,908 entries. These counts include the duplicated buffer captures.

Fresh native original and repeat images must equal the previously captured
application viewport byte for byte. They do. Candidate repeats are also exact.
The analysis verifies archived geometry hashes, draw ranges, states and matrix
bits against the saved application log. All fourteen control images per policy
are retained, including six isolated triangles, disabled depth, reversed order
and strict `Less` comparisons.

| Architecture / path | Different pixels | Delta > 1 pixels | Maximum channel delta |
|---|---:|---:|---:|
| x64 original DX11 | 102 | 7 | 87 |
| x64 candidate W only | 96 | 1 | 49 |
| x64 combined XYZ + candidate W | 1 | 1 | 49 |
| x86 original DX11 | 9 | 8 | 72 |
| x86 candidate W only | 1 | 0 | 1 |
| x86 combined XYZ + candidate W | 3 | 2 | 94 |

Every nonzero channel difference remains a failure. All four candidate image
diagnostics return **32**, as do the two unchanged baselines.

Disabling depth leaves 95/1 pixels with delta 1 for policy 1 (x64/x86), and
0/1 for policy 2. The six isolated triangles match native exactly under both
policies. Policy 2's x64 residual is at (1220,505), with channel delta 49.
Changing to strict `Less` or reversing triangle order removes this x64 residual,
but leaves or introduces other x86 residuals. Those counterfactual changes
cannot count as acceptance of the original draw.

## Conclusion and next bounded check

Actual GPU implementation reproduces the fixed CPU W candidate on the tested
inputs and eliminates the synthetic W-related mismatch. Real images improve,
but the best policy depends on viewport/architecture; combining XYZ also
introduces new x86 surface-selection errors. This is insufficient to establish
general DX9 transform equivalence or accept the accessory draw.

Keep the candidate diagnostic-only. A further investigation can isolate the
remaining x64 overlap at (1220,505), together with the new x86 overlap controls,
holding each policy fixed while comparing vertex clip values and depth-plane
thresholds separately. Do not choose a transform policy by architecture, add
a depth bias, or replace zero-difference gates with a tolerance. Other portable
RHI work need not depend on resolving this driver arithmetic hypothesis.

The [reduced overlap measurements](RHI_W_OVERLAP_DEPTH_REDUCTION.md) now retain
the residuals in triangle pairs. Native Z-only `dp4` restores all 21 tested
original depth thresholds, while W-only misses three; shared clip thresholds
agree across backends. This narrows the remaining local transform question to
Z. The separate x86 one-channel color delta survives a solo-triangle control.

## Reproduce

```powershell
python tools/generate_w_geometry.py exports/w-geometry/fixtures.bin
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --w-gpu-geometry exports/w-geometry/fixtures.bin exports/w-gpu-geometry/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --w-gpu-geometry exports/w-geometry/fixtures.bin exports/w-gpu-geometry/x86
python tools/analyze_w_geometry.py --gpu --fixtures exports/w-geometry/fixtures.bin exports/w-gpu-geometry/x64 exports/w-gpu-geometry/x86

# Requires the previously captured private PMM evidence; repeat for x86 and policy 2.
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-native-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-w-gpu exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 1
python tools/analyze_w_gpu_batch.py exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 1
```

Synthetic captures/analysis remain ignored under `exports/w-gpu-geometry/`;
PMM captures/analysis under each reference's `accessory-w-gpu-{1,2}/` directory.
Logs are `exports/w-gpu-geometry-*.log`, `w-gpu-analysis-combined.log`,
`w-gpu-real-*-p*.log`, `w-gpu-real-analysis-*-p*.log` and `w-gpu-baseline-*.log`.
No private PMM assets or captured images are added to source control.

Both builds pass, together with twelve focused CTest regressions, recorded in
`exports/w-gpu-focused-{x64,x86}.log`. These verify existing replay conversion,
Hardware/WARP replay, viewport handling and portable replay validation; they
do not turn the failed native PMM image comparison into a pass.
