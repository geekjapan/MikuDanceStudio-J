# Accessory draw 2: saved-image isolation

The [shadow acceptance trace](RHI_PROJECTED_SHADOW_COLOR.md) first diverges
between native DX9 and DX11 at accessory draw 2, before the shadow begins.
This investigation narrows that failure without changing application rendering
or accepting a nonzero image difference.

## Current device evidence

The subsequent reconnect is **confirmed by actual native DX9 creation**:
x64 and x86 each pass the 30-image basic native-vs-DX11 Hardware probe.
Both native accessory controls now execute all 14 cases with new native
images, rather than comparing changed states against an old native reference.
Evidence: `exports/accessory-device-recovery-{x64,x86}.log` and
`exports/accessory-native-recovered-{x64,x86}.log`.

| New native Hardware control | x64 differing pixels | x86 differing pixels |
| --- | --- | --- |
| Original, and repeated original | 102 | 9 |
| Draw 2 alone | 102 | 9 |
| Depth disabled in both backends | 95, all delta 1 | 1, delta 1 |
| Each of six selected triangles alone | 0 | 0 |
| Reversed triangles, and strict Less | 101 | 5 |

The depth-disabled native comparison removes **all high-delta differences**.
Every selected triangle individually agrees natively. This confirms the
large-difference dependence on depth selection between coplanar surfaces;
it does not yet identify the depth interpolation/quantization mechanism.
The remaining delta-1 shading discrepancies remain a separate investigation.
Reversal/strict Less still fail zero-difference acceptance. Both complete
diagnostics return 32 because the original batch still fails, not because
device creation failed. No production state change is enabled.

The subsequent [coplanar depth measurement](RHI_COPLANAR_DEPTH_MEASUREMENT.md)
uses fixed-color triangle pairs and constant-reference attachment comparisons.
It measures a 1-3 float32 reference-step native-vs-DX11 Hardware threshold
difference for the narrow faces at all 15 original high-delta coordinates,
while long faces agree. The measured relations predict every differing
surface choice. Bias and production depth rules remain unchanged.

These runs use the already verified older reduction inputs and saved reference
viewport; a fresh live first-divergence archive is still needed to exercise
the new automatic export. The earlier disconnected attempts below are retained
as historical evidence.

RDP reports session 2 disconnected. A fresh x64 native probe and the newly
prepared native accessory comparison both fail at DX9 device creation with
`0x8876086C`, before drawing. DX11 Hardware on NVIDIA TITAN Xp and WARP still
run. No new native accessory comparison is accepted in this investigation.
The previously accepted native shadow controls and isolated batch remain
historical results, not proof of current GPU availability.

Evidence: `exports/accessory-device-check-x64.log`,
`exports/accessory-native-blocked-x64.log`.

## Inputs and provenance

Draw 2 uses FVF 274, stride 32, index start 6, 232 triangles. Neither of the
first two draws has a texture binding: texture decode, Mip or sampler changes
cannot fix this first failure.

The older `rhi-real-dx11-reduction-normals-{x64,x86}` archives supply complete
untextured snapshots. The analysis tool verifies each of their first two
draws against the later live trace: vertex/index hashes, draw range, all 253
recorded render/stage/sampler values, and world/view/projection matrices at
float32 precision. x64 and x86 have different vertex hashes; each is checked
against its own trace. The older x86 viewport is explicitly replaced with
the later reference viewport; these are diagnostic images.

The later trace did not record material/light values. Those still come from
the older archive, so this is not a new complete native capture. Independently,
the Hardware reconstruction matches the saved **live DX11 image byte for
byte** in each architecture's entire viewport. It reproduces the exact same
102/9 mismatching pixels against the saved native DX9 image, including all
first coordinates and color values. Repeating the DX11 draw is exact.

## Measured separation

