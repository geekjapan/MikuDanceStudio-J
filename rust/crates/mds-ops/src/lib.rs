//! The bulk key operations of the editor's menus and dialogs, as pure
//! functions over a [`mds_formats::pmm::Pmm`] scene.
//!
//! A port of the C++ handlers in `src/window/command_file_menu.cpp`
//! (`CmdFileMenu`), `command_view_menu.cpp`, `command_dispatch.cpp`,
//! `frame_line_edit.cpp`, `misc_dialogs.cpp`, `frame_range_apply.cpp` and
//! `dialog_procs.cpp`, with `src/model/model_key_reduction.cpp`. The record
//! level work (register, delete marked, the search cursors) is `mds-edit`;
//! this crate adds what the handlers do around it. Each doc comment cites the
//! C++ lines it follows, and every test module says which lines its expected
//! pool states come from.
//!
//! # Operations
//!
//! "Oracle" is the `--mds-script` oracle of the script slice, which covers
//! the selection commands and the frame-line commands. Every other operation
//! needs a later script2 slice to be compared with the C++ binary; until
//! then the tests here (hand-derived from the C++) are its only check.
//!
//! | Menu | Operation | Function | Oracle |
//! |------|-----------|----------|--------|
//! | 217 | select all bone frames | [`select_all_bone_frames`] | script |
//! | 218 | select all display frames | [`select_all_display_frames`] | script |
//! | 219 | center position bias | [`center_position_bias`] | script2 (the brief's 217-220 range names it; the script command list does not) |
//! | 220 | select all morph frames | [`select_all_morph_frames`] | script |
//! | 222 | delete unused frames | [`remove_unused_keys`] | script2 |
//! | 225 | shift lip frames | [`shift_lip_frames`] | script2 |
//! | 226 | delete all lip frames | [`delete_lip_frames`] | script2 |
//! | 227 | random blinks | [`random_blinks`] | script2 |
//! | 228 | delete all eye frames | [`delete_eye_frames`] | script2 |
//! | 229 | register all facial frames | [`register_all_morph_frames`] | script2 |
//! | 230 | reset all morphs | [`reset_morphs`] | script2 |
//! | 231 | delete all eyebrow frames | [`delete_eyebrow_frames`] | script2 |
//! | 237 | select all camera frames | [`select_all_camera_frames`] | script |
//! | 238 | select all light frames | [`select_all_light_frames`] | script |
//! | 239 | select all self-shadow frames | [`select_all_self_shadow_frames`] | script |
//! | 240 | select all gravity frames | [`select_all_gravity_frames`] | script |
//! | 241 | select all accessory frames | [`select_all_accessory_frames`] | script |
//! | 242 | camera scale and add | [`multiply_camera_frames`] | script2 |
//! | 251 | bone scale and add | [`multiply_bone_frames`] | script2 |
//! | 252 | morph scale and add | [`multiply_morph_frames`] | script2 |
//! | 255 | insert bone/camera frame line | [`insert_bone_camera_frame_line`] | script |
//! | 256 | delete bone/camera frame line | [`delete_bone_camera_frame_line`] | script |
//! | 257 | insert facial/light frame line | [`insert_morph_light_frame_line`] | script |
//! | 258 | delete facial/light frame line | [`delete_morph_light_frame_line`] | script |
//! | 275 | physics ON/OFF conversion | [`set_physics_on_off`] | script2 |
//! | 424 | frame-range scale | [`scale_frame_range`] | script2 |
//!
//! # Conventions
//!
//! * Dialog inputs are parameters; a message box is an [`Error`] value, and
//!   the operation then changes nothing the C++ would not have changed.
//! * What the model file knows and a PMM does not (bone type and parent,
//!   morph type) is passed as [`ModelFacts`].
//! * The edit mode (bone or camera) is read from the scene; an operation
//!   called in the other mode returns [`Error::WrongMode`], as the handler
//!   returns at its mode gate.
//! * A pool that fills up mid-operation does not stop the loops that the C++
//!   does not stop; the first such error is returned at the end. Any other
//!   error ends the operation, and the operations that can fail half way run
//!   on a copy and commit it only on success.
//! * [`MsvcRand`] is the MSVC CRT `rand()` (the LCG
//!   `state = state * 214013 + 2531011`, result `(state >> 16) & 0x7fff`).
//!   The C application never calls `srand`, so the state starts at 1; the
//!   generator is one process-wide state, so the caller keeps one value and
//!   passes it to every user. The blink phase byte (`BlinkPhase`, also a
//!   global of the C++) is likewise a parameter.
//! * Float arithmetic follows the C++ expression: `f32` for the multiply
//!   dialogs and the frame-range product, a double product cast to `f32` and
//!   divided by 180 for degrees, and `mds_crtmath`/`mds_math` for the
//!   transcendental and matrix parts.
//!
//! # Where the result is not a valid pool
//!
//! Every operation leaves the pools satisfying
//! [`mds_formats::key_pool::KeyPool::validate_tracks`] except the following, which are the C++ behavior and are asserted as such
//! by the tests:
//!
//! * Menus 226, 228 and 231 (`PurgeMorphFrames`) free every key of a track
//!   but the last; the last key stays in its record with its frame, but no
//!   track reaches it any more.
//! * Menu 225 drops a key whose shifted frame is not positive by relinking
//!   the track head only, so the next key keeps a stale `previous`.
//!
//! # The `type` and `panel` fields
//!
//! The facial menus 225, 226, 228 and 231 select morphs with
//! `MorphRecord::type` where the morph's panel (the model editor's eyebrow,
//! eye, lip category) is clearly meant, and `PurgeMorphFrames` compares the
//! same byte. The port keeps the C++ field choice; [`ModelFacts::morph_type`]
//! carries whichever byte the caller reads from the model file, so the
//! discrepancy is one parameter to change.
//!
//! # Not ported
//!
//! Undo and redo bookkeeping (the document slice wraps these functions in
//! commands); the dialogs and message boxes themselves; automatic
//! interpolation after a bone edit and the fixed-axis (twist) bone paths,
//! which `mds-edit` reports as [`mds_edit::Error::Unsupported`]; the physics
//! reset flag set after a physics conversion; and the `FrameRangeStartFrame`
//! state the dialog keeps between uses.

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
