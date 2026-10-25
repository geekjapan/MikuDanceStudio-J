//! Image-hash regression for the fixture models.
//!
//! Each model is rendered and its pixels are hashed (FNV-1a, 64 bit). The expected hash is
//! looked up in `tests/hashes.tsv` by model and adapter (`name|backend`), because two GPUs
//! rasterize the same scene to different bytes. With no adapter, or an adapter that has no
//! recorded hash, a model reports SKIP, which is not a pass: run with `--nocapture` to see it.
//!
//! * `MDS_RENDER_RECORD=1` records (replaces) the hashes of this adapter in `hashes.tsv`.
//! * `MDS_RENDER_PNG_DIR=<dir>` also writes `<model>.png` there for a human to look at.

use mds_formats::pmx::Pmx;
use mds_render::{encode_png, render, Gpu, CLEAR, HEIGHT, WIDTH};
use std::collections::BTreeMap;
use std::path::PathBuf;

const FIXTURES: [&str; 3] = ["chain8.pmx", "chain8_ik.pmx", "morph4.pmx"];

/// The fixtures are flat quads, which have no edge hull and no curvature. This unit cube with
/// smooth (corner-pointing) normals and chain8's material, edge size 2, shows the edge, the toon
/// ramp and the highlight. The camera sits on the -Z side because the mean normal is zero.
fn cube() -> Pmx {
    let mut pmx = load("chain8.pmx");
    let base = pmx.vertices[0].clone();
    pmx.vertices.clear();
    pmx.indices.clear();
    let corners: Vec<[f32; 3]> = (0..8)
        .map(|i| [0, 1, 2].map(|b| if i >> b & 1 == 1 { 0.5 } else { -0.5 }))
        .collect();
    for c in &corners {
        let l = (c[0] * c[0] + c[1] * c[1] + c[2] * c[2]).sqrt();
        let mut v = base.clone();
        v.position = *c;
        v.normal = c.map(|x| x / l);
        pmx.vertices.push(v);
    }
    for axis in 0..3 {
        for side in [0, 1] {
            // The face's four corners in a fixed order, then two triangles wound clockwise
            // seen from outside, which is cross(b - a, c - a) pointing outward.
            let ids: Vec<usize> = (0..8).filter(|i| i >> axis & 1 == side).collect();
            let (a, b, c, d) = (ids[0], ids[1], ids[3], ids[2]);
            for tri in [[a, b, c], [a, c, d]] {
                let p = |i: usize| corners[tri[i]];
                let (u, w) = (
                    [0, 1, 2].map(|k| p(1)[k] - p(0)[k]),
                    [0, 1, 2].map(|k| p(2)[k] - p(0)[k]),
                );
                let n = [
                    u[1] * w[2] - u[2] * w[1],
                    u[2] * w[0] - u[0] * w[2],
                    u[0] * w[1] - u[1] * w[0],
                ];
                let outward = if side == 1 { 1.0 } else { -1.0 };
                let order = if n[axis] * outward > 0.0 {
                    [0, 1, 2]
                } else {
                    [0, 2, 1]
                };
                pmx.indices.extend(order.map(|i| tri[i] as i32));
            }
        }
    }
    pmx.materials[0].face_vertex_count = pmx.indices.len() as i32;
    pmx.materials[0].edge_size = 2.0;
    pmx
}

fn models() -> Vec<(String, Pmx)> {
    let mut m: Vec<_> = FIXTURES.iter().map(|n| (n.to_string(), load(n))).collect();
    m.push(("cube-synthetic".into(), cube()));
    m
}

fn fnv1a(data: &[u8]) -> u64 {
    data.iter().fold(0xcbf2_9ce4_8422_2325, |h, &b| {
        (h ^ u64::from(b)).wrapping_mul(0x0000_0100_0000_01b3)
    })
}

fn table_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/hashes.tsv")
}

/// `(model, adapter) -> hash`
fn read_table() -> BTreeMap<(String, String), String> {
    let text = std::fs::read_to_string(table_path()).unwrap_or_default();
    text.lines()
        .filter(|l| !l.starts_with('#') && !l.is_empty())
        .map(|l| {
            let f: Vec<&str> = l.split('\t').collect();
            assert_eq!(f.len(), 3, "bad line in hashes.tsv: {l}");
            ((f[0].to_string(), f[1].to_string()), f[2].to_string())
        })
        .collect()
}

fn write_table(t: &BTreeMap<(String, String), String>) {
    let mut out =
        String::from("# model<TAB>adapter (name|backend)<TAB>FNV-1a 64 of the RGBA8 pixels\n");
    for ((model, adapter), hash) in t {
        out += &format!("{model}\t{adapter}\t{hash}\n");
    }
    std::fs::write(table_path(), out).unwrap();
}

fn load(name: &str) -> Pmx {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/rust")
        .join(name);
    Pmx::read(&std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display())))
        .unwrap_or_else(|e| panic!("{name}: {e}"))
}

#[test]
fn fixture_models_match_the_recorded_hashes() {
    let gpu = match Gpu::new().expect("device") {
        Some(g) => g,
        None => {
            eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
            return;
        }
    };
    let record = std::env::var_os("MDS_RENDER_RECORD").is_some();
    let png_dir = std::env::var_os("MDS_RENDER_PNG_DIR").map(PathBuf::from);
    let mut table = read_table();
    let mut skipped = Vec::new();

    for (name, pmx) in models() {
        let name = name.as_str();
        let pixels = render(&gpu, &pmx).unwrap_or_else(|e| panic!("{name}: {e}"));
        assert_eq!(pixels.len(), (WIDTH * HEIGHT * 4) as usize);
        // The model is visible: some pixels differ from the clear color, and the clear
        // color is still there (the model does not fill the frame).
        let changed = pixels.chunks(4).filter(|p| *p != CLEAR).count();
        assert!(
            changed > 100 && changed < pixels.len() / 4,
            "{name}: {changed} of {} pixels differ from the clear color",
            pixels.len() / 4
        );
        // Rendering twice gives the same bytes.
        assert_eq!(
            pixels,
            render(&gpu, &pmx).unwrap(),
            "{name} is not deterministic"
        );

        if let Some(dir) = &png_dir {
            std::fs::create_dir_all(dir).unwrap();
            let file = dir.join(format!("{}.png", name.trim_end_matches(".pmx")));
            std::fs::write(&file, encode_png(WIDTH, HEIGHT, &pixels)).unwrap();
            eprintln!("wrote {}", file.display());
        }

        let hash = format!("{:016x}", fnv1a(&pixels));
        let key = (name.to_string(), gpu.adapter.clone());
        if record {
            table.insert(key, hash);
        } else {
            match table.get(&key) {
                Some(want) => assert_eq!(&hash, want, "{name} on {}", gpu.adapter),
                None => {
                    eprintln!(
                        "SKIP: {name} has no recorded hash for {} (hash {hash}; not a pass)",
                        gpu.adapter
                    );
                    skipped.push(name.to_string());
                }
            }
        }
    }
    if record {
        write_table(&table);
    }
    if skipped.is_empty() && !record {
        eprintln!("PASS: all models matched on {}", gpu.adapter);
    }
}
