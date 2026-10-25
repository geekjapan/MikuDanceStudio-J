//! Every fixture of `tests/fixtures/rust/accessory/` against its Windows dump in
//! `tests/fixtures/rust/accessory/dump/`: the native `d3dx9` load (`raw`, compared
//! with [`mesh::load`]) and the C++ `LoadAccessoryObject` (`record`, compared with
//! [`vac::load_file`]). The format is in `src/tools/mesh_dump.cpp`. Every float is
//! compared bit for bit.

use mds_accessory::mesh::{self, AttributeRange, Vertex, XMesh};
use mds_accessory::{vac, Accessory};
use std::path::{Path, PathBuf};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/accessory")
}

/// One dump line: unquoted words as their bytes, quoted strings unescaped.
fn tokens(line: &str) -> Vec<Vec<u8>> {
    let b = line.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b' ' {
            i += 1;
        } else if b[i] == b'"' {
            let mut s = Vec::new();
            i += 1;
            while b[i] != b'"' {
                if b[i] == b'\\' {
                    let hex = std::str::from_utf8(&b[i + 2..i + 4]).unwrap();
                    s.push(u8::from_str_radix(hex, 16).unwrap());
                    i += 4;
                } else {
                    s.push(b[i]);
                    i += 1;
                }
            }
            out.push(s);
            i += 1;
        } else {
            let start = i;
            while i < b.len() && b[i] != b' ' {
                i += 1;
            }
            out.push(b[start..i].to_vec());
        }
    }
    out
}

struct Line(Vec<Vec<u8>>);

impl Line {
    fn word(&self, i: usize) -> &str {
        std::str::from_utf8(&self.0[i]).unwrap()
    }
    fn u32(&self, i: usize) -> u32 {
        self.word(i).parse().unwrap()
    }
    /// `%.9g` reads back to the float it printed.
    fn f32(&self, i: usize) -> f32 {
        self.word(i).parse().unwrap()
    }
    fn floats(&self, from: usize, n: usize) -> Vec<f32> {
        (from..from + n).map(|i| self.f32(i)).collect()
    }
}

/// The lines of one section, from its first line (`raw ...`, `record ...`) to the
/// next section.
fn section<'a>(lines: &'a [Line], name: &str) -> &'a [Line] {
    let start = lines
        .iter()
        .position(|l| l.word(0) == name)
        .unwrap_or_else(|| panic!("no {name} section"));
    let len = lines[start + 1..]
        .iter()
        .position(|l| matches!(l.word(0), "raw" | "frame" | "frames" | "record"))
        .map_or(lines.len() - start, |n| n + 1);
    &lines[start..start + len]
}

fn bits(v: &[f32]) -> Vec<u32> {
    v.iter().map(|x| x.to_bits()).collect()
}

const USAGE_POSITION: u32 = 0;
const USAGE_NORMAL: u32 = 3;
const USAGE_TEXCOORD: u32 = 5;
const USAGE_COLOR: u32 = 10;

