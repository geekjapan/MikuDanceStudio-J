# Equal-input explicit clipping of ground geometry

This continues [the endpoint and depth-threshold measurements](RHI_GROUND_ENDPOINT_DEPTH.md)
on the same saved PMM inputs, NVIDIA TITAN Xp, single-sample RGBA8/D24S8.
The original application images and the original raw-clip diagnostic failures
are reproduced before any geometry changes. Both baseline images are verified
by three fresh repetitions. Production rendering remains DX9.

The test uses CPU clipping to submit the **same owned float4 vertices** to
programmable DX9 and DX11. It bypasses original vertex transformations and
retains the existing dynamic DX11 pixel-center correction. It does not capture
DX9's native clipped vertices or emulate a driver's clipping precision.

## Shared geometry and clipping controls

`tests/explicit_clip_geometry.hpp` clips lines and polygons in homogeneous
coordinates. Plane order is fixed:

1. `X + limitX * W >= 0`
2. `-X + limitX * W >= 0`
3. `Y + limitY * W >= 0`
4. `-Y + limitY * W >= 0`
5. `Z >= 0`
6. `W - Z >= 0`

For canonical clipping, both limits are 1. For guarded controls,
`limitX = 1 - 2 * guardPixels / viewportWidth`, with the analogous Y formula.
Intersections use double intermediates through all six planes and round to
float32 only when the final vertex list is produced. Polygons use a triangle
fan; an additional control changes the fan anchor while preserving the polygon.
Input, polygon and submitted triangle/line bytes are saved independently.

Canonical boundary vertices can still require clipping after DX11's center
correction. The 2-pixel and 8-pixel guarded controls instead assert that every
submitted vertex is strictly inside both APIs' clip volumes, including corrected
DX11 XY coordinates. All have positive W. Thus these guarded controls remove
native frustum intersections for the submitted primitives. They also trim the
edge of the original geometry and are diagnostic inputs, not replacements for
the real draw.

`SharedClipDepthRenderer` now accepts triangle lists rather than only one
triangle. DX9 submits the full list; DX11 uploads complete triangles in batches
of at most six vertices using its existing buffer. Update padding preserves the
buffer's full read extent. The constant-depth ruler and earlier three-vertex
controls retain their behavior.

## Line coverage results

The input remains segment 18 in the x64 viewport `(565,25,1032,774)`.
Its first raw endpoint has negative W. Depth, stencil, blending and color
interpolation are disabled. Each control is rendered once and then repeated
three fresh times on each API.

| Submitted geometry | DX9 vs DX11 differing pixels | DX9 changed from raw | DX11 changed from raw |
| --- | ---: | ---: | ---: |
| Raw endpoints | 2 | 0 | 0 |
| Canonical clipped line | 0 | 2 | 0 |
| Canonical, reversed endpoints | 0 | 2 | 0 |
| Guard 2 | 0 | 3 | 1 |
| Guard 2, reversed | 0 | 4 | 2 |
| Guard 8 | 0 | 9 | 11 |
| Guard 8, reversed | 0 | 10 | 12 |

The raw failure is still `(1380,634)` / `(1380,635)`, with the same images as
the earlier common-clip control. The canonical result equals the earlier DX11
image; DX9 changes those two pixels. All six explicitly clipped controls agree
between APIs. Reversing guarded endpoints changes one endpoint pixel within
each API, but both APIs make the same change; reversal invariance is not an
acceptance assumption.

This establishes that the observed two-pixel mismatch is absent on these
shared visible segments, including segments that require no native clipping.
It does not prove an exact general line rasterization rule or identify a
particular native intersection rounding operation. Pixel comparisons remain
restricted to the recorded viewport.

## Triangle depth results

The two triangles remain ground-plane triangle 1 of draw 2 and accessory
triangle 1141 of draw 6 in the x86 viewport `(274,25,670,503)`. Each is drawn
alone and measured by the same independent constant-depth ruler under `Less`
and `Equal`. The focus `(922,439)` and validation coordinates `(921,439)` and
`(923,439)` are unchanged; no points are selected by agreement.

The plane becomes a five-vertex polygon / three triangles. The clipped
accessory remains a three-vertex polygon, with changed boundary intersections.
All three original accessory vertices have positive W, but this alone does not
place the original triangle wholly inside the frustum.

