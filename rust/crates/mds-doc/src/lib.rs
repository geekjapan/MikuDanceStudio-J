//! The editable state of the application: a PMM scene, the model files it
//! names, and the undo history, edited only through [`Command`]s.
//!
//! # Data shape
//!
//! * [`Document::pmm`] is the scene, `mds_formats::pmm::Pmm`, as read. It
//!   holds everything `SaveSceneFile` (`src/io/pmm_save.cpp`) writes: the key
//!   pools, the saved current pose of each model, the camera, light,
//!   accessory, gravity and self-shadow state, and the timeline. Saving is
//!   [`Document::save`]: [`save::normalize`], then `Pmm::write`.
//! * [`Document::models`] runs parallel to `pmm.models`: the parsed PMX or
//!   PMD of each model path, or [`ModelFile::Missing`]. The C++ loader drops
//!   a model whose file it cannot open; the document keeps the PMM record,
//!   so a missing file still saves, and refuses only the commands that need
//!   the bone flags of the file. Accessory files are not read (slice
//!   `accessory`); the PMM accessory records are kept.
//! * [`Document::edit`] is the edit state the C++ keeps outside the file:
//!   the per-model `searchCursor` and undo rings, the clipboard, the
//!   self-shadow mode radio, and the "auto interpolation" checkbox (530).
//! * Physics and render state are never stored. The PMM's saved pose block
//!   is the pose the user edits and "register" stores; a frame change, a
//!   paste, a delete and a motion load re-evaluate it from the keys
//!   (`SeekModelFrame`, through `mds-pose`), as the C++ handlers do.
//!
//! # Commands
//!
//! Every edit is one [`Command`], applied by [`Document::apply`]; undo and
//! redo are commands too. One line of the C++ `--mds-script` maps to one
//! command. The C++ that each command ports is named on its variant.
//! Model-mode key commands act on the selected model
//! (`pmm.selected_model_slot`); camera mode is `pmm.settings.options[0]`.
//!
//! * Bone, morph and display keys go through `mds-edit`, which matches the
//!   C++ record by record. `mds-doc` adds what `mds-edit` leaves out: the
//!   undo bookkeeping, the mark clearing of each button, the
//!   `lastRegisteredFrame` updates, and the paste orchestration.
//! * Camera, light, self-shadow, gravity and accessory keys are ported here
//!   ([`global`]): `src/model/global_key_registration.cpp`,
//!   `src/window/ui_frame_refresh.cpp` (`RegisterSelfShadowState`),
//!   `src/render/accessory.cpp` (`RegisterAccessoryKey`),
//!   `src/window/accessory_paste.cpp`, and the camera branch of
//!   `DeleteMarkedKeyframes` (`src/window/command_frame_edit.cpp`).
//! * Undo and redo ([`history`]) keep the C++ rings of
//!   `include/mikudancestudio/undo_layout.hpp`: per model, 30 undo and 30
//!   redo slots, a cursor, the latest cursor, and the two dirty flags that
//!   gate Ctrl+Z and Ctrl+X. Only bone keys and the saved bone pose are
//!   undoable, as in the C++: morph, display and camera-mode edits push
//!   nothing.
//!
//! # Saving
//!
//! [`save::normalize`] applies what `pmm_save.cpp` changes against a plain
//! round trip of the scene as read:
//!
//! * The header is `"Polygon Movie maker 0002"`, NUL, and zeros (bytes
//!   25..29 are pinned to zero).
//! * Every byte the C++ writes as `x != 0` becomes 0 or 1: the seven option
//!   flags, `loadComplete`, the display-group flags, the `allocated`,
//!   `physicsDisabled`, `visible` and IK bytes of the model keys, the three
//!   saved-pose flags of each bone, the IK switches, `postLoadFlag2`, the
//!   toon flag, the camera key `perspective` and every key `selected`, the
//!   camera perspective, the accessory shadow and additive flags, the three
//!   playback flags, the wave, picture, FPS, grid, ground-shadow,
//!   shadow-blend and gravity-noise flags, the gravity key noise flag, the
//!   self-shadow enabled byte, and the black-background, follow-camera,
//!   suppress-transform and floor flags. `cameraReferenceMode`, the
//!   physics mode, the self-shadow key mode, the AVI flag and the display
//!   order stay raw.
//! * Names are written to their first NUL (`strlen`).
//! * The repeated display-group count is the group count.
//! * Model paths, accessory list names and accessory paths share one
//!   256-byte scratch buffer: zeros after the NUL on first use, the residue
//!   of the previous string afterwards, and an empty path writes the buffer
//!   unchanged. The wave, AVI and picture paths are zeroed first. Accessory
//!   names are saved whole, with what the record holds after the NUL
//!   ([`Document::load`]).
//! * Accessory transparency bytes go through the float opacity the C++
//!   keeps ([`save::opacity_byte`]).
//! * The play start and stop frames and the max frame are read back from
//!   their edit boxes (7 and 9 characters, `atol`), the max frame clamped
//!   to 0 or more.
//! * Model and accessory blocks are in slot order.
//! * The tail is always flag 1 and one registration per model, in slot
//!   order; a model without one gets 3 (`model_init.cpp`).
//!
//! # Not ported
//!
//! * `PostModelReload` modes 1 and 2.
//! * The physics of the frame loop ([`frame::FrameLoop`]) rebuilds the world
//!   when the model set changes, where the C++ adds the new bodies to the
//!   world it has; a failing motion load requests no settle.
//! * Leaving camera mode with a camera parent or a reference mode other
//!   than 0, and the model-name fallbacks of the loaders (unmappable
//!   characters, the `Null_NN` names of textures and materials).
//! * Range scaling (`ChainedBoneKeys` undo entries).
//! * Bone matrices are those of the saved pose without physics, and
//!   without outside parents in other models, wherever the C++ reads the
//!   frame loop's `matInit` ([`Command::SetCameraReference`],
//!   [`Command::SetCameraParentModel`], [`Command::ApplyOutsideParent`]).
//! * The runtime state of the background media (size, frame range, decoded
//!   frames): [`background`] keeps what the PMM saves.
//!
//! The script replay of `tests/fixtures/rust/script/` to `script4/` is
//! [`script::Runner`]; `tests/script.rs` compares every save with the C++
//! output.

mod accessory;
mod add_model;
pub mod background;
mod bulk;
mod camera_reference;
mod delete_model;
pub mod frame;
pub mod global;
pub mod history;
mod lip_sync;
pub mod model;
pub mod new_scene;
mod order;
pub mod outside_parent;
pub mod panel;
pub mod pmd_edit;
pub mod pose_file;
mod readout;
mod refresh;
pub mod save;
pub mod script;
mod timeline;
pub mod vmd_save;

pub use accessory::vac_mesh_name;
pub use global::{GlobalClipboard, GlobalTrack};
pub use model::ModelClipboard;
pub use panel::{ModelFlag, ViewOption};
pub use pmd_edit::EnglishName;

use mds_formats::pmd::Pmd;
use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use model::{ModelEdit, Skeleton};
use std::fmt;

/// The self-shadow key mode the C++ resets to on a device with
/// post-processing (`postProcessEnabled`), which this port assumes.
pub(crate) const POST_PROCESS_SHADOW_MODE: u8 = 1;

/// `kPiLit` of the edit handlers (3.141592025756836, the float pi).
pub(crate) const PI_LIT: f64 = 3.141592025756836;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// The PMM or a model file does not parse.
    Format(String),
    /// A key-pool operation failed.
    Edit(mds_edit::Error),
    /// The command needs a model, accessory or mode that is not there.
    NotApplicable(&'static str),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Format(e) => write!(f, "{e}"),
            Error::Edit(e) => write!(f, "{e:?}"),
            Error::NotApplicable(what) => write!(f, "not applicable: {what}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<mds_edit::Error> for Error {
    fn from(e: mds_edit::Error) -> Self {
        Error::Edit(e)
    }
}

/// The file a PMM model path names.
#[derive(Clone, Debug)]
pub enum ModelFile {
    Pmx(Box<Pmx>),
    Pmd(Box<Pmd>),
    Missing,
}

/// A key track, for selection.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Track {
    /// The bone track of the selected model's bone `n`.
    Bone(u32),
    Morph(u32),
    /// The display, IK and outside-parent track.
    Display,
    Global(GlobalTrack),
}

