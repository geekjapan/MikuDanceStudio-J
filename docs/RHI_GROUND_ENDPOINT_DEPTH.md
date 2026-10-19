# Ground endpoints and triangle depth thresholds

This extends [the independent line/depth repros](RHI_GROUND_HISTORY_ISOLATION.md)
without changing production rendering or arithmetic. Both tests use the original
owned snapshots and the diagnostic normal/material candidate on NVIDIA TITAN Xp,
single-sample RGBA8/D24S8. Native and candidate baselines still match their saved
application/candidate images before any controlled input changes.

## Line endpoints and equal-input clipping/coverage

Segment 18 is captured as a compact two-vertex line. The DX11 vertex shader's
GPU stream output records positions both before and after pixel-center
correction. The test uses the candidate's combined matrix and explicit Z/W
evaluation, with the actual PositionColor layout. Three fresh captures preserve
all output bits. The test helper now supports both 16-byte PositionColor and
32-byte PositionNormalUv observations; shader-bytecode cache keys distinguish
the two variants.

| Endpoint | Pre-center clip X,Y,Z,W | Screen X,Y from corrected GPU output |
| --- | --- | --- |
| (20,0.1,-50) | 37.351234436, -38.915973663, -12.984577179, -11.984447479 | -527.187377930, -844.668823242 |
| (20,0.1,50) | 38.963737488, -38.155216217, 87.013839722, 88.012969971 | 1309.435546875, 579.771545410 |

The first endpoint has negative W and lies behind the camera. These are
**unclipped** endpoint observations; their connecting segment requires native
clipping before visible rasterization. They are not the visible clipped line's
final endpoints.

DX9 `ProcessVertices` is investigated separately as an API observation. Its
hardware-VP probe raises `0xC0000005` in `d3d9.dll`, including with an explicit
output declaration, on both architectures. It runs in an isolated child
process, with the exit status retained; the failed output is never consumed.
The software-VP variant returns successfully. Compared with the GPU candidate's
derived screen values, it differs by:

| Endpoint | Software minus candidate X,Y,Z,RHW |
| --- | --- |
| First | +0.0001220703125, 0, -0.00000011920928955, 0 |
| Second | 0, -0.00006103515625, 0, 0 |

Software processing is **not** treated as actual hardware fixed-function draw
output. The failed hardware endpoint probe prevents that direct claim.

The decisive control feeds the **same recorded raw float4 clip endpoints** to
programmable DX9 and DX11 passthrough shaders. DX11 retains the existing dynamic
pixel-center correction; depth, stencil and blending are disabled and the line
is uniform red. The original matrices and vertex position evaluation are
bypassed on both sides.

The same two pixels still exchange coverage: `(1380,634)` and `(1380,635)`.
Both common-input images match their respective uniform original-transform
images byte-for-byte within the known viewport. Repeated common-input images
also agree. This proves original vertex transforms are **unnecessary** for the
coverage failure. Remaining stages include clipping, viewport/pixel-center
mapping and line rasterization. It does not yet select one native raster rule
or exclude pixel-center correction rounding.

Only the recorded viewport is compared. DX9's viewport-local clear leaves
outside pixels unspecified; full-target differences outside it are not accepted
as evidence of line behavior. Earlier partial endpoint runs remain preserved
separately and are not the final accepted diagnostic evidence.

## Independent depth ruler

The original compact pair is retained: plane triangle 1 of draw 2, accessory
triangle 1141 of draw 6. Each triangle is measured **alone** after clear, using
uniform diagnostic color with original position layout/matrices. An independent
full-viewport, constant-depth green ruler is submitted second, without depth
writes, under `Less` or `Equal`.

A binary search finds the first float32 ruler input that no longer passes
`Less`; `Equal` must pass at that input. Every measured boundary is verified by
fresh `Less(threshold-1)`, `Less(threshold)` and `Equal(threshold)` draws, each
repeated three times. Cached search results only avoid duplicate search renders;
they never replace the fresh boundary checks.

