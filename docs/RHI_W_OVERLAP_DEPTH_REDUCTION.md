# Reduced PMM overlap after the W candidate

The [diagnostic fused-W candidate](RHI_DX11_W_CANDIDATE.md) still leaves one
large x64 pixel difference and introduces two large x86 differences under its
combined-XYZ policy. These are now reduced to individual triangle pairs.
Native programmable `dp4` component controls identify a remaining Z-transform
dependency. The separate x86 color delta survives a one-triangle reduction.
**The application and production shaders remain unchanged.**

## Fixed experiment boundary

`--w-overlap-depth` reads the existing untextured 232-triangle accessory archive.
The three DX11 paths keep their preceding meanings throughout:

| Policy | Position computation |
|---|---|
| 0 | Original production staged world/view/projection |
| 1 | Original X/Y/Z, fixed candidate W |
| 2 | CPU sequential combined-matrix X/Y/Z, fixed candidate W |

Fresh DX9 HAL hardware-vertex-processing draws keep the archived matrices.
DX11 Hardware runs on NVIDIA TITAN Xp. All targets are single-sample RGBA8 with
D24S8; this is not MSAA or full-scene acceptance. The application is not opened
again: the source is previously captured real PMM data, rendered by fresh
independent native and diagnostic devices.

The analyzer checks geometry hashes, original draw ranges, matrix bytes and
253 archived render/texture/sampler states against the saved application log.
Each original shaded reduction must retain the saved native pixel color at
its primary coordinate. That check passes for all four reductions.

## Reductions and coordinates

| Captured viewport | Triangles, original zero-based numbers | Primary coordinate | Coverage-selected additional coordinates |
|---|---|---|---|
| x64: (565,25), 1032x774 | 135, 227 | (1220,505) | (1218,505), (1222,505) |
| x86: (274,25), 670x503 | 197, 231 | (427,338) | (425,338), (429,338) |
| x86: same | 185, 231 | (381,340) | (383,339), (381,339) |
| x86: same | 197 alone | (430,234) | (428,234), (429,234) |

Primary coordinates diagnose the already observed residuals. They are not
unseen validation data. Two additional coordinates per group are chosen from
a fixed nearby offset list by interior coverage alone. No threshold agreement
selects them, and no matrix or arithmetic hypothesis is fitted to these data.
Triangle 185's primary point lies near an edge, so its additional coordinates
use the adjacent row rather than relaxing the interior-coverage condition.

Shaded pair/solo renders preserve original material, lights and culling.
Separate red/green ID draws remove shading, disable culling and compare original
`LessEqual`, strict `Less`, disabled depth, and both draw orders. Disabling depth
produces zero backend differences for every ID control.

Each selected triangle is also rendered independently against a constant-depth
ruler with `Less` and `Equal`. A bounded binary search identifies its equality
reference. Adjacent references must fail equality, and three fresh repeated
checks must preserve the relation. Original index order and both cyclic orders
are measured. Every path uses the same target and original viewport; depth
results are float32 ruler input bits, **not raw native D24 or native clip bits**.

## Shared clip and native instruction controls

The candidate's actual DX11 pre-center clip float4 values are supplied to both
backends through a test-local passthrough shader. Before any image collection,
stream output must confirm that the DX11 passthrough reproduces all selected
final production/candidate clip bits exactly. Candidate raw captures must also
equal those from the preceding validated W experiment.

The shared renderer now supports the original viewport/target sizes in addition
to its earlier 64x64 default. It uses production's dynamic viewport division
for pixel-center compensation. An initial test version folded `1/width` into
an immediate constant and failed the clip-bit prerequisite on an x86 vertex.
Replacing it with the same dynamic expression restores exact selected clip
bits; no evidence from that failed comparison is treated as acceptance.

For each original-order triangle, four native programmable controls take the
same CPU sequential `(world * view) * projection` matrix and object vertices:

| Native DX9 control | Components recomputed using `dp4` |
|---|---|
| Full dot | X, Y, Z, W |
| Z only | Z; candidate clip X/Y/W held fixed |
| W only | W; candidate clip X/Y/Z held fixed |
| Z and W | Z, W; candidate clip X/Y held fixed |

Existing bytecode checks require the expected four/one/one/two `dp4`
instructions. These controls change the native vertex program and are
counterfactual diagnostics, not substitutes for fixed-function acceptance.
Their DX11 companion still consumes the unchanged policy-2 clip input.

## Measured surface selection

The main residual is a quantized depth tie under native DX9:

