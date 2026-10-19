# Draw 42: clip Y rounding and triangle interpolation

The remaining draw-42 color differences from [the sampler-input measurement](RHI_MODEL_SAMPLING_INPUTS.md)
are now reproduced and removed by a diagnostic clip-coordinate arithmetic
change. On the existing three triangles, changing only the Y dot-product result
at their shared vertex restores every observed UV, gradient and float sample.
The test-only GPU shader produces the same predicted clip bytes. The complete
2222-triangle material batch then has zero native/DX11 byte differences.

This is a measured compatibility result on the captured inputs, not a native
DX9 vertex-register capture or a production renderer switch.

## Controls and fixed inputs

Both architectures use the identical x64 archive and the previously saved
sampling reference. The target is 1920 x 1080, recorded viewport
`(565,25,1032,774)`, one sample and readback crop `(847,333,42,27)`. Rasterization
and derivatives still use the full viewport. Every control retains the captured
Sphere UV, texture/mip bytes and sampler. Lighting, depth, stencil and blending
remain disabled in the established pure-Sphere reductions.

Each triangle tests three float observations: sampled color, pixel UV and
`ddx(UV)/ddy(UV)`. The 486 observations per architecture cover:

- original native transforms and shared-clip baseline, with three extra
  repetitions of each;
- sixteen CPU clip hypotheses: four matrix-combination rounding rules times
  four vertex dot-product rules (sequential float, one final float rounding
  after double accumulation, paired float, and sequential fused accumulation);
- fused X/Y with original Z/W, plus separate X-only and Y-only changes;
- native fixed-function transforms supplied with precombined WVP or WV, using
  all four matrix rounding rules;
- pretransformed DX9 XYZRHW inputs, using either the original shared clip or
  corrected X/Y and two screen-coordinate evaluation rules;
- all six permutations of the same vertices, with culling disabled, for the
  original native, original shared and corrected shared paths.

No candidate uses point-dependent corrections, fitted coefficients or a search
over vertex ULPs. Submitted geometry and native transform matrices are saved.
All shared-clip controls have exact inter-API results, even when they disagree
with the original native UV/sample reference.

## One common vertex explains the reduced failures

The three triangles are 1478, 1822 and 1823 (zero-based within the material
batch). They share original vertex index **3341**. The corrected clip coordinates
change only its Y component:

| Component | Prior diagnostic value | Fused candidate value |
| --- | --- | --- |
| X | -16.207550048828125 | unchanged |
| Y | 6.010467529296875 | 6.010463714599609 |
| Z | 37.29788589477539 | unchanged |
| W | 38.29751205444336 | unchanged |

The Y delta is `-3.814697265625e-6`, or **-8 float32 ULPs**. Other vertices in
these triangles have unchanged corrected clip bytes. The object-to-clip Y dot
product includes translation/cancellation, so its resulting float error is not
bounded by one ULP of the final small value simply because its operands are
float32.

| Triangle | Original shared UV / gradient pixels differing | Original shared sample pixels differing | Y-only or fused-X/Y UV / gradient / sample pixels differing |
| --- | --- | ---: | --- |
| 1478 | 72 / 72 | 62 | 0 / 0 / 0 |
| 1822 | 35 / 35 | 30 | 0 / 0 / 0 |
| 1823 | 26 / 26 | 24 | 0 / 0 / 0 |

Changing X alone leaves the original failure. The tested W values already agree
between the prior diagnostic and the fused candidate; no W change is required
for this recovery. Using the one-final-rounding double dot candidate also
recovers all reduced observations. Its matching result prevents claiming that
this fixture uniquely identifies the driver's internal fused operation order.

All native precombined-WVP/WV controls preserve the native observations.
Matrix-combination rounding rules have identical X/Y/W columns for this source;
one rule changes a Z translation coefficient by one ULP, which does not affect
these depth-disabled UV/sample controls. This input alone therefore does not
validate every matrix coefficient or distinguish general matrix multiplication
rounding rules.

## Interpolation and screen-coordinate controls

The corrected common clip geometry matches native sample, UV and gradients for
all six vertex orders on both APIs. The original common geometry keeps the
same failure across orders. No remaining inter-API triangle-setup discrepancy
is observed after correcting the shared clip input on these triangles.

Pretransformed XYZRHW is a separate counterfactual boundary: it supplies rounded
screen coordinates and reciprocal W, bypassing native transform/projection. With
corrected X/Y it matches all sample images and the first two triangles' UV and
gradients. Triangle 1823 retains 23 differing UV pixels and 22 differing gradient
pixels, with maximum UV delta `1.7881393432617188e-7`. Both tested CPU screen
evaluation rules produce this result. These small input/interpolation changes
are retained as failures; XYZRHW is not declared equivalent to the corrected
common-clip path. They do not require a color difference in this texture control.

## GPU shader and full material verification

A new factory `CreateD3D11FusedXYCandidateDevice` exists only in the diagnostic
executable's backend copy. It retains the viewport-center, Z/W, normal and
lighting candidates and evaluates X/Y with explicit sequential fused steps,
using the existing float32 combined matrix. Each step uses exact float products
in double and rounds the product-plus-accumulator result back to float.

