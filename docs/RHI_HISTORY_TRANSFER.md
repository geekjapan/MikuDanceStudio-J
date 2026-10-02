# Exact history contract and MSAA investigation

The portable RHI now declares an explicit history-transfer contract. The
single-sample INTZ diagnostic capture uses its capability checks and data
validation. Native 8x-MSAA investigation confirms that this DX9 path provides
resolved color readback, but not direct per-sample color/depth/stencil transfer.
**Real PMM 8x-MSAA three-way image acceptance is still incomplete.** It is marked
BLOCKED, not skipped into success or approximated using resolved history.

## Portable contract

`rhi.hpp` defines:

- `HistoryDesc`: dimensions, source sample count/quality, color/depth/stencil
  attachment presence, sample-pattern identity, representation and resolve rule.
- `HistoryRepresentation`: SingleSample, PerSample, or ResolvedColor. Resolved
  color has one RGBA value per pixel even though its source sample count is >1.
  It cannot contain a depth/stencil plane and cannot satisfy exact restoration.
- `ColorResolveRule`: None, LinearUnorm or Srgb. Availability of resolved
  readback does not establish which numerical rule a driver uses.
- `HistoryData`: texel-major/sample-major RGBA8 and packed D24(low)/S8(high),
  plus scene/frame/draw-sequence/source-device/reset-epoch identity. A backend
  must validate identities against the requested boundary before restoring;
  a reset invalidates pending native operations/resources.
- `HistoryCapabilities`: separate capture/restore access for every attachment,
  per-sample capture/restore, supported resolve modes and maximum sample count.
  Access can be Unsupported, Native or DriverExtension. DrawReplay is a distinct
  strategy, not direct readback. Capabilities describe implemented operations.
- `HistoryReplayBoundary`: ordered event coverage from clear, resource versions,
  supported events and target description. `completeDrawReplay` may be true only
  after every preceding clear, draw, resource update and target change is covered.

`ValidHistoryDesc` and `ValidHistoryData` check layout/plane lengths.
`CanCaptureHistory` and `CanRestoreHistory` reject unsupported attachments,
incompatible sample counts/quality/patterns and loss of exact samples.
In particular a resolved 8x color image cannot initialize exact 8x color/depth/
stencil history, nor can it be passed off as a single-sample exact scene boundary.
`CanReplayHistory` independently requires a complete supported/versioned stream.

`Device::HistoryFeatures`, `CaptureHistory` and `RestoreHistory` are optional
extension points. Null and the general DX9 adapter currently return Unsupported;
the optional methods do not advertise functionality that has not been wired.
The narrower application diagnostic exposes `DiagnosticHistoryFeatures` and
`CaptureDiagnosticHistory`: single-sample color is native readback, depth/stencil
capture requires the active INTZ extension. Restore is not advertised by that
service. The standalone replay reader still seeds its targets independently.
Both per-sample flags remain false. The capture bridge now consumes validated
`HistoryData` before writing its existing local diagnostic transport.

Sample-pattern IDs are an explicit caller/backend agreement, not a numeric
sample index or an assumption that both vendors use identical sample locations.
The common contract admits counts 1/2/4/8/16; other native layouts need explicit
extension. It is not a general CPU image resampler or depth-resolve policy.

## DX9 8x-MSAA probe

The probe creates actual 64x64 eight-sample color and D24S8 surfaces on NVIDIA
TITAN Xp (`10de:1b02`), quality 0. x64/x86 both produce:

| Operation | Result |
| --- | --- |
| GetRenderTargetData on MSAA color | `8876086c` (INVALIDCALL) |
| D24S8 system-memory readback surface | `8876086c` |
| GetRenderTargetData on depth | `8876086c` |
| LockRect on MSAA color/depth | `8876086c` |
| Get texture container from native MSAA depth surface | `80004002` (NOINTERFACE) |
| StretchRect color resolve, then readback | Both `00000000` |
| Sample-index Texture2DMS.Load compiled for ps_3_0 | `80004001`, unsupported instruction mapping |

The depth GetRenderTargetData call uses an available color readback target;
it demonstrates the attempted path's rejection, not a supported depth-read API.
The separate depth system-memory creation result documents that limitation too.
The standard DX9 interface has no multisample texture creation/sample-index-load
contract: CreateTexture has no sample count; CreateRenderTarget and
CreateDepthStencilSurface create surfaces. A sample-index load cannot be
represented by the DX9 shader instruction set. The previous INTZ diagnostic
creates a single-sample texture; it does not expose MSAA depth/stencil samples.

These probes do not rule out every proprietary driver extension. No proprietary
per-sample path has been implemented or validated in this project. The evidence
supports using ordered preceding-draw replay rather than pretending that a
color resolve plus an approximate depth value is an exact substitute.