| Hardware capture | All differing pixels | Delta exactly 1 | Delta above 1 | Maximum channel delta | Row containing all deltas above 1 |
| --- | --- | --- | --- | --- | --- |
| x64 | 102 | 95 | 7 | 87 | global y=505 |
| x86 | 9 | 1 | 8 | 72 | global y=337 |

These groups are diagnostic categories, not tolerances. Every nonzero delta
still fails the zero-difference gate.

Removing draw 1 changes its unrelated background coverage, but changes **none
of the originally divergent pixels** in either architecture. Disabling
specular produces exactly the original DX11 image. Disabling depth does not
fix any of the high-delta pixels; later overlapping faces overwrite earlier
ones in that control. These comparisons against saved native data are not
native counterfactual tests.

Six selected triangles (zero-based 134/135, 146/147, 226/227) form overlapping
top surfaces. Every one of their vertices has the exact same object-space
y coordinate, `0.32416996359825134`: they are coplanar. CPU double projection
places the small pairs at only 0.195 pixels high in x64 and 0.127 pixels in x86;
the long pair is about 0.445/0.289 pixels high. CPU projection is a geometry
diagnostic, not a native raster or depth oracle.

At **all 7/8 high-delta pixels**, an independently rendered DX11 triangle from
the small pairs exactly matches the saved native color. The combined DX11
batch instead shows another overlapping face. This identifies surface
selection as the immediate cause of the large color differences, while the
underlying depth representation/interpolation remains to be measured natively.
It does not identify the cause of the remaining delta-1 pixels.

Reversing all triangles and changing `LessEqual` to strict `Less` produce
identical DX11 images in each capture, consistent with equal represented-depth
ties. They fix only 4/7 and 5/8 original high-delta pixels and introduce other
differences: total mismatches increase to 134 and 23. Neither is a valid fix.
The production depth comparison and draw order remain unchanged.

WARP is recorded separately: original images differ at 76,142/31,944 pixels,
mostly delta 1 (53/32 pixels exceed 1). It is not substituted for the Hardware
baseline or presented as an accepted native equivalent.

## Reproduction and next native comparison

```powershell
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-saved-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
python tools/analyze_accessory_isolation.py exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64

# Requires actual native DX9 availability; tests both backends under each control.
./build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --accessory-native-hardware exports/rhi-real-dx11-reduction-normals-x64 exports/shadow-prefix-dx11-x64
```

Use the corresponding x86 paths and `warp` driver to reproduce those results.
Saved-image mode returns 32 for its failing baseline and retains all control
images; it never skips or treats the expected failure as success.

The first-divergence recorder now automatically freezes the entire preceding
prefix as `history_replay.dx11_prefix.drawN.*`. It includes target/clear,
geometry, index format from the recorder log, viewport, matrices, material,
lights, scissor, all captured states, textures, and explicit generated Mip
bytes plus per-level hashes. Native before-draw images accompany each batch;
the native image after the divergent draw remains `dx11_first_actual.bgra`.
The GUI harness retains these artifacts. The reader rejects corrupted or
duplicate prepared Mip levels and never enables texture input implicitly.

A fresh live capture using the existing default-off diagnostic flags will
provide current material/light proof; the comparison tool prefers that frozen
prefix when present. This new export has built successfully but could not be
exercised live while DX9 creation is failing. The next native experiment is
draw 2 alone and the six individual triangles, then the same coplanar pairs in
both orders under original `LessEqual` and diagnostic strict `Less`, using a
simple ID color to distinguish coverage/depth selection from lighting.

Evidence: `exports/accessory-saved-{hardware,warp}-{x64,x86}.log`, per-driver
image directories under `exports/shadow-prefix-dx11-{x64,x86}/`, and the
generated `analysis.json`. Both app/harness builds and eight focused CTests
pass (`exports/accessory-focused-{x64,x86}.log`), including corrupt/duplicate
Mip-proof rejection. Assets and generated evidence remain ignored. Rendering
stays on native DX9 and full-prefix DX11 acceptance remains blocked.
