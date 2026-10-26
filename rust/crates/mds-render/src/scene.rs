//! The pieces of a PMM scene that drawing needs: the camera and light of a frame, and the pose
//! of a model from `mds-pose`.

use crate::{Camera, GroundShadow, Light, Pose, SelfShadow, Stage};
use mds_accessory::transform::{parent_bone_index, parent_model_slot, world_matrix, ParentBone};
use mds_accessory::AccessoryState;
use mds_formats::pmm::Pmm;
use mds_scene::track::{
    evaluate_accessory, evaluate_camera, evaluate_light, evaluate_self_shadow, CameraMode,
    LightMode,
};

/// The camera at `frame`, from the PMM camera track. The flag the PMM stores as "perspective"
/// reads 1 for an orthographic view in the golden scene (README of `tests/fixtures/rust/golden`).
/// `None` when the track cannot be evaluated.
pub fn camera_at(pmm: &Pmm, frame: u32) -> Option<Camera> {
    camera_with_parent_at(pmm, frame, CameraMode::Seek).map(|(camera, _)| camera)
}

/// The same evaluated camera with the attachment pair of its active key.
pub fn camera_with_parent_at(
    pmm: &Pmm,
    frame: u32,
    mode: CameraMode,
) -> Option<(Camera, [i32; 2])> {
    let c = evaluate_camera(&pmm.camera, f64::from(frame), mode)?;
    Some((
        Camera {
            target: c.position,
            rotation: c.rotation,
            distance: c.distance,
            fov_deg: c.fov,
            orthographic: c.perspective == 1,
        },
        [c.parent_model, c.parent_bone],
    ))
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
pub fn stage_at(pmm: &Pmm, frame: u32) -> Stage<'static> {
    Stage {
        accessories: &[],
        picture: None,
        shadow_map: Default::default(),
        self_shadow: evaluate_self_shadow(&pmm.self_shadow, f64::from(frame))
            .filter(|&(mode, _)| mode != 0)
            .map(|(mode, distance)| SelfShadow { mode, distance }),
        ground_shadow: (pmm.view.ground_shadow != 0).then_some(GroundShadow {
            ambient: pmm.physics.projected_shadow_ambient,
            translucent: pmm.physics.projected_shadow_blend != 0,
        }),
    }
}

/// The state of a PMM accessory at `frame` and its world matrix (row vectors, row-major), from the
/// accessory track and the bone it follows in `models` (posed, any order: found by slot). The
/// additive flag is the accessory record's. `None` when the track cannot be evaluated.
pub fn accessory_at(
    accessory: &mds_formats::pmm::Accessory,
    frame: u32,
    models: &[mds_pose::model::Model],
) -> Option<(AccessoryState, [f32; 16])> {
    let a = evaluate_accessory(&accessory.keys, accessory.slot, f64::from(frame))?;
    let state = AccessoryState {
        visible: a.visible != 0,
        position: a.position,
        rotation: a.rotation,
        scale: a.scale,
        parent_model: a.parent_model,
        parent_bone: a.parent_bone,
        shadow_enabled: a.shadow_enabled != 0,
        additive_blend: accessory.state.additive != 0,
        opacity: a.opacity,
    };
    let parent = parent_model_slot(state.parent_model)
        .and_then(|slot| models.iter().find(|m| usize::from(m.slot) == slot))
        .and_then(|m| m.bones.get(parent_bone_index(state.parent_bone)))
        .map(|b| ParentBone {
            position: b.position,
            matrix: b.mat_init,
        });
    let world = world_matrix(&state, parent.as_ref()).0;
    Some((state, world))
}
