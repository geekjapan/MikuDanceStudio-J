# Intersection rounding on fixed ground repros

This extends [the equal-input clipping controls](RHI_GROUND_EXPLICIT_CLIP.md)
on NVIDIA TITAN Xp, Windows x64/x86, single-sample RGBA8/D24S8. Only rounding
of newly generated CPU clipping intersections varies. Source float4 vertices,
six-plane order, double distance / intersection evaluation, polygon fan anchor,
viewport, center correction, render state and measurement coordinates stay fixed.
Both APIs receive the same final vertex bytes for each control. Production
rendering remains DX9.

## Rounding policies and fixed gates

There are ten policies on each of the canonical and 2-pixel guarded boundaries:

| Policy | Rounding of a newly generated intersection |
| --- | --- |
| `deferred` | Keep double through clipping; nearest float32 at final upload |
| `nearest` | Nearest float32 after every intersection, all four components |
| `zero` | Float32 toward zero after every intersection |
| `down` | Float32 toward negative infinity after every intersection |
| `up` | Float32 toward positive infinity after every intersection |
| `nearest_z` | Nearest float32 only for generated Z |
| `nearest_xyw` | Nearest float32 only for generated X, Y and W |
| `nearest_x` | Nearest float32 only for generated X |
| `nearest_y` | Nearest float32 only for generated Y |
| `nearest_w` | Nearest float32 only for generated W |

Directed rounding first finds the nearest float32, compares it with the double
value and, when required, takes one adjacent float32 toward the requested
direction. It does not change the process floating-point rounding mode or round
distances, coefficients, division or every arithmetic operation to float32.
Untouched original vertices retain their bytes. Changed intersections can
influence the double inputs of subsequent intersections; this propagation is
part of the measured policy.

The standalone portable test adds exact halfway ties, positive / negative
directed rounding, exact-value preservation and component-only generated
intersection checks. Every intersection records its plane, pre-round double
float4 and post-round double float4 in `intersections.csv`; `rounding.csv`
records policy, component mask, guard and intersection count.

The original PMM prefix images are reproduced and repeated three fresh times.
Raw common-clip line images and triangle thresholds must reproduce earlier
evidence. The two `deferred` controls must also reproduce the earlier canonical
and guarded clipping geometry, line images and depth thresholds. Polygon vertex
counts and fan anchor remain fixed. Guarded uploads must be strictly inside
both APIs' clip volumes, including DX11's center correction.

## Line result: no selected rounding policy recovers the raw DX9 coverage

The input remains segment 18, viewport `(565,25,1032,774)`, uniform red without
depth, stencil or blending. The raw common-input control still has the two
coverage differences `(1380,634)` / `(1380,635)`.

All twenty clipped controls agree across APIs, with three fresh repetitions.
Within each boundary, all ten policies produce identical line images, although
their submitted endpoints contain **five distinct byte sequences**. Canonical
images remain identical to the raw DX11 image and differ from the raw DX9 image
at those two pixels. Guarded images also remain identical to the earlier
guarded images. These input differences do not change line coverage on the
fixed repro; none restores the original raw DX9 line.

## Depth result: early Y or W rounding changes subsequent generated Z

The same plane triangle 1 / accessory triangle 1141 and viewport
`(274,25,670,503)` are used. The focus `(922,439)` and independent points
`(921,439)`, `(923,439)` are unchanged. Every triangle is drawn alone with the
constant-depth ruler. Values below are **float32 ruler input bits at the first
non-Less value**, not raw D24 attachment codes.

| Intersection policy | Canonical plane, all points | Guarded plane, all points | Canonical accessory, focus | Guarded accessory, focus |
| --- | ---: | ---: | ---: | ---: |
| `deferred` | 1065073176 | 1065073173 | 1065073178 | 1065073180 |
| `nearest` | 1065073176 | 1065073174 | 1065073178 | 1065073180 |
| `zero` | 1065073176 | 1065073173 | 1065073180 | 1065073180 |
| `down` | 1065073176 | 1065073173 | 1065073180 | 1065073180 |
| `up` | 1065073176 | 1065073173 | 1065073179 | 1065073179 |
| `nearest_z` | 1065073176 | 1065073173 | 1065073178 | 1065073180 |
| `nearest_xyw` | 1065073176 | 1065073174 | 1065073178 | 1065073180 |
| `nearest_x` | 1065073176 | 1065073173 | 1065073178 | 1065073180 |
| `nearest_y` | 1065073176 | 1065073174 | 1065073178 | 1065073180 |
| `nearest_w` | 1065073176 | 1065073174 | 1065073178 | 1065073180 |

