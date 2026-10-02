# Portable resource and device lifecycle boundary

`Device::Status()` exposes adapter identity, epoch and reset-protocol state.
Unknown/zero is the conservative default for an adapter without this contract.
Ready means the wrapper accepts operations under its reset protocol; it is
not a GPU-health query or a promise that Present cannot fail.

`ResourceLifecycleFeatures()` reports implemented behavior, independently of
shader/history hardware features. Null and DX9 currently report reset support,
retained static buffers and existing RGBA8 textures, and invalidated dynamic
buffers. They do not own the native device reset. Unsupported adapters default
to all false. This contract does not cover render-target textures, fences,
async resource retirement, swapchain recreation or full native-device replacement.

## Reset ordering

1. Finish frame operations; call PrepareForReset outside a frame.
2. A successful prepare enters ResetPending, blocking resource and frame work.
   Dynamic-buffer generations are invalidated. Epoch has not advanced yet.
3. The Windows application performs native DX9 Reset. Failure must leave the
   adapter pending; it must not publish a successful restore.
4. RestoreAfterReset checks the native cooperative state. Only success returns
   the adapter to Ready and advances its nonzero epoch.
5. Recreate transient buffers and rebuild submissions. Retained resource handles
   remain valid; stale transient handles and old submission identities do not.

`IsCurrentSubmission` verifies nonzero device identity/epoch and Ready state.
A submission token from another adapter or an earlier epoch is invalid even
if retained resource handles still work. Device identity changes on wrapper
replacement. Both Draw and DrawIndexed reject missing, foreign and stale tokens before
issuing a native draw. Record stamps a command at recording time; it must not
be used to refresh an old command at execution time. Borrowed DX9 overlay
and model adapters validate their immediate submissions at the native boundary.

Null tests exercise invalid transitions, repeated reset cycles, retained and
transient handles, and stale submission identities. The DX9 test checks the
same query contract around actual native Reset and existing retained texture /
buffer use. Existing asset and texture preparation tests cover cache reuse
and resource access across reset. Portable core changes do not depend on Win32.

## Migration boundary

Native interpolation remains the production renderer's behavior. Portable
analytic shading remains diagnostic until image-equivalence gates pass.
Lifecycle capability support is not evidence of shader/MSAA parity. This
change neither adds a rendering backend nor enables a material adapter path.

AtlasTextureCache and MaterialTextureCache track the upload device and epoch.
Get blocks while ResetPending, reuses retained textures, and rebuilds invalidated
textures from the supplied decoded CPU asset. A backend declaring
retainsTextures=false must invalidate texture handles on successful reset.
Rebind releases the old device's resources before changing the device pointer;
call it outside a frame while both devices are alive. Release failure leaves
the cache on the original device and returns false. Decoded CPU assets remain
caller-owned and are passed to Get again after replacement. Cache ownership
must end before the bound device is destroyed. Native application replacement
still rebuilds its borrowed adapter wrappers.

Swapchain and device-replacement contracts are defined below.
DX11/DX12/Vulkan/Metal lifetimes must be declared from actual implementations,
not inferred from DX9 managed-resource semantics. CPU source bytes remain the
portable authority for rebuilding uploads after full device replacement.

## Validation for this change

Windows Release x64/x86 builds succeeded. Each architecture ran and passed
six CTests without skips in the final run: rhi_d3d9, rhi_d3d9_parity, rhi_null,
rhi_assets, rhi_material_textures and rhi_texture_preparation.
The DX9 test exercised native Reset, rejected a recorded pre-reset draw with
retained geometry, reused a cached texture without another upload, then drew
with a newly recorded submission. Pixel parity regression also passed.
Null tests reject stale indexed and non-indexed submissions. Asset tests cover
retained cache entries, blocked access while pending, an eviction backend that
requires CPU reupload, device rebinding, and drawing after recovery. Material
cache tests cover retained entries and rebinding too.

The initial GPU run skipped device tests; after the environment recovered,
the final x64/x86 runs and direct DX9 test executions succeeded. No
Linux/macOS execution was performed in this turn; these headless tests run
on Windows here and remain available in the existing portable CI matrix.


## Swapchain contract (optional DX9 controller)

`rhi_swapchain.hpp` is platform independent. `SwapchainDesc` contains an opaque
window token with its window-system tag, explicit pixel dimensions, RGBA8 color,
optional D16 or D24S8 depth, sample count and quality index, windowed mode, and
Immediate/VSync presentation. Zero dimensions are not silently translated into
native defaults: minimize pauses presentation; rebuild after a nonzero resize.
Quality is backend-local and does not identify sample locations across APIs.

