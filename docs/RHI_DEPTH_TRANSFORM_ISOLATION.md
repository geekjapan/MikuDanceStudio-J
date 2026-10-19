# Vertex transform versus triangle depth setup

This continues [coplanar depth measurement](RHI_COPLANAR_DEPTH_MEASUREMENT.md)
using the same archived accessory draw 2, six triangles and five ID-colored
triangle pairs. It changes diagnostic input only. The application still uses
native DX9; full-prefix DX11 image acceptance remains blocked.

## Isolation and equivalence checks

The decisive control exports camera-space vertices from the production DX11
vertex shader, then gives those identical float32 vertices to both backends.
World and view become identity. The original projection matrix, homogeneous
W, viewport, depth attachment and comparison rules remain in use. This avoids
the representation change of an NDC input with W=1.

The stream-output fixture uses the generated production model shader source,
`vs_5_0` and `D3DCOMPILE_IEEE_STRICTNESS`. It first captures the unmodified
shader's clip XYZW, including the existing DX9 pixel-center compensation.
A second shader additionally exports its intermediate camera-space value.
Two mandatory bitwise checks cover **all 13,894 vertices** in each archive:

1. Adding the camera output must preserve every original clip-output bit.
2. Feeding captured camera XYZ through identity world/view and the original
   projection must preserve every original clip-output bit again.

Camera W must equal 1 before storing XYZ in the original 32-byte vertex layout.
Neither check substitutes a CPU projection for a hardware observation.
The captured observation is **DX11**, not DX9 fixed-function output.

The existing pair experiments then exercise LessEqual, strict Less, reversed
order, three repeats, depth disabled, cyclic vertex order and three depth
ranges. Equal/Less scans use all original mismatch coordinates even when the
new pair image is exact. Two additional x64 coordinates and one additional
x86 coordinate are selected from common triangle coverage, independently of
the mismatch values. Other pairs have no additional common covered pixel.
Reference-plane calibration and surface-choice predictions remain mandatory.

## Hardware results

Actual DX9 devices created and completed these experiments on NVIDIA TITAN Xp.
Single sampling and D24S8 are used throughout; this is not an MSAA acceptance.

| Control | x64 | x86 |
| --- | --- | --- |
| Original-input pair image comparisons with a mismatch | 33 / 100 | 46 / 100 |
| Original-input differing reference-probe results | 25 / 252 | 31 / 288 |
| Shared DX11 camera-input pair image comparisons with a mismatch | **0 / 100** | **0 / 100** |
| Shared camera-input differing reference-probe results | **0 / 324** | **0 / 324** |
| Shared camera-input differing measured thresholds | **0 / 18** | **0 / 18** |
| Constant-reference calibration comparisons | 15 exact | 15 exact |
| Verified surface-choice predictions | 18 | 18 |

The original-input experiment was rerun in the same session after the camera
experiment: its mismatches persist. Its diagnostic returns 32; the shared
camera diagnostic returns 0. Those outcomes refer to their respective inputs.

The following compares the five original-order, original-range pair images
against the corresponding unmodified input in each backend:

| Triangle pair | x64 changed DX9 pixels | x86 changed DX9 pixels | Changed DX11 pixels, either architecture |
| --- | --- | --- | --- |
| 134 / 226 | 0 | 4 | 0 |
| 135 / 227 | 4 | 0 | 0 |
| 146 / 226 | 0 | 1 | 0 |
| 147 / 227 | 3 | 0 | 0 |
| 135 / 226 | 0 | 3 | 0 |

Thus the camera-input control preserves these original DX11 images and
changes the original DX9 surface choices at the earlier discrepant pixels.
It is not an equivalent replacement for native DX9 rendering.

An earlier control used production DX11 clip XYZW divided by W, compensating
for the pixel-center offset before supplying shared NDC vertices. It also
produced 100 exact pair images and 324 exact probes per architecture. Because
it changes homogeneous W and interpolation representation, it alone cannot
separate the stages. The camera-input control above is the stronger evidence.
An explicit CPU float multiply/add camera control on x64 also produced exact
backend comparisons, but CPU arithmetic is not a capture of DX9 output.

## Interpretation and remaining limits

With shared camera input and the original projection, there is no observed
remaining backend discrepancy in the measured depth-plane/attachment tests.
Keeping production DX11 clip bits fixed while bypassing DX9 world/view
arithmetic changes the native image. This makes the fixed-function transform
path, including driver arithmetic or matrix-combination behavior, the next
priority rather than a universal raster-depth correction.

This is a constrained experiment, not direct proof of the DX9 intermediate
Z/W values. Identity matrices may change driver shader generation or how it
combines transforms; the precise native multiplication and rounding sequence
is still unknown. The experiment does not rule out triangle setup differences
for other inputs, drivers or sample counts. No raw D24 bits are read back.

The next useful measurement is an independently validated observation of DX9
post-transform values or a transform arithmetic control that preserves the
native image. Software `ProcessVertices`, CPU double projection and assumed
matrix-product order cannot be labeled that reference without validation.
Color delta-1 differences and 8x MSAA remain independent acceptance items.
No depth bias, global comparison-rule change or renderer switch is justified.

## Reproduce and evidence

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --transform-depth-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64 6
python tools/analyze_coplanar_depth.py exports/shadow-prefix-dx11-x64/coplanar-depth-hardware-dx11_so_camera/measurements.csv
```

Use corresponding x86 paths. Other diagnostic modes are 1: CPU float camera,
2: CPU double camera, 3: CPU float NDC, 4: CPU double NDC and 5: DX11 stream-output
NDC. Mode 6 is the verified camera-output control. These private-archive
diagnostics are explicitly invoked and are not silently skipped CTests.

Ignored evidence includes:

- `exports/transform-depth-dx11-camera-{x64,x86}.log` and analysis logs.
- `exports/transform-depth-original-recheck-{x64,x86}.log`.
- `coplanar-depth-hardware-dx11_so_camera/measurements.csv` and `.json`,
  original-order pair images, baked vertex bytes and production clip XYZW.
- `exports/transform-depth-dx11-so-{x64,x86}.log` for the NDC control.
- `exports/transform-focused-{x64,x86}.log` for focused CTest regressions.

Both diagnostic builds pass. Six focused CTests per architecture cover CPU
conversion, resource/version validation, Hardware/WARP native conversion and
Hardware/WARP viewport behavior; all twelve pass. They do not override the
original-input image failures.

No private model or PMM assets are added to the repository.

The subsequent [matrix combination and rounding audit](RHI_DEPTH_MATRIX_ROUNDING.md)
tests explicit precombined coefficients. It preserves the measured original
DX9 outcomes, but leaves backend differences and cannot uniquely determine
the native rounding rule from the sparse matrices in this archive.
