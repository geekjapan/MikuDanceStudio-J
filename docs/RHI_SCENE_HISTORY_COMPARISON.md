# Larger real PMM batch with actual scene history

The larger independent material batch now passes a three-way comparison:
the actual application draw, DX9 replay and DX11 replay produce identical
pixels. Both original and controlled translucent configurations pass on
x64/x86. The application remains on the original DX9 draw path.

This acceptance covers **single-sample** history on the tested NVIDIA driver.
The capture uses the DX9 INTZ extension explicitly. Multisample history and
devices without that extension remain separate gates; the earlier isolated
8x MSAA test is not evidence for full MSAA scene history.

## Batch and meaningful controls

Source: the existing real PMM v1 `UserFile/sample.pmm`, relocated through the
normal missing-model GUI. At frame 5, model slot 2/material 13 of
`Miku_Hatsune_metal.pmd` has 336 indices (112 triangles), starting at 64731.
It is 14 times the first eight-triangle batch. Existing dependency checks
continue to classify it as independent of IK, physics and unsupported grants;
MME is disabled for the diagnostic scene.

Two configurations run:

- Original source material, Alpha 1.
- A temporary copied PMD with only material 13 Alpha changed to 0.5. Original
  assets, geometry, animation and dependencies are preserved. This configuration
  intentionally tests transparent blending; it is not an untouched-source claim.

The opaque batch does not change when blending is disabled. Therefore it alone
cannot establish blend acceptance. The translucent configuration must produce
different RGB pixels when blending is disabled. Both configurations must also
produce different RGB pixels when depth testing is disabled. Every control
still compares DX9 and DX11 strictly; differences are not accepted by tolerance.

## Actual history transport

`MDS_RHI_SCENE_HISTORY=1` is a diagnostic-only mode. Device setup selects a
single-sample target. Immediately before the main scene clear,
`PrepareDiagnosticSceneDepth` attaches a same-size INTZ depth texture. The old
DX9 scene then renders normally into that depth/stencil surface. The depth
texture is owned by the bound surface; no static DEFAULT-pool reference is kept
across reset. Capture preflight checks INTZ depth-texture and R32F render-target
support and returns 77 when unavailable.

Before the selected draw, `ReadDiagnosticSceneHistory` reads:

- The canvas's actual RGBA destination pixels, including preceding backgrounds,
  floor/shadow passes and models.
- Actual depth sampled from the INTZ texture into an R32F target, converted to
  packed D24 values.
- Actual stencil values by equality-testing each reference with all depth and
  stencil writes suppressed; the result is packed in the high eight bits.

Reading restores render targets, depth surface, viewport and the captured state
block. Successful capture also requires successful restoration. Neither the
depth nor stencil capture pass writes to the scene's original depth/stencil.
This approach snapshots completed old-runtime results, so earlier IK/physics
evaluation is not moved to the shader backend.

Diagnostic capture schema 5 adds history presence, source color format and
actual software/hardware vertex-processing mode. When history is present, RGBA
and packed D24S8 planes follow the existing geometry/material/texture payload.
This is a local native diagnostic transport, not a public portable scene format.
Its shader-input size and schema version must match the reader. Multisample
history is rejected rather than resolved into a purported equivalent history.

DX9 replay uploads the actual destination color, restores D24 with a depth-output
shader and reconstructs occupied stencil references. DX11 initializes matching
color and D24S8 textures directly from the captured planes. Both then execute
the selected batch with captured depth, stencil and separate blend state.
`before.rgba` must exactly equal the captured color plane.

The application additionally reads its original target **immediately after
the actual selected draw**, before later materials alter the image. This is
`history_live.rgba`. The earlier read-only-depth diagnostic probe is retained as
`history_probe.rgba`; it is not substituted for the actual draw reference.
The normal replay must agree with the application as well as the other API.
No-depth/no-blend controls compare the APIs, not the unmodified application draw.

## Precision correction from the actual reference

The original isolated test created DX9 with software vertex processing. Its
8-bit diffuse profile made that replay agree with DX11, but that result was
limited to the replay's processing mode. In the new translucent test, two such
replays still matched each other while differing from the actual application
at 128 pixels (maximum channel error 1). That mutual match was insufficient.

