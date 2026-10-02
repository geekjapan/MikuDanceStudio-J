# Portable Toon resources and first owned material texture

## Contract

`rhi::ToonTextureResolver` accepts decoded filesystem paths and a platform-free
`AssetSource`. Win32 only supplies embedded PNG bytes and converts PMD CP932 /
PMX UTF8 or UTF16LE names at the application boundary. The resolver contains
no Win32, D3DX or Direct3D types.

| Request | Lookup | Failure behavior |
| --- | --- | --- |
| Default | Asset ID `Toon00` (`0x67`) | Report unavailable; retain legacy drawing |
| Shared slot 1..10 | Shared directory `toonNN.bmp`, then `ToonNN` (`0x68..0x71`) PNG bytes | Missing or undecodable BMP falls back to the corresponding builtin PNG |
| Model file | Absolute path, or normalized model-directory-relative path | PMD policy leaves it unbound; PMX policy can request default Toon |

The Windows bridge recognizes a PMD shared filename only when it is exactly
the legacy expected `toon%02d.bmp` for that reference index. It does not turn
arbitrary custom names into shared Toon. PMX shared indices are zero-based;
the resolver's shared slots are 1..10. Missing private PMD Toon is not silently
replaced with a white texture. The optional first batch requires a successfully
resolved texture, otherwise it falls back to the old draw.

`DecodeTextureRgba` detects BMP/PNG by content, returns top-down tightly packed
RGBA8, and rejects malformed/truncated input and dimensions above 4096. The
existing PNG-only entry point remains PNG-only. BMP tests include bottom-up and
top-down scanlines and 24-bit row padding. The decoder uses the existing licensed
stb_image dependency. File assets are bounded at 16 MiB. Other material image
formats, mip chains and shader/color-space contracts remain future work.

`MaterialTextureAsset` keeps logical identity, origin, resolved source path,
fallback status, CPU pixels and a content revision. Shared Toon identity stays
stable when its source changes from BMP to builtin PNG. `MaterialTextureCache`
keys by identity, revision and dimensions, uploads once, reuses matching handles,
and replaces changed resources only after a successful new upload. The host
invalidates GPU caches before resetting or replacing a device; retained CPU
pixels can then upload again. Handles belong to a device and generation.

## Windows adapter gate

`BorrowedModelTextureCache` owns a persistent DX9 RHI device/cache and binds its
uploaded Toon to material stage 0. It restores all captured external state.
Base/Sphere bindings, texture cascades, lights, transforms, material constants
and the current CPU-skinned mesh remain supplied by the old runtime. An issued
draw is never duplicated by fallback, even when the callback or restoration fails.

The diagnostic option `MDS_RHI_MODEL_TOON=1` first compares the resolved RGBA
against the old bound level-0 Toon (including X8R8G8B8's implicit opaque alpha).
Only a successful comparison allows the owned-texture A/B probe. The existing
snapshot and same-frame pixel gates still precede `MDS_RHI_MODEL_ADAPTER=1`.
Both options default off. Scene reload, device reset and shutdown discard the
comparison gate and GPU cache. MME effects remain excluded from this initial
batch; actual submission still traverses the existing MME draw bridge once.

CTest entries `rhi_real_model_toon_gui` and `rhi_real_model_toon_optin_gui` use
the real v1 `sample.pmm`, model slot 2 `Miku_Hatsune_metal.pmd`, material 10,
frame 5, first index 63381, count 24. Original independent-bone eligibility is
unchanged. PMX's broader material renderer is not enabled by this change.

## Measured results, September 30, 2026

| Check | x64 | x86 |
| --- | --- | --- |
| Resolved Toon RGBA vs old texture | 0 different channels | 0 different channels |
| Source | builtin `toon01.png` fallback, X8R8G8B8 | external `data/toon01.bmp`, A8R8G8B8 |
| Dimensions / content revision | 32x32 / 15602473146173188027 | identical |
| Same-frame target pixels / differences | 2073600 / 0 | 2073600 / 0 |
| Pixels changed by the batch | 11 | 8 |
| Actual optional adapter vs reference | 0 differences | 0 differences |
| Persistent texture uploads / hits | 1 / 2 | 1 / 2 |
| Actual MME bridge / host / direct calls | 1 / 0 / 1 | 1 / 0 / 1 |

The different viewports are the existing x64/x86 editor layouts. Each compares
against its own same-frame old draw, not against the other architecture's screen.
Evidence is under `exports/rhi-model-toon-x64`, `exports/rhi-model-toon-x86`
and `exports/rhi-model-toon-x86-probe`. The first x86 probe attempt timed out
in missing-model reselection before reaching the live main window. The opt-in
run and immediate probe retry passed; the initial timeout is a window-flow
limitation, not counted as a successful graphical run.

Both architectures passed `rhi_d3d9` and `rhi_material_textures`. The DX9 smoke
test checks the owned binding inside the callback, original binding restoration,
reuse, callback failure/issued-draw reporting, and reupload after native reset.
The complete x64 application also builds with the DX9 RHI disabled.
The real v2 `test_1.pmm` material-snapshot regression passed on both architectures
(25 batches, zero mismatches); its PMX draws remain on the legacy renderer.
The original borrowed-texture model opt-in and independent DX9 pixel-parity tests
also passed on x64. Reports are in `exports/rhi-materials-v2-toon-x64/x86` and
`exports/rhi-model-baseline-after-toon-x64`.

The standalone `cmake/rhi-resource-tests` target now runs four always-available
tests. The new material test constructs an original 2x2 PNG/BMP fixture, covering
file/builtin RGBA equality, path normalization, shared precedence, missing/corrupt
fallback, revision replacement, upload/bind/reuse, reset, device replacement,
stale handles and release. It needs no proprietary PMM/model/Toon fixture.

All four passed on the user's Linux server (GCC 11.4) in
`/data2/wangjun/github/MikuDanceStudio/toon-resource-check-20260930`.
[CI run 36704138289](https://github.com/jstzwj/MikuDanceStudio/actions/runs/36704138289)
passed the same four tests on Windows (MSVC 19.51), Linux (GCC 13.3) and macOS
(AppleClang 21), with no resource tests skipped. Only the standalone dependencies
were published on a validation branch; main and unrelated working changes were
not published. The full formats job is intentionally skipped on that branch.
Logs are retained in `exports/rhi-toon-resource-ci.log`.

## Next boundary

Base and Sphere now share the portable flow and have separately gated,
real-scene-derived pixel comparisons. See [material texture validation](RHI_MATERIAL_TEXTURE_VALIDATION.md)
for the supported inputs, Mipmap requirement and the blocked non-power-of-two
texture that still needs portable D3DX-compatible preparation.

An experimental non-power-of-two preparation flow and its rejection tests now
exist; see [preparation validation](RHI_TEXTURE_PREPARATION_VALIDATION.md).
Exact D3DX-compatible preparation remains the next texture acceptance boundary;
full light/view and pipeline inputs still precede another rendering backend.
This first owned Toon does not establish parity for arbitrary materials, IK,
physics, MME effects or an entire model renderer.
