# Accessory `.x` fixtures

Input of `rust/crates/mds-accessory/tests/`. Every file is written by
`gen_accessory_x.py` (Python 3, standard library only; Python 3.13 wrote these):

    python3 tests/fixtures/rust/accessory/gen_accessory_x.py

The output is deterministic. The run also writes `SHA256SUMS` (`sha256sum -c
SHA256SUMS` from this directory checks the files). The hashes at the time of
writing:

| File | sha256 |
|---|---|
| `bad_header.x` | `9a35b2eba1feebcc8f196c50b68bd41c1044e7448f765cdd7c67ba84626194ae` |
| `compressed_bzip.x` | `a3a06a194b3520892ab3192ec946af740814c20f5915f54e39c107a35f989e7f` |
| `compressed_tzip.x` | `4f543e6363ed86a3a12a6d72702357a1b835cac56048421cd0ff6ae902a91534` |
| `cube.x` | `1afa5c387b22797c997bfde9484462803184ab09ce80fd38570feed261c47995` |
| `cube_bin.x` | `6c53c41c7810bc17d4308eab72c5ee8a852f65a07383a64cf44577145f57f0c2` |
| `cube_bin64.x` | `154e4dcfb7b6c5c2adf17bc45e7ec06bb131b4d8637a657aa09ac092192f5e50` |
| `degenerate_face.x` | `7ea179b33b4d6845b6ca0fdf111105ea82a4095770c5c46c9395fe1abcc54edc` |
| `empty_mesh.x` | `c56bdd910de4124ed60b8009e6d7695dc4658a0921ffb045bfb55a788038ace6` |
| `face_index_range.x` | `ce1e37887d913ca27c4ad794f8be6ffdb0172fff91f2da25cc3dc420e931e122` |
| `face_two_vertices.x` | `07640f549cd891e1c3a28d8a3bd9863c17e910ac4eeff2e7d6fba1c88a5546dc` |
| `frame_matrix_short.x` | `de4bdbea17c8a580ea1d59afb5633cb23fef78ade560f436d276fd6e8106bfdf` |
| `frames.x` | `62cdc9640033586532c3bf546381a1d67c54c603cff040b64b89a36d33faef84` |
| `frames_normals.x` | `4adfcf2274fdfe93de4a0e55708ca96ec8a85a675ae55bce5e2af70f8dd29c62` |
| `material_count.x` | `fd950df60c95878104ea0b54f13150bd3c3a9928e27d8427fdf65d12e42657f5` |
| `material_index_range.x` | `93f6d86add276e8c45c5c9d9aae6ec28e268e5d93428f2d9b3493eef3515344e` |
| `multi_material.x` | `de6159219b141b10197ac5aff6c3cbe58c761ae2cd65d9608049a704446792c7` |
| `no_faces.x` | `6ec5b0ef8199e168aac09e5071219620444226ba8a1512696d143114491e25d5` |
| `no_mesh.x` | `d5ec9ba97e06bd42339fd3c6d7745fabf1438d0252adce593f7b3dc84ff1c223` |
| `no_normals_uvs.x` | `c35de3650b548939757b68f75f4c66824aa1396d16c90a76ed053bba8dfb68b9` |
| `normals_count.x` | `6eaa3010e234bbe776b946390af57591cdb1cc645c2ceb45be78e292c1c4c3ca` |
| `normals_no_uv.x` | `f9763961ffc962c8e746c429fbdb85206d1acabcc6fe1aab5de0a82d531c7661` |
| `normals_uv.x` | `16bbe9752efff101dabea1ef0cf8589c539c417016177eb23d22abefe56d4495` |
| `not_x.x` | `8d24a13510a79a5ad35dfd59933af1c2c963f654cfbe3fb965b240104aeb8ec2` |
| `placed.vac` | `326fafa211674331853a1908fd57b3f4adc0284e5e7fb93f4fda3a2ca28aa712` |
| `placed_default.vac` | `b31c48227e2a9421d9ddb28613d0d2b4e7f2ac8306ccb07ac8521826645d5403` |
| `sphere_map.x` | `100a497a7a5ac58b1674f247ee509549295f73ba43fb83a0e66784125175ecbe` |
| `stray_brace.x` | `cac4ec0efb3adeea66fb64a669b1e16b55cf6524a2601860068047eac3156528` |
| `texcoord_count.x` | `4654c702a8cae6b54da5c663c569cca15e8fbfa50c9e9d326999bcba64248357` |
| `truncated_mesh.x` | `bd4751c2a33e3f0dc769abca2c6f36d78845f7c2957fdeea722abc3913cd5149` |
| `unterminated.x` | `132377b13ef23c6e04c1d85924f8cabde98f5ff0a515550fc6279e84a9049e0c` |

