//! `mds-app --frame-dump` of every scene of `tests/fixtures/rust/mmegold/` against the C++ MME
//! images, by the per-pixel rule and gate list of `mds-mmert/tests/mmegold.rs` ([`LIMITS`],
//! [`flat`], [`score`], [`overlay`], [`host_drawn`] and [`PIXEL_GATED`] are copied from there,
//! because a test file of another crate cannot be imported).
//!
//! Each scene is staged as the Windows lane `tools/oracle/mmegold.ps1` stages it: the PMM with its
//! EMM beside it, the `$(fixtures)`, `$(mmegold)` and `$(corpus)` effect paths made absolute, and
//! the model and accessory files next to the PMM. The app then autoloads the EMM, as the C++ app
//! does. Needs the vkd3d-shader library (`MDS_VKD3D_LIB`, else the one `tools/vkd3d/build.sh`
//! leaves in the temp directory) and, for the ray-mmd scenes, the corpus of
//! `tools/fixtures/fetch_corpus.sh` (`MDS_CORPUS`); without them it prints SKIP.
//!
//! `MDS_APP_MME_DIR=<dir>` keeps the staged scenes and the dumped PNGs there.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_math::Mat4;
use mds_mmert::bind::{look_at_lh, mul, perspective_lh, Mat};
use mds_physics::PhysicsScene;
use mds_scene::track::{evaluate_camera, CameraMode};

const W: u32 = 640;
const H: u32 = 360;

/// Scenes and their probed frames (`SCENES` of `gen_mmegold.py`).
const SCENES: [(&str, &[u32]); 8] = [
    ("objects", &[0, 30]),
    ("post", &[0, 30]),
    ("offscreen", &[0, 30]),
    ("timeofday", &[0, 30]),
    ("main", &[0, 30]),
    ("control", &[0, 15, 30]),
    ("anime", &[0, 3, 4, 9, 30]),
    ("ray", &[0, 30]),
];

/// Scenes whose every probed frame meets [`LIMITS`] in `mmegold.rs`. `post` joins them once its
/// fixed effect `mmegold/post.fx` is in the fixtures (slice `cppfix`).
const PIXEL_GATED: &[&str] = &[
    "objects",
    "offscreen",
    "timeofday",
    "main",
    "control",
    "anime",
];

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn mmegold() -> PathBuf {
    fixtures().join("mmegold")
}

fn gated(name: &str) -> bool {
    PIXEL_GATED.contains(&name) || (name == "post" && mmegold().join("post.fx").is_file())
}

fn vkd3d_lib() -> PathBuf {
    match std::env::var_os("MDS_VKD3D_LIB") {
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
    }
}

fn corpus() -> Option<PathBuf> {
    let dir = match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd");
    dir.is_dir().then_some(dir)
}

/// The scene `name` in `dir`: the PMM, its EMM with absolute effect paths, the models, and the
/// accessory; the effects of `mmegold/` with `blink.gif` in `dir/mmegold`.
fn stage(name: &str, dir: &Path, corpus: &Path) {
    let effects = dir.join("mmegold");
    std::fs::create_dir_all(&effects).unwrap();
    for e in std::fs::read_dir(mmegold()).unwrap() {
        let p = e.unwrap().path();
        if p.extension().is_some_and(|x| x == "fx") {
            std::fs::copy(&p, effects.join(p.file_name().unwrap())).unwrap();
        }
    }
    let gif = Path::new(env!("CARGO_MANIFEST_DIR")).join("../mds-mmert/tests/data/blink.gif");
    std::fs::copy(gif, effects.join("blink.gif")).unwrap();
    for m in ["chain8.pmx", "morph4.pmx"] {
        std::fs::copy(fixtures().join(m), dir.join(m)).unwrap();
    }
    if corpus.join("ray.x").is_file() {
        std::fs::copy(corpus.join("ray.x"), dir.join("ray.x")).unwrap();
    }
    std::fs::copy(
        mmegold().join(format!("{name}.pmm")),
        dir.join(format!("{name}.pmm")),
    )
    .unwrap();
    let root = |p: &Path| p.to_string_lossy().into_owned() + "/";
    let emm = std::fs::read_to_string(mmegold().join(format!("{name}.emm"))).unwrap();
    let emm: String = emm
        .lines()
        .map(|l| match l.split_once(" = $(") {
            Some((key, rest)) => {
                let (var, path) = rest.split_once(")\\").unwrap();
                let base = match var {
                    "fixtures" => root(&fixtures().join("mme/effects")),
                    "mmegold" => root(&effects),
                    "corpus" => root(corpus),
                    _ => panic!("unknown effect root {var}"),
                };
                format!("{key} = {base}{}\r\n", path.replace('\\', "/"))
            }
            None => format!("{l}\r\n"),
        })
        .collect();
    std::fs::write(dir.join(format!("{name}.emm")), emm).unwrap();
}

