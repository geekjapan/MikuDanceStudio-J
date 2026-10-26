//! `mds_mmert::host` draws a model through its effect in the pose `mds-pose` gives it, not in its
//! bind pose: `chain8.pmx` of the mmegold `objects` scene with `objects.fx`, once as loaded and
//! once with every bone moved 5 units along x. The camera looks along -z (yaw pi), so +x is to
//! the left of the picture, 5 units there being about 168 pixels (distance 20, 30 degrees, 360
//! pixels high).

use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_math::Mat4;
use mds_mmert::emm::Assignment;
use mds_mmert::host::{Frame, Host, Source};
use mds_render::Camera;
use mds_scene::track::{evaluate_camera, evaluate_light, CameraMode, LightMode};

mod common;

const W: u32 = 640;
const H: u32 = 360;

/// The mean x of the pixels that are not the corner's colour.
fn mean_x(px: &[u8]) -> f32 {
    let bg = &px[..3];
    let xs: Vec<u32> = (0..W * H)
        .filter(|&i| &px[i as usize * 4..i as usize * 4 + 3] != bg)
        .map(|i| i % W)
        .collect();
    assert!(xs.len() > 1000, "the model covers {} pixels", xs.len());
    xs.iter().sum::<u32>() as f32 / xs.len() as f32
}

#[test]
fn a_posed_model_draws_in_its_pose() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let fixtures = common::fixtures();
    let pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    let pmx = Pmx::read(&std::fs::read(fixtures.join("chain8.pmx")).unwrap()).unwrap();
    let mut host = Host::new((W, H));
    host.add(&gpu, "chain8.pmx", Source::Pmx(&pmx), 1.0, |_| None)
        .unwrap();
    let c = evaluate_camera(&pmm.camera, 0.0, CameraMode::Playback).unwrap();
    let camera = Camera {
        target: c.position,
        rotation: c.rotation,
        distance: c.distance,
        fov_deg: c.fov,
        orthographic: false,
    };
    let light = evaluate_light(&pmm.light, 0.0, LightMode::Playback).unwrap();
    let assignments = [Assignment {
        effect: "objects.fx".into(),
        ..Assignment::default()
    }];
    let effects = fixtures.join("mme/effects");
    let resolve = |p: &str| effects.join(p);
    let mut posed = mds_pose::model::Model::from_pmx(pmm.models[0].slot, &pmx).unwrap();
    let mut draw = |posed: &mds_pose::model::Model| {
        let f = Frame {
            pmm: &pmm,
            poses: std::slice::from_ref(posed),
            camera: &camera,
            light,
            frame: 0,
            elapsed: 0.0,
            size: (W, H),
            assignments: &assignments,
            resolve: &resolve,
        };
        let mut log = Vec::new();
        let skipped = host.render(&gpu, &vk, &f, &mut log);
        assert!(skipped.is_empty(), "{skipped:?} {log:?}");
        host.target().unwrap().read(&gpu).unwrap()
    };
    for b in &mut posed.bones {
        b.mat_init = Mat4::IDENTITY;
    }
    let bind = mean_x(&draw(&posed));
    for b in &mut posed.bones {
        b.mat_init = Mat4::translation(5.0, 0.0, 0.0);
    }
    let moved = mean_x(&draw(&posed));
    let shift = bind - moved;
    assert!((150.0..190.0).contains(&shift), "moved {shift} pixels left");
}
