# Portable texture preparation: experimental, blocked for the real eye texture

Current DX9 acceptance uses a separate optional backend service, documented in
[DX9 preparation capability](RHI_D3D9_TEXTURE_PREPARATION.md). It passes exact
resource and independent-draw parity; the portable candidate below still fails
and remains a research comparison. The default renderer remains unchanged.

September 30, 2026. The preparation interface and its resource lifetime are
implemented. The original scene's `eyeM2.bmp` has **not** passed strict RGBA
parity and stays on the old DX9 texture path. A passing rejection test is not
acceptance of that resource or its rendered pixels.

## Boundary and implementation

`DecodeTextureRgba` still returns the original image dimensions and RGBA bytes.
`NextPowerOfTwoTextureSize` is an explicit size policy, bounded by the host's
device limit and 4096; it fails rather than silently clamping. The decoder does
not choose GPU dimensions.

`PrepareTriangleDitherWrap` is an experimental CPU filter. It integrates the
periodic bilinear reconstruction over destination texels, then applies measured
4x4 ordered dithering. It accepts identity or enlargement up to twice each
source dimension, and rejects shrinking and invalid input. Identity preserves
every byte. Output can alias input. This is an independently implemented
candidate, not a complete or bit-identical D3DX implementation; single-axis,
alpha-rich and other-size inputs still need independent native comparisons.

`MaterialTextureAsset::content` retains the decoded image. Optional `prepared`
data has a separate content revision. `MaterialTextureCache` uses it only when
`usePrepared` is explicitly accepted by the host. Size, revision and automatic
Mipmap policy participate in cache reuse. Invalidation releases GPU handles;
retained CPU images support upload after device restoration.

The DX9 comparison bridge enables candidate preparation only with
`MDS_RHI_TEXTURE_PREP_CANDIDATE=1`, and only when decoded dimensions differ from
the bound legacy texture. The host checks its size policy against the actual
legacy dimensions, reads GPU level 0, and requires zero differing RGBA channels
before setting `usePrepared`. It also checks linear automatic Mipmap policy.
A failed comparison reports `BLOCKED_PREPARATION` and leaves `usePrepared=false`.
The ordinary adapter remains opt-in; this flag alone does not switch rendering.

## Native measurements

The original PMD's material 6 references `eyeM2.bmp`: decoded 106x106, legacy
128x128, A8R8G8B8, managed, automatic Mipmaps (`Usage=1024`). Comparing an
unresized native load against raw decode found zero byte differences. The
remaining mismatch is introduced during preparation, not initial decoding.

The measurement executable dynamically loads Microsoft's `d3dx9_43.dll` and
calls `D3DXCreateTextureFromFileInMemoryEx` with the legacy default dimensions,
one level, usage 1024 and managed A8R8G8B8. It compares both default filtering
and explicit `D3DX_FILTER_TRIANGLE | D3DX_FILTER_DITHER` (`0x80004`). Both native
filters produced identical bytes in the measurements below. Both installed DLLs
report version 9.29.952.3111.

| Context | Different candidate RGBA channels | Maximum error |
| --- | ---: | ---: |
| Standalone x64 HAL, software vertex processing | 1 | 1 |
| Standalone x64 HAL, hardware vertex processing | 1 | 1 |
| Standalone x86 HAL, software vertex processing | 2 | 1 |
| Standalone x86 HAL, hardware vertex processing | 2 | 1 |
| Standalone x86 HAL, software VP + FPU_PRESERVE | 1 | 1 |
| Existing application, x64 | 1 | 1 |
| Existing application, x86 | 1 | 1 |

The shared discrepancy is texel `(52,48)`, green: candidate 46, native 45.
Standalone x86 without FPU preservation also differs at `(97,77)`, red:
candidate 76, native 75. The portable candidate RGBA was identical across the
two local Windows architectures. The probe records device behavior and floating
point control before/after device creation. On x86, creation changes that
control word; preserving it removes the extra red discrepancy. Thus it would
be incorrect to describe the standalone discrepancy count as a universal
x86-versus-x64 rule. Do not change application floating point mode to hide it.

No tolerance, per-texel correction or proprietary fixture is used to pass a
comparison. The unresolved green filter-arithmetic discrepancy blocks this
resource before upload and before any claim of eye-batch pixel equivalence.

## Follow-up: float filtering and an original counterexample