The entries below are **float32 ruler input bits at the first non-Less value**,
not raw D24 attachment codes. At each boundary, `Equal` must pass.

| Geometry | Plane, all three points: DX9 / DX11 | Accessory focus / left / right: both APIs |
| --- | --- | --- |
| Raw | 1065073177 / 1065073176 | 1065073177 / 1065073175 / 1065073179 |
| Canonical | 1065073176 / 1065073176 | 1065073178 / 1065073176 / 1065073180 |
| Guard 2 | 1065073173 / 1065073173 | 1065073180 / 1065073178 / 1065073182 |
| Guard 2, fan anchor 1 | 1065073173 / 1065073173 | 1065073180 / 1065073178 / 1065073182 |
| Guard 8 | 1065073176 / 1065073176 | 1065073177 / 1065073175 / 1065073179 |

There are 30 measurements and 1003 ruler queries per architecture, including
three fresh repetitions of `Less(threshold-1)`, `Less(threshold)` and
`Equal(threshold)` for every distinct measured boundary. All 24 explicitly
clipped measurements agree across APIs. Changing the guard-2 fan anchor also
preserves these thresholds.

The original one-step plane discrepancy survives the raw rerun and disappears
when both APIs receive the shared clipped geometry. The absolute thresholds
change with clipping boundaries. Even with double intersections, rounding the
new vertices to float32 can change the subsequent depth plane. Therefore this
does not prove that CPU clipping preserves the original native depth plane, or
that every original coplanar comparison has passed.

## Conclusions and acceptance boundary

For these two failures, changing from common **unclipped** vertices to common
**visible** geometry removes the inter-API discrepancy. Clipping and the
geometry it produces influence the outcome. The strictly interior controls
give no evidence of a remaining API discrepancy at these fixed line pixels
and depth coordinates. General rasterization and depth quantization differences
remain possible on other inputs.

The original PMM image gate remains failed. No production clipping, matrix,
depth offset, comparison tolerance or backend switch is introduced. The
[intersection rounding controls](RHI_GROUND_CLIP_ROUNDING.md) now vary only
newly generated intersections on these same inputs. Early Y or W rounding moves
the guarded plane threshold, while no selected policy recovers the original
DX9 plane threshold or raw line coverage. A native precision model remains
unidentified.

## Audit, regression and reproduction

`tools/analyze_ground_explicit_clip.py` independently reconstructs clipping and
fan geometry from the saved source float4 bytes. It verifies every uploaded
geometry byte, guarded interior checks, raw images / thresholds against earlier
evidence, application baselines, image hashes, per-pixel logs, monotonic ruler
queries, boundary repetitions and saved 5x5 readback classifications.

Both executables consume the **same x64 line archive and same x86 depth
archive**, with the same previous endpoint/threshold evidence. All **37 line
artifacts and 226 depth artifacts** match by SHA-256 across architectures,
including geometry, images, queries, thresholds and summaries.

Seven focused CTests pass on each architecture: portable explicit clipping,
native-to-portable conversion, shared clip depth, explicit Z, normal precision,
generated ground images and portable model replay validation. The portable
clipping test covers rejection, near/far intersections, polygon area, fan
anchors and strict interior checks. Its registration is platform-independent;
this turn's measured GPU and CTest results are Windows x64/x86.

After building `rhi_d3d9_replay_conversion_test` and `explicit_clip_geometry_test`,
run with fresh output folders:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-explicit-lines exports/ground-rhi-prefix-x64 exports/ground-endpoint-final-x64 exports/new-explicit-line
python tools/analyze_ground_explicit_clip.py lines exports/ground-rhi-prefix-x64 exports/ground-endpoint-final-x64 exports/new-explicit-line
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-explicit-depth exports/ground-rhi-prefix-x86 exports/ground-depth-threshold-x64 exports/new-explicit-depth
python tools/analyze_ground_explicit_clip.py depth exports/ground-rhi-prefix-x86 exports/ground-depth-threshold-x64 exports/new-explicit-depth
```

Repeat using the x86 executable and the same inputs. Private PMM captures and
measurement outputs remain ignored:

- `exports/ground-explicit-line-final-{x64,x86}/`
- `exports/ground-explicit-depth-final-{x64,x86}/`
- `exports/ground-explicit-shared-input-architecture.json`
- `exports/ground-explicit-regression-{x64,x86}.log`
