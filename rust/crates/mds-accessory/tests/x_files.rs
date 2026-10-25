//! Each fixture of `tests/fixtures/rust/accessory/` against the values its generator
//! (`gen_accessory_x.py`) puts in it.
//!
//! "Spec" below means the DirectX `.x` templates (counts and layout), "D3DX" the
//! loader rules of `D3DXLoadMeshFromXInMemory` as Wine implements them (vertex
//! duplication order, fan triangulation, attribute sort, default material, frame
//! order), and "C++" the lines of `src/render/accessory.cpp` named in each test.
//! No expected value comes from running this crate.

use mds_accessory::mesh::XMesh;
use mds_accessory::{load_x, Accessory, Error, TextureKind};
use std::path::PathBuf;

fn fixture(name: &str) -> Vec<u8> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/rust/accessory")
        .join(name);
    std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn load(name: &str) -> Accessory {
    load_x(&fixture(name)).unwrap_or_else(|e| panic!("{name}: {e}"))
}

fn close(got: [f32; 3], want: [f32; 3], tol: f32) {
    assert!(
        got.iter().zip(want).all(|(g, w)| (g - w).abs() < tol),
        "{got:?} != {want:?}"
    );
}

fn tri(a: &Accessory, face: usize) -> [[f32; 3]; 3] {
    std::array::from_fn(|k| a.vertices[a.indices[face * 3 + k] as usize].position)
}

const CUBE_V: [[f32; 3]; 8] = [
    [-1., -1., -1.],
    [1., -1., -1.],
    [1., 1., -1.],
    [-1., 1., -1.],
    [-1., -1., 1.],
    [1., -1., 1.],
    [1., 1., 1.],
    [-1., 1., 1.],
];
const CUBE_F: [[usize; 4]; 6] = [
    [0, 3, 2, 1],
    [4, 5, 6, 7],
    [0, 4, 7, 3],
    [1, 2, 6, 5],
    [0, 1, 5, 4],
    [3, 7, 6, 2],
];
const CUBE_N: [[f32; 3]; 6] = [
    [0., 0., -1.],
    [0., 0., 1.],
    [-1., 0., 0.],
    [1., 0., 0.],
    [0., -1., 0.],
    [0., 1., 0.],
];
const CUBE_UV: [[f32; 2]; 8] = [
    [0., 0.],
    [1., 0.],
    [1., 1.],
    [0., 1.],
    [0., 0.],
    [1., 0.],
    [1., 1.],
    [0., 1.],
];

fn check_cube(a: &Accessory) {
    // Spec: 6 quads are 12 triangles. D3DX: each cube corner is used with three
    // different normals, so it becomes three vertices: 8 + 16 copies.
    assert_eq!(a.vertices.len(), 24);
    assert_eq!(a.indices.len(), 36);
    assert_eq!(a.face_material, vec![0; 12]);
    assert_eq!(a.materials.len(), 1);
    assert!(!a.normals_computed, "C++ 547: FVF is 274 already");
    for (q, quad) in CUBE_F.iter().enumerate() {
        // D3DX fans a polygon from its first vertex: (0,1,2), (0,2,3).
        for (k, fan) in [[0, 1, 2], [0, 2, 3]].iter().enumerate() {
            let face = 2 * q + k;
            for (c, &corner) in fan.iter().enumerate() {
                let v = &a.vertices[a.indices[face * 3 + c] as usize];
                assert_eq!(
                    v.position, CUBE_V[quad[corner]],
                    "quad {q} face {k} corner {c}"
                );
                // The file's normals pass through D3DXVec3Normalize, whose reciprocal
                // square root estimate leaves 1 - 2^-24 for a unit vector.
                close(v.normal, CUBE_N[q], 1e-6);
                assert_eq!(v.texcoord, CUBE_UV[quad[corner]]);
            }
        }
    }
    // D3DX keeps a vertex's first normal; later normals append copies in face order.
    // Face 0 (-Z) and 1 (+Z) own the first 8; face 2 (-X) appends 8..=11 for
    // corners 0, 4, 7, 3.
    let near = |v: usize, pos: [f32; 3], n: [f32; 3]| {
        assert_eq!(a.vertices[v].position, pos, "vertex {v}");
        close(a.vertices[v].normal, n, 1e-6);
    };
    near(0, CUBE_V[0], CUBE_N[0]);
    near(4, CUBE_V[4], CUBE_N[1]);
    near(8, CUBE_V[0], CUBE_N[2]);
    near(9, CUBE_V[4], CUBE_N[2]);
    near(10, CUBE_V[7], CUBE_N[2]);
    near(11, CUBE_V[3], CUBE_N[2]);
    near(23, CUBE_V[2], CUBE_N[5]);

    // C++ 513-519: Ambient = Diffuse; Diffuse and Specular RGB times 0.1.
    let m = &a.materials[0];
    assert_eq!(m.ambient, [0.8, 0.4, 0.2, 1.0]);
    assert_eq!(m.diffuse, [0.8f32 * 0.1, 0.4f32 * 0.1, 0.2f32 * 0.1, 1.0]);
    assert_eq!(m.specular, [0.5f32 * 0.1, 0.25f32 * 0.1, 1.0f32 * 0.1, 1.0]);
    assert_eq!(m.emissive, [0.1, 0.2, 0.3, 1.0]);
    assert_eq!(m.power, 10.0);
    assert_eq!(m.texture.kind, TextureKind::Plain);
    assert_eq!(m.texture.primary.text, "cube.bmp");
    assert_eq!(m.texture.sphere.text, "");
}

