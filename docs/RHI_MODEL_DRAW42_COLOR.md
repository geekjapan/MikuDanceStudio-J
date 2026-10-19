# Real PMM draw 42: Sphere sampling color reduction

The viewport-center diagnostic from [the clipping experiment](RHI_GROUND_CENTER_STAGE.md)
first differs at model-material draw 42 in the x64 `sample.pmm` capture. This
experiment reduces its seven one-byte color differences to three individual
triangles and tests the texture input boundary. It does not enable a production
DX11 renderer or change the zero-difference image gate.

## Baseline and geometry

Both executables use **the same x64 archive**, target 1920 x 1080, viewport
`(565,25,1032,774)`, one sample, native D24S8 and white clear. The diagnostic
DX11 candidate disables the vertex shader's XY shift and offsets the viewport
origin by `(0.5,0.5)`. Its existing explicit Z/W, lighting and normal candidates
are retained. This is not a rerun of the smaller original x86 viewport, which
already passed the preceding experiment.

The original draw-alone images match the prior native/DX11 evidence byte for
byte. Three additional fresh draw repetitions match both images. The original
batch is indexed XYZ/normal/UV, stride 32, start index 42126, 2222 triangles.
Every branch of a binary range reduction is tested; the following zero-based
triangle numbers account for all seven original differing pixels:

| Triangle in this batch | Original vertex indices | Original differing pixels |
| --- | --- | ---: |
| 1478 | 3342, 3341, 3298 | 4 |
| 1822 | 3947, 3298, 3341 | 2 |
| 1823 | 3947, 3341, 3964 | 1 |

Compacting each to three original vertices and indices `(0,1,2)` preserves both
complete images exactly. A draw number is not a material or triangle number.
All coordinates below are absolute target coordinates; bytes are BGRA:

| Pixel | DX9 | Diagnostic DX11 |
| --- | --- | --- |
| (873,344) | 13,12,13,255 | 13,12,12,255 |
| (866,346) | 26,24,24,255 | 27,24,24,255 |
| (868,347) | 22,21,21,255 | 22,20,21,255 |
| (867,348) | 16,16,16,255 | 16,15,16,255 |
| (859,349) | 28,24,24,255 | 27,24,24,255 |
| (860,352) | 28,25,25,255 | 27,25,25,255 |
| (861,352) | 18,17,18,255 | 18,17,17,255 |

## Stage controls

Each altered input is a diagnostic control, not a substitute for the original
acceptance input. Comparisons inspect the whole viewport, including newly
differing pixels outside the original seven positions.

Each architecture completes 163 comparisons. On identical archive inputs, all
349 evidence artifacts (images, tables, compact meshes, stream-output captures
and metadata) have matching SHA-256 hashes across x64/x86. This rules out an
architecture-specific change in these observed results on this NVIDIA TITAN Xp.

| Whole batch control | Differing pixels | Maximum channel delta |
| --- | ---: | ---: |
| Original | 7 | 1 |
| Disable blending / alpha test / depth and stencil, separately | 7 each | 1 |
| Disable specular | 6 | 1 |
| Disable lighting | 17 | 1 |
| Disable normal normalization | 7 | 1 |
| Toon only | 0 | 0 |
| Sphere only (promoted stage with diffuse input) | 5 | 1 |
| Disable textures | 0 | 0 |
| White Toon / white Sphere / both white | 5 / 0 / 0 | 1 / 0 / 0 |
| Point min/mag/mip | 0 | 0 |
| Linear min/mag, point mip | 3 | 1 |
| Linear min/mag/mip | 6 | 1 |

Stage zero is a 32 x 32 Toon texture; stage one is a 256 x 256 Sphere texture,
with nine captured RGBA mip levels. Both use camera-normal coordinates and
MODULATE. The source min/mag/mip filters are anisotropic, maximum anisotropy 16.
The recorded Toon/Sphere transforms, texture bytes, material and lights are
otherwise retained. These results require the nonconstant Sphere path to
reproduce the original differences. Disabling lighting does not establish that
lighting is exact; it changes the color fed into the cascade.

## Shared coordinates and frozen mips

The test observes the candidate's existing `TEXCOORD1` semantic through DX11
stream output, alongside clip position and diffuse color. No shader arithmetic
is rewritten to encode UV in a color channel. Each three-vertex observation is
captured three additional times and saved; all repetitions are byte-identical.
These are **DX11 observations**, not captures of native DX9 vertex outputs.

