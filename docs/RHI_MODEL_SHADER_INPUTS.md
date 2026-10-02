# Platform-independent model shader inputs

October 1, 2026. Model draw snapshots now retain explicit matrix, directional
light, material, normal-transform and texture-cascade inputs. An optional DX9
replay consumes these fields for the previously accepted independent batch.
A separate DX11 WARP triangle validates the vertex-stage matrix/light contract.
This is a fixed-function compatibility subset, not a complete DX11 renderer.

## Data and conventions

`MaterialDraw::shaderInputs` is optional `rhi::MaterialShaderInputs`. A document
capture has no actual draw state, so it does not invent shader inputs from PMM.
The Windows producer captures them at the actual submission boundary. Unsupported
states produce `SHADER ... status=UNSUPPORTED`, instead of supplying defaults.

| Field | Meaning |
| --- | --- |
| `world`, `view`, `projection` | Row-major matrices acting on row vectors: `p * world * view * projection`. World/view are affine; projection retains its perspective fourth column. Left-handed scene/view; D3D clip depth is `[0,w]`. Backend clip conversion is explicit. |
| `normalView` | Inverse transpose of the linear part of `world * view`. No translation; reject singular/non-finite transforms. |
| `diffuse` | Model-document material diffuse, used by existing model/snapshot comparison. |
| `nativeDiffuse`, `materialAmbient`, `materialSpecular`, `emissive`, `shininess` | Effective four-channel material colors and power at this draw, not assumed equal to unmodified document parameters. |
| `lights[0..7]` | Enabled directional lights with native/world-space ray direction and diffuse/ambient/specular colors. Preserve direction magnitude in the contract; shader formulas normalize explicitly. Convert directions into view space for view-space normal lighting. Other light types are unsupported in this subset. |
| `globalAmbient` | Explicit RGBA decoded from legacy packed ambient render state. No implicit sRGB conversion. |
| Lighting flags and material sources | Lighting, normal normalization, specular enable, local viewer and vertex color enable; material-source selections are Material/Color1/Color2. |
| `layout.stages`, `textureTransforms`, `samplers`, `srgbSample` | Logical Toon/Base/Sphere cascade order, texture/color/alpha arguments, mesh UV0/UV1 or camera-space-normal coordinates, row-vector texture transforms, addressing/filtering and sampling color-space flag. No DX9 tokens cross this boundary. |
| `alphaTest`, `alphaCompare`, `alphaReference` | Explicit byte alpha-test policy. |
| `MaterialDraw::raster` | Existing depth, blend factors and cull policy, plus draw pass/sequence and resource references in the enclosing draw. |

Inputs are semantic C++ records, **not** a GPU constant-buffer memory layout.
Do not memcpy booleans/enums/the entire struct into HLSL. Backend code packs
explicit float groups with verified 16-byte alignment. The DX11 test demonstrates
an explicit matrix/direction/diffuse constant buffer and `row_major` HLSL.

`TransformShaderVector` implements the stated convention. `BuildShaderNormalMatrix`
computes the inverse-transpose matrix without Win32/D3DX. The portable validator
checks finite values, affine world/view structure, normal-matrix shape, nonzero
enabled-light directions, material power, source selections and sampler/layout
enum bounds. It does not assert the rendered scene is physically correct.

Toon/Sphere cascade validation retains the earlier PMD/PMX layout rules. The
Windows producer checks the native operation, arguments, coordinate source,
transform flags and sampler values against that logical layout. Unknown material
layouts remain unsupported; texture names do not determine light/view values.

## Capture, comparison and DX9 replay

Capture occurs for every actual draw even when owned textures are disabled.
`model_material.snapshot` now contains `SHADER`, `INPUT`, `PARAMETERS`,
`TEXTURE_INPUT` and enabled `LIGHT` records alongside previous geometry/raster
and native-state records. Matrices are emitted with nine significant digits for
float round trips. Frame, slot, material, pass and sequence identify the batch.

`MDS_RHI_SHADER_INPUTS=1` enables optional explicit DX9 replay for the owned Toon/
material batch path. Every adapter submission recaptures current inputs before
applying them; texture-cache hits must not reuse a previous frame's camera/light
constants. The adapter applies matrices, directional lights, effective material,
lighting/source/alpha-test flags, texture transforms, cascade and sampler states
inside the existing captured-state transaction. Raster state continues through
its existing contract; read-only probes keep depth/stencil writes disabled.
The full legacy state block restores host state after the callback.

Immediately before submitting the draw, the bridge independently reads back the
replayed DX9 values and compares them with the retained input record.
`shader_inputs.transport` reports field/component, frame, slot/material, expected
and observed value on a difference, and a summary for each submission. Matrix,
material, normal, lighting flags, power, lights, texture matrices, sampler and
sRGB values are checked. Cascade operation/argument mismatch fails capture.
The GUI test requires a PASS summary and no DIFFERENCE/FAIL records.

