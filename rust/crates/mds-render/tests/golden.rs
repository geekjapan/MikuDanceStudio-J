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

const W: usize = 640;
const H: usize = 360;

/// What the whole picture of every frame must reach. A pixel is close when no channel is further
/// than `tolerance` from the golden image.
struct Limits {
    tolerance: u8,
    min_close: f64,
    max_diff: u8,
}

/// 4 levels, 99.99% of the pixels (at most 22 may be further), none beyond 48. Measured (see
/// `gate`): frame 0 differs by at most 1 level everywhere; frames 150, 300 and 599 have 1, 5 and
/// 10 pixels beyond 4 and a largest difference of 12, 46 and 25. Those pixels are hairline
/// slivers of the swinging strand of slot 3, where one of the
/// eight samples falls on the other side of the edge: a single sample of a dark sliver on white is
/// worth up to about 45 levels.
const LIMITS: Limits = Limits {
    tolerance: 4,
    min_close: 0.9999,
    max_diff: 48,
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

fn golden_pmm() -> Pmm {
    let mut pmm =
        Pmm::read(&std::fs::read(fixtures().join("swing600-golden.pmm")).unwrap()).unwrap();
    pmm.physics.playback_mode = 2;
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

#[derive(Debug)]
struct Score {
    pixels: usize,
    /// Fraction of the pixels within the tolerance.
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

fn gpu_or_skip() -> Option<Gpu> {
    let gpu = Gpu::new().expect("device");
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
    }
    gpu
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
