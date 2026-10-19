# Independent line coverage and ground depth repros

The subsequent [endpoint and depth-threshold measurements](RHI_GROUND_ENDPOINT_DEPTH.md)
feed the same clip coordinates to both APIs. The line coverage failure persists;
the plane's measured ruler threshold differs by one float32 input step while
the accessory agrees. These controls move both failures beyond the original
vertex transformation stage, with native clipping/viewport/raster behavior
still unresolved.

The [ground geometry milestone](RHI_GROUND_GEOMETRY.md) admitted both ground
commands, but retained real image failures. This step changes only the
diagnostic executable and evidence auditor. Production rendering remains DX9;
no raster rule, depth comparison, bias, viewport or acceptance tolerance changes.

## Ground line: two vertices and two neighboring pixels

The x64 archive uses viewport `(565,25,1032,774)`. Fresh native reconstruction
matches the saved application image and the DX11 candidate matches the preceding
saved candidate. Each baseline is repeated three times, with identical bytes.
Every one of the 45 line segments is drawn independently in both endpoint
orders, retaining original state, matrices, colors and index semantics.

Only **segment 18** differs. It references original vertices 34 and 35:
`(20,0.100000001,-50)` and `(20,0.100000001,50)`, both native ARGB
`4290032820` (opaque RGB 180). The failure survives a compact two-vertex buffer
and a two-index buffer, and does not depend on other grid segments.

| Target pixel | Native DX9 BGRA | DX11 candidate BGRA |
| --- | --- | --- |
| (1380,634) | 255,255,255,255 (background) | 180,180,180,255 (line) |
| (1380,635) | 180,180,180,255 (line) | 255,255,255,255 (background) |

Reversing endpoints preserves these exact images. Disabling depth testing,
depth writes, stencil, alpha test or blending separately also preserves these
two differences. A uniform red line with lighting, depth, stencil, alpha test
and blending disabled still exchanges coverage between the same two pixels,
now with maximum delta 255. This is a transformed-position/line-coverage
boundary, independent of the tested color, depth and stencil effects. The
experiment does **not** yet distinguish coordinate precision from the native
line rasterization rule.

The line investigation contains **104 controls**: four baseline/repetitions,
seven state/order controls, 90 individual/reversed segments, and three compact
controls for the differing segment. The original 44 other segments are exact.

## Ground depth: one plane triangle and one accessory triangle

The x86 archive uses viewport `(274,25,670,503)`. The first differing prefix is
after draw 6 at `(922,439)`. Exhaustive enumeration of all **32 subsets** of
draws 1 through 5, preserving order and always drawing the original draw 6 last,
finds a single minimal subset: **draw 2 (plane), then draw 6 (accessory)**.
Every subset containing the plane reproduces the pixel; every subset without
the plane is exact. The grid and preceding three accessory draws are unnecessary.

The plane's depth writes are necessary. Disabling them removes the difference;
disabling only grid depth writes does not. Disabling all stencil testing,
ground stencil writes, selected stencil or selected blending does not remove
the difference. Color-masked plane drawing with stencil disabled still fails,
so plane color and stencil contents are unnecessary.

Binary reduction of the accessory's 1162 triangles, plus independent testing of
the plane's two triangles, gives:

| Draw | Source primitive (zero based) | Original vertex indices |
| --- | --- | --- |
| Plane draw 2 | 1 | 3,4,5 |
| Accessory draw 6 | 1141 | 13308,13315,13313 |

Both triangles survive independent buffer compaction: plane 48 bytes, accessory
96 bytes, accessory indices 6 bytes. All matrices, normals, material, textures
and raster state are retained. Each triangle drawn alone is exact; their ordered
pair reproduces the original one-pixel difference. The compact geometry is
checked byte-for-byte against the original referenced vertices by the auditor.

| Selected triangle depth rule | Native result at focus | Candidate result at focus |
| --- | --- | --- |
| LessEqual (original) | Accessory BGRA 96,75,66,255 | Plane BGRA 255,255,255,0 |
| Less | Plane retained | Plane retained |
| Equal | Accessory passes | Plane retained |
| Always or depth disabled | Accessory passes | Accessory passes |

These controls constrain the comparison: native depth compares equal to the
stored plane depth, while candidate depth compares greater. Stencil-free
controls independently preserve the failure. This is an **indirect depth
comparison measurement**, not raw D24 attachment readback, and it does not
establish the number of quantization steps or a driver arithmetic formula.
The remaining distinction is between transformed vertex depth, triangle depth
plane construction/evaluation, and depth quantization.

The history investigation contains **50 controls**, including baseline
repetitions, all prior subsets and 14 state controls. The triangle reduction
adds **38 controls** with both binary branches where necessary, isolated draws,
buffer compaction and depth/stencil controls.

## Architecture, stability and verification

Both executables run the **same x64 line archive** and the **same x86 depth
archive**. SHA-256 agrees for all **214 line artifacts** and **84 depth-reduction
artifacts**, including every native/candidate image, control/pixel CSV, compact
geometry and completion summary. These fixed-input failures are therefore not
an x64-versus-x86 executable difference. Viewport/geometry inputs are kept fixed
for this check; the archives' different viewports are not conflated.

Independent auditing verifies every saved image size, pixel delta, maximum
delta, first coordinate, full image hash, per-pixel value and baseline change.
It proves the native baseline against saved application output and the candidate
baseline against the earlier candidate output, verifies all three repetitions,
checks endpoint/range reduction and compact geometry, and fingerprints source
state/geometry/texture files. A successful audit means valid diagnostic evidence,
not image acceptance. Fresh-output checks prevent reuse of stale partial runs.

Focused converter, ground hardware and portable replay CTests pass **3/3 on
x64 and 3/3 on x86**. The generated ground test still compares 60 images with
zero differences per run. CPU and image evidence are retained in ignored
`exports/`; no private PMM or model data is added to the repository.

## Reproduction

After building `rhi_d3d9_replay_conversion_test`, use fresh output directories:

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-lines-isolation exports/ground-rhi-prefix-x64 exports/new-line-isolation
python tools/analyze_ground_history_isolation.py lines exports/ground-rhi-prefix-x64 exports/new-line-isolation
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-history-isolation exports/ground-rhi-prefix-x86 exports/new-ground-history 6
python tools/analyze_ground_history_isolation.py history exports/ground-rhi-prefix-x86 exports/new-ground-history
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --ground-depth-reduction exports/ground-rhi-prefix-x86 exports/new-ground-depth 6
python tools/analyze_ground_history_isolation.py reduction exports/ground-rhi-prefix-x86 exports/new-ground-depth
```

Current evidence:

- `exports/ground-line-compact-{x64,x86}/`: same x64 source archive, 104 controls.
- `exports/ground-history-isolation-x86/`: all 32 prior-history subsets.
- `exports/ground-depth-reduction-{x64,x86}/`: same x86 source archive, 38 controls.
- `exports/ground-isolation-shared-input-architecture.json`: cross-executable hashes.
- `exports/ground-isolation-regression-{x64,x86}.log`: focused CTest results.

Next, use these two independent minimal inputs: compare common transformed
endpoints for segment 18, and measure depth thresholds for the compact triangle
pair. Keep scene image acceptance blocked until the original unaltered images
pass; diagnostic state controls must not become production fixes.
