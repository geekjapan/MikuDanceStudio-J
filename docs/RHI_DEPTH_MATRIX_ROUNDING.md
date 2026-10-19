# Matrix combination and rounding controls

This extends [camera-space isolation](RHI_DEPTH_TRANSFORM_ISOLATION.md) using
the same private PMM accessory draw 2, six triangles and five ID-colored pairs.
Native DX9 HAL hardware vertex processing and DX11 Hardware run on NVIDIA
TITAN Xp. All measurements are single-sample D24S8; application rendering is
unchanged and full-prefix DX11 acceptance remains blocked.

## Controls

Ten candidate modes retain the original object-space vertex bytes:

| Modes | Supplied matrices | Coefficient arithmetic |
| --- | --- | --- |
| 7, 8, 13, 16 | World = I, View = W*V, Projection = original P | Sequential float, double, paired float, fused float |
| 9, 10, 14, 15 | World = I, View = I, Projection = (W*V)*P | Sequential float, double, paired float, fused float |
| 11, 12 | World = I, View = I, Projection = W*(V*P) | Sequential float, double |

The original diagnostic ID shading removes lights, textures, blend and
stencil while retaining the vertex layout and position transform. No vertex
position is divided by W or CPU-baked in these matrix controls. The GPU still
performs vertex transformation; CPU arithmetic only builds the proposed
combined coefficients.

Coefficient kernels specify their rounding boundaries explicitly:

- Sequential: four float32 products, then float32 left-to-right additions.
- Paired: four float32 products, then `(p0+p1)+(p2+p3)` with float32 partials.
- Fused: left-to-right `std::fma` steps with one rounding per fused step.
- Double: double products and double accumulation, then cast each output
  coefficient to float32. Each matrix multiplication returns float32; it does
  not carry double coefficients through the next matrix multiplication.

Volatile intermediates pin separate rounding steps across x86/x64. Independent
cancellation checks distinguish sequential/paired/double accumulation and
separate/fused multiplication before GPU experiments run. These verify the
diagnostic kernels; they do not establish the driver's arithmetic.

Each candidate repeats the 100 pair-image controls, reference-plane calibration
and Equal/Less scans. Its five original-order pair images are also compared
directly against freshly rendered original matrices in each backend. The
analyzer compares every previously measured native threshold (14 x64 and
16 x86) at the exact same coordinates and checks independently selected
coverage coordinates. Reference bits denote float32 reference-plane inputs,
not raw D24 codes.

The production DX11 shader is observed through stream output before and after
matrix replacement. Changed clip components are recorded separately from
image and attachment results; they are not labeled native DX9 vertex outputs.

## Results

All ten modes complete on both architectures. All retain the five original
DX9 pair images and every previously measured native DX9 threshold exactly.
This preservation claim covers those images and coordinates, not all possible
native images or drivers. Every mode still returns **32**, because backend
image/depth differences remain in its full control matrix.

| Input form | x64 mismatching images / 100 | x86 mismatching images / 100 | x64 differing thresholds | x86 differing thresholds |
| --- | --- | --- | --- | --- |
| Original separate matrices | 33 | 46 | 7 / 14 | 8 / 16 |
| Precombined W*V, all four coefficient kernels | 23 | 31 | 6 / 18 | 8 / 18 |
| Precombined WVP, either parenthesization and all tested kernels | 9 | 4 | 3 / 20 | 8 / 18 |

Threshold denominators differ because candidate controls retain all original
coordinates and add coverage-selected or newly discrepant coordinates.
Counts therefore cannot be treated as error rates on identical sample sets.
All original coordinates are compared explicitly in `matrix_controls.json`.

For precombined WVP, the five original-order pair images have one nonzero
backend pair on x64 and zero on x86. The x86 zero does not survive the other
ordering/depth controls. Its remaining attachment differences can be hidden
when both faces move together or the original order selects the same winner.
An apparently exact surface image is not an exact depth-history contract.

Every mode has 15 exact reference calibration comparisons. Repeats match
within each backend and depth-disabled images remain exact. The shared
camera-input control from the preceding experiment still provides a distinct
reference: it makes backend depth comparisons exact but changes native DX9
results. These precombined-matrix controls preserve those native results but
do not eliminate all backend differences.

## What the experiment distinguishes

Each architecture's ten candidate modes produce only **three distinct matrix
byte sets**:

1. All W*V coefficient kernels produce the same bytes.
2. All `(W*V)*P` coefficient kernels produce the same bytes.
3. Both `W*(V*P)` kernels produce the same bytes.

Left- and right-parenthesized WVP differ at exactly two coefficients on both
architectures, each by one float32 ULP (zero-based row/column):

| Combined projection coefficient | Left-parenthesized bits | Right-parenthesized bits |
| --- | --- | --- |
| row 0, column 1 | `0xba0731c6` | `0xba0731c7` |
| row 3, column 0 | `0x3dcb38c1` | `0x3dcb38c0` |

These affect X/Y only. The Z and W columns are byte-identical, so equal measured
depth outcomes cannot discriminate these parenthesizations. The small X/Y
changes also leave the measured image outcomes identical. The original
view is nearly diagonal and the projection is sparse. Consequently this
archive does not discriminate coefficient rounding rules or parenthesization
despite the different algorithms and their independently verified behavior.
The analyzer records matrix SHA256 groups and every left/right coefficient's
float value and bits to expose this limitation.

Precombination changes production DX11 clip outputs substantially while
preserving measured native DX9 outcomes. This is consistent with native
matrix-combination/vertex-arithmetic behavior different from the current
staged HLSL transformation. It does not prove whether the driver precombines
two or three matrices, or identify its exact multiply/add ordering.
With combined coefficients supplied, the remaining backend differences also
prevent attributing everything solely to CPU coefficient rounding. GPU dot
evaluation, perspective division and depth setup remain possible contributors.

The next discriminating experiment needs controlled matrices with multiple
nonzero terms and cancellation, chosen so candidate coefficients or clip
values differ at independent coordinates. Alternatively, a validated native
post-transform observation can test the arithmetic directly. No CPU formula,
software `ProcessVertices`, depth bias or global comparison change is adopted
as a native reference or production correction from these results.

## Reproduce and evidence

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --transform-depth-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 9
python tools/analyze_depth_matrix_controls.py exports/shadow-prefix-dx11-x64 --modes 9
```

Run modes 7 through 16 for the full matrix. Use the corresponding x86 paths.
The analyzer rejects missing original coordinates, malformed/incomplete pair
matrices, invalid threshold scans and failed ruler/surface-choice checks. It
does not turn expected backend image failures into acceptance.

Ignored evidence includes `exports/matrix-depth-*.log`, `matrix-candidates-*.log`,
`matrix-build-*.log`, each candidate directory's CSV/JSON, pair images,
`candidate_matrices.bin`, stream-output clip data and `matrix_controls.json`.
No private model/PMM assets are added to the repository.

Both diagnostic builds and twelve focused CTests pass, including arithmetic
cancellation checks, CPU conversion/version checks and Hardware/WARP native
conversion/viewport regressions. Logs are `exports/matrix-focused-{x64,x86}.log`.
These regressions do not override the failing native image/depth gates.

The subsequent [sensitive cancellation fixtures](RHI_SENSITIVE_DEPTH_MATRICES.md)
produce distinguishable depth results without private assets. A sequential
float32 `(W*V)*P` candidate matches the native synthetic thresholds including
fixed holdouts, while perspective PMM and MSAA acceptance remain separate.
