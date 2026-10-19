# Draw 42: measure UV, gradients and sampling before byte conversion

The three triangles from [the Sphere color reduction](RHI_MODEL_DRAW42_COLOR.md)
now have a measured sampler-input diagnosis. Their native fixed-function DX9
UV/gradients differ from the diagnostic DX11 inputs. Feeding the same measured
UV and gradients to either programmable sampler recovers the corresponding
original float32 **and actual RGBA8** images exactly, at every covered pixel.
This identifies an input boundary before texture sampling for these controls;
it does not enable a production backend or pass the original full-material gate.

## Inputs and observation gates

Both x64/x86 executables use the same x64 archive, the same three compact
triangles, all nine owned Sphere mip levels, and the same recorded viewport
`(565,25,1032,774)` in a 1920 x 1080 single-sample target. Wrap addressing,
maximum anisotropy 16 and the recorded filter state are retained. The DX11
diagnostic viewport is offset by `(0.5,0.5)`; the vertex shader makes no XY
correction. Lighting, specular, depth, stencil, blending and alpha test are
disabled in the already-established pure-Sphere control.

Rasterization uses the full original target and viewport. Readback alone is
cropped to `(847,333,42,27)`, containing all 133 reference-covered pixels with
padding. Baseline byte draws verify that all pixels outside the readback region
remain white. The independent auditor proves that the crop contains every
non-white pixel of the full prior reference images.

There are two distinct paths:

1. **Native vertex processing.** Original model XYZ/normal/UV inputs, matrices
   and fixed-function vertex processing are retained. A diagnostic `ps_2_a`
   exposes texture sampling, UV, or `ddx(UV)/ddy(UV)`. Its texture-sample byte
   image must match the prior native fixed-function image; its float image must
   match a fresh draw with the pixel shader also left fixed-function. Both gates
   pass, including explicit-gradient sampling. Sample, UV and gradient float
   observations are each repeated on three additional fresh DX9 devices.
2. **Common clip input.** The earlier captured diagnostic DX11 clip positions
   and Sphere UV are fed directly to both programmable APIs. DX11 must match
   its prior adapter image. The programmable DX9 proxy differs from its native
   reference at 11 / 1 / 5 pixels; these failures are recorded, not treated as
   native-equivalent passes. Common-input DX9/DX11 byte and float images, UV and
   gradients match exactly. DX9 `vs_2_0/ps_2_a` and `vs_3_0/ps_3_0` linkage also
   match for common inputs.

The first native-vertex observation used `ps_3_0` and read zero UV, failing all
covered reference pixels. It was rejected. The legacy TEXCOORD register linkage
used by `ps_2_a` passes both observation gates. A shader that compiles is not
sufficient evidence that it observes the intended native varying inputs.

## Measured input and float-color differences

UV means the value delivered to the pixel shader; this experiment does not
capture native DX9 vertex-register contents. Gradients are the observed shader
`ddx/ddy` values. Deltas cover all channels of each observation.

| Triangle (zero-based) | Covered pixels | UV pixels differing / maximum | Gradient pixels differing / maximum | Float sample pixels differing / maximum |
| --- | ---: | --- | --- | --- |
| 1478 | 72 | 72 / 0.0000858903 | 72 / 0.0000171661 | 62 / 0.00187689 |
| 1822 | 35 | 35 / 0.0000826716 | 35 / 0.0000155568 | 30 / 0.00146484 |
| 1823 | 26 | 26 / 0.0000517964 | 26 / 0.00000643730 | 24 / 0.00157169 |

Three additional repetitions preserve the common-input sample float images
exactly. Freezing all native mip levels preserves the untouched fixed-function
float image, extending the earlier RGBA8 mip validation.

Common-input auto sampling, explicit-gradient sampling, linear/point controls
and integer fixed LODs 0 through 8 all have zero inter-API differences, in both
byte and float targets. For native-vertex LOD 0, zero explicit gradients force
top-level sampling, with linear min/mag and point mip. It still differs from the
common-input DX11 LOD 0 at **62 / 28 / 23 float pixels**, with maximum deltas
0.00265506 / 0.00202942 / 0.00184631. A difference in automatic LOD selection is
therefore not necessary to reproduce the sample difference.

## Crossfeed all covered pixels

At each of all 133 covered pixels, the test feeds four measured input pairs into
`tex2Dgrad` / `SampleGrad`, with the UV and gradients held constant in shader
parameters for that query:

- native UV + native gradients;
- common-input DX11 UV + common-input DX11 gradients;
- native UV + common-input DX11 gradients;
- common-input DX11 UV + native gradients.

No inputs are fitted, rounded or chosen only from failing pixels. Every covered
coordinate is retained in scan order, including independent positions without
original byte differences. Each query renders separately to float32 and RGBA8
targets. All **532 input-pair queries** have exact inter-API float results and
exact inter-API actual byte results.