This verifies **native-state capture -> portable record -> native replay**.
It is not an independent PMM-to-camera/light evaluation oracle: the Windows
producer still obtains effective drawing transforms and lighting from the host.
Likewise, byte equality of matrices is a transport check, not proof of correct
camera reconstruction or skeletal deformation. Existing geometry/dependency
and pixel gates remain necessary.

## Acceptance and tests

The real v1 test derives the same independent frame-5 batch from a temporary
scene copy: slot 2, material 10, first index 63381, count 24. It uses the already
accepted D3DX-prepared eye texture on that batch; original assets remain untouched.
It captures 17 material input records on each architecture. The real v2
`test_1.pmm` snapshot captures 25 material input records without unsupported
captures, alongside the existing 25-draw/zero-mismatch and Save As/readback checks.
PMX drawing remains on the old renderer.

The explicit replay requires `rhi_real_shader_inputs_gui`, with external
`MDS_PMM_GUI_FIXTURE=.../UserFile/sample.pmm` and
`MDS_PMM_RELOCATE_MODEL=Dammy_Bone.pmd`. CTest supplies the replay flag and
temporary configured-material mode. The existing native pixel gate still
requires zero same-frame and actual-adapter pixel differences.

Portable material-resource tests now also verify non-commuting world/view/
perspective transforms against independent expected vectors, direction (`w=0`)
translation exclusion, non-uniform normal scale, rotated tangent/normal
orthogonality, singular rejection, non-finite colors and invalid enums. These
tests run without external model assets in the existing standalone CI suite.

`rhi_d3d11_shader_inputs` uses WARP, an original three-vertex triangle, an explicit
constant buffer and VS/GS stream output. It reads back clip positions and Lambert
diffuse/alpha values, compares against the portable CPU expectation (absolute
float tolerance `1e-6`, non-finite outputs rejected), and exercises positive,
negative and perpendicular light-facing normals. It needs no desktop window.
No render target/pixel shader is involved: it validates a minimal **vertex-stage
shader batch**, not same-frame DX9/DX11 pixel equivalence, Toon/Sphere shading,
specular lighting, or application integration. Unavailable WARP/feature level
returns skip 77; shader/validation failure returns 1. Local x64/x86 runs passed.

Evidence is retained in `exports/rhi-shader-inputs-x64`, `...-x86` and
`exports/rhi-shader-inputs-v2-x64`, `...-x86`. The first two include the transport
comparison and same-frame/actual pixel report; v2 directories contain complete
material snapshots.

Local acceptance on both x64/x86: three independent-batch transport summaries
per run report zero differing fields, and the 2073600-pixel comparison reports
zero same-frame and actual draw differences. Changed pixels are 11 on x64 and
8 on x86; actual adapter application is 1, with one MME bridge/direct submission.
The existing resource smoke test also passes. Both complete Windows builds pass;
the full x64 application additionally builds with the DX9 RHI disabled.

The standalone five-test suite (including the expanded material/matrix test)
passes locally, on the user's Linux server in the existing
`preparation-resource-check-20260930` directory, and in
[CI run 36792159999](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36792159999)
on Windows, Linux and macOS. No resource tests were skipped. The isolated source
revision is `885c637509cea70dfce4d18ce56052bd1952ff89`, recorded in
`out/resource-ci/shader-inputs-remote-run.json`; logs are retained under
`exports/rhi-shader-inputs-resource-ci.log`. The validation branch contains only
portable resource dependencies; its full formats job is intentionally skipped.
Native DX9/DX11 acceptance is local Windows evidence, not a three-platform GPU test.

## Remaining backend boundaries

Keep replay opt-in. Shader backends still require a complete pipeline/pass
contract for separate alpha blend, stencil, fog, shadow passes and MME; mesh
deformation remains on the old path for IK/physics and unsupported dependencies.
The first DX11 shader only covers matrix/normal/directional diffuse transport.
The initial Toon/Sphere pixel cascade now has a synthetic offscreen probe;
see [pixel acceptance](RHI_MATERIAL_PIXEL_VALIDATION.md). Point cases pass,
but WARP linear sampling remains blocked. Follow-up same-GPU hardware probes
pass point and linear sampling. The initial real batch now also passes with
production lighting/coordinates and explicit compatibility settings; see
[real DX11 batch](RHI_REAL_DX11_BATCH.md). A larger batch now also passes
[single-sample scene history](RHI_SCENE_HISTORY_COMPARISON.md) and an actual
application reference. Next preserve per-sample MSAA history. Do not
activate a full backend merely because vertex-stage transport passes.
