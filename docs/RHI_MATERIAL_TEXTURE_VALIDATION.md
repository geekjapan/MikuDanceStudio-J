# Base/Sphere resources and portable material inputs

## Implemented boundary

`LoadMaterialTexture` resolves a decoded model-relative or absolute file path,
normalizes separators, reads bounded bytes and shares BMP/PNG RGBA decoding
with Toon. `.sph` and `.spa` describe material operations; their underlying image
bytes determine the decoder. A BMP saved as `.sph` and a PNG saved as `.spa` use
the same portable resource path. Empty, ready and missing/undecodable references
have distinct statuses. Missing Base/Sphere resources do not invent a white
texture or a Toon fallback. Their attempted path and identity remain diagnostic
information.

`MaterialTextureCache` owns upload/revision replacement/reuse/release. File
identity is shared across material roles; GPU cache entries also include size
and Mipmap policy. `TextureDesc::Mips` distinguishes single level from generated
linear Mipmaps. DX9 uses its managed `AUTOGENMIPMAP` resource and explicitly
requests linear generation after upload. Null validates policy/lifetime only;
it does not simulate a GPU's filtering. Other backend generation and rounding
still need their own pixel validation.

`BorrowedModelTextureCache::DrawMaterial` accepts up to three owned assets.
Only supplied entries replace external texture bindings; absent/disabled stages
retain their inherited binding, including PMD's harmless stale stage-1 binding.
It uploads and binds Toon, Base and Sphere, submits once through the existing
MME bridge, and restores all device state. A failed secondary upload prevents
submission. Callback failure or restoration failure after submission revokes
the gate and cannot trigger a duplicate legacy draw. Scene/device invalidation
discards GPU caches while caller-owned CPU assets can upload again.

## Material input contract

`MaterialTextureLayout` describes logical cascade inputs, rather than hardware
registers or native DX tokens. `MaterialShaderInputs` carries the observed
row-major texture matrices, samplers, per-input sRGB policy, diffuse/ambient/
specular/shininess values, lighting and alpha-test inputs. Actual diagnostic draw
records retain these inputs when the native state matches the supported layout.
Unknown modes/states fail closed instead of receiving guessed shader semantics.

| Input | Coordinates | Color |
| --- | --- | --- |
| Toon | Camera-space normal transformed by the captured Toon matrix | Texture multiplied by lit diffuse |
| Base | Mesh UV0; no texture transform | Texture multiplied by previous color |
| Sphere multiply | Camera-space normal transformed by captured Sphere matrix | Texture multiplied by previous color |
| Sphere add | Same normal/matrix convention | Texture added to previous color |
| PMX subtexture | Mesh UV1 with captured texture matrix | Texture multiplied by previous color |

Each active input's alpha operation is captured/validated as texture alpha
multiplied by previous alpha. Color/alpha arguments are separate typed fields.
The Windows producer checks the expected operations, argument sources, coordinates
and transform flags against the live device. Samplers capture min/mag/mip filter,
Wrap/Clamp addresses, maximum anisotropy and sRGB sampling; the alpha comparison
and reference remain explicit. Base UV0 ignores the stored texture matrix;
normal-derived and UV1 coordinates apply it as a row-vector transform. New API
clip/UV conventions must be handled at the backend boundary.

PMD can store a lone Sphere in its main texture field, placing it in input 1.
With Base plus Sphere, the latter uses input 2. The classifier preserves the old
substring checks for `.sph`/`.SPH` and `.spa`/`.SPA`, including mixed-case `.Sph`
being treated as Base. A separate PMD Sphere field multiplies when it contains
`.sph`/`.SPH`, otherwise adds. PMX modes 0/1/2/3 mean disabled/multiply/add/
subtexture; without Base, Sphere is promoted to input 1. Unsupported PMX modes
are rejected. Subtexture is covered by headless layout tests; PMX rendering has
not been migrated or graphically accepted.

This defines texture/material inputs, not a complete shader pipeline. Vertex
deformation, full light/view inputs, separate alpha blending, stencil state and
multi-pass behavior still need explicit producer contracts before a new shader
backend can replace the model renderer. The current adapter borrows the existing
fixed-function cascade, lighting, transforms and skinned mesh.

## Real-source audit and a measured limitation

`MDS_RHI_MODEL_TEXTURES=1` enables the diagnostic file-source audit and owned
Base/Sphere bindings alongside `MDS_RHI_MODEL_TOON=1`. Existing snapshot,
bone-dependency, effects-exclusion and same-frame pixel gates remain required.
The adapter stays off by default.

Original v1 `sample.pmm` has five active Base/Sphere references across its
17 batches. Four Sphere references decoded to RGBA exactly equal to the old
bound texture. The fifth, **eyeM2.bmp**, decodes to **106x106**, while D3DX's
default load produces **128x128**. It is explicitly `BLOCKED_DIMENSIONS`;
the audit summary is `PARTIAL checks=5 failures=0 blocked=1`. No channel/pixel
parity is claimed for that resource. Its draw remains on the old path.

