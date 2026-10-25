//! Frame-hash regression of a few effects, until `mmegold` adds golden images.
//!
//! Each effect runs one frame (every technique, `chain8.pmx` as the geometry) and the back
//! buffer is hashed (FNV-1a 64 of the RGBA8 pixels). Hashes are looked up in
//! `tests/hashes.tsv` by effect and adapter (`name|backend`); an adapter without a recorded
//! hash, a missing corpus, or no adapter reports SKIP, which is not a pass.
//!
//! `MDS_MMERT_RECORD=1` records the hashes of this adapter; `MDS_MMERT_PNG_DIR=<dir>` also
//! writes each frame as a PNG.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};

use mds_mmert::{DrawInput, Effect, Gpu, Model, Scene, Target, BACKBUFFER};

/// `(label, root, effect below the root)`; `corpus` roots need the ray-mmd corpus.
const EFFECTS: [(&str, &str); 5] = [
    ("fixtures", "objects.fx"),
    ("fixtures", "post.fx"),
    ("fixtures", "offscreen.fx"),
    ("corpus", "Skybox/Time of day/Time of day.fx"),
    ("corpus", "Main/main.fx"),
];

fn report(text: &str) {
    let _ = writeln!(std::io::stderr(), "{text}");
}

fn root(kind: &str) -> PathBuf {
    match kind {
        "fixtures" => {
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/mme/effects")
        }
        _ => match std::env::var_os("MDS_CORPUS") {
            Some(p) => PathBuf::from(p),
            None => std::env::temp_dir().join("mds-corpus"),
        }
        .join("ray-mmd"),
    }
}

fn fnv1a(data: &[u8]) -> u64 {
    data.iter().fold(0xcbf2_9ce4_8422_2325, |h, &b| {
        (h ^ u64::from(b)).wrapping_mul(0x0000_0100_0000_01b3)
    })
}

fn table_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/hashes.tsv")
}

fn read_table() -> BTreeMap<(String, String), String> {
    std::fs::read_to_string(table_path())
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.starts_with('#') && !l.is_empty())
        .map(|l| {
            let f: Vec<&str> = l.split('\t').collect();
            assert_eq!(f.len(), 3, "bad line in hashes.tsv: {l}");
            ((f[0].to_string(), f[1].to_string()), f[2].to_string())
        })
        .collect()
}

#[test]
fn frames_match_the_recorded_hashes() {
    let Some(gpu) = Gpu::new().unwrap() else {
        report("SKIP: no wgpu adapter (a skip is not a pass)");
        return;
    };
    let lib = match std::env::var_os("MDS_VKD3D_LIB") {
        Some(p) => PathBuf::from(p),
        None if cfg!(target_os = "macos") => {
            std::env::temp_dir().join("mds-vkd3d/macos/lib/libvkd3d-shader.1.dylib")
        }
        None => {
            let arch = if cfg!(target_arch = "x86_64") {
                "amd64"
            } else {
                "arm64"
            };
            std::env::temp_dir().join(format!("mds-vkd3d/linux-{arch}/lib/libvkd3d-shader.so.1"))
        }
    };
    let vk = mds_shader::vkd3d::Vkd3d::open(&lib)
        .unwrap_or_else(|e| panic!("vkd3d-shader not loaded: {e}"));
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    let pmx =
        mds_formats::pmx::Pmx::read(&std::fs::read(fixtures.join("chain8.pmx")).unwrap()).unwrap();
    let model = Model::from_pmx(&gpu.device, &pmx).unwrap();
    let record = std::env::var_os("MDS_MMERT_RECORD").is_some();
    let png_dir = std::env::var_os("MDS_MMERT_PNG_DIR").map(PathBuf::from);
    let mut table = read_table();
    let mut mismatches = Vec::new();
    for (kind, rel) in EFFECTS {
        let dir = root(kind);
        if !dir.is_dir() {
            report(&format!(
                "SKIP {rel}: no corpus at {} (a skip is not a pass)",
                dir.display()
            ));
            continue;
        }
        let ((pixels, report_), errors) = gpu.scoped(|| {
            let mut e = Effect::load(&gpu, &vk, &dir.join(rel), &dir)
                .unwrap_or_else(|e| panic!("{rel}: {e}"));
            let target = Target::new(&gpu, BACKBUFFER);
            let mut scene = Scene::default_view(BACKBUFFER.0, BACKBUFFER.1);
            // chain8 faces +Z.
            scene.view =
                mds_mmert::bind::look_at_lh([0.0, 4.0, 20.0], [0.0, 4.0, 0.0], [0.0, 1.0, 0.0]);
            let input = DrawInput {
                scene: &scene,
                geometry: Some((&model, 0)),
                draw_type: mds_mmert::bind::DRAW_OBJECT,
            };
            let r = e.frame(&gpu, &target, &input);
            (target.read(&gpu).unwrap(), r)
        });
        assert!(errors.is_empty(), "{rel}: wgpu errors {errors:?}");
        let hash = format!("{:016x}", fnv1a(&pixels));
        if let Some(d) = &png_dir {
            std::fs::create_dir_all(d).unwrap();
            let name = rel.replace(['/', ' '], "_");
            let mut out = Vec::new();
            let mut enc = png::Encoder::new(&mut out, BACKBUFFER.0, BACKBUFFER.1);
            enc.set_color(png::ColorType::Rgba);
            enc.write_header()
                .unwrap()
                .write_image_data(&pixels)
                .unwrap();
            std::fs::write(d.join(format!("{name}.png")), out).unwrap();
        }
        let key = (rel.to_string(), gpu.adapter.clone());
        report(&format!(
            "{rel}: {hash} ({} of {} draws reached the GPU)",
            report_.drawn, report_.draws
        ));
        if record {
            table.insert(key, hash);
            continue;
        }
        match table.get(&key) {
            None => report(&format!(
                "SKIP {rel}: no hash recorded for {} (a skip is not a pass)",
                gpu.adapter
            )),
            Some(want) if *want != hash => {
                mismatches.push(format!("{rel}: expected {want}, got {hash}"))
            }
            Some(_) => {}
        }
    }
    if record {
        let mut out = String::from(
            "# effect<TAB>adapter (name|backend)<TAB>FNV-1a 64 of the RGBA8 back buffer\n",
        );
        for ((e, a), h) in &table {
            out.push_str(&format!("{e}\t{a}\t{h}\n"));
        }
        std::fs::write(table_path(), out).unwrap();
    }
    assert!(mismatches.is_empty(), "{mismatches:?}");
}
