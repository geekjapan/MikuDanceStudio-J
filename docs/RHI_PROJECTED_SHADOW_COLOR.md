# Projected-shadow vertex color input

The current real-PMM portable prefix stops at draw 20: projected-shadow
geometry uses native FVF 66 (`XYZ | DIFFUSE`), stride 16. The earlier accepted
material layout was position/normal/UV0, stride 32. Ground projection can be
singular, so computing a normal inverse for these vertices is inappropriate.

## Contract and implementation

`ModelPipeline.vertexLayout` and each vertex resource's `vertexLayout` now
explicitly select either:

| Layout | Bytes | Attributes |
| --- | --- | --- |
| PositionNormalUv | 32 | float3 position, float3 normal, float2 UV0 |
| PositionColor | 16 | float3 position, RGBA8 vertex color |

The converter preserves positions and swizzles native D3DCOLOR's BGRA memory
bytes into portable RGBA. It checks native draw/index ranges using the selected
stride. The stream validator rejects layout mismatches, malformed buffers and
missing-normal coordinate requests before submission. Layouts can switch in
one stream under immutable resource versions.

The DX11 adapter compiles a separate color-input vertex shader and input
layout. Unlit vertices use their supplied RGBA, independently of the material.
The lit subset selects material or Color1 for diffuse alpha, ambient and
emissive according to `colorVertex` and the four native material-source
selections. Absent Color2 falls back to the material. With no normal input,
the shader uses zero normal, omits directional diffuse/specular contributions,
and evaluates ambient/emissive terms. It neither normalizes zero nor builds a
normal inverse. Projection still uses the original world/view/projection and
viewport half-pixel conversion. No supplied UV means constant UV0 `(0,0)`;
normal-generated coordinates are rejected. Pixel texture cascade, alpha,
blend, depth and stencil states remain explicit.

These missing-attribute/lighting semantics have independent DX11 checks and
native DX9 image acceptance for the controls and first real isolated batch
described below. Passing transport alone still does not accept scene images.

The converter's `allowPositionColor` defaults to false. The application recorder
requires the default-off `MDS_RHI_PORTABLE_SHADOW_CAPTURE=1` to request it.
Application rendering continues to use native DX9; this adds no renderer switch.
Default portable capture stops with `position_color_not_enabled` at that layout.

## Independent controls

CPU checks cover RGBA swizzling, singular position transforms, explicit opt-in,
layout/stride matching, invalid buffers, missing normal coordinates and native
offset rejection. The shared portable replay test includes color vertices so
the new validation can execute without Win32 in existing headless builds.

The DX11-only image oracle covers six material/vertex-color source cases,
bound/unbound textures, an offset viewport, source-alpha blending, strict
depth, a farther shadow rejected by depth, repeated shadows suppressed by
stencil, earlier prefix replay, and two device instances. The oracle independently
computes expected RGBA and rectangle coverage. Both x64 and x86 pass on
Hardware and WARP: **448 exact image checks**, with no native DX9 source required.
The existing viewport/multi-material and CPU CTests also pass (eight focused
CTest results per architecture). Both application/probe builds pass.

The native-versus-converted suite instead draws normal-layout background and
color-layout shadow snapshots through DX9 and DX11, comparing prefixes 1,2,3,1
on two DX11 devices. It has 96 expected images per architecture/driver. Its
first x64/x86 attempts and subsequent x64 retry failed at DX9 `CreateDevice`,
HRESULT `0x8876086C`, before drawing. RDP reported `Active`; that alone did not
make DX9 available. After GPU recovery, both native CTests pass on x64 and x86,
Hardware and WARP: **384 exact images**. Each architecture repeatedly creates
native DX9 devices and compares converted prefixes on two DX11 devices.

Evidence: `exports/shadow-focused-{x64,x86}.log`,
`exports/shadow-color-initial-x64.log`, `exports/shadow-color-x86.log`, and
`exports/shadow-native-retry-x64.log` retain the earlier failures;
`exports/shadow-native-current-{x64,x86}.log` record the successful recovery.
The earlier Mip/native-scene acceptance
in [RHI_DX9_MIP_CAPTURE.md](RHI_DX9_MIP_CAPTURE.md) predates this change.

## Captured real batch

`MDS_RHI_SHADOW_BATCH_EXPORT=1` exports the first FVF-66 snapshot at the selected
history boundary as `history_replay.shadow_batch.state`, `.vertices`, `.indices`
and `.textureN`. The diagnostic state file now contains texture descriptors,
avoiding guesses about format/size/presence. The legacy untextured reader still
rejects texture files without descriptor proof. This is local test transport,
not a portable scene file format.

The earlier x64 live-export attempt failed at application device creation
(GUI fixture exit 5, `CreateDevice Failed!`). The recovered x64/x86 application
now loads real `sample.pmm` after missing-model recovery and exports draw 20:
FVF 66, stride 16, 2,425 triangles. With admission still off, each native
49-draw prefix matches the actual DX9 scene exactly before material 13, while
the portable gate deliberately rejects draw 20 (`position_color_not_enabled`,
GUI fixture exit 31). Both facts are independently logged.

