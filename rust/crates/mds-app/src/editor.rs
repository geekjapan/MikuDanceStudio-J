//! [`Editor`]: the open document and what the window derives from it, driven the way the C++
//! frame loop drives its scene.
//!
//! The document ([`mds_doc::Document`]) is the only state that is saved. The meshes, the live
//! physics world, the view camera and the playback cursor are derived from it and kept here.
//!
//! Each window pass is one [`Editor::pump`]: `PlaybackCatchup` then `PhysicsFrame`
//! (`FrameDriver`, `src/app/frame_driver.cpp:510` and `:518`), on one `mds-physics` world that
//! lives as long as the document:
//!
//! * playing, target not past the end: [`PhysicsScene::catch_up`] (BLOCK 2,
//!   `src/app/playback_catchup.cpp:456`);
//! * past the end with loop on: [`PhysicsScene::loop_restart`] (`PlayingBeyondEnd`,
//!   `playback_catchup.cpp:251`);
//! * past the end with loop off: `StopPlayback` (`playback_catchup.cpp:274`,
//!   `src/app/playback_state.cpp:345`) as [`PhysicsScene::stop_playback`], then
//!   [`PhysicsScene::tick`];
//! * stopped: [`PhysicsScene::tick`] with the pass's real time step (`g_CatchupDtBudget =
//!   DeltaTime`, `playback_catchup.cpp:321`, and `PhysicsFrame`,
//!   `src/physics/physics_frame.cpp:658`).
//!
//! Seeks and frame steps only move the keys and request a settle ([`PhysicsScene::seek`],
//! [`PhysicsScene::step_frame`]); a backward seek keeps the world. The world is built again only
//! when the set of models changes (open, new scene, a model load). The C++ adds the bodies of a
//! loaded model to the world it has (`LoadModelFile`, `src/model/add_model.cpp`); `mds-physics`
//! has no call for that yet, so a model load builds the world again.
//!
//! The view camera is the C++ camera state (app+0x310, [`scene::state_camera`]): a seek, a
//! frame step and the playback put the track's camera there, and an edit that moves the state
//! (the camera panel, a paste or delete of camera keys) shows it before any key is registered.
//! While playing, the C++ greys out every register path (`PlaybackActive() == 0` gates of
//! `src/app/key_ladder.cpp` and `src/app/pump_edit_keys.cpp`, `DisablePlaybackMenus`), so
//! [`Editor::apply`] refuses the register commands then, and no edit seeks the playing world.

use crate::file;
use crate::playback::{Options, Pass, Playback};
use crate::scene::{self, read_model, Assets, Shot};
use mds_doc::{Command, Document};
use mds_physics::PhysicsScene;
use mds_render::{Camera, Frame, Stage};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Editor {
    pub doc: Document,
    /// `EnvFileName`, where Save writes. New scene keeps it, as `ResetAppState` does.
    pub path: Option<PathBuf>,
    /// `SceneModified`: set by edits, cleared by load, save and new scene.
    pub modified: bool,
    /// The folder model paths resolve against.
    dir: PathBuf,
    /// The meshes, accessories and picture of the document's files.
    assets: Assets,
    pub physics: PhysicsScene,
    /// How many times the physics world was built for this editor.
    pub physics_opens: usize,
    /// The camera the viewport draws from (the camera-mode view state).
    pub camera: Camera,
    /// The play panel. The PMM stores it in `timeline`, but the document has no command for it yet,
    /// so it is not saved.
    pub options: Options,
    pub playback: Option<Playback>,
    last_pump_ms: Option<u64>,
    /// An edit while playing left the live models' keys behind the document's.
    keys_stale: bool,
    /// The bytes of the models `Command::LoadModel` added, by stored path: the physics world is
    /// built again from them, wherever the file was.
    loaded: HashMap<String, Vec<u8>>,
}

