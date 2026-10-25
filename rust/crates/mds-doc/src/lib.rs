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

pub mod save;

use mds_formats::pmd::Pmd;
use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use std::fmt;

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

#[derive(Clone, Debug)]
pub struct Document {
    pub pmm: Pmm,
    /// One entry per `pmm.models` entry, in the same order.
    pub models: Vec<ModelFile>,
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
                Some(bytes) if path.to_ascii_lowercase().ends_with(".pmd") => ModelFile::Pmd(
                    Box::new(Pmd::read(&bytes).map_err(|e| Error::Format(format!("{path}: {e}")))?),
                ),
                Some(bytes) => ModelFile::Pmx(Box::new(
                    Pmx::read(&bytes).map_err(|e| Error::Format(format!("{path}: {e}")))?,
                )),
            });
        }
        Ok(Document { pmm, models })
    }

    /// The bytes `SaveSceneFile` writes for this scene.
    pub fn save(&self) -> Result<Vec<u8>, Error> {
        save::normalize(&self.pmm)
            .write()
            .map_err(|e| Error::Format(e.to_string()))
    }
}