/// One edit. See the crate doc.
#[derive(Clone, Debug, PartialEq)]
pub enum Command {
    /// The model combo (`ApplyModelComboSelection`): model mode on a model.
    SelectModel(u8),
    /// The combo's "camera/light/accessory" entry.
    SelectCameraMode,
    /// The current-frame edit (417, `CommitEditControl`) and its
    /// `RefreshAfterFrameApply` (VA 0x00432FA0): every model with a selected
    /// bone pushes `SnapshotPoseBeforeFrameChange` at the new frame (when a
    /// bone is edited) and loses its bone selection, the timeline scrolls,
    /// every model seeks to the frame, and in camera mode the camera,
    /// light, self-shadow, gravity and accessory states follow their keys.
    SetFrame(u32),
    /// The selected model's bone selection (`boneSelection`); the first bone
    /// becomes `selectedBone`.
    SelectBones(Vec<u32>),
    /// Menu 273 on a model with no rigid-body bone
    /// (`command_view_menu.cpp:1186-1196`): every bone mark of the selected
    /// model is cleared and `selectedBone` stays.
    ClearBoneMarks,
    /// A pose edit of one bone (`BonePosEdit`, `BoneRotEdit`, the viewport
    /// drags): `PushBoneEditUndo`, the pose, and the edited mark.
    SetBonePose {
        bone: u32,
        translation: [f32; 3],
        rotation: [f32; 4],
    },
    SetMorph {
        morph: u32,
        value: f32,
    },
    /// A bone readout edit in model mode (544..549, `CommitEditControlTail`,
    /// `src/window/ui_edit_commit.cpp`, VA 0x0044BEF0) on the selected bone:
    /// axes 0..2 set the translation, 3..5 the X, Y or Z degrees, composed
    /// with the other two readout angles (`ComposeEulerToBone`).
    BoneReadoutEdit {
        axis: u8,
        value: f64,
    },
    /// A morph lane combo (504, 509, 514, 519; `MorphRowSelect`,
    /// `src/window/command_dispatch.cpp`): `selectedMorphs[lane]`.
    SelectMorphLane {
        lane: u8,
        morph: u32,
    },
    /// The camera panel: position, rotation (pitch, yaw, roll), distance,
    /// view angle and perspective.
    SetCamera {
        position: [f32; 3],
        rotation: [f32; 3],
        distance: f32,
        fov: f32,
        perspective: bool,
    },
    SetLight {
        color: [f32; 3],
        direction: [f32; 3],
    },
    /// The self-shadow radio (0, 1, 2) and distance (button 565 stores
    /// `(10000 - v) / 100000` of the edit value `v`).
    SetSelfShadow {
        mode: u8,
        distance: f32,
    },
    /// An `EN_UPDATE` of the gravity dialog (`SetGravityChannel`, VA
    /// 0x0045FD80): 0 magnitude, 1..3 direction X..Z, 4 noise. An all-zero
    /// direction gets Y = 0.1.
    SetGravityChannel(u8, f32),
    /// The gravity dialog's cancel: `DestroyWindow`, then
    /// `ApplyGravityTrack` (VA 0x00412330).
    CloseGravityDialog,
    SetGravity {
        acceleration: f32,
        noise: i32,
        direction: [f32; 3],
        noise_enabled: bool,
    },
    SetAccessory {
        slot: u8,
        visible: bool,
        opacity: f32,
        shadow: bool,
        parent_model: i32,
        parent_bone: i32,
        position: [f32; 3],
        rotation: [f32; 3],
        scale: f32,
    },
    /// Checkbox 530 (']'): automatic interpolation for model keys, curve
    /// reset for camera keys.
    SetAutoInterpolation(bool),
    /// Clears every mark of the selected model and of the camera-mode tracks.
    ClearKeySelection,
    /// Marks the keys of a track with a frame in `from..=to`.
    SelectKeys {
        track: Track,
        from: u32,
        to: u32,
    },
    /// The register button (500) on the selected bones.
    RegisterBoneKeys,
    /// A morph register button, for morph `n` of the selected model.
    RegisterMorphKey(i32),
    /// Button 438.
    RegisterDisplayKey,
    /// The camera-mode register buttons (452, 468, 565, 487, the gravity
    /// dialog) and Enter (`PumpGlobalEnterRegister`): the camera-mode marks
    /// cleared once, then each listed track at the current frame, in the
    /// order camera, light, self shadow, gravity, accessories.
    RegisterGlobalKeys(Vec<GlobalTrack>),
    /// Frame copy (420), by mode.
    Copy,
    /// Frame paste (421), by mode, at the current frame.
    Paste,
    /// Reverse paste (button 422, `PasteMirroredBoneKeyframes`): the copied
    /// bone keys on their left/right counterparts, mirrored, at the current
    /// frame ([`model::paste_bones`]). Nothing in camera mode.
    PasteMirrored,
    /// "Paste to another bone" (menu 250, `MDS_CMD_PASTE_AT_DIFFERENT_FRAME`,
    /// `command_file_menu.cpp` 1471-1638) after its OK/Cancel question: in
    /// model mode the copied bone keys on the selected bone at the current
    /// frame; in camera mode the copied accessory keys on the selected
    /// accessory, then the camera-mode refresh. The menu is enabled when the
    /// clipboard holds bone keys (model mode) or accessory keys (camera
    /// mode); an empty one changes nothing.
    PasteToSelectedBone,
    /// The delete button (423) and the Delete key (`DeleteMarkedKeyframes`).
    DeleteSelectedKeys,
    Undo,
    Redo,
    NewScene,
    /// "Load motion" (menu 209), `LoadVmdMotion` (`src/model/vmd_load.cpp`,
    /// VA 0x00434B60) with the file bytes: in camera mode onto the camera,
    /// light and self-shadow tracks, then their refresh; in model mode onto
    /// the selected model ([`model::load_vmd`]), then `SeekModelFrame`.
    LoadMotion(Vec<u8>),
    /// "Add model" (button 435), `LoadModelFile` (`src/model/add_model.cpp`,
    /// VA 0x00460430) with the path as given and the file bytes: the model
    /// takes the first free slot, is selected, leaves camera mode, and the
    /// viewport edit mode becomes bone (0).
    LoadModel {
        path: String,
        data: Vec<u8>,
    },
    /// "Load accessory" (button 472, `LoadAccessoryFile`,
    /// `src/render/accessory.cpp`, VA 0x00460B30) with the path as given
    /// (the name is what follows its last backslash) and the `.x` bytes.
    LoadAccessory {
        path: String,
        data: Vec<u8>,
    },
    /// "Load accessory" of a `.vac` file (a path holding `.vac`): the
    /// `.vac` text, and the mesh it names ([`vac_mesh_name`]) as the caller
    /// resolved it (the C++ looks next to the `.vac`, then in the
    /// `UserFile` folders) with its bytes.
    LoadVac {
        path: String,
        vac: Vec<u8>,
        mesh_path: String,
        mesh: Vec<u8>,
    },
    /// "Load WAVE" (menu 206, `LoadWaveFile`, `src/media/wave_audio.cpp`).
    LoadWave {
        path: String,
        data: Vec<u8>,
    },
    /// The accessory combo (471, `command_dispatch.cpp`).
    SelectAccessory(u8),
    /// The accessory edits 478..485 (`CommitEditControl`,
    /// `src/window/ui_edit_commit.cpp`) on the selected accessory: 0..2
    /// position, 3..5 rotation in degrees, 6 scale, 7 opacity (clamped to
    /// 0..1).
    AccessoryEdit {
        field: u8,
        value: f64,
    },
    /// The accessory parent model combo (474, `command_dispatch.cpp`):
    /// a model slot, or `None` for the ground entry.
    SetAccessoryParentModel(Option<u8>),
    /// The accessory parent bone combo (475): a bone of the parent model.
    SetAccessoryParentBone(u32),
    /// "Load pose" (menu 202, `CmdLoadPose`, `command_impl.cpp`) with the
    /// VPD bytes, onto the selected model ([`pose_file::load_vpd`]). Nothing
    /// in camera mode.
    LoadPose(Vec<u8>),
    /// The select-all menus 217, 218, 220 (model) and 237..241 (camera
    /// mode), `mds_ops::select`.
    SelectAll(SelectAll),
    /// Menus 255..258 (`mds_ops::frame_line`): the bone or camera line
    /// (`morph == false`), the morph or light line, inserted or deleted at
    /// the current frame.
    FrameLine {
        morph: bool,
        insert: bool,
    },
    /// Menu 219, center position bias (`command_file_menu.cpp` 1042-1093,
    /// [`mds_ops::center_position_bias`]): the offset added to every marked
    /// key of a root bone, after a `SnapshotSelectedKeysForUndo` entry; the
    /// model seeks and physics settles.
    CenterPositionBias([f32; 3]),
    /// Menu 222, delete unused frames (`command_file_menu.cpp` 1118-1145):
    /// [`mds_ops::mark_unused_keys`], then the delete button's
    /// `DeleteMarkedKeyframes`. The count of the info box is
    /// [`EditState::reported`].
    RemoveUnusedKeys,
    /// Menu 225 (`command_file_menu.cpp` 1242-1316,
    /// [`mds_ops::shift_lip_frames`]), then `FramePurgeTail`.
    ShiftLipFrames(i32),
    /// Menu 226, `PurgeMorphFrames(app, 3)` (`command_file_menu.cpp`
    /// 1323-1347), then `FramePurgeTail`. The confirmation is the caller's.
    DeleteLipFrames,
    /// Menu 228, `PurgeMorphFrames(app, 2)` (`command_file_menu.cpp` 1446).
    DeleteEyeFrames,
    /// Menu 231, `PurgeMorphFrames(app, 1)` (`command_file_menu.cpp` 1737).
    DeleteEyebrowFrames,
    /// Menu 227, random blinks (`command_file_menu.cpp` 1352-1438,
    /// [`mds_ops::random_blinks`]) with the document's `rand()` state and
    /// blink phase. The count of the info box is [`EditState::reported`].
    RegisterBlinks {
        start: i32,
        end: i32,
    },
    /// Menu 230 (`command_file_menu.cpp` 1709-1735): every morph weight 0.
    ResetMorphs,
    /// Menu 229 and key H (`command_file_menu.cpp` 1654-1695,
    /// [`mds_ops::register_all_morph_frames`]), then the seek.
    RegisterAllMorphFrames,
    /// Menu 242 (`ApplyCameraFrameScaleAdd`, `misc_dialogs.cpp` 361-402),
    /// camera mode only.
    MultiplyCamera(mds_ops::CameraScale),
    /// Menu 251 (`ApplyBoneFrameScaleAdd`, `misc_dialogs.cpp` 530-591): a
    /// `RegisterBoneUndoSnapshot` entry, the pairs, then the seek.
    MultiplyBone(mds_ops::BoneScale),
    /// Menu 252 (`ApplyMorphScaleAdd`, `misc_dialogs.cpp` 604-628).
    MultiplyMorph {
        scale: f32,
        add: f32,
    },
    /// Menu 275 (`ApplyPhysicsOnOff`, `misc_dialogs.cpp` 652-768): the
    /// `physicsDisabled` byte of every marked key of a rigid-body bone;
    /// combo item 0 ("ON") is `false`.
    SetKeyPhysics {
        disabled: bool,
    },
    /// Button 424 (`ApplyFrameRangeScale`, `frame_range_apply.cpp`
    /// 297-340, [`mds_ops::scale_frame_range`]), then the seek.
    ScaleFrames(mds_ops::RangeScale),
    /// A click on the frame strip of the timeline ([`Document::click_frame`]):
    /// unlike [`Command::SetFrame`] (the frame edit and the step buttons,
    /// which clear the bone selection), it clears the edited marks and keeps
    /// the selection.
    ClickFrame(u32),
    /// The edit-mode radios 490..493 and keys C, X, Z
    /// (`command_panel_toggles.cpp` 612-650, `key_ladder.cpp` 99, 259, 290):
    /// `timeline.edit_mode`, 0 bone, 1 box selection, 2 none, 3 rotate,
    /// 4 move.
    SetEditMode(i32),
    /// Button 494 and key A ([`Document::select_all_bones`]).
    SelectAllBones,
    /// Button 501 and key S ([`Document::select_unregistered_bones`]).
    SelectUnregisteredBones,
    /// Button 495 ([`Document::reset_bone_pose`]).
    ResetBonePose,
    /// Button 496 ([`Document::copy_bone_pose`]).
    CopyBonePose,
    /// Buttons 497 and 498 ([`Document::paste_bone_pose`]).
    PasteBonePose {
        mirror: bool,
    },
    /// Combo 449 ([`Document::set_camera_parent_model`]): a model slot, or
    /// `None` for no parent.
    SetCameraParentModel(Option<u8>),
    /// Combo 450 ([`Document::set_camera_parent_bone`]).
    SetCameraParentBone(u32),
    /// Check boxes 439..441 (`command_frame_edit.cpp` 1566-1592) on the
    /// selected model.
    SetModelFlag {
        flag: ModelFlag,
        on: bool,
    },
    /// Buttons 444 and 445 (`command_frame_edit.cpp` 1598-1617): the IK
    /// switch of chain `chain` of the selected model (`ik_pose`); no key.
    SetIkEnabled {
        chain: u32,
        on: bool,
    },
    /// The expand and collapse buttons of the panels (`OptionFlagRefresh`,
    /// `command_frame_register.cpp` 422-430, `ui_model_reload.cpp` 205-245):
    /// `settings.options[panel]`, 1 camera, 2 light, 3 accessory, 4 bone,
    /// 5 morph, 6 self shadow.
    SetPanelExpanded {
        panel: u8,
        expanded: bool,
    },
    /// The play panel (411, 413, 414 and edits 409, 410;
    /// `command_frame_edit.cpp` 1431-1439): loop, return to the start frame,
    /// play from the current frame, and the start and stop frames.
    SetPlayback {
        looped: bool,
        return_to_start: bool,
        from_current: bool,
        start_frame: i32,
        stop_frame: i32,
    },
    /// The view switches of menus 211, 215, 221, 254, 279 and 282.
    SetViewOption {
        option: ViewOption,
        on: bool,
    },
    /// Menus 234, 235, 236 (`command_file_menu.cpp` 1913-1932):
    /// `view.fps_limit` 1000, 30 or 60.
    SetFpsLimit(f32),
    /// Menu 212 (`ScreenSizeDlgProc`, `command_file_menu.cpp` 436-468, and
    /// 1008-1029): refused above [`EditState::max_texture_size`].
    SetRenderSize {
        width: i32,
        height: i32,
    },
    /// Menu 247 ([`Document::set_follow_camera`]).
    SetFollowCamera(bool),
    /// The edge thickness dialog of menu 253 (`SetEdgeThickness`,
    /// `command_view_menu.cpp` 434-441): `edge_scale` of the selected model.
    SetEdgeScale(f32),
    /// Menu 286 (`command_view_menu.cpp` 1464-1495): the model outline
    /// colour, red, green, blue.
    SetOutlineColor([u8; 3]),
    /// Copy curve ([`Document::copy_curve`]) of the curve combo's channel.
    CopyInterpolationCurve {
        channel: u8,
    },
    /// Paste curve ([`Document::write_curve`]).
    PasteInterpolationCurve {
        channel: u8,
    },
    /// Reset curve ([`Document::write_curve`]).
    ResetInterpolationCurves {
        channel: u8,
    },
    /// A drag in the curve editor ([`Document::set_curve_point`]): the start
    /// point (`end == false`) or the end point, in curve units.
    SetKeyInterpolation {
        channel: u8,
        end: bool,
        point: [i32; 2],
    },
    /// A click in the margin column of a display group row
    /// ([`Document::toggle_display_group`]).
    ToggleDisplayGroup(u8),
    /// A plain click on an unmarked key: [`Command::SelectKeys`] after the
    /// marks of the mode are cleared.
    ReplaceKeySelection {
        track: Track,
        from: u32,
        to: u32,
    },
    /// The timeline scroll bar (428, `ui_hscroll.cpp` 274-313):
    /// `timeline.start_frame`.
    SetTimelineStart(i32),
    /// The bone list scroll bar (`HandleVScroll`, `ui_scroll_mouse.cpp`
    /// 42-105): the selected model's `bone_list_pos` in model mode, else
    /// `display_list_scroll`.
    SetTrackListScroll(i32),
    /// The bone rotation edit boxes 540..542 committed in model mode
    /// ([`Document::zero_bone_rotation_axis`]): `degrees` is what the three
    /// boxes held, `axis` the edited one (0 X, 1 Y, 2 Z).
    ZeroBoneRotationAxis {
        axis: u8,
        degrees: [f32; 3],
    },
    /// The delete button of the accessory panel (`DeleteSelectedAccessory`,
    /// `command_panel_toggles.cpp` 220-321) on the accessory in `slot`,
    /// after the confirmation box.
    DeleteAccessory(u8),
    /// Checkbox 477 (`command_panel_toggles.cpp` 554-562): the additive
    /// blend of the selected accessory. The C++ toggles; this sets.
    SetAccessoryAdditive(bool),
    /// A drag of the marked keys by `delta` frames, the mouse row offset
    /// of `HandleMouseMove` (`ui_mousemove.cpp` 330-404) over 13 pixels per
    /// frame ([`timeline`]). The keys stay between their unmarked
    /// neighbours; head keys do not move. Model mode: the undo entry of the
    /// mouse-down, the display, morph and bone keys, the max frames, the
    /// seek. Camera mode: the camera, light, self-shadow, gravity and
    /// accessory keys, then their refresh.
    MoveSelectedKeys(i32),
    /// The delete button of the model panel (437, `DeleteSelectedModel`,
    /// `command_frame_edit.cpp` 1186-1335) on the model in `slot`, after
    /// the confirmation box: the combo and display orders above it move
    /// down, every link to the slot (outside parents of poses and display
    /// keys, the camera parent and camera keys, accessory parents and
    /// keys) is cut, and the scene enters camera mode.
    DeleteModel(u8),
    /// The camera reference check boxes 412 and 531: 0 none, 1 the model
    /// (center bone), 2 the selected bone. In model mode the view offset
    /// and distance are re-anchored ([`camera_reference`]).
    SetCameraReference(u8),
    /// The English name dialog (menu 259) on the selected model
    /// ([`pmd_edit::EnglishName`]).
    SetEnglishName {
        name: EnglishName,
        text: String,
    },
    /// The toon texture names of "enhance model" (menu 261,
    /// `CollectToonFileNames`, `enhance_model_io.cpp` 57-95) on the
    /// selected PMD: ten names, of which one equal to `toonNN.bmp` keeps the
    /// stored name. The C++ stores a name only when the texture loads from
    /// the model directory; that check is the caller's.
    SetToonFileNames(Vec<String>),
    /// The OK of the physics model dialog (menu 262, `CommitPhysicsEdits`,
    /// `physics_model_dialog.cpp` 1129-1295) on the selected PMD: the rigid
    /// bodies and joints as the dialog left them, in file form.
    SetPhysicsModel {
        rigids: Vec<mds_formats::pmd::Rigid>,
        joints: Vec<mds_formats::pmd::Joint>,
    },
    /// The model path the PMM saves (`model.path`), which "save enhanced
    /// model" sets to the saved file.
    SetModelPath {
        slot: u8,
        path: String,
    },
    /// Button 630 of the outside-parent dialog (button 442,
    /// `ApplyBoneAttach`, `dialog_select_ops.cpp` 404-460) on the bone of
    /// selector `selector` of the selected model, with the parent the
    /// dialog's combos show: the pose that keeps the bone where it is under
    /// that parent ([`outside_parent`]), the bone alone selected, then the
    /// register button's `RegisterSelectedBoneKeys`. The model's selector
    /// records stay; [`Command::RegisterOutsideParents`] writes them.
    ApplyOutsideParent {
        selector: u32,
        parent: OutsideParent,
    },
    /// Button 632 of the outside-parent dialog (`ResetModelSelection`,
    /// `dialog_select_ops.cpp` 334-376): every key mark of the selected
    /// model cleared, the dialog's records (one per selector) written to
    /// the model, and `RegisterDisplayKeyCurrent`.
    RegisterOutsideParents(Vec<OutsideParent>),
    /// The outside-parent dialog closing (`EditAccessoryAttachments`,
    /// `command_frame_edit.cpp` 1344-1378; its cancel ends the dialog with
    /// `IDOK`): the selected model seeks when 630 or 632 ran since the last
    /// close.
    CloseOutsideParentDialog,
    /// The OK of the model draw order dialog (menu 288,
    /// `ModelDisplayOrderDlgProc`, `model_order_dialog.cpp` 201-325): the
    /// model slots in their new combo order, all of them. Then the combo's
    /// camera entry, as [`Command::SelectCameraMode`].
    SetModelDrawOrder(Vec<u8>),
    /// The OK of the model calculation order dialog (menu 289,
    /// `ModelCalculateOrderDlgProc`, `model_order_dialog.cpp` 114-185): the
    /// model slots in their new calculation order, all of them
    /// (`pmm::Model::display_order`, `comboSelIndex2`).
    SetModelCalcOrder(Vec<u8>),
    /// The OK of the accessory order dialog (menu 249,
    /// `AccessorySettingsDlgProc`, `command_file_menu.cpp` 720-900, and
    /// `ApplyAccessorySettingsDialog` 932-958): the accessory slots in their
    /// new combo order, all of them. Each takes its combo text as its name;
    /// the first becomes the selected accessory.
    SetAccessoryOrder(Vec<u8>),
    /// The rename button (633) of the accessory order dialog: the combo
    /// text and, on OK, the name of the accessory in `slot`. An empty name
    /// changes nothing.
    RenameAccessory {
        slot: u8,
        name: String,
    },
    /// The count edit (0x27B) of the accessory order dialog on OK:
    /// `accessoryRenderSplitOrder`, clamped to `0..=` the accessory count
    /// as its `EN_CHANGE` clamps it.
    SetAccessoryRenderSplit(i32),
    /// The start of a viewport bone drag (`frame_modes.cpp` 351, 353):
    /// `PushBoneEditUndo` of the selected bones. The moves are
    /// [`Command::DragBonePose`].
    BeginBoneEdit,
    /// One move of a viewport bone drag: [`Command::SetBonePose`] without
    /// the undo entry, which [`Command::BeginBoneEdit`] pushed.
    DragBonePose {
        bone: u32,
        translation: [f32; 3],
        rotation: [f32; 4],
    },
    /// The model-mode view offset, `viewOffsetX` and `viewOffsetY`
    /// (`camera_state[3..5]`), as the shift+right drag
    /// (`pump_navigation.cpp` 330-334), the middle-button pan (376-380) and
    /// the pan tool (`frame_modes.cpp` 530-537) write it; the PMM saves it.
    /// The callers' model-mode gate is theirs.
    SetViewOffset([f32; 2]),
    /// A viewport drag on the record the physics model dialog shows
    /// (`EditModeRecord`, `frame_modes_bone.cpp` 158-224), on
    /// [`EditState::physics_scratch`]: rigid body `index` (`joint ==
    /// false`) or joint `index`, `axis` 0..2, by the mouse row delta `dy`.
    /// Rotation moves by 0.01 radian per row, position and size by 0.05; a
    /// size stays at 0.1 or more. A joint has no size.
    EditPhysicsRecord {
        joint: bool,
        index: u32,
        field: PhysicsField,
        axis: u8,
        dy: i32,
    },
    /// "Load background AVI file" (menu 213, a dropped `.avi`;
    /// `LoadAviFile`, `src/media/media_load.cpp` 155-314) with the path the
    /// loader resolved and the file bytes ([`background`]).
    LoadBackgroundMovie {
        path: String,
        data: Vec<u8>,
    },
    /// "Load background picture file" (menu 232, a dropped `.bmp`;
    /// `LoadBackgroundPicture`, `media_load.cpp` 321-378) with the path the
    /// loader resolved and the file bytes ([`background`]).
    LoadBackgroundPicture {
        path: String,
        data: Vec<u8>,
    },
    /// Menu 216 (`command_dispatch.cpp` 541-553): the AVI background shown
    /// or hidden. Showing needs a loaded movie.
    ShowBackgroundMovie(bool),
    /// Menu 233 (`command_file_menu.cpp` 1893-1906): the picture background
    /// shown or hidden. Showing needs a loaded picture.
    ShowBackgroundPicture(bool),
    /// The Delete key (`PumpDeleteRebuild`, `pump_edit_keys.cpp` 241-254):
    /// [`Command::DeleteSelectedKeys`], without the button's `SceneModified`.
    DeleteKey,
    /// The physics menus 265 (1, anytime), 269 (2, on/off), 270 (3, trace)
    /// and 272 (0, none) (`command_view_menu.cpp` 1048-1110):
    /// `pmm.physics.playback_mode`; modes 1 to 3 request a settle. The live
    /// world takes the mode through `mds_physics::PhysicsScene::set_physics_mode`.
    SetPhysicsMode(u8),
    /// Menu 285 (`command_view_menu.cpp` 1437-1452):
    /// `pmm.appearance.floor_visible`. The C++ toggles, and stores 1 (shown)
    /// or -1 into the ground body's `m_collisionFlags` (x64 `+0xE0`, x86
    /// `+0xD4`), which no `mds-physics` call does yet. This sets.
    SetFloorVisible(bool),
    /// The physics check box (499): [`EditState::physics_checkbox`].
    SetPhysicsCheckbox(bool),
    /// The camera-mode paths of menu 300 (the numeric input dialog's OK,
    /// `command_view_menu.cpp` 1748-1773) and menu 302 (reset rotation,
    /// 1864-1872): position, pitch, yaw, roll and distance, which
    /// [`Command::SetCamera`] also writes; unlike the camera panel, both set
    /// `SceneModified`. Camera mode only.
    SetCameraFromMenu {
        position: [f32; 3],
        rotation: [f32; 3],
        distance: f32,
    },
    /// The self-shadow range slider 560 at `position` (`ui_hscroll.cpp`
    /// 261-272): the distance `(10000 - position) / 100000`, the mode
    /// unchanged; unlike [`Command::SetSelfShadow`], it sets `SceneModified`.
    SetSelfShadowSlider(i32),
    /// The end of a Kinect recording (`PumpKinectSkeleton`,
    /// `oni_skeleton_pump.cpp` 510-524) on the selected model in model
    /// mode: `RegisterKinectPoseCapture` at `frame` of a trace of `samples`
    /// samples, whose keys are [`mds_kinect::register`]'s
    /// ([`model::register_capture`]); then the model seeks, the last
    /// registered frame rises to the model's max frame, and a settle is
    /// requested.
    RegisterKinectCapture {
        frame: u32,
        samples: u32,
        keys: Vec<mds_kinect::KeyRegistration>,
    },
    /// The screen capture radios 243..246 (`command_file_menu.cpp`
    /// 2053-2090): `view.capture_mode`, 0 off, 1 full frame, 2 the 4:3
    /// crop, 3 background refresh.
    SetCaptureMode(i32),
}