The native probe now also captures a separate managed RGBA32F target, with
usage 0 and explicit prepared dimensions. Applying the measured 4x4 dither
and byte quantization to this **native** floating-point output reproduces every
channel of the native byte texture for both measured filters on x64 and on x86
with FPU preservation. This does not validate the portable filter: its input
floating-point values already differ before quantization. The diagnostic target
never enters the application or the RHI texture cache.

An additional identity-size RGBA32F capture isolates byte-to-float conversion.
On the true eye, 3917 channels differ from single-precision `byte / 255.0f`,
while **zero** differ from `byte * (1.0f / 255.0f)` on both measured architectures.
The candidate's conversion stage has now been changed to reciprocal
multiplication to match this independently measured result. This correction does
not explain the green counterexample by itself: its source values 45 and 46
normalize identically by either expression, yet filtering still differs.
The probe retains original decoded RGBA and native identity-size float channels
so the analysis script can verify this separately from the resize.

`--boundary <evidence-directory>` generates an original 106x106 RGB BMP:
all channels 45, except source pixel `(44,39)` has green 46. It reproduces the
same single-channel discrepancy on both architectures without any PMM or model
assets. The source is generated by code and can be distributed with the project.
It is a counterexample to native equivalence, not a correction at that pixel.

At destination `(52,48)`, the canonical integral is
`45 + (18/53)*(625/6784) = 45.0312889373`; adding dither `31/32` crosses 46.
Native floating-point filtering instead yields approximately `45.0311214477`
on x64, or `45.0311252475` on FPU-preserved x86. Adding the same dither remains
below 46, hence the legacy byte is 45. The difference is in the filter's
numerical behavior, before the final byte conversion; changing the dither
threshold cannot explain it consistently across the other pixels.

The probe additionally generates a constant field and nine independent impulses
(three RGB-separated source pixels in each of three rows). The nine native tap
responses sum to `0.999996215163` on x64 and `0.999996262253` on FPU-preserved
x86, rather than the canonical 1. A constant input of 45 produces roughly
`44.99983` before byte conversion at that target pixel. These measurements
explain the small downward shift and expose architecture-dependent intermediate
arithmetic. They do **not** yet identify the exact internal expression or supply
a general portable algorithm matching all native coefficients.

Both the original counterexample and the true eye measurement still exit 2,
`BLOCKED`. Their separate `FLOAT ... status=MATCH reconstructedChannels=0`
reports mean only that native float output explains native byte output.
`tools/analyze_rhi_texture_preparation.py` independently checks artifact sizes,
actual candidate difference counts and float-to-byte reconstruction, using only
Python's standard library. Its `candidateAccepted` field remains false.

Reproduce without external assets:

```powershell
& build-x64/build/Release/rhi_texture_preparation_d3d9_test.exe `
  --boundary exports/rhi-texture-boundary-x64
# Expected current exit code: 2 (candidate BLOCKED).
$env:MDS_TEXTURE_PROBE_PRESERVE = '1'
& build-x86/build/Release/rhi_texture_preparation_d3d9_test.exe `
  --boundary exports/rhi-texture-boundary-x86
# Expected current exit code: 2 (candidate BLOCKED).
Remove-Item Env:MDS_TEXTURE_PROBE_PRESERVE
python tools/analyze_rhi_texture_preparation.py exports/rhi-texture-boundary-x64
# Analysis exit 0 means artifacts are valid; candidateAccepted is still false.
```

Evidence is in `exports/rhi-texture-boundary-x64`, `...-x86` and
`exports/rhi-texture-filter-diagnostic-x64`, `...-x86`. Each retains native
RGBA bytes, candidate bytes, little-endian native RGBA32F channels and reports.
The boundary directories also retain the generated original BMP and the
constant/impulse response reports. After these diagnostic changes, both
architecture builds and their portable/native preparation CTests passed again.
The boundary measurement remains a failing parity probe; it is not added as a
passing candidate-equivalence CTest. These native diagnostic observations were
measured on Windows; they do not establish any native macOS/Linux rendering result.

After the conversion correction, both full Windows architectures rebuilt and
passed the original-scene preparation GUI rejection test. The eligible material
10 comparison still has zero differing target pixels, while material 6 remains
`BLOCKED_PREPARATION`, one differing channel, `preparedAccepted=0`. Evidence is
under `exports/rhi-texture-filter-gui-x64` and `...-x86`.