Each observed float32 Sphere UV is copied into the compact mesh's UV field.
Both APIs then use mesh UV for stage one without a texture transform. For all
three triangles, both resulting images are byte-identical to their respective
original camera-normal-coordinate images. Differences remain 4 / 2 / 1 pixels.
Thus native coordinate generation is not necessary to reproduce these failures
when the supplied common UV values are used.

Replacing native AUTOGEN with explicit upload of every captured mip level also
preserves both complete images, for the whole batch, common-UV triangles and
pure-Sphere controls. The corresponding DX11 textures use the same owned RGBA
levels. Hidden mip regeneration is not necessary to reproduce the failures.

Pure-Sphere controls retain common UV and disable lighting, specular, blending,
alpha test, depth and stencil. They differ at 11 / 1 / 5 pixels for triangles
1478 / 1822 / 1823 respectively, all by one byte. Point filtering is exact for
all three. Linear filtering can produce differences as well; this is not an
anisotropic-only finding. The pure-Sphere controls change the color calculation
and therefore do not retain every original focus pixel.

For each pure-Sphere triangle, seven constant-UV controls use its three vertex
UVs, three edge midpoints and centroid. All **21 constant-UV images are exact**.
The triangles visibly draw 72 / 35 / 26 non-white pixels respectively; these
are not empty-image passes.
These controls also change derivatives/LOD and do not prove that texture
filtering itself is exact for the original varying UV plane.

## Conclusion and limits

The remaining failure has been isolated to a small textured triangle path
without scene history, depth, stencil, blending, hidden mip generation or native
coordinate generation as necessary conditions. Varying UV with filtered Sphere
sampling remains the relevant boundary. The observations do not yet distinguish
UV interpolation precision, texture derivatives/LOD, filter precision and final
color rounding. The next useful measurement is interpolated UV/gradients and
sampled color before RGBA8 conversion, using these same three triangles.

The follow-up [pixel-stage sampling measurement](RHI_MODEL_SAMPLING_INPUTS.md)
now verifies those inputs and samples. Native UV/gradient crossfeed restores
all 133 pure-Sphere pixels in float and actual byte targets; differing UV is
the dominant measured input, with a smaller gradient contribution. The original
full-material image gate remains failed.

A later [clip-Y arithmetic isolation](RHI_MODEL_XY_INTERPOLATION.md) subsequently
passes the full draw-42 gate using a test-only fused-X/Y candidate. The earlier
viewport-only failure remains a saved baseline; no production switch is made.

The original seven pixels remain failures. No point-filter substitution,
tolerance increase or production backend activation is made. DX9 remains the
application path. Other scenes, hardware and MSAA are outside this measurement.

## Evidence and reproduction

`tests/model_color_isolation_fixture.hpp` is invoked by the existing replay
conversion executable. `tools/analyze_model_color_isolation.py` independently
checks reference images, full-image metrics and hashes, all focus bytes, both
branches of the range tree, source indices/vertices, compact geometry, saved
SO repetitions, exact shared-UV bytes, mip controls and completion metadata.
It preserves `imageAcceptance=0` in its report.

Eight focused CTests pass per architecture: portable clipping, replay conversion,
shared clip depth, explicit Z, normal precision, normal transforms, ground images
and portable model replay. GPU runs are serialized; compilation/link completes
before executing changed tests. Private material captures are not CI fixtures.

After building `rhi_d3d9_replay_conversion_test`, use fresh folders:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --model-color-isolation exports/ground-rhi-prefix-x64 exports/center-stage-pmm-viewport-final-x64 exports/new-color42-x64
python tools/analyze_model_color_isolation.py exports/ground-rhi-prefix-x64 exports/center-stage-pmm-viewport-final-x64 exports/new-color42-x64
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --model-color-isolation exports/ground-rhi-prefix-x64 exports/center-stage-pmm-viewport-final-x64 exports/new-color42-x86
python tools/analyze_model_color_isolation.py exports/ground-rhi-prefix-x64 exports/center-stage-pmm-viewport-final-x64 exports/new-color42-x86 --compare exports/new-color42-x64
```

The diagnostic returns zero for complete measurements, even with differing
images; it is not an image acceptance test. The preceding real prefix gate
still returns 32 for the x64 color differences. Private PMM/texture evidence is
kept under ignored `exports/model-color42-verified-{x64,x86}/`.
