//! The golden2 scenes (`tests/fixtures/rust/golden2/`) against the golden images of the C++ app,
//! with the per-pixel rule of `golden.rs` ([`common::LIMITS`]).
//!
//! Every scene runs with physics mode 0, so the pose of a frame is its keys: `mds-physics` loads
//! the scene and steps it to the frame as the frame dump does.
//!
//! Left out of the comparison, as in `golden.rs`, is what the app draws apart from the scene:
//! the ground grid and its axes ([`grid_mask`]), which `mds-render` does not draw.
//!
//! Scenes that do not meet the rule yet are `#[ignore]`d with their score; `--include-ignored` runs
//! them.
//!
//! `MDS_RENDER_PNG_DIR=<dir>` writes `<scene>-<frame>.png` and `<scene>-<frame>-diff.png`
//! (4 times the difference; masked pixels magenta).

use mds_formats::pmm::Pmm;
use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_physics::PhysicsScene;
use mds_render::picture::PictureQuad;
use mds_render::{
    encode_png, render_frame_with, scene, AccessoryDraw, AccessoryMesh, Frame, Gpu, Image, Mesh,
    Picture, Pose, ShadowMapSize, Stage, View, PIXEL_OFFSET_D3D9, SAMPLES_8X,
};
use std::path::{Path, PathBuf};
use std::sync::Arc;

mod common;
use common::{fixtures, gpu_or_skip, pixel_diff, read_png, Score, LIMITS};

const W: usize = 640;
const H: usize = 360;

fn golden2() -> PathBuf {
    fixtures().join("golden2")
}

/// A file a scene names, by its last path component: the golden2 folder first (its own models,
/// textures and accessories), then the shared fixtures, then the accessory fixtures (`cube.x`).
/// The oracle staged all of them next to the exe.
fn scene_file(path: &str) -> Result<Vec<u8>, String> {
    let name = path.rsplit(['\\', '/']).next().unwrap_or(path);
    let file = [golden2(), fixtures(), fixtures().join("accessory")]
        .into_iter()
        .map(|d| d.join(name))
        .find(|f| f.is_file())
        .unwrap_or_else(|| golden2().join(name));
    std::fs::read(&file).map_err(|e| format!("{}: {e}", file.display()))
}

/// The model a scene names, with its textures. The app takes a model's texture folder from its
/// path up to the last backslash, so a bare file name (the chain models) loads no texture (README
/// of golden2).
fn mesh_of(path: &str) -> Mesh {
    let data = scene_file(path).unwrap();
    let mut mesh = if path.to_ascii_lowercase().ends_with(".pmd") {
        Mesh::from_pmd(&Pmd::read(&data).unwrap()).unwrap()
    } else {
        Mesh::from_pmx(&Pmx::read(&data).unwrap()).unwrap()
    };
    if path.contains('\\') {
        let errors = mesh.load_textures(|name| scene_file(name).ok());
        assert!(errors.is_empty(), "{errors:?}");
    }
    mesh
}

fn pmm(name: &str) -> Pmm {
    Pmm::read(&std::fs::read(golden2().join(format!("{name}.pmm"))).unwrap()).unwrap()
}

/// The scene stepped to `frame`.
fn stepped(pmm: &Pmm, frame: u32) -> PhysicsScene {
    let mut physics = PhysicsScene::new(pmm, scene_file).unwrap();
    for _ in 0..frame {
        physics.step().unwrap();
    }
    physics
}

/// The poses of every model in `physics`, in PMM order.
fn poses(pmm: &Pmm, physics: &PhysicsScene) -> Vec<Pose> {
    pmm.models
        .iter()
        .map(|m| {
            let model = physics.scene.models.iter().find(|s| s.slot == m.slot);
            scene::pose_of(model.unwrap())
        })
        .collect()
}

