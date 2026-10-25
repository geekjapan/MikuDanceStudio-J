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
//! * Pose, physics and render state are never stored. The PMM's saved pose
//!   block is the pose the user edits and "register" stores; commands
//!   change it, nothing evaluates into it.
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
//! The load-side normalization of `pmm_load_v2.cpp` (flags read as
//! `b == 1`, `RefreshSelfShadowPanel` after load), the pose re-evaluation of
//! `SeekModelFrame` on a frame change, range scaling (`ChainedBoneKeys`
//! undo entries), and the `mds-edit` paths it reports as
//! [`mds_edit::Error::Unsupported`] (the pose of a bone with a rigid body,
//! fixed-axis twist, automatic interpolation).

pub mod global;
pub mod history;
pub mod model;
pub mod new_scene;
pub mod save;

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
    /// Moves the current frame. In model mode with a bone edited and not
    /// registered, `SnapshotPoseBeforeFrameChange` pushes an undo entry.
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
            let format = |e: mds_formats::Error| Error::Format(format!("{path}: {e}"));
            models.push(match read(path) {
                None => ModelFile::Missing,
                Some(b) if path.to_ascii_lowercase().ends_with(".pmd") => {
                    ModelFile::Pmd(Box::new(Pmd::read(&b).map_err(format)?))
                }
                Some(b) => ModelFile::Pmx(Box::new(Pmx::read(&b).map_err(format)?)),
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

    pub fn apply(&mut self, cmd: Command) -> Result<(), Error> {
        let frame = self.frame();
        match cmd {
            Command::SelectModel(slot) => {
                if !self.pmm.models.iter().any(|m| m.slot == slot) {
                    return Err(not("no model in that slot"));
                }
                self.pmm.selected_model_slot = slot;
                self.pmm.settings.options[0] = 0;
            }
            Command::SelectCameraMode => self.pmm.settings.options[0] = 1,
            Command::SetFrame(f) => {
                if let (false, Some(i)) = (self.camera_mode(), self.active()) {
                    let m = &self.pmm.models[i];
                    model::push_frame_change(m, &mut self.edit.models[i].history, frame);
                }
                self.pmm.timeline.current_frame = f as i32;
            }
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
            Command::NewScene => {
                self.pmm = new_scene::reset(&self.pmm);
                self.models.clear();
                self.skeletons.clear();
                self.edit = EditState {
                    self_shadow_mode: shadow_mode_at(&self.pmm),
                    auto_interpolation: self.edit.auto_interpolation,
                    ..EditState::default()
                };
            }
        }
        Ok(())
    }
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
