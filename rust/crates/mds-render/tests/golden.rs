//! The rendered swing600-golden scene against the golden images of the C++ app
//! (`tests/fixtures/rust/golden/`: frames 0, 150, 300 and 599, 640x360, 8x MSAA, D3D9).
//!
//! The metric, per pixel: the largest difference over R, G and B (alpha is 255 on both sides). Over
//! the pixels of a part of the picture the part passes when at least `min_close` of them differ by
//! at most `tolerance` and none differs by more than `max_diff` ([`LOOSE`] and [`TIGHT`] below).
//! The pixels left out are what the C++ app draws apart from the models (see [`overlay`]), the
//! columns of a model whose pose is not the golden pose, and, for a stand-in pose, the silhouette
//! (see [`Form`]).
//!
//! `MDS_RENDER_PNG_DIR=<dir>` writes `render-<frame>-<test>.png` and `diff-<frame>-<test>.png`
//! (4 times the difference; masked pixels magenta) for a human to look at.
//!
//! Where the poses come from, by test:
//!
//! * `frame_0`: `mds-pose` at physics mode 0, with the keys of the bones that have a rigid body
//!   cleared (the rigid body starts at the bind pose and drives the bone).
//! * `later_frames_with_the_recorded_pose`: the `bonew` and `morph` lines of the physics-on trace of
//!   `swing600.pmm` (`tests/fixtures/rust/l2/`), shifted by the root offset the golden PMM adds.
//!   Valid for the models that do not touch the others: the four models of `swing600.pmm` stand in
//!   one place and collide, those of the golden PMM do not, so slot 3 (and, after the golden PMM
//!   drops its outside-parent link at frame 300, slot 0) swing differently.
//! * `later_frames_with_mds_pose`: `mds-pose` itself, for physics mode 2. SKIP until it has it.

use mds_formats::pmm::Pmm;
use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_pose::Scene;
use mds_render::{
    encode_png, render_frame, scene, Frame, Gpu, Mesh, Pose, PIXEL_OFFSET_D3D9, SAMPLES_8X,
};
use std::collections::BTreeMap;
use std::path::PathBuf;

const W: usize = 640;
const H: usize = 360;

/// What a part of the picture must reach. A pixel is close when no channel is further than
/// `tolerance` from the golden image.
#[derive(Clone, Copy)]
struct Limits {
    tolerance: u8,
    min_close: f64,
    max_diff: u8,
}

/// For whole pictures with the physics-driven tips: 8 levels, 99.9% of the pixels, none beyond 40.
/// Frame 0 measures 99.976% and 32 (see `frame_0`).
const LOOSE: Limits = Limits {
    tolerance: 8,
    min_close: 0.999,
    max_diff: 40,
};
/// For parts the pose does not move (slot 1) and for interiors: 4 levels, 99.99%, none beyond 8.
/// They measure 100% and at most 4.
const TIGHT: Limits = Limits {
    tolerance: 4,
    min_close: 0.9999,
    max_diff: 8,
};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn model_bytes(path: &str) -> Result<Vec<u8>, String> {
    let name = path.rsplit(['\\', '/']).next().unwrap();
    std::fs::read(fixtures().join(name)).map_err(|e| format!("{name}: {e}"))
}

fn mesh_of(path: &str) -> Mesh {
    let data = model_bytes(path).unwrap();
    if path.to_ascii_lowercase().ends_with(".pmd") {
        Mesh::from_pmd(&Pmd::read(&data).unwrap()).unwrap()
    } else {
        Mesh::from_pmx(&Pmx::read(&data).unwrap()).unwrap()
    }
}

fn golden_pmm(physics_mode: u8) -> Pmm {
    let mut pmm =
        Pmm::read(&std::fs::read(fixtures().join("swing600-golden.pmm")).unwrap()).unwrap();
    pmm.physics.playback_mode = physics_mode;
    pmm
}

fn golden(frame: u32) -> Vec<u8> {
    let path = fixtures().join(format!("golden/swing600-golden-{frame}.png"));
    let mut reader = png::Decoder::new(std::io::Cursor::new(std::fs::read(path).unwrap()))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!((info.width as usize, info.height as usize), (W, H));
    assert_eq!(info.color_type, png::ColorType::Rgba);
    buf
}

// ---- poses ----