All original independent batches lack Base/Sphere references; the original
textured batches depend on IK, physics or unsupported bones. Eligibility was
not loosened. For graphical resource validation, CTest modifies **only material
10's 20-byte texture-name field in a temporary copied original PMD**:

| Variant | Temporary texture reference | Owned textures |
| --- | --- | --- |
| Base + multiply Sphere | `eye2.bmp*metal.sph` | Toon, Base, Sphere |
| Base + add Sphere | `eye2.bmp*a3.spa` | Toon, Base, Sphere |
| Multiply Sphere alone | `metal.sph` | Toon, Sphere in stage 1 |
| Add Sphere alone | `a3.spa` | Toon, Sphere in stage 1 |

These use real supplied 32x32, 256x256 and 512x512 BMP resources. Original source
files, geometry, influences and PMM animation remain unchanged. The test scene is
a real-scene-derived configured fixture; it is not evidence that the original
material 10 naturally used these textures or that arbitrary IK/physics batches
are portable. Assets are local external fixtures and are not published by CI.

The first combined comparison had four differing pixels despite equal level-0
RGBA. Its old Base/Sphere textures had `Usage=1024` (automatic Mipmaps), whereas
the adapter had a single level. Preserving linear automatic Mipmap generation
and including that policy in the cache key eliminated the difference.

## Accepted results, September 30, 2026

All four configured variants passed on **x64 and x86**:

| Metric | x64 | x86 |
| --- | --- | --- |
| Batch/frame | slot 2, material 10, frame 5 | identical |
| Index range | first 63381, count 24 | identical |
| Comparison target | 2073600 pixels | 2073600 pixels |
| Same-frame / actual adapter differences | 0 / 0 | 0 / 0 |
| Changed pixels | 11 | 8 |
| Base/Sphere RGBA differences | 0 | 0 |
| Combined texture uploads / cache hits | 3 / 6 | 3 / 6 |
| Sphere-only texture uploads / cache hits | 2 / 4 | 2 / 4 |
| Actual bridge / host / direct calls | 1 / 0 / 1 | 1 / 0 / 1 |

The source audit also retains the separate blocked original 106x106 eye texture
in every variant (`PARTIAL`, zero unexpected failures, one blocked resource).
Blocked textures are not counted as passed comparisons. The original-scene audit
CTest and all configured pixel CTests passed on both architectures. One initial
x86 combined run timed out in missing-model reselection before reaching the main
window; the immediate retry passed. That timeout remains a window-flow limitation.

The original Toon opt-in regression and independent DX9 pixel-parity test passed
on x64. The real v2 `test_1.pmm` material-snapshot regression passed on x64/x86
(25 draws, zero mismatches); PMX rendering stays on the old path. The seven
focused x64 resource/snapshot/dependency CTests passed, and the complete x64
application also builds with `MIKUDANCESTUDIO_RHI_D3D9=OFF`.

Evidence is in `exports/rhi-material-resources-x64-*` and
`exports/rhi-material-resources-x86-*`; each directory retains the source audit,
material snapshot, Toon source/cache report and same-frame/actual pixel report.

The three-platform standalone suite runs four always-available tests. The
original 2x2 fixtures verify Base/Sphere content detection, missing/absent states,
PMD/PMX coordinate/combiner layout, private/shared paths, revisions, upload/bind/
reuse, Mipmap cache policy, reset/device replacement and release. Real material
assets are not needed or skipped. DX9 smoke tests additionally inspect the three
owned GPU bindings/RGBA/Mipmap usage inside the callback, restore every original
binding, reject partial upload, and reupload after device reset on x64/x86.

The user's Linux server passed all four tests with GCC 11.4 in
`/data2/wangjun/github/MikuDanceStudio/material-resource-check-20260930`.
The final [CI run 36711377231](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36711377231)
passed all four tests on Windows (MSVC 19.51), Linux (GCC 13.3) and macOS
(AppleClang 21), with no resource tests skipped. Its source revision is
`ca905c19161021ffbd372398df4a40ba703656c5`, recorded under
`out/resource-ci/materials-remote-run.json`; logs are retained under
`exports/rhi-material-resource-ci.log`. Validation branches contain only the
standalone test dependencies; main and unrelated working changes are not published.

## Next work

The optional [DX9 preparation capability](RHI_D3D9_TEXTURE_PREPARATION.md) now
passes exact RGBA and independent-batch same-frame/actual-draw comparison on
x64/x86. Prepared upload ownership is available through the existing opt-in
adapter gates. The experimental portable filter remains a separate blocked path.

The separate experimental preparation policy and strict rejection gate are now
implemented; see [texture preparation validation](RHI_TEXTURE_PREPARATION_VALIDATION.md).
The real 106x106 -> 128x128 eye preparation still differs by one green channel
in both application architectures and remains blocked. Resolve that filtering/
quantization boundary and validate eligible-draw pixels before admitting it.
Raw decode remains separate from prepared upload data. The standalone resource
suite now has five tests passing on Windows/Linux/macOS in the linked new report.
After that, complete light/view and pipeline inputs and validate a shader-backed
material batch before adding DX11/DX12 rendering.
