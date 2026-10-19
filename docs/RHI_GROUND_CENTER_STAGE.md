# Pixel-center correction before clipping versus in the viewport

This continues [the fixed intersection-rounding repros](RHI_GROUND_CLIP_ROUNDING.md)
on NVIDIA TITAN Xp, Windows x64/x86, single-sample RGBA8/D24S8. It fixes the
same line, two triangles and three depth coordinates. The only DX11 stage
variation moves the existing half-pixel correction from clip XY arithmetic
to the viewport origin. Production rendering remains DX9.

## Two correction stages on the same uploaded bytes

The existing diagnostic applies this vertex-shader correction before native
clipping:

```hlsl
p.xy += float2(1 / viewportWidth, -1 / viewportHeight) * p.w;
```

The new test-local alternative returns the uploaded float4 unchanged and sets
DX11's viewport to `(X + 0.5, Y + 0.5, Width, Height, MinDepth, MaxDepth)`.
In exact arithmetic both map to the same screen positions. Their clip inputs
and arithmetic boundaries differ. The viewport alternative preserves the raw
clip XY through native clipping and avoids the shader's multiply/add correction.
DX9 inputs, viewport and shaders stay unchanged.

Four geometry controls run through each stage:

1. Raw captured float4 vertices, with no CPU clipping.
2. CPU clipping only against `Z >= 0` and `W - Z >= 0`.
3. The earlier six-plane CPU clipping, in its fixed order.
4. The earlier six-plane 2-pixel guarded clipping, strictly inside both API clip
   volumes including corrected DX11 coordinates.

CPU intersections retain double intermediates and the original final float32
upload policy. The near/far helper skips all four side planes with zero plane
distances; it does not introduce a separate W plane. CPU tests verify that this
preserves geometry outside the sides while still applying near clipping.
The CPU near/far control does not disable subsequent native side / guard-band
clipping. Actual driver plane selection is not inferred from its name.

Each pair submits identical geometry bytes. GPU stream output saves every
vertex after the selected shader, including multi-triangle polygons. Captures
repeat three fresh times and verify that viewport-mode outputs preserve all
input bits; shader-mode outputs match explicit float32 correction. Viewport
state is read back and checked on every rendering query. Changing center stage
must not change a pair's DX9 images or depth thresholds.

## Line: the unmodified raw repro now matches DX9

The input remains segment 18 in viewport `(565,25,1032,774)`. Uniform color,
disabled depth/stencil/blending and viewport-local comparison are unchanged.
Every image is independently rendered three more times.

| Geometry / correction | DX9 vs DX11 differing pixels | DX9 changes from raw baseline | DX11 changes from raw baseline |
| --- | ---: | ---: | ---: |
| Raw / shader | 2 | 0 | 0 |
| Raw / viewport | 0 | 0 | 2 |
| Near/far / shader | 2 | 2 | 2 |
| Near/far / viewport | 0 | 2 | 0 |
| Six planes / shader | 0 | 2 | 0 |
| Six planes / viewport | 0 | 2 | 0 |
| Guard 2 / shader | 0 | 3 | 1 |
| Guard 2 / viewport | 0 | 3 | 1 |

Moving correction to the viewport makes the **raw DX11 image byte-identical to
the original raw DX9 image**, including `(1380,634)` and `(1380,635)`. No CPU
clipping or vertex perturbation is needed for that match.

Near/far clipping alone changes the DX9 image at those two pixels and leaves a
two-pixel inter-API mismatch under shader correction, with swapped coverage.
The viewport correction again matches the corresponding altered DX9 geometry.
Full side clipping removes the stage sensitivity on this input. Thus explicit
CPU side clipping is not required to observe the correction-stage failure, and
clipping can mask the original raw coverage discrepancy by changing geometry.

## Depth: the original plane threshold is restored

The plane triangle 1 / accessory triangle 1141, viewport `(274,25,670,503)` and
points `(922,439)`, `(921,439)`, `(923,439)` are unchanged. Each triangle is drawn
alone with the same independent `Less` / `Equal` ruler. The entries are float32
**ruler input bits**, not raw D24 attachment codes.

| Geometry | Plane at all three points: DX9 | DX11 shader | DX11 viewport | Accessory focus / left / right: all APIs/stages |
| --- | ---: | ---: | ---: | --- |
| Raw | 1065073177 | 1065073176 | 1065073177 | 1065073177 / 1065073175 / 1065073179 |
| Near/far | 1065073176 | 1065073176 | 1065073176 | 1065073177 / 1065073175 / 1065073179 |
| Six planes | 1065073176 | 1065073176 | 1065073176 | 1065073178 / 1065073176 / 1065073180 |
| Guard 2 | 1065073173 | 1065073173 | 1065073173 | 1065073180 / 1065073178 / 1065073182 |

For raw geometry, viewport correction restores the original DX9 plane threshold
at the focus **and both validation points**, preserving all raw uploaded bytes.
Accessory thresholds stay unchanged. CPU near/far clipping alone changes the
plane's native threshold; it is not an equivalent replacement for the original
native depth plane. Adding side clipping changes accessory thresholds too.

There are **48 measurements and 1588 ruler queries** per executable. Every
measured edge is verified by three fresh `Less(threshold-1)`, `Less(threshold)`
and `Equal(threshold)` queries. All raw viewport-mode thresholds now agree.
The original raw shader-mode plane failure still reproduces.

## Return to the captured real PMM prefix

Because the raw minimal controls pass, the same correction-stage alternative
is added to the test-only DX11 normal/material candidate backend. A diagnostic
constant disables shader XY correction; the backend instead offsets the native
viewport origin by 0.5. It retains original model vertices, resource versions,
matrices, shading, textures, state and draw order. It performs no CPU clipping.
The factory and constant are test-local; the production library cannot create
this candidate. Conditional implementation hooks are compiled only under
`MDS_RHI_TEST_W_CANDIDATE`.