DX11 stream output observes fresh clip and Sphere UV bytes for each compact
triangle and three additional repetitions. Every byte matches the CPU fused-X/Y
prediction with original Z/W; the normal/UV calculation is unchanged. No native
`ProcessVertices` result is used as an actual fixed-function draw capture.

The full original **2222-triangle draw 42**, with its original material, Toon,
Sphere, specular, blend, depth and stencil state restored, matches native DX9
at every viewport pixel. The native image remains byte-identical to the prior
draw-alone reference. Three additional complete native/candidate draws also
match exactly. No triangle subset or pure-Sphere state substitutes for this
full-material image gate.

## Scene-prefix verification and limits

The real captured scene contains 51 draws / 195 events / 143 owned resource
versions: two ground, nineteen accessory, seventeen projected-shadow and
thirteen model-material draws. The diagnostic fused-X/Y candidate uses original
geometry, matrices, resource versions and draw order. The prefix test reconstructs
native DX9 at every boundary and checks it against the actual application capture.
It also draws each batch independently and repeats the final candidate image
three additional times.

| Captured input / executable | Native failing boundaries | Candidate failing boundaries | Failing independent draws | Final differing pixels |
| --- | ---: | ---: | ---: | ---: |
| x64 `(565,25,1032,774)` / x64 | 0 | 0 | 0 | 0 |
| Same x64 archive / x86 | 0 | 0 | 0 | 0 |
| Original x86 `(274,25,670,503)` / x86 | 0 | 0 | 0 | 0 |

The two executables replaying the identical x64 archive have **60 byte-identical
evidence artifacts**, including all boundary images, trace and independent-draw
tables, and three saved final repetitions. The original x86 viewport differs,
so its images are compared to its own application capture, not to the x64 image.
The uncorrected viewport-center candidate is rerun separately: all 65 artifacts
match the prior evidence, preserving its 10 failing boundaries, 3 independent
draw failures and 8 final differing pixels. Adding the selector did not change
the original baseline.

These are
GPU replays of prior owned real PMM captures, not new application backend
activation or a guarantee for every other PMM scene. MSAA, other GPUs, general
matrix/geometry inputs and MME remain separate acceptance work. The DX11
candidate requires double shader operations and is a compatibility diagnostic;
its performance and wider backend suitability are not established here.

The application stays on DX9. No tolerance, UV lookup correction or production
shader formula is changed. Next, qualify the X/Y arithmetic on independent
world/view/projection inputs before considering a production compatibility mode.

That independent qualification is now recorded in
[Independent XY/W transforms](RHI_INDEPENDENT_XY.md): 36 generated cases,
including separate dense matrices, perspective and large cancellation, match
native DX9 observations and complete material images on x64/x86. Native driver
operation order and production activation remain separate decisions.

## Audit and reproduction

`tools/analyze_model_transform.py` independently checks every matrix coefficient,
CPU clip arithmetic, original vertex indices, shared UV bytes, permutations,
screen/RHW conversion, actually submitted native vertices/matrices, GPU SO
repetitions, float-image metrics and full-material byte hashes/reference/repeats.
It retains the differing XYZRHW controls. The x64/x86 reduction results have
**1054 matching evidence-artifact SHA-256 hashes** on the identical archive.

`tools/analyze_scene_prefix.py --evidence` checks actual-application/native prefix
reconstruction, complete candidate images, independent draw metrics, the
test-only fused-X/Y policy and three final repetitions.

Nine focused CTests pass per architecture: portable clipping, replay conversion,
shared clip depth, explicit Z, shared color, normal precision, normal transforms,
ground images and portable model replay. GPU tests run serially, after changed
executables finish linking. Captured assets are not added as CI fixtures.

After building `rhi_d3d9_replay_conversion_test`, use fresh output folders:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --model-transform exports/ground-rhi-prefix-x64 exports/model-sampling-final-capture-x64 exports/new-transform-x64
python tools/analyze_model_transform.py exports/ground-rhi-prefix-x64 exports/model-sampling-final-capture-x64 exports/new-transform-x64 --material-reference exports/center-stage-pmm-viewport-final-x64
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --model-transform exports/ground-rhi-prefix-x64 exports/model-sampling-final-capture-x64 exports/new-transform-x86
python tools/analyze_model_transform.py exports/ground-rhi-prefix-x64 exports/model-sampling-final-capture-x64 exports/new-transform-x86 --material-reference exports/center-stage-pmm-viewport-final-x64 --compare exports/new-transform-x64
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --scene-prefix-fused-xy exports/ground-rhi-prefix-x64 exports/new-fused-prefix
python tools/analyze_scene_prefix.py exports/ground-rhi-prefix-x64 --evidence exports/new-fused-prefix
```

The reduction command returns zero for completed diagnostics with its altered
controls; the prefix command retains its original zero-difference gate and
returns 32 if a native/candidate boundary differs. Private model, texture and
PMM evidence is ignored under `exports/`. Initial and final runs remain separate.
Final reductions are in `exports/model-transform-final-{x64,x86}/`; full prefixes
are in `exports/xy-fused-prefix-final-{x64,x86}/`, with the identical-input x86
replay in `exports/xy-fused-prefix-shared-x86/`. Cross-architecture/baseline hashes
are recorded in `exports/model-xy-architecture-proof.json`.
