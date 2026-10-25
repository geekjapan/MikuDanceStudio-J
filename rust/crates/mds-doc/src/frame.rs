//! The physics of the frame loop around the document: what one
//! `FrameDriver` pump (`src/app/frame_driver.cpp`) does to the bones while
//! playback is stopped, through `mds_physics::PhysicsScene::tick`. The
//! document never stores this state; the pump writes back what the C++
//! keeps in each `BoneRecord`: the pose after the physics readback (which
//! zeroes the translation of a bone whose body follows the bone position)
//! and `ikBackup`, the physics pose that "register" and "save pose" read
//! ([`crate::model::ModelEdit::physics_pose`]).
//!
//! The world is built (`PhysicsScene::open`, the PMM load) whenever the set
//! of model slots changes; the C++ adds the bodies of an added model to the
//! world it has. A pump with no model does nothing. Gate A of
//! `PhysicsFrame` is taken as open: the idle-physics suppress toggle (menu
//! 299) is off at start-up, so every pump runs physics.

use crate::Document;
use mds_physics::PhysicsScene;
use mds_pose::model::Model;

#[derive(Default)]
pub struct FrameLoop {
    scene: Option<PhysicsScene>,
    slots: Vec<u8>,
}

impl FrameLoop {
    /// One pump of `delta_time` seconds. `read` maps a model path as stored
    /// in the PMM to the file bytes, for a rebuilt world.
    pub fn pump(
        &mut self,
        doc: &mut Document,
        delta_time: f32,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<(), String> {
        let slots: Vec<u8> = doc.pmm.models.iter().map(|m| m.slot).collect();
        if slots != self.slots || self.scene.is_none() {
            self.scene = None;
            if !slots.is_empty() {
                // The load requests its own settle.
                self.scene = Some(PhysicsScene::open(&doc.pmm, read)?);
            }
            self.slots = slots;
        }
        let Some(ps) = self.scene.as_mut() else {
            doc.edit.physics_reset_pending = false;
            return Ok(());
        };
        let mode = i32::from(doc.pmm.physics.playback_mode);
        ps.scene.physics_mode = mode;
        for (sm, dm) in ps.scene.models.iter_mut().zip(&doc.pmm.models) {
            let before: Vec<u8> = sm.bones.iter().map(|b| b.physics_disabled).collect();
            sm.apply_pmm(dm)?;
            // `NotifyBonePhysicsMode`, which the registrars and the seek call
            // when they change the flag in mode 2 or 3.
            for (b, old) in before.into_iter().enumerate() {
                let new = sm.bones[b].physics_disabled;
                if mode >= 2 && sm.bones[b].has_rigid_body != 0 && new != old {
                    Model::notify_bone_physics_mode(&mut sm.rigids, b, new);
                }
            }
        }
        if std::mem::take(&mut doc.edit.physics_reset_pending) {
            ps.reset();
        }
        ps.tick(delta_time)?;
        let models = doc.pmm.models.iter_mut().zip(&mut doc.edit.models);
        for (sm, (dm, e)) in ps.scene.models.iter().zip(models) {
            for (p, b) in dm.bone_pose.iter_mut().zip(&sm.bones) {
                p.translation = b.trans;
                p.rotation = b.rot_quat;
            }
            let backup = |k: [f32; 7]| ([k[3], k[4], k[5], k[6]], [k[0], k[1], k[2]]);
            e.physics_pose = Some(sm.bones.iter().map(|b| backup(b.ik_backup)).collect());
        }
        Ok(())
    }
}
