# Optional DX9 texture preparation capability

October 1, 2026. The DX9 capability passes strict RGBA and independent-batch
pixel acceptance on x64/x86. It remains opt-in. The portable numerical candidate
is a separate implementation and still fails its exact native comparison.

## Responsibilities

`TexturePreparer` in `rhi_image.hpp` is a platform-independent optional service:

```cpp
class TexturePreparer {
public:
    virtual ~TexturePreparer() = default;
    virtual bool Prepare(const RgbaImage& source, std::uint32_t width,
                         std::uint32_t height, RgbaImage& prepared) = 0;
};
```

The caller owns original decoded RGBA, texture identity, explicit target-size
policy and retained prepared CPU data. The service returns pixels only. A true
result is not authorization to render: the host still requires resource and
draw parity. Failed preparation clears output; aliasing is supported.
Backend preparation does not resolve model paths or silently choose dimensions.

`CreateD3D9TexturePreparer(device)` returns the optional DX9 implementation.
Null devices, an unavailable system `d3dx9_43.dll`, or a missing entry point
return no capability. DX9-disabled builds provide an empty factory. The service
retains a device reference; callers destroy it before releasing that device.
The application bridge uses a temporary service, with no persistent native
scratch texture or surface across reset.

The DX9 implementation swizzles raw RGBA to BGRA and calls
`D3DXLoadSurfaceFromMemory` with A8R8G8B8 source pixels, the source rectangle,
and `TRIANGLE | DITHER` (`0x80004`) into a temporary managed A8R8G8B8 texture.
It reads back prepared RGBA and releases the temporary surface/texture. It loads
the installed system DLL only, never a DLL from a model directory. It checks
image bounds, device limits and cooperative state. The core has no Win32/D3DX
includes or link dependency; the new source belongs only to the DX9 target.

The final texture is independently created and uploaded through the existing
`MaterialTextureCache` and RHI device. Prepared dimensions/revision and Mipmap
policy participate in reuse. The host accepts linear automatic Mipmaps from
the old binding and retains that policy in the owned upload. Invalidate the
GPU cache before reset; retained CPU raw/prepared images support reupload.
No host-owned DX9 texture is adopted as an RHI handle.

## Gates and switches

- `MDS_RHI_TEXTURE_PREP_D3DX=1`: request the DX9 preparation service when raw
  and bound legacy dimensions differ. Compare every prepared RGBA channel
  against the actual bound texture before setting `usePrepared`.
- `MDS_RHI_TEXTURE_PREP_CANDIDATE=1`: retain the experimental portable filter
  comparison. The D3DX flag takes precedence if both are requested; a failed
  D3DX capability does not silently substitute the non-equivalent candidate.
- `MDS_RHI_MODEL_TEXTURES=1`: request owned material textures after resource gates.
- `MDS_RHI_MODEL_AB=1`: same-frame comparison and eligibility checks.
- `MDS_RHI_MODEL_ADAPTER=1`: actual opt-in draw, after existing snapshot, resource
  and pixel gates pass. Turning it off retains the old renderer.

Preparation alone does not enable an adapter draw. Missing capability, failed
preparation, unmatched size/Mipmap state, or any RGBA discrepancy blocks owned
material inputs. Existing fallback and no-double-submission rules stay active.
IK, physics, grant-bone and MME eligibility exclusions remain intact.

## Acceptance results

The native preparation test compares the new service's output with independent
`D3DXCreateTextureFromFileInMemoryEx` results for both legacy default filtering
and explicit triangle+dither. The original synthetic 3x3 -> 4x4 fixture passes
on both architectures. It also verifies original raw preservation, invalid and
null input, aliasing, identity-size alpha bytes, RHI upload/readback, cache reuse,
stale-handle rejection and native device Reset followed by reupload. These checks
run without external model assets.

The true 106x106 `eyeM2.bmp` prepares to 128x128 with **zero RGBA differences**
on both architectures, including the normal x86 device floating-point profile.
The standalone executable still exits 2 for the separately measured portable
candidate; its `backend.preparation.report` explicitly records the DX9 service
as PASS with zero differences. Do not conflate these two implementations.

