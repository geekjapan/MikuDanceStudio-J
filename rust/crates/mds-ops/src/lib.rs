//! DOC PLACEHOLDER

mod bias;
mod blink;
mod facial;
mod frame_line;
mod model;
mod multiply;
mod pool;
mod range;
mod select;
mod unused;

pub use bias::{center_position_bias, set_physics_on_off};
pub use blink::{random_blinks, MsvcRand};
pub use facial::{
    delete_eye_frames, delete_eyebrow_frames, delete_lip_frames, register_all_morph_frames,
    reset_morphs, shift_lip_frames,
};
pub use frame_line::{
    delete_bone_camera_frame_line, delete_morph_light_frame_line, insert_bone_camera_frame_line,
    insert_morph_light_frame_line,
};
pub use model::{active_model, BoneFacts, ModelFacts};
pub use multiply::{
    multiply_bone_frames, multiply_camera_frames, multiply_morph_frames, BoneScale, CameraScale,
};
pub use range::{scale_frame_range, RangeScale};
pub use select::{
    select_all_accessory_frames, select_all_bone_frames, select_all_camera_frames,
    select_all_display_frames, select_all_gravity_frames, select_all_light_frames,
    select_all_morph_frames, select_all_self_shadow_frames,
};
pub use unused::remove_unused_keys;

/// Why an operation did not run, or did not finish.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// The record-level register or delete refused (a full pool, or a path
    /// `mds-edit` does not port).
    Edit(mds_edit::Error),
    /// The scene has no model in the selected slot.
    NoModel,
    /// A link or index points outside its pool, a chain does not end, or the
    /// model's tables disagree with its pools.
    Corrupt,
    /// The handler returns at its mode gate and changes nothing: the
    /// operation belongs to the other edit mode (`settings.options[0]`).
    WrongMode,
    /// Menu 227 shows "this model has not facial motion of 'blink'" and
    /// stops.
    NoBlinkMorph,
    /// Menu 424 returns when the end frame is not past the start frame.
    EmptyRange,
    /// Menu 424 returns when the scale is below 1e-5 or exactly 1.
    ScaleOutOfRange,
}

pub type Result<T> = std::result::Result<T, Error>;

impl From<mds_edit::Error> for Error {
    fn from(e: mds_edit::Error) -> Self {
        Error::Edit(e)
    }
}