fn hex_float(t: &str) -> f32 {
    let (neg, t) = match t.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, t),
    };
    let (mant, exp) = t.strip_prefix("0x").unwrap().split_once('p').unwrap();
    let (lead, frac) = mant.split_once('.').unwrap();
    let m = f64::from(lead.parse::<u32>().unwrap())
        + f64::from(u32::from_str_radix(frac, 16).unwrap()) / f64::from(1u32 << (4 * frac.len()));
    let v = (m * 2f64.powi(exp.parse().unwrap())) as f32;
    if neg {
        -v
    } else {
        v
    }
}

#[test]
fn hex_floats_of_the_trace_parse_exactly() {
    assert_eq!(hex_float("0x1.800000p+1"), 3.0);
    assert_eq!(hex_float("-0x1.000000p-2"), -0.25);
    assert_eq!(hex_float("0x0.000000p+0"), 0.0);
    assert_eq!(hex_float("0x1.9b65d2p-1"), f32::from_bits(0x3f4d_b2e9));
}

/// The `bonew` skin matrices and `morph` values of one frame of an L2 trace, by slot.
fn trace_poses(trace: &str, frame: u32) -> BTreeMap<u8, Pose> {
    let mut out: BTreeMap<u8, Pose> = BTreeMap::new();
    let (bonew, morph) = (format!("{frame} bonew "), format!("{frame} morph "));
    for line in trace.lines() {
        let (rest, is_bone) = match (line.strip_prefix(&bonew), line.strip_prefix(&morph)) {
            (Some(r), _) => (r, true),
            (_, Some(r)) => (r, false),
            _ => continue,
        };
        let mut f = rest.split(' ');
        let slot: u8 = f.next().unwrap().parse().unwrap();
        let _index = f.next().unwrap();
        let v: Vec<f32> = f.map(hex_float).collect();
        let pose = out.entry(slot).or_default();
        if is_bone {
            pose.skin.push(v.try_into().unwrap());
        } else {
            pose.morphs.push(v[0]);
        }
    }
    out
}

fn mode0_scene(pmm_name: &str, frame: u32) -> Scene {
    let mut pmm = Pmm::read(&std::fs::read(fixtures().join(pmm_name)).unwrap()).unwrap();
    pmm.physics.playback_mode = 0;
    let mut scene = Scene::new(&pmm, model_bytes).unwrap();
    for _ in 0..frame {
        scene.step();
    }
    scene
}

fn frame_0_poses() -> Vec<Pose> {
    let mut pmm = golden_pmm(0);
    let probe = Scene::new(&pmm, model_bytes).unwrap();
    for (model, posed) in pmm.models.iter_mut().zip(&probe.models) {
        for (bone, key) in model.bone_keys.heads_mut().iter_mut().enumerate() {
            if posed.bones[bone].has_rigid_body != 0 {
                key.position = [0.0; 3];
                key.rotation = [0.0, 0.0, 0.0, 1.0];
            }
        }
    }
    let scene = Scene::new(&pmm, model_bytes).unwrap();
    scene.models.iter().map(scene::pose_of).collect()
}

/// The physics-on pose of `swing600.pmm` at `frame`, moved by the offset of each model's root bone
/// between `swing600.pmm` and the golden PMM (the golden PMM stands the models apart along x).
fn recorded_poses(trace: &str, frame: u32) -> Vec<Pose> {
    let mut poses = trace_poses(trace, frame);
    let golden = mode0_scene("swing600-golden.pmm", frame);
    let base = mode0_scene("swing600.pmm", frame);
    golden
        .models
        .iter()
        .zip(&base.models)
        .map(|(g, b)| {
            let mut pose = poses.remove(&g.slot).unwrap();
            for m in &mut pose.skin {
                for k in 0..3 {
                    m[12 + k] += g.bones[0].mat_init.0[12 + k] - b.bones[0].mat_init.0[12 + k];
                }
            }
            pose
        })
        .collect()
}

// ---- rendering and the metric ----

fn render_at(gpu: &Gpu, pmm: &Pmm, posed: &[Pose], frame: u32) -> Vec<u8> {
    let meshes: Vec<Mesh> = pmm.models.iter().map(|m| mesh_of(&m.path.text)).collect();
    let models: Vec<_> = meshes
        .iter()
        .zip(posed)
        .map(|(m, p)| (m, Some(p)))
        .collect();
    let camera = scene::camera_at(pmm, frame).unwrap();
    render_frame(
        gpu,
        &Frame {
            width: W as u32,
            height: H as u32,
            view: camera.view(W as u32, H as u32),
            light: scene::light_at(pmm, frame).unwrap(),
            background: [255; 4],
            toon: scene::self_shadow_mode_2_at(pmm, frame),
            models: &models,
            samples: &SAMPLES_8X,
            pixel_offset: PIXEL_OFFSET_D3D9,
        },
    )
    .unwrap()
}

