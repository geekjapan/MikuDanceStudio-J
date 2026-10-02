# Model material batch preparation and validation

## Boundary

`render::MaterialBatch` now records the material number, index range, diffuse
color, original base/sphere/toon resource references, encoding, default toon
fallback, flags and sphere mode. References retain CP932 (PMD) or UTF8/UTF16LE
(PMX) bytes; the snapshot does not turn them into Windows paths. Model order
comes from PMM's `selection.comboIndex`, with slot as the tie breaker.

`render::MaterialDraw` adds the actual sequence, pass number and portable
`rhi::BatchRasterState`. Document-only snapshots leave `materialDraws` empty.
The diagnostic fixed-function producer fills these records at submission,
where inherited depth, blend and cull state is known. The diagnostic output
also records the borrowed DX9 texture cascades, samplers, alpha/stencil state
and texture binding presence. DX9 compatibility tokens in that report are
not a shader interface for future backends.

`model_material.snapshot` compares every submitted batch with the corresponding
SceneSession resource: vertex/index/material counts, first/count, model order,
diffuse color, base/sphere paths, toon selection/path and material flags. It
checks the unique batch count against the visible nonempty batch count. Paths
are compared after decoding and separator normalization against the runtime's
resolved path suffix, not against an invented absolute source directory.
PMX's absent private toon (`index=-1`) correctly predicts the loader's `0xff`
default-toon marker rather than `0xfe` (a loaded private toon).

## First adapter

The first accepted batch is **Miku_Hatsune_metal.pmd, model slot 2, material 10**
in the real v1 `sample.pmm`, frame 5. Its range is **first=63381, count=24**,
eight triangles. Eligibility walks each indexed vertex's nonzero bone
influences and their parent chains. IK chain sources/targets/links, dynamic
rigid-body influences, invalid bones/cycles and unaudited PMD grant types are
excluded. PMX batches remain unsupported for this adapter until inheritance,
SDEF/QDEF and external-parent dependencies are audited.

`DrawModelBatchInScene` uploads the live XYZ/normal/UV mesh and uint16 indices
into owned RHI buffers, applies explicit portable depth/blend/cull state and
submits through the application callback. It restores all borrowed device
state. Textures, toon/sphere cascades, lights, material constants, transforms
and CPU skinning still come from the legacy runtime. This is a draw-submission
migration, not portable skinning or a complete model renderer.

Same-frame A/B probes clone the live color target and preserve the live
depth/stencil tests while suppressing all depth/stencil writes. **SetRenderTarget
resets the viewport**; the probe explicitly restores the original canvas
viewport on each copied target. Readback occurs after EndScene. A visible
pixel change and zero legacy/adapter differences are required. A subsequent
frame may use the adapter only after both snapshot and pixel comparison pass;
the actual target pixels and exactly one application draw-bridge call are
checked too. Actual pixel/setup failures revoke the gate. Scene loading,
device reset and shutdown clear comparison state and release capture surfaces.

The adapter reports whether its callback already issued a draw. Before
submission, setup failure falls back to the legacy draw; after submission,
failure revokes validation without drawing the same material twice.

## Switches

This application bridge is diagnostic-build-only and off by default.

| Variable | Purpose |
| --- | --- |
| `MDS_RHI_MODEL_AB=1` | Capture and compare fixed-function material batches. |
| `MDS_RHI_LIVE_COMPARE_DIR` | Existing writable directory for reports. |
| `MDS_RHI_MODEL_MATERIAL=10` | Restrict the candidate to the accepted batch. |
| `MDS_RHI_MODEL_ADAPTER=1` | Request the gated adapter; `0` keeps legacy draws. |
| `MDS_RHI_MODEL_NO_MME=1` | Diagnostic fixture startup without registering MME. |
| `MDS_RHI_EVIDENCE_DIR` | GUI test copies reports here before removing its fixture. |

Eligibility requires a fixed-function draw without an active MME interception
path. Acceptance intentionally uses the no-MME diagnostic fixture. It reports
`bridgeCalls=1 hostCalls=0 directCalls=1`; this is not validation of material
effects or deferred MME draw snapshots. Existing MME-enabled HUD and selection
tests remain separate regression coverage.

## Results, 2026-09-30

| Check | x64 | x86 |
| --- | --- | --- |
| Real v1 material snapshot | 17/17 batches, 0 mismatches | 17/17, 0 mismatches |
| Real v2 `test_1.pmm` snapshot | 25/25 batches, 0 mismatches | 25/25, 0 mismatches |
| First model batch A/B | 0 differing pixels | 0 differing pixels |
| Gated actual model draw | 0 differing pixels, one bridge call | 0 differing pixels, one bridge call |

The x64 and x86 comparisons each cover 2,073,600 target pixels, with 8x MSAA.
The accepted batch changes 11 pixels on the x64 canvas (1032x774) and 8 on the
x86 canvas (825x618). These are per-architecture same-frame comparisons;
different viewport sizes are not claimed to produce identical cross-architecture
images. Reports are retained under `exports/rhi-model-x64-final`,
`exports/rhi-model-x86-final` and `exports/rhi-materials-v2-x64/x86`.

`rhi_d3d9` also checks invalid ranges, callback failure and state restoration,
including preventing duplicate submission. Windows x64 passed the eight
focused RHI/snapshot tests (including the fixture dependency); x86 passed the
adapter and bone-dependency tests. Existing x64 real selection, HUD/text opt-in
and v2 multi-model GUI regressions passed. The complete x64 application also
builds with `MIKUDANCESTUDIO_RHI_D3D9=OFF`. One final repeated x86 GUI run
timed out during missing-model reselection before reaching the main window;
an immediate rerun of the same build passed in 8 seconds. This window-flow
intermittency is retained as a limitation, rather than counted as pixel parity.

The user's Linux server built the current portable snapshot and resource code
in `/data2/wangjun/github/MikuDanceStudio/material-portable-check-20260930` with
GCC 11.4. All six focused CTests passed: Null RHI, PNG decode, resource lifecycle,
scene fixture, bone dependency classification and render snapshot.

## macOS resource CI

The existing portable workflow now has a dedicated three-platform `resources`
job using `cmake/rhi-resource-tests`. It always runs `rhi_null`, `rhi_image` and
`rhi_assets`, including asset ID lookup, file/embedded equality, upload/reuse,
revision replacement, stale handles and reupload after device rebuild.

An isolated validation branch published only those test dependencies and the
workflow, without changing main or publishing the unrelated working tree.
[Run 36693985235](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36693985235)
passed on **macos-latest (AppleClang 21), ubuntu-latest and windows-latest**:
three tests each, no skipped resource tests. The full formats job is
intentionally skipped on this dependency-only validation branch; regular
`next` pushes and pull requests retain both jobs. The macOS log is retained
in `exports/rhi-resource-macos-ci.log`.

The first batch can now optionally resolve, decode, upload and cache its Toon
through the portable material resource contract. The borrowed-texture results
above remain the initial baseline; see [owned Toon validation](RHI_TOON_TEXTURE_VALIDATION.md)
for the new RGBA/pixel comparisons and three-platform lifecycle evidence.
Base/Sphere textures, explicit shader inputs and the full model renderer remain
the next boundaries. IK/physics/MME retain their existing implementation.