/// A parent of the outside-parent dialog (`BoneOrderEntry::linkedModel`
/// and `linkedBone`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OutsideParent {
    /// "none" (-1).
    None,
    /// "ground" (-2).
    Ground,
    /// Bone `bone` of the model in slot `model`.
    Bone { model: u8, bone: u32 },
}

/// The record field of [`Command::EditPhysicsRecord`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PhysicsField {
    Rotation,
    Position,
    /// The rigid-body size (Shift held).
    Size,
}

impl Command {
    /// Whether the C++ handler sets `SceneModified` (the unsaved-changes
    /// flag of the close and open questions) once it gets past its gates;
    /// the caller sets its flag when [`Document::apply`] succeeds. The
    /// handlers that leave it alone include every selection, view, panel
    /// and pose edit, and the PMD edits, which set `EnhancedModelDirty`
    /// instead. [`Command::NewScene`] and "open project" clear it. A paste
    /// with an empty clipboard leaves the flag, where this says `true`;
    /// [`Document::marks_modified`] sees that gate. [`Document::lip_sync`]
    /// sets it (menu 224 and the drop).
    pub fn marks_modified(&self) -> bool {
        use Command as C;
        matches!(
            self,
            // command_frame_register.cpp 386, 517; command_frame_edit.cpp
            // 1549; command_panel_toggles.cpp 139; frame_register 811;
            // gravity_setting_dialog.cpp 149.
            C::RegisterBoneKeys
                | C::RegisterMorphKey(_)
                | C::RegisterDisplayKey
                | C::RegisterGlobalKeys(_)
                // frame_clipboard.cpp 516, 678, 786; command_file_menu.cpp
                // 1501, 1603; command_frame_edit.cpp 1652, 523, 556.
                | C::Paste
                | C::PasteMirrored
                | C::PasteToSelectedBone
                | C::DeleteSelectedKeys
                | C::Undo
                | C::Redo
                // command_impl.cpp 441, 363; add_model.cpp 70;
                // render/accessory.cpp 615.
                | C::LoadMotion(_)
                | C::LoadModel { .. }
                | C::LoadAccessory { .. }
                | C::LoadVac { .. }
                | C::LoadWave { .. }
                // command_view_menu.cpp 892; command_file_menu.cpp 1086,
                // 1136, 363 (FramePurgeTail), 1433, 1658, 1018;
                // misc_dialogs.cpp 401, 589, 627; frame_range_apply.cpp 338.
                | C::FrameLine { .. }
                | C::CenterPositionBias(_)
                | C::RemoveUnusedKeys
                | C::ShiftLipFrames(_)
                | C::DeleteLipFrames
                | C::DeleteEyeFrames
                | C::DeleteEyebrowFrames
                | C::RegisterBlinks { .. }
                | C::RegisterAllMorphFrames
                | C::MultiplyCamera(_)
                | C::MultiplyBone(_)
                | C::MultiplyMorph { .. }
                | C::ScaleFrames(_)
                | C::SetRenderSize { .. }
                // command_view_menu.cpp 438; command_frame_edit.cpp 1034,
                // 1083, 1239; command_panel_toggles.cpp 265; ui_mousemove.cpp
                // 334.
                | C::SetEdgeScale(_)
                | C::PasteInterpolationCurve { .. }
                | C::ResetInterpolationCurves { .. }
                | C::DeleteModel(_)
                | C::DeleteAccessory(_)
                | C::MoveSelectedKeys(_)
                // dialog_select_ops.cpp 335, 437; command_frame_edit.cpp
                // 1356; command_impl.cpp 570, command_file_menu.cpp 1889 (set
                // even when the load fails).
                | C::ApplyOutsideParent { .. }
                | C::RegisterOutsideParents(_)
                | C::CloseOutsideParentDialog
                | C::LoadBackgroundMovie { .. }
                | C::LoadBackgroundPicture { .. }
                // command_view_menu.cpp 1771, 1870; ui_hscroll.cpp 270.
                | C::SetCameraFromMenu { .. }
                | C::SetSelfShadowSlider(_)
        )
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SelectAll {
    Bone,
    Display,
    Morph,
    Camera,
    Light,
    SelfShadow,
    Gravity,
    Accessory,
}

/// Edit state the C++ keeps outside the file.
#[derive(Clone, Debug, Default)]
pub struct EditState {
    /// One per `pmm.models` entry.
    pub models: Vec<ModelEdit>,
    pub model_clipboard: ModelClipboard,
    pub global_clipboard: GlobalClipboard,
    /// `SelfShadowMode`, the 0/1/2 radio.
    pub self_shadow_mode: u8,
    pub auto_interpolation: bool,
    /// The physics checkbox (499), which "register" stores negated as the
    /// `physicsDisabled` of a rigid-body bone.
    pub physics_checkbox: bool,
    /// `PhysicsResetPending`: the commands whose C++ handler requests a
    /// physics settle set it; the frame loop ([`frame::FrameLoop`]) takes it.
    pub physics_reset_pending: bool,
    /// The CRT `rand()` state, one per process (menu 227).
    pub rand: mds_ops::MsvcRand,
    /// `blinkPhase` (`app+0x9EB7F`), which menu 227 carries between runs.
    pub blink_phase: u8,
    /// The number the last command's info box showed (menus 222 and 227),
    /// `None` after any other command.
    pub reported: Option<u32>,
    /// Buttons 496..498.
    pub bone_pose_clipboard: panel::BonePoseClipboard,
    /// The curve copy, paste and reset buttons.
    pub curve_clipboard: panel::CurveClipboard,
    /// The device's `maxTextureWidth` and `maxTextureHeight`, which bound
    /// the render size (menu 212); the application sets it from its device.
    /// `None` checks nothing.
    pub max_texture_size: Option<[i32; 2]>,
    /// The viewport rectangle and `viewScale` that `MediaAspect` reads
    /// when a background loads; the application sets it from its window.
    /// `None` refuses the background loads.
    pub viewport: Option<mds_media::background::Viewport>,
    /// The rigid bodies and joints the open physics model dialog edits
    /// (`rigidScratchArray`, `jointScratchArray`, `physics_model_dialog.cpp`
    /// 574-685), which [`Command::EditPhysicsRecord`] drags; the dialog
    /// fills it when it opens, commits it through
    /// [`Command::SetPhysicsModel`] after reading its edit boxes back
    /// (`%3.2f` sizes and positions, `%5.4f` joint positions), and clears
    /// it when it closes.
    pub physics_scratch: Option<(Vec<mds_formats::pmd::Rigid>, Vec<mds_formats::pmd::Joint>)>,
    /// `AccessoryApplyGate`: 630 or 632 of the outside-parent dialog ran.
    pub outside_parent_applied: bool,
}

impl EditState {
    /// The check boxes as the application starts: "auto interpolation"
    /// (530, `checkPhysicsFrame` in `window_init.cpp` without a config) and
    /// physics (499, which `ui_init.cpp` checks).
    pub fn startup() -> EditState {
        EditState {
            auto_interpolation: true,
            physics_checkbox: true,
            ..EditState::default()
        }
    }
}

#[derive(Clone, Debug)]
pub struct Document {
    pub pmm: Pmm,
    /// One entry per `pmm.models` entry, in the same order.
    pub models: Vec<ModelFile>,
    pub edit: EditState,
    skeletons: Vec<Option<Skeleton>>,
}

use bulk::ops;

pub(crate) fn not(what: &'static str) -> Error {
    Error::NotApplicable(what)
}

impl Document {
    /// Loads a PMM and the model files it names, with the edit state of a
    /// start-up ([`EditState::startup`]). `read` maps a model path as stored
    /// in the PMM to the file bytes; a path it cannot read gives
    /// [`ModelFile::Missing`]. [`Document::load_scene`] is "open project",
    /// which keeps the check boxes of the document it replaces.
    pub fn load(
        data: &[u8],
        mut read: impl FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<Document, Error> {
        let mut pmm = Pmm::read(data).map_err(|e| Error::Format(e.to_string()))?;
        // The combo rows stay in place; the accessories move to their rows
        // ([`order`]).
        let rows: Vec<_> = pmm
            .accessories
            .iter()
            .map(|a| a.list_name.clone())
            .collect();
        pmm.accessories.sort_by_key(|a| a.order);
        for (a, r) in pmm.accessories.iter_mut().zip(rows) {
            a.list_name = r;
            accessory::record_name(a);
        }
        let mut models = Vec::with_capacity(pmm.models.len());
        for m in &pmm.models {
            let path = m.path.text.as_str();
            models.push(match read(path) {
                None => ModelFile::Missing,
                Some(b) => parse_model(path, &b)?,
            });
        }
        let skeletons = models
            .iter()
            .zip(&pmm.models)
            .map(|(f, m)| Skeleton::new(f, m))
            .collect();
        let edit = EditState {
            models: vec![ModelEdit::default(); pmm.models.len()],
            self_shadow_mode: shadow_mode_at(&pmm),
            ..EditState::startup()
        };
        Ok(Document {
            pmm,
            models,
            edit,
            skeletons,
        })
    }

    /// The scene the application starts with ([`new_scene::startup`]).
    pub fn startup() -> Document {
        let pmm = new_scene::startup();
        Document {
            edit: EditState {
                self_shadow_mode: shadow_mode_at(&pmm),
                ..EditState::startup()
            },
            pmm,
            models: Vec::new(),
            skeletons: Vec::new(),
        }
    }

    /// "Open project" (menu 205): `LoadSceneFile` (`src/io/pmm_load_v2.cpp`,
    /// VA 0x00450000) replacing this document. Against [`Document::load`],
    /// it keeps what the loader leaves from the scene before: the sidebar
    /// width, which `HandleWindowSize` sets back from the window (the file's
    /// value only lasts until the relayout), and the offset and scale of an
    /// AVI or picture background that is not enabled. The display groups of
    /// each model are those of its file (`ModelLoadPMD`).
    pub fn load_scene(
        &mut self,
        data: &[u8],
        read: impl FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<(), Error> {
        let mut d = Document::load(data, read)?;
        // The display groups come from the model file; the saved flags are
        // kept (as `b == 1`) only when the counts agree.
        for (m, f) in d.pmm.models.iter_mut().zip(&d.models) {
            let Some(g) = model::group_count(f) else {
                continue;
            };
            let s = &mut m.selection;
            if g == m.group_count {
                s.group_flags
                    .iter_mut()
                    .for_each(|b| *b = u8::from(*b == 1));
            } else {
                s.group_flags = vec![0; usize::from(g)];
            }
            m.group_count = g;
            s.group_count_repeat = g;
        }
        let (old, p) = (&self.pmm, &mut d.pmm);
        p.settings.panel_width = old.settings.panel_width;
        if p.avi.enabled != 1 {
            (p.avi.offset, p.avi.scale) = (old.avi.offset, old.avi.scale);
        }
        if p.picture.enabled == 0 {
            (p.picture.offset, p.picture.scale) = (old.picture.offset, old.picture.scale);
        }
        d.edit.auto_interpolation = self.edit.auto_interpolation;
        d.edit.physics_checkbox = self.edit.physics_checkbox;
        d.edit.rand = self.edit.rand;
        d.edit.blink_phase = self.edit.blink_phase;
        d.edit.max_texture_size = self.edit.max_texture_size;
        d.edit.viewport = self.edit.viewport;
        // `LoadSceneV2_ReleaseTracks`: no model in the selected slot means
        // camera mode.
        if d.active().is_none() {
            d.pmm.settings.options[0] = 1;
        }
        // The load ends in `ApplyModelComboSelection` on the selected
        // model's combo entry; an entry of 0 is the camera entry. The edit
        // mode read after it stays.
        let combo = d.selected_model().map(|m| m.selection.combo_index);
        if combo == Some(0) {
            let edit_mode = d.pmm.timeline.edit_mode;
            d.apply(Command::SelectCameraMode)?;
            d.pmm.timeline.edit_mode = edit_mode;
        }
        d.edit.physics_reset_pending = true;
        *self = d;
        Ok(())
    }

    /// The bytes `SaveSceneFile` writes for this scene.
    pub fn save(&self) -> Result<Vec<u8>, Error> {
        save::normalize(&self.pmm)
            .write()
            .map_err(|e| Error::Format(e.to_string()))
    }

    /// "Save pose" (menu 203, `CmdSavePose`, `command_impl.cpp`): the VPD
    /// bytes of the selected bones of the selected model.
    pub fn save_pose(&mut self) -> Result<Vec<u8>, Error> {
        if self.camera_mode() {
            return Err(not("saving a pose in camera mode"));
        }
        let (i, s) = self.keyed()?;
        let mode = self.pmm.physics.playback_mode;
        pose_file::save_vpd(&self.pmm.models[i], &s, &self.edit.models[i], mode)
    }

    /// "Save enhanced model" (menu 263, `SaveEnhancedModel`) of the selected
    /// PMD model to `path`, which becomes the model's path. The C++ writer
    /// reads PMD-only data and ends the process on a PMX model, so a PMX
    /// model is refused.
    pub fn save_pmd(&mut self, path: &str) -> Result<Vec<u8>, Error> {
        let i = self.active_model()?;
        let ModelFile::Pmd(pmd) = &mut self.models[i] else {
            return Err(not("the PMD writer on a model that is not a PMD"));
        };
        let bytes = pose_file::save_pmd(pmd)?;
        let slot = self.pmm.models[i].slot;
        self.apply(Command::SetModelPath {
            slot,
            path: path.to_string(),
        })?;
        Ok(bytes)
    }

    /// The model-mode name check of `LoadVmdMotion` (`src/model/vmd_load.cpp`
    /// 318-338) on the VMD's model name: `Err` for camera and light data,
    /// which the C++ refuses; `Ok(true)` when the name differs from the
    /// selected model's, where the C++ asks an OK/Cancel question before
    /// loading. [`Command::LoadMotion`] is the OK path; the question is the
    /// caller's.
    pub fn motion_needs_confirmation(&self, vmd_model_name: &[u8]) -> Result<bool, Error> {
        Self::motion_model_name(vmd_model_name)?;
        let name = |raw: &[u8]| raw.split(|&b| b == 0).next().unwrap_or(&[]).to_vec();
        let m = self.selected_model().ok_or(not("no model selected"))?;
        Ok(name(vmd_model_name) != name(&m.name.raw))
    }

    fn motion_model_name(raw: &[u8]) -> Result<(), Error> {
        let cl = vmd_save::CAMERA_LIGHT;
        if raw.len() > cl.len() && raw[..cl.len()] == *cl && raw[cl.len()] == 0 {
            return Err(not("the motion is camera and light data (a message box)"));
        }
        Ok(())
    }

    fn camera_mode(&self) -> bool {
        self.pmm.settings.options[0] != 0
    }

    fn frame(&self) -> u32 {
        self.pmm.timeline.current_frame as u32
    }

    /// The selected model in model mode.
    pub fn selected_model(&self) -> Option<&mds_formats::pmm::Model> {
        let i = self.active().filter(|_| !self.camera_mode())?;
        self.pmm.models.get(i)
    }

    /// The selected bone's `(rotation, translation)` shown by `PostViewRefresh`.
    pub fn selected_bone_readout(&self) -> Option<([f32; 4], [f32; 3])> {
        let i = self.active()?;
        let m = &self.pmm.models[i];
        let b = usize::try_from(m.selection.selected_bone).ok()?;
        let p = m.bone_pose.get(b)?;
        let rigid = self.skeletons[i].as_ref().is_some_and(|s| s.bones[b].2);
        if self.pmm.physics.playback_mode == 3 && rigid {
            Some(
                self.edit.models[i]
                    .physics_pose
                    .as_ref()
                    .and_then(|v| v.get(b).copied())
                    .unwrap_or(model::NO_PHYSICS_POSE),
            )
        } else {
            Some((p.rotation, p.translation))
        }
    }

    /// The selected model's index in `pmm.models`.
    fn active(&self) -> Option<usize> {
        let slot = self.pmm.selected_model_slot;
        self.pmm.models.iter().position(|m| m.slot == slot)
    }

    fn active_model(&self) -> Result<usize, Error> {
        self.active().ok_or(not("no model in the selected slot"))
    }

    /// The selected model with its skeleton, for the key commands.
    fn keyed(&mut self) -> Result<(usize, Skeleton), Error> {
        let i = self.active_model()?;
        let s = self.skeletons[i]
            .clone()
            .ok_or(not("the model file is missing or does not match the PMM"))?;
        Ok((i, s))
    }

    /// `0x9E16C = max(0x9E16C, model.maxFrame)` after a model register.
    fn bump_last_registered(&mut self, i: usize) {
        let max = self.pmm.models[i].selection.max_frame as i32;
        let last = &mut self.pmm.timeline.last_registered_frame;
        *last = (*last).max(max);
    }

    /// `RefreshAfterFrameApply` (`src/window/ui_frame_step.cpp`) after the
    /// current frame changed.
    fn apply_frame(&mut self) {
        let frame = self.frame();
        for (m, e) in self.pmm.models.iter_mut().zip(&mut self.edit.models) {
            if m.bone_pose.iter().any(|p| p.flags[2] != 0) {
                model::push_frame_change(m, &mut e.history, frame);
                m.bone_pose.iter_mut().for_each(|p| p.flags[2] = 0);
            }
        }
        self.seek_frame();
    }

    /// The tail every frame change shares: the timeline scroll, every model
    /// at the frame, and in camera mode the camera-mode tracks.
    fn seek_frame(&mut self) {
        // `CameraAttachmentTransformSuppressed() = 0` (`ui_frame_step.cpp`
        // 188, `ui_editor_click.cpp` 805).
        self.pmm.appearance.suppress_camera_transform = 0;
        let frame = self.frame();
        // The timeline shows `(SidebarWidth - 84) / 26` frames before the
        // current one.
        let visible = ((self.pmm.settings.panel_width - 84) / 26) as u32;
        self.pmm.timeline.start_frame = frame.saturating_sub(visible) as i32;
        let mode = self.pmm.physics.playback_mode;
        for (m, f) in self.pmm.models.iter_mut().zip(&self.models) {
            refresh::seek_model(m, f, frame, mode);
        }
        if self.camera_mode() {
            self.refresh_context();
        }
    }

    /// The refresh tail of the delete and paste handlers: in camera mode the
    /// camera, light, self-shadow, gravity and accessory states follow their
    /// keys; in model mode the selected model seeks to the current frame.
    fn refresh_context(&mut self) {
        let frame = self.frame();
        if self.camera_mode() {
            refresh::camera(&mut self.pmm);
            refresh::light(&mut self.pmm);
            refresh::self_shadow(&mut self.pmm, &mut self.edit.self_shadow_mode);
            refresh::gravity(&mut self.pmm);
            for a in &mut self.pmm.accessories {
                refresh::accessory(a, frame);
            }
        } else if let Some(i) = self.active() {
            let mode = self.pmm.physics.playback_mode;
            refresh::seek_model(&mut self.pmm.models[i], &self.models[i], frame, mode);
        }
    }

    pub fn apply(&mut self, cmd: Command) -> Result<(), Error> {
        // The handlers that set `PhysicsResetPending` once they get past
        // their gates: RefreshAfterFrameApply, CmdLoadMotion, CmdLoadPose,
        // the three paste handlers, and the undo and redo buttons. A command
        // that fails is one the user could not run.
        let model_mode = self.pmm.settings.options[0] == 0;
        let settles = match &cmd {
            Command::SetFrame(_) | Command::ClickFrame(_) | Command::LoadMotion(_) => true,
            Command::PasteBonePose { .. } => {
                model_mode && !self.edit.bone_pose_clipboard.is_empty()
            }
            Command::LoadPose(_) | Command::Undo | Command::Redo => {
                model_mode && self.active().is_some()
            }
            Command::CenterPositionBias(_) => model_mode,
            Command::SetPhysicsMode(m) => (1..=3).contains(m),
            Command::RegisterKinectCapture { .. } => model_mode && self.active().is_some(),
            Command::PasteToSelectedBone if !model_mode => false,
            c => self.paste_runs(c).unwrap_or(false),
        };
        self.edit.reported = None;
        let r = self.apply_inner(cmd);
        if r.is_ok() && settles {
            self.edit.physics_reset_pending = true;
        }
        r
    }

    /// For a paste command, whether its handler gets past the clipboard
    /// gate (`frame_clipboard.cpp` 491-516, 653-678, 761-786;
    /// `command_file_menu.cpp` 1471-1501).
    fn paste_runs(&self, cmd: &Command) -> Option<bool> {
        let model_mode = !self.camera_mode();
        let clip = &self.edit.model_clipboard;
        Some(match cmd {
            Command::Paste if model_mode => {
                !(clip.bones.is_empty() && clip.morphs.is_empty() && clip.displays.is_empty())
            }
            Command::Paste => !self.edit.global_clipboard.is_empty(),
            Command::PasteMirrored => model_mode && !clip.bones.is_empty(),
            Command::PasteToSelectedBone if model_mode => !clip.bones.is_empty(),
            Command::PasteToSelectedBone => !self.edit.global_clipboard.accessories.is_empty(),
            _ => return None,
        })
    }

    /// [`Command::marks_modified`] with the clipboard gates of the paste
    /// commands, which depend on the document: whether `cmd`, applied to
    /// this document, sets `SceneModified`. Ask before [`Document::apply`].
    pub fn marks_modified(&self, cmd: &Command) -> bool {
        cmd.marks_modified() && self.paste_runs(cmd).unwrap_or(true)
    }

    fn apply_inner(&mut self, cmd: Command) -> Result<(), Error> {
        let frame = self.frame();

        match cmd {
            Command::SelectModel(slot) => {
                if !self.pmm.models.iter().any(|m| m.slot == slot) {
                    return Err(not("no model in that slot"));
                }
                let follow = self.pmm.appearance.camera_parent_model >= 0
                    && self.pmm.appearance.follow_camera != 0;
                if self.camera_mode() && !refresh::model_mode_supported(&self.pmm)
                    || !self.camera_mode() && follow
                {
                    return Err(not("a model selection with a camera parent (not ported)"));
                }
                self.pmm.selected_model_slot = slot;
                if self.camera_mode() {
                    refresh::rebuild_model_mode(&mut self.pmm, &mut self.edit.self_shadow_mode);
                }
                self.pmm.timeline.edit_mode = 0;
            }
            Command::SelectCameraMode => {
                if !self.camera_mode() {
                    // `RebuildCameraModePanel` (VA 0x0044D780).
                    self.pmm.camera_state[3] = 0.0;
                    self.pmm.camera_state[4] = 0.0;
                    self.pmm.settings.options[0] = 1;
                    self.refresh_context();
                    let mut basis = [0.0; 16];
                    for i in [0, 5, 10, 15] {
                        basis[i] = 1.0;
                    }
                    self.pmm.appearance.camera_attachment_basis = basis;
                    self.pmm.timeline.edit_mode = 2;
                }
                self.pmm.settings.options[0] = 1;
            }
            Command::LoadAccessory { path, data } => {
                accessory::load(&mut self.pmm, &path, &data)?;
            }
            Command::LoadVac {
                path,
                vac,
                mesh_path,
                mesh,
            } => {
                accessory::load_vac(&mut self.pmm, &path, &vac, &mesh_path, &mesh)?;
            }
            Command::LoadWave { path, data } => accessory::load_wave(&mut self.pmm, &path, &data),
            Command::SelectAccessory(slot) => {
                global::accessory(&mut self.pmm, slot)?;
                self.pmm.selected_accessory_slot = slot;
            }
            Command::AccessoryEdit { field, value } => {
                let slot = self.pmm.selected_accessory_slot;
                let Ok(a) = global::accessory(&mut self.pmm, slot) else {
                    return Ok(());
                };
                let s = &mut a.state;
                let f = usize::from(field);
                match f {
                    0..=2 => s.position[f] = value as f32,
                    3..=5 => s.rotation[f - 3] = (value / 180.0 * PI_LIT) as f32,
                    6 => s.scale = value as f32,
                    7 => {
                        let visible = s.opacity_visible & 1;
                        s.opacity_visible =
                            save::opacity_visible(value.clamp(0.0, 1.0) as f32, visible);
                    }
                    _ => return Err(not("no such accessory field")),
                }
            }
            Command::SetAccessoryParentModel(model) => {
                let slot = self.pmm.selected_accessory_slot;
                let found = model.filter(|m| self.pmm.models.iter().any(|x| x.slot == *m));
                let Ok(a) = global::accessory(&mut self.pmm, slot) else {
                    return Ok(());
                };
                match (model, found) {
                    (None, _) => a.state.parent_model = -1,
                    (Some(_), Some(m)) => {
                        a.state.parent_model = i32::from(m);
                        a.state.parent_bone = 0;
                    }
                    (Some(_), None) => {}
                }
            }
            Command::SetAccessoryParentBone(bone) => {
                let slot = self.pmm.selected_accessory_slot;
                let Ok(a) = global::accessory(&mut self.pmm, slot) else {
                    return Ok(());
                };
                if a.state.parent_model >= 0 {
                    a.state.parent_bone = bone as i32;
                }
            }
            Command::SetFrame(f) => {
                self.pmm.timeline.current_frame = f as i32;
                self.apply_frame();
            }
            Command::SetGravityChannel(ch, v) => {
                let p = &mut self.pmm.physics;
                let d = &mut p.gravity_direction;
                match ch {
                    0 => p.gravity_magnitude = v,
                    1..=3 => d[ch as usize - 1] = v,
                    4 => p.gravity_noise = v as i32,
                    _ => return Err(not("no such gravity channel")),
                }
                if ch < 4 && *d == [0.0; 3] {
                    d[1] = 0.1;
                }
            }
            Command::CloseGravityDialog => refresh::gravity(&mut self.pmm),
            Command::SelectBones(bones) => {
                let i = self.active_model()?;
                let m = &mut self.pmm.models[i];
                if bones.iter().any(|&b| b as usize >= m.bone_pose.len()) {
                    return Err(not("no such bone"));
                }
                for (i, p) in m.bone_pose.iter_mut().enumerate() {
                    p.flags[2] = u8::from(bones.contains(&(i as u32)));
                }
                m.selection.selected_bone = bones.first().map_or(-1, |&b| b as i32);
            }
            Command::ClearBoneMarks => {
                let i = self.active_model()?;
                for p in &mut self.pmm.models[i].bone_pose {
                    p.flags[2] = 0;
                }
            }
            Command::SetBonePose {
                bone,
                translation,
                rotation,
            } => {
                let i = self.active_model()?;
                if bone as usize >= self.pmm.models[i].bone_pose.len() {
                    return Err(not("no such bone"));
                }
                self.apply_inner(Command::BeginBoneEdit)?;
                self.apply_inner(Command::DragBonePose {
                    bone,
                    translation,
                    rotation,
                })?;
            }
            Command::SetMorph { morph, value } => {
                let i = self.active_model()?;
                let m = &mut self.pmm.models[i];
                *m.morph_pose
                    .get_mut(morph as usize)
                    .ok_or(not("no such morph"))? = value;
            }
            Command::BoneReadoutEdit { axis, value } => {
                let (i, _) = self.keyed()?;
                let m = &self.pmm.models[i];
                let Ok(b) = usize::try_from(m.selection.selected_bone) else {
                    return Ok(());
                };
                if b >= m.bone_pose.len() || axis > 5 {
                    return Err(not("no such bone or axis"));
                }
                let (rotation, _) = self.selected_bone_readout().unwrap();
                model::push_pose_edit(m, &mut self.edit.models[i].history);
                let p = &mut self.pmm.models[i].bone_pose[b];
                let axis = usize::from(axis);
                if axis < 3 {
                    p.translation[axis] = value as f32;
                } else {
                    let deg = readout::euler_degrees(rotation);
                    p.rotation = readout::rotation_edit(deg, axis - 3, value);
                }
                p.flags[1] = 1;
            }
            Command::SelectMorphLane { lane, morph } => {
                let i = self.active_model()?;
                let m = &mut self.pmm.models[i];
                if morph as usize >= m.morph_names.len() || lane > 3 {
                    return Err(not("no such morph"));
                }
                m.selection.selected_morphs[usize::from(lane)] = morph as i32;
            }
            Command::SetCamera {
                position,
                rotation,
                distance,
                fov,
                perspective,
            } => {
                let s = &mut self.pmm.camera_state;
                s[..3].copy_from_slice(&position);
                s[5] = distance;
                s[6..].copy_from_slice(&rotation);
                self.pmm.settings.camera_fov = fov;
                self.pmm.camera_perspective = u8::from(perspective);
            }
            Command::SetLight { color, direction } => {
                self.pmm.light_state[..3].copy_from_slice(&color);
                self.pmm.light_state[3..].copy_from_slice(&direction);
            }
            Command::SetSelfShadow { mode, distance } => {
                self.edit.self_shadow_mode = mode;
                self.pmm.physics_interval = distance;
            }
            Command::SetGravity {
                acceleration,
                noise,
                direction,
                noise_enabled,
            } => {
                let p = &mut self.pmm.physics;
                p.gravity_magnitude = acceleration;
                p.gravity_noise = noise;
                p.gravity_direction = direction;
                p.gravity_noise_enabled = u8::from(noise_enabled);
            }
            Command::SetAccessory {
                slot,
                visible,
                opacity,
                shadow,
                parent_model,
                parent_bone,
                position,
                rotation,
                scale,
            } => {
                let s = &mut global::accessory(&mut self.pmm, slot)?.state;
                s.opacity_visible = save::opacity_visible(opacity, u8::from(visible));
                s.shadow = u8::from(shadow);
                s.parent_model = parent_model;
                s.parent_bone = parent_bone;
                s.position = position;
                s.rotation = rotation;
                s.scale = scale;
            }
            Command::SetAutoInterpolation(on) => self.edit.auto_interpolation = on,
            Command::ClearKeySelection => {
                global::clear_selection(&mut self.pmm);
                if let Some(i) = self.active() {
                    let mut cursor = self.edit.models[i].search_cursor;
                    model::with_tracks(&mut self.pmm.models[i], &mut cursor, |t| t.clear_marks());
                }
            }
            Command::SelectKeys { track, from, to } => match track {
                Track::Global(g) => global::select(&mut self.pmm, g, from, to)?,
                Track::Bone(b) => {
                    let i = self.active_model()?;
                    let m = &mut self.pmm.models[i];
                    model::select(&mut m.bone_keys, b, from, to)?
                }
                Track::Morph(n) => {
                    let i = self.active_model()?;
                    let m = &mut self.pmm.models[i];
                    model::select(&mut m.morph_keys, n, from, to)?
                }
                Track::Display => {
                    let i = self.active_model()?;
                    let m = &mut self.pmm.models[i];
                    model::select(&mut m.display_keys, 0, from, to)?
                }
            },
            Command::RegisterBoneKeys => {
                let (i, s) = self.keyed()?;
                let auto = self.edit.auto_interpolation;
                let physics = model::Physics {
                    checkbox: self.edit.physics_checkbox,
                    mode: self.pmm.physics.playback_mode,
                };
                let r = model::register_bones(
                    &mut self.pmm.models[i],
                    &s,
                    &mut self.edit.models[i],
                    auto,
                    physics,
                    frame,
                );
                self.bump_last_registered(i);
                r?;
            }
            Command::RegisterMorphKey(morph) => {
                let (i, s) = self.keyed()?;
                let r = model::register_morph(
                    &mut self.pmm.models[i],
                    &s,
                    &mut self.edit.models[i],
                    morph,
                    frame,
                );
                self.bump_last_registered(i);
                r?;
            }
            Command::RegisterDisplayKey => {
                let (i, s) = self.keyed()?;
                let r = model::register_display(
                    &mut self.pmm.models[i],
                    &s,
                    &mut self.edit.models[i],
                    frame,
                );
                self.bump_last_registered(i);
                r?;
            }
            Command::RegisterGlobalKeys(mut tracks) => {
                for t in &tracks {
                    if let GlobalTrack::Accessory(s) = t {
                        global::accessory(&mut self.pmm, *s)?;
                    }
                }
                tracks.sort_by_key(|t| match t {
                    GlobalTrack::Camera => (0, 0),
                    GlobalTrack::Light => (1, 0),
                    GlobalTrack::SelfShadow => (2, 0),
                    GlobalTrack::Gravity => (3, 0),
                    GlobalTrack::Accessory(s) => (4, *s),
                });
                tracks.dedup();
                global::clear_selection(&mut self.pmm);
                let mode = self.edit.self_shadow_mode;
                let reset = self.edit.auto_interpolation;
                let mut first = Ok(());
                for t in tracks {
                    if let Err(e) = global::register(&mut self.pmm, t, frame, mode, reset) {
                        first = first.and(Err(e));
                    }
                }
                first?;
            }
            Command::Copy => {
                if self.camera_mode() {
                    self.edit.global_clipboard = global::copy(&self.pmm);
                } else {
                    let m = &self.pmm.models[self.active_model()?];
                    self.edit.model_clipboard = model::copy(m)?;
                }
            }
            Command::Paste => {
                if self.camera_mode() {
                    global::paste(&mut self.pmm, &self.edit.global_clipboard)?;
                } else {
                    let (i, s) = self.keyed()?;
                    let counts: Vec<(i32, i32)> = self
                        .pmm
                        .models
                        .iter()
                        .map(|m| (i32::from(m.slot), m.bone_names.len() as i32))
                        .collect();
                    let count = |slot| counts.iter().find(|c| c.0 == slot).map(|c| c.1);
                    model::paste(
                        &mut self.pmm.models[i],
                        &s,
                        &mut self.edit.models[i],
                        &mut self.edit.model_clipboard,
                        frame as i32,
                        count,
                    )?;
                }
                self.refresh_context();
            }
            Command::PasteMirrored | Command::PasteToSelectedBone => {
                let mirrored = cmd == Command::PasteMirrored;
                if self.camera_mode() {
                    if mirrored || self.edit.global_clipboard.accessories.is_empty() {
                        return Ok(());
                    }
                    let r = global::paste_onto_selected_accessory(
                        &mut self.pmm,
                        &self.edit.global_clipboard,
                    );
                    if !matches!(r, Err(Error::NotApplicable(_))) {
                        self.refresh_context();
                    }
                    return r;
                }
                if self.edit.model_clipboard.bones.is_empty() {
                    return Ok(());
                }
                let (i, s) = self.keyed()?;
                let target = if mirrored {
                    mds_edit::BoneTarget::Mirrored
                } else {
                    match self.pmm.models[i].selection.selected_bone {
                        -1 => return Err(not("no bone is selected (a message box)")),
                        b => mds_edit::BoneTarget::Selected(b),
                    }
                };
                model::paste_bones(
                    &mut self.pmm.models[i],
                    &s,
                    &mut self.edit.models[i],
                    &self.edit.model_clipboard,
                    frame as i32,
                    target,
                )?;
                self.refresh_context();
            }
            Command::DeleteSelectedKeys => {
                if self.camera_mode() {
                    global::delete_selected(&mut self.pmm)?;
                } else {
                    let (i, s) = self.keyed()?;
                    let auto = self.edit.auto_interpolation;
                    model::delete(
                        &mut self.pmm.models[i],
                        &s,
                        &mut self.edit.models[i],
                        auto,
                        frame,
                    )?;
                }
                self.refresh_context();
            }
            Command::Undo | Command::Redo => {
                if self.camera_mode() {
                    return Err(not("undo is model mode only"));
                }
                let i = self.active_model()?;
                let h = &mut self.edit.models[i].history;
                let m = &mut self.pmm.models[i];
                let to = if cmd == Command::Undo {
                    if !h.undo_dirty {
                        return Err(not("nothing to undo"));
                    }
                    h.undo(m)
                } else {
                    if !h.redo_dirty {
                        return Err(not("nothing to redo"));
                    }
                    h.redo(m)
                };
                if let Some(f) = to {
                    self.pmm.timeline.current_frame = f as i32;
                }
                // `RedoKeyframeEdit` seeks unless the entry it redid is a pose.
                let h = &self.edit.models[i].history;
                if cmd == Command::Redo && !matches!(h.undo[h.cursor], history::Entry::BonePose(_))
                {
                    self.refresh_context();
                }
            }
            Command::LoadMotion(data) => {
                let vmd =
                    mds_formats::vmd::Vmd::read(&data).map_err(|e| Error::Format(e.to_string()))?;
                if !self.camera_mode() {
                    let (i, s) = self.keyed()?;
                    if Self::motion_model_name(&vmd.model_name.raw).is_err() {
                        return Err(not("the motion is camera and light data (a message box)"));
                    }
                    let r = model::load_vmd(
                        &mut self.pmm.models[i],
                        &s,
                        &mut self.edit.models[i],
                        &vmd,
                        &data,
                        frame,
                    );
                    self.bump_last_registered(i);
                    let mode = self.pmm.physics.playback_mode;
                    refresh::seek_model(&mut self.pmm.models[i], &self.models[i], frame, mode);
                    return r;
                }
                let r = global::load_vmd(&mut self.pmm, &vmd);
                refresh::camera(&mut self.pmm);
                refresh::light(&mut self.pmm);
                refresh::self_shadow(&mut self.pmm, &mut self.edit.self_shadow_mode);
                refresh::gravity(&mut self.pmm);
                r?;
            }
            Command::LoadPose(data) => {
                if self.camera_mode() {
                    return Ok(());
                }
                let (i, s) = self.keyed()?;
                let h = &mut self.edit.models[i].history;
                pose_file::load_vpd(&mut self.pmm.models[i], &s, h, &data)?;
            }
            Command::SelectAll(what) => {
                use mds_ops as s;
                let p = &mut self.pmm;
                match what {
                    SelectAll::Bone => s::select_all_bone_frames(p).map_err(ops)?,
                    SelectAll::Display => s::select_all_display_frames(p).map_err(ops)?,
                    SelectAll::Morph => s::select_all_morph_frames(p).map_err(ops)?,
                    SelectAll::Camera => s::select_all_camera_frames(p),
                    SelectAll::Light => s::select_all_light_frames(p),
                    SelectAll::SelfShadow => s::select_all_self_shadow_frames(p),
                    SelectAll::Gravity => s::select_all_gravity_frames(p),
                    SelectAll::Accessory => s::select_all_accessory_frames(p),
                }
            }
            Command::FrameLine { morph, insert } => {
                use mds_ops as f;
                let bones = !morph && !self.camera_mode();
                let mut pose = Vec::new();
                let mut rig = None;
                if bones {
                    let m = &self.pmm.models[self.active_model()?];
                    // The rebuild needs the bone count of the file; a delete
                    // that rebuilds nothing runs without it.
                    if !insert
                        && self.edit.auto_interpolation
                        && model::line_delete_rebuilds(m, frame)
                    {
                        let (i, s) = self.keyed()?;
                        rig = Some(model::rig(&self.pmm.models[i], &s, true));
                    }
                    let m = &self.pmm.models[self.active_model()?];
                    pose = model::selection_snapshot(m);
                }
                let p = &mut self.pmm;
                let undo = match (morph, insert) {
                    (false, true) => f::insert_bone_camera_frame_line(p),
                    (false, false) => f::delete_bone_camera_frame_line(p, rig.as_ref()),
                    (true, true) => f::insert_morph_light_frame_line(p).map(|()| None),
                    (true, false) => f::delete_morph_light_frame_line(p).map(|()| None),
                }
                .map_err(ops)?;
                if bones {
                    // No key moved: the C++ returns before the undo entry and the seek.
                    let Some(keys) = undo else { return Ok(()) };
                    let i = self.active_model()?;
                    self.edit.models[i].history.push(history::Entry::BoneKeys {
                        frame,
                        pose,
                        keys,
                    });
                    self.refresh_context();
                } else if !self.camera_mode() {
                    self.refresh_context();
                } else if morph {
                    refresh::light(&mut self.pmm);
                } else {
                    refresh::camera(&mut self.pmm);
                }
            }
            Command::LoadModel { path, data } => {
                let file = parse_model(&path, &data)?;
                if self.camera_mode() && !refresh::model_mode_supported(&self.pmm) {
                    return Err(not(
                        "leaving camera mode with a camera parent or reference (not ported)",
                    ));
                }
                let slot = (0..=254u8)
                    .find(|s| self.pmm.models.iter().all(|m| m.slot != *s))
                    .ok_or(not("every model slot is taken"))?;
                // `CB_ADDSTRING` after the camera entry and the models before.
                let combo = self.pmm.models.len() as u8 + 1;
                let m = add_model::record(slot, &path, &file, combo)?;
                let at = self.pmm.models.partition_point(|m| m.slot < slot);
                self.skeletons.insert(at, model::Skeleton::new(&file, &m));
                self.pmm.models.insert(at, m);
                self.models.insert(at, file);
                self.edit.models.insert(at, ModelEdit::default());
                self.pmm.selected_model_slot = slot;
                if self.camera_mode() {
                    refresh::rebuild_model_mode(&mut self.pmm, &mut self.edit.self_shadow_mode);
                }
                self.pmm.timeline.edit_mode = 0;
            }
            Command::CenterPositionBias(offset) => {
                let (i, f) = self.ops_model()?;
                self.push_marked_undo(i);
                mds_ops::center_position_bias(&mut self.pmm, &f, offset).map_err(ops)?;
                self.seek(i);
            }
            Command::RemoveUnusedKeys => {
                let n = self.remove_unused()?;
                self.edit.reported = Some(n);
            }
            Command::ShiftLipFrames(shift) => {
                let (i, f) = self.ops_model()?;
                mds_ops::shift_lip_frames(&mut self.pmm, &f, shift).map_err(ops)?;
                self.seek(i);
            }
            Command::DeleteLipFrames | Command::DeleteEyeFrames | Command::DeleteEyebrowFrames => {
                let (i, f) = self.ops_model()?;
                let p = &mut self.pmm;
                match cmd {
                    Command::DeleteLipFrames => mds_ops::delete_lip_frames(p, &f),
                    Command::DeleteEyeFrames => mds_ops::delete_eye_frames(p, &f),
                    _ => mds_ops::delete_eyebrow_frames(p, &f),
                }
                .map_err(ops)?;
                self.seek(i);
            }
            Command::RegisterBlinks { start, end } => {
                let (_, f) = self.ops_model()?;
                let e = &mut self.edit;
                let n = mds_ops::random_blinks(
                    &mut self.pmm,
                    &f,
                    start,
                    end,
                    &mut e.rand,
                    &mut e.blink_phase,
                )
                .map_err(ops)?;
                e.reported = Some(n);
            }
            Command::ResetMorphs => {
                if self.camera_mode() {
                    return Err(not("the menu is grayed out in camera mode"));
                }
                mds_ops::reset_morphs(&mut self.pmm).map_err(ops)?;
            }
            Command::RegisterAllMorphFrames => {
                let (i, f) = self.ops_model()?;
                let r = mds_ops::register_all_morph_frames(&mut self.pmm, &f).map_err(ops);
                self.seek(i);
                r?;
            }
            Command::MultiplyCamera(p) => {
                mds_ops::multiply_camera_frames(&mut self.pmm, &p).map_err(ops)?;
                // `ReloadModels` (`timeline_advance.cpp` 178): the camera
                // follows its keys.
                refresh::camera(&mut self.pmm);
            }
            Command::MultiplyBone(p) => {
                let (i, _) = self.ops_model()?;
                self.push_marked_undo(i);
                mds_ops::multiply_bone_frames(&mut self.pmm, &p).map_err(ops)?;
                self.seek(i);
            }
            Command::MultiplyMorph { scale, add } => {
                let (i, _) = self.ops_model()?;
                mds_ops::multiply_morph_frames(&mut self.pmm, scale, add).map_err(ops)?;
                self.seek(i);
            }
            Command::SetKeyPhysics { disabled } => {
                let (i, f) = self.ops_model()?;
                self.push_physics_undo(i, &f);
                mds_ops::set_physics_on_off(&mut self.pmm, &f, disabled).map_err(ops)?;
                self.seek(i);
            }
            Command::ScaleFrames(p) => {
                let (i, f) = self.ops_model()?;
                let r = mds_ops::scale_frame_range(&mut self.pmm, &f, &p).map_err(ops);
                self.seek(i);
                r?;
            }
            Command::ClickFrame(f) => self.click_frame(f),
            Command::SetEditMode(mode) => self.pmm.timeline.edit_mode = mode,
            Command::SelectAllBones => self.select_all_bones()?,
            Command::SelectUnregisteredBones => self.select_unregistered_bones()?,
            Command::ResetBonePose => self.reset_bone_pose()?,
            Command::CopyBonePose => self.copy_bone_pose()?,
            Command::PasteBonePose { mirror } => self.paste_bone_pose(mirror)?,
            Command::SetCameraParentModel(slot) => self.set_camera_parent_model(slot),
            Command::SetCameraParentBone(bone) => self.set_camera_parent_bone(bone)?,
            Command::SetModelFlag { flag, on } => {
                let i = self.active_model()?;
                let m = &mut self.pmm.models[i];
                let field = match flag {
                    ModelFlag::Visible => &mut m.selection.load_complete,
                    ModelFlag::Shadow => &mut m.toon,
                    ModelFlag::AddBlend => &mut m.post_load,
                };
                *field = u8::from(on);
            }
            Command::SetIkEnabled { chain, on } => {
                let i = self.active_model()?;
                *self.pmm.models[i]
                    .ik_pose
                    .get_mut(chain as usize)
                    .ok_or(not("no such IK chain"))? = u8::from(on);
            }
            Command::SetPanelExpanded { panel, expanded } => {
                if !(1..=6).contains(&panel) {
                    return Err(not("no such panel"));
                }
                self.pmm.settings.options[usize::from(panel)] = u8::from(expanded);
            }
            Command::SetPlayback {
                looped,
                return_to_start,
                from_current,
                start_frame,
                stop_frame,
            } => {
                let t = &mut self.pmm.timeline;
                t.playback_loop = u8::from(looped);
                t.return_to_start = u8::from(return_to_start);
                t.start_at_current = u8::from(from_current);
                t.play_start_frame = start_frame;
                t.play_stop_frame = stop_frame;
            }
            Command::SetViewOption { option, on } => {
                let p = &mut self.pmm;
                *match option {
                    ViewOption::Information => &mut p.view.fps_overlay,
                    ViewOption::CoordinateAxis => &mut p.view.ground_grid,
                    ViewOption::GroundShadow => &mut p.view.ground_shadow,
                    ViewOption::GroundShadowTransparency => &mut p.physics.projected_shadow_blend,
                    ViewOption::SelfShadow => &mut p.self_shadow_mode,
                    ViewOption::BlackBackground => &mut p.appearance.black_background,
                } = u8::from(on);
            }
            Command::SetFpsLimit(fps) => self.pmm.view.fps_limit = fps,
            Command::SetRenderSize { width, height } => {
                let [w, h] = self.edit.max_texture_size.unwrap_or([i32::MAX; 2]);
                if width > w || height > h {
                    return Err(not("too big for your PC! (a message box)"));
                }
                self.pmm.settings.render_width = width;
                self.pmm.settings.render_height = height;
            }
            Command::SetFollowCamera(on) => self.set_follow_camera(on),
            Command::SetEdgeScale(v) => {
                if self.camera_mode() {
                    return Err(not("the edge thickness is a model-mode setting"));
                }
                let i = self.active_model()?;
                self.pmm.models[i].edge_scale = v;
            }
            Command::SetOutlineColor(c) => {
                self.pmm.appearance.outline_color = c.map(i32::from);
            }
            Command::CopyInterpolationCurve { channel } => self.copy_curve(channel)?,
            Command::PasteInterpolationCurve { channel } => self.write_curve(channel, false)?,
            Command::ResetInterpolationCurves { channel } => self.write_curve(channel, true)?,
            Command::SetKeyInterpolation {
                channel,
                end,
                point,
            } => self.set_curve_point(channel, end, point)?,
            Command::ToggleDisplayGroup(g) => self.toggle_display_group(g)?,
            Command::ReplaceKeySelection { track, from, to } => {
                self.clear_mode_marks(track)?;
                return self.apply_inner(Command::SelectKeys { track, from, to });
            }
            Command::SetTimelineStart(f) => self.pmm.timeline.start_frame = f,
            Command::SetTrackListScroll(v) => match self.active().filter(|_| !self.camera_mode()) {
                Some(i) => self.pmm.models[i].selection.bone_list_pos = v,
                None => self.pmm.display_list_scroll = v,
            },
            Command::ZeroBoneRotationAxis { axis, degrees } => {
                self.zero_bone_rotation_axis(axis, degrees)?
            }
            Command::DeleteAccessory(slot) => self.delete_accessory(slot)?,
            Command::MoveSelectedKeys(delta) => self.move_selected_keys(delta)?,
            Command::DeleteModel(slot) => self.delete_model(slot)?,
            Command::SetCameraReference(mode) => self.set_camera_reference(mode)?,
            Command::SetEnglishName { name, text } => self.set_english_name(name, &text)?,
            Command::SetToonFileNames(names) => {
                let names: &[String; 10] = names
                    .as_slice()
                    .try_into()
                    .map_err(|_| not("not ten toon names"))?;
                self.set_toon_file_names(names)?
            }
            Command::SetPhysicsModel { rigids, joints } => {
                self.set_physics_model(rigids, joints)?
            }
            Command::SetModelPath { slot, path } => self.set_model_path(slot, &path)?,
            Command::ApplyOutsideParent { selector, parent } => {
                self.apply_outside_parent(selector, parent)?
            }
            Command::RegisterOutsideParents(records) => self.register_outside_parents(&records)?,
            Command::CloseOutsideParentDialog => {
                if std::mem::take(&mut self.edit.outside_parent_applied) {
                    self.seek(self.active_model()?);
                }
            }
            Command::SetModelDrawOrder(slots) => {
                self.set_model_draw_order(&slots)?;
                self.apply_inner(Command::SelectCameraMode)?;
            }
            Command::SetModelCalcOrder(slots) => self.set_model_calc_order(&slots)?,
            Command::SetAccessoryOrder(slots) => self.set_accessory_order(&slots)?,
            Command::RenameAccessory { slot, name } => self.rename_accessory(slot, &name)?,
            Command::SetAccessoryRenderSplit(n) => {
                let count = self.pmm.accessories.len() as i32;
                self.pmm.physics.accessory_render_order = n.clamp(0, count);
            }
            Command::BeginBoneEdit => {
                let i = self.active_model()?;
                model::push_pose_edit(&self.pmm.models[i], &mut self.edit.models[i].history);
            }
            Command::DragBonePose {
                bone,
                translation,
                rotation,
            } => {
                let i = self.active_model()?;
                let p = self.pmm.models[i]
                    .bone_pose
                    .get_mut(bone as usize)
                    .ok_or(not("no such bone"))?;
                p.translation = translation;
                p.rotation = rotation;
                p.flags[1] = 1;
            }
            Command::SetViewOffset([x, y]) => {
                self.pmm.camera_state[3] = x;
                self.pmm.camera_state[4] = y;
            }
            Command::EditPhysicsRecord {
                joint,
                index,
                field,
                axis,
                dy,
            } => self.edit_physics_record(joint, index, field, axis, dy)?,
            Command::LoadBackgroundMovie { path, data } => {
                self.load_background_movie(&path, &data)?
            }
            Command::LoadBackgroundPicture { path, data } => {
                self.load_background_picture(&path, &data)?
            }
            Command::ShowBackgroundMovie(on) => {
                let a = &mut self.pmm.avi;
                if !on || !a.path.text.is_empty() {
                    a.enabled = u32::from(on);
                }
            }
            Command::ShowBackgroundPicture(on) => {
                let p = &mut self.pmm.picture;
                if !on || !p.path.text.is_empty() {
                    p.enabled = u32::from(on);
                }
            }
            Command::DeleteKey => return self.apply_inner(Command::DeleteSelectedKeys),
            Command::SetPhysicsMode(m) => {
                if m > 3 {
                    return Err(not("no such physics mode"));
                }
                self.pmm.physics.playback_mode = m;
            }
            Command::SetCaptureMode(mode) => {
                if !(0..=3).contains(&mode) {
                    return Err(not("no such capture mode"));
                }
                self.pmm.view.capture_mode = mode;
            }
            Command::SetFloorVisible(on) => self.pmm.appearance.floor_visible = u8::from(on),
            Command::SetPhysicsCheckbox(on) => self.edit.physics_checkbox = on,
            Command::SetCameraFromMenu {
                position,
                rotation,
                distance,
            } => {
                if !self.camera_mode() {
                    return Err(not(
                        "the camera path of menus 300 and 302 is camera mode only",
                    ));
                }
                let s = &mut self.pmm.camera_state;
                s[..3].copy_from_slice(&position);
                s[5] = distance;
                s[6..].copy_from_slice(&rotation);
            }
            Command::SetSelfShadowSlider(position) => {
                self.pmm.physics_interval = (f64::from(10000 - position) / 100000.0) as f32;
            }
            Command::RegisterKinectCapture {
                frame,
                samples,
                keys,
            } => {
                if self.camera_mode() {
                    return Err(not("the Kinect pump is model mode only"));
                }
                let i = self.active_model()?;
                let r = model::register_capture(
                    &mut self.pmm.models[i],
                    &mut self.edit.models[i],
                    frame,
                    samples,
                    &keys,
                );
                if !matches!(r, Err(Error::NotApplicable(_))) {
                    self.seek(i);
                    self.bump_last_registered(i);
                }
                r?;
            }
            Command::SetAccessoryAdditive(on) => {
                let slot = self.pmm.selected_accessory_slot;
                if let Ok(a) = global::accessory(&mut self.pmm, slot) {
                    a.state.additive = u8::from(on);
                }
            }
            Command::NewScene => {
                self.pmm = new_scene::reset(&self.pmm);
                self.models.clear();
                self.skeletons.clear();
                self.edit = EditState {
                    self_shadow_mode: shadow_mode_at(&self.pmm),
                    auto_interpolation: self.edit.auto_interpolation,
                    physics_checkbox: self.edit.physics_checkbox,
                    rand: self.edit.rand,
                    blink_phase: self.edit.blink_phase,
                    max_texture_size: self.edit.max_texture_size,
                    viewport: self.edit.viewport,
                    ..EditState::default()
                };
                // The refresh tail of `ResetAppState`.
                refresh::camera(&mut self.pmm);
                refresh::light(&mut self.pmm);
                refresh::self_shadow(&mut self.pmm, &mut self.edit.self_shadow_mode);
                refresh::gravity(&mut self.pmm);
            }
        }
        Ok(())
    }
}

/// A PMD by its extension, else a PMX.
fn parse_model(path: &str, data: &[u8]) -> Result<ModelFile, Error> {
    let format = |e: mds_formats::Error| Error::Format(format!("{path}: {e}"));
    Ok(if path.to_ascii_lowercase().ends_with(".pmd") {
        ModelFile::Pmd(Box::new(Pmd::read(data).map_err(format)?))
    } else {
        ModelFile::Pmx(Box::new(Pmx::read(data).map_err(format)?))
    })
}

/// `RefreshSelfShadowPanel` (VA 0x00411B90): the mode of the self-shadow
/// key at the current frame, else of the key before it.
fn shadow_mode_at(pmm: &Pmm) -> u8 {
    let pool = &pmm.self_shadow;
    let frame = pmm.timeline.current_frame as u32;
    let Ok(i) = global::walk(pool, 0, frame) else {
        return POST_PROCESS_SHADOW_MODE;
    };
    let k = pool.get(i);
    let k = match k {
        Some(k) if k.frame != frame => pool.get(k.previous),
        k => k,
    };
    k.map_or(0, |k| k.mode)
}