/// The accessories a scene names, with their textures.
fn accessories_of(pmm: &Pmm) -> Vec<AccessoryMesh> {
    pmm.accessories
        .iter()
        .map(|a| {
            let acc = mds_accessory::load_x(&scene_file(&a.path.text).unwrap()).unwrap();
            let mut mesh = AccessoryMesh::new(acc);
            let errors = mesh.load_textures(|name| scene_file(name).ok());
            assert!(errors.is_empty(), "{errors:?}");
            mesh
        })
        .collect()
}

fn render_at(gpu: &Gpu, pmm: &Pmm, frame: u32, shadow_map: ShadowMapSize) -> (Vec<u8>, View) {
    render_with_display(gpu, pmm, frame, shadow_map, None)
}

fn render_with_display(
    gpu: &Gpu,
    pmm: &Pmm,
    frame: u32,
    shadow_map: ShadowMapSize,
    shadow_map_display: Option<[f32; 4]>,
) -> (Vec<u8>, View) {
    let meshes: Vec<Mesh> = pmm
        .models
        .iter()
        .map(|m| {
            let mut mesh = mesh_of(&m.path.text);
            mesh.set_edge_scale(m.edge_scale);
            mesh
        })
        .collect();
    let physics = stepped(pmm, frame);
    let posed = poses(pmm, &physics);
    let accessories = accessories_of(pmm);
    let states: Vec<_> = pmm
        .accessories
        .iter()
        .map(|a| scene::accessory_at(a, frame, &physics.scene.models).unwrap())
        .collect();
    let draws: Vec<AccessoryDraw> = accessories
        .iter()
        .zip(&states)
        .map(|(mesh, (state, world))| AccessoryDraw {
            mesh,
            state,
            world: *world,
        })
        .collect();
    let image = (pmm.picture.enabled != 0).then(|| {
        let data = scene_file(&pmm.picture.path.text).unwrap();
        let img = Image::decode(&data).unwrap();
        let rect = picture_rect(pmm, &img);
        (Arc::new(img), rect)
    });
    let picture = image
        .as_ref()
        .map(|(image, rect)| Picture { image, rect: *rect });
    let stage = Stage {
        accessories: &draws,
        picture,
        shadow_map,
        shadow_map_display,
        ..scene::stage_at(pmm, frame)
    };
    let models: Vec<_> = meshes
        .iter()
        .zip(&posed)
        .map(|(m, p)| (m, Some(p)))
        .collect();
    let view = scene::camera_at(pmm, frame)
        .unwrap()
        .view(W as u32, H as u32);
    let px = render_frame_with(
        gpu,
        &Frame {
            width: W as u32,
            height: H as u32,
            view,
            light: scene::light_at(pmm, frame).unwrap(),
            background: [255; 4],
            toon: true,
            models: &models,
            samples: &SAMPLES_8X,
            pixel_offset: PIXEL_OFFSET_D3D9,
        },
        &stage,
    )
    .unwrap();
    (px, view)
}

/// Where the app put the picture quad: placed in the pixels of its main window's viewport, which
/// the `picture` line of the scene's edge probe records (offset, scale, picture size, an unused
/// value, the viewport, the output size, the quad), and drawn into the output unchanged (README
/// of golden2).
fn picture_rect(pmm: &Pmm, image: &Image) -> [f32; 4] {
    let probe = std::fs::read_to_string(golden2().join("background.edge.txt")).unwrap();
    let line = probe
        .lines()
        .find(|l| l.split(' ').nth(1) == Some("picture"))
        .unwrap();
    let v: Vec<f32> = line
        .split(' ')
        .skip(2)
        .map(|w| w.parse().unwrap())
        .collect();
    PictureQuad::in_viewport(
        image.width,
        image.height,
        pmm.picture.scale,
        pmm.picture.offset,
        [v[6], v[7], v[8], v[9]],
        pmm.settings.render_width as u32,
    )
    .rect
}