The real v1 GUI test copies `sample.pmm` and its resource tree, reselects a
relocated dummy model, and changes only the previously empty 20-byte texture
reference of material 10 to `eyeM2.bmp` in the temporary copied PMD. The original
PMM/model/texture files are untouched. Frame 5, slot 2, material 10 remains the
accepted eight-triangle batch, first index 63381, count 24. Its bone influences
and eligibility are unchanged. This tests the eye **texture** on an independent
batch; it does not authorize the original IK-dependent material-6 mesh.

| Result | x64 | x86 |
| --- | ---: | ---: |
| Original-eye / configured-batch prepared RGBA differences | 0 / 0 | 0 / 0 |
| Source checks / failures / blocked | 6 / 0 / 0 | 6 / 0 / 0 |
| Target pixels | 2073600 | 2073600 |
| Same-frame / actual draw pixel differences | 0 / 0 | 0 / 0 |
| Changed pixels | 11 | 8 |
| Actual adapter applied | 1 | 1 |
| Owned Toon / Base / Sphere | 1 / 1 / 0 | 1 / 1 / 0 |
| Uploads / cache hits | 2 / 4 | 2 / 4 |
| MME bridge / host / direct submissions | 1 / 0 / 1 | 1 / 0 / 1 |

Both full Windows architectures build. Both pass five focused resource/parity
CTests, including the expanded native preparation/lifetime test. The x64 full
application also builds with the DX9 RHI disabled, and the standalone portable
five-test suite passes locally. The x86 portable-candidate GUI rejection
regression remains blocked with one differing channel and zero unexpected
failures, while its eligible batch still has zero pixel differences.
The real v2 material-snapshot/Save As/readback regression passes on both
architectures, with 25 draws and zero mismatches. PMX rendering remains on its
existing path.

The portable optional interface and five resource lifecycle tests also passed
on the user's Linux server and all three CI platforms in
[run 36742649440](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36742649440).
All five resource tests ran; none was skipped. The validation revision is
`8f31dbbc94c44673400e9eda52f5b87ca21d809a`, recorded under
`out/resource-ci/preparation-interface-remote-run.json`; logs are retained in
`exports/rhi-preparation-interface-resource-ci.log`. This isolated branch contains
portable resource dependencies only. Its full formats job is intentionally
skipped; the DX9 preparation implementation is validated by the local Windows
tests above, not by the Linux/macOS jobs. Unrelated work and main are not published.

Evidence:

- `exports/rhi-d3dx-backend-x64` and `...-x86`: native reference bytes,
  `backend.rgba`, prepared-resource lifetime PASS report and separate candidate diagnostics.
- `exports/rhi-d3dx-native-gui-x64` and `...-x86`: source RGBA audit, material
  snapshot, same-frame/actual draw report and owned-cache counters.
- `exports/rhi-d3dx-portable-rejection-x86`: separate portable rejection regression.
- `exports/rhi-d3dx-regression-v2-x64` and `...-x86`: v2 material snapshots.

Run the real fixture CTest with `MDS_PMM_GUI_FIXTURE` set to the original
`UserFile/sample.pmm` and `MDS_PMM_RELOCATE_MODEL=Dammy_Bone.pmd`, then select
`rhi_real_model_textures_native_gui`. It performs its own temporary material
configuration and enables the required comparison flags. Missing external
resources skip that GUI test; a skip is not pixel acceptance.

## Next boundary

Matrix/light/material capture, optional DX9 replay and a minimal DX11 WARP
vertex-stage batch are now implemented; see
[model shader inputs](RHI_MODEL_SHADER_INPUTS.md) for conventions and evidence.

Keep this optional DX9 service while defining complete light/view and pipeline
inputs for a shader-backed material batch. Other backends can provide their own
preparation service, or use raw dimensions under an explicitly validated policy;
no universal D3DX numerical equivalence is assumed. Continue portable-filter
research with the original constant/impulse counterexample rather than patching
individual pixels. Native DX9 validation is not a macOS/Linux rendering test.