#[test]
fn cube_text() {
    check_cube(&load("cube.x"));
}

#[test]
fn cube_binary_matches_text() {
    let text = load("cube.x");
    assert_eq!(load("cube_bin.x"), text);
    assert_eq!(load("cube_bin64.x"), text, "0064 floats");
    check_cube(&load("cube_bin.x"));
}

#[test]
fn several_materials_group_faces_and_resolve_references() {
    let a = load("multi_material.x");
    // Spec: faces are tri, quad, tri, tri = 5 triangles; all normals are one vector
    // used at every corner, so no vertex splits.
    assert_eq!(a.vertices.len(), 6);
    assert_eq!(a.materials.len(), 3);
    // Per polygon material 2,0,1,0; triangles in file order carry 2,0,0,1,0.
    // D3DX groups faces by material (ATTRSORT), here in file order within a group.
    assert_eq!(a.face_material, vec![0, 0, 0, 1, 2]);
    assert_eq!(a.indices, vec![1, 3, 4, 1, 4, 2, 0, 2, 5, 2, 4, 5, 0, 1, 2]);
    assert_eq!(a.subset_faces(0).collect::<Vec<_>>(), vec![0, 1, 2]);
    assert_eq!(a.subset_faces(1).collect::<Vec<_>>(), vec![3]);
    assert_eq!(a.subset_faces(2).collect::<Vec<_>>(), vec![4]);
    assert_eq!(a.vertices[3].texcoord, [1.0, 0.0]);
    assert!(!a.normals_computed);

    let kinds: Vec<_> = a.materials.iter().map(|m| m.texture.kind).collect();
    assert_eq!(
        kinds,
        [
            TextureKind::Plain,
            TextureKind::SphereMultiply,
            TextureKind::SubAdd
        ]
    );
    assert_eq!(a.materials[0].texture.primary.text, "a.bmp");
    // `{ Shared }` is the top-level Material of that name.
    assert_eq!(a.materials[1].texture.primary.text, "env.sph");
    assert_eq!(a.materials[1].diffuse[3], 0.5);
    assert_eq!(a.materials[2].texture.primary.text, "b.bmp");
    assert_eq!(a.materials[2].texture.sphere.text, "c.spa");
    assert_eq!(a.materials[0].diffuse, [0.1, 0.0, 0.0, 1.0]);
}