impl Editor {
    pub fn new(doc: Document, path: Option<PathBuf>) -> Result<Editor, String> {
        let dir = path
            .as_deref()
            .and_then(Path::parent)
            .unwrap_or(Path::new("."))
            .to_path_buf();
        let physics = PhysicsScene::open(&doc.pmm, |p| read_model(&dir, p))?;
        let current = doc.pmm.timeline.current_frame.max(0) as u32;
        Ok(Editor {
            assets: Assets::load(&doc, &dir)?,
            camera: scene::track_camera(&doc, current)?,
            options: Options::of(&doc.pmm.timeline),
            doc,
            path,
            modified: false,
            dir,
            physics,
            physics_opens: 1,
            playback: None,
            last_pump_ms: None,
            keys_stale: false,
            loaded: HashMap::new(),
        })
    }

    /// The startup scene with the PMM at `path` opened, as `mds-app <pmm>` starts: the edit
    /// state the file does not hold (the auto-interpolation and physics check boxes) is the
    /// startup's.
    pub fn open(path: &Path) -> Result<Editor, String> {
        let mut doc = file::read(path)?;
        let startup = Document::startup().edit;
        doc.edit.auto_interpolation = startup.auto_interpolation;
        doc.edit.physics_checkbox = startup.physics_checkbox;
        Editor::new(doc, Some(path.to_path_buf()))
    }

    /// The scene the application starts with ([`Document::startup`]: the empty scene, with
    /// automatic interpolation on as `checkPhysicsFrame` sets it, `src/window/window_init.cpp`).
    pub fn empty() -> Editor {
        Editor::new(Document::startup(), None).expect("the startup scene opens")
    }

    /// "Add model" (button 435, a dropped PMD or PMX): `LoadModelFile` on the file at `path`,
    /// stored as given (a relative path names a file of the scene's folder, as the C++ handlers
    /// name one of the exe's). The model takes the first free slot and is selected, drawn after
    /// the models before it; the physics world is built again with its bodies.
    pub fn load_model(&mut self, path: &Path) -> Result<(), String> {
        let path = path.to_string_lossy().into_owned();
        let data = read_model(&self.dir, &path)?;
        self.apply(Command::LoadModel { path, data })
    }

    /// `currentFrame`.
    pub fn current_frame(&self) -> u32 {
        self.doc.pmm.timeline.current_frame.max(0) as u32
    }

    /// The frame on screen: the playback cursor's while playing.
    pub fn shown_frame(&self) -> u32 {
        self.playback.map_or(self.current_frame(), |p| p.frame())
    }

    pub fn playing(&self) -> bool {
        self.playback.is_some()
    }

    fn follow_track(&mut self, frame: u32) -> Result<(), String> {
        self.camera = scene::track_camera(&self.doc, frame)?;
        Ok(())
    }

    fn stopped(&self) -> Result<(), String> {
        match self.playback {
            Some(_) => Err("not while playing".into()),
            None => Ok(()),
        }
    }

    /// Applies a document command and brings the derived state up to date with it.
    pub fn apply(&mut self, cmd: Command) -> Result<(), String> {
        use Command::*;
        // Commands that change no key and no pose the live models read.
        let edit = !matches!(
            cmd,
            SelectModel(_)
                | SelectCameraMode
                | SetFrame(_)
                | SelectBones(_)
                | ClearKeySelection
                | SelectKeys { .. }
                | Copy
                | SelectMorphLane { .. }
                | SelectAccessory(_)
                | ToggleDisplayGroup(_)
                | SetEditMode(_)
                | SelectAllBones
                | SelectUnregisteredBones
                | CopyBonePose
        );
        // Of the rest, those whose C++ handler sets no `SceneModified`: the frame strip click,
        // the pose load (`CmdLoadPose`, `src/window/command_impl.cpp`), the follow-camera switch
        // (menu 247) and the morph reset (menu 230).
        let dirty = edit
            && !matches!(
                cmd,
                ClickFrame(_) | LoadPose(_) | SetFollowCamera(_) | ResetMorphs
            );
        let register = matches!(
            cmd,
            RegisterBoneKeys
                | RegisterMorphKey(_)
                | RegisterDisplayKey
                | RegisterGlobalKeys(_)
                | RegisterAllMorphFrames
                | RegisterBlinks { .. }
        );
        if register {
            self.stopped()?;
        }
        let new_scene = cmd == NewScene;
        let follow = matches!(cmd, ClickFrame(_));
        if let LoadModel { path, data } = &cmd {
            self.loaded.insert(path.clone(), data.clone());
        }
        let (files, camera) = (Files::of(&self.doc), scene::state_camera(&self.doc));
        self.doc.apply(cmd).map_err(|e| e.to_string())?;
        if new_scene {
            self.rebuild()?;
            self.modified = false;
            return Ok(());
        }
        let now = Files::of(&self.doc);
        if now.models != files.models {
            self.models_changed()?;
        }
        if now.accessories != files.accessories {
            self.assets.accessories = Assets::load_accessories(&self.doc, &self.dir);
        }
        if now.picture != files.picture {
            self.assets.picture = scene::picture(&self.doc, &self.dir);
        }
        if edit {
            self.modified |= dirty;
            self.assets.set_edge_scales(&self.doc);
            self.sync_keys()?;
            let moved = scene::state_camera(&self.doc);
            if self.playing() {
                return Ok(());
            }
            if follow {
                self.physics.seek(self.current_frame());
                self.follow_track(self.current_frame())?;
            } else if moved != camera {
                self.camera = moved;
            }
        }
        Ok(())
    }

