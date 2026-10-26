//! The runtime against the C++ application's MME path: the scenes, probes, and images of
//! `tests/fixtures/rust/mmegold/` (README there: `--mds-mme-dump`, the probe format).
//!
//! Per scene the test loads the PMM and its objects into `mds_mmert::host` (the host `mds-app`
//! draws through), takes the effect rows of the EMM, and renders every frame from 0 as the dump
//! does: frame 0 twice, then each frame. The poses come from `mds-physics` (physics mode 0: the
//! motion alone); the camera and light from the playback tracks.
//!
//! 1. Inputs: after each probed frame, every numeric parameter of every effect the probe lists
//!    equals it within [`VALUE_TOL`] (the count of bit-equal values is printed). `MOUSEPOSITION`
//!    follows the host's cursor and is not compared. [`KNOWN_INPUTS`] lists the known differences.
//! 2. Pixels: the 640x360 image against the golden PNG by the rule of [`LIMITS`], outside what
//!    the host draws itself: the grid, axes, ground line, and bone marks (every pixel that is not
//!    white in `offscreen-0.png`, whose effect draws nothing visible). The models without an effect
//!    are the host's standard shading and are compared; the table prints beside each mask the one
//!    the gate took before the host drew them ([`Staged::old_host_mask`]). [`PIXEL_GATED`] lists
//!    the scenes that meet the rule; the table prints them all. Not gated: `ray`, whose scene is dark (the light hits the faces the camera
//!    sees from behind, and there is no sky; see the mmegold README). `post` runs
//!    `mmegold/post.fx`, which drops the non-multisampled `RenderColorTarget1` that Direct3D 9
//!    refused beside the multisampled back buffer.
//!
//! `MDS_MMERT_PNG_DIR=<dir>` writes `<scene>-<frame>.png` and a difference image per frame.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_mmert::bind::mul;
use mds_mmert::emm::{parse_emm, Assignment};
use mds_mmert::host::{scene, Frame, Host, Source};
use mds_mmert::Gpu;
use mds_physics::PhysicsScene;
use mds_render::Camera;
use mds_scene::track::{evaluate_camera, evaluate_light, CameraMode, LightMode};
use mds_shader::vkd3d::Vkd3d;

mod common;

const W: u32 = 640;
const H: u32 = 360;
/// The back buffer of the C++ run (README), which `ViewportRatio` targets are sized against. The
/// picture is its 640x360 corner.
const BACKBUFFER: (u32, u32) = (3072, 1728);

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

/// `|rust - probe| <= VALUE_TOL * max(1, |probe|)`. The probe's matrices come from D3DX on x64;
/// the runtime's from `mds-math` and plain f32 products, which differ in the last bits.
const VALUE_TOL: f32 = 1e-5;

/// `(scene, effect file, parameter)` that differ from the probe, and why.
const KNOWN_INPUTS: &[(&str, &str, &str, &str)] = &[(
    "ray",
    "ray-mmd/ray.fx",
    "MaterialPower",
    "a scene effect binds the stale device material of the host's last draw (5, chain8's power); \
     the runtime has no device material and binds none (0.1)",
)];

/// Scenes whose every probed frame meets [`LIMITS`].
const PIXEL_GATED: &[&str] = &[
    "objects",
    "post",
    "offscreen",
    "timeofday",
    "main",
    "control",
    "anime",
];

fn mmegold() -> PathBuf {
    common::fixtures().join("mmegold")
}

/// The scene's own effects staged with `blink.gif` beside them, as `mmegold.ps1` stages them.
fn stage() -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-mmertgold-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    for f in ["anime.fx", "control.fx", "post.fx"] {
        std::fs::copy(mmegold().join(f), dir.join(f)).unwrap();
    }
    let gif = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data/blink.gif");
    std::fs::copy(gif, dir.join("blink.gif")).unwrap();
    dir
}

// ---- the probe ----

#[derive(Debug)]
struct Param {
    name: String,
    semantic: String,
    values: Vec<f32>,
}

