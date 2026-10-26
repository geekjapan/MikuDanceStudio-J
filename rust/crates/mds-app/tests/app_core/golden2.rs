//! `mds-app --frame-dump` of the golden2 scenes (`tests/fixtures/rust/golden2/`) against the
//! direct render of `mds-render/tests/golden2.rs`: the same pixels, so the dump meets the numbers
//! that test prints for every scene. [`direct`] is `render_at` of that file, copied, because a
//! test file of another crate cannot be imported.
//!
//! The scenes are staged into one folder first ([`stage_golden2`]). The background picture is
//! placed in the viewport of the edge probe (`MDS_FRAME_DUMP_PICTURE_VIEWPORT`), as golden2.rs
//! places it.

use super::{fixtures, scratch, stage_golden2};
use mds_formats::pmm::Pmm;
use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_physics::PhysicsScene;
use mds_render::picture::PictureQuad;
use mds_render::{
    render_frame_with, scene, AccessoryDraw, AccessoryMesh, Frame, Gpu, Image, Mesh, Picture, Pose,
    Stage, PIXEL_OFFSET_D3D9, SAMPLES_8X,
};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

const W: u32 = 640;
const H: u32 = 360;
const SCENES: [(&str, &[u32]); 6] = [
    ("selfshadow", &[0, 30]),
    ("groundshadow", &[0, 30]),
    ("accessory", &[0, 30]),
    ("skin", &[0, 30]),
    ("background", &[0]),
    ("perspective", &[0, 30]),
];

fn golden2() -> PathBuf {
    fixtures().join("golden2")
}

fn read_png(path: &Path) -> Vec<u8> {
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut reader = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!((info.width, info.height), (W, H));
    buf
}

/// The viewport of the `picture` line of the background scene's edge probe.
fn probe_viewport() -> [f32; 4] {
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
    [v[6], v[7], v[8], v[9]]
}

fn scene_file(path: &str) -> Result<Vec<u8>, String> {
    let name = path.rsplit(['\\', '/']).next().unwrap_or(path);
    let file = [golden2(), fixtures(), fixtures().join("accessory")]
        .into_iter()
        .map(|d| d.join(name))
        .find(|f| f.is_file())
        .unwrap_or_else(|| golden2().join(name));
    std::fs::read(&file).map_err(|e| format!("{}: {e}", file.display()))
}

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

/// `render_at` of `mds-render/tests/golden2.rs`.
fn direct(gpu: &Gpu, pmm: &Pmm, frame: u32) -> Vec<u8> {
    let meshes: Vec<Mesh> = pmm
        .models
        .iter()
        .map(|m| {
            let mut mesh = mesh_of(&m.path.text);
            mesh.set_edge_scale(m.edge_scale);
            mesh
        })
        .collect();
    let mut physics = PhysicsScene::new(pmm, scene_file).unwrap();
    for _ in 0..frame {
        physics.step().unwrap();
    }
    let posed: Vec<Pose> = pmm
        .models
        .iter()
        .map(|m| {
            let model = physics.scene.models.iter().find(|s| s.slot == m.slot);
            scene::pose_of(model.unwrap())
        })
        .collect();
    let accessories: Vec<AccessoryMesh> = pmm
        .accessories
        .iter()
        .map(|a| {
            let acc = mds_accessory::load_x(&scene_file(&a.path.text).unwrap()).unwrap();
            let mut mesh = AccessoryMesh::new(acc);
            assert!(mesh.load_textures(|n| scene_file(n).ok()).is_empty());
            mesh
        })
        .collect();
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
        let img = Image::decode(&scene_file(&pmm.picture.path.text).unwrap()).unwrap();
        let rect = PictureQuad::in_viewport(
            img.width,
            img.height,
            pmm.picture.scale,
            pmm.picture.offset,
            probe_viewport(),
            pmm.settings.render_width as u32,
        )
        .rect;
        (Arc::new(img), rect)
    });
    let picture = image
        .as_ref()
        .map(|(image, rect)| Picture { image, rect: *rect });
    let stage = Stage {
        accessories: &draws,
        picture,
        ..scene::stage_at(pmm, frame)
    };
    let models: Vec<_> = meshes
        .iter()
        .zip(&posed)
        .map(|(m, p)| (m, Some(p)))
        .collect();
    render_frame_with(
        gpu,
        &Frame {
            width: W,
            height: H,
            view: scene::camera_at(pmm, frame).unwrap().view(W, H),
            light: scene::light_at(pmm, frame).unwrap(),
            background: [255; 4],
            toon: true,
            models: &models,
            samples: &SAMPLES_8X,
            pixel_offset: PIXEL_OFFSET_D3D9,
        },
        &stage,
    )
    .unwrap()
}

#[test]
fn the_dump_of_every_golden2_scene_is_the_direct_render() {
    let gpu = Gpu::new().expect("device");
    let Some(gpu) = gpu else {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    };
    let dir = scratch("golden2");
    std::fs::create_dir(dir.join("in")).unwrap();
    stage_golden2(&dir.join("in"));
    let [l, t, r, b] = probe_viewport();
    let mut compared = 0;
    for (name, frames) in SCENES {
        let out = dir.join("out");
        let status = Command::new(env!("CARGO_BIN_EXE_mds-app"))
            .env(
                "MDS_FRAME_DUMP_PICTURE_VIEWPORT",
                format!("{l},{t},{r},{b}"),
            )
            .arg("--frame-dump")
            .arg(dir.join("in").join(format!("{name}.pmm")))
            .arg(&out)
            .args(frames.iter().map(u32::to_string))
            .status()
            .unwrap();
        assert!(status.success(), "{name}: {status}");
        let pmm =
            Pmm::read(&std::fs::read(golden2().join(format!("{name}.pmm"))).unwrap()).unwrap();
        for &frame in frames {
            let dumped = read_png(&out.join(format!("{name}-{frame}.png")));
            let want = direct(&gpu, &pmm, frame);
            let differ = dumped
                .chunks(4)
                .zip(want.chunks(4))
                .filter(|(a, b)| a != b)
                .count();
            assert_eq!(differ, 0, "{name}-{frame}: pixels unlike the direct render");
            eprintln!("{name}-{frame}: the direct render's pixels");
            compared += 1;
        }
    }
    assert_eq!(compared, 11);
    std::fs::remove_dir_all(&dir).unwrap();
}