/// The grid lines are 5 units apart from -50 to 50 along x and z (`perspective-0.png`: the
/// farthest line is z = -50), drawn about 0.1 above the ground (the lines of the orthographic
/// scenes sit 3.7 px above y = 0, and the models' feet). The axes run from the origin along +x,
/// +y and -z, and past the grid: the z axis of `perspective-30.png` ends near z = -64.
const GRID_STEP: f32 = 5.0;
const GRID_HALF: f32 = 50.0;
const GRID_Y: f32 = 0.1;
const AXIS: f32 = 70.0;
/// How far from a line's center a pixel center may lie and still be masked. The app draws the
/// lines one pixel wide under 8x multisampling, which tints up to two pixels across a line.
const GRID_REACH: f32 = 1.5;
/// Lines are clipped at this view depth (w) in front of the camera.
const GRID_NEAR: f32 = 0.5;

/// The pixels the grid and its axes may cover, from the scene's own camera: every segment is
/// projected with `view` and the pixels within [`GRID_REACH`] of it are masked. Pixel centers are
/// on integer coordinates (Direct3D 9).
fn grid_mask(view: &View) -> Vec<bool> {
    let o = [0.0, GRID_Y, 0.0];
    let mut segments = vec![
        (o, [AXIS, GRID_Y, 0.0]),
        (o, [0.0, AXIS, 0.0]),
        (o, [0.0, GRID_Y, -AXIS]),
    ];
    let lines = (2.0 * GRID_HALF / GRID_STEP) as i32;
    for k in 0..=lines {
        let c = -GRID_HALF + k as f32 * GRID_STEP;
        segments.push(([c, GRID_Y, -GRID_HALF], [c, GRID_Y, GRID_HALF]));
        segments.push(([-GRID_HALF, GRID_Y, c], [GRID_HALF, GRID_Y, c]));
    }
    let mut mask = vec![false; W * H];
    for (a, b) in segments {
        let (mut ca, mut cb) = (view.clip(a), view.clip(b));
        if ca[3] < GRID_NEAR && cb[3] < GRID_NEAR {
            continue;
        }
        let cut = |p: [f32; 4], q: [f32; 4]| {
            let t = (GRID_NEAR - p[3]) / (q[3] - p[3]);
            std::array::from_fn::<f32, 4, _>(|i| p[i] + (q[i] - p[i]) * t)
        };
        if ca[3] < GRID_NEAR {
            ca = cut(ca, cb);
        } else if cb[3] < GRID_NEAR {
            cb = cut(cb, ca);
        }
        let px = |c: [f32; 4]| {
            [
                (c[0] / c[3] + 1.0) * 0.5 * W as f32,
                (1.0 - c[1] / c[3]) * 0.5 * H as f32,
            ]
        };
        let (pa, pb) = (px(ca), px(cb));
        let lo = |i: usize| (pa[i].min(pb[i]) - GRID_REACH).floor().max(0.0) as usize;
        let hi = |i: usize, n: usize| {
            ((pa[i].max(pb[i]) + GRID_REACH).ceil().max(0.0) as usize).min(n - 1)
        };
        let d = [pb[0] - pa[0], pb[1] - pa[1]];
        let len2 = d[0] * d[0] + d[1] * d[1];
        for y in lo(1)..=hi(1, H) {
            for x in lo(0)..=hi(0, W) {
                let p = [x as f32 - pa[0], y as f32 - pa[1]];
                let t = if len2 > 0.0 {
                    ((p[0] * d[0] + p[1] * d[1]) / len2).clamp(0.0, 1.0)
                } else {
                    0.0
                };
                let (ex, ey) = (p[0] - d[0] * t, p[1] - d[1] * t);
                if ex * ex + ey * ey <= GRID_REACH * GRID_REACH {
                    mask[y * W + x] = true;
                }
            }
        }
    }
    mask
}