#[test]
fn nested_frames_apply_their_transforms_in_order() {
    let a = load("frames.x");
    assert_eq!(a.vertices.len(), 12);
    assert_eq!(a.indices, (0..12).collect::<Vec<u32>>());
    // Meshes come in traversal order: A (in Outer), B (in Inner), C (after Outer's
    // second matrix), Top.
    // A: translation (10,0,0).
    assert_eq!(tri(&a, 0), [[11., 0., 0.], [10., 1., 0.], [10., 0., 1.]]);
    // B: Inner's transform is Outer's times its own (D3DX parse_frame multiplies
    // parent * new), so a point is translated first and then rotated 90 degrees about
    // Z: (x, y) -> (-y, x). (1,0,0) -> (11,0,0) -> (0,11,0). The other order would give
    // (10,1,0); that is the question for accgold.
    assert_eq!(tri(&a, 1), [[0., 11., 0.], [-1., 10., 0.], [0., 10., 1.]]);
    // C: Outer's matrix, then the second matrix of the same frame: (10,5,0).
    assert_eq!(tri(&a, 2), [[11., 5., 0.], [10., 6., 0.], [10., 5., 1.]]);
    // Top-level mesh: identity.
    assert_eq!(tri(&a, 3), [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]);
    // One default material for a file without any (D3DX); C++ 513-519 on it.
    assert_eq!(a.materials.len(), 1);
    assert_eq!(a.face_material, vec![0; 4]);
    // No normals in the file, so C++ 547-553 computes them. A triangle on the unit
    // axes has normal (1,1,1)/sqrt(3); B is that turned by the same rotation: (-1,1,1)/sqrt(3).
    assert!(a.normals_computed);
    let s = 1.0 / 3f32.sqrt();
    for (face, want) in [(0, [s, s, s]), (1, [-s, s, s]), (3, [s, s, s])] {
        for k in 0..3 {
            let n = a.vertices[a.indices[face * 3 + k] as usize].normal;
            close(n, want, 1e-5);
        }
    }
}

fn assert_normals(a: &Accessory, want: [f32; 3]) {
    for v in &a.vertices {
        close(v.normal, want, 1e-5);
    }
}

#[test]
fn mesh_without_normals_or_uvs_gets_computed_normals_and_default_material() {
    let a = load("no_normals_uvs.x");
    assert_eq!(a.vertices.len(), 4);
    // The quad (0,1,2,3) fans to (0,1,2) and (0,2,3).
    assert_eq!(a.indices, vec![0, 1, 2, 0, 2, 3]);
    assert!(a.vertices.iter().all(|v| v.texcoord == [0.0, 0.0]));
    assert!(a.normals_computed);
    // (v0-v1) x (v0-v2) of a counter-clockwise quad in the XY plane is +Z.
    assert_normals(&a, [0.0, 0.0, 1.0]);
    // D3DX default material: diffuse and specular 0.5, alpha 0; then C++ 513-519.
    assert_eq!(a.materials.len(), 1);
    let m = &a.materials[0];
    assert_eq!(m.ambient, [0.5, 0.5, 0.5, 0.0]);
    assert_eq!(m.diffuse, [0.05, 0.05, 0.05, 0.0]);
    assert_eq!(m.specular, [0.05, 0.05, 0.05, 0.0]);
    assert_eq!(m.emissive, [0.0; 4]);
    assert_eq!(m.texture.kind, TextureKind::Plain);
    assert_eq!(a.state.opacity, 1.0);
}

#[test]
fn normals_in_the_file_are_replaced_when_texture_coordinates_are_missing() {
    // The file says +Y. FVF is XYZ|NORMAL, not 274, so C++ 547-553 clones the mesh
    // and D3DXComputeNormals overwrites the normals.
    let a = load("normals_no_uv.x");
    assert!(a.normals_computed);
    assert_normals(&a, [0.0, 0.0, 1.0]);
}

#[test]
fn normals_in_the_file_stay_when_texture_coordinates_exist() {
    let a = load("normals_uv.x");
    assert!(!a.normals_computed);
    assert_eq!(a.vertices.len(), 4, "one normal for every corner: no split");
    assert_normals(&a, [0.0, 1.0, 0.0]);
    assert_eq!(a.vertices[2].texcoord, [1.0, 1.0]);
}

