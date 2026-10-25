//! The per-model undo and redo rings of `src/model/model_keyframe_edit.cpp`
//! (`UndoModelEdit` VA 0x004A1870, `RedoModelEdit` VA 0x004A2490) and the
//! button and Ctrl+Z/Ctrl+X tails around them (`command_frame_edit.cpp`
//! 400/401, `key_ladder.cpp`).
//!
//! An entry holds the saved pose of some bones and, for key edits, the bone
//! key records the edit touched as they were before it (`AppendBoneKeyToUndo`
//! order is irrelevant: each index is held once). A record that was never
//! used is `None`.

use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{BoneKey, Model};

/// Ring depth.
pub const SLOTS: usize = 30;

/// `BonePoseSnapshot`: one bone of the saved pose and its
/// `bonePhysicsState` byte (the "edited, not registered" mark).
#[derive(Clone, Debug, PartialEq)]
pub struct PoseSnapshot {
    pub bone: u32,
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
    pub edited: u8,
}

/// `UndoOperation`, without `ChainedBoneKeys` (range scaling is not ported).
#[derive(Clone, Debug, Default)]
pub enum Entry {
    #[default]
    Empty,
    /// `PushBoneEditUndo` (VA 0x0042D6E0): the selected bones before a pose
    /// edit.
    BonePose(Vec<PoseSnapshot>),
    /// A key edit: every bone's pose, the touched records, and the frame.
    BoneKeys {
        frame: u32,
        pose: Vec<PoseSnapshot>,
        keys: Vec<(u32, Option<BoneKey>)>,
    },
    /// `SnapshotPoseBeforeFrameChange` (VA 0x004A0080): every bone's pose and
    /// the frame left.
    BonePoseWithFrame { frame: u32, pose: Vec<PoseSnapshot> },
}

#[derive(Clone, Debug, Default)]
pub struct History {
    pub undo: [Entry; SLOTS],
    /// Only `Empty`, `BonePose` and `BoneKeys` (with an empty pose: redo
    /// does not restore the pose, the C++ re-seeks instead).
    pub redo: [Entry; SLOTS],
    pub cursor: usize,
    pub latest: usize,
    /// `undoDirty` / `redoDirty`, which enable the buttons and Ctrl+Z/X.
    pub undo_dirty: bool,
    pub redo_dirty: bool,
}

/// The saved pose of `bones` as an undo snapshot.
pub fn snapshot(m: &Model, bones: impl Iterator<Item = usize>) -> Vec<PoseSnapshot> {
    bones
        .map(|i| {
            let p = &m.bone_pose[i];
            PoseSnapshot {
                bone: i as u32,
                translation: p.translation,
                rotation: p.rotation,
                edited: p.flags[1],
            }
        })
        .collect()
}

/// `CaptureAndApplyPose`: returns what it overwrites.
fn apply_pose(m: &mut Model, pose: &[PoseSnapshot]) -> Vec<PoseSnapshot> {
    let before = snapshot(m, pose.iter().map(|s| s.bone as usize));
    for s in pose {
        let p = &mut m.bone_pose[s.bone as usize];
        p.translation = s.translation;
        p.rotation = s.rotation;
        p.flags[1] = s.edited;
    }
    before
}

/// Puts each record back; returns what it overwrites.
fn apply_keys(
    pool: &mut KeyPool<BoneKey>,
    keys: &[(u32, Option<BoneKey>)],
) -> Vec<(u32, Option<BoneKey>)> {
    let heads = pool.heads().len() as u32;
    keys.iter()
        .map(|(i, k)| {
            let before = pool.get(*i).cloned();
            match k {
                Some(k) if *i < heads => pool.heads_mut()[*i as usize] = k.clone(),
                Some(k) => {
                    pool.insert(*i, k.clone());
                }
                None => {
                    pool.remove(*i);
                }
            }
            (*i, before)
        })
        .collect()
}

impl History {
    /// `AdvanceUndo` and the store of a new entry; disables redo.
    pub fn push(&mut self, entry: Entry) {
        self.cursor = (self.cursor + 1) % SLOTS;
        self.latest = self.cursor;
        self.undo[self.cursor] = entry;
        self.undo_dirty = true;
        self.redo_dirty = false;
    }

    /// `UndoModelEdit` and the button tail. Returns the frame to move to.
    pub fn undo(&mut self, m: &mut Model) -> Option<u32> {
        let c = self.cursor;
        let mut frame = None;
        match std::mem::take(&mut self.undo[c]) {
            Entry::Empty => {
                self.undo_dirty = false;
            }
            entry => {
                self.redo[c] = match &entry {
                    Entry::BonePose(pose) => Entry::BonePose(apply_pose(m, pose)),
                    Entry::BonePoseWithFrame { frame: f, pose } => {
                        frame = Some(*f);
                        Entry::BonePose(apply_pose(m, pose))
                    }
                    Entry::BoneKeys {
                        frame: f,
                        pose,
                        keys,
                    } => {
                        frame = Some(*f);
                        apply_pose(m, pose);
                        Entry::BoneKeys {
                            frame: *f,
                            pose: Vec::new(),
                            keys: apply_keys(&mut m.bone_keys, keys),
                        }
                    }
                    Entry::Empty => unreachable!(),
                };
                self.undo[c] = entry;
                self.cursor = (c + SLOTS - 1) % SLOTS;
            }
        }
        if matches!(self.undo[self.cursor], Entry::Empty) || self.cursor == self.latest {
            self.undo_dirty = false;
        }
        self.redo_dirty = true;
        frame
    }

    /// `RedoModelEdit` and the button tail. Returns the frame to move to.
    pub fn redo(&mut self, m: &mut Model) -> Option<u32> {
        self.cursor = (self.cursor + 1) % SLOTS;
        let c = self.cursor;
        let mut frame = None;
        match &self.redo[c] {
            Entry::Empty => self.redo_dirty = false,
            Entry::BonePose(pose) => {
                apply_pose(m, pose);
            }
            Entry::BoneKeys { keys, .. } => {
                apply_keys(&mut m.bone_keys, keys);
                frame = match &self.undo[c] {
                    Entry::BoneKeys { frame, .. } | Entry::BonePoseWithFrame { frame, .. } => {
                        Some(*frame)
                    }
                    _ => None,
                };
            }
            Entry::BonePoseWithFrame { .. } => unreachable!("redo holds no frame entries"),
        }
        if self.cursor == self.latest {
            self.redo_dirty = false;
        }
        self.undo_dirty = true;
        frame
    }
}