Native/native inputs recover the untouched fixed-function float sample and its
prior actual byte image at **all 133 pixels**. DX11/DX11 inputs recover the prior
diagnostic DX11 float and actual byte results at all 133 pixels.

| Input pair | Triangle 1478: differing float / actual byte pixels vs native | Triangle 1822 | Triangle 1823 |
| --- | --- | --- | --- |
| Native UV + native gradients | 0 / 0 | 0 / 0 | 0 / 0 |
| DX11 UV + DX11 gradients | 62 / 11 | 30 / 1 | 24 / 5 |
| Native UV + DX11 gradients | 5 / 2 | 3 / 0 | 5 / 1 |
| DX11 UV + native gradients | 61 / 10 | 28 / 1 | 23 / 5 |

For these triangles, UV changes account for most of the observed color change;
gradient differences account for a smaller residual. Equal sampler inputs
produce equal results on this device in all these controls. The discrepancy
therefore lies between native vertex processing/raster setup and the delivered
UV/gradient inputs, rather than requiring different sampler arithmetic.

## Actual byte output and limits

A simple `floor(color * 255 + 0.5)` model applied to the separately captured
float target fails to predict 8 / 3 / 2 native auto-sample byte pixels and
9 / 2 / 2 common-input byte pixels (maximum delta one). The model is retained as
a failed diagnostic; actual RGBA8 crossfeed draws provide the acceptance data.
Reading a float render target does not by itself prove the exact value or
conversion rule used by the byte-target draw. No new resolve/rounding fit is
installed in a backend.

The original full-material draw still has seven one-byte differing pixels.
This experiment measures the pure-Sphere reduction; it does not replace the
full Toon/material/specular cascade with captured pixel inputs. Native matrix
combination/XY/W transformation, viewport mapping and triangle interpolation
setup remain possible sources of the input difference. The next useful
isolation is to compare those geometric inputs while retaining these exact
triangles and the measured UV/gradient observations as the verification target.
The data does not establish an undocumented driver coefficient formula.

The follow-up [XY/W and triangle-order isolation](RHI_MODEL_XY_INTERPOLATION.md)
now identifies a clip-Y arithmetic change at shared vertex 3341. Correcting only
Y recovers the reduced UV, gradients and sample observations; the test-only GPU
candidate also passes the full draw-42 byte image gate. This follow-up preserves
the distinction between a matching hypothesis and native register observation.

The application remains DX9. All instrumentation and shared-input shaders are
test-only, and `imageAcceptance=0` is preserved. No texture-filter substitution,
per-pixel lookup correction, tolerance change or production activation is made.
Results concern this NVIDIA TITAN Xp and single sampling; they are not acceptance
of other PMM scenes or MSAA.

## Verification and reproduction

Each architecture completes 102 paired image observations, 532 crossfeed input
pairs (each to two target formats), three additional common-input repetitions,
and three additional native sample/UV/gradient repetitions. The 269 evidence
artifacts have matching SHA-256 hashes across x64/x86 on identical inputs.

Nine focused CTests pass on each architecture: replay conversion, native mip
capture, shared clip depth, explicit Z, shared color, normal precision, native
ground images, hardware replay conversion and portable model replay. GPU tests
are serialized, with changed executables linked before execution. These private
PMM measurements are not added as asset-dependent CI acceptance fixtures.

`tools/analyze_model_sampling.py` independently verifies the crop/reference
coverage, prior SO input bytes, full saved-image metrics, reference gates,
native float equivalence, repetitions, explicit gradients, every crossfeed
input value and coordinate, float/actual byte recovery, mip preservation and
cross-architecture hashes. It reports failed rounding predictions explicitly.
Private images and model textures remain in ignored `exports/`.

After building `rhi_d3d9_replay_conversion_test`, use fresh output directories:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --model-sampling exports/ground-rhi-prefix-x64 exports/model-color42-verified-x64 exports/new-sampling-x64
python tools/analyze_model_sampling.py exports/ground-rhi-prefix-x64 exports/model-color42-verified-x64 exports/new-sampling-x64
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --model-sampling exports/ground-rhi-prefix-x64 exports/model-color42-verified-x64 exports/new-sampling-x86
python tools/analyze_model_sampling.py exports/ground-rhi-prefix-x64 exports/model-color42-verified-x64 exports/new-sampling-x86 --compare exports/new-sampling-x64
```

The measurement command returns zero for complete diagnostics; it is not an
image-acceptance test. The existing full prefix gate remains failed. The final
evidence is `exports/model-sampling-final-capture-{x64,x86}/`; initial failed-linkage and
earlier partial measurements remain separate.
