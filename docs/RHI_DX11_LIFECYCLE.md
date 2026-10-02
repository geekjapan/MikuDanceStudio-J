# Minimal DX11 lifecycle adapter

The standalone adapter validates the existing portable Device/Swapchain contracts
against a second real backend. It does not select a DX11 renderer in the editor.
The application continues to use its original DX9 path and the independent DX9
8x MSAA image gate remains unresolved.

## Supported boundary

Build with `MIKUDANCESTUDIO_RHI_D3D11=ON` (Windows only). `CreateD3D11Device`
explicitly selects Hardware or WARP, requires feature level 11.0, and returns a
bundle whose swapchain dies before its device. Creation reports the failing
stage, native HRESULT and adapter identification; there is no driver fallback.
Shader/target/validation failures fail the test, rather than being counted as
unavailable hardware. Native unsupported/unavailable/removed device cases can
return the documented CTest skip code 77.

The initial surface supports one windowed discard buffer, RGBA8 linear UNORM,
one sample with quality zero, Immediate or VSync presentation, and optional D16
or D24S8 depth. Fullscreen, other windows, copy presentation, XRGB/D24X8 and MSAA
are rejected. Format support is queried from the actual device.

The implemented drawing subset is a non-indexed triangle list using
ScreenPositionColorUv (28-byte XYZRHW/packed ARGB/UV vertices), a single uploaded
RGBA8 texture and explicit shader modulation. Color channels are converted from
the packed vertex convention in the vertex shader. Point/linear filtering,
wrap/clamp, disabled lighting/stencil/alpha-test, no culling, Always/LessEqual
depth and the existing source-alpha blend rule are supported. All other pipeline
requests fail closed. Indexed/model draws, compute, render-target textures,
generated mip chains, Toon/Sphere and deferred command lists are not advertised.
Dynamic buffer upload uses whole-buffer DISCARD; partial dynamic writes fail.
The adapter exposes shaders but does not expose general shader creation yet.

## Rebuild responsibilities

The creation thread owns the immediate context and all surface operations.
Every frame explicitly reapplies viewport, pipeline and texture binding.
Diagnostic readback occurs after EndFrame and before Present, avoiding undefined
discard-buffer content after presentation.

| Event | Contract |
| --- | --- |
| Resize / repeated surface rebuild | Reject active frames; stop submissions; ClearState; release RTV/DSV/depth references; Flush and drain an event query; ResizeBuffers; create target/depth views; restore and advance epoch |
| Minimize | SurfaceHealth::Suspended; BeginFrame/Present refuse work; rebuild returns RetryLater without releasing resources or advancing epoch; restore permits the normal resize sequence |
| Removed native device | Health reports Removed, drawing refuses work; rebuild requires device replacement, not a successful Reset on the existing device |
| Explicit replacement | Rebind/release caches while the old device is ready; retire old surface; construct a new bundle with new identity; upload CPU data and rebuild submissions |

DX11 resize retains static buffers, dynamic buffers and uploaded textures. The
existing names PrepareForReset/RestoreAfterReset/controllerOwnsReset refer here
to the surface rebuild protocol: DX11 has no native device Reset, and
ResourceLifecycleCapabilities::ownsNativeReset remains false. An external
backbuffer reference makes ResizeBuffers fail with DXGI_ERROR_INVALID_CALL;
resources/submissions stay blocked, the epoch does not advance, and releasing
that reference allows a retry. Target recreation failure also keeps submission
blocked. Device removal is distinguished from surface resize; creation of the
replacement device remains a host responsibility.

GPU drain uses an event query with a bounded five-second wait. Native error or
wait timeout leaves the adapter pending. This small implementation is intended
for isolated tests, not a general asynchronous submission scheduler.

Cache owners must die before whichever device they are currently bound to.
Rebind retains CPU assets but releases old GPU uploads; resize reuses the upload
without incrementing cache upload count. A submission using new geometry but an
old device identity is rejected, as is a pre-resize submission whose geometry
was retained. Retired controllers never resume; a new adapter is required.

## Verification

CTest exposes independent `rhi_d3d11_lifecycle_warp` and
`rhi_d3d11_lifecycle_hardware` tests. Both x64 and x86 passed with no skips on
this machine. Hardware was NVIDIA TITAN Xp (10de:1b02); WARP was Microsoft Basic
Render Driver (1414:008c).

Each test generates its own texture and mesh, performs seven 64/96/80/64/96/80/64
client/backbuffer resize cycles, verifies stale rejection, retained dynamic and
static geometry, exactly one cached upload across resize, minimize/restore,
held-backbuffer failure/retry and full native device replacement. Replacement
requires a second upload from the same CPU pixels. Full RGBA readback is compared
against expected interior/background pixels and repeated-size reference images.
The final 64, 80 and 96 images were byte-identical across all four runs
(x64/x86 times Hardware/WARP). This is evidence for the generated unlit batch,
not for model materials or MSAA equivalence.

The complete fresh x64 formats-only build ran 27 CTests: 26 passed, and the one
external-PMM test skipped because no external fixture was supplied. This includes
scene fixture generation and load/edit/play/save/readback, resource tests, and
the two new DX11 cases. Linux/macOS execution was not performed in this change.
Actual native device removal was not forced; explicit retirement/replacement
and real ResizeBuffers failure were exercised.

```powershell
cmake -S . -B build-dx11 -DMIKUDANCESTUDIO_FORMATS_ONLY=ON -DMIKUDANCESTUDIO_RHI_D3D9=OFF -DMIKUDANCESTUDIO_RHI_D3D11=ON
cmake --build build-dx11 --config Release
ctest --test-dir build-dx11 -C Release -R '^rhi_d3d11_lifecycle_' --output-on-failure
```

Local logs and generated RGBA images are in each build tree's
`dx11-lifecycle-evidence`; they are ignored build artifacts. The next migration
is one existing PMM material batch through an explicit shader/buffer contract
into an offscreen DX11 target. Do not switch application rendering based on
this lifecycle acceptance.
