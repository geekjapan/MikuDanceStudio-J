# Perspective Z/W and real-PMM depth retest

This continues the [orthographic cancellation experiment](RHI_SENSITIVE_DEPTH_MATRICES.md).
It extends the asset-free fixture to varying positive clip W, then retests the
existing real-PMM accessory captures with actual DX9 draws. All controls use
single sampling and D24S8. Application rendering remains native DX9.

## Perspective fixture and controls

The generator's `--perspective` option emits version `SDEP0002`. Camera depth
is centered near 4 after cancellation of large translation products. View Z
depends on object X/Y. Projection uses a conventional left-handed near/far
depth mapping: `P[2,3]=1`, `P[3,3]=0`. Clip W therefore varies over the triangle.
Near/far values and matrices are selected using the fixed CPU seed and depth
visibility/discrimination criteria, without observing GPU residuals.

There are twelve cases: six calibration and six preassigned holdout. The
orthographic experiment's sequential float32 `(W*V)*P` candidate is fixed before
this measurement. The other five matrix hypotheses remain comparison controls;
no new formula is fitted to the perspective holdout.

Seven original/matrix modes are retained. Three new controls share production
DX11 shader observations:

1. Shared camera: export the intermediate camera value and feed its XYZ to
   both backends with identity world/view and the original perspective matrix.
   Instrumentation and the bypass must preserve every original DX11 clip bit.
2. Shared NDC float: divide captured clip XYZ by W in float32 on CPU, undo the
   existing pixel-center compensation, then feed shared XYZ with identity
   matrices and W=1.
3. Shared NDC double: divide in double, round each result to float32 and feed
   the same representation. This distinguishes any CPU quotient difference;
   neither mode is a capture of native GPU division.

The two fixed interior coordinates per case must have common triangle
coverage in all modes. Constant-reference Less/Equal scans establish native
attachment thresholds and repeat the actual boundary three times. CPU
candidate planes and captured clip planes center conservative brackets;
endpoint relations must be verified by both backends. There are 240 measured
threshold pairs per architecture. The recorded bits identify float32 reference
inputs, not raw D24 codes.

Saved production clip data must have varying positive W in every case. Analysis
verifies all camera-bypass clip bits and checks the shared NDC clip Z against
correctly rounded CPU Z/W for all 36 vertices. It compares the NDC controls
against the original DX11 thresholds separately from comparing backend results.
Changing W to 1 changes representation and cannot itself establish equivalence
to the original native renderer.

## Perspective results

On both x64 and x86, the fixed sequential-float `(W*V)*P` hypothesis
retains all 12 calibration and all 12 native holdout thresholds. The five
alternative coefficient hypotheses match 0, 8, 12, 0 and 0 of the original
native thresholds respectively (double left, paired left, fused left,
sequential right, double right).

Supplying this fixed combined matrix to DX11 matches 23/24 original native
thresholds, not 24/24. The remaining point is holdout case 10, pixel (36,46):
native reference bits 1061277837 versus DX11 1061277836. Both equality and
the preceding Less boundary repeat exactly. This is one reference float step,
not a measured raw D24-bit delta.

Original separate-matrix depth differs across backends at all 24 coordinates.
Across all six combined candidates, 14/144 backend thresholds differ. Thus
the orthographic experiment's exact combined-input result does not generalize
to these varying-W cases.

Shared camera preserves all original DX11 clip bits and thresholds, and
matches across backends at all 24 coordinates. It changes all 24 original
native thresholds. This again constrains transform-path differences for the
original input; it does not recover the original native vertex outputs.

Shared NDC is also exact across backends at all 24 coordinates, but preserves
only 18/24 original DX11 thresholds. Both CPU division variants have identical
saved clip bits; all 36 shared NDC Z values agree with correctly rounded CPU
Z/W. Captured W varies positively from approximately 3.487 to 4.513.
Consequently changing to W=1 cannot be treated as an equivalent history input.
This control changes vertex quotient rounding and geometric representation;
its six changed thresholds do not uniquely locate an internal GPU division
error. The remaining combined-input discrepancy also cannot be assigned to
division alone without native post-transform evidence.

The diagnostic returns 32 because its full control matrix contains backend
differences. No tolerated delta or depth bias changes that acceptance result.
All 480 corresponding backend thresholds are identical across architectures.
Each has 240 observations with stable repeated boundaries. Analysis also stores
CPU double quotient planes and a rounded-vertex-Z-only control for the original
and precombined clip data. These mathematical diagnostics are not fitted GPU
interpolation models or direct raw-D24 predictions.

## Real-PMM retest scope