    /// The world again from the document, after a new scene.
    fn rebuild(&mut self) -> Result<(), String> {
        self.playback = None;
        self.models_changed()?;
        self.assets = Assets::load(&self.doc, &self.dir)?;
        self.options = Options::of(&self.doc.pmm.timeline);
        self.follow_track(self.current_frame())
    }

    /// The meshes and the physics world again, after the set of models changed.
    fn models_changed(&mut self) -> Result<(), String> {
        self.playback = None;
        self.assets.meshes = scene::meshes(&self.doc, &self.dir)?;
        let read = |p: &str| match self.loaded.get(p) {
            Some(b) => Ok(b.clone()),
            None => read_model(&self.dir, p),
        };
        self.physics = PhysicsScene::open(&self.doc.pmm, read)?;
        self.physics_opens += 1;
        Ok(())
    }

    /// The edited keys and the saved pose into the live models (an edit moves the keys in place
    /// in the C++; the world stays). The saved pose is what the window shows: the document puts
    /// the keys' pose there where the C++ handler seeks (a paste, a delete, a motion load), and
    /// leaves an edited pose that is not registered yet, which the C++ keeps on screen until the
    /// frame changes. So no seek here; a settle when the command's C++ handler requests one
    /// (`PhysicsResetPending`). While playing the cursor keeps the frame.
    fn sync_keys(&mut self) -> Result<(), String> {
        if self.playing() {
            // `apply_pmm` puts the saved pose on the bones, which would move the playing world;
            // the keys go in when playback stops.
            self.keys_stale = true;
            return Ok(());
        }
        self.keys_stale = false;
        for source in &self.doc.pmm.models {
            if let Some(m) = self
                .physics
                .scene
                .models
                .iter_mut()
                .find(|m| m.slot == source.slot)
            {
                m.apply_pmm(source)?;
            }
        }
        if std::mem::take(&mut self.doc.edit.physics_reset_pending) {
            self.physics.reset();
        }
        Ok(())
    }

    /// A jump to `frame` while stopped (the frame edit, the timeline strip).
    pub fn seek(&mut self, frame: u32) -> Result<(), String> {
        self.stopped()?;
        self.apply(Command::SetFrame(frame))?;
        self.physics.seek(frame);
        self.follow_track(frame)
    }

    /// `StepFrame` (`src/window/ui_frame_step.cpp`), buttons 418 and 419 and the arrow keys.
    pub fn step_frame(&mut self, forward: bool) -> Result<(), String> {
        self.stopped()?;
        let current = self.current_frame();
        let frame = match forward {
            true => current + 1,
            false if current == 0 => return Ok(()),
            false => current - 1,
        };
        self.apply(Command::SetFrame(frame))?;
        self.physics.step_frame(frame, forward);
        self.follow_track(frame)
    }

