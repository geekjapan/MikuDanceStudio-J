# Independent XY/W transform qualification

The test-only fused-X/Y candidate from [draw 42](RHI_MODEL_XY_INTERPOLATION.md)
now matches native DX9 on **36 generated cases** on both x64 and x86. All cases
match UV, derivatives, float texture samples, byte texture samples and complete
fixed-function-versus-RHI material images. Each group has three additional
repetitions. This extends the measured input range without switching the
application renderer.

## Independent inputs and boundaries

`tests/independent_xy_fixture.hpp` constructs twelve fixed world/view/projection
sets and three triangle shapes per set. The matrices exercise identity, dyadic
affine transforms, dense rotations/shears, separate world/view transforms,
nonuniform scale, near-unit coefficients, off-axis and narrow perspective,
orthographic projection and large translation cancellation. The last six
transforms form eighteen predeclared holdout cases. No captured PMM inputs,
measured coordinates, pixel-dependent corrections or fitted coefficients enter
their construction.

Camera-space vertices come from fixed NDC XY and independent depths. A double
matrix inverse rounded to float constructs object-space geometry. The broad,
thin and oblique triangles have different nonzero Z values and UV values.
Python independently reconstructs every input coefficient and vertex byte.
A deterministic 32 x 32 RGBA texture is generated in code; no external material
or font license is needed for this fixture.

The target is 80 x 72 with viewport `(5,7,64,56)`, single sampling, linear texture
filtering and one mip level. Pixel-center correction remains a viewport shift
of `(0.5,0.5)` on DX11. Triangles stay inside the clip volume. Depth, stencil,
lighting and blending are disabled to isolate transformation and interpolation.
Different viewport sizes, clipping boundaries, MSAA, MME and lighting remain
outside this qualification.

## Observations and complete material path

Each case records original native fixed-function transformation followed by
legacy pixel shaders observing UV, `ddx/ddy`, float samples and byte samples.
These are raster observations, not native vertex-register captures.

Sixteen predefined CPU hypotheses combine four matrix multiplication rounding
rules with four vertex dot rules: sequential float, final rounding after double
accumulation, paired float and sequential fused accumulation. Native draws using
each precombined WVP additionally isolate matrix combination from vertex
evaluation. All hypotheses retain their observed differences.

Fresh DX11 stream output records the old diagnostic X/Y and the fused-X/Y
candidate. The unchanged Z/W already use the prior fused candidate. Every
candidate clip byte agrees with independent CPU arithmetic. Both APIs then draw
the same stream-output geometry through their own rasterizers and samplers.
There are **2592 observation rows per architecture**; common-clip inter-API
differences are zero throughout.

Separately, the complete generated snapshot goes through native DX9 with its
ordinary fixed-function pixel path and through `ReplayD3D11WCandidatePrefix`
with the real test-only RHI backend factory. This comparison includes the
generated texture upload, binding, material stages and normal output color
conversion. It does not replace the full-material gate with the observation
pixel shaders. Both old and fused-X/Y adapters are recorded; the fused adapter
passes all 36 cases and three additional complete draws per case.

## Distinguishing controls

Two holdout cases expose the old X/Y evaluation failure. They use the same
large-cancellation transform with translations near 4096, -8192 and 2048, but
different triangle shapes:

| Case | Shape | Covered pixels | Old UV / derivative pixels differing | Old full-material pixels differing | Fused candidate pixels differing |
| --- | --- | ---: | --- | ---: | ---: |
| 18 | broad | 867 | 867 / 867 | 235 (max byte delta 2) | 0 |
| 20 | oblique | 773 | 773 / 773 | 227 (max byte delta 1) | 0 |

The thin triangle under the same transform already agrees with the old
candidate. Shape-dependent results are kept: sharing matrix values alone does
not make the old arithmetic equivalent.

Twenty-seven cases produce distinct combined coefficients across the matrix
rules; thirty-three produce distinct clip coordinates across the hypotheses.
Sequential-matrix/fused-dot and paired-matrix/fused-dot each match every UV and
derivative image. Sequential-matrix/double-dot matches 20 cases, sequential-dot
27, and paired-dot 22. This independently rejects double final rounding as a
general substitute within this suite, although it matched the prior draw-42
reduction. These observations still do not uniquely identify all of the native
driver's operation order or matrix-combination implementation.

Native precombined-WVP controls agree in 36 cases with the sequential or paired
matrix rule, 29 with the double rule and 31 with the fused rule. Thus the suite
also detects changes at the matrix-combination boundary; it does not identify
the sequential-versus-paired choice where both preserve the observations.

The two architecture runs have **6882 byte-identical evidence artifacts**,
including their independent inputs, complete hypothesis images, repeated GPU
observations, material images and metrics. The Python audit checks the file
membership, image-derived metrics, CPU/GPU clip correspondence, repetitions
and every cross-architecture SHA-256. It does not weaken the image comparison
with a tolerance.

## Automated checks and reproduction

After building `rhi_d3d9_replay_conversion_test`, use a fresh output directory:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --xy-independent exports/new-independent-x64
python tools/analyze_independent_xy.py exports/new-independent-x64
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --xy-independent exports/new-independent-x86
python tools/analyze_independent_xy.py exports/new-independent-x86 --compare exports/new-independent-x64
ctest --test-dir build-x64/build -C Release --output-on-failure -R "^(rhi_independent_xy_controls|rhi_shared_clip_depth_hardware|rhi_d3d9_replay_conversion|rhi_model_replay)$"
```

`--xy-independent` returns 32 when the native-equivalence or shared-clip gate
fails. The separate CTest entry `rhi_independent_xy_controls` validates completed
measurements, finite output, CPU/GPU arithmetic, repeated images and inter-API
shared-clip agreement. It reports native-equivalence counts separately; it
does not assert that every future GPU implements the same fixed-function math.
Its `--xy-independent-controls` mode creates a fresh process-specific evidence
folder, so CTest reruns do not overwrite prior observations. Python 3.13 or
newer supplies `math.fma` for the independent audit.

The four listed CTests pass on both architectures (40.79 seconds on x64 and
45.83 seconds on x86). The separate native-equivalence commands and both Python
audits return zero. Generated GPU tests run serially.

Final manual evidence is retained under ignored
`exports/xy-independent-final-{x64,x86}/`, with respective `analysis.json`
files and `exports/xy-independent-audit-{x64,x86}.log`. Initial pure sampling
evidence remains separate. Generated fixture source and auditing code can be
distributed; these experiments require Windows, native DX9 and a hardware DX11
device supporting shader doubles. No WARP or other-GPU qualification is claimed.

The application remains on DX9. The candidate still uses double shader
operations to emulate the tested rounding, so performance and production
backend capability policy need separate validation before activation.

The [optional DX11 compatibility mode](RHI_DX11_COMPATIBILITY.md) now implements
that capability boundary and tests the generated material path through the
regular backend, alongside real scene resource restoration and GPU timing.
