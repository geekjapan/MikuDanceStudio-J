# Model viewport and initialized-region contract

`ModelPipeline::viewport` now carries `ModelViewport`: integer top-left target
pixel position, width/height, and floating min/max depth. An absent viewport
means the full current target and [0,1] depth; it never inherits an earlier draw.
Positions and dimensions must fit the target without overflow, dimensions must
be positive, and finite depths must satisfy 0 <= min <= max <= 1. Equal min/max
is allowed. Fractional origins, reversed ranges and out-of-target views are
outside this subset.

The DX9 converter copies all six viewport fields. DX11 calls RSSetViewports for
each model pipeline and maps clip depth [0,w] into the requested range. The
existing DX9 half-pixel compatibility adjustment uses **viewport** width/height,
not backbuffer dimensions. Changing to HUD explicitly restores the full target
and [0,1], so model viewport/depth state cannot leak into HUD drawing.

## Clear coverage is separate from viewport mapping

DX9 Clear with no rectangles is constrained by the native viewport. For a scene
inside an editor backbuffer, this does not establish the pixels outside that
rectangle. `ModelReplayStream::initializedRegion` explicitly describes this
known rectangle (only its pixel bounds govern coverage). Absent means the full
target is initialized. Every draw viewport must stay within the known region;
otherwise validation returns `draw_outside_initialized_region` before touching
the device. The clear's depth remains 1 and stencil remains 0, independently of
the viewport's draw depth range.

Replay keeps the full target size and returns a full-size image. It initializes
the diagnostic allocation outside the known region deterministically as well,
but those outside pixels are **unspecified with respect to the captured scene**
and must not be included in an equivalence claim. No prior outside color/depth/
stencil is captured or inferred, and this subset cannot sample those attachments.
This is a bounded history contract, not an implicit crop or a complete editor
backbuffer transfer. Generated tests with full initial clears compare every pixel.

## Verification on 2026-10-03

`rhi_d3d11_viewport_{warp,hardware}` draws overlapping constant-color rectangles
and compares full RGBA targets with a CPU oracle. It checks offset/size changes,
depth-range occlusion, returning to a default full viewport, invalid-view rejection
without changing target/epoch, regional-history bounds, and a visible HUD pixel
outside the previous model viewport. Runs cover 64 -> 80 -> 64 targets and two
devices per driver. x64/x86 Hardware/WARP passed: **96 complete viewport images
with zero differences**, plus HUD/invalid-input controls.

Both application builds passed. Eight focused CTests per architecture passed
without skips: viewport, multi-material and lifecycle Hardware/WARP tests, CPU
native-snapshot conversion, and portable command-stream validation. Existing
multi-material prefix images remain exact. No Linux/macOS run was performed.

The native DX9 conversion test also now has five viewport cases, including equal
depth endpoints. Its initial x64 GPU execution failed **at DX9 device creation**,
HRESULT `0x8876086C` (D3DERR_INVALIDCALL), before any viewport draw. The real PMM
GUI attempt likewise stopped at CreateDevice with this HRESULT. RDP reported
Active, while independent DX11 Hardware/WARP succeeded. This observation does
not establish the cause of the DX9 failure. That attempt was not accepted;
the subsequent successful device retry is recorded below.

### Retry after device availability returned

On the user's retry, all four native DX9/DX11 viewport tests passed (x64/x86,
Hardware/WARP): five scenarios, two DX11 devices, three prefix comparisons each,
**120 full-image comparisons with zero differences**. Equal depth endpoints,
offset/size switches and depth-range occlusion are now checked against native
DX9. Both saved independent real-PMM adapter CTests also passed again.

Fresh real sample.pmm GUI runs loaded on both architectures and recorded the
same 49 preceding draws. Native DX9 replay before material 13 differed by zero
pixels. The scene viewport was accepted; portable admission then stopped at
draw 1 (event sequence 2), an accessory with `unbound_active_texture_stage`.
Exit 31 is conversion rejection, not a successful whole-scene gate.
No complete DX11 scene image was produced. Native after-material history is
not claimed by the before-material prefix report.

