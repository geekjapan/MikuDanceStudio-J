# Perspective holdout case 10: vertex evaluation versus depth plane

This continues [perspective evaluation](RHI_PERSPECTIVE_DEPTH_EVALUATION.md).
It fixes the synthetic holdout case 10, sequential-float `(W*V)*P` coefficients,
original object-space triangle and pixels (36,46) and (20,42). It requires no
PMM assets. Tests use DX9 HAL hardware vertex processing and DX11 Hardware on
NVIDIA TITAN Xp, a 64x64 single-sample target and D24S8.

The remaining original difference is one reference-plane float32 step at
(36,46): native threshold input bits 1061277837 versus DX11 1061277836.
The independent coordinate (20,42) is 1061372272 in both backends. These are
constant-reference input bits classified by Less/Equal, not raw depth codes.

## Shared clip control

The production DX11 shader exports its clip XYZW before the existing half-pixel
compensation. Adding that export must leave all three final clip vertices
bit-identical to the unmodified shader.

A separate test-local renderer supplies the captured four-component clip bytes
to both backends. Its DX9 shader passes them through directly; DX11 applies
the same half-pixel compensation as production. Stream output must prove that
the resulting DX11 final clip output is bit-identical to production again.
Both shaders use float4 vertex input, avoiding a CPU divide or forced W=1.

This shared-input test retains the original production DX11 thresholds on
both coordinates. DX9 changes to the DX11 threshold at (36,46); the one-step
backend discrepancy disappears. Thus the tested raster paths can agree when
given these common clip inputs. The native fixed-function intermediate clip
values have not been captured; a programmable bypass is not assumed to be
equivalent to its internal driver-generated shader.

## Explicit native instruction controls

Test-local DX9 vertex shaders consume the original object-space float4 and
the same combined coefficients while DX11 keeps the proven shared clip input:

- Dot: four explicit `dp4` operations, using matrix columns as constants.
- Ordered: explicit separate `mul` and left-to-right `add` instructions.
- Reverse: the same products added from W/Z toward Y/X.
- Paired: `(X product + Y product) + (Z product + W product)`.

Disassembled shader listings are logged. The compiler must actually emit the
claimed `dp4` or separate `mul/add` structures; HLSL source spelling alone is
not the evidence. The explicit `dp4` shader reproduces the original native
thresholds at both coordinates. Ordered and paired controls match shared
clip instead. Reverse accumulation raises the independent coordinate by one
reference step and matches the original native value at (36,46).

Four additional hybrid shaders pass captured components through unchanged
while computing only Z, W, Z/W together, or X/Y via `dp4`. A separate float4
attribute supplies the captured clip components, so no matrix multiplication
is required for the components held fixed. Logged disassembly confirms the
corresponding individual dot instructions.
Instruction counts are checked, not merely logged: full dot must contain four
`dp4`; explicit accumulation must contain four `mul` and three `add`, with no
`mad`; each hybrid must contain the expected one or two dot operations.

| Native path | Threshold at (36,46) | Threshold at (20,42) |
| --- | --- | --- |
| Original fixed function | 1061277837 | 1061372272 |
| Shared clip | 1061277836 | 1061372272 |
| Full `dp4` | 1061277837 | 1061372272 |
| Ordered `mul/add` | 1061277836 | 1061372272 |
| Reverse `mul/add` | 1061277837 | 1061372273 |
| Paired `mul/add` | 1061277836 | 1061372272 |
| Only Z via `dp4` | 1061277836 | 1061372272 |
| Only W via `dp4` | **1061277837** | 1061372272 |
| Z and W via `dp4` | 1061277837 | 1061372272 |
| Only X/Y via `dp4` | 1061277836 | 1061372272 |

The DX11 side is fixed at 1061277836 / 1061372272 for these instruction
controls, with final clip bits equal to the original production shader.
Replacing W evaluation alone is sufficient to reproduce the remaining native
depth discrepancy. Replacing Z or X/Y alone is not. This makes native dot/W
evaluation the next target; it does not identify an exact native rounding
formula or directly measure the native W bits.

