# W dot coefficient perturbation

This extends the [case-10 component reduction](RHI_PERSPECTIVE_CASE10_REDUCTION.md).
It holds the original synthetic triangle, sequential-float combined matrix,
single-sample D24S8 target and coordinates (36,46) and (20,42) fixed. DX9 HAL
hardware vertex processing and DX11 Hardware run on NVIDIA TITAN Xp. No
production shader, application render path or real-PMM input is changed.

## Preassigned inputs and controls

The three active combined-matrix W coefficients (flat row-major indices 3,
7 and 15) are independently moved by -4, -2, -1, +1, +2 and +4 float32 ULP.
The unchanged baseline is included once: **19 cases** total. `nextafter` moves
in the numerical direction, including for negative coefficients. Only one
coefficient changes in each case. The coefficient at index 11 is inactive
because every original object Z is zero, so it is not included in this sweep.

The unchanged case and +/-1 ULP are calibration: seven cases, fourteen
coordinates. +/-2 and +/-4 ULP are fixed holdout: twelve cases, twenty-four
coordinates. The input order, split, offsets and coordinates are defined
before measurements. No residual selects or modifies a coefficient case.

Each case repeats nine paths:

1. Original native fixed-function evaluation of the supplied combined matrix,
   compared with the production DX11 shader.
2. Shared raw clip input bypassing matrix evaluation in both backends.
3. Native explicit full `dp4`, with DX11 retaining production clip input.
4. Native separate ordered `mul/add`, with the same DX11 clip input.
5. Native W-only `dp4`, passing captured X/Y/Z unchanged.
6. CPU sequential separate product/add W, then shared clip input.
7. CPU double product/sum W rounded once to float32, then shared clip input.
8. CPU paired separate product/add W, then shared clip input.
9. CPU left-to-right `std::fma` W, then shared clip input.

The CPU modes hold captured clip X/Y/Z fixed and replace only W. The fused
kernel computes `sum = fma(object[k], Wcolumn[k], sum)` for k=0..3 starting
with zero. This is fused **vertex W** evaluation; it is different from the
earlier fused **matrix-coefficient multiplication** hypothesis.

Mandatory checks retain raw X/Y/Z across perturbations and preserve the
production DX11 final clip bits through instrumentation and shared passthrough.
Native shader disassembly checks retain actual `dp4` and separate `mul/add`
instructions. The constant-reference Less/Equal search proves endpoints,
equality and the preceding Less boundary, then repeats each boundary three
times with fresh draws. The unchanged case must reproduce all five earlier
GPU paths' measured thresholds.

There are **342** threshold pairs per architecture: 19 cases, nine paths and
two coordinates. Reference bits describe the input float32 ruler plane,
not raw D24 attachment bits or captured native W values.

## Results

Both architectures complete with identical outcomes and stable repetition.
All **684 corresponding backend thresholds** agree across x64/x86.

| Path | Native matches to original native, calibration | Native matches, holdout | DX9/DX11 matches across all 38 coordinates |
| --- | --- | --- | --- |
| Shared production clip | 12 / 14 | 22 / 24 | 38 / 38 |
| Explicit native full `dp4` | **14 / 14** | **24 / 24** | 34 / 38 |
| Explicit native ordered `mul/add` | 12 / 14 | 22 / 24 | 38 / 38 |
| Native W-only `dp4` | **14 / 14** | **24 / 24** | 34 / 38 |
| CPU sequential W | 12 / 14 | 22 / 24 | 38 / 38 |
| CPU double W | 13 / 14 | 22 / 24 | 38 / 38 |
| CPU paired W | 12 / 14 | 22 / 24 | 38 / 38 |
| CPU fused W | **14 / 14** | **24 / 24** | **38 / 38** |

The CPU shortlist chosen solely from calibration is uniquely `cpu_fused`.
All twenty-four fixed holdout coordinates confirm it. Native full `dp4` and
W-only `dp4` preserve all thirty-eight native thresholds, extending the prior
unperturbed observation. Ordered separate operations instead match the
captured production DX11 clip path.

Original native versus production DX11 differs at four of thirty-eight points:

| Case | W coefficient index / numerical ULP offset | Pixel | Native minus DX11 reference steps |
| --- | --- | --- | --- |
| 0 | Unchanged | (36,46) | +1 |
| 14 | 15 / +1 | (36,46) | +2 |
| 16 | 15 / +2 | (36,46) | +1 |
| 16 | 15 / +2 | (20,42) | +1 |

Each diagnostic returns **32**: original/full-dot/W-only-dot each contain
these four backend differences, totaling twelve mismatching control pairs.
Shared CPU-fused input matching native is a constrained result, not full
render-path acceptance.

Across 57 vertices (nineteen cases times three), CPU sequential and paired
W bits match production DX11 at 57/57, double at 47/57, and fused at 50/57.
The seven fused changes are each one positive-W float32 step smaller than
production. Four do not change either measured threshold; depth quantization
can hide a vertex arithmetic change. All four reference-threshold mismatches
are eliminated by the fused W input in this experiment. Candidate W fingerprints
form three distinct groups: sequential/paired, double, fused.

## Interpretation and next boundary

On these neighboring inputs, fused W evaluation predicts native depth choices
better than separate product/add or double accumulation. Full/W-only `dp4`
also remains native-equivalent in the measured threshold relations. This
supports investigating driver translation or dot arithmetic with fused-like
rounding rather than applying a generic depth-plane bias.

It does **not** prove that native fixed-function W bits equal the CPU fused
bits, or that the driver literally executes this exact four-step FMA sequence.
No native post-transform W capture exists, and only two coordinates on one
triangle and small local coefficient neighborhoods were tested. Sequential
and paired arithmetic are indistinguishable here because one product is zero.
Alternative algorithms could quantize to these same reference thresholds.

The next useful validation is fixed independent geometry with nonzero object Z
and cancellation in all four W terms, extending the matching W candidate
without fitting a driver formula to these data. Real-PMM position/normal/light
contracts and image gates must remain separate. No production FMA policy,
depth bias, shader change or renderer activation follows from this sweep.

## Reproduce and evidence

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --perspective-w-perturb exports/perspective-depth/fixtures.bin exports/w-perturb/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --perspective-w-perturb exports/perspective-depth/fixtures.bin exports/w-perturb/x86
python tools/analyze_w_perturb.py exports/w-perturb/x64 exports/w-perturb/x86
```

Generate the perspective fixtures as described in the preceding reports.
The analyzer rejects incomplete or duplicate measurements, split/order changes,
incorrect ULP movement, collateral coefficient changes, CPU-kernel disagreement,
loss of production clip bits, changed raw X/Y/Z, unstable repeats or failure to
reproduce the unchanged baseline. The CPU candidate implementation is checked
against its prescribed arithmetic independently of the measured thresholds.

Ignored evidence includes `exports/w-perturb-{x64,x86}.log`,
`w-perturb-build-*.log`, `w-perturb-analysis-{x64,combined}.log` and matrices,
clip data, perturbation metadata, CSV/JSON under `exports/w-perturb/`.
Both builds and twelve focused CTest regressions pass
(`exports/w-perturb-focused-{x64,x86}.log`). The remaining native depth and
real-PMM image gates remain unaccepted.

The subsequent [independent four-term geometry validation](RHI_W_INDEPENDENT_GEOMETRY.md)
retains the fused candidate and matches native thresholds with nonzero object Z.
All four CPU signatures are now distinct; native W output remains unobserved.
