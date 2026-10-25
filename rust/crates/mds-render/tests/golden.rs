//! The rendered swing600-golden scene against the golden images of the C++ app
//! (`tests/fixtures/rust/golden/`: frames 0, 150, 300 and 599, 640x360, 8x MSAA, D3D9).
//!
//! The metric, per pixel: the largest difference over R, G and B (alpha is 255 on both sides). The
//! whole picture passes when at least [`LIMITS`]`.min_close` of the pixels differ by at most
//! `tolerance` and none differs by more than `max_diff`. The only pixels left out are what the C++
//! app draws apart from the models (see [`overlay`]).
//!
//! `MDS_RENDER_PNG_DIR=<dir>` writes `render-<frame>.png` and `diff-<frame>.png` (4 times the
//! difference; masked pixels magenta) for a human to look at.
//!
//! The pose of every frame comes from `mds-physics` (a dev-dependency: the library does not use
//! it), stepped from the load the way its L2 gate steps `swing600.pmm`: physics mode 2, frame 0 is
//! the state after the load, and each later frame is one more `step`. Frame 0 needs it too: the
//! bodies settle at the load, which moves the swinging tips by up to a pixel from the bind pose.

use mds_formats::pmm::Pmm;
use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_physics::PhysicsScene;
use mds_render::{
    encode_png, render_frame, scene, Frame, Gpu, Mesh, Pose, PIXEL_OFFSET_D3D9, SAMPLES_8X,
};
use std::path::PathBuf;

mod common;
use common::{fixtures, gpu_or_skip, pixel_diff, read_png, Score, LIMITS};

const W: usize = 640;
const H: usize = 360;

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

fn golden_pmm() -> Pmm {
    let mut pmm =
        Pmm::read(&std::fs::read(fixtures().join("swing600-golden.pmm")).unwrap()).unwrap();
    pmm.physics.playback_mode = 2;
    pmm
}

fn golden(frame: u32) -> Vec<u8> {
    let (w, h, px) = read_png(&fixtures().join(format!("golden/swing600-golden-{frame}.png")));
    assert_eq!((w, h), (W, H));
    px
}

/// The poses of every model after `mds-physics` stepped the PMM to `frame`, in PMM order.
fn physics_poses(pmm: &Pmm, frame: u32) -> Vec<Pose> {
    let mut physics = PhysicsScene::new(pmm, model_bytes).unwrap();
    for _ in 0..frame {
        physics.step().unwrap();
    }
    pmm.models
        .iter()
        .map(|m| {
            let model = physics.scene.models.iter().find(|s| s.slot == m.slot);
            scene::pose_of(model.unwrap())
        })
        .collect()
}

// ---- rendering and the metric ----

fn render_at(gpu: &Gpu, pmm: &Pmm, posed: &[Pose], frame: u32) -> Vec<u8> {
    let meshes: Vec<Mesh> = pmm
        .models
        .iter()
        .map(|m| {
            let mut mesh = mesh_of(&m.path.text);
            mesh.set_edge_scale(m.edge_scale);
            mesh
        })
        .collect();
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
            toon: scene::toon_at(pmm, frame),
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

/// Compares `px` with the golden image of `frame` outside the overlay. With `dir`, writes the
/// render and the difference image there (4 times the difference; the overlay is magenta).
fn score(px: &[u8], frame: u32, dir: Option<&std::path::Path>) -> Score {
    let gold = golden(frame);
    let mut diff: Vec<u8> = [255, 0, 255, 255].repeat(W * H);
    let (mut n, mut close, mut max, mut sum) = (0, 0, 0u8, 0u64);
    for i in (0..W * H).filter(|&i| !overlay(i % W, i / W)) {
        let d = pixel_diff(px, &gold, i);
        let v = 255 - d.saturating_mul(4);
        diff[i * 4..i * 4 + 3].copy_from_slice(&[v, v, v]);
        n += 1;
        close += usize::from(d <= LIMITS.tolerance);
        max = max.max(d);
        sum += u64::from(d);
    }
    if let Some(dir) = dir {
        std::fs::create_dir_all(dir).unwrap();
        let (w, h) = (W as u32, H as u32);
        std::fs::write(
            dir.join(format!("render-{frame}.png")),
            encode_png(w, h, px),
        )
        .unwrap();
        std::fs::write(
            dir.join(format!("diff-{frame}.png")),
            encode_png(w, h, &diff),
        )
        .unwrap();
    }
    Score {
        pixels: n,
        close: close as f64 / n as f64,
        max,
        mean: sum as f64 / n as f64,
    }
}

/// Renders `frame` of the golden scene with the `mds-physics` pose and checks it against
/// [`LIMITS`].
fn gate(frame: u32) {
    let Some(gpu) = gpu_or_skip() else { return };
    let pmm = golden_pmm();
    let px = render_at(&gpu, &pmm, &physics_poses(&pmm, frame), frame);
    let dir = std::env::var_os("MDS_RENDER_PNG_DIR").map(PathBuf::from);
    let s = score(&px, frame, dir.as_deref());
    eprintln!(
        "frame {frame}: {} px, within {} {:.5}, max {}, mean {:.4}",
        s.pixels, LIMITS.tolerance, s.close, s.max, s.mean
    );
    assert!(s.close >= LIMITS.min_close, "frame {frame}: {s:?}");
    assert!(s.max <= LIMITS.max_diff, "frame {frame}: {s:?}");
}

#[test]
fn frame_0() {
    gate(0);
}

#[test]
fn frame_150() {
    gate(150);
}

#[test]
fn frame_300() {
    gate(300);
}

#[test]
fn frame_599() {
    gate(599);
}