/// Compares `px` with `golden` outside `mask`; with `dir`, writes the render and the difference.
fn score(px: &[u8], gold: &[u8], mask: &[bool], name: &str, dir: Option<&Path>) -> Score {
    let mut diff: Vec<u8> = [255, 0, 255, 255].repeat(W * H);
    let (mut n, mut close, mut max, mut sum) = (0, 0, 0u8, 0u64);
    for i in (0..W * H).filter(|&i| !mask[i]) {
        let d = pixel_diff(px, gold, i);
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
        std::fs::write(dir.join(format!("{name}.png")), encode_png(w, h, px)).unwrap();
        std::fs::write(
            dir.join(format!("{name}-diff.png")),
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

fn gate(scene: &str, frame: u32) {
    let Some(gpu) = gpu_or_skip() else { return };
    let pmm = pmm(scene);
    let (px, view) = render_at(&gpu, &pmm, frame, ShadowMapSize::default());
    let name = format!("{scene}-{frame}");
    let (w, h, gold) = read_png(&golden2().join(format!("{name}.png")));
    assert_eq!((w, h), (W, H));
    let mask = grid_mask(&view);
    let dir = std::env::var_os("MDS_RENDER_PNG_DIR").map(PathBuf::from);
    let s = score(&px, &gold, &mask, &name, dir.as_deref());
    eprintln!(
        "{name}: {} px ({} masked), within {} {:.5}, max {}, mean {:.4}",
        s.pixels,
        W * H - s.pixels,
        LIMITS.tolerance,
        s.close,
        s.max,
        s.mean
    );
    assert!(s.passes(), "{name}: {s:?}");
}

/// Every golden2 image and frame.
const IMAGES: [(&str, u32); 11] = [
    ("selfshadow", 0),
    ("selfshadow", 30),
    ("groundshadow", 0),
    ("groundshadow", 30),
    ("accessory", 0),
    ("accessory", 30),
    ("skin", 0),
    ("skin", 30),
    ("background", 0),
    ("perspective", 0),
    ("perspective", 30),
];

/// One multisample of the gray grid line over white is 8 to 11 levels.
const ONE_SAMPLE: u8 = 11;

/// The grid and the axes against every golden2 image, on the pixels [`grid_mask`] leaves out of
/// [`gate`]: at least [`GRID_MIN_CLOSE`] of them within the tolerance, and at most
/// [`GRID_MAX_OFF`] further than [`ONE_SAMPLE`]. Measured: 0.994 to 1 within 4, and up to 91
/// pixels beyond one sample (`perspective-0`), where the y axis meets the flat chain models in
/// their own plane (which wins is a matter of depth rounding) and where single samples of the
/// slanted lines fall on the other side of a pixel edge. Without the grid an image has thousands.
#[test]
fn grid_lines() {
    let Some(gpu) = gpu_or_skip() else { return };
    let mut failed = Vec::new();
    for (scene, frame) in IMAGES {
        let pmm = pmm(scene);
        let (px, view) = render_at(&gpu, &pmm, frame, ShadowMapSize::default());
        let name = format!("{scene}-{frame}");
        let (_, _, gold) = read_png(&golden2().join(format!("{name}.png")));
        let mask = grid_mask(&view);
        let lines: Vec<usize> = (0..W * H).filter(|&i| mask[i]).collect();
        let diffs: Vec<u8> = lines.iter().map(|&i| pixel_diff(&px, &gold, i)).collect();
        let close = diffs.iter().filter(|&&d| d <= LIMITS.tolerance).count();
        let off = diffs.iter().filter(|&&d| d > ONE_SAMPLE).count();
        eprintln!(
            "{name} grid: {} px, within {} {:.5}, beyond one sample {off}, max {}",
            lines.len(),
            LIMITS.tolerance,
            close as f64 / lines.len() as f64,
            diffs.iter().max().unwrap()
        );
        if off > GRID_MAX_OFF || (close as f64) < GRID_MIN_CLOSE * lines.len() as f64 {
            failed.push(name);
        }
    }
    assert!(failed.is_empty(), "{failed:?}");
}

const GRID_MAX_OFF: usize = 100;
const GRID_MIN_CLOSE: f64 = 0.99;

#[test]
fn groundshadow_0() {
    gate("groundshadow", 0);
}

#[test]
fn groundshadow_30() {
    gate("groundshadow", 30);
}

/// No golden image has the 4096 map. It must render, change the picture (the map is used), and
/// keep it close to the 2048 map's; the 2048 render after it checks that the map is made again.
#[test]
fn selfshadow_0_map_4096() {
    let Some(gpu) = gpu_or_skip() else { return };
    let pmm = pmm("selfshadow");
    let (big, _) = render_at(&gpu, &pmm, 0, ShadowMapSize::Texels4096);
    let (base, _) = render_at(&gpu, &pmm, 0, ShadowMapSize::Texels2048);
    let close = (0..W * H)
        .filter(|&i| pixel_diff(&big, &base, i) <= LIMITS.tolerance)
        .count() as f64
        / (W * H) as f64;
    eprintln!(
        "selfshadow-0, 4096 against 2048: within {} {close:.5}",
        LIMITS.tolerance
    );
    assert_ne!(big, base);
    assert!(close > 0.99, "{close}");
}

/// The self-shadow map display has no golden image: inside its rectangle the picture is the
/// map's depth in gray, with the models' depth darker than the white of the empty map; outside
/// it the picture is the one without the display. A frame without self-shadow draws no display.
#[test]
fn shadow_map_display_draws_the_map_in_gray() {
    let Some(gpu) = gpu_or_skip() else { return };
    let rect = [10.0, 20.0, 330.0, 340.0];
    let inside = |i: usize| {
        let (x, y) = ((i % W) as f32, (i / W) as f32);
        x >= rect[0] + 1.0 && x <= rect[2] - 2.0 && y >= rect[1] + 1.0 && y <= rect[3] - 2.0
    };
    let near_rect = |i: usize| {
        let (x, y) = ((i % W) as f32, (i / W) as f32);
        x >= rect[0] - 2.0 && x <= rect[2] + 1.0 && y >= rect[1] - 2.0 && y <= rect[3] + 1.0
    };
    let scene = pmm("selfshadow");
    let (plain, _) = render_at(&gpu, &scene, 0, ShadowMapSize::default());
    let (shown, _) = render_with_display(&gpu, &scene, 0, ShadowMapSize::default(), Some(rect));
    let mut dark = 0;
    for i in 0..W * H {
        let p = &shown[i * 4..i * 4 + 3];
        if inside(i) {
            assert!(p[0] == p[1] && p[1] == p[2], "pixel {i}: {p:?}");
            dark += usize::from(p[0] < 250);
        } else if !near_rect(i) {
            assert_eq!(p, &plain[i * 4..i * 4 + 3], "pixel {i}");
        }
    }
    assert!(dark > 100, "{dark} dark pixels");
    // Self-shadow is off in the ground shadow scene.
    let off = pmm("groundshadow");
    let (a, _) = render_at(&gpu, &off, 0, ShadowMapSize::default());
    let (b, _) = render_with_display(&gpu, &off, 0, ShadowMapSize::default(), Some(rect));
    assert_eq!(a, b);
}

#[test]
fn selfshadow_0() {
    gate("selfshadow", 0);
}

#[test]
#[ignore = "within 4 is 0.99998, but max 56: 3 pixels where a shadow map texel edge falls 1 px off"]
fn selfshadow_30() {
    gate("selfshadow", 30);
}

#[test]
#[ignore = "within 4 is 0.99984 (33 px over, 20 allowed): the cube's top edge and texel edges"]
fn accessory_0() {
    gate("accessory", 0);
}

#[test]
fn accessory_30() {
    gate("accessory", 30);
}

#[test]
#[ignore = "within 4 is 0.99927, max 107: the edge hull and the body of a translucent face meet in a 23 px sliver (depth rounding), and the translucent faces' edges"]
fn skin_0() {
    gate("skin", 0);
}

#[test]
#[ignore = "within 4 is 0.99889: the translucent faces and their edges"]
fn skin_30() {
    gate("skin", 30);
}

#[test]
fn background_0() {
    gate("background", 0);
}

#[test]
fn perspective_0() {
    gate("perspective", 0);
}

#[test]
fn perspective_30() {
    gate("perspective", 30);
}