/// What the C++ app draws besides the models, which the render does not: the ground line (two rows
/// of a gray 1 px line at the bottom of the models, rows 320 and 321 at this camera) and the
/// green bone axis (column 320, from the top of the picture down to the selected bone, which
/// moves with the pose; it ends above row 274 in all four frames). The grid and the axis follow
/// the app's own drawing rules, and the golden images show them only as one line each.
fn overlay(x: usize, y: usize) -> bool {
    (320..=321).contains(&y) || (x == 320 && y <= 273)
}

/// The columns each model occupies in the images (slot 3, 2, 0 and 1 from left to right; slot 3,
/// columns 0 to 190, is not compared with a stand-in pose).
const SLOT_2: std::ops::Range<usize> = 190..280;
const SLOT_0: std::ops::Range<usize> = 280..400;
const SLOT_1: std::ops::Range<usize> = 400..W;

/// How far from a pixel an image must be covered for the pixel to count as interior.
const INTERIOR: isize = 2;

/// How a part of the picture is compared.
#[derive(Clone, Copy, PartialEq)]
enum Form {
    /// Every pixel against the same pixel.
    Strict,
    /// Only the pixels at least [`INTERIOR`] pixels inside the models in both images: shading,
    /// light and toon compare, silhouettes (which a stand-in pose puts a pixel or two off) do not.
    Interior,
}

struct Part {
    cols: std::ops::Range<usize>,
    form: Form,
    limits: Limits,
}

#[derive(Debug)]
struct Score {
    pixels: usize,
    /// Fraction of the pixels within the part's tolerance.
    close: f64,
    max: u8,
    mean: f64,
}

fn pixel_diff(a: &[u8], b: &[u8], i: usize) -> u8 {
    (0..3)
        .map(|c| a[i * 4 + c].abs_diff(b[i * 4 + c]))
        .max()
        .unwrap()
}

fn covered(img: &[u8], i: usize) -> bool {
    img[i * 4..i * 4 + 3] != [255, 255, 255]
}

/// Whether the (2 * INTERIOR + 1) square around pixel `i` is covered in both images.
fn interior(a: &[u8], b: &[u8], i: usize) -> bool {
    let (x, y) = ((i % W) as isize, (i / W) as isize);
    (-INTERIOR..=INTERIOR).all(|dy| {
        (-INTERIOR..=INTERIOR).all(|dx| {
            let (nx, ny) = (x + dx, y + dy);
            (0..W as isize).contains(&nx)
                && (0..H as isize).contains(&ny)
                && covered(a, ny as usize * W + nx as usize)
                && covered(b, ny as usize * W + nx as usize)
        })
    })
}

/// Compares `px` with the golden image of `frame` over `parts`, outside the overlay; one score per
/// part. With `dir`, writes the render and the difference image there (4 times the difference;
/// pixels that are not compared are magenta).
fn score(
    px: &[u8],
    frame: u32,
    parts: &[Part],
    dir: Option<(&std::path::Path, &str)>,
) -> Vec<Score> {
    let gold = golden(frame);
    let mut diff: Vec<u8> = [255, 0, 255, 255].repeat(W * H);
    let mut scores = Vec::new();
    for part in parts {
        let (mut n, mut close, mut max, mut sum) = (0, 0, 0u8, 0u64);
        for i in (0..W * H).filter(|i| part.cols.contains(&(i % W))) {
            let compared =
                !overlay(i % W, i / W) && (part.form == Form::Strict || interior(px, &gold, i));
            if !compared {
                diff[i * 4..i * 4 + 3].copy_from_slice(&[255, 0, 255]);
                continue;
            }
            let d = pixel_diff(px, &gold, i);
            n += 1;
            close += usize::from(d <= part.limits.tolerance);
            max = max.max(d);
            sum += u64::from(d);
            let v = 255 - d.saturating_mul(4);
            diff[i * 4..i * 4 + 3].copy_from_slice(&[v, v, v]);
        }
        scores.push(Score {
            pixels: n,
            close: close as f64 / n as f64,
            max,
            mean: sum as f64 / n as f64,
        });
    }
    if let Some((dir, name)) = dir {
        std::fs::create_dir_all(dir).unwrap();
        let (w, h) = (W as u32, H as u32);
        std::fs::write(
            dir.join(format!("render-{frame}-{name}.png")),
            encode_png(w, h, px),
        )
        .unwrap();
        std::fs::write(
            dir.join(format!("diff-{frame}-{name}.png")),
            encode_png(w, h, &diff),
        )
        .unwrap();
    }
    scores
}

