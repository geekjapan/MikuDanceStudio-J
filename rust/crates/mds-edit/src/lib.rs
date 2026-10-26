//! Keyframe register, paste and delete over the `mds-formats` key pools.
//!
//! A port of the C++ editor: `src/model/key_registrars.cpp`,
//! `src/model/model_keyframe_edit.cpp`, and the paste and register handlers
//! in `src/window/frame_clipboard.cpp`, `command_frame_register.cpp` and
//! `command_frame_edit.cpp`. The operations keep the C++ record-level
//! behavior, quirks included: the search cursor shared by the three pools,
//! stale fields of freed records, the raw frame offset in the max-frame bump
//! of a bone key, and the writes through link `0` when a deleted key ended its
//! track. `tests/keypool_replay.rs` replays the `tools/keypool_check`
//! operation sequences and compares every pool state with the C++ harness.
//!
//! The pools must satisfy `KeyPool::validate_tracks` (a loaded file should be
//! checked once). On a pool that does not, an operation returns
//! [`Error::Corrupt`] or stops, instead of indexing out of bounds or looping.
//!
//! The fixed-axis twist correction calls the D3DX quaternion functions
//! through `mds-math`. The bone operations take an [`Extra`]: the bone
//! fields and UI state beyond [`Rig`] that the twist correction and the pose
//! of a bone with a rigid body read. An [`Extra`] without the bone returns
//! [`Error::Unsupported`] on those two paths.
//!
//! Not ported: undo and redo bookkeeping and the overflow message boxes (the
//! operations return [`Error::Full`]).

mod delete;
mod link;
mod register;

pub use link::{rebuild_interpolation, Link};
pub use register::{mirrored_bone, twist, BoneClip, BoneTarget, DisplayClip, MorphClip};

