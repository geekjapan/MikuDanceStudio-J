# Versioned single-sample model prefix replay

`rhi_model_replay.hpp` defines a CPU-owned ordered command stream. It has no
Win32 or native GPU handles. The DX11 adapter implements
`ReplayD3D11ModelPrefix(device, stream, drawCount, output)` for the explicit model
subset. Application rendering remains DX9 and `completeDrawReplay` remains false:
this is not a recorder for all application rendering operations.

## Ownership, versions and order

- A stream owns copies of vertex/index bytes, exact texture mip data, shader
  constants and pipeline state. Resource keys are `(id, version)`, both nonzero.
  The same key cannot be defined twice, even with identical bytes.
- Events have contiguous sequence numbers. The first event must be a full clear;
  publication events activate immutable resource versions, followed by
  draws. Revisions for an ID must increase, and the resource kind cannot change.
- A draw must reference the currently published version, with matching geometry
  kind and texture sRGB interpretation. Future, missing and superseded revisions
  are errors. Historical draws still retain their earlier snapshots.
- The initial target is explicitly single-sample RGBA8/D24S8, at most 4096 per
  dimension, clear depth 1 and stencil 0. Other targets, additional clears,
  target changes and unsupported operations block replay. Producers must record
  unsupported events instead of dropping them.

The [viewport extension](RHI_VIEWPORT_CONTRACT.md) adds explicit per-draw
position, extent and depth range, plus a known initial-clear region when the
native viewport covers only part of the target. Validation prevents drawing
outside initialized history; no implicit cropping occurs.

The [ground geometry extension](RHI_GROUND_GEOMETRY.md) adds explicit list
topology and mutually exclusive indexed/nonindexed ranges, with resource
version, buffer layout and epoch validation on both submission paths.

`ValidateModelReplay` checks the **entire** stream, including commands beyond a
requested draw boundary. It checks immutable resource definitions, mip sizes,
pipeline/sampling limits, buffer ranges and every referenced index. It returns
the first failing event sequence and reason (sequence 0 denotes stream/resource
definition errors). Completion is a producer assertion, not proof that an
external application's draw hooks captured everything.

The current stream is an in-memory contract, not a durable binary serialization
format. Callers must keep it unchanged during synchronous validation/replay; its
value copies own their data. There is no persistent ID cache that could reuse
different bytes under the same key across streams.

## DX11 execution

Full validation runs before any device mutation. All resource snapshots are then
uploaded into private handles before target reconstruction. Replay rebuilds the
offscreen target (advancing epoch), clears once, and issues draws in order up to
the requested boundary. No intermediate image is used to replace depth/stencil
history. Replaying each prefix independently allows readback after EndFrame
without adding presentation boundaries or clearing between its draws.

Uploads are released on exit and recreated on the destination device for the
next replay. This deliberately simple diagnostic path does not yet cache uploads
between prefixes. Resource allocation/native device failures are reported, never
accepted as partial replay. A runtime failure after reconstruction may leave a
partially rendered target; callers must discard it and rebuild/retry. Invalid
streams fail before reconstruction, preserving the previous image and epoch.

## Verification (2026-10-03)

The generated multi-material test publishes fresh versions under the same three
logical texture IDs as successive draws change materials. It compares each of
15 replay boundaries with direct RHI submission and an independent CPU image
oracle. This covers color, depth occlusion, disabled depth writes, alpha discard,
translucent blending, stencil marking/testing, color masks, texture-stage changes
and sampler changes. Full RGBA images are compared; depth/stencil contents are
verified through subsequent draws rather than native attachment readback.

Hardware and WARP on x64/x86 each run two native devices and 64 -> 80 -> 64 target
sizes: 90 prefix comparisons per configuration, **360 replay images with zero
differences**. Logs identify draw boundary, event sequence and batch label; a
mismatch reports the first pixel and writes direct/replay RGBA evidence.
An unsupported final command blocks even a request for the first draw, with
unchanged image and epoch.

The platform-neutral `rhi_model_replay` CTest checks incomplete streams, invalid
targets, missing clear, broken sequences, unsupported operations, late/old
versions, duplicate keys, invalid mip data, index bounds, unsupported sampling,
sRGB mismatch, owned snapshot copies and UInt32 indices. It is part of the
formats-only test graph and does not need Windows or an external asset.

The saved real PMM material-13 capture also passes through this replay entry.
x64/x86, original/larger targets, device replacement and repeated rebuilds produce
24 images equal to the direct adapter and independent DX11 baseline. This remains
a single captured material, not the application's full preceding scene history.
DX9 differences are separately zero for these single-sample captures; the DX9
8x MSAA issue is unchanged. Linux/macOS execution was not performed here.

Run the following after building the corresponding test targets and setting
`MDS_RHI_MODEL_CAPTURE` to the architecture's saved version-5 independent capture:

```powershell
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^(rhi_model_replay|rhi_d3d11_(multimaterial_.*|lifecycle_.*|model_adapter))$'
```

Evidence stays in each build tree's `dx11-multimaterial-evidence` and
`rhi-model-adapter-evidence`. The next producer integration must translate the
native DX9 recorder into these owned snapshots and mark every unsupported draw
or target operation. Shadows, ground, accessory layouts and MME are not silently
converted. Whole-scene history capabilities must remain disabled until that
capture is complete and all draw boundaries pass.

The [DX9 recorder conversion](RHI_DX9_PORTABLE_CAPTURE.md) now supplies owned
snapshots for the supported subset. The later viewport, null-texture, Mip and
[projected-shadow work](RHI_PROJECTED_SHADOW_COLOR.md) now validate the captured
49-draw real-PMM prefix with diagnostic shadow admission. Native reconstruction
is exact at every recorded boundary. DX11 scene images still fail first at
accessory draw 2; whole-scene history capabilities remain disabled.
