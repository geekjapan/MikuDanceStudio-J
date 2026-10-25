//! The pieces of a PMM scene that drawing needs: the camera and light of a frame, and the pose
//! of a model from `mds-pose`.

use crate::{Camera, GroundShadow, Light, Pose, SelfShadow, Stage};
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

/// Whether the self-shadow track is in mode 2 at `frame`. Superseded: draw with `Frame::toon` set
/// and the self-shadow of [`stage_at`], which picks the toon as the golden images show it.
pub fn self_shadow_mode_2_at(pmm: &Pmm, frame: u32) -> bool {
    evaluate_self_shadow(&pmm.self_shadow, f64::from(frame)).is_some_and(|(mode, _)| mode == 2)
}

/// The [`Stage`] of the PMM at `frame`.
pub fn stage_at(pmm: &Pmm, frame: u32) -> Stage {
    Stage {
        self_shadow: evaluate_self_shadow(&pmm.self_shadow, f64::from(frame))
            .filter(|&(mode, _)| mode != 0)
            .map(|(mode, distance)| SelfShadow { mode, distance }),
        ground_shadow: (pmm.view.ground_shadow != 0).then_some(GroundShadow {
            ambient: pmm.physics.projected_shadow_ambient,
            translucent: pmm.physics.projected_shadow_blend != 0,
        }),
    }
}