The application uses hardware vertex processing. Matching that mode and keeping
floating diffuse/Alpha makes both replays agree with its actual draw without
color offsets or tolerance. Accordingly, the capture records
`GetSoftwareVertexProcessing`; the reader chooses the corresponding DX9 mode.
The hardware history profile uses floating lighting. Byte quantization remains
an explicit diagnostic option for software-processing experiments, not a global
RHI default. The old small-batch runner has also been updated to the recorded
hardware mode/floating profile and passes again on both architectures.

## Local acceptance

GPU: NVIDIA TITAN Xp, `10de:1b02`, matching DX9/DX11 device IDs. The x64 canvas
was 1032x774 and x86 was 825x618; each API uses exactly the same input within its
architecture. Different viewport sizes mean the two architectures' whole images
are not expected to match each other.

For both architectures, original and translucent normal replays have:
`differingPixels=0`, `differingChannels=0`, `maxError=0`,
`liveDX9Differences=0`, `liveDX11Differences=0`, and nonzero changed pixels.
The actual application reports `actualAdapterApplied=0` throughout.
Each architecture runs two captures and six replay comparisons (normal,
no-depth and no-blend for each capture). Thus all twelve pairs pass; all four
normal pairs additionally pass the actual-application reference gate.

The tested x64 capture contains 798023 populated depth pixels and stencil
values 0, 1 and 2. Original and translucent normal draws each change 135 pixels.
Disabling depth changes 180 RGB pixels for the original material and 188 for
the translucent configuration. Disabling blending changes 135 RGB pixels for
the translucent configuration and zero for the opaque one. The stencil is
preserved and nonempty, but this material's Always stencil comparison is not
a general test of all stencil operations.

The x86 capture has 509772 populated depth pixels and the same three stencil
values. Original and translucent draws each change 88 pixels. Disabling depth
changes 114 original / 122 translucent RGB pixels; disabling blending changes
88 translucent RGB pixels. `history-acceptance.json` retains the full histograms.
The external-resource evidence is retained in ignored directories
`exports/rhi-real-dx11-history-{x64,x86}-final`; the consolidated independent
verification is `exports/rhi-real-dx11-history-acceptance.json`.
Each comparison includes both raw targets, the actual before color and a report.
The analyzer recalculates differences, maxima and changed pixels, and checks
the actual application reference independently from target bytes.

Validation also retains six focused shader CTests per architecture and the
existing small-batch GUI regression with three configurations/six target pairs
per architecture. All ran locally without skips. This change adds Windows
diagnostics only; no Linux/macOS GPU result is claimed and no new portable-core
change requires replacing the previous portable resource CI evidence.

## Reproduce

```powershell
cmake --build build-x64/build --config Release --target MikuDanceStudio pmm_v1_relocation_gui_test rhi_d3d11_real_batch_test
$env:MDS_PMM_GUI_FIXTURE='C:\Users\jstzw\Downloads\MikuMikuDanceE_v932\UserFile\sample.pmm'
$env:MDS_PMM_RELOCATE_MODEL='Dammy_Bone.pmd'
ctest --test-dir build-x64/build -C Release -R '^rhi_real_d3d11_history_gui$' --output-on-failure
```

Repeat with `build-x86/build`. The Python runner preflights the extension,
removes stale capture/reference files, requires actual native draw equality,
checks that the adapter stayed off, verifies populated history, and requires
measured depth/blend effects. Do not set `--vertex-byte` for this hardware profile.

```powershell
build-x64/build/Release/rhi_d3d11_real_batch_test.exe exports/rhi-real-dx11-history-x64-final/translucent/real_batch.capture exports/rhi-real-dx11-history-x64-final/translucent/history
python tools/analyze_rhi_real_batch.py exports/rhi-real-dx11-history-x64-final/translucent/history --images
```

## Next gate

The [history transfer contract and native MSAA investigation](RHI_HISTORY_TRANSFER.md)
now define exact capabilities and reject resolved-history substitution. Direct
DX9 per-sample transfer is unavailable on the tested path; complete preceding
draw replay remains to be implemented. Preserve per-sample history before extending
this acceptance to the application's normal 8x configuration; a resolved color
image and one resolved depth value cannot replace those samples. Keep the
renderer switch gated on that acceptance and retain the existing DX9 fallback.
