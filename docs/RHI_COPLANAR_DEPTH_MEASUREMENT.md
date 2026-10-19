# Coplanar surface depth interpolation / quantization measurements

The [accessory isolation](RHI_ACCESSORY_DRAW2_ISOLATION.md) identified 7 x64
and 8 x86 high-delta pixels whose color differs because a different coplanar
surface wins. This native measurement removes shading differences with solid
red/green IDs and uses attachment comparisons to measure effective depth.
The application, shader contracts, depth rules and default renderer are unchanged.

## Experiment

The original immutable draw-2 archives and later reference viewports are used,
as in the previous isolation. This is a native experiment on saved geometry,
not a new live PMM capture. Both builds create native DX9 HAL devices repeatedly;
DX11 Hardware is NVIDIA TITAN Xp. x64 also runs the same controls on DX11 WARP
(Microsoft Basic Render Driver). All targets are single-sample RGBA8/D24S8,
with depth bias zero and depth clear 1.

Geometry and world/view/projection matrices remain original. The position /
normal / UV vertex layout and transform path are retained. Lighting is replaced
by constant emissive red for the small face and green for the long face; blending,
alpha test, stencil and culling are disabled. No texture is bound. These changes
are diagnostic controls, not changes to application rendering.

Five zero-based triangle pairs are compared: 134/226, 135/227, 146/226,
147/227 and 135/226. Each pair is tested in both draw orders with `LessEqual`,
strict `Less` and depth disabled; the original-depth pairs are repeated three
times. Cyclic vertex permutations preserve winding and geometry. Depth-range
controls additionally use `[0,0.5]`, `[0,0.125]` and `[0.5,1]`.

For every differing pixel in the original-order Hardware pair images, each
triangle is drawn alone in red and must cover that pixel identically in both
backends. A full-viewport green quad then supplies a known constant reference
depth, scanning nine neighboring float32 inputs. `Equal` and `Less` identify
a unique monotone threshold independently for each triangle and backend.
Double CPU projection only centers the scan; it is not treated as GPU truth.

Near depth 0.9914, adjacent float32 values are separated by `2^-24`, about
`5.96046448e-8`. The D24 code spacing is `1/(2^24-1)`, about `5.96046483e-8`.
They are close but different. The saved float/bit patterns are **reference
inputs**, not raw native attachment codes. This method measures effective
comparison thresholds; it does not read pre-quantization depth or raw D24 bits.

## Results

| Configuration | Pair / range comparisons | Nonzero pair images | Reference probes | Different probe results | Constant-reference calibration |
| --- | --- | --- | --- | --- | --- |
| x64 Hardware | 100 | 33 | 252 | 25 | 15 exact images / expected relations |
| x86 Hardware | 100 | 46 | 288 | 31 | 15 exact images / expected relations |
| x64 WARP | 100 | 17 | 108 | 22 | 15 exact images / expected relations |

Pair counts include repeat, cyclic-order and range controls; they are not
counts of unique triangles. Probe counts include both `Equal` and `Less` at
nine inputs per measured triangle/pixel. The diagnostics return **32** because
original-depth pair images differ. This is not a successful scene image gate.
Reference analysis succeeds only when threshold monotonicity, equality and
calibration checks pass.

Across Hardware, all 15 original high-delta coordinates are measured for
both faces (30 thresholds). The small-face DX9 threshold is **1-3 reference
float steps smaller** than DX11. Long-face thresholds agree at all 15 points.
Constant reference planes agree across backends, so the ruler itself does not
show the captured triangle-dependent discrepancy.

| Hardware capture | Small-face DX9 minus DX11 steps | Long-face DX9 minus DX11 steps | DX11 pair tied | DX11 small face farther |
| --- | --- | --- | --- | --- |
| x64, 7 points | -1 at 3; -2 at 4 | 0 at all 7 | 4 | 3 |
| x86, 8 points | -1 at 2; -2 at 5; -3 at 1 | 0 at all 8 | 5 | 3 |

At every measured point DX9's small face is closer than the long face. DX11's
small face is equal at 9 points and one reference step farther at the other 6.
These independently measured threshold relations predict the red/green
two-face result at every point in both backends: **30 verified surface choices**.
This explains the earlier observation that reversal or strict `Less` fixes
only 4/7 and 5/8 original high-delta pixels: it changes the equal-depth winner,
but does not repair the six reversed-depth relations. It also introduces
other image differences, so neither is a production fix.

The original repeats match exactly in each backend. Depth-disabled pair images
all agree, and individual ID-colored triangles have identical coverage. Cyclic
permutations produce zero changed pixels relative to each backend's original
pair image. These observations constrain coverage, lighting and submission
instability at the measured coordinates; they do not prove all internal depth
coefficients are invariant.

Compressing the depth range changes the mismatches:

| Range | x64 nonzero images / sum of differing pixels | x86 nonzero images / sum of differing pixels |
| --- | --- | --- |
| [0,0.5] | 4 / 11 | 5 / 9 |
| [0,0.125] | 1 / 1 | 1 / 1 |
| [0.5,1] | 4 / 13 | 4 / 7 |

Each row has 10 images: five pairs in both orders. Compression brings the
small plane differences into fewer depth-code boundaries, but still does not
make every image equal. It supports the role of depth representation and
quantization in surface selection; it does not identify whether the initial
error arises in vertex `Z/W`, raster depth-plane setup or interpolation.

WARP is separate evidence: the original x64 135/227 mismatch disappears there,
while 147/227 still differs. At its three measured points the small-face native
threshold is 2-3 steps smaller than WARP and the long face is 1 step smaller.
It cannot replace the Hardware baseline or justify a universal correction.
x86 WARP was not measured in this depth experiment.

## Reproduce and evidence

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --coplanar-depth-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
python tools/analyze_coplanar_depth.py exports/shadow-prefix-dx11-x64/coplanar-depth-hardware/measurements.csv
```

Use the corresponding x86 paths, or `--coplanar-depth-warp` and the WARP
directory. These tools need the private archives; the assets are not bundled
in the repository and the diagnostic is not an automatically skipped CTest.

Evidence remains ignored:

- `exports/coplanar-depth-{hardware-x64,hardware-x86,warp-x64}.log`.
- `measurements.csv` / `measurements.json` under each reference capture's
  `coplanar-depth-{hardware,warp}/` directory.
- Original-order native/DX11 pair RGBA files in the same directories.
- `exports/coplanar-analysis-{hardware-x64,hardware-x86,warp-x64}.log`.

Both test builds pass. Eight focused CTests pass across x64/x86 (conversion,
resource/version validation and viewport Hardware/WARP), recorded in
`exports/coplanar-focused-{x64,x86}.log`. Those checks do not override the
nonzero native pair images above.

The subsequent [transform/depth-plane isolation](RHI_DEPTH_TRANSFORM_ISOLATION.md)
uses these measured coordinates and independent validation coordinates.
Shared DX11 camera-space input preserves production DX11 clip bits and makes
the measured backend depth comparisons exact, while changing the original
DX9 image. Native transform arithmetic remains to be identified.
Any transform capture must demonstrate equivalence to the native hardware
fixed-function path; CPU projection or software `ProcessVertices` is not
automatically that reference. Delta-1 color differences remain separate.
No arbitrary depth bias, global `Less` switch or renderer activation follows
from this measurement.
