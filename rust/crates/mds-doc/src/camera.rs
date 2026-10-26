//! Camera transition inputs independent of rendering.
use crate::{Document, Error};
use mds_math::Mat4;

#[derive(Clone, Copy, Debug)]
pub struct CameraBone {
    pub mat_init: Mat4,
    pub position: [f32; 3],
}
impl CameraBone {
    pub fn point(self) -> [f32; 3] {
        let (m, p) = (self.mat_init.0, self.position);
        std::array::from_fn(|c| m[c] * p[0] + m[4 + c] * p[1] + m[8 + c] * p[2] + m[12 + c])
    }
    pub(crate) fn detach_point(self) -> [f32; 3] {
        let (m, p) = (self.mat_init.0.map(f64::from), self.position.map(f64::from));
        std::array::from_fn(|c| {
            (p[1] * m[4 + c] + p[0] * m[c] + p[2] * m[8 + c] + m[12 + c]) as f32
        })
    }
}
#[derive(Clone, Copy, Debug, Default)]
pub struct CameraAnchors {
    pub parent: Option<CameraBone>,
    pub selected_root: Option<[f32; 3]>,
    pub selected_bone: Option<CameraBone>,
    pub selected_bone_negative: bool,
}
#[derive(Clone, Copy, Debug)]
pub enum CameraPoseRequest {
    Current,
    AfterModelLoad { slot: u8 },
    AfterFrameSeek,
}
pub type CameraPoseProvider<'a> =
    dyn FnMut(&Document, CameraPoseRequest) -> Result<CameraAnchors, Error> + 'a;

pub fn camera_anchors(doc: &Document, models: &[mds_pose::model::Model]) -> CameraAnchors {
    let p = &doc.pmm;
    let bone = |b: &mds_pose::model::Bone| CameraBone {
        mat_init: b.mat_init,
        position: b.position,
    };
    let selected = models.iter().find(|m| m.slot == p.selected_model_slot);
    let index = doc
        .active()
        .map_or(-1, |i| p.models[i].selection.selected_bone);
    CameraAnchors {
        parent: models
            .iter()
            .find(|m| i32::from(m.slot) == p.appearance.camera_parent_model)
            .and_then(|m| m.bones.get(p.appearance.camera_parent_bone.max(0) as usize))
            .map(bone),
        selected_root: selected
            .and_then(|m| m.bones.get(m.center_bone))
            .map(|b| b.mat_init.0[12..15].try_into().unwrap()),
        selected_bone: selected
            .and_then(|m| m.bones.get(index.max(0) as usize))
            .map(bone),
        selected_bone_negative: index < 0,
    }
}
pub(crate) fn saved_camera_anchors(
    doc: &Document,
    _: CameraPoseRequest,
) -> Result<CameraAnchors, Error> {
    let models: Vec<_> = crate::panel::posed_scene(doc)
        .into_iter()
        .flatten()
        .collect();
    Ok(camera_anchors(doc, &models))
}