## What each file is for

| File | Content | Tests |
|---|---|---|
| `cube.x` | `xof 0303txt 0032`. A template declaration, a `Header` object, comments, a cube of 8 positions and 6 quads with one normal per face, UVs, and one material with a texture. | `cube_text`: 24 vertices after D3DX splits one per normal, 36 indices, the vertex order of the split, the material colors and texture name. |
| `cube_bin.x`, `cube_bin64.x` | The same cube in the binary format (`0303bin 0032` and `0303bin 0064`, with a template to skip). | `cube_binary_matches_text`: equal to the text result. |
| `multi_material.x` | `0302txt`. Three materials, one of them a `{ Shared }` reference to a top-level `Material`, faces interleaved over the materials, a quad, normals and UVs. | Faces grouped by material, subset ranges, texture types 0, 1 and 5. |
| `frames.x` | `0302txt 0064`. Nested frames: a translation, a rotation inside it, a second translation after a mesh, and a top-level mesh. | Vertex positions after the merge, the new default material, computed normals. |
| `frames_normals.x` | Nested frames (scale 2 and a translation; a turn and a translation inside) over two quads with normals and UVs, and a top-level quad with a normal of length 2. | Normals under a frame transform (`mesh_dump.rs`). |
| `degenerate_face.x` | A face whose three corners are on one line, and one ordinary face, no normals. | The `acos` clamp of `D3DXComputeNormals` (`mesh_dump.rs`). |
| `no_normals_uvs.x` | One quad, no normals, no UVs, no material list. | Default material, computed normals, zero UVs. |
| `normals_no_uv.x` | One quad with a wrong normal (+Y) and no UVs. | The normal is replaced (`accessory.cpp:547`). |
| `normals_uv.x` | The same with UVs. | The normal stays. |
| `sphere_map.x` | Nine materials with `*`, `.sph`, `.spa`, `screen.bmp`, a case difference, an empty sphere part, no texture, and Shift-JIS names (cp932 bytes). | The texture types of `accessory.cpp:524-538`. |
| `placed.vac`, `placed_default.vac` | `.vac` files for `cube.x`: with all fields, and with only the two header lines. | `vac_sets_the_placement`, `vac_without_values_keeps_the_defaults`. |
| `bad_header.x` ... `stray_brace.x` | Malformed files, one fault each (header, compression, truncation, unterminated object, index and count mismatches, no mesh, no faces, short frame matrix). | `malformed_files_return_their_error` names the error of each. |

## Where the expected values come from

* `.x` layout and counts: the DirectX `.x` templates.
* Loader behavior (vertex splitting by normal, fan triangles, grouping faces by
  material, the default material, frame order, the float operations): the
  native `d3dx9_43.dll`, through the Windows dump in `dump/`. The crate first
  followed Wine's `dlls/d3dx9_36/mesh.c`; the dump corrected it where the two
  differ.
* Everything after the load: `src/render/accessory.cpp`, with line numbers in the tests.

## The Windows dump (`dump/`)

`dump/<file>.txt` is what `--mds-mesh-dump` (`src/tools/mesh_dump.cpp`, which
also describes the format) wrote for each `.x` and `.vac` file here: the native
`D3DXLoadMeshFromXW` result (`raw`), the frame tree of
`D3DXLoadMeshHierarchyFromXW` (`frame`, `container`), and the accessory record
after the C++ `LoadAccessoryObject` (`record`). A `.vac` has the record only.
`rust/crates/mds-accessory/tests/mesh_dump.rs` compares every file with the
crate: the load result or its failure, every vertex, index, attribute,
attribute range, material, texture type and name, and the placement. Floats
are compared bit for bit, with no tolerance.

Written on the Windows host `nanoha-lan` (i9-12900K, RTX 3090, VS 2022 Build
Tools, x64 Release) by the app built at `673ea35` with
`tools/windows/build.ps1`. `tools/oracle/accgold.ps1` ran the dump twice in the
console session, and the two runs gave the same bytes. A second session after
`degenerate_face.x` was added gave the same bytes again for the other 29 files.
To regenerate, from a checkout at `<checkout>`:

1. `tools\windows\build.ps1 -Root <checkout> -Testing OFF -Targets MikuDanceStudio`
2. `tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\accgold.ps1
   -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir>'`
3. Copy `<Out>\run1\*` to `dump/`.

The command line is `--mds-mesh-dump <pmm> <out-dir> <x-file>...`. WinMain loads
the PMM before any headless mode runs, so the mode needs one to host the
device; the lane uses the empty scene `../script/expected/empty/empty.pmm`.

D3DX takes the `rcpss` and `rsqrtss` estimates of the CPU, which differ between
CPU vendors. The crate reproduces those of the i9-12900K (`mds-math`), so the
dump holds for that CPU family.

### What the dump settled

The six points the Wine version left open:

1. **Face order inside a material.** File order, as the crate had
   (`multi_material.x`).
2. **Frame matrix order.** A frame's own matrix applies before its parent's
   (`new * transform` with row vectors), not Wine's order: `frames.x` mesh B
   is at `(10,1,0)`, not `(0,11,0)`. Each `FrameTransformMatrix` applies to
   the meshes after it in the frame, so `MeshA` in `frames.x` has the first
   matrix of `Outer` and `MeshC` both. The hierarchy loader keeps only the
   last matrix of a frame.
3. **Normals under a frame transform.** `D3DXVec3TransformNormal`, without the
   translation, then `D3DXVec3Normalize`. That runs for every mesh, a top-level
   one with the identity, so a file normal of `(0,0,2)` becomes
   `(0,0,1-2^-24)`. The file's normals are not normalized before; the vertex
   split compares them as written (`frames_normals.x`).
4. **`D3DXComputeNormals` weights.** The angle at a corner is the `acos`, in
   `f64`, of the dot product of the two edges after `D3DXVec3Normalize`, not
   the dot product over the product of the lengths. The face normal and the
   final vertex normal are `D3DXVec3Normalize`. At vertex 0 of
   `degenerate_face.x` that dot product is 1.0000001 and the native result is
   not NaN, so the clamp to `[-1, 1]` (or a guard with the same result) is
   real; without it the crate gives NaN there.
5. **Default material alpha.** 0, as in Wine: diffuse and specular
   `(0.5,0.5,0.5,0)`, ambient and emissive 0, power 0.
6. **Specular and emissive alpha.** 1 for a loaded `Material`, as in Wine.

Beyond those:

* Every position goes through `D3DXVec3TransformCoord`, also without a frame,
  and D3DX multiplies by its reciprocal estimate of `w` instead of dividing:
  `w = 1` scales by `1 - 2^-24`, so `cube.x`'s `-1` loads as `-0.99999994`. The
  binary files give the same, so it is not the text number parser.
* The attribute table has one range per attribute (vertex span from the lowest
  to the highest index) when the file holds one mesh, and no range when D3DX
  merged several (`frames.x`, `frames_normals.x`). What `DrawSubset` draws on
  a mesh without ranges is not checked here.
* D3DX rejects the 17 malformed files that the crate rejects (the dump has the
  `HRESULT`). The crate's error names are its own.
* The texture names that `LoadAccessoryObject` stores (after
  `ConvertMaterialName`) equal the crate's decoded names, the Shift-JIS ones of
  `sphere_map.x` included. No texture file exists next to the fixtures.

Still open: the text number parser beyond the `%.6f` numbers of these files
(all of them match), the vertex limit of `D3DXCreateMeshFVF`, and backslash
escapes in strings (no fixture has one).