## Geometry controls and limits

With shared clip input, cyclic vertex order, reversed winding and power-of-two
homogeneous scales of 2 and 8 preserve both measured thresholds exactly in
both backends. Scaling all four components is bit-exact and leaves the ideal
projected depth plane unchanged. A shared NDC W=1 control also preserves these
two particular thresholds; this does not override the non-equivalence at six
other coordinates in the preceding perspective experiment.

Shortening either original edge to 7/8 changes the measured thresholds, but
DX9/DX11 still agree on every tested coordinate. New clip endpoints use double
homogeneous interpolation rounded to float32. Analysis reports the resulting
ideal double plane change separately from measured threshold changes. These
modified triangles must not be called bit-identical planes or native-preserving
replacements. Geometry-dependent raster setup can alter both backends in the
same direction; the controls do not prove every internal depth coefficient
is invariant or that geometry error is absent generally.

| Edge restriction | Ideal double-plane change in float reference steps, target / independent point | Measured shared threshold change, target / independent point |
| --- | --- | --- |
| Edge 1 shortened to 7/8 | +0.0387 / +0.0490 | +1 / +1 |
| Edge 2 shortened to 7/8 | +0.4366 / +0.2012 | -19 / -9 |

The mathematical plane shifts are small, while the measured edge-2 changes are
larger and in the other direction. Both raster backends show the same change.
This demonstrates geometry-dependent establishment/evaluation effects beyond
the exact double plane, including possible screen-coordinate quantization;
it does not identify which internal raster step causes them. It is separate
from the native W-only control that creates a backend discrepancy.

## Results and next boundary

Both architectures complete 18 variants at two coordinates (36 threshold
pairs each). Every boundary and immediately preceding Less input is verified
three times by fresh draws. All 72 corresponding backend thresholds are equal
across x64/x86. Six native/DX11 threshold pairs differ per architecture: the
original production point, full dot point, two reverse-accumulation points,
W-only point and Z/W point. Diagnostics return **32**, retaining those failures.

This is strong local evidence for vertex W arithmetic involvement rather than
a cross-backend depth-plane discrepancy on identical captured inputs. Native
fixed-function clip output, driver translation of `dp4` and precise dot rounding
remain unobserved. No production shader, matrix policy or depth bias changes.
The application's original DX9 path and real-PMM image acceptance gate remain.

A next useful control is to compare individual W dot hypotheses and their
reference-plane predictions, including independent coordinates and small
coefficient perturbations. A validated native post-transform observation would
be stronger than fitting reference-depth thresholds alone. Real-PMM narrow
triangles and MSAA still require their own acceptance.

## Reproduce and evidence

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --perspective-case10 exports/perspective-depth/fixtures.bin exports/perspective-case10/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --perspective-case10 exports/perspective-depth/fixtures.bin exports/perspective-case10/x86
python tools/analyze_perspective_case10.py exports/perspective-case10/x64 exports/perspective-case10/x86
```

Generate the existing perspective fixture using the preceding report's command.
Ignored evidence is `exports/case10-{x64,x86}.log` (including disassembly),
`case10-build-*.log`, `case10-analysis.log`, and the per-architecture matrices,
object/clip data, CSV and JSON under `exports/perspective-case10/`.
The analyzer rejects missing coordinates, unstable repeats, changed original
thresholds and any failure to retain production clip bits.

Both builds and twelve focused CTests pass, recorded in
`exports/case10-focused-{x64,x86}.log`. These regressions do not override the
failed original native image/depth gates.

The subsequent [W coefficient perturbation](RHI_W_DOT_PERTURBATION.md) extends
the native dot/W relation to +/-1, +/-2 and +/-4 ULP inputs. A CPU fused-W
hypothesis matches calibration and fixed holdout depth thresholds, while
native W bits and a universal arithmetic rule remain unobserved.
