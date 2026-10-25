# mds-skin fixtures

`skin.dump` is the output of `tools/skin_check` on `cases.txt`. The harness
loads each model with the real C++ loaders (`src/model/pmx_load.cpp`,
`src/model/pmd_load.cpp`). For each case it runs the real `ModelApplyMorphs`
(`src/model/morph_apply.cpp`) and `UpdateModelVertexBuffers`
(`src/model/model_skinning.cpp`). The test `rust/crates/mds-skin/tests/skin_check.rs`
writes the same text from Rust and requires it to be byte-identical.

| File | sha256 |
|---|---|
| `skin.dump` | `b5aa5f1204078a1650279c417b1bb3f6135c1916167f1269c7de6087e21c6309` |
| `cases.txt` | `9a1da11806023ad9eee6bee8c326aebf3bb55f6cf8270cc57c1f0079d5d63cd6` |
| `skin.pmx` | `c717df6ee5ee9072085cf51b155c163d30405616cb0b2aaf824914481d0bcd45` |
| `skin.pmd` | `133c53b04d7c3cdcb09d7c61009ee27d7ab527875cf437606cbfb839e50f6470` |
| `skin_dup.pmx` | `4bcd391e3c9ce0bcae283b9eb3c15bbb84ea62adc0cd79949b5e9559c43be431` |
| `skin_uv4.pmx` | `2f80eeafdb75f07c240151df2baa1bdf76e82d58a8e638c47459c705b76a4bed` |

## Regenerate

From the repository root, on macOS with Apple clang and cargo:

```sh
python3 -I tests/fixtures/rust/skin/gen_skin.py --write   # the models and cases.txt
tools/skin_check/run.sh tests/fixtures/rust/skin/skin.dump
shasum -a 256 tests/fixtures/rust/skin/*.dump tests/fixtures/rust/skin/cases.txt
```

`gen_skin.py --check` compares the generated files with the committed
ones without writing anything.

The cases cover `chain8.pmx`, `chain8.pmd` and `morph4.pmx` (in
`tests/fixtures/rust`) plus the four models here, 26 cases in total.
`skin.pmx` has:

- BDEF1, BDEF2, BDEF4 and SDEF vertices, and bone references of -1.
- Two additional UVs.
- Three materials whose edge sizes decide the material of shared vertices.
- Vertex, UV and additional UV morphs.
- Multiplicative, additive and all-material material morphs.
- Bone morphs, and a group morph over all of these.

Two of its vertices become QDEF after loading (the `qdef` line), because the
C++ loader accepts only PMX 2.0, which has no QDEF. `skin.pmd` has:

- A base morph whose position differs from the vertex record.
- A weight over 127, which the loader reads as a negative `int8`.
- A bone index of `0xFFFF`.
- Vertices with the edge off.

Both models also have a case with `-0.0` matrix entries.

`skin_dup.pmx` has the vertices, bones and materials of `skin.pmx` and four
bone morphs: three that name bones twice in one morph and across morphs, and a
group over them. The C++ loader skips a bone for the bone morph table only
when an earlier morph moves it (`pmx_load.cpp`, the `j < i` scans), so a bone
named twice in one morph gets a second, unused `b` record. `skin_uv4.pmx` has
four additional UVs and a morph of every UV kind from 3 to 7, two of them
(kind 7) sharing a vertex, and a group morph.

## How the harness computes

The harness does not invent any D3DX math. `tools/skin_check/ffi` is a
static library that exports `mds-math` (D3DX) and `mds-crtmath` (the MSVC
UCRT `acosf`, `sinf` and `cosf`) through a C ABI. The `d3dx_dyn.hpp` shim
calls it, and `crt_math.h` reroutes `std::acos`, `std::sin` and `std::cos`
in `morph_apply.cpp` to it. Every C++ file builds with `-ffp-contract=off`,
because MSVC x64 rounds every float operation. Physics bodies, textures,
the bone sort order and `PostLoadInit` are no-ops. They do not reach the
vertex buffers.

## Dump format

The dump has one line per item, and floats are the 8 hex digits of their
bits.

- `model <file> <pmx|pmd> vertices <n> stride <bytes>`
- `case <name>`
- `v <i> <main record> <edge record>`: the main record is position, normal,
  UV and each additional UV. The edge record is the position and the
  `A8R8G8B8` color.
- `m <i> <16 floats>`: diffuse RGB (`diffuseMirror`), diffuse alpha,
  specular, ambient, specular power, edge color and edge size.
- `b <i> <bone> <translation> <rotation>`: the bone morph work records. The
  Rust side computes these with `mds_pose::pose::apply_morphs`.

## What render2 needs to consume mds-skin

`mds-render` skins on its own in `mesh.rs`, with BDEF weights only. Its edge
pass pushes back faces out by a fitted constant (`EDGE_WORLD`). To match the
C++, render2 needs these changes:

- Upload `Skin::main` as the vertex buffer: `Skin::stride()` floats per
  vertex with position, normal, UV and the additional UVs. This replaces the
  skinning and vertex morphs of `mesh.rs`, and adds SDEF, the QDEF hold and
  UV morphs.
- Draw the edge from `Skin::edge`: positions already pushed out on the CPU
  by camera distance, field of view, edge thickness, vertex edge scale and
  material edge size, plus the packed edge color. The edge pass then needs
  no shader push and no `EDGE_WORLD`. Self-shadow mode makes the edge alpha
  opaque (`View::self_shadow`).
- Take the material colors from `Skin::materials` after
  `Skin::apply_morphs`: `diffuse_mirror[0..3]` with `diffuse[3]`, then
  `specular`, `ambient`, `specular_power`, `edge_color` and `edge_size`. The
  texture, sphere and toon tints are computed in `Skin::material_add` and
  `Skin::material_mul`, but the C++ never writes them to a material.
- Call `apply_morphs` and then `update` each frame. Pass the bone
  `mat_init` matrices that `mds-pose` leaves, the morph weights, the frame
  world matrix and the camera.
- Settle the license first. `mds-render` is MIT and `mds-skin` ports
  upstream C++ (license pending), so `mds-render` cannot depend on it until
  the license of `mds-skin` is settled.
