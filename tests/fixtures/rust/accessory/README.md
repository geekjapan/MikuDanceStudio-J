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
| `empty_mesh.x` | `c56bdd910de4124ed60b8009e6d7695dc4658a0921ffb045bfb55a788038ace6` |
| `face_index_range.x` | `ce1e37887d913ca27c4ad794f8be6ffdb0172fff91f2da25cc3dc420e931e122` |
| `face_two_vertices.x` | `07640f549cd891e1c3a28d8a3bd9863c17e910ac4eeff2e7d6fba1c88a5546dc` |
| `frame_matrix_short.x` | `de4bdbea17c8a580ea1d59afb5633cb23fef78ade560f436d276fd6e8106bfdf` |
| `frames.x` | `62cdc9640033586532c3bf546381a1d67c54c603cff040b64b89a36d33faef84` |
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
| `no_normals_uvs.x` | One quad, no normals, no UVs, no material list. | Default material, computed normals, zero UVs. |
| `normals_no_uv.x` | One quad with a wrong normal (+Y) and no UVs. | The normal is replaced (`accessory.cpp:547`). |
| `normals_uv.x` | The same with UVs. | The normal stays. |
| `sphere_map.x` | Nine materials with `*`, `.sph`, `.spa`, `screen.bmp`, a case difference, an empty sphere part, no texture, and Shift-JIS names (cp932 bytes). | The texture types of `accessory.cpp:524-538`. |
| `placed.vac`, `placed_default.vac` | `.vac` files for `cube.x`: with all fields, and with only the two header lines. | `vac_sets_the_placement`, `vac_without_values_keeps_the_defaults`. |
| `bad_header.x` ... `stray_brace.x` | Malformed files, one fault each (header, compression, truncation, unterminated object, index and count mismatches, no mesh, no faces, short frame matrix). | `malformed_files_return_their_error` names the error of each. |

## Where the expected values come from

* `.x` layout and counts: the DirectX `.x` templates.
* Loader behavior (vertex splitting by normal, fan triangles, grouping faces by
  material, the default material, frame order): `D3DXLoadMeshFromXInMemory`
  as implemented in Wine `dlls/d3dx9_36/mesh.c`, not the native `d3dx9_43.dll`.
  Nothing here has run on Windows.
* Everything after the load: `src/render/accessory.cpp`, with line numbers in the tests.

## accgold

The slice `accgold` will compare this crate with a Windows D3DX mesh dump: the
real `D3DXLoadMeshFromXW` result of these same files (vertex buffer, index
buffer, attribute buffer, `D3DXMATERIAL` array, `GetFVF`) after the code path of
`LoadAccessoryObject`. These points decide which Wine assumption is wrong:

1. **Face order inside a material.** The crate keeps file order within one
   material (a stable sort). `OptimizeInplace(ATTRSORT)` may order differently.
2. **Frame matrix order.** The crate multiplies `parent * child`, as Wine's
   `parse_frame` does (`frames.x`: B at `(0,11,0)`). The usual scene-graph order,
   `child * parent`, gives `(10,1,0)`.
3. **Normals under a frame transform.** Wine moves the normal with
   `D3DXVec3TransformCoord`, translation included, and does not normalize it
   again. A native `d3dx9_43.dll` may use `TransformNormal`.
4. **`D3DXComputeNormals` weights.** Angle at each corner, no vertex welding
   (adjacency NULL), `acos` of the ratio clamped to `[-1, 1]` and evaluated
   in `f64`. The clamp is not in Wine.
5. **Default material alpha.** Wine gives the mesh without a material list
   diffuse alpha 0 (so `drawn_alpha` is 0); native may give 1.
6. **Specular and emissive alpha.** Both 1 for a loaded `Material`, as in Wine.
7. **Text number parsing.** `str::parse::<f32>`; D3DX has its own text parser.
8. **Vertex limit.** More than 65535 vertices is an error (16-bit indices, option
   544); the exact limit of `D3DXCreateMeshFVF` is unchecked.
9. **Strings.** A `TextureFilename` is kept byte for byte, backslash escapes
   included.

## Not covered

Skin meshes and animation objects (skipped, as D3DX does without skin info),
a `{ Name }` reference to a `Mesh` inside a `Frame` (parsed, not in a fixture),
compressed files (`tzip`, `bzip`: `Unsupported`), a `.vac` whose middle field is malformed (the crate keeps the defaults from there on; C `fscanf` keeps reading), and the `ExtractXTexture`
retry of the C++, which re-reads the texture name from the same text.