// ---- the mask of what the host draws (mmegold.rs) ----

/// The view and projection of `host_scene` in mmegold.rs.
fn view_projection(pmm: &Pmm, frame: u32) -> Mat {
    let c = evaluate_camera(&pmm.camera, f64::from(frame), CameraMode::Playback).unwrap();
    let [pitch, yaw, roll] = c.rotation;
    let t = Mat4::translation(-c.position[0], -c.position[1], -c.position[2]);
    let r = Mat4::multiply(&Mat4::rotation_y(yaw), &Mat4::rotation_x(pitch));
    let r = Mat4::multiply(&r, &Mat4::rotation_z(roll));
    let frame_world = Mat4::multiply(&t, &r);
    let eye = [0.0, 0.0, c.distance];
    let view = look_at_lh(eye, [0.0, 0.0, c.distance + 80.0], [0.0, 1.0, 0.0]);
    let fov = (f64::from(c.fov) * std::f64::consts::PI / 180.0) as f32;
    let view = mul(&frame_world.0, &view);
    mul(
        &view,
        &perspective_lh(fov, W as f32 / H as f32, 1.0, 100000.0),
    )
}

/// `Host::host_drawn`: the screen rectangle, 2 px wider, of each model other than the first that
/// has no effect row. Each vertex moves with its first bone.
fn host_drawn(
    pmm: &Pmm,
    pmxs: &[Pmx],
    assigned: &[bool],
    physics: &PhysicsScene,
    frame: u32,
) -> Vec<bool> {
    let view_proj = view_projection(pmm, frame);
    let mut mask = vec![false; (W * H) as usize];
    for (i, (m, pmx)) in pmm.models.iter().zip(pmxs).enumerate().skip(1) {
        if assigned[i] {
            continue;
        }
        let posed = physics
            .scene
            .models
            .iter()
            .find(|p| p.slot == m.slot)
            .unwrap();
        let (mut lo, mut hi) = ([f32::MAX; 2], [f32::MIN; 2]);
        for v in &pmx.vertices {
            let b = &posed.bones[v.bones[0] as usize].mat_init.0;
            let p: [f32; 3] = std::array::from_fn(|c| {
                v.position[0] * b[c]
                    + v.position[1] * b[4 + c]
                    + v.position[2] * b[8 + c]
                    + b[12 + c]
            });
            let clip: [f32; 4] = std::array::from_fn(|c| {
                p[0] * view_proj[c]
                    + p[1] * view_proj[4 + c]
                    + p[2] * view_proj[8 + c]
                    + view_proj[12 + c]
            });
            let px = [
                (clip[0] / clip[3] + 1.0) * 0.5 * W as f32,
                (1.0 - clip[1] / clip[3]) * 0.5 * H as f32,
            ];
            for c in 0..2 {
                lo[c] = lo[c].min(px[c]);
                hi[c] = hi[c].max(px[c]);
            }
        }
        let range = |c: usize, n: u32| {
            (lo[c] - 2.0).floor().max(0.0) as u32..((hi[c] + 2.0).ceil().max(0.0) as u32).min(n)
        };
        for y in range(1, H) {
            for x in range(0, W) {
                mask[(y * W + x) as usize] = true;
            }
        }
    }
    mask
}