`rhi_d3d9_msaa_history_capability` passing means the probe successfully verified
and reported the limitation. Its report still says `msaaSceneAcceptance=BLOCKED`.
It is not a successful scene image comparison. No resolve-curve support is
advertised merely from the successful StretchRect call.

## Real PMM prefix audit

The audit runs the original normal-MSAA application with real `sample.pmm`,
frame 5, slot 2/material 13: 336 indices / 112 triangles. It starts after the
scene clear and records observed MME-bridge draw calls until the selected batch.
The source remains eight samples; INTZ/single-sample mode is disabled.

Both x64/x86 observe 30 preceding draw calls: 13 position/normal/UV model draws
and 17 other-format draws, including projected shadow geometry. Material-only
replay omits those operations and cannot establish the actual history. Background,
floor, accessories, shadow passes, clears and target switches must all be covered
when present, including calls outside these wrappers. Current logging is an
inventory, not a command stream: it lacks versioned resource contents, complete
states, target-change/clear coverage and translated pipelines for all formats.
Therefore `allEventsRecorded=0`, `allResourcesVersioned=0` and
`completeDrawReplay=0` remain explicit. The audit covers the first captured
boundary per application process; it is not a general multi-scene recorder.

The existing old-DX9 vs DX9-adapter diagnostic for the selected draw remains
zero-difference in the actual scene, with the application adapter off. On x64
it reports 241 changed resolved pixels. That is useful regression evidence,
but **DX11 three-way scene comparison is NOT_RUN**: no equivalent complete
MSAA history exists yet. Isolated batch draws on a uniform background or resolved
history do not close that gate.

Evidence is retained under ignored `exports/rhi-real-dx11-msaa-audit-{x64,x86}`:
native HRESULT report, shader compiler diagnostics, real capture, existing
native parity report and `msaa_replay.prefix`. `msaa-history-gate.json` explicitly
reports BLOCKED/NOT_RUN; the consolidated summary is
`exports/rhi-msaa-history-audit.json`. These external-resource captures are not
added to distributable repository assets.

## Checks and reproduction

Portable history tests cover attachment sizes, exact-vs-resolved rejection,
sample pattern/quality mismatch, unsupported operations and incomplete replay.
The standalone resource suite now has six tests. All six pass locally and on
the user's Linux server. [CI run 36828257337](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36828257337)
passes all six on Windows, Linux and macOS with no resource skips; isolated
source revision `04bc9fcb6a9df84eb2594a45de9f4e903c3ccbaa`.
Metadata/logs: `out/resource-ci/history-contract-remote-run.json` and
`exports/rhi-history-contract-ci.log`. This validates the portable contract,
not GPU history transfer on macOS/Linux.

Both architectures build the application, native probe and history tests.
The native probe passes without skips. The existing single-sample real scene
history test remains the required regression for the capture bridge.

```powershell
cmake --build build-x64/build --config Release --target MikuDanceStudio pmm_v1_relocation_gui_test rhi_history_test rhi_d3d9_msaa_history_test
ctest --test-dir build-x64/build -C Release -R '^rhi_(history|d3d9_msaa_history_capability)$' --output-on-failure
$env:MDS_PMM_GUI_FIXTURE='C:\Users\jstzw\Downloads\MikuMikuDanceE_v932\UserFile\sample.pmm'
$env:MDS_PMM_RELOCATE_MODEL='Dammy_Bone.pmd'
python tools/audit_real_d3d11_msaa_history.py --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe --application build-x64/build/Release/MikuDanceStudio.exe --dx9-test build-x64/build/Release/rhi_d3d9_parity_test.exe --probe build-x64/build/Release/rhi_d3d9_msaa_history_test.exe --evidence exports/rhi-real-dx11-msaa-audit-x64
```

The last command deliberately returns **2** for the unclosed MSAA gate. Repeat
with the x86 paths. Missing devices/fixtures may return 77; these local audits
actually ran. Never promote a successful capability probe into scene acceptance.

## Remaining implementation

The first native DX9 frozen-resource recorder/replayer is now implemented.
[Native replay status](RHI_DX9_HISTORY_REPLAY.md) documents the newly discovered
19 accessory draws, the 49-draw prefix, and the remaining 533-pixel failure.
It supersedes the wrapper-only inventory for implementation progress; it does
not close the MSAA acceptance gate or provide complete portable/DX11 replay.

The required next work is a real command stream, not further attempts to read
resolved color: capture clear/target/resource events and every preceding draw,
including FVF66 colored shadow geometry and FVF274 model geometry; snapshot
resource versions and all relevant pass state. Replay that exact stream into
same-sample-pattern DX9/DX11 targets and verify the **before** state first.
Only then issue material 13 and compare both results to the actual application
draw, retaining no-depth/no-blend controls. Any unsupported event must block
the stream. This implementation and its 8x three-way acceptance are not yet
complete. The production renderer continues to use the original DX9 path.
