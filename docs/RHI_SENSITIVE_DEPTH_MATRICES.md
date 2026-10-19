# Cancellation matrices for depth arithmetic discrimination

This continues the [matrix audit](RHI_DEPTH_MATRIX_ROUNDING.md). The real PMM
matrices were too sparse to distinguish several rounding hypotheses. This
experiment generates new, deliberately sensitive matrices and one simple
triangle. It requires no private PMM, model, texture or application UI.

## Fixtures and separation

`tools/generate_sensitive_depth_matrices.py` uses fixed seed 20261003. World
has translations up to 12000; view undoes X/Y translation and combines several
small nonzero Z coefficients with a compensating Z translation. Projection
has a non-power-of-two depth scale and a compensating offset. The resulting
small depth comes from cancellation of much larger terms, while X/Y remain
visible. W is 1; this isolates coefficient combination without perspective
division. The fixture is orthographic, not a PMM camera emulation.

Selection uses only CPU coefficient discrimination and visible depth bounds.
Every case has at least three distinct candidate center depths, separated by
at least 2^-21 in total. No GPU residual is used to select or modify a case.
The first six cases are calibration and the remaining six are fixed holdout.
Each has two interior pixel coordinates, (20,42) and (36,46), assigned before
measurement. Triangle coverage at both coordinates is verified for every mode
and backend before depth probing.

The generator stores original float32 matrices in a versioned binary fixture
and predicted candidate coefficients in JSON. The C++ diagnostic recomputes
them with the independently checked rounding kernels. Analysis requires the
generator/C++ center coefficient bits to agree for all candidates.

Seven modes are compared:

- Original W, V and P supplied separately to native fixed-function DX9 and
  the production DX11 model shader.
- Precombined `(W*V)*P` using sequential float32, double intermediate products
  and sums with float32 coefficient storage after each matrix multiply,
  paired float32 sums, or left-to-right float32 fused multiply/add.
- Precombined `W*(V*P)` using sequential float32 or double intermediate arithmetic.

Combined modes retain the original object-space triangle and set world/view
to identity. The combined coefficients are supplied as projection. ID colors
remove lights/textures/blend/stencil from the observed surface decision.

## Observation

DX9 is HAL hardware vertex processing; DX11 uses Hardware on NVIDIA TITAN Xp.
Both use a 64x64 target, single sampling and D24S8. For each mode and coordinate,
the diagnostic draws the red triangle and a green constant-reference plane.
Binary search with `Less` finds the first reference float32 input that no
longer passes. `Equal` must pass at that boundary. The preceding input must
pass `Less`, and both comparisons are reissued three times with fresh draws.
Cached search results only remove duplicate bisection queries; they never
replace repeated stability checks.

The CPU candidate planes merely center a conservative search bracket. Both
backends must prove its lower/upper endpoint relations. The measurement is
an actual attachment comparison, not a CPU prediction or raw D24 readback.
Production DX11 clip outputs and all candidate Z/W coefficients are saved.

There are 168 threshold observations per architecture: twelve cases, seven
modes and two coordinates. The analyzer rejects missing/duplicate entries,
failed equality or repetition, a changed split, and coefficient-generation
disagreement. It chooses a shortlist solely on calibration matches to original
DX9, then reports the fixed holdout separately. Full-scene acceptance is always
false; mismatching backend diagnostic results return 32.

## Results

Both architectures complete all 168 measurements. Equal/Less boundaries repeat
exactly. The generator's predicted center bits agree with the C++ coefficient
kernels for all 72 candidates. The six-candidate coefficient differences are
now observable in depth; they are not duplicate matrices as in the PMM audit.

| Candidate | Native calibration matches, each architecture | Native holdout matches, each architecture |
| --- | --- | --- |
| `(W*V)*P`, sequential float32 | **12 / 12** | **12 / 12** |
| `(W*V)*P`, double intermediates | 0 / 12 | 0 / 12 |
| `(W*V)*P`, paired float32 | 2 / 12 | 4 / 12 |
| `(W*V)*P`, fused float32 | 10 / 12 | 8 / 12 |
| `W*(V*P)`, sequential float32 | 2 / 12 | 4 / 12 |
| `W*(V*P)`, double intermediates | 0 / 12 | 0 / 12 |

The calibration shortlist is uniquely `left_sequential`. It is chosen before
considering holdout matches. The preassigned holdout confirms all twelve
additional depth thresholds; other candidates do not match all coordinates.
The matching DX11 precombined candidate also agrees with the original native
DX9 thresholds at these same coordinates.

All **144** precombined candidate observations per architecture agree between
DX9 and DX11. The original separate-matrix input differs between backends at
**23 of 24** coordinates per architecture. Both full diagnostics therefore
return **32**, retaining the original-input failure rather than declaring the
full control matrix accepted. The matching candidate is a narrower conclusion.

All 336 corresponding backend thresholds across x64/x86 are identical. This
architecture check uses exactly the same fixture bytes, triangle and viewport,
unlike the earlier real-PMM captures with different viewport sizes.

The results support `(W*V)*P` with separate float32 product/add rounding as a
native-equivalent coefficient hypothesis for these synthetic controls on the
tested device. They reject the other five candidate hypotheses as exact
descriptions of these measurements. They do not uniquely identify all possible
internal driver algorithms or guarantee a match for perspective PMM batches.

## Interpretation limits

These exaggerated cancellation matrices identify behavior of this device,
driver and diagnostic state. They do not establish a universal DX9 arithmetic
contract. A candidate that preserves native depth thresholds is not a capture
of the native vertex output or proof of identical coefficients inside the
driver. Depth attachment quantization can hide smaller arithmetic differences.
The orthographic W=1 fixtures do not distinguish perspective division or MSAA.

The real PMM precombined-WVP controls still have residual backend differences,
so even a fully matching synthetic candidate cannot activate a renderer or
justify an arbitrary depth correction. Application drawing remains DX9.

## Reproduce

```powershell
python tools/generate_sensitive_depth_matrices.py exports/sensitive-depth/fixtures.bin
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --sensitive-depth-hardware exports/sensitive-depth/fixtures.bin exports/sensitive-depth/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --sensitive-depth-hardware exports/sensitive-depth/fixtures.bin exports/sensitive-depth/x86
python tools/analyze_sensitive_depth.py exports/sensitive-depth/x64 exports/sensitive-depth/x86
```

Fixture binaries/JSON, thresholds, coefficients, clip captures and analysis
remain ignored under `exports/sensitive-depth`. This test is explicitly invoked
and fails if hardware setup or measurements fail; it never silently skips.

Evidence logs are `exports/sensitive-depth-{x64,x86}.log`,
`sensitive-analysis-{x64,x86,combined}.log` and `sensitive-build-{x64,x86}.log`.
Both builds and twelve focused regression CTests pass, recorded in
`exports/sensitive-focused-{x64,x86}.log`. Those regressions do not override
the original-input depth mismatches or real-PMM image gates.

The subsequent [perspective and real-PMM retest](RHI_PERSPECTIVE_DEPTH_EVALUATION.md)
retains the synthetic native coefficient hypothesis but finds a remaining
single-reference-step DX11 discrepancy and persistent real-PMM differences.
Shared post-division input is not equivalent to the original depth history.