All table entries agree across APIs. Accessory right ruler bits are focus plus
two for every policy. Left bits are focus minus two, except canonical `zero`
and `down`: their left bits are 1065073177, focus minus three. Thus directed
rounding can also change the measured neighboring depth slope. All 120 clipped
triangle/point measurements agree across APIs. Each boundary, its preceding
input and its `Equal` observation are verified by three fresh repetitions.

The original plane's raw thresholds remain **1065073177 on DX9 versus
1065073176 on DX11**, at all three points. No tested policy recovers the raw
DX9 plane threshold at those points. Canonical plane thresholds are insensitive
to these policies despite eight distinct uploaded polygons. Guarded plane
thresholds move from 1065073173 to 1065073174 when Y or W intersections are
rounded early, independently. X-only and Z-only nearest policies do not move
them. This is one float32 ruler input step (`2^-24` at this depth).

The final guarded polygons explain why changing generated Y can affect depth:

- `nearest_z` produces exactly the `deferred` polygon bytes on this input.
- `nearest_x` changes polygon vertex 0's final X by `+2^-18`, with unchanged Z.
- `nearest_y` changes vertex 0's final X **and Z** by `+2^-18`; final Y and W
  remain unchanged after upload rounding.
- `nearest_w` changes vertex 0's final Z by `+2^-18`, and vertex 1's X by
  `-0.00000286102294921875`; final W values remain unchanged after upload.

Thus a component rounded at an intermediate intersection need not be the
component that changes in the final uploaded geometry. The saved traces show
the propagation through subsequent double intersections. The observed threshold
change is consistent with these final Z changes; it does not identify how the
driver evaluates its native clipping intersections.

## Evidence and acceptance limits

Each architecture completes 21 line variants and 21 depth variants, including
the raw controls: **126 depth measurements, 4119 ruler queries, 40 recorded line
intersections and 160 triangle intersections**. Line and depth geometry are
audited by an independent Python reconstruction. It verifies rounding traces,
component masks, all final bytes, unchanged topology, guarded interior checks,
prior baselines, pixel tables, monotonic searches, repeated boundaries and
readback colors. Derived analysis records distinct geometry counts, policy
threshold shifts and policies matching the original native plane (none).

Both architectures run the same x64 line archive, x86 depth archive and prior
evidence. All **81 line artifacts and 870 depth artifacts** match by SHA-256.
Seven focused CTests pass per architecture: explicit clipping/rounding,
conversion, shared clip depth, explicit Z, normal precision, ground images and
portable replay validation.

The controls constrain these rounding candidates: changing intersection
rounding changes some absolute depth results but does not explain the original
inter-API discrepancy. No native clipped-vertex capture, driver arithmetic
model or unchanged PMM image acceptance is claimed. The original PMM image gate
remains failed, and no production depth bias or clipping replacement is added.
The [center-stage controls](RHI_GROUND_CENTER_STAGE.md) now retain these inputs,
vary near/far versus side clipping, and move half-pixel correction into the
viewport. Raw line coverage and the original plane depth threshold then match
DX9 on both architectures. The captured real x86 prefix also passes; the x64
prefix retains small model-material color deltas.

## Reproduction

Build `rhi_d3d9_replay_conversion_test` and `explicit_clip_geometry_test`; use
fresh output folders. The third input is the previous accepted explicit-clip
evidence, which serves as the unchanged deferred-policy gate.

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-clip-rounding-lines exports/ground-rhi-prefix-x64 exports/ground-endpoint-final-x64 exports/ground-explicit-line-final-x64 exports/new-clip-rounding-line
python tools/analyze_ground_explicit_clip.py lines exports/ground-rhi-prefix-x64 exports/ground-endpoint-final-x64 exports/new-clip-rounding-line --rounding-reference exports/ground-explicit-line-final-x64
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-clip-rounding-depth exports/ground-rhi-prefix-x86 exports/ground-depth-threshold-x64 exports/ground-explicit-depth-final-x64 exports/new-clip-rounding-depth
python tools/analyze_ground_explicit_clip.py depth exports/ground-rhi-prefix-x86 exports/ground-depth-threshold-x64 exports/new-clip-rounding-depth --rounding-reference exports/ground-explicit-depth-final-x64
```

Repeat using the x86 executable and identical inputs. Private captures remain
ignored under:

- `exports/ground-clip-rounding-line-final-{x64,x86}/`
- `exports/ground-clip-rounding-depth-final-{x64,x86}/`
- `exports/ground-clip-rounding-shared-input-architecture.json`
- `exports/ground-clip-rounding-regression-{x64,x86}.log`

Initial seven-policy runs remain in separate folders. The final ten-policy runs
above are the completed evidence; earlier partial runs are not used as its gate.