| Coordinate / triangle | Native reference bits | DX11 policy 0 | DX11 policy 1 | DX11 policy 2 |
|---|---:|---:|---:|---:|
| x64 (1220,505), 135 | 1065209263 | 1065209264 | 1065209262 | 1065209262 |
| x64 (1220,505), 227 | 1065209263 | 1065209263 | 1065209263 | 1065209263 |
| x86 (427,338), 197 | 1065209328 | 1065209328 | 1065209328 | 1065209328 |
| x86 (427,338), 231 | 1065209328 | 1065209328 | 1065209328 | 1065209329 |
| x86 (381,340), 185 | 1065209385 | 1065209385 | 1065209385 | 1065209385 |
| x86 (381,340), 231 | 1065209385 | 1065209385 | 1065209385 | 1065209386 |

Native `LessEqual` draws the later face at each tie. In x64, the W candidate
makes triangle 135 one reference step nearer, so later triangle 227 fails the
depth test. The reduced shaded pair retains the channel delta 49 seen in the
full batch. In x86, policy 2 makes later triangle 231 one step farther at both
points, retaining the earlier face; this reproduces channel deltas 94 and 56.
The measured thresholds predict all 54 checked ID surface choices, including
the additional coordinates.

The different x64/x86 source captures use different viewport sizes and probe
coordinates. These are not an experiment isolating process bitness itself;
no transform policy should be chosen by executable architecture.

## Z component evidence

Across the original-order measurements (six x64 and fifteen x86 points):

| Native programmable control | Matches original fixed-function native threshold |
|---|---:|
| Full `dp4` | 21/21 |
| Z-only `dp4` | 21/21 |
| W-only `dp4` | 18/21 |
| Z/W `dp4` | 21/21 |

At x64 (1220,505), triangle 135's Z-only control moves the candidate threshold
from 1065209262 to native 1065209263. W-only remains at 1065209262. At the two
x86 primary overlap coordinates, triangle 231's Z-only control removes the
policy-2 +1 step; W-only retains it.

Shared policy-1/2 clip inputs give **126/126 identical DX9/DX11 thresholds**,
and all match their corresponding actual DX11 adapter thresholds. Across all
three index orders, the 63 triangle/coordinate observations have no cyclic
threshold changes. This narrows the three primary mismatches to a Z-dependent
vertex transform difference under these controls, rather than an observed
backend difference when identical clip inputs are rasterized.

It does not reveal native fixed-function clip bits, specify the driver's exact
Z arithmetic, or prove that rasterization precision is identical generally.
Double depth planes computed from saved clip values still differ from measured
thresholds by up to a reference step at some points; those planes remain
diagnostic estimates rather than native interpolation formulas.

## Separate one-channel color residual

Triangle 197 alone retains the x86 (430,234) residual under all three policies:
native RGBA (26,30,56,255), DX11 (26,30,57,255). All its primary/additional depth
thresholds agree, and its ID image comparisons are exact. Thus this pixel's
color delta cannot be removed by fixing the measured overlap depth tie. Color
interpolation/rounding remains a separate investigation; this test does not
claim which operation loses precision.

## Acceptance and next step

Both full diagnostics return **32**. x64 records 24 image comparisons and 114
threshold pairs, with 12 nonmatching images and 18 nonmatching threshold pairs.
x86 records 60 images and 285 pairs, with 16 and 12 failures respectively.
Counterfactual controls and matching local thresholds do not accept the original
PMM batch or activate a renderer.

The [explicit DX11 Z validation](RHI_DX11_EXPLICIT_Z.md) now checks fixed arithmetic
candidates against independent Z-sensitive geometry and actual GPU bits, then
retests these coordinates and both viewports. Fused Z matches all measured
depth intervals and makes the x64 batch image exact; x86 retains its one-channel
color residual. All candidates remain diagnostic-only and production stays DX9.

## Reproduce and evidence

```powershell
cmake --build build-x64/build --config Release --target rhi_d3d9_replay_conversion_test
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --w-overlap-depth exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 exports/w-overlap/x64
python tools/analyze_w_overlap.py exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 exports/w-overlap/x64
# Repeat with the x86 build and corresponding x86 capture directories.
```

Original source geometry/matrices, GPU clip values, reduced images, coordinate
CSV, threshold CSV and analysis JSON remain ignored under `exports/w-overlap/`.
Logs: `exports/w-overlap-{x64,x86}.log`, `w-overlap-analysis-{x64,x86}.log`,
`w-overlap-final-build-{x64,x86}.log`, `w-overlap-focused-{x64,x86}.log`.

Both builds and fourteen focused CTest checks pass. The new asset-free
`rhi_shared_clip_depth_hardware` test validates the 64x64 default passthrough,
center-corrected clip bits, six `Less`/`Equal` ruler images and native pixel
results. Existing checks cover replay conversion/validation, Hardware/WARP
replay and viewport handling. They do not suppress native PMM failures.