`Swapchain::Query(desc)` checks the complete tuple, including depth/color MSAA
compatibility and quality count. Unsupported descriptions are rejected before
preparing resources. DX9 queries the actual adapter/device type, display format,
presentation caps, depth matching and both color/depth multisample quality counts.
It supports a windowed single-backbuffer discard swapchain, or single-sample
Copy presentation; RGBA8/XRGB8 and D16/D24S8/D24X8 map explicitly.
Fullscreen, nonmaskable MSAA and unrepresented native flags are rejected. Query
support does not guarantee successful allocation, or image equivalence to DX11.

`CreateD3D9Swapchain(device, native)` attaches to the existing primary swapchain.
The caller must supply the adapter wrapping that same native device. The Device
must outlive its controller. The controller retains a native reference and owns
Reset sequencing only when explicitly invoked. The editor keeps its original Reset calls by default. The optional application
integration below delegates Reset only when explicitly enabled. Application
code must release its own default-pool surfaces, state blocks and other borrowed
resources before invoking Rebuild; the controller only releases adapter resources.
All native operations run on the device creation thread, outside a scene.

| Event | Action | Completion |
| --- | --- | --- |
| Resize | Validate tuple; stop submissions via PrepareForReset; release transient resources; native Reset | Restore publishes new epoch; recreate dynamic buffers; record fresh draws |
| Temporary loss | Prepare even when native unbinding reports device loss; poll cooperative state | Lost returns RetryLater with submissions blocked; Resettable permits retry; successful Reset alone permits restore |
| Complete replacement | Release or rebind caches while old device is Ready when possible; Retire old controller | Application creates a new native device and adapter with a new identity; upload CPU assets and rebuild all submissions |

`Health` distinguishes native Ready, TemporarilyLost, Resettable, Removed and
Unknown. Adapter `DeviceStatus::Ready` remains protocol state, not a GPU health
probe. Rebuild returns Busy inside an active frame without releasing resources.
Native failure keeps ResetPending and does not advance epoch or publish the new
description. `LastNativeError` exposes the most recent Reset HRESULT for logging;
portable control flow uses RebuildResult. A retired controller is terminal.
Device replacement is never disguised as a successful Reset on the old identity.

Managed DX9 textures/static buffers survive successful Reset; dynamic buffers do
not. Reapply pipeline, texture and sampler state after Reset. Replacement retains
CPU data only, not old GPU handles. If loss already prevents Rebind, discard old
cache/adapter owners and construct caches for the replacement device using the
same CPU assets; do not pretend the old upload remains usable.

The new `rhi_d3d9_swapchain` CTest exercises seven resize/reset cycles (64, 96, 80,
64, 96, 80, 64), rejection inside an active frame, stale submissions, retained
texture upload count, explicit HUD state reapplication, full image readback and
identical images whenever dimensions repeat. It also exercises the temporary-loss
recovery entry while the native device is cooperative, then creates a second
native device, rebinds the cache, retires the old controller and compares the
restored image. Actual driver loss and RetryLater cannot safely be forced by this
test and remain unverified; it does not reset drivers or disconnect RDP.


Validation of the swapchain change: Windows Release x64 and x86 builds succeeded.
All seven focused CTests passed on each architecture without skips: d3d9_swapchain,
d3d9, d3d9_parity, null, assets, material_textures and texture_preparation. The
new test verifies real client-area resize, repeated full-image equality and native
device replacement, and deliberately keeps a backbuffer reference to verify
Reset failure remains pending until the reference is released. Its control batch
explicitly disables lighting, culling and stencil instead of borrowing HUD state.
The portable header is also compiled by rhi_null_test in the headless resource CI.
No Linux/macOS run or genuine GPU-loss event was performed for this change.


## Application integration (default off)

Set `MDS_RHI_SWAPCHAIN_CONTROLLER=1` before launching the Windows application
with the DX9 adapter compiled in. `MDS_RHI_SWAPCHAIN_LOG` selects an append-only
log containing reason, phase, requested width/height, native color/depth formats,
MSAA type/quality, swap effect, interval, window, HRESULT, adapter identity,
epoch and state. Unsupported native parameter tuples stop the opt-in path;
there is no implicit parameter change or fallback after resources are released.
The switch is intended to be selected at launch. Diagnostic comparisons change
it on the render thread; disabling it during a pending failure is not recovery.
No UI or binary-layout fields were added to MMDApp or D3DRenderer. Side-table
owners are released by ShutdownCleanup before the renderer is destroyed.

The only production native `IDirect3DDevice9::Reset` call is PostDeviceReset;
other `Reset` calls found in DirectShow sources reset enumerators, not the GPU.
All callers therefore share the integration:

| Caller | Purpose |
| --- | --- |
| frame_driver.cpp | Still-picture completion/resizing and device-loss recovery |
| pump_edit_keys.cpp | Adopt changed canvas/viewport size |
| command_view_menu.cpp | Picture render and canvas-size dialog |
| avi_record_start.cpp | AVI recording setup |
| record_readback.cpp | Recording readback/size adjustment |
| late_ports.cpp | Recording completion and window-size restoration |