The second part uses the previously captured `sample.pmm` accessory draw 2
(232 triangles) and its six selected coplanar triangles. It does not claim a
new application capture: source geometry/matrices/material/light data come
from the documented private reduction archive. Native images and depth
comparisons are freshly rendered with HAL hardware vertex processing.

The complete original batch keeps material/light inputs and supplies the
original transforms. Matrix controls operate on ID-colored coplanar pairs
to isolate depth; precombining the position matrices is not a correct replacement
for material normal/light transforms. No full-material pipeline is silently
rewritten. Original, sequential precombined WVP (mode 9) and verified shared
camera (mode 6) are compared with the same viewport per architecture.

The matrix control includes LessEqual/Less, both draw orders, repeats, vertex
cycles, alternate depth ranges and independent reference calibration. Native
thresholds at every earlier mismatch coordinate remain explicitly compared
with the original. Full-scene acceptance is always false while these image
or depth gates fail.

## Real-PMM results and decision

Fresh native original/repeat images are byte-identical to each other and to
the saved application crop on both architectures (SHA256 equality). Rebuilt
DX11 original images also match their earlier diagnostic images exactly.
This validates the archived baseline without claiming a new live application
capture.

| Fresh original full accessory batch | x64 | x86 |
| --- | --- | --- |
| Different pixels | 102 | 9 |
| Pixels with delta above 1 | 7 | 8 |
| Maximum channel delta | 87 | 72 |
| Different pixels with depth disabled | 95, all delta 1 | 1, delta 1 |
| Six isolated triangle images | All exact | All exact |

The two archived viewport sizes differ; this table compares each architecture
with its own native baseline, not x64 images directly with x86 images.

| Real-PMM ID-pair control | x64 nonexact images / 100 | x86 nonexact images / 100 | x64 differing reference probes | x86 differing reference probes |
| --- | --- | --- | --- | --- |
| Original matrices | 33 | 46 | 25 / 252 | 31 / 288 |
| Sequential precombined WVP | 9 | 4 | 9 / 360 | 25 / 324 |
| Shared production DX11 camera | 0 | 0 | 0 / 324 | 0 / 324 |

Precombination retains all five original-order native pair images and all
previously measured native thresholds (14 x64, 16 x86). It leaves 3/20 x64
and 8/18 x86 measured backend thresholds different. It is not an accepted
position pipeline even though the synthetic native coefficient hypothesis
matches. The original and combined diagnostics return 32.

Shared camera has exact backend thresholds but changes 7 original native
pixels on x64 and 8 on x86. Original DX11 pair images and all 13,894 production
clip vertices per architecture remain bit-exact. Its diagnostic returns 0 only
for the shared-input comparison; it does not preserve the native baseline.
All per-control ruler checks and repeated draws remain stable.

The remaining investigation can start from synthetic holdout case 10, (36,46),
with saved clip data and the real-PMM narrow-triangle threshold coordinates.
Native vertex dot evaluation, division and depth-plane setup must be separated
without changing native surface choices. No global WVP replacement, NDC history
substitution, arbitrary bias or renderer activation follows from this result.
Color delta-1, full-scene history and MSAA remain separate acceptance gates.

## Reproduce

```powershell
python tools/generate_sensitive_depth_matrices.py exports/perspective-depth/fixtures.bin --perspective
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --sensitive-depth-hardware exports/perspective-depth/fixtures.bin exports/perspective-depth/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --sensitive-depth-hardware exports/perspective-depth/fixtures.bin exports/perspective-depth/x86
python tools/analyze_sensitive_depth.py exports/perspective-depth/x64 exports/perspective-depth/x86

./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-native-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --coplanar-depth-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --transform-depth-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 9
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --transform-depth-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 6
```

Use corresponding x86 paths for real-PMM retests. All fixture binaries, clip
captures, images, reference thresholds and analysis remain ignored under
`exports`. The generator and analysis scripts contain no private assets.

Evidence logs: `exports/perspective-depth-{x64,x86}.log`,
`perspective-analysis-{x64,combined}.log`, `perspective-real-batch-*.log`,
`perspective-real-original-*.log`, `perspective-real-mode{9,6}-*.log` and
the corresponding matrix/camera analysis logs. Both builds and twelve focused
CTest regressions pass (`exports/perspective-focused-{x64,x86}.log`), while
the original native image/depth gates above remain failed.

The subsequent [case-10 reduction](RHI_PERSPECTIVE_CASE10_REDUCTION.md) shows
shared clip inputs agree, while native `dp4` evaluation of W alone reproduces
the one-step difference. Native W bits and exact dot arithmetic remain unknown.
