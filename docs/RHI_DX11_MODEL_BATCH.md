# DX11 RHI independent model batch

The optional DX11 adapter now draws one captured PMM material batch through
RHI buffers, constants and texture handles. The editor still renders with DX9.
This acceptance uses saved captures, not a new live application capture.

## Contract

`rhi_model_pipeline.hpp` defines `ModelPipeline`: portable material shader inputs,
raster state, independent color/alpha blend operations, depth/stencil and color
write masks. `Device::SetModelPipeline` defaults to unsupported on other backends.
The DX11 implementation validates it before creating native state. A rejected
pipeline invalidates readiness, preventing accidental reuse of prior state.

Model vertices use PositionNormalUv (32 bytes). Index buffers support UInt16
and UInt32; submission checks the index range, addressed vertex range, device
identity and epoch. Shader constants contain world/view/projection transforms,
material and directional lighting inputs. The embedded shaders come from the
same checked-in HLSL as the independent DX11 reference; buffer upload, state
translation, resource binding and command submission are separate implementations.
Thus exact images validate integration, not an independent proof of the shader
lighting equations.

`CreateD3D11ModelTexture` accepts RGBA mip levels or one base level with generated
mips, with explicit linear/sRGB interpretation. Base, Toon and Sphere bind through
the shader's three texture roles. Missing active textures and mismatched sRGB
views reject drawing. Resize retains buffers/textures. Device replacement creates
new handles by uploading the same caller-owned CPU mesh and mip data.

`ResizeD3D11Offscreen` owns a single-sample RGBA8/D24S8 target (maximum 4096 per
dimension). It stops submission, clears bindings, drains work, releases target
views, creates the new target and advances the epoch. `ReadD3D11Offscreen` performs
staging readback; this is a backend test service, not a general portable render
pass or arbitrary render-target texture API. The swapchain keeps its presentation
description independently, and can rebuild back to presentation after offscreen
use. A retired device cannot be resurrected by offscreen resize.

Unsupported inputs fail closed: secondary mesh UV, unsupported enum values,
missing depth attachment for depth/stencil work, and invalid geometry. The capture
adapter gate rejects previous-scene history, MSAA and reference-only shader
variants. Fog, user clip planes, depth bias, MME, skinning and general shader
creation are outside this contract. Dynamic buffer updates remain whole-buffer
DISCARD only.

## Acceptance on 2026-10-03

Local version-5 captures of sample.pmm, frame 5, model slot 2, material 13 contain
112 triangles (336 indices starting at 64731), fixed geometry, camera, lighting
and texture data, without previous-scene history. Assets/captures are not added
to the repository.

| Build | Original target | Larger target | RHI vs reference DX11 | DX9 vs reference DX11 |
| --- | --- | --- | --- | --- |
| x64 | 1032 x 774 | 1048 x 790 | 0 differing pixels | 0 differing pixels |
| x86 | 825 x 618 | 841 x 634 | 0 differing pixels | 0 differing pixels |

Each size runs two separately created devices and three drawing cycles per
device, including a resize away and back. All 24 adapter images exactly match
their corresponding independent DX11 baseline. Old-epoch submissions, old-device
identities with new handles, invalid index ranges and retired-device restoration
are rejected. DX9 differences are reported independently and do not gate adapter
integration; these zero counts do not close the separate DX9 8x MSAA issue.

Both architectures passed all three CTests without skips: real model adapter,
hardware lifecycle and WARP lifecycle. The two lifecycle tests also generate an
indexed model triangle with three texture roles, check unsupported UV/missing
texture rejection and compare images after offscreen resize. The real PMM batch
test uses hardware; no real PMM WARP equivalence is claimed. Linux/macOS execution
is outside this Windows backend test.

## Reproduce

Enable `MIKUDANCESTUDIO_RHI_D3D11` and `MIKUDANCESTUDIO_RHI_D3D9`; the latter builds
the independent DX9/reference DX11 comparison program. Build
`rhi_d3d11_real_batch_test` and `rhi_d3d11_lifecycle_test`, then run:

```powershell
$env:MDS_RHI_MODEL_CAPTURE = (Resolve-Path 'exports/rhi-real-dx11-device-single-control-x64/real_batch.capture').Path
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^rhi_d3d11_(model_adapter|lifecycle_)'
```

Use the corresponding x86 capture/build for x86. The optional external-capture
test skips with code 77 if no fixture is supplied; the generated model lifecycle
cases need no external material. `tools/run_rhi_model_adapter.py` records two
sizes in `rhi-model-adapter-evidence/acceptance.json`, with reference/adapter RGBA
images and native reports in `original` and `larger` subdirectories. Evidence is
ignored build output. Extend coverage to multiple materials and command history
before considering an application rendering switch.

The following [multi-material acceptance](RHI_DX11_MULTIMATERIAL.md) adds
generated overlapping batches, HUD/model transition checks and material-state
priming before the saved real batch. Full captured scene-history replay remains
outside that acceptance.