fn png_dir() -> Option<PathBuf> {
    std::env::var_os("MDS_RENDER_PNG_DIR").map(PathBuf::from)
}

fn gpu_or_skip() -> Option<Gpu> {
    let gpu = Gpu::new().expect("device");
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
    }
    gpu
}

fn check(name: &str, frame: u32, parts: &[Part], scores: &[Score]) {
    for (part, s) in parts.iter().zip(scores) {
        let l = part.limits;
        eprintln!(
            "{name} frame {frame} columns {:?} {}: {} px, within {} {:.5}, max {}, mean {:.4}",
            part.cols,
            if part.form == Form::Strict {
                "strict"
            } else {
                "interior"
            },
            s.pixels,
            l.tolerance,
            s.close,
            s.max,
            s.mean
        );
        assert!(
            s.close >= l.min_close,
            "{name} frame {frame} {:?}: {s:?}",
            part.cols
        );
        assert!(
            s.max <= l.max_diff,
            "{name} frame {frame} {:?}: {s:?}",
            part.cols
        );
    }
}

fn part(cols: std::ops::Range<usize>, form: Form, limits: Limits) -> Part {
    Part { cols, form, limits }
}

#[test]
fn frame_0() {
    let Some(gpu) = gpu_or_skip() else { return };
    let pmm = golden_pmm(2);
    let px = render_at(&gpu, &pmm, &frame_0_poses(), 0);
    let parts = [part(0..W, Form::Strict, LOOSE)];
    let scores = score(&px, 0, &parts, png_dir().as_deref().map(|d| (d, "frame_0")));
    check("frame_0", 0, &parts, &scores);
}

#[test]
fn later_frames_with_the_recorded_pose() {
    let Some(gpu) = gpu_or_skip() else { return };
    let pmm = golden_pmm(2);
    let trace = std::fs::read_to_string(fixtures().join("l2/swing600-600.trace")).unwrap();
    // Slot 1 has no rigid body: its pose is exact, so it compares strictly. So does slot 0 at
    // frame 150, which the recorded pose reproduces to a rounding step. Slot 2 moves like the
    // golden one apart from a pixel or two at the swinging tip, so its interior compares. Slot 3
    // is left out, and slot 0 from frame 300 (the golden PMM has no outside parent link there).
    for (frame, parts) in [
        (
            150,
            vec![
                part(SLOT_2, Form::Interior, TIGHT),
                part(SLOT_0, Form::Strict, TIGHT),
                part(SLOT_1, Form::Strict, TIGHT),
            ],
        ),
        (
            300,
            vec![
                part(SLOT_2, Form::Interior, TIGHT),
                part(SLOT_1, Form::Strict, TIGHT),
            ],
        ),
        (
            599,
            vec![
                part(SLOT_2, Form::Interior, TIGHT),
                part(SLOT_1, Form::Strict, TIGHT),
            ],
        ),
    ] {
        let px = render_at(&gpu, &pmm, &recorded_poses(&trace, frame), frame);
        let dir = png_dir();
        let scores = score(&px, frame, &parts, dir.as_deref().map(|d| (d, "recorded")));
        check("recorded", frame, &parts, &scores);
    }
}

#[test]
fn later_frames_with_mds_pose() {
    let Some(gpu) = gpu_or_skip() else { return };
    let pmm = golden_pmm(2);
    let mut scene = match Scene::new(&pmm, model_bytes) {
        Ok(scene) => scene,
        Err(e) => {
            eprintln!("SKIP: frames 150, 300 and 599 with mds-pose: {e} (not a pass)");
            return;
        }
    };
    let mut at = 0;
    for frame in [150, 300, 599] {
        while at < frame {
            scene.step();
            at += 1;
        }
        let posed: Vec<Pose> = scene.models.iter().map(self::scene::pose_of).collect();
        let px = render_at(&gpu, &pmm, &posed, frame);
        let parts = [part(0..W, Form::Strict, LOOSE)];
        let dir = png_dir();
        let scores = score(&px, frame, &parts, dir.as_deref().map(|d| (d, "mds_pose")));
        check("mds_pose", frame, &parts, &scores);
    }
}