Resource/notification order is preserved: release application capture texture,
AVI background texture/surface, capture render target/system surface; release
renderer capture/depth/backbuffer/shadow/HDR/shadow-depth surfaces; D3DX effect
OnLostDevice; MME OnLostDevice; discard borrowed overlay cache, history replay
state blocks/resources and model-comparison resources; prepare adapter resources;
native Reset; MME OnResetDevice; InitRenderStates and shadow-menu render state;
D3DX effect OnResetDevice; viewport refresh. Managed model/Toon/font/sprite
resources remain retained; default-pool targets are reacquired lazily by their
existing producers. Transient comparison state blocks cannot span Reset: replay
and comparison invalidation happens before it. The integration does not impose
new lifetimes on untracked third-party resources.

The opt-in failure path performs lost notifications/releases only once across
retries. Failure leaves rendering blocked and does not issue MME/D3DX reset
notifications. FrameDriver polls recovery on later frames instead of entering
the legacy blocking wait. RenderFrameScene also guards its native scene entry.
Minimization suspends FrameDriver while the opt-in switch is enabled. A D3DX
restore error also leaves application rendering blocked. MME notification has
no HRESULT in the existing bridge, so callback invocation/order is checked,
not claimed as proof that arbitrary external effects have recovered.

Adapter/device replacement is detected by native pointer change; old owners and
borrowed overlay caches are retired before attachment to the replacement. The
application itself still creates the native device. Native full replacement was
covered by the standalone test, not forced on a loaded application in this turn.
The default-off legacy path retains its original reset-failure behavior; the
new stop/retry protocol is an opt-in behavior.

### Real PMM verification and remaining gate

`tools/run_application_swapchain.py` uses the existing GUI relocation harness
and real distribution `sample.pmm`, its three models and accessories. Two missing
model references are graphically resolved to their original resources. Physics
is frozen for comparison; no scene frame advance occurs between the four images
of each comparison. The sequence resizes the real client window and backbuffer
through 960x720, 1100x800, 960x720, 960x720, 1100x800, 960x720, and minimizes and
restores the window midway. Each size executes two legacy resets/renders and two
controller resets/renders, records full BGRA images, rejects the previous epoch,
and enables the existing RHI HUD sprite cache. Upload count is exactly one after
each cache invalidation/rebuild (four uploads in each four-image group).
MME remains in the application's scene/reset bridge; model rendering is unchanged.

The diagnostic also holds a backbuffer reference to deliberately make Reset
fail, verifies blocked rendering and unchanged epoch, releases it, then recovers.
The callback log must not contain reset/restored notifications between failure
and native success. Minimize suspends rebuilding; restore resumes the sequence.
This forced failure is not a real driver-loss event.

Windows Release x64/x86 and x64 with both diagnostics and DX9 RHI disabled build
successfully. Real-PMM single-sample controls passed on x64 and x86: six groups,
zero differing pixels including both native repeats, restored HUD uploads and
failure recovery. Local evidence lives in
`exports/application-swapchain-final-single-x64-retry2` and
`exports/application-swapchain-final-single-x86`. Earlier x64 attempts encountered
startup/GUI availability failures; these are kept as failed evidence.

**Default 8x MSAA image acceptance remains blocked.** The first x64 comparison
had 509 different pixels. The added repeat control measured 374 pixels between
two legacy resets, 606 between controller repeats, and 535 between the second
legacy/controller images. Those nonzero results are not an adapter acceptance.
Subsequent final x64/x86 default-MSAA launches failed before scene loading;
the native 8x capability probe reported `D3DERR_NOTAVAILABLE` (0x8876086a) on
TITAN Xp. The source of the earlier repeat differences has not been isolated by
this lifecycle test. No precision fitting or shader change is applied to mask it.
Keep the application controller disabled by default until the native MSAA
baseline is stable and both architectures pass the exact image gate.

Focused CTests: x86 passed all seven without skips; final x64 passed six, with
rhi_d3d9_swapchain skipped on unavailable device creation. The same x64 standalone
swapchain executable also ran successfully earlier in this turn. No skipped GPU
case is counted as a pass. Linux/macOS were not run, and genuine device loss,
fullscreen, recording/export and third-party MME effects remain separate GUI
regressions; only the listed resize/minimize/rebuild scenario was exercised.

```powershell
$env:MDS_PMM_GUI_FIXTURE='C:\Users\jstzw\Downloads\MikuMikuDanceE_v932\UserFile\sample.pmm'
$env:MDS_PMM_RELOCATE_MODEL='Dammy_Bone.pmd'
ctest --test-dir build-x64/build -C Release -R '^rhi_application_swapchain_single_gui$' --output-on-failure
ctest --test-dir build-x64/build -C Release -R '^rhi_application_swapchain_gui$' --output-on-failure
```

Repeat sequentially with build-x86/build. The single-sample control does not
replace the default-MSAA gate. Evidence files and fixture licensing remain
external to the repository.
