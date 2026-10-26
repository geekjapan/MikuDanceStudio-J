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

#[derive(Clone, Copy, Debug)]
pub struct CameraFrame {
    pub target: [f32; 3],
    pub rotation: [[f32; 3]; 3],
    pub distance: f32,
    pub fov_deg: f32,
    pub orthographic: bool,
    pub offset: [f32; 2],
}
impl Document {
    /// One native SetupFrameWorldTransform boundary after the live pose pass.
    pub fn prepare_camera_frame(&mut self, anchors: CameraAnchors, playing: bool) -> CameraFrame {
        let p = &mut self.pmm;
        let a = &mut p.appearance;
        let camera_view = p.settings.options[0] != 0
            || a.follow_camera != 0
                && (playing
                    || a.camera_parent_model >= 0
                        && a.camera_parent_model == i32::from(p.selected_model_slot));
        let target = if camera_view {
            if let Some(parent) = anchors.parent {
                p.camera_state.copy_within(..3, 3);
                parent.point()
            } else {
                p.camera_state[..3].try_into().unwrap()
            }
        } else {
            match p.timeline.camera_reference_mode {
                1 => anchors.selected_root,
                2 if !anchors.selected_bone_negative => anchors.selected_bone.map(|b| b.point()),
                _ => None,
            }
            .unwrap_or([0.0; 3])
        };
        let mut basis = Mat4::IDENTITY;
        if a.follow_camera != 0 || p.settings.options[0] != 0 {
            if let Some(parent) = anchors.parent.filter(|_| a.suppress_camera_transform == 0) {
                for row in 0..3 {
                    for col in 0..3 {
                        basis.0[row * 4 + col] = parent.mat_init.0[col * 4 + row];
                    }
                }
            } else {
                a.camera_attachment_basis = basis.0;
            }
        } else {
            basis = Mat4(a.camera_attachment_basis);
        }
        let s = &p.camera_state;
        let rotation = Mat4::multiply(
            &basis,
            &Mat4::multiply(
                &Mat4::multiply(&Mat4::rotation_y(s[7]), &Mat4::rotation_x(s[6])),
                &Mat4::rotation_z(s[8]),
            ),
        );
        CameraFrame {
            target,
            rotation: std::array::from_fn(|i| std::array::from_fn(|j| rotation.0[i * 4 + j])),
            distance: s[5],
            fov_deg: p.settings.camera_fov,
            orthographic: p.camera_perspective != 0,
            offset: [s[3], s[4]],
        }
    }
}

/// Editable native PMM controls, never a composed render camera.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CameraControls {
    pub target: [f32; 3],
    pub rotation: [f32; 3],
    pub distance: f32,
    pub fov_deg: f32,
    pub orthographic: bool,
}
impl Document {
    pub fn camera_controls(&self) -> CameraControls {
        let p = &self.pmm;
        let s = p.camera_state;
        CameraControls {
            target: [s[0], s[1], s[2]],
            rotation: [s[6], s[7], s[8]],
            distance: s[5],
            fov_deg: p.settings.camera_fov,
            orthographic: p.camera_perspective != 0,
        }
    }
}
impl From<CameraControls> for crate::Command {
    fn from(c: CameraControls) -> Self {
        Self::SetCamera {
            position: c.target,
            rotation: c.rotation,
            distance: c.distance,
            fov: c.fov_deg,
            perspective: c.orthographic,
        }
    }
}