The updated standalone **five-test** resource suite passed locally, on the user's
Linux server (same preparation-resource-check directory), and on all three
platforms in [CI run 36729493111](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36729493111).
No resource tests were skipped. The isolated validation commit is
`b9a22851bd7543e69e97ec3aaffc1b7a1d017a2e`, recorded in
`out/resource-ci/filter-arithmetic-remote-run.json`; logs are in
`exports/rhi-filter-arithmetic-resource-ci.log`. This branch validates the
portable resource dependencies; the complete formats job is intentionally skipped
on this validation branch. Existing unrelated work and the main branch were not published.

## Tests and evidence

The always-available portable test uses an original 3x3 RGB BMP pattern and
64 expected RGBA bytes independently captured from native 4x4 preparation.
It verifies those bytes, raw preservation, size rejection, aliasing, explicit
prepared-resource selection, cache replacement/reuse, reset and reupload.
The Windows native test reproduces that synthetic comparison without external
model assets. Its normal CTest passes only on zero difference; unavailable DX9
or D3DX returns skip code 77. External measurement mismatches return **2**.

Both x64 and x86 passed the five focused CTests: DX9 resource smoke, DX9 pixel
parity, material resources, portable preparation and synthetic native preparation.
The full application builds on both architectures; the x64 build also passes
with the DX9 RHI disabled.
The real `sample.pmm` preparation GUI test checks that material 6 remains blocked,
while the existing eligible material-10 Toon comparison retains zero same-frame
pixel differences. This is fallback validation, not acceptance of material 6.
The existing configured Base/Sphere batch also retains zero pixel differences.
The real v2 material-snapshot regression passed on x64/x86: 25 draws, zero
mismatches, with Save As/readback checks intact. An initial x86 test failed
because the startup report was complete before the main window was visible;
the runtime report itself passed all predicates and the material snapshot had
zero mismatches. The GUI test now waits for the main window within its existing
deadline. Both architecture reruns passed after that test-only timing fix.

The standalone resource suite now has **five tests**, with no external model
requirements. It passed on the user's Linux server (GCC 11.4) under
`/data2/wangjun/github/MikuDanceStudio/preparation-resource-check-20260930` and
on Windows, Linux and macOS in
[CI run 36720626991](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36720626991)
(MSVC 19.51, GCC 13.3, AppleClang 21). All five tests ran on each CI platform;
none was skipped. The isolated validation revision is
`e63249287dc4bb470f6c64b99407f281cde1adfb`. Its scope is the standalone resource
suite, not a native macOS renderer or the complete Windows application.

Local evidence directories:

- `exports/rhi-texture-preparation-x64` and `...-x86`: default/software-VP
  reports, candidate bytes and native bytes.
- `exports/rhi-texture-preparation-hardware-x64` and `...-x86`: hardware VP.
- `exports/rhi-texture-preparation-preserve-x86`: FPU-preserved native report.
- `exports/rhi-texture-preparation-gui-x64` and `...-x86`: original-scene audit,
  material snapshot and same-frame eligible-batch report.
- `exports/rhi-texture-preparation-v2-x64` and `...-x86`: v2 material snapshots.
- `exports/rhi-preparation-resource-ci.log`: three-platform CI logs.

Example native measurement, from the repository root:

```powershell
$env:MDS_TEXTURE_PROBE_PRESERVE = '1' # optional, isolated probe only
& build-x86/build/Release/rhi_texture_preparation_d3d9_test.exe `
  'C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/Model/eyeM2.bmp' `
  exports/rhi-texture-preparation-preserve-x86
# Expected current exit code: 2, BLOCKED, one differing green channel.
```

For real GUI checks set `MDS_PMM_GUI_FIXTURE` to the original `UserFile/sample.pmm`
and `MDS_PMM_RELOCATE_MODEL` to the filename `Dammy_Bone.pmd`, then run
`rhi_real_model_textures_preparation_gui` via CTest. Missing external assets skip
that GUI test; such a skip is never reported as graphical acceptance. Relocate
the dummy model, leaving the textured model and its texture files together in
their copied `Model` directory; moving just the textured PMD would deliberately
make its model-relative textures missing and invalidate this comparison setup.

## Remaining acceptance gate

Trace the native coefficient construction and accumulation under recorded
floating-point conditions, using the original constant/impulse counterexample
and RGBA32F observations. Do not normalize measured native taps to 1 or apply
a content-specific byte patch: either would conceal the arithmetic being
compared. Alpha/one-axis resizing still need independent vectors. Only after exact RGBA parity
should a prepared textured eligible batch undergo same-frame and actual-adapter
pixel comparison. Material 6's existing IK dependency does not become eligible
merely because its texture matches; keep the prior batch dependency exclusions.
Retain the old path until both resource and eligible-draw gates pass.
