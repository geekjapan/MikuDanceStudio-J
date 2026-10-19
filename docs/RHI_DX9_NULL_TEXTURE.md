# Native DX9 null-texture control

## Scope and acceptance

The preceding real-PMM portable capture stopped at the first accessory draw:
`unbound_active_texture_stage`. The native stage is enabled and references
`D3DTA_TEXTURE`, but the captured binding is null. This is different from a
missing asset or failed image decode.

The new independent `rhi_d3d9_null_texture_native` CTest compares two native
DX9 HAL draws: the captured style of null binding, and an explicit
`D3DTOP_DISABLE` at the same stage. After RDP recovered, both x64 and x86
passed all 48 comparisons with zero differing RGBA pixels. This establishes
cascade termination for the tested argument/operation subset on this device.

The generated controls cover 48 combinations:

- Null binding at stage 0, 1 or 2.
- Color Modulate or Add; canonical texture/diffuse-or-current arguments.
- Lighting off or emissive lighting with fractional RGB/material alpha.
- Plain output, source-alpha blending, or alpha test with reference 64 or 192.

All RGBA pixels are compared, including alpha. Earlier stages have colored
textures. A later magenta/zero-alpha sentinel checks cascade termination;
replacing the null binding with a real texture must visibly change the output
in the plain-output cases (12 additional negative controls). Unlit interior
pixels also have an explicit expected value to prevent an empty draw from
passing. These cases use generated, single-sample geometry without PMM assets.

The test's native renderer now applies each snapshot's material, documented
render states, light state, geometry and all eight texture bindings, including
explicit nulls. The existing viewport test continues to use the same helper.
No white texture is substituted for a null binding.

## Conversion rule

`AppendD3D9ReplaySnapshot` checks the canonical Modulate/Add color and Modulate
alpha arguments before recognizing a null binding. It then ends the cascade,
preserves earlier stages and publishes no texture for that or later slots.
Unsupported arguments still reject the snapshot transactionally. A null
descriptor carrying texture bytes is inconsistent and is rejected explicitly.
The terminated stage's coordinates/sampler and all later stage state are
unused, as with explicit `D3DTOP_DISABLE`.

CPU checks cover stages 0-2, both operations, ignored later unsupported state,
absence of fabricated resources, and null/bound/null version transitions.
The DX11 adapter itself needs no new shader or null-resource behavior: the
portable pipeline simply contains fewer enabled stages.

## Execution evidence

The x64 and x86 executables build. The CPU conversion and versioned replay
tests pass on both architectures (four CTest results).

The first native probe was attempted on both architectures. Both stopped before the
first draw at `CreateDevice`, HRESULT `0x8876086C` (`D3DERR_INVALIDCALL`). At
that attempt, `query session` reported the current RDP session as `Disc`.
This records the environment and failure; it does not prove that the session
state was the only cause. Those logs are retained separately.

On the subsequent retry `query session` reported `Active`, both native CTests
passed (96 equality comparisons, plus 24 visible sentinel controls), and both
application builds succeeded. Logs: `exports/null-texture-rdp-retry-{x64,x86}.log`.
Application rendering remains on DX9; conversion support alone does not
establish a complete scene history or DX11 scene-image equivalence.

The Hardware controls pass on x64 and x86: 144 images each, **288 exact RGBA
comparisons**, including null/bound/null transitions and device replacement.
The five existing viewport cases also pass on both architectures and both
DX11 drivers (120 exact comparisons). CPU conversion/replay checks pass.

WARP does **not** meet the cross-API zero-difference gate. On each architecture, 78 of 144
comparisons differ by at most one byte per channel. A representative half-lit
pixel is DX9 `(255,127,64,127)` versus WARP `(255,128,64,128)`. For each failing
single-draw case, independently converting an explicit `D3DTOP_DISABLE`
produces the same WARP image as null canonicalization (zero differences).
The corresponding native null/explicit-disable comparisons also passed.
Thus the mismatch is already present in the supported disabled-cascade
shading path; this observation does not locate the exact arithmetic or
quantization step. No tolerance, shader rounding adjustment or software-driver
skip was added. `rhi_d3d9_null_texture_warp` intentionally continues to return
failure until the zero-difference requirement is met. It must not be reported
as an accepted WARP scene path.

Evidence: `exports/null-texture-regression-{x64,x86}.log` and
`exports/null-texture-warp-baseline-{x64,x86}.log`.

## Reproduce and continue

With an available DX9 desktop device, run the architectures serially:

```powershell
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^rhi_d3d9_null_texture_'
ctest --test-dir build-x86/build -C Release --output-on-failure -R '^rhi_d3d9_null_texture_'
```

Device creation failure is a test failure, not a skip. Success prints
`nativeNullTextureComparisons=48 differingPixels=0`. WARP in the existing
cross-API test selects only the DX11 destination; it cannot replace the native
DX9 source required to establish this behavior.

The Hardware/WARP controls compare those 48 cases through converted DX11
streams. Six further cases (three slots, Modulate/Add) draw null/bound/null
and compare prefixes 1, 2, 3, 1, ensuring binding transitions and repeated
earlier prefixes preserve immutable resource versions. Each driver repeats
the controls after replacing the DX11 device: 144 images per configuration.

## Real PMM retry

Fresh x64 and x86 GUI runs loaded `sample.pmm` with missing-model relocation
and reached material 13 in single-sample mode. Both recorded 49 preceding
draws; native DX9 replay reports zero differing pixels before material 13.
The first eight accessory snapshots now convert successfully. Admission then
stops at draw 9/event 26 (`unsupported_texture_format_mips_or_lod`). Both GUI
tests return 31, which is rejected portable admission, not complete-scene PASS.
The gate's `draws=0` is the incomplete-stream validation result; the eight
successful conversions are logged individually as `PORTABLE ... CONVERTED`.
No full DX11 scene image or after-material history result is claimed.

That first textured accessory has a 64x64 A8R8G8B8 texture, `autoMips=1`,
`levels=1`, `lod=0`; generated lower mips are not captured as a portable chain.
All 12 formerly blocked untextured accessories are now convertible (eight in
the prefix, four audited in isolation after it breaks). Seven textured
accessories and five model-material draws still reject texture preparation.
Seventeen projected-shadow draws, starting at draw 20 with FVF 66, reject
their vertex layout. Eight other model-material draws remain convertible in
isolation. No ground draw is present in this prefix.

Evidence: `exports/portable-null-texture-{x64,x86}/history_replay.dx9` and
`exports/portable-null-texture-summary.json`. Captures and original assets
remain local ignored files.

Next, define and test how to transfer autogenerated mip contents or reproduce
their generation before admitting the textured draw. Keep the WARP rounding
difference as an independent strict image gate; do not fit shader precision
or silently use only the top mip to bypass either failure.

The subsequent [mip materialization implementation](RHI_DX9_MIP_CAPTURE.md)
prepares explicit native levels behind a default-off diagnostic switch.
After the interrupted initial run, all six x64/x86 mip CTests passed. Fresh
PMM captures now convert the first 19 accessory draws and stop at projected
shadow draw 20; the complete scene prefix is still rejected.