/// [`host_drawn`] of `name` at each frame of `frames`, with the physics stepped as the dump steps it.
fn host_masks(name: &str, frames: &[u32]) -> BTreeMap<u32, Vec<bool>> {
    let pmm = Pmm::read(&std::fs::read(mmegold().join(format!("{name}.pmm"))).unwrap()).unwrap();
    let read = |p: &str| {
        let name = p.rsplit(['\\', '/']).next().unwrap();
        std::fs::read(fixtures().join(name)).map_err(|e| e.to_string())
    };
    let pmxs: Vec<Pmx> = pmm
        .models
        .iter()
        .map(|m| Pmx::read(&read(&m.path.text).unwrap()).unwrap())
        .collect();
    let emm = std::fs::read(mmegold().join(format!("{name}.emm"))).unwrap();
    let (emm, _) = mds_mmert::emm::parse_emm(&emm, name);
    let keys: Vec<String> = emm.unwrap().sections[0]
        .entries
        .iter()
        .map(|e| e.key.clone())
        .collect();
    let assigned: Vec<bool> = (0..pmm.models.len())
        .map(|i| keys.contains(&format!("Pmd{i}")))
        .collect();
    let mut physics = PhysicsScene::new(&pmm, read).unwrap();
    let mut out = BTreeMap::new();
    for f in 0..=*frames.iter().max().unwrap() {
        if f > 0 {
            physics.step().unwrap();
        }
        if frames.contains(&f) {
            out.insert(f, host_drawn(&pmm, &pmxs, &assigned, &physics, f));
        }
    }
    out
}

// ---- pixels (mmegold.rs) ----

/// A pixel is close when no channel of R, G, B is more than `tolerance` from the golden image.
/// An image passes when `min_close` of its pixels are close and every other pixel is on an edge
/// of the golden image (its 3x3 neighbourhood there is not one colour within `tolerance`).
struct Limits {
    tolerance: u8,
    min_close: f64,
}

const LIMITS: Limits = Limits {
    tolerance: 4,
    min_close: 0.995,
};

#[derive(Debug)]
struct Score {
    pixels: usize,
    close: f64,
    max: u8,
    mean: f64,
    /// Pixels beyond the tolerance inside a flat area of the golden image.
    flat: usize,
}

impl Score {
    fn passes(&self) -> bool {
        self.close >= LIMITS.min_close && self.flat == 0
    }
}

fn pixel_diff(a: &[u8], i: usize, b: &[u8], j: usize) -> u8 {
    (0..3)
        .map(|c| a[i * 4 + c].abs_diff(b[j * 4 + c]))
        .max()
        .unwrap()
}

/// Whether the 3x3 neighbourhood of pixel `i` of `gold` is one colour within the tolerance.
fn flat(gold: &[u8], i: usize) -> bool {
    let (x, y) = ((i % W as usize) as i64, (i / W as usize) as i64);
    (-1..=1).all(|dy| {
        (-1..=1).all(|dx| {
            let (nx, ny) = (x + dx, y + dy);
            !(0..W as i64).contains(&nx)
                || !(0..H as i64).contains(&ny)
                || pixel_diff(gold, i, gold, (ny * W as i64 + nx) as usize) <= LIMITS.tolerance
        })
    })
}

fn read_png(path: &Path) -> Vec<u8> {
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut reader = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!(info.color_type, png::ColorType::Rgba);
    assert_eq!((info.width, info.height), (W, H));
    buf
}

