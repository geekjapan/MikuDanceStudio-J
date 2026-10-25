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

/// Whether the self-shadow track is in mode 2 at `frame`. In the golden images the toon ramp darkens
/// the faces turned from the light (down to 0.8) from the frame where this becomes true (frame 300
/// of the fixture) and not while the track is in mode 1. The render takes the mode as the switch
/// (`Frame::toon`); the four golden frames, which all match with it, cannot rule out a switch on
/// the light instead. The light of the fixture does not step at frame 300: it fades from its key
/// at 0 to its key at 300 and stays (frame 150 has the half-way light, still without the darker
/// ramp), so a light-driven switch would have to be a threshold on that fade that happens to fall
/// between frames 150 and 300. Only a scene whose light and self-shadow keys sit at different
/// frames can tell.
pub fn self_shadow_mode_2_at(pmm: &Pmm, frame: u32) -> bool {
    evaluate_self_shadow(&pmm.self_shadow, f64::from(frame)).is_some_and(|(mode, _)| mode == 2)
}