| Dump | sha256 |
|---|---|
| `bad_header.x.txt` | `ae0f7814e3ba60ebd8be901c105cfd9e7b8d1594591c9ca0aa2e3c100f061cfd` |
| `compressed_bzip.x.txt` | `7a2b14f6412ca83388580711893fff2bbbd226d5070cd15da8d12529bb3bd69e` |
| `compressed_tzip.x.txt` | `5e81a4751d2e2fdfa36006e2bb3d2849da7886306b51b9de53343a6f0bbb71de` |
| `cube.x.txt` | `98657f0f3bf2b2f36768e1976c9540e861d9a17e6f6fd9745f728998d8690c07` |
| `cube_bin.x.txt` | `baaa363fea4d6cfaef5c2c3b9f085e1980fa80dce53f547ee8495aca50eda3ac` |
| `cube_bin64.x.txt` | `84965225fa356053d9a9b892f0a8956c5d0eca8ca9b328336f4af7da4531a3ff` |
| `degenerate_face.x.txt` | `dffb5fb94eb01857c903cfb6cb291df75c4043803132d9acdbdc9836eb9c6b1a` |
| `empty_mesh.x.txt` | `a772046edd6f269ec97c757e724d01d13d8fc0b3c1aadaac4e3dfbee1b0b5b92` |
| `face_index_range.x.txt` | `6a8448028fede8aabd03bee7685f72d159ce921892266b53b7a71acb4451dad5` |
| `face_two_vertices.x.txt` | `f96044c7a50ecf5010ee11af116732da58485b7831259258ef245548610d8f17` |
| `frame_matrix_short.x.txt` | `df86cfc415ca66183b7327de5217e950d0a8bf93c121ce23e83012739c0c95eb` |
| `frames.x.txt` | `c3b2d200619c37f344244645f84444cbde5bbfcff41c5fd552033de676a17e1c` |
| `frames_normals.x.txt` | `e02a95eede10772465d0620aba5bf639a6c1f43a353ceae38f4bf3d4ff0a49b9` |
| `material_count.x.txt` | `a661c70561d2521e88fac4b5955b9af49e3ffe176ee00b0a797d13de6cb7b473` |
| `material_index_range.x.txt` | `08adac4f406fa80b99860055b72a6d2a953e545af5fdb5fd09a31a61af2fc9e2` |
| `multi_material.x.txt` | `c935bd4a1546b4361c1802557d1fd889db948ad0187bb26decc91a7afefaefe9` |
| `no_faces.x.txt` | `7010ddce957a85dd9890b094e420fec1b42e118b367a735ed565e7719e0d6986` |
| `no_mesh.x.txt` | `5951e55e0fa1e00bd883fc6703453b6a9801ec3dd7b6777cd909e366733c6ca7` |
| `no_normals_uvs.x.txt` | `30a5e346835ac379474b330ae087d308646a473ef819c4576648d9a595bd6f53` |
| `normals_count.x.txt` | `a3b6e1f0c3b09c894aa037c1d6d634b89bcdb5e552e08a4df02124dc9b2a162e` |
| `normals_no_uv.x.txt` | `ffaad245b3329d36dc7b07d7be6296356215deb72e4c55f17223812459b74b74` |
| `normals_uv.x.txt` | `ba731c41f8243031e55ee1958a0eab8d934a1ca9632f79a9695103b387503aca` |
| `not_x.x.txt` | `145308bda0992f548935f687b669b030689a33d0272b097ea51a51424adc42b6` |
| `placed.vac.txt` | `fbafa06b1ce7e4a12b6c96b834c63158921e34695ac23a5c9a94ca5fded555ea` |
| `placed_default.vac.txt` | `fa55bb9ee7ef911ce00643899e8b644cc83ad259ef854abce65d88862a555d18` |
| `sphere_map.x.txt` | `6058cc5ea4500cd78d8d41d8e6e6e8ab3dfe847bfdba07511a0a2ecc28f1b663` |
| `stray_brace.x.txt` | `d3de26bfc1455d69e59470c7f36f5eb8f73a1b52b1d794995c13f79b0d6a2c58` |
| `texcoord_count.x.txt` | `7ed17c05f331cc59648c0f5f9e647e7b54710be83b45fb41bce69bef464b97bb` |
| `truncated_mesh.x.txt` | `2c40d539c0c3cd3fb8ff31fe9b2f42850d8e56393ae61c6b41e78f1f85e47488` |
| `unterminated.x.txt` | `dc09dc375c56a96bfb9e2249a7465acfd9dc65044bb0d24007ba2490de5badb7` |

## Not covered

Skin meshes and animation objects (skipped, as D3DX does without skin info),
a `{ Name }` reference to a `Mesh` inside a `Frame` (parsed, not in a fixture),
compressed files (`tzip`, `bzip`: `Unsupported`), a `.vac` whose middle field is malformed (the crate keeps the defaults from there on; C `fscanf` keeps reading), and the `ExtractXTexture`
retry of the C++, which re-reads the texture name from the same text.