/// What the app draws besides the effects: the grid, the axes, the ground line, and the bone
/// marks. `offscreen-0.png` holds them alone (its effect draws nothing visible), so every pixel
/// that is not white there is left out.
fn overlay() -> Vec<bool> {
    read_png(&mmegold().join("offscreen-0.png"))
        .chunks(4)
        .map(|p| p[..3] != [255, 255, 255])
        .collect()
}

fn score(px: &[u8], gold: &[u8], mask: &[bool]) -> Score {
    let (mut n, mut close, mut max, mut sum, mut flats) = (0, 0, 0u8, 0u64, 0);
    for i in (0..(W * H) as usize).filter(|&i| !mask[i]) {
        let d = pixel_diff(px, i, gold, i);
        flats += usize::from(d > LIMITS.tolerance && flat(gold, i));
        n += 1;
        close += usize::from(d <= LIMITS.tolerance);
        max = max.max(d);
        sum += u64::from(d);
    }
    Score {
        pixels: n,
        close: close as f64 / n as f64,
        max,
        mean: sum as f64 / n as f64,
        flat: flats,
    }
}

#[test]
fn frame_dumps_meet_the_mmegold_rule() {
    if mds_render::Gpu::new().expect("device").is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    }
    let lib = vkd3d_lib();
    if let Err(e) = mds_shader::vkd3d::Vkd3d::open(&lib) {
        eprintln!("SKIP: vkd3d-shader not loaded: {e} (not a pass)");
        return;
    }
    let corpus = corpus();
    let keep = std::env::var_os("MDS_APP_MME_DIR").map(PathBuf::from);
    let out = keep.clone().unwrap_or_else(|| {
        std::env::temp_dir().join(format!("mds-app-mme-{}", std::process::id()))
    });
    let mask = overlay();
    let mut table = Vec::new();
    let mut failures = Vec::new();
    for (name, frames) in SCENES {
        let emm = std::fs::read_to_string(mmegold().join(format!("{name}.emm"))).unwrap();
        let corpus = match &corpus {
            Some(c) => c.clone(),
            None if emm.contains("$(corpus)") => {
                eprintln!("SKIP {name}: needs the corpus (a skip is not a pass)");
                continue;
            }
            None => PathBuf::new(),
        };
        let dir = out.join(name);
        stage(name, &dir, &corpus);
        let status = Command::new(env!("CARGO_BIN_EXE_mds-app"))
            .env("MDS_VKD3D_LIB", &lib)
            .arg("--frame-dump")
            .arg(dir.join(format!("{name}.pmm")))
            .arg(dir.join("out"))
            .args(frames.iter().map(u32::to_string))
            .status()
            .unwrap();
        assert!(status.success(), "{name}: mds-app --frame-dump: {status}");
        let masks = host_masks(name, frames);
        for &f in frames {
            let px = read_png(&dir.join(format!("out/{name}-{f}.png")));
            let gold = read_png(&mmegold().join(format!("{name}-{f}.png")));
            let m: Vec<bool> = mask.iter().zip(&masks[&f]).map(|(a, b)| a | b).collect();
            let s = score(&px, &gold, &m);
            let image = format!("{name}-{f}");
            table.push(format!(
                "{image:<14} {:>7} {:>9.5} {:>4} {:>7.3} {:>5}  {}{}",
                s.pixels,
                s.close,
                s.max,
                s.mean,
                s.flat,
                if gated(name) { "yes" } else { "no" },
                if s.passes() { "" } else { " (fails)" }
            ));
            if gated(name) && !s.passes() {
                failures.push(format!("{image}: {s:?}"));
            }
        }
    }
    eprintln!(
        "{:<14} {:>7} {:>9} {:>4} {:>7} {:>5}  gated",
        "image", "pixels", "within 4", "max", "mean", "flat"
    );
    for l in &table {
        eprintln!("{l}");
    }
    if keep.is_none() {
        std::fs::remove_dir_all(&out).unwrap();
    }
    assert!(failures.is_empty(), "{failures:?}");
}