#[derive(Debug)]
struct ProbeEffect {
    path: String,
    params: Vec<Param>,
}

#[derive(Debug)]
struct Probe {
    frame: u32,
    time: f32,
    /// `(object file, assigned effect or "-")`.
    objects: Vec<(String, String)>,
    effects: Vec<ProbeEffect>,
}

fn parse_probe(text: &str) -> Probe {
    let mut lines = text.lines();
    assert_eq!(lines.next(), Some("mds-mme-probe 1"));
    let mut p = Probe {
        frame: 0,
        time: 0.0,
        objects: Vec::new(),
        effects: Vec::new(),
    };
    for line in lines {
        let f: Vec<&str> = line.split(' ').collect();
        match f[0] {
            "frame" => {
                p.frame = f[1].parse().unwrap();
                p.time = f[2].parse().unwrap();
            }
            // object <file> effect <path> class C render R shown S; the path may hold spaces.
            "object" => {
                let at = f.iter().position(|&w| w == "effect").unwrap();
                let n = f.len();
                p.objects
                    .push((f[1..at].join(" "), f[at + 1..n - 6].join(" ")));
            }
            // effect <path> class C order O errors E
            "effect" => p.effects.push(ProbeEffect {
                path: f[1..f.len() - 6].join(" "),
                params: Vec::new(),
            }),
            // param <name> <semantic> <class> <type> <RxCxE> <value>...
            "param" => p.effects.last_mut().unwrap().params.push(Param {
                name: f[1].into(),
                semantic: f[2].into(),
                values: f[6..].iter().map(|v| v.parse().unwrap()).collect(),
            }),
            _ => panic!("unknown probe line: {line}"),
        }
    }
    p
}

// ---- the scene ----

/// Where an effect path of the stage lives here.
fn local(path: &str, stage: &Path, corpus: &Path) -> PathBuf {
    let path = path.replace('\\', "/");
    let (dir, rest) = path.split_once('/').unwrap();
    let root = match dir {
        "effects" => common::fixtures().join("mme/effects"),
        "mmegold" => stage.to_path_buf(),
        "ray-mmd" => corpus.to_path_buf(),
        _ => panic!("unknown effect root in {path}"),
    };
    mds_fx::preprocess::resolve_ci(&root, rest).unwrap_or_else(|| root.join(rest))
}

/// The probe's spelling of an EMM effect row (`$(fixtures)\objects.fx` is `effects/objects.fx`).
fn stage_path(row: &str) -> String {
    row.replace("$(fixtures)", "effects")
        .replace("$(mmegold)", "mmegold")
        .replace("$(corpus)", "ray-mmd")
        .replace('\\', "/")
}

fn file_name(path: &str) -> &str {
    path.rsplit(['\\', '/']).next().unwrap()
}

fn scene_file(path: &str) -> Result<Vec<u8>, String> {
    let name = file_name(path);
    std::fs::read(common::fixtures().join(name)).map_err(|e| format!("{name}: {e}"))
}

/// The scene's camera at `frame`, as the dump's playback evaluates it.
fn camera(pmm: &Pmm, frame: u32) -> Camera {
    let c = evaluate_camera(&pmm.camera, f64::from(frame), CameraMode::Playback).unwrap();
    Camera {
        target: c.position,
        rotation: c.rotation,
        distance: c.distance,
        fov_deg: c.fov,
        orthographic: c.perspective == 1,
    }
}

struct Staged {
    pmm: Pmm,
    pmxs: Vec<Pmx>,
    host: Host,
    stage: PathBuf,
    corpus: PathBuf,
    /// The EMM rows, by object index, in the probe's spelling.
    assignments: Vec<Assignment>,
}

