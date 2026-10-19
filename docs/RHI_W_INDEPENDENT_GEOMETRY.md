# Independent geometry with four active W terms

This validates the fixed fused-W hypothesis from
[coefficient perturbation](RHI_W_DOT_PERTURBATION.md) on independent geometry.
No model, PMM or other private asset is needed. The application and production
shaders are unchanged. DX9 HAL hardware vertex processing and DX11 Hardware
run on NVIDIA TITAN Xp with a 64x64 single-sample target and D24S8.

## Inputs fixed before GPU measurement

`tools/generate_w_geometry.py` uses seed 20261004, distinct from the earlier
case-10 fixture seed. It generates twelve independent triangles and homogeneous
position matrices. Every vertex has nonzero X, Y and Z and object W=1; all
four coefficients of the clip-W column are nonzero. Thus every W dot product
has four nonzero products. Signs of the first three coefficients vary, and
their contributions can partially cancel the positive translation term.

Clip X and Y are simple 3.5-scaled object coordinates. Clip Z is exactly 3,
so the new nonzero object Z affects W while Z evaluation cannot introduce a
second dot-arithmetic discrepancy. These are custom homogeneous transforms
chosen to isolate W, not conventional PMM perspective camera matrices. Their
depth still varies over the screen because W varies.

Selection uses only CPU candidate-bit discrimination and conservative visible
depth/common coverage. Every case has at least three distinct CPU W signatures.
Sequential accumulation must differ from paired and fused signatures. No GPU
result selects, tunes or regenerates any geometry.

Six cases are assigned to calibration and six to holdout before measurement.
Coordinates (36,46), (20,42), and the additional independent point (28,44) are
fixed for every case. The fused candidate is retained from the preceding
experiment and is **not selected again** using these data. The binary fixture,
JSON manifest and saved measured input must agree byte for byte.

## Controls and checks

The same nine paths from the preceding experiment are retained: original
native/production DX11, shared clip, full native `dp4`, ordered native `mul/add`,
W-only native `dp4`, and CPU sequential/double/paired/fused W inputs. CPU inputs
hold captured X/Y/Z fixed and replace only W. The fused kernel is the original
left-to-right `std::fma` sequence starting at zero; no new rounding rule is fitted.

Shared input must retain every production DX11 final clip bit. Native instruction
controls retain the same DX11 clip input. Shader disassembly/count checks prove
the diagnostic bytecode's `dp4` or separate `mul/add` structure. Each CPU candidate
is checked independently against its prescribed arithmetic and the generator
manifest, including all four active terms.

Less/Equal reference-plane searches verify both bracket endpoints, the unique
boundary and preceding Less input; each boundary is reissued three times by
fresh native/DX11 draws. Common coverage at all measured points follows from
the required red/green endpoint relations. The target, sample count, viewport
and constant-reference ruler remain fixed. Reference bits are float32 ruler
inputs, not captured native W or raw D24 attachment bits.

There are **324** threshold pairs per architecture: twelve geometries, nine
paths and three coordinates. The analyzer rejects missing/duplicate cases,
split changes, binary/manifest disagreement, inactive terms, CPU-kernel
disagreement, loss of production clip bits or unstable repeats.

## Results

Both architectures have identical results. All **648 corresponding backend
thresholds** agree across x64/x86, and repeated boundaries remain stable.
Captured production W ranges from approximately 3.2980 to 4.8783.

| Path | Matches to original native, calibration | Matches, holdout | Backend matches across 36 coordinates |
| --- | --- | --- | --- |
| Shared production clip | 11 / 18 | 14 / 18 | 36 / 36 |
| Native full `dp4` | **18 / 18** | **18 / 18** | 25 / 36 |
| Native ordered `mul/add` | 18 / 18 | 16 / 18 | 27 / 36 |
| Native W-only `dp4` | **18 / 18** | **18 / 18** | 25 / 36 |
| CPU sequential W | 11 / 18 | 14 / 18 | 36 / 36 |
| CPU double W | 16 / 18 | 15 / 18 | 36 / 36 |
| CPU paired W | 10 / 18 | 10 / 18 | 36 / 36 |
| CPU fused W | **18 / 18** | **18 / 18** | **36 / 36** |

The unchanged fused-W hypothesis matches every native coordinate, including
all eighteen holdout observations and the additional independent pixel.
Full native dot and W-only native dot also retain every native threshold.
Sequential, double and paired CPU hypotheses all have mismatches.

Original production DX11 differs from native at **11/36** coordinates. Its
shared clip input preserves the DX11 results and does not reproduce those
eleven native values. Fused CPU W input matches native on both shared-input
backends. All four CPU paths match between backends on their respective shared
inputs; this is narrower than native rendering equivalence.

Unlike the prior zero-Z experiment, all four CPU W signatures are distinct.
Of 36 vertices, sequential W matches production DX11 at 36/36 bits, double at
22/36, paired at 19/36 and fused at 23/36. The thirteen changed fused W values
are observations of the CPU candidate relative to captured DX11, not native
W-output observations.

Each full diagnostic returns **32**, with 42 backend mismatches across its
324 pairs: eleven original, eleven full-dot, eleven W-only-dot and nine
ordered-operation observations. No tolerated delta changes this image/depth
acceptance result. The matching fused hypothesis is reported separately.

## Interpretation and limits

The earlier fused-like W explanation survives independent nonzero-Z geometry
and active four-term dot products. It is no longer explained by sequential
and paired arithmetic collapsing to the same zero-Z signature. This strengthens
the local arithmetic hypothesis on the tested driver.

The ordered GPU shader is also informative: its bytecode contains four `mul`
and three `add` instructions, yet it matches 34 native thresholds versus 25
for CPU separate product/add. That bytecode cannot be assumed to specify the
exact hardware rounding sequence after driver translation. Fusion or other
evaluation behavior remains possible; it is not directly observed here.

Matching quantized thresholds still does not prove native W bits equal the
CPU fused bits or uniquely identify the driver's arithmetic. This experiment
isolates a custom constant-Z transform. It does not accept general perspective
PMM transforms, model shading/normal transforms, full-scene history or MSAA.
No production FMA policy, matrix change, depth bias or renderer activation follows.

The [test-only DX11 shader validation](RHI_DX11_W_CANDIDATE.md) now checks actual
GPU W bits against the fixed CPU hypothesis and retests both these synthetic
inputs and archived PMM batches. Synthetic thresholds match; real PMM images
still differ. That local improvement does not substitute for native acceptance.

## Reproduce and evidence

```powershell
python tools/generate_w_geometry.py exports/w-geometry/fixtures.bin
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --w-independent-geometry exports/w-geometry/fixtures.bin exports/w-geometry/x64
./build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --w-independent-geometry exports/w-geometry/fixtures.bin exports/w-geometry/x86
python tools/analyze_w_geometry.py exports/w-geometry/x64 exports/w-geometry/x86
```

Generated fixture bytes/JSON, measured matrices/object data, clip captures,
threshold CSV and analysis JSON remain ignored under `exports/w-geometry/`.
Logs are `exports/w-geometry-{x64,x86}.log`, `w-geometry-build-*.log` and
`w-geometry-analysis-{x64,combined}.log`.

Both builds and twelve focused CTest regressions pass, recorded in
`exports/w-geometry-focused-{x64,x86}.log`. Those regressions do not override
the original native depth mismatches or real-PMM image gates.
