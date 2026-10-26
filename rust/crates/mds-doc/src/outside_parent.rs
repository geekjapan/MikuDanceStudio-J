//! The outside-parent dialog of button 442 (`IDD_OUTSIDE_PARENT`,
//! `SelectNavDlgProc`, `src/window/dialog_procs.cpp` 109-163, with
//! `src/window/dialog_select_ops.cpp`). The dialog edits a copy of the
//! selected model's selector records (`BoneOrderEntry`: bone, window, linked
//! model and bone, `pmm::Model::selector_bones` and `selector_pose`); its
//! combos are the caller's. Button 630 bakes one bone's pose for the parent
//! the combos show, button 632 writes the copy back as a display key, and
//! the close seeks.
//!
//! The bone matrices are those of the saved pose without physics
//! ([`crate::panel::posed_scene`]), where the C++ reads the frame loop's.

use crate::{model, not, panel, Document, Error, OutsideParent};
use mds_math::{Mat4, Quat};

/// `D3DXMatrixInverse`, which the C++ calls without checking the result.
fn inverse(m: &Mat4) -> Result<Mat4, Error> {
    m.inverse()
        .map(|(m, _)| m)
        .ok_or(not("a singular bone matrix"))
}

/// `D3DXVec3Transform`: `(p, 1) * m`.
fn transform(p: [f32; 3], m: &Mat4) -> [f32; 3] {
    let m = &m.0;
    std::array::from_fn(|c| p[0] * m[c] + p[1] * m[4 + c] + p[2] * m[8 + c] + m[12 + c])
}

impl Document {
    fn outside_parent_model(&self) -> Result<usize, Error> {
        if self.camera_mode() {
            return Err(not("the outside-parent dialog is a model-mode dialog"));
        }
        self.active_model()
    }

    /// [`crate::Command::ApplyOutsideParent`], `ApplyBoneAttach`
    /// (`dialog_select_ops.cpp` 382-460). With `X` the bone's matrix
    /// under the new parent (D3DX row-vector products):
    ///
    /// * none: `matInit · matInit(parent)⁻¹`, or `matInit` for a root bone;
    /// * ground: `matInit`;
    /// * a bone of a model: `matInit · (T(-p) · T(q) · matExtra(target))⁻¹`,
    ///   `p` the bone's rest position and `q` the target's.
    ///
    /// The translation becomes `p · X - p`, and the rotation that of `X`
    /// without its translation row.
    pub(crate) fn apply_outside_parent(
        &mut self,
        selector: u32,
        parent: OutsideParent,
    ) -> Result<(), Error> {
        let i = self.outside_parent_model()?;
        let (_, skeleton) = self.keyed()?;
        let mode = self.pmm.physics.playback_mode;
        let m = &self.pmm.models[i];
        let b = m
            .selector_bones
            .get(selector as usize)
            .and_then(|&b| usize::try_from(b).ok())
            .filter(|&b| b < m.bone_pose.len())
            .ok_or(not("no such selector bone"))?;
        let missing = || not("the model file is missing or does not match the PMM");
        let mut scene = panel::posed_scene(self);
        let pose = scene[i].take().ok_or_else(missing)?;
        let bone = pose.bones.get(b).ok_or_else(missing)?;
        let p = bone.position;
        let x = match parent {
            OutsideParent::None => match usize::try_from(bone.parent) {
                Ok(up) => {
                    let up = pose.bones.get(up).ok_or_else(missing)?;
                    Mat4::multiply(&bone.mat_init, &inverse(&up.mat_init)?)
                }
                Err(_) => bone.mat_init,
            },
            OutsideParent::Ground => bone.mat_init,
            OutsideParent::Bone { model, bone: t } => {
                let j = self
                    .pmm
                    .models
                    .iter()
                    .position(|m| m.slot == model)
                    .ok_or(not("no model in that slot"))?;
                let tpose = match j == i {
                    true => &pose,
                    false => scene[j].as_ref().ok_or_else(missing)?,
                };
                let target = tpose.bones.get(t as usize).ok_or(not("no such bone"))?;
                let q = target.position;
                let mut x = Mat4::multiply(&Mat4::translation(q[0], q[1], q[2]), &target.mat_extra);
                x = Mat4::multiply(&Mat4::translation(-p[0], -p[1], -p[2]), &x);
                Mat4::multiply(&bone.mat_init, &inverse(&x)?)
            }
        };
        let out = transform(p, &x);
        let mut r = x;
        r.0[12..15].fill(0.0);
        let frame = self.frame();
        let m = &mut self.pmm.models[i];
        let pose = &mut m.bone_pose[b];
        pose.translation = std::array::from_fn(|c| out[c] - p[c]);
        pose.rotation = Quat::from_matrix(&r).0;
        for (k, pose) in m.bone_pose.iter_mut().enumerate() {
            pose.flags[2] = u8::from(k == b);
        }
        let physics = model::Physics {
            checkbox: self.edit.physics_checkbox,
            mode,
        };
        let r = model::register_bones(
            m,
            &skeleton,
            &mut self.edit.models[i],
            self.edit.auto_interpolation,
            physics,
            frame,
        );
        self.bump_last_registered(i);
        self.edit.outside_parent_applied = true;
        r
    }

    /// [`crate::Command::RegisterOutsideParents`], `ResetModelSelection`
    /// (`dialog_select_ops.cpp` 334-376). The windows of the records stay;
    /// none and ground link bone 0 (`RebuildTargetBoneList`).
    pub(crate) fn register_outside_parents(
        &mut self,
        records: &[OutsideParent],
    ) -> Result<(), Error> {
        let i = self.outside_parent_model()?;
        let (_, skeleton) = self.keyed()?;
        if records.len() != self.pmm.models[i].selector_pose.len() {
            return Err(not("not one record per selector"));
        }
        let mut links = Vec::with_capacity(records.len());
        for r in records {
            links.push(match *r {
                OutsideParent::None => [-1, 0],
                OutsideParent::Ground => [-2, 0],
                OutsideParent::Bone { model, bone } => {
                    if !self.pmm.models.iter().any(|m| m.slot == model) {
                        return Err(not("no model in that slot"));
                    }
                    [i32::from(model), bone as i32]
                }
            });
        }
        let frame = self.frame();
        let m = &mut self.pmm.models[i];
        for (s, l) in m.selector_pose.iter_mut().zip(links) {
            s[2..].copy_from_slice(&l);
        }
        let r = model::register_display(m, &skeleton, &mut self.edit.models[i], frame);
        self.bump_last_registered(i);
        self.edit.outside_parent_applied = true;
        r
    }
}