impl Staged {
    fn new(gpu: &Gpu, name: &str, stage: &Path, corpus: &Path) -> Staged {
        let pmm =
            Pmm::read(&std::fs::read(mmegold().join(format!("{name}.pmm"))).unwrap()).unwrap();
        let pmxs: Vec<Pmx> = pmm
            .models
            .iter()
            .map(|m| Pmx::read(&scene_file(&m.path.text).unwrap()).unwrap())
            .collect();
        let mut host = Host::new(BACKBUFFER);
        let read = |n: &str| std::fs::read(common::fixtures().join(n)).ok();
        for (m, pmx) in pmm.models.iter().zip(&pmxs) {
            host.add(gpu, &m.path.text, Source::Pmx(pmx), m.edge_scale, read)
                .unwrap();
        }
        for a in &pmm.accessories {
            let file = corpus.join(file_name(&a.path.text));
            let acc = mds_accessory::vac::load_file(&file).unwrap();
            host.add(gpu, &a.path.text, Source::Accessory(acc), 1.0, read)
                .unwrap();
        }
        let emm_path = mmegold().join(format!("{name}.emm"));
        let (emm, log) = parse_emm(
            &std::fs::read(&emm_path).unwrap(),
            &emm_path.to_string_lossy(),
        );
        let emm = emm.unwrap_or_else(|| panic!("{name}.emm: {log:?}"));
        let section = emm.sections.iter().find(|s| s.is_default()).unwrap();
        let n_models = pmm.models.len();
        let mut assignments = vec![Assignment::default(); n_models + pmm.accessories.len()];
        for e in &section.entries {
            let owner = if let Some(s) = e.key.strip_prefix("Pmd") {
                s.parse::<usize>().unwrap()
            } else {
                n_models + e.key.strip_prefix("Acs").unwrap().parse::<usize>().unwrap()
            };
            assignments[owner].effect = stage_path(&e.effect);
        }
        Staged {
            pmm,
            pmxs,
            host,
            stage: stage.to_path_buf(),
            corpus: corpus.to_path_buf(),
            assignments,
        }
    }