    /// The play button 408 (`ApplyPlaybackRangeEdits`, `src/window/command_frame_edit.cpp:622`).
    pub fn toggle_play(&mut self, now_ms: u64) -> Result<(), String> {
        if let Some(p) = self.playback.take() {
            return self.stop(&p);
        }
        let t = &self.doc.pmm.timeline;
        let (current, last) = (t.current_frame, t.last_registered_frame);
        let p = Playback::start(&self.options, current, last, now_ms);
        let frame_changed = self.options.from_current || self.options.start_frame == current;
        self.physics.start_playback(p.start, frame_changed);
        self.playback = Some(p);
        self.follow_track(p.frame())
    }

    /// `StopPlayback`: the current frame after the stop, every model at it, and a settle.
    fn stop(&mut self, p: &Playback) -> Result<(), String> {
        let frame = p
            .stop_frame(&self.options, self.doc.pmm.timeline.current_frame)
            .max(0) as u32;
        self.apply(Command::SetFrame(frame))?;
        if self.keys_stale {
            self.sync_keys()?;
        }
        self.physics.stop_playback(frame);
        self.follow_track(frame)
    }

    /// The physics reset, menu 268 (`MDS_CMD_RESET_PHYSICS_BODIES`).
    pub fn reset_physics(&mut self) {
        self.physics.reset();
    }

    /// One window pass at wall-clock `now_ms`; see the module doc.
    pub fn pump(&mut self, now_ms: u64) -> Result<(), String> {
        let dt = self
            .last_pump_ms
            .map_or(0.0, |t| now_ms.saturating_sub(t) as f32 * 0.001);
        self.last_pump_ms = Some(now_ms);
        let Some(mut p) = self.playback else {
            return self.physics.tick(dt);
        };
        match p.pass(&self.options, now_ms) {
            Pass::Playing => {
                self.playback = Some(p);
                self.physics.catch_up(p.cursor, dt)?;
            }
            Pass::Looped => {
                self.playback = Some(p);
                self.physics.loop_restart(p.start, dt)?;
            }
            Pass::Stopped => {
                self.playback = None;
                self.stop(&p)?;
                return self.physics.tick(dt);
            }
        }
        self.follow_track(p.frame())
    }

    /// Save: to [`Editor::path`]. `Ok(false)` when there is none (the caller asks for one, as
    /// the C++ falls into Save As).
    pub fn save(&mut self) -> Result<bool, String> {
        let Some(path) = self.path.clone() else {
            return Ok(false);
        };
        self.save_as(&path)?;
        Ok(true)
    }

    pub fn save_as(&mut self, path: &Path) -> Result<(), String> {
        file::write(&self.doc, path)?;
        self.path = Some(path.to_path_buf());
        self.modified = false;
        Ok(())
    }

    /// Calls `draw` with the frame on screen at `size`; `samples` as [`Frame::samples`].
    pub fn with_frame<R>(
        &self,
        size: [u32; 2],
        samples: &[[f32; 2]],
        draw: impl FnOnce(&Frame) -> R,
    ) -> Result<R, String> {
        self.with_stage(size, samples, |f, _| draw(f))
    }

    /// [`Editor::with_frame`] with the stage of the frame ([`scene::with_stage`]): shadows,
    /// accessories and the background picture, placed in the whole picture.
    pub fn with_stage<R>(
        &self,
        size: [u32; 2],
        samples: &[[f32; 2]],
        draw: impl FnOnce(&Frame, &Stage) -> R,
    ) -> Result<R, String> {
        let shot = Shot {
            physics: &self.physics,
            frame: self.shown_frame(),
            camera: &self.camera,
            size,
            samples,
            picture_viewport: None,
        };
        scene::with_stage(&self.doc, &self.assets, &shot, draw)
    }
}

/// The files a document names: when they change, the derived meshes are loaded again.
#[derive(PartialEq)]
struct Files {
    models: Vec<(u8, String)>,
    accessories: Vec<(u8, String)>,
    picture: (u32, String),
}

impl Files {
    fn of(doc: &Document) -> Files {
        let p = &doc.pmm;
        Files {
            models: p
                .models
                .iter()
                .map(|m| (m.slot, m.path.text.clone()))
                .collect(),
            accessories: p
                .accessories
                .iter()
                .map(|a| (a.slot, a.path.text.clone()))
                .collect(),
            picture: (p.picture.enabled, p.picture.path.text.clone()),
        }
    }
}