/// Checks the decl, v, f and table lines of `lines` against a mesh. Returns the
/// usages of the declaration.
fn check_mesh(
    what: &str,
    lines: &[Line],
    vertices: &[Vertex],
    indices: &[u32],
    face_material: &[u32],
    attribute_table: &[AttributeRange],
) -> Vec<u32> {
    let head = &lines[0];
    assert_eq!(head.u32(6) as usize, vertices.len(), "{what}: vertex count");
    assert_eq!(
        head.u32(8) as usize * 3,
        indices.len(),
        "{what}: face count"
    );
    let decl: Vec<(u32, u32)> = lines
        .iter()
        .filter(|l| l.word(0) == "decl")
        .map(|l| (l.u32(2), l.u32(3)))
        .collect();
    for (i, l) in lines.iter().filter(|l| l.word(0) == "v").enumerate() {
        assert_eq!(l.u32(1) as usize, i);
        let v = &vertices[i];
        let mut at = 2;
        for &(ty, usage) in &decl {
            let (got, want): (Vec<f32>, &[f32]) = match usage {
                USAGE_POSITION => (l.floats(at, 3), &v.position),
                USAGE_NORMAL => (l.floats(at, 3), &v.normal),
                USAGE_TEXCOORD => (l.floats(at, 2), &v.texcoord),
                USAGE_COLOR => {
                    at += 1;
                    continue;
                }
                u => panic!("{what}: vertex element usage {u}"),
            };
            assert_eq!(
                ty as usize + 1,
                got.len(),
                "{what}: element type of usage {usage}"
            );
            assert_eq!(
                bits(&got),
                bits(want),
                "{what}: vertex {i} usage {usage}: dump {got:?}, crate {want:?}"
            );
            at += got.len();
        }
        assert_eq!(at, l.0.len(), "{what}: vertex {i} has more values");
    }
    let faces: Vec<&Line> = lines.iter().filter(|l| l.word(0) == "f").collect();
    assert_eq!(faces.len() * 3, indices.len(), "{what}: f lines");
    for (i, l) in faces.iter().enumerate() {
        let got = [l.u32(2), l.u32(3), l.u32(4)];
        assert_eq!(got, indices[i * 3..i * 3 + 3], "{what}: face {i} indices");
        assert_eq!(l.u32(5), face_material[i], "{what}: face {i} attribute");
    }
    let table: Vec<[u32; 5]> = lines
        .iter()
        .filter(|l| l.word(0) == "t")
        .map(|t| std::array::from_fn(|k| t.u32(k + 1)))
        .collect();
    let want: Vec<[u32; 5]> = attribute_table
        .iter()
        .map(|r| {
            [
                r.id,
                r.face_start,
                r.face_count,
                r.vertex_start,
                r.vertex_count,
            ]
        })
        .collect();
    assert_eq!(table, want, "{what}: attribute table");
    decl.iter().map(|d| d.1).collect()
}

fn check_raw(name: &str, lines: &[Line], got: Result<XMesh, mds_accessory::Error>) {
    let raw = section(lines, "raw");
    if raw[0].word(1) == "hr" {
        assert!(
            got.is_err(),
            "{name}: D3DX fails with {}, the crate loads it",
            raw[0].word(2)
        );
        return;
    }
    let x = got.unwrap_or_else(|e| panic!("{name}: D3DX loads it, the crate fails: {e}"));
    let what = format!("{name} raw");
    let usages = check_mesh(
        &what,
        raw,
        &x.vertices,
        &x.indices,
        &x.face_material,
        &x.attribute_table,
    );
    assert_eq!(
        usages.contains(&USAGE_NORMAL),
        x.has_normals,
        "{what}: normals"
    );
    assert_eq!(
        usages.contains(&USAGE_TEXCOORD),
        x.has_texcoords,
        "{what}: UVs"
    );
    assert_eq!(
        usages.contains(&USAGE_COLOR),
        x.has_colors,
        "{what}: colors"
    );
    let count = raw.iter().find(|l| l.word(0) == "materials").unwrap();
    assert_eq!(
        count.u32(1) as usize,
        x.materials.len(),
        "{what}: materials"
    );
    for (i, l) in raw.iter().filter(|l| l.word(0) == "m").enumerate() {
        let m = &x.materials[i];
        let want = [
            &m.diffuse[..],
            &m.ambient,
            &m.specular,
            &m.emissive,
            &[m.power],
        ]
        .concat();
        let got = l.floats(2, 17);
        assert_eq!(
            bits(&got),
            bits(&want),
            "{what}: material {i}: dump {got:?}, crate {want:?}"
        );
        let texture = (l.0[19] != b"-").then(|| l.0[19].clone());
        assert_eq!(texture, m.texture, "{what}: material {i} texture");
    }
}