Use the existing relocation GUI harness with mip capture enabled, leave the
shadow-admission switch off, and request this export. Then run:

```powershell
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^rhi_d3d9_shadow_'
ctest --test-dir build-x86/build -C Release --output-on-failure -R '^rhi_d3d9_shadow_'

./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --shadow-archive-hardware exports/shadow-native-real-x64/history_replay.shadow_batch.state
```

The archive test keeps the original geometry, viewport, matrices, lighting,
native state and textures, clears an independent target enclosing the viewport,
and requires a visible batch. A black shadow on a black fixture clear cannot
prove coverage; both backends instead clear to RGBA `(240,224,208,255)`, with
depth 1 and stencil 0. The captured draw and all its states remain unchanged.
It compares native DX9 and converted DX11 images three times on each of two
DX11 devices: **24 exact real-batch images** across x64/x86 and Hardware/WARP.
Visible coverage is 1,519 pixels in the x64 capture and 649 in x86; the GUI
viewports differ, so these are separate same-input comparisons, not identical
cross-architecture images. This establishes an isolated batch, not preceding
scene depth/stencil history. Assets and exports remain ignored.

Evidence: `exports/shadow-native-real-{x64,x86}/`,
`exports/shadow-archive-{hardware,warp}-{x64,x86}.log`.

The prerequisites now permit diagnostic shadow admission for a fresh prefix
run. `MDS_RHI_PORTABLE_DX11_COMPARE=1` also requests per-draw native-vs-DX11
images; it requires `MDS_RHI_HISTORY_TRACE=1`, valid portable capture and exact
native prefix reconstruction. It uses Hardware unless the separate
`MDS_RHI_PORTABLE_DX11_WARP=1` is set. It compares boundaries from clear (draw
zero) through the selected prefix, only inside the explicitly initialized
scene viewport. `PORTABLE_GATE` accepts transport; `DX11_GATE` separately
reports exact image acceptance. GUI exit 32 means the latter failed or was
blocked. First divergent native/rebuilt images are retained for diagnosis.
Both flags default off and application rendering continues on DX9.

## Live prefix result after shadow admission

Fresh single-sample `sample.pmm` runs with both diagnostic flags enabled pass
all 49 portable draws (190 transport events), including projected shadows at
draws 20-36. Each architecture compares 49 native before-draw boundaries plus
the final native prefix, and all native DX9 reconstructions have zero differing
pixels. There is no ground draw in this captured prefix. Material 13's own
draw is after the selected boundary and is not accepted by these checks.

The new DX11 Hardware trace, on NVIDIA TITAN Xp, compares 50 image boundaries
per architecture (clear plus every draw). **Whole-prefix DX11 images fail**:

| Capture | Draw 0 / draw 1 | First divergent draw | Pixels at first divergence | Pixels after draw 49 |
| --- | --- | --- | --- | --- |
| x64, viewport 565,25,1032,774 | 0 / 0 | 2, accessory | 102 | 429 |
| x86, viewport 274,25,670,503 | 0 / 0 | 2, accessory | 9 | 203 |

Both have 48 divergent boundaries and GUI exit 32. At draw 2 the maximum
channel differences are 87 (x64) and 72 (x86), so these are not characterized
as rounding-only mismatches. The first divergent coordinates/values and
cropped native/rebuilt BGRA images are retained. Differences already exist
before the shadow begins; the isolated shadow pass must not be interpreted
as full-scene parity. No tolerance or renderer switch is enabled.

Evidence: `exports/shadow-prefix-dx11-{x64,x86}/history_replay.dx9`,
`history_replay.dx11_first_{actual,rebuilt}.bgra` in those directories,
and `exports/shadow-prefix-dx11-{x64,x86}.gui.log`.

For a fresh GUI trace, combine the usual single-sample model-13 relocation
fixture configuration with:

```powershell
$env:MDS_RHI_PORTABLE_REPLAY='1'
$env:MDS_RHI_PORTABLE_MIP_CAPTURE='1'
$env:MDS_RHI_PORTABLE_SHADOW_CAPTURE='1'
$env:MDS_RHI_PORTABLE_DX11_COMPARE='1'
$env:MDS_RHI_HISTORY_TRACE='1'
```

The next image investigation can isolate accessory draw 2 using its recorded
matrices, states and resource versions. Ground, other scenes and MSAA remain
unaccepted; the default application path stays DX9.

The subsequent [accessory isolation](RHI_ACCESSORY_DRAW2_ISOLATION.md)
reproduces the saved Hardware image exactly and identifies coplanar surface
selection at all high-delta pixels. Native retesting is again blocked by DX9
device creation; no production depth/order change or full-scene acceptance
follows from the offline controls.

Both architecture application/harness builds pass. Six focused CTests per
architecture also pass after adding the clear-only replay boundary: viewport
Hardware/WARP, multi-material Hardware/WARP, native-to-portable CPU conversion
and portable resource/version validation. Evidence:
`exports/shadow-prefix-focused-{x64,x86}.log`. These regression successes do
not override the failed live DX11 image gates above.

The separate WARP lit precision discrepancy and 8x MSAA remain independent
acceptance items.