#[test]
fn texture_names_choose_the_sphere_map_type() {
    let a = load("sphere_map.x");
    let got: Vec<_> = a
        .materials
        .iter()
        .map(|m| {
            (
                m.texture.kind,
                m.texture.primary.text.as_str(),
                m.texture.sphere.text.as_str(),
            )
        })
        .collect();
    use TextureKind::*;
    assert_eq!(
        got,
        vec![
            // C++ 524-531: '*' splits; the part after it decides 4 (.sph), 5 (.spa) or 0.
            (SubMultiply, "tex.bmp", "sphere.sph"),
            // C++ 533-538 without '*': .spa -> 2, .sph -> 1, screen.bmp -> 3 (no file), else 0.
            (SphereAdd, "light.spa", ""),
            (Plain, "plain.png", "notmap.bmp"),
            (Screen, "", ""),
            // strstr is case-sensitive.
            (Plain, "x.SPH", ""),
            (SubAdd, "mix.bmp", "env.spa"),
            // C++ 521: no texture name, type stays 0.
            (Plain, "", ""),
            // The sphere part is empty: type 0. The main part is not tested.
            (Plain, "a.sph", ""),
            // Shift-JIS names are kept as bytes and decoded for display.
            (
                SubMultiply,
                "\u{30c6}\u{30af}\u{30b9}\u{30c1}\u{30e3}.bmp",
                "\u{30b9}\u{30d5}\u{30a3}\u{30a2}.sph"
            ),
        ]
    );
    assert_eq!(a.materials[8].texture.primary.raw[..2], [0x83, 0x65]);
    assert_eq!(a.materials.len(), 9);
    assert_eq!(a.face_material, (0..9).collect::<Vec<u32>>());
    assert_eq!(TextureKind::SubAdd as u8, 5, "the C++ textureTypes values");
}

#[test]
fn malformed_files_return_their_error() {
    let cases: &[(&str, Error)] = &[
        ("bad_header.x", Error::BadHeader),
        ("not_x.x", Error::BadHeader),
        (
            "compressed_tzip.x",
            Error::Unsupported("compressed .x (tzip, bzip)"),
        ),
        (
            "compressed_bzip.x",
            Error::Unsupported("compressed .x (tzip, bzip)"),
        ),
        (
            "truncated_mesh.x",
            Error::Invalid("object data is truncated"),
        ),
        ("unterminated.x", Error::Syntax("missing '}'")),
        (
            "face_index_range.x",
            Error::Invalid("face index out of range"),
        ),
        (
            "face_two_vertices.x",
            Error::Invalid("face with fewer than 3 vertices"),
        ),
        (
            "material_index_range.x",
            Error::Invalid("material index out of range"),
        ),
        (
            "material_count.x",
            Error::Invalid("fewer materials than declared"),
        ),
        (
            "normals_count.x",
            Error::Invalid("face normal has a different vertex count"),
        ),
        (
            "texcoord_count.x",
            Error::Invalid("texture coordinate count differs from vertex count"),
        ),
        ("no_mesh.x", Error::NoMesh),
        ("empty_mesh.x", Error::NoMesh),
        ("no_faces.x", Error::Invalid("mesh has no faces")),
        (
            "frame_matrix_short.x",
            Error::Invalid("FrameTransformMatrix needs 16 floats"),
        ),
        (
            "stray_brace.x",
            Error::Syntax("expected an object at top level"),
        ),
    ];
    for (name, want) in cases {
        assert_eq!(load_x(&fixture(name)).unwrap_err(), *want, "{name}");
    }
}

#[test]
fn every_truncation_of_a_valid_file_is_handled() {
    for name in ["cube.x", "cube_bin.x", "multi_material.x", "frames.x"] {
        let data = fixture(name);
        for n in 0..data.len() {
            let _ = load_x(&data[..n]);
        }
    }
}

#[test]
fn more_than_16_bit_vertices_are_refused() {
    let mut s = String::from("xof 0303txt 0032\nMesh M {\n 65536;\n");
    for _ in 0..65536 {
        s.push_str("0;0;0;,\n");
    }
    s.push_str(";\n 1;\n 3;0,1,2;;\n}\n");
    assert_eq!(load_x(s.as_bytes()).unwrap_err(), Error::TooLarge);
}

#[test]
fn deep_nesting_does_not_overflow_the_stack() {
    let mut s = String::from("xof 0303txt 0032\n");
    s.push_str(&"Frame F {\n".repeat(1000));
    assert!(matches!(load_x(s.as_bytes()), Err(Error::Syntax(_))));
}

#[test]
fn xmesh_reports_what_the_loaded_format_had() {
    let x: XMesh = mds_accessory::mesh::load(&fixture("normals_no_uv.x")).unwrap();
    assert!((x.has_normals, x.has_texcoords, x.has_colors) == (true, false, false));
    let x = mds_accessory::mesh::load(&fixture("cube.x")).unwrap();
    assert!((x.has_normals, x.has_texcoords, x.has_colors) == (true, true, false));
}
