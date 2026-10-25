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
//!   names keep zeros after the NUL (`strcpy_s` into a zeroed record).
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
//! * Paths that depend on `mds-edit` gaps: display-key registration on a
//!   model with the root selector (every PMX here), so the model-mode VMD
//!   load and the paste of display keys stop with `Corrupt`; mirrored paste
//!   ("paste reverse"); the pose of a bone with a rigid body; fixed-axis
//!   twist. Automatic interpolation (checkbox 530, on at start-up) is
//!   applied here after `mds-edit` registers or deletes with it off
//!   (`auto_interp`).
//! * VPD load and save, the PMD writer, "paste at a different frame", and
//!   the undo entry of a model-mode frame-line edit.
//! * Leaving camera mode with a camera parent or a reference mode other
//!   than 0, and the model-name fallbacks of the loaders (unmappable
//!   characters, the `Null_NN` names of textures and materials).
//! * Range scaling (`ChainedBoneKeys` undo entries).
//!
//! The script replay of `tests/fixtures/rust/script/` is
//! [`script::Runner`]; `tests/script.rs` compares every save with the C++
//! output.

mod accessory;
mod add_model;
mod auto_interp;
pub mod global;
pub mod history;
pub mod model;
pub mod new_scene;
mod readout;
mod refresh;
pub mod save;
pub mod script;
pub mod vmd_save;

pub use global::{GlobalClipboard, GlobalTrack};
pub use model::ModelClipboard;

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
}

#[derive(Clone, Debug)]
pub struct Document {
    pub pmm: Pmm,
    /// One entry per `pmm.models` entry, in the same order.
    pub models: Vec<ModelFile>,
    pub edit: EditState,
    skeletons: Vec<Option<Skeleton>>,
}

fn ops(e: mds_ops::Error) -> Error {
    Error::Format(format!("{e:?}"))
}

fn not(what: &'static str) -> Error {
    Error::NotApplicable(what)
}

impl Document {
    /// Loads a PMM and the model files it names. `read` maps a model path as
    /// stored in the PMM to the file bytes; a path it cannot read gives
    /// [`ModelFile::Missing`].
    pub fn load(
        data: &[u8],
        mut read: impl FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<Document, Error> {
        let pmm = Pmm::read(data).map_err(|e| Error::Format(e.to_string()))?;
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
            ..EditState::default()
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
                // `checkPhysicsFrame` (`window_init.cpp`) without a config.
                auto_interpolation: true,
                ..EditState::default()
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
        *self = d;
        Ok(())
    }

    /// The bytes `SaveSceneFile` writes for this scene.
    pub fn save(&self) -> Result<Vec<u8>, Error> {
        save::normalize(&self.pmm)
            .write()
            .map_err(|e| Error::Format(e.to_string()))
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
            Command::SetBonePose {
                bone,
                translation,
                rotation,
            } => {
                let i = self.active_model()?;
                let m = &mut self.pmm.models[i];
                if bone as usize >= m.bone_pose.len() {
                    return Err(not("no such bone"));
                }
                model::push_pose_edit(m, &mut self.edit.models[i].history);
                let p = &mut m.bone_pose[bone as usize];
                p.translation = translation;
                p.rotation = rotation;
                p.flags[1] = 1;
            }
            Command::SetMorph { morph, value } => {
                let i = self.active_model()?;
                let m = &mut self.pmm.models[i];
                *m.morph_pose
                    .get_mut(morph as usize)
                    .ok_or(not("no such morph"))? = value;
            }
            Command::BoneReadoutEdit { axis, value } => {
                let (i, s) = self.keyed()?;
                let m = &mut self.pmm.models[i];
                let Ok(b) = usize::try_from(m.selection.selected_bone) else {
                    return Ok(());
                };
                if b >= m.bone_pose.len() || axis > 5 {
                    return Err(not("no such bone or axis"));
                }
                if self.pmm.physics.playback_mode == 3 && s.bones[b].2 {
                    return Err(not(
                        "the readout of a rigid-body bone in physics mode 3 (not ported)",
                    ));
                }
                model::push_pose_edit(m, &mut self.edit.models[i].history);
                let p = &mut m.bone_pose[b];
                let axis = usize::from(axis);
                if axis < 3 {
                    p.translation[axis] = value as f32;
                } else {
                    let deg = readout::euler_degrees(p.rotation);
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
                let r = model::register_bones(
                    &mut self.pmm.models[i],
                    &s,
                    &mut self.edit.models[i],
                    auto,
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
            }
            Command::LoadMotion(data) => {
                let vmd =
                    mds_formats::vmd::Vmd::read(&data).map_err(|e| Error::Format(e.to_string()))?;
                if !self.camera_mode() {
                    let (i, s) = self.keyed()?;
                    let m = &self.pmm.models[i];
                    let name = |raw: &[u8]| raw.split(|&b| b == 0).next().unwrap_or(&[]).to_vec();
                    if name(&vmd.model_name.raw) != name(&m.name.raw) {
                        return Err(not("the motion is for another model (a message box)"));
                    }
                    let r = model::load_vmd(
                        &mut self.pmm.models[i],
                        &s,
                        &mut self.edit.models[i],
                        &vmd,
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
                let p = &mut self.pmm;
                match (morph, insert) {
                    (false, true) => f::insert_bone_camera_frame_line(p),
                    (false, false) => f::delete_bone_camera_frame_line(p),
                    (true, true) => f::insert_morph_light_frame_line(p),
                    (true, false) => f::delete_morph_light_frame_line(p),
                }
                .map_err(ops)?;
                if !self.camera_mode() {
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
            Command::NewScene => {
                self.pmm = new_scene::reset(&self.pmm);
                self.models.clear();
                self.skeletons.clear();
                self.edit = EditState {
                    self_shadow_mode: shadow_mode_at(&self.pmm),
                    auto_interpolation: self.edit.auto_interpolation,
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
