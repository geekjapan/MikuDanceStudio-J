//! The pieces of a PMM scene that drawing needs: the camera and light of a frame, and the pose
//! of a model from `mds-pose`.

use crate::{Camera, Light, Pose};
use mds_formats::pmm::Pmm;
use mds_scene::track::{
    evaluate_camera, evaluate_light, evaluate_self_shadow, CameraMode, LightMode,
};

/// The camera at `frame`, from the PMM camera track. The flag the PMM stores as "perspective"
/// reads 1 for an orthographic view in the golden scene (README of `tests/fixtures/rust/golden`).
/// `None` when the track cannot be evaluated.
pub fn camera_at(pmm: &Pmm, frame: u32) -> Option<Camera> {
    let c = evaluate_camera(&pmm.camera, f64::from(frame), CameraMode::Seek)?;
    Some(Camera {
        target: c.position,
        rotation: c.rotation,
        distance: c.distance,
        fov_deg: c.fov,
        orthographic: c.perspective == 1,
    })
}

/// The light at `frame`, from the PMM light track.
pub fn light_at(pmm: &Pmm, frame: u32) -> Option<Light> {
    let l = evaluate_light(&pmm.light, f64::from(frame), LightMode::FrameSeek)?;
    Some(Light {
        color: [l[0], l[1], l[2]],
        direction: [l[3], l[4], l[5]],
    })
}

/// The pose a model has after `mds-pose` stepped it: the final bone matrices and the morph values.
pub fn pose_of(model: &mds_pose::model::Model) -> Pose {
    Pose {
        skin: model.bones.iter().map(|b| b.mat_init.0).collect(),
        morphs: model.morphs.iter().map(|m| m.value).collect(),
    }
}

/// Whether the toon ramp applies at `frame`. The golden images show it darkening the faces turned
/// from the light only from the frame where the self-shadow key turns to mode 2 (frame 300 of the
/// fixture) and not before, under mode 1. The light key changes at the same frame, so one scene
/// cannot say which of the two switches it; this follows the self-shadow mode.
pub fn toon_at(pmm: &Pmm, frame: u32) -> bool {
    evaluate_self_shadow(&pmm.self_shadow, f64::from(frame)).is_some_and(|(mode, _)| mode == 2)
}
