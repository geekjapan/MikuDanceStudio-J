# DX11 multiple-material transition acceptance

The adapter uses the existing ordered `SetModelPipeline -> BindTexture ->
DrawIndexed` interface for multiple materials in one frame. Each pipeline change
requires all active texture slots to be rebound. Application rendering remains
DX9; this change does not enable a complete scene renderer or MSAA history replay.

## State isolation fix

The generated transition test exposed a model/HUD bug: `SetFixedPipeline` retained
the prior HUD texture handle while native slot 0 could still contain a model
texture. A HUD draw without a new binding incorrectly passed validation.
Both pipeline setters now invalidate the HUD binding; the fixed setter also
clears logical model slots and native SRVs. The model setter already cleared
native SRVs and its own logical slots. Invalid pipeline requests leave drawing
disabled. The regression requires an unbound HUD draw to fail on every transition.

## Tests

`rhi_d3d11_multimaterial_test` generates 15 ordered material batches with no
external assets:

- Opaque base, a depth-occluded batch, source-alpha blending without depth writes,
  and an opaque batch that must pass after the translucent batch.
- Alpha discard, disabled depth, a restricted color write mask, stencil mark
  and stencil-equal drawing.
- Toon/Base/Sphere addition, switching to untextured constants, and restoring
  all three texture stages with multiplication.
- Point wrap, point clamp, and linear filtering of a two-texel texture.

Before every model batch a fully clipped HUD triangle exercises shader, input
layout, sampler and texture transitions without changing the expected image.
The test requires missing bindings, obsolete epochs and foreign device identities
to be rejected. Every prefix is redrawn from clear and compared across the entire
image with an independent CPU rectangle/color/depth/stencil oracle. The oracle
does not invoke RHI shader evaluation or attempt to fit native interpolation.

Each run covers 64 -> 80 -> 64 targets on each of two native devices, uploading
the same CPU resources to the replacement. This gives 90 prefix comparisons per
run. x64/x86 each passed Hardware and WARP: **360 whole-image prefix comparisons,
zero differing pixels**, including repeated-size and replacement equality.

An exploratory two-texel linear-filter midpoint with endpoint 255 yielded 127
on hardware and 128 on WARP. The gating fixture uses endpoint 254, whose midpoint
is integer 127, to isolate sampler/state switching from half-byte quantization.
No shader precision workaround or image tolerance was introduced. The original
observation remains a precision diagnostic, not an equivalence claim.

The real PMM adapter test now submits two additional material variants using
the captured geometry before restoring the original material: three texture
stages with different constants/sampling, followed by an untextured variant.
These control draws cannot modify color/depth/stencil. They check restoration
against the existing independent DX11 image, not real-scene occlusion history.
Both architectures, both target sizes and all 24 adapter images still match the
reference exactly; DX9 counts are separately zero for these saved single batches.
This does not claim multiple distinct captured PMM materials were replayed.

Five CTests passed without skips on each architecture: two multi-material,
two lifecycle, and one external PMM adapter test. Evidence is in
`build-{x64,x86}/build/dx11-multimaterial-evidence` and
`rhi-model-adapter-evidence`. Run:

```powershell
$env:MDS_RHI_MODEL_CAPTURE = (Resolve-Path 'exports/rhi-real-dx11-device-single-control-x64/real_batch.capture').Path
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^rhi_d3d11_(multimaterial_|lifecycle_|model_adapter)'
```

## Boundary for the next history step

The initial [versioned model prefix implementation](RHI_MODEL_REPLAY.md) now
implements the model-only, single-target subset below and validates it at every
generated draw boundary. The full native application capture remains pending.

The existing `rhi_history_replay.cpp` recorder holds DX9 native state/resources;
it is not a portable DX11 command stream. The current batch capture's optional
color/depth data cannot stand in for a complete ordered scene prefix. Keep
`HistoryCapabilities::completeDrawReplay` false and continue rejecting history
and MSAA in the model adapter acceptance.

The next step is to serialize an immutable, versioned single-sample prefix from
clear, with explicit target descriptions, geometry, mip data, pipeline/constants,
and draw order. Validate the entire prefix before submission; report the first
unsupported operation (including target changes or vertex layouts outside the
implemented subset). Compare at each draw boundary before accepting full-scene
replay. Shadows, ground, accessories and MME must be represented or block the
prefix; omitting them cannot produce an accepted history. MSAA remains a separate
gate after single-sample replay works.