fn check_record(name: &str, lines: &[Line], got: Result<Accessory, mds_accessory::Error>) {
    let rec = section(lines, "record");
    if rec[0].word(1) == "failed" {
        assert!(got.is_err(), "{name}: the C++ fails, the crate loads it");
        return;
    }
    let a = got.unwrap_or_else(|e| panic!("{name}: the C++ loads it, the crate fails: {e}"));
    let what = format!("{name} record");
    assert_eq!(
        rec[0].u32(2),
        mds_accessory::accessory::FVF_274,
        "{what}: FVF"
    );
    check_mesh(
        &what,
        rec,
        &a.vertices,
        &a.indices,
        &a.face_material,
        &a.attribute_table,
    );
    let materials: Vec<&Line> = rec.iter().filter(|l| l.word(0) == "rm").collect();
    assert_eq!(materials.len(), a.materials.len(), "{what}: materials");
    for (i, l) in materials.iter().enumerate() {
        let m = &a.materials[i];
        let want = [
            &m.diffuse[..],
            &m.ambient,
            &m.specular,
            &m.emissive,
            &[m.power],
        ]
        .concat();
        let got = l.floats(2, 17);
        assert_eq!(
            bits(&got),
            bits(&want),
            "{what}: material {i}: dump {got:?}, crate {want:?}"
        );
        assert_eq!(
            l.u32(19),
            m.texture.kind as u32,
            "{what}: material {i} texture type"
        );
        let text = |t: usize| String::from_utf8(l.0[t].clone()).unwrap();
        assert_eq!(
            text(20),
            m.texture.primary.text,
            "{what}: material {i} texture"
        );
        assert_eq!(
            text(21),
            m.texture.sphere.text,
            "{what}: material {i} sphere map"
        );
    }
    let place = rec.iter().find(|l| l.word(0) == "place").unwrap();
    let s = &a.state;
    assert_eq!(place.u32(1) != 0, s.visible, "{what}: visible");
    let want = [&[s.scale][..], &s.position, &s.rotation].concat();
    assert_eq!(bits(&place.floats(2, 7)), bits(&want), "{what}: placement");
    assert_eq!(place.u32(9) != 0, s.shadow_enabled, "{what}: shadow");
    assert_eq!(
        place.word(10),
        s.parent_model.to_string(),
        "{what}: parent model"
    );
    assert_eq!(
        place.word(11),
        s.parent_bone.to_string(),
        "{what}: parent bone"
    );
    assert_eq!(
        place.f32(12).to_bits(),
        s.opacity.to_bits(),
        "{what}: opacity"
    );
    assert_eq!(place.u32(13) != 0, s.additive_blend, "{what}: additive");
}

fn dump(name: &str) -> Vec<Line> {
    let path = fixtures().join("dump").join(format!("{name}.txt"));
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "{}: {e} (tools/oracle/accgold.ps1 writes it)",
            path.display()
        )
    });
    let lines: Vec<Line> = text.lines().map(|l| Line(tokens(l))).collect();
    assert_eq!(lines[0].word(0), "mds-mesh-dump", "{name}");
    assert_eq!(lines[1].0[1], name.as_bytes(), "{name}: file line");
    lines
}

#[test]
fn every_fixture_equals_its_windows_dump() {
    let mut names: Vec<String> = std::fs::read_dir(fixtures())
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .filter(|n| n.ends_with(".x") || n.ends_with(".vac"))
        .collect();
    names.sort();
    assert_eq!(names.len(), 30, "{names:?}");
    // Every file is checked, so one run names every mismatch.
    let failed: Vec<String> = names
        .iter()
        .filter_map(|name| {
            std::panic::catch_unwind(|| {
                let path: &Path = &fixtures().join(name);
                let lines = dump(name);
                if !name.ends_with(".vac") {
                    check_raw(name, &lines, mesh::load(&std::fs::read(path).unwrap()));
                }
                check_record(name, &lines, vac::load_file(path));
            })
            .err()
            .map(|e| {
                e.downcast_ref::<String>()
                    .cloned()
                    .unwrap_or_else(|| name.clone())
            })
        })
        .collect();
    assert!(
        failed.is_empty(),
        "{} of {} differ:\n{}",
        failed.len(),
        names.len(),
        failed.join("\n")
    );
}