The per-draw isolated audit was identical on x64 and x86:

| Phase | Draws | First unsupported condition per draw |
| --- | --- | --- |
| Accessory | 12 | Active texture stage has no bound texture |
| Accessory | 7 | Texture format, mip generation or LOD outside the subset |
| Projected shadow | 17 | Geometry layout/base outside the subset |
| Model material | 5 | Texture format, mip generation or LOD outside the subset |
| Model material | 8 | Convertible in isolation; not admitted after a broken prefix |

No ground-phase draw occurred in this captured prefix, so ground rendering is
still unverified. These counts classify conversion support, not pixel equality
for isolated draws. Current evidence is in
`exports/portable-viewport-retry-{x64,x86}` and
`exports/portable-viewport-retry-summary.json`; the earlier device failures are
retained separately. The next work is to establish native null-texture cascade
behavior, then admit that behavior with focused image tests before addressing
the later texture and projected-shadow boundaries.

## Ground, shadow and accessory diagnostics

The fixed renderer labels background, ground, accessory, projected-shadow,
model-material, outline and accessory-tail phases in the recorder. After a
portable prefix first blocks, subsequent captured draws can be audited in
isolation as `PORTABLE_AUDIT`; those successes never repair or admit the broken
prefix. Shadow-map target switching retains its explicit unsupported gate.

Archived real PMM reduction snapshots can be checked without a DX9 device:

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --audit-reduction `
  exports/rhi-real-dx11-reduction-x64-ten/history_replay.reduction.draw1.state
```

The loader uses the saved geometry bytes, matrices, lighting, native states and
matching index-format log. It rejects textured archives whose older export lacks
texture descriptors. It audits a single snapshot in local bounds enclosing its
viewport and does not assert completeness of a scene prefix.

Saved accessory draws 1-7 (XYZ/normal/UV0, FVF 274) now pass viewport validation,
then block with `unbound_active_texture_stage`: native stage 0 is enabled but has
no texture resource. This distinct fixed-function behavior still needs a native
control before conversion is admitted. A null texture is not reported as a file
decode failure and is not silently replaced by a white texture. Ground and
shadow DX11 images remain unverified after the retry described above.

Evidence: `exports/portable-viewport-x64.gui.log` records the failed live launch;
`exports/portable-viewport-archived-x86.log` records offline snapshot checks.
CTest logs remain under their build trees. The previous 49-draw DX9 result in
RHI_DX9_PORTABLE_CAPTURE.md predates this change and is not a new viewport pass.

```powershell
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^(rhi_model_replay|rhi_d3d9_replay_conversion|rhi_d3d11_(viewport_.*|multimaterial_.*|lifecycle_.*))$'
```

The viewport/device retry is complete. Only after checking null-texture stage
semantics and each later recorded operation should the full
scene prefix be admitted. The application remains on DX9 and MSAA is unchanged.

The subsequent [native null-texture control](RHI_DX9_NULL_TEXTURE.md) now has a
dedicated 48-case CTest. Its first x64/x86 execution was blocked at DX9 device
creation while RDP was disconnected. After reconnection both native suites
passed, and canonical null-stage termination is now converted. Hardware DX11
controls pass; WARP retains a one-byte shading mismatch also present with
explicitly disabled stages. See that document for the current acceptance
boundary; this does not admit the complete scene prefix.

The subsequent Mip and [projected-shadow capture](RHI_PROJECTED_SHADOW_COLOR.md)
work now validates the diagnostic real-PMM 49-draw prefix. Native DX9 images
match at all recorded boundaries. Full-prefix DX11 images diverge first at
accessory draw 2 on both x64 and x86; viewport transport acceptance does not
imply image parity. The application remains on DX9.
