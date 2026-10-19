# Ground geometry contract and native image checks

The subsequent [line/depth isolation](RHI_GROUND_HISTORY_ISOLATION.md) reduces
the ground line failure to two vertices of segment 18 and the ground-history
failure to one plane triangle followed by one accessory triangle. Both repros
agree byte-for-byte across executable architectures on fixed archive inputs.

`ModelPipeline::topology` now explicitly selects `TriangleList` or `LineList`.
The default remains triangles. Unsupported topologies block conversion and
submission; a list must contain complete primitives (three or two vertices).
This extends the model pipeline, not the screen-space HUD layout.

`ModelReplayDraw::indexed` selects one of two mutually exclusive ranges:

| Draw | Resource and range |
| --- | --- |
| Indexed | Published vertex and index keys; `firstIndex`, `indexCount`, `vertexCount` bounds every index. Nonindexed range fields are zero. |
| Nonindexed | Published vertex key; `firstVertex`, `drawVertexCount`. Index key and indexed range fields are zero. |

Validation checks the entire stream before device mutation. Both paths require
current immutable vertex versions, matching layouts, nonempty ranges and
overflow-safe bounds. Nonindexed draws need no index resource or publication.
The DX9 converter respects native primitive counts, index min/count constraints
and nonindexed start vertices. Unused native index bindings do not become
portable dependencies. Conversion failure still leaves the input stream intact.

The DX11 adapter selects native topology per pipeline, unbinds the index buffer
for nonindexed submission and checks device identity/epoch on both paths.
`NonIndexedDraw::layout` must explicitly match the model pipeline. Legacy fixed
draws may inherit their existing layout; an explicit mismatch fails on DX9,
DX11 and Null. Model XYZ/RGBA8 vertices are 16 bytes, distinct from screen-space
selection vertices (20 bytes) and HUD vertices (28 bytes).

## Generated tests

`tests/ground_replay_fixture.hpp` generates redistributable grid lines and a
plane, with no PMM, model or font asset dependency. It exercises indexed and
nonindexed lines and triangles, nonzero starts, out-of-range sentinels outside
the requested range, texture and topology transitions, depth occlusion,
64/80/64 target sizes, repeated prefixes and device replacement. Full images
are compared with fresh native DX9 draws; selected colors also have a CPU
oracle. The hardware and WARP tests each compare 60 images per architecture.
Direct submissions verify stale epoch, replaced-device handle and mismatched
layout rejection, followed by successful fresh submission.

Focused CTests pass on x64 and x86 for ground Hardware/WARP, native/Hardware/WARP
Mip capture, converted shadows and shadow CPU oracle, viewport and stream
validation. A separate formats-only build with the DX11 adapter disabled passes
the converter, stream validator and Null layout checks. Linux/macOS execution
was not performed during this step; the portable stream validator already
belongs to their existing CI test graph. Evidence logs are
`exports/ground-focused-{x64,x86}.log` and `exports/ground-cpu.log`.

The portable `rhi_model_replay` test covers list arity, unsupported topology,
mixed ranges, nonindexed draws without any index resource, missing/old vertex
versions and overflow/bounds rejection. The CPU converter test checks both
ground commands and transactional failures; the snapshot reader accepts
nonindexed captures without inventing an index format.

## Fresh real PMM results (2026-10-04)

Both GUI runs recover the missing model in real `sample.pmm` and enable the
ground grid only in a temporary PMM copy. The application keeps DX9 rendering.
Each fresh capture now reports `READY`, **51 draws, 195 events, 143 resource
versions**, covering two ground, 19 accessory, 17 shadow and 13 model draws.
All **52 native reconstruction boundaries are exact** on both architectures.
The DX11 normal/material candidate repeats its final image exactly.

| Image gate | x64, viewport (565,25,1032,774) | x86, viewport (274,25,670,503) |
| --- | --- | --- |
| Ground line draw alone / first boundary | 2 differing pixels, max delta 75; first (1380,634) | Zero differences |
| Ground plane draw alone | Zero differences | Zero differences |
| Ground line + plane boundary | 2 differing pixels, max delta 255 | Zero differences |
| First failing complete-prefix boundary | Draw 1, ground | Draw 6, accessory; 1 pixel, max delta 255 at (922,439) |
| Failed prefix boundaries | 51/52 | 46/52 |
| Final prefix difference | 19 pixels | 1 pixel |

The x64 ground line mismatch occurs without any preceding geometry; the plane
alone is exact. On x86 every one of the 51 draws is exact **in isolation**, but
the prefix first differs after accessory draw 6 with ground history present.
Thus passing isolated batches does not establish equivalent depth/stencil
history. No depth bias, changed viewport or tolerance hides these failures.
The earlier no-ground x64 viewport-sensitive failures remain separately
documented in [the prefix investigation](RHI_SCENE_PREFIX_DIAGNOSTIC.md).

Evidence is retained in ignored `exports/ground-rhi-prefix-{x64,x86}/`: native
states and bytes, every boundary image, per-draw isolated comparisons, summary
and independently audited `candidate/analysis.json`. The generated tests and
interfaces can be committed without these private assets. Reproduce with
`tools/run_scene_prefix_diagnostic.py --ground` using the existing prefix
runner arguments, then `tools/analyze_scene_prefix.py ARCHIVE`.

The adapter contract is implemented; **real scene image acceptance remains
failed**. Production renderer selection and whole-scene history capability
remain unchanged. The next diagnostic should reduce the two x64 ground pixels
by line segment and the x86 accessory pixel by prior ground depth, keeping
these failures separate from portable interface progress.
