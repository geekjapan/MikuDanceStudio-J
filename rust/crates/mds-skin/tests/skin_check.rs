//! Gate: `tests/fixtures/rust/skin/skin.dump`, the output of the C++ harness
//! `tools/skin_check` on `cases.txt` (format in `tools/skin_check/skin_check.cpp`),
//! bit for bit. The bone morph records ("b" lines) come from
//! `mds_pose::pose::apply_morphs`, the rest from mds-skin.

use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_skin::{Mat4, Skin, View};
use std::fmt::Write;
use std::path::PathBuf;

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn float(word: &str) -> f32 {
    f32::from_bits(u32::from_str_radix(word, 16).unwrap())
}

fn floats<const N: usize>(words: &mut std::str::SplitWhitespace) -> [f32; N] {
    std::array::from_fn(|_| float(words.next().unwrap()))
}

struct Model {
    skin: Skin,
    pose: Option<mds_pose::model::Model>,
}

fn load(file: &str) -> (Model, Option<Pmx>) {
    let data = std::fs::read(fixtures().join(file)).unwrap();
    if file.ends_with(".pmd") {
        let pmd = Pmd::read(&data).unwrap();
        let skin = Skin::from_pmd(&pmd).unwrap();
        return (Model { skin, pose: None }, None);
    }
    let pmx = Pmx::read(&data).unwrap();
    let pose = mds_pose::model::Model::from_pmx(0, &pmx).unwrap();
    let skin = Skin::from_pmx(&pmx).unwrap();
    (
        Model {
            skin,
            pose: Some(pose),
        },
        Some(pmx),
    )
}

fn hex(out: &mut String, values: impl IntoIterator<Item = f32>) {
    for v in values {
        write!(out, " {:08x}", v.to_bits()).unwrap();
    }
}

fn print(out: &mut String, model: &Model) {
    let skin = &model.skin;
    let stride = skin.stride();
    for (i, edge) in skin.edge.iter().enumerate() {
        write!(out, "v {i}").unwrap();
        hex(out, skin.main[stride * i..stride * (i + 1)].iter().copied());
        hex(out, edge.position);
        writeln!(out, " {:08x}", edge.diffuse).unwrap();
    }
    for (i, m) in skin.materials.iter().enumerate() {
        write!(out, "m {i}").unwrap();
        let [r, g, b, _] = m.diffuse_mirror;
        hex(out, [r, g, b, m.diffuse[3]]);
        hex(out, m.specular);
        hex(out, m.ambient);
        hex(out, [m.specular_power]);
        hex(out, m.edge_color);
        hex(out, [m.edge_size]);
        out.push('\n');
    }
    for (i, r) in model
        .pose
        .iter()
        .flat_map(|p| &p.bone_morph_offsets)
        .enumerate()
    {
        write!(out, "b {i} {}", r.bone_index).unwrap();
        hex(out, r.translation);
        hex(out, r.rotation);
        out.push('\n');
    }
}

fn run(cases: &str) -> String {
    let mut out = String::new();
    let mut model: Option<(Model, Option<Pmx>)> = None;
    let mut weights = Vec::new();
    let mut bones = Vec::new();
    let mut view = View {
        world: Mat4::IDENTITY,
        camera_position: [0.0; 3],
        camera_fov: 0.0,
        edge_scale: 1.0,
        self_shadow: false,
    };
    for line in cases.lines() {
        let mut words = line.split_whitespace();
        let Some(op) = words.next() else { continue };
        if op.starts_with('#') {
            continue;
        }
        if op == "model" {
            let file = words.next().unwrap();
            let (m, pmx) = load(file);
            let kind = if m.skin.is_pmx() { "pmx" } else { "pmd" };
            let (n, stride) = (m.skin.vertex_count(), 4 * m.skin.stride());
            writeln!(out, "model {file} {kind} vertices {n} stride {stride}").unwrap();
            model = Some((m, pmx));
            view.edge_scale = 1.0;
            continue;
        }
        let (m, pmx) = model.as_mut().unwrap();
        match op {
            "qdef" => {
                let pmx = pmx.as_mut().unwrap();
                for v in words {
                    pmx.vertices[v.parse::<usize>().unwrap()].weight_kind = 4;
                }
                m.skin = Skin::from_pmx(pmx).unwrap();
            }
            "case" => {
                writeln!(out, "case {}", words.next().unwrap()).unwrap();
                weights = vec![0.0; m.skin.morph_count()];
                bones = vec![Mat4::IDENTITY; m.skin.bone_count()];
                view.world = Mat4::IDENTITY;
            }
            "world" => view.world = Mat4(floats(&mut words)),
            "camera" => {
                view.camera_position = floats(&mut words);
                view.camera_fov = float(words.next().unwrap());
            }
            "edge" => view.edge_scale = float(words.next().unwrap()),
            "shadow" => view.self_shadow = words.next().unwrap() != "0",
            "morph" => {
                let i: usize = words.next().unwrap().parse().unwrap();
                weights[i] = float(words.next().unwrap());
            }
            "bone" => {
                let i: usize = words.next().unwrap().parse().unwrap();
                bones[i] = Mat4(floats(&mut words));
            }
            "end" => {
                m.skin.apply_morphs(&weights);
                m.skin.update(&weights, &bones, &view);
                if let Some(pose) = &mut m.pose {
                    for (morph, &w) in pose.morphs.iter_mut().zip(&weights) {
                        morph.value = w;
                    }
                    mds_pose::pose::apply_morphs(pose);
                }
                print(&mut out, m);
            }
            _ => panic!("unknown case line {line}"),
        }
    }
    out
}

#[test]
fn skin_matches_the_cpp_harness() {
    let dir = fixtures().join("skin");
    let cases = std::fs::read_to_string(dir.join("cases.txt")).unwrap();
    let expected = std::fs::read_to_string(dir.join("skin.dump")).unwrap();
    let actual = run(&cases);
    let cases_run = expected.lines().filter(|l| l.starts_with("case ")).count();
    assert_eq!(cases_run, 17);
    for (n, (a, e)) in actual.lines().zip(expected.lines()).enumerate() {
        assert_eq!(a, e, "first mismatch at dump line {}", n + 1);
    }
    assert_eq!(actual.lines().count(), expected.lines().count());
    assert!(actual == expected);
}