use mds_formats::key_pool::{KeyPool, BONE_KEY_CAPACITY, DISPLAY_KEY_CAPACITY, MORPH_KEY_CAPACITY};
use mds_formats::pmm::{BoneKey, DisplayKey, MorphKey};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// The pool has no free record. The C++ shows a message box and the
    /// operation changes nothing but the search cursor.
    Full { pool: &'static str, limit: u32 },
    /// A link or index points outside the pool or the model, or a chain
    /// does not end.
    Corrupt,
    /// A path of the C++ operation that this crate does not port.
    Unsupported(&'static str),
}

pub type Result<T> = std::result::Result<T, Error>;

/// What the editor reads of a bone. Names compare as C strings: up to the
/// first NUL.
#[derive(Clone, Debug)]
pub struct BoneInfo {
    pub name: Vec<u8>,
    /// Bone types 0, 1 and 2 (rotate+move, move, IK) store a position.
    pub writes_position: bool,
    /// Fixed-axis bones (type 8, or type 4 with the 0x400 flag) get a twist
    /// correction on paste, which needs [`BoneExtra::axis`].
    pub twist: bool,
    pub rigid_body: bool,
    /// Current pose, which "register" stores.
    pub rotation: [f32; 4],
    pub translation: [f32; 3],
}

impl BoneInfo {
    pub fn new(name: &str) -> Self {
        BoneInfo {
            name: name.as_bytes().to_vec(),
            writes_position: true,
            twist: false,
            rigid_body: false,
            rotation: [0.0, 0.0, 0.0, 1.0],
            translation: [0.0; 3],
        }
    }
}

#[derive(Clone, Debug)]
pub struct MorphInfo {
    pub name: Vec<u8>,
    pub value: f32,
}

#[derive(Clone, Debug)]
pub struct IkChain {
    pub bone: u32,
    pub enabled: u8,
}

/// One outside-parent selector (a `BoneOrderEntry`).
#[derive(Clone, Debug)]
pub struct Selector {
    pub bone: u32,
    pub linked_model: i32,
    pub linked_bone: i32,
}

/// The model as the editor reads it. Only the physics pose of
/// [`Tracks::register_bone_pose_with`] changes it.
#[derive(Clone, Debug)]
pub struct Rig {
    pub bones: Vec<BoneInfo>,
    pub morphs: Vec<MorphInfo>,
    pub ik_chains: Vec<IkChain>,
    pub selectors: Vec<Selector>,
    /// PMX model (`physicsMode == 2`). Only a PMX model registers morph 0.
    pub pmx: bool,
    /// `loadComplete`, which "register display key" stores as the visible flag.
    pub load_complete: u8,
    /// The "auto interpolation" checkbox (`kPhysicsFrameCheckbox`, 530):
    /// register and delete rebuild the position curves around a bone key.
    pub auto_interpolation: bool,
}

/// What the bone registrars read of a bone beyond [`BoneInfo`], and what the
/// register button changes.
#[derive(Clone, Debug, Default)]
pub struct BoneExtra {
    /// The twist axis of a fixed-axis bone: `BoneRecord::axis` for PMX, or
    /// the tail bone's position minus the bone's for PMD, which the
    /// registrar normalizes.
    pub axis: [f32; 3],
    /// `ikBackup`: the pose the physics step left, which "register" stores
    /// for a bone with a rigid body while physics drives it.
    pub physics_rotation: [f32; 4],
    pub physics_translation: [f32; 3],
    /// `BoneRecord::physicsDisabled`: physics does not drive the bone.
    pub physics_disabled: u8,
}

/// The state beyond [`Rig`] that the `*_with` operations read and change.
#[derive(Clone, Debug, Default)]
pub struct Extra {
    /// One per bone of the rig.
    pub bones: Vec<BoneExtra>,
    /// The physics checkbox (`kPhysicsCheckbox`, 499). "Register" sets the
    /// `physics_disabled` of a bone with a rigid body to its negation.
    pub physics_checkbox: bool,
    /// `PlaybackPhysicsMode`, which the register button passes as `mode`.
    pub physics_mode: i32,
}

/// The key pools of one model with the two fields next to them that the
/// operations touch.
#[derive(Clone, Debug)]
pub struct Tracks {
    pub bone: KeyPool<BoneKey>,
    pub morph: KeyPool<MorphKey>,
    pub display: KeyPool<DisplayKey>,
    /// `searchCursor`: one field shared by the three pools, so it can hold
    /// another pool's position.
    pub search_cursor: u32,
    /// `maxFrame`, the timeline end.
    pub max_frame: u32,
}

impl Tracks {
    /// The pools of a freshly loaded model (`pmx_load.cpp` pool tail and
    /// `ModelInitDefaults`): one head per bone and morph, one display head.
    pub fn new(rig: &Rig) -> Self {
        let bone_heads = (0..rig.bones.len()).map(|_| link::bone_head()).collect();
        let morph_heads = vec![MorphKey::default(); rig.morphs.len()];
        Tracks {
            bone: KeyPool::new(BONE_KEY_CAPACITY, bone_heads).expect("bone heads fit"),
            morph: KeyPool::new(MORPH_KEY_CAPACITY, morph_heads).expect("morph heads fit"),
            display: KeyPool::new(DISPLAY_KEY_CAPACITY, vec![DisplayKey::blank(rig)])
                .expect("display head fits"),
            search_cursor: 0,
            max_frame: 0,
        }
    }

    /// `ClearModelKeyMarks` on the three pools: no key is selected.
    pub fn clear_marks(&mut self) {
        link::clear_marks(&mut self.bone);
        link::clear_marks(&mut self.morph);
        link::clear_marks(&mut self.display);
    }

    /// `ResetBoneKeyCursor` (VA 0x4A4940): the first free record from the
    /// first non-head record.
    pub fn reset_bone_cursor(&mut self, rig: &Rig) {
        self.search_cursor = link::reset_cursor(&self.bone, rig.bones.len() as u32);
    }

    /// `ResetMorphKeyCursor` (VA 0x4A49A0).
    pub fn reset_morph_cursor(&mut self, rig: &Rig) {
        self.search_cursor = link::reset_cursor(&self.morph, rig.morphs.len() as u32);
    }

    /// `ResetDisplayKeyCursor` (VA 0x4A4A00).
    pub fn reset_display_cursor(&mut self) {
        self.search_cursor = link::reset_cursor(&self.display, 1);
    }
}
