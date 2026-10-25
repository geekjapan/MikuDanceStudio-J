//! The bulk key operations of the menus and dialogs as document commands:
//! `mds-ops` does the pool work, this module adds the model facts from the
//! file, the undo entry, and the refresh tail of each C++ handler.

use crate::history::{snapshot, Entry};
use crate::model::{self, Skeleton};
use crate::{not, refresh, Document, Error, ModelFile};
use mds_formats::pmm;
use mds_ops::{BoneFacts, ModelFacts};
use mds_pose::model::Model as PoseModel;

/// `mds_ops::Error` as a document error.
pub(crate) fn ops(e: mds_ops::Error) -> Error {
    match e {
        mds_ops::Error::Edit(e) => Error::Edit(e),
        mds_ops::Error::WrongMode => not("the menu is grayed out in this edit mode"),
        mds_ops::Error::NoModel => not("no model in the selected slot"),
        mds_ops::Error::NoBlinkMorph => {
            not("the model has no morph named まばたき (a message box)")
        }
        mds_ops::Error::EmptyRange => not("the end frame is not after the start frame"),
        mds_ops::Error::ScaleOutOfRange => not("the scale is below 1e-5 or exactly 1"),
        e => Error::Format(format!("{e:?}")),
    }
}

/// What the C++ bone and morph records hold beyond the PMM: the bone types
/// and parents the loaders leave, the twist axes, and `MorphRecord::type`,
/// which the PMX loader (`src/model/pmx_load.cpp`) fills with the PMX morph
/// kind and the PMD loader leaves 0.
pub(crate) fn facts(file: &ModelFile, m: &pmm::Model, s: &Skeleton) -> Result<ModelFacts, Error> {
    let pose = match file {
        ModelFile::Pmx(p) => PoseModel::from_pmx(m.slot, p),
        ModelFile::Pmd(p) => PoseModel::from_pmd(m.slot, p),
        ModelFile::Missing => return Err(not("the model file is missing")),
    }
    .map_err(Error::Format)?;
    let morph_type = match file {
        ModelFile::Pmx(p) => p.morphs.iter().map(|m| m.kind).collect(),
        _ => vec![0; m.morph_names.len()],
    };
    Ok(ModelFacts {
        bones: pose
            .bones
            .iter()
            .zip(&s.axes)
            .map(|(b, &axis)| BoneFacts {
                parent: b.parent,
                kind: b.kind,
                flags: b.flags,
                rigid_body: b.has_rigid_body != 0,
                axis,
            })
            .collect(),
        morph_type,
        pmx: pose.pmx,
    })
}

/// `RegisterBoneUndoSnapshot` (`src/window/misc_dialogs.cpp` 419-470):
/// when any bone key is marked, one `BoneKeys` entry with every bone's pose
/// and a copy of every marked record.
pub(crate) fn marked_undo(m: &pmm::Model, frame: u32) -> Option<Entry> {
    let pool = &m.bone_keys;
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    let keys: Vec<_> = heads
        .chain(pool.records().iter().map(|(i, k)| (*i, k)))
        .filter(|(_, k)| k.allocated != 0)
        .map(|(i, k)| (i, Some(k.clone())))
        .collect();
    (!keys.is_empty()).then(|| Entry::BoneKeys {
        frame,
        pose: snapshot(m, 0..m.bone_pose.len()),
        keys,
    })
}

impl Document {
    /// The selected model in model mode with its facts, for an `mds-ops`
    /// call.
    pub(crate) fn ops_model(&mut self) -> Result<(usize, ModelFacts), Error> {
        if self.camera_mode() {
            return Err(not("the menu is grayed out in camera mode"));
        }
        let (i, s) = self.keyed()?;
        let f = facts(&self.models[i], &self.pmm.models[i], &s)?;
        Ok((i, f))
    }

    /// `SeekModelFrame` of model `i` at the current frame.
    pub(crate) fn seek(&mut self, i: usize) {
        let (frame, mode) = (self.frame(), self.pmm.physics.playback_mode);
        refresh::seek_model(&mut self.pmm.models[i], &self.models[i], frame, mode);
    }

    /// Pushes [`marked_undo`] of model `i`.
    pub(crate) fn push_marked_undo(&mut self, i: usize) {
        if let Some(e) = marked_undo(&self.pmm.models[i], self.frame()) {
            self.edit.models[i].history.push(e);
        }
    }

    /// The undo entry of `ApplyPhysicsOnOff` (`misc_dialogs.cpp` 652-740):
    /// every bone's pose and the marked records of the rigid-body tracks,
    /// when there is one.
    pub(crate) fn push_physics_undo(&mut self, i: usize, f: &ModelFacts) {
        let m = &self.pmm.models[i];
        let pool = &m.bone_keys;
        let mut keys = std::collections::BTreeMap::new();
        for (bone, _) in f.bones.iter().enumerate().filter(|(_, b)| b.rigid_body) {
            let mut cur = bone as u32;
            for _ in 0..=pool.records().len() {
                let Some(k) = pool.get(cur) else { break };
                if k.allocated != 0 {
                    keys.insert(cur, Some(k.clone()));
                }
                if k.next == 0 {
                    break;
                }
                cur = k.next;
            }
        }
        if keys.is_empty() {
            return;
        }
        let e = Entry::BoneKeys {
            frame: self.frame(),
            pose: snapshot(m, 0..m.bone_pose.len()),
            keys: keys.into_iter().collect(),
        };
        self.edit.models[i].history.push(e);
    }

    /// Menu 222 (`command_file_menu.cpp` 1118-1145): the marks of
    /// `MarkRedundantModelKeys`, then `DeleteMarkedKeyframes` as the delete
    /// button runs it (undo entry, automatic interpolation, seek).
    pub(crate) fn remove_unused(&mut self) -> Result<u32, Error> {
        let (i, f) = self.ops_model()?;
        let n = mds_ops::mark_unused_keys(&mut self.pmm, &f).map_err(ops)?;
        let (_, s) = self.keyed()?;
        let auto = self.edit.auto_interpolation;
        let frame = self.frame();
        model::delete(
            &mut self.pmm.models[i],
            &s,
            &mut self.edit.models[i],
            auto,
            frame,
        )?;
        self.seek(i);
        Ok(n)
    }
}