The first point is the original failure `(922,439)`. Two neighboring validation
points, `(921,439)` and `(923,439)`, are selected by common triangle coverage
before threshold searches; depth agreement is not a selection criterion.

| Triangle / point | DX9 first non-Less ruler bits | DX11 first non-Less ruler bits |
| --- | --- | --- |
| Plane, all three points | 1065073177 | 1065073176 |
| Accessory, (922,439) | 1065073177 | 1065073177 |
| Accessory, (921,439) | 1065073175 | 1065073175 |
| Accessory, (923,439) | 1065073179 | 1065073179 |

At the original focus, the plane ruler thresholds correspond to
`0.9833083748817444` (DX9) and `0.9833083152770996` (DX11), one float32 input
step (`2^-24`) apart. The accessory threshold agrees across APIs and equals
the DX9 plane threshold. This explains the earlier pair control: the native
accessory compares equal to its plane, while the candidate accessory compares
farther than its plane.

These bits identify **ruler input values**, not raw D24 attachment codes. The
test validates its independent constant-depth ruler with 15 additional
`Less`/`Equal`/`LessEqual` controls around 0.97. This does not equate all float32
spacing with D24 quantization or claim direct depth attachment readback.

## Same clip coordinates still reproduce the plane threshold difference

The second measurement path bypasses original vertex transformations on both
APIs and feeds identical GPU-recorded float4 clip vertices to programmable
passthrough shaders. Every threshold, for both triangles and all three points,
matches its corresponding original-transform threshold exactly.

Thus the plane threshold discrepancy survives identical raw vertex positions;
original matrix combination and Z/W dot evaluation are unnecessary for this
failure. The plane includes a negative-W vertex, whereas all three accessory
vertices have positive W. Clipping, center/viewport mapping, depth plane
construction/evaluation and depth quantization remain candidates. The current
measurement alone does not distinguish them.

Both measurement paths are diagnostic subsets: changing shading/state makes
depth comparison observable, and common-input controls use programmable DX9.
They do not certify unchanged real PMM rendering or enable a production backend.

## Stability, audit and tests

There are **12 threshold measurements, 454 native/DX11 ruler queries and 15
constant-ruler calibration controls** per executable. Small 5x5 BGRA readback
regions retain each freshly verified boundary and its independently selected
pixel. The audit checks monotonic search observations, threshold brackets,
fresh repetition counts, image classifications, calibration and source geometry.
Endpoint CSV float values/bits are verified against saved GPU/API buffers;
the compact line is checked against original indexed endpoints.

The same x64 line archive and the same x86 depth archive run in both executable
architectures. All **19 endpoint artifacts** and **114 depth artifacts** have
matching SHA-256 hashes, including API probe statuses, clip bytes, images,
threshold/query tables and summaries. The six focused CTests pass on each
architecture: conversion, shared clip depth, explicit Z, normal precision,
generated ground images and portable stream validation.

Final evidence stays in ignored folders:

- `exports/ground-endpoint-final-{x64,x86}/`
- `exports/ground-depth-threshold-{x64,x86}/`
- `exports/ground-measure-shared-input-architecture.json`
- `exports/ground-measure-regression-{x64,x86}.log`

Build `rhi_d3d9_replay_conversion_test`, then run with fresh output paths:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-endpoints exports/ground-rhi-prefix-x64 exports/new-ground-endpoints
python tools/analyze_ground_endpoint_depth.py endpoints exports/ground-rhi-prefix-x64 exports/new-ground-endpoints
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-depth-thresholds exports/ground-rhi-prefix-x86 exports/new-ground-thresholds
python tools/analyze_ground_endpoint_depth.py depth exports/ground-rhi-prefix-x86 exports/new-ground-thresholds
```

The [explicit clipping controls](RHI_GROUND_EXPLICIT_CLIP.md) now supply shared
visible geometry to both APIs, retaining the same validation points and the raw
failures. Their clipped line images and depth thresholds agree on both
architectures, while absolute thresholds change with the clipped geometry.
The original image gate remains failed; no diagnostic threshold offset becomes
a production depth bias.