Both existing ground-enabled `sample.pmm` archives are replayed: 51 draws / 195
events / 143 resource versions, including two ground, nineteen accessory,
seventeen projected-shadow and thirteen model-material draws. Each native
reconstruction is checked against the actual application capture at all 52
boundaries. The original shader candidate is also rerun: every boundary image,
trace row and independent draw table remains byte-identical to prior evidence.
This controls for shader compilation or baseline drift when adding the stage
selector.

| Captured viewport / executable | Native failing boundaries | Shader candidate failing boundaries | Viewport candidate failing boundaries | Final pixels: shader → viewport |
| --- | ---: | ---: | ---: | --- |
| x64 `(565,25,1032,774)` | 0 | 51 | 10 | 19 → 8 |
| x86 `(274,25,670,503)` | 0 | 46 | 0 | 1 → 0 |

The x64 viewport candidate is exact through draw 41. Ground, all accessory and
all projected-shadow draw-alone images are exact. The remaining failure begins
at draw 42, a model-material draw: 7 pixels, maximum channel delta 1, first
coordinate `(873,344)`. Draw-alone model failures are draw 42 (7 pixels), draw
43 (2 pixels) and draw 45 (1 pixel), all with maximum delta 1. The final prefix
has 8 differing pixels and maximum delta 1. Its image gate remains failed,
returning 32.

The x86 capture has zero differing pixels at **all 52 boundaries and all 51
draw-alone controls**, returning 0. On each architecture the final viewport
candidate image is replayed three additional times and saved independently;
all repetitions are byte-identical. These are independent replays of owned
real application captures, not an application backend switch or evidence that
every other PMM scene is accepted.

## Interpretation and limits

Moving pixel-center correction out of clip-coordinate arithmetic resolves both
fixed raw failures and the real x86 prefix on this device. The real x64 prefix
also loses its ground/accessory/shadow coverage and large depth-related deltas;
only small model-material color deltas remain. This identifies the placement
and arithmetic of pixel-center correction as a concrete compatibility boundary
for these inputs.

The experiment changes both correction ordering and the arithmetic used to map
XY; it does not separately prove an undocumented driver intersection rounding
formula. Guard-band details and results on other hardware / MSAA remain outside
this measurement. The production renderer and zero-difference image gate are
preserved. Next, reduce the first remaining x64 model draw's color calculation
and texture/interpolation behavior while keeping the now-tested viewport
candidate as a diagnostic baseline.

The follow-up [draw-42 Sphere color reduction](RHI_MODEL_DRAW42_COLOR.md) now
isolates the seven pixels to three compact triangles. Shared observed UV and
explicit mip upload preserve their original images; filtered varying UV remains
the relevant boundary. The original color acceptance gate remains failed.

## Audit and reproduction

`tools/analyze_ground_explicit_clip.py --stage-reference` audits CPU plane
selection and every submitted vertex, GPU shader outputs, stage descriptions,
prior raw/six-plane/guarded gates, equal DX9 baselines between stages, pixel
logs and independent depth queries. The same line archive and same depth archive
run on both executables; all **49 line artifacts and 363 depth artifacts** have
matching SHA-256 hashes. The real PMM viewports differ between the original
architectures, so their full images are not compared by cross-architecture hash.

`tools/analyze_scene_prefix.py --evidence` audits the saved real prefix against
its original archive without overwriting earlier candidate evidence. It retains
the failed x64 image gate and verifies three saved final repetitions and the
test-only center mode. Eight focused CTests pass per architecture: portable
clipping, conversion, shared clip depth, explicit Z, normal precision, normal
transforms, ground images and portable model replay.

After building `rhi_d3d9_replay_conversion_test` and `explicit_clip_geometry_test`,
use fresh output folders:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-center-stage-lines exports/ground-rhi-prefix-x64 exports/ground-endpoint-final-x64 exports/ground-explicit-line-final-x64 exports/new-center-line
python tools/analyze_ground_explicit_clip.py lines exports/ground-rhi-prefix-x64 exports/ground-endpoint-final-x64 exports/new-center-line --stage-reference exports/ground-explicit-line-final-x64
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-center-stage-depth exports/ground-rhi-prefix-x86 exports/ground-depth-threshold-x64 exports/ground-explicit-depth-final-x64 exports/new-center-depth
python tools/analyze_ground_explicit_clip.py depth exports/ground-rhi-prefix-x86 exports/ground-depth-threshold-x64 exports/new-center-depth --stage-reference exports/ground-explicit-depth-final-x64
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --scene-prefix-viewport-center exports/ground-rhi-prefix-x64 exports/new-center-pmm
python tools/analyze_scene_prefix.py exports/ground-rhi-prefix-x64 --evidence exports/new-center-pmm
```

The last x64 command/test returns 32 for its remaining material pixels. Repeat
the minimal tests using the x86 executable and identical inputs. For the real
x86 prefix use its original `exports/ground-rhi-prefix-x86` archive. Private
evidence remains ignored:

- `exports/ground-center-stage-{line,depth}-{x64,x86}/`
- `exports/ground-center-stage-shared-input-architecture.json`
- `exports/center-stage-pmm-shader-{x64,x86}/`
- `exports/center-stage-pmm-viewport-final-{x64,x86}/`
- `exports/ground-center-stage-regression-{x64,x86}.log`

Initial real viewport runs remain separate. The final runs include all three
saved final repetitions; partial evidence is not an acceptance gate.