    /// The mask the gate took before the host drew the objects without an effect: the screen
    /// rectangle, 2 px wider, of each model other than the first that has no effect (`morph4.pmx`
    /// of `control`). Each vertex moves with its first bone. The table prints its size beside
    /// today's mask.
    fn old_host_mask(&self, physics: &PhysicsScene, frame: u32) -> Vec<bool> {
        let light = evaluate_light(&self.pmm.light, f64::from(frame), LightMode::Playback).unwrap();
        let (scene, _, _) = scene(
            &camera(&self.pmm, frame).into(),
            [0.0; 2],
            light,
            frame,
            0.0,
            (W, H),
        )
        .unwrap();
        let view_proj = mul(&scene.view, &scene.projection);
        let mut mask = vec![false; (W * H) as usize];
        for (i, (m, pmx)) in self.pmm.models.iter().zip(&self.pmxs).enumerate().skip(1) {
            if !self.assignments[i].effect.is_empty() {
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

    /// Renders `frame` into the host's back buffer and returns why draws were skipped.
    fn render(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        frame: u32,
        elapsed: f32,
        physics: &PhysicsScene,
    ) -> Vec<String> {
        let camera = camera(&self.pmm, frame);
        let light = evaluate_light(&self.pmm.light, f64::from(frame), LightMode::Playback).unwrap();
        let (stage, corpus) = (self.stage.clone(), self.corpus.clone());
        let resolve = |p: &str| local(p, &stage, &corpus);
        let f = Frame {
            pmm: &self.pmm,
            poses: &physics.scene.models,
            camera: &camera.into(),
            view_offset: [0.0; 2],
            shadow_map: Default::default(),
            shadow_map_display: false,
            light,
            frame,
            elapsed,
            size: (W, H),
            assignments: &self.assignments,
            offscreen: &Default::default(),
            resolve: &resolve,
        };
        let mut log = Vec::new();
        self.host.render(gpu, vk, &f, &mut log)
    }
}

/// Renders `name` from frame 0 to its last probed frame and calls `at` after each probed frame
/// with the image, the skipped draws, and [`Staged::old_host_mask`]. Returns the wgpu errors.
fn run_scene(
    gpu: &Gpu,
    vk: &Vkd3d,
    staged: &mut Staged,
    frames: &[u32],
    mut at: impl FnMut(&Staged, u32, Vec<u8>, Vec<String>, Vec<bool>),
) -> Vec<String> {
    let mut physics = PhysicsScene::new(&staged.pmm, scene_file).unwrap();
    let ((), errors) = gpu.scoped(|| {
        // The render while the app loads: the frame before frame 0 in edit mode, which makes
        // ELAPSEDTIME 0 at frame 0.
        staged.render(gpu, vk, 0, 0.0, &physics);
        for f in 0..=*frames.iter().max().unwrap() {
            if f > 0 {
                physics.step().unwrap();
            }
            let elapsed = if f == 0 { 0.0 } else { 1.0 / 30.0 };
            let skipped = staged.render(gpu, vk, f, elapsed, &physics);
            if frames.contains(&f) {
                let old = staged.old_host_mask(&physics, f);
                let px = staged.host.target().unwrap().read(gpu).unwrap();
                at(staged, f, px, skipped, old);
            }
        }
    });
    errors
}

// ---- inputs ----

#[derive(Default)]
struct InputScore {
    values: usize,
    exact: usize,
    skipped: usize,
    /// Values of the parameters that differ.
    differing: usize,
    /// The differences not in [`KNOWN_INPUTS`], then the known ones.
    failures: Vec<String>,
    known: Vec<String>,
}

fn close(a: f32, b: f32) -> bool {
    (a - b).abs() <= VALUE_TOL * b.abs().max(1.0)
}

/// A path to compare loaded effects by: the file itself, else as it is spelled.
fn canonical(p: &Path) -> PathBuf {
    std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf())
}

fn compare_inputs(scene: &str, host: &Staged, probe: &Probe, out: &mut InputScore) {
    let at = format!("{scene}-{}", probe.frame);
    let assigned: Vec<(String, String)> = host
        .pmm
        .models
        .iter()
        .map(|m| file_name(&m.path.text).to_string())
        .chain(
            host.pmm
                .accessories
                .iter()
                .map(|a| a.path.text.replace('\\', "/")),
        )
        .zip(&host.assignments)
        .map(|(n, a)| {
            let e = if a.effect.is_empty() {
                "-".into()
            } else {
                a.effect.clone()
            };
            (n, e)
        })
        .collect();
    if assigned != probe.objects {
        out.failures.push(format!(
            "{at}: objects {assigned:?}, probe {:?}",
            probe.objects
        ));
    }
    for pe in &probe.effects {
        let file = canonical(&local(&pe.path, &host.stage, &host.corpus));
        let Some(l) = host
            .host
            .effects()
            .iter()
            .find(|l| canonical(&l.file) == file)
        else {
            out.failures.push(format!("{at}: {} not loaded", pe.path));
            continue;
        };
        for p in &pe.params {
            if p.semantic == "MOUSEPOSITION" {
                out.skipped += p.values.len();
                continue;
            }
            let Some(i) = l.effect.sas.fx.param_by_name(&p.name) else {
                out.failures
                    .push(format!("{at}: {} has no parameter {}", pe.path, p.name));
                continue;
            };
            let rust = &l.effect.values[i];
            out.values += p.values.len();
            out.exact += rust
                .iter()
                .zip(&p.values)
                .filter(|(a, b)| a.to_bits() == b.to_bits())
                .count();
            if rust.len() == p.values.len()
                && rust.iter().zip(&p.values).all(|(&a, &b)| close(a, b))
            {
                continue;
            }
            out.differing += p.values.len();
            let line = format!(
                "{at}: {} {} ({}): rust {rust:?}, probe {:?}",
                pe.path, p.name, p.semantic, p.values
            );
            match KNOWN_INPUTS
                .iter()
                .find(|k| k.0 == scene && k.1 == pe.path && k.2 == p.name)
            {
                Some(k) => out.known.push(format!("{line} [known: {}]", k.3)),
                None => out.failures.push(line),
            }
        }
    }
}

// ---- pixels ----

/// A pixel is close when no channel of R, G, B is more than `tolerance` from the golden image.
/// An image passes when `min_close` of its pixels are close and every other pixel is on an edge
/// of the golden image (its 3x3 neighbourhood there is not one colour within `tolerance`): the
/// runtime draws without multisampling, so a silhouette pixel may differ by up to 255.
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

/// Whether the 3x3 neighbourhood of pixel `i` of `gold` is one colour within the tolerance.
fn flat(gold: &[u8], i: usize) -> bool {
    let (x, y) = ((i % W as usize) as i64, (i / W as usize) as i64);
    (-1..=1).all(|dy| {
        (-1..=1).all(|dx| {
            let (nx, ny) = (x + dx, y + dy);
            !(0..W as i64).contains(&nx)
                || !(0..H as i64).contains(&ny)
                || pixel_diff_at(gold, i, (ny * W as i64 + nx) as usize) <= LIMITS.tolerance
        })
    })
}

fn pixel_diff_at(px: &[u8], i: usize, j: usize) -> u8 {
    (0..3)
        .map(|c| px[i * 4 + c].abs_diff(px[j * 4 + c]))
        .max()
        .unwrap()
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

fn encode_png(px: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut enc = png::Encoder::new(&mut out, W, H);
    enc.set_color(png::ColorType::Rgba);
    enc.write_header().unwrap().write_image_data(px).unwrap();
    out
}

fn pixel_diff(a: &[u8], b: &[u8], i: usize) -> u8 {
    (0..3)
        .map(|c| a[i * 4 + c].abs_diff(b[i * 4 + c]))
        .max()
        .unwrap()
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

fn score(px: &[u8], gold: &[u8], mask: &[bool], name: &str, dir: Option<&Path>) -> Score {
    let n_px = (W * H) as usize;
    let mut diff: Vec<u8> = [255, 0, 255, 255].repeat(n_px);
    let (mut n, mut close, mut max, mut sum, mut flats) = (0, 0, 0u8, 0u64, 0);
    for i in (0..n_px).filter(|&i| !mask[i]) {
        let d = pixel_diff(px, gold, i);
        flats += usize::from(d > LIMITS.tolerance && flat(gold, i));
        let v = 255 - d.saturating_mul(4);
        diff[i * 4..i * 4 + 3].copy_from_slice(&[v, v, v]);
        n += 1;
        close += usize::from(d <= LIMITS.tolerance);
        max = max.max(d);
        sum += u64::from(d);
    }
    if let Some(dir) = dir {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(format!("{name}.png")), encode_png(px)).unwrap();
        std::fs::write(dir.join(format!("{name}-diff.png")), encode_png(&diff)).unwrap();
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
fn scenes_match_the_cpp_probes_and_images() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let corpus = common::corpus();
    let stage = stage();
    let mask = overlay();
    let png_dir = std::env::var_os("MDS_MMERT_PNG_DIR").map(PathBuf::from);
    let mut inputs = InputScore::default();
    let mut table = vec![format!(
        "{:<14} {:>7} {:>9} {:>4} {:>7} {:>5} {:>7} {:>7}  gated",
        "image", "pixels", "within 4", "max", "mean", "flat", "masked", "before"
    )];
    let mut pixel_failures = Vec::new();
    let mut by_scene: BTreeMap<&str, bool> = BTreeMap::new();
    for (name, frames) in SCENES {
        let text = std::fs::read_to_string(mmegold().join(format!("{name}.emm"))).unwrap();
        let corpus = match &corpus {
            Some(c) => c.clone(),
            None if text.contains("$(corpus)") => {
                eprintln!("SKIP {name}: needs the corpus (a skip is not a pass)");
                continue;
            }
            None => PathBuf::new(),
        };
        let mut staged = Staged::new(&gpu, name, &stage, &corpus);
        let errors = run_scene(
            &gpu,
            &vk,
            &mut staged,
            frames,
            |host, f, px, skipped, old_mask| {
                let probe = parse_probe(
                    &std::fs::read_to_string(mmegold().join(format!("{name}-{f}.mme.txt")))
                        .unwrap(),
                );
                assert_eq!((probe.frame, probe.time), (f, f as f32 / 30.0));
                compare_inputs(name, host, &probe, &mut inputs);
                if !skipped.is_empty() {
                    eprintln!("{name}-{f}: skipped draws {skipped:?}");
                }
                let gold = read_png(&mmegold().join(format!("{name}-{f}.png")));
                let image = format!("{name}-{f}");
                let s = score(&px, &gold, &mask, &image, png_dir.as_deref());
                let before = mask
                    .iter()
                    .zip(&old_mask)
                    .filter(|(a, b)| **a || **b)
                    .count();
                let pass = s.passes();
                let gated = name != "ray" && PIXEL_GATED.contains(&name);
                *by_scene.entry(name).or_insert(true) &= pass;
                table.push(format!(
                    "{image:<14} {:>7} {:>9.5} {:>4} {:>7.3} {:>5} {:>7} {:>7}  {}{}",
                    s.pixels,
                    s.close,
                    s.max,
                    s.mean,
                    s.flat,
                    (W * H) as usize - s.pixels,
                    before,
                    if gated { "yes" } else { "no" },
                    if pass { "" } else { " (fails)" }
                ));
                if gated && !pass {
                    pixel_failures.push(format!("{image}: {s:?}"));
                }
            },
        );
        if !errors.is_empty() {
            eprintln!("{name}: wgpu errors {errors:?}");
        }
    }
    eprintln!(
        "inputs: {} values, {} bit-equal, {} within {VALUE_TOL:e}, {} MOUSEPOSITION values not compared",
        inputs.values,
        inputs.exact,
        inputs.values - inputs.differing,
        inputs.skipped
    );
    for k in &inputs.known {
        eprintln!("  {k}");
    }
    for f in &inputs.failures {
        eprintln!("  DIFFERS {f}");
    }
    eprintln!(
        "pixels ({}, at least {} of the pixels):",
        LIMITS.tolerance, LIMITS.min_close
    );
    for l in &table {
        eprintln!("  {l}");
    }
    let passing: Vec<&str> = by_scene
        .iter()
        .filter(|(_, &p)| p)
        .map(|(n, _)| *n)
        .collect();
    eprintln!("scenes that meet the rule: {passing:?}");
    assert!(
        inputs.failures.is_empty(),
        "{} inputs differ",
        inputs.failures.len()
    );
    assert!(pixel_failures.is_empty(), "{pixel_failures:?}");
}

#[test]
fn missing_inputs_skip_instead_of_panicking() {
    let nowhere = std::env::temp_dir().join("mds-mmertgold-nowhere");
    assert!(common::vkd3d_at(&nowhere.join("libvkd3d-shader.dylib")).is_none());
    assert!(common::corpus_at(&nowhere).is_none());
}

#[test]
fn local_effect_paths_match_windows_case() {
    let dir = std::env::temp_dir().join(format!("mds-mmegold-paths-{}", std::process::id()));
    let materials = dir.join("Materials");
    let shadow = dir.join("Shadow");
    std::fs::create_dir_all(&materials).unwrap();
    std::fs::create_dir_all(&shadow).unwrap();
    std::fs::write(materials.join("material_2.0.fx"), b"material").unwrap();
    std::fs::write(shadow.join("PSSM1.fx"), b"shadow").unwrap();
    assert_eq!(
        local("ray-mmd/materials/material_2.0.fx", &dir, &dir),
        materials.join("material_2.0.fx")
    );
    assert_eq!(
        local("mmegold\\shadow\\pssm1.FX", &dir, &dir),
        shadow.join("PSSM1.fx")
    );
    assert_eq!(
        local("ray-mmd/missing.fx", &dir, &dir),
        dir.join("missing.fx")
    );
    std::fs::remove_dir_all(dir).unwrap();
}
