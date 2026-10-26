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
//! The C++ builds its one world at `WM_CREATE` (`SceneConstruct`, `src/window/ui_init.cpp:219`),
//! and the first paint (`UpdateWindow`, `src/window/window_init.cpp:423`) spends the 1/60 s the
//! new world's substep clock starts at. A PMM named on the command line loads before that paint
//! (`LoadSceneFile`, `window_init.cpp:402`), into the fresh world ([`Editor::startup`],
//! [`PhysicsScene::open`]); every later load (File > Open, a drop, a model load, a new scene)
//! loads into a world that has spent it ([`Editor::open`], [`PhysicsScene::open_running`]). The
//! clock remainder that wall-clock pumps leave in the C++ world is not carried into a new one.
//!
//! Gate A of `PhysicsFrame` (`src/physics/physics_frame.cpp:688`) skips the whole stopped pump
//! once the message counter `messageSeen` has decayed to 0. `AdvanceFrameRenderGate`
//! (`src/app/frame_driver.cpp:61`) holds it at 1 while playing, while menu 299
//! (`FrameVolumeControlEnabled`) is off, and while the English names dialog is open; otherwise
//! it walks 1, 2, 3, 0, and every window message sets it to 1 ([`Editor::message`]).
//!
//! The view camera is the C++ camera state (app+0x310, [`scene::state_camera`]): in the camera
//! view a seek, a frame step and the playback put the track's camera there, and an edit that
//! moves the state (the camera panel, a paste or delete of camera keys) shows it before any key is
//! registered. The model view turns about its reference point with the view offsets in the eye
//! ([`model_view`]) and keeps its camera over seeks and playback.
//! The light is the light state (`light_state`, which the light panel edits and a camera-mode seek
//! moves to the track, `RefreshAfterFrameApply`) except in camera mode and while playing with
//! camera tracking on: `PlaybackPoseAdvance` plays the light track only behind the same gate as
//! the camera's (`src/app/timeline_advance.cpp:389-394`), and `UpdateBoneFrames` starts it only
//! there (`InitGlobalTracks`, `src/app/playback_state.cpp:327`). In camera mode the track at the
//! frame on screen stands for the state a seek put there ([`Editor::light`]).
//! While playing, the C++ greys out every register path (`PlaybackActive() == 0` gates of
//! `src/app/key_ladder.cpp` and `src/app/pump_edit_keys.cpp`, `DisablePlaybackMenus`), so
//! [`Editor::apply`] refuses the register commands then, and no edit seeks the playing world.
//!
//! A recording ([`record`]) is a playback too: it plays the frame steps of the AVI frame rate
//! instead of the wall clock, and writes each frame before the step. [`Editor::playing`] is
//! true while it runs. The loaded WAV ([`Editor::wave`]) plays along with playback and frame
//! moves ([`audio`]).
//!
//! The effects ([`Editor::mme`]) follow the document's objects: autoloaded with the PMM
//! ([`Mme::autoload`]), assigned again when the models or accessories change, written beside the
//! PMM on save with Auto Save Mapping File on (`MmeAutoSaveEmmForPmm`,
//! `third_party/mmeffect/src/mmeffect/emm_manager.cpp`), and with Auto Reload on loaded again when
//! their file changes, polled every 100 ms (`mme_ui.cpp`). A recording draws through them when
//! they are active.

use crate::mme::{self, Mme, View};
use crate::playback::{self, Options, Pass, Playback};
use crate::record::{self, Recording};
use crate::scene::{self, read_model, Assets, Shot};
use crate::ui::dialog::AviSettings;
use crate::ui::viewport::pan_view_offset;
use crate::{audio, file};
use mds_doc::{Command, Document, ModelFile};
use mds_media::wav::Wave;
use mds_physics::PhysicsScene;
use mds_render::{Camera, Frame, Light, Stage};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

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
    pub recording: Option<Recording>,
    /// The document's WAV (`LoadWaveFile`), when it loads as PCM.
    pub wave: Option<Arc<Wave>>,
    /// The MME effects of the document's objects.
    pub mme: Mme,
    /// When Auto Reload last polled the effect files.
    last_reload_ms: u64,
    last_pump_ms: Option<u64>,
    /// An edit while playing left the live models' keys behind the document's.
    keys_stale: bool,
    /// The bytes of the models `Command::LoadModel` added, by stored path: the physics world is
    /// built again from them, wherever the file was.
    loaded: HashMap<String, Vec<u8>>,
    /// Menu 299 on and the English names dialog closed: gate A may close ([`Editor::message`]).
    /// The window sets it every pass.
    pub low_power: bool,
    /// `messageSeen`.
    message_seen: u8,
    /// Menu 285's ground body. The C++ builds its world once (`SceneConstruct`,
    /// `src/window/ui_init.cpp:219`) and keeps it across scene and model loads, and a PMM load
    /// leaves the ground alone (`pmm_load_v2.cpp:2366` only sets its deactivation time), so each
    /// new world here gets the last menu state again. On at start-up (`app_defaults.cpp:173`).
    floor: bool,
}

impl Editor {
    /// `doc` as the application starts with it, before the first paint.
    pub fn new(doc: Document, path: Option<PathBuf>) -> Result<Editor, String> {
        Editor::build(doc, path, false)
    }

    fn build(doc: Document, path: Option<PathBuf>, running: bool) -> Result<Editor, String> {
        let dir = path
            .as_deref()
            .and_then(Path::parent)
            .unwrap_or(Path::new("."))
            .to_path_buf();
        let read = |p: &str| read_model(&dir, p);
        let physics = match running {
            true => PhysicsScene::open_running(&doc.pmm, read)?,
            false => PhysicsScene::open(&doc.pmm, read)?,
        };
        let current = doc.pmm.timeline.current_frame.max(0) as u32;
        Ok(Editor {
            mme: Mme::autoload(&doc, path.as_deref()),
            last_reload_ms: 0,
            assets: Assets::load(&doc, &dir)?,
            wave: wave_of(&doc, &dir),
            recording: None,
            camera: match model_view(&doc, &physics.scene.models) {
                Some(c) => c,
                None => view_camera(
                    &doc,
                    &physics.scene.models,
                    true,
                    scene::track_camera(&doc, current)?,
                ),
            },
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
            low_power: false,
            message_seen: 1,
            floor: true,
        })
    }

    /// The PMM at `path` opened in the running application (File > Open, a drop), for
    /// [`Editor::adopt`]: the edit state the file does not hold (the auto-interpolation and
    /// physics check boxes) is the startup's, and the world has spent its first 1/60 s.
    pub fn open(path: &Path) -> Result<Editor, String> {
        Editor::read(path, true)
    }

    /// The PMM at `path` named on the command line, as `mds-app <pmm>` starts: [`Editor::open`]
    /// before the first paint, into a fresh world.
    pub fn startup(path: &Path) -> Result<Editor, String> {
        Editor::read(path, false)
    }

    fn read(path: &Path, running: bool) -> Result<Editor, String> {
        let mut doc = file::read(path)?;
        let startup = Document::startup().edit;
        doc.edit.auto_interpolation = startup.auto_interpolation;
        doc.edit.physics_checkbox = startup.physics_checkbox;
        Editor::build(doc, Some(path.to_path_buf()), running)
    }

    /// The scene the application starts with ([`Document::startup`]: the empty scene, with
    /// automatic interpolation on as `checkPhysicsFrame` sets it, `src/window/window_init.cpp`).
    pub fn empty() -> Editor {
        Editor::new(Document::startup(), None).expect("the startup scene opens")
    }

    /// `fresh`, a scene just opened (`LoadSceneFile`), takes this editor's place with what the C++
    /// keeps across a scene load: the auto-interpolation and physics check boxes
    /// (`Document::load_scene` keeps them too), the physics menus of its one world, the clock of
    /// the frame loop and gate A, and the MMEffect menu state, runtime library and log.
    pub fn adopt(&mut self, mut fresh: Editor) -> Result<(), String> {
        let (old, new) = (&self.doc.edit, &mut fresh.doc.edit);
        new.auto_interpolation = old.auto_interpolation;
        new.physics_checkbox = old.physics_checkbox;
        fresh.last_pump_ms = self.last_pump_ms;
        fresh.low_power = self.low_power;
        fresh.message_seen = self.message_seen;
        fresh.floor = self.floor;
        fresh.reapply_physics_menus(self.physics.always_on_off)?;
        fresh.physics_opens += self.physics_opens;
        let (old, new) = (&mut self.mme, &mut fresh.mme);
        new.switches = old.switches;
        new.vkd3d = old.vkd3d.take();
        new.backbuffer = old.backbuffer;
        let mut log = old.log.take();
        log.append(new.log.get_mut());
        *new.log.get_mut() = log;
        *self = fresh;
        Ok(())
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

    /// The frame on screen: the playback or recording cursor's while playing.
    pub fn shown_frame(&self) -> u32 {
        if let Some(r) = &self.recording {
            return cursor_frame(r.cursor);
        }
        self.playback.map_or(self.current_frame(), |p| p.frame())
    }

    /// Playing or recording.
    pub fn playing(&self) -> bool {
        self.playback.is_some() || self.recording.is_some()
    }

    /// The view camera at `frame` of the camera track, where the C++ draws from the camera: in
    /// camera mode, and with camera tracking on while playing or with the camera's parent model
    /// selected (`cameraView`, `src/render/debug_geometry.cpp:476`). The model view keeps its
    /// camera over seeks and playback (`RefreshAfterFrameApply` moves the camera state in camera
    /// mode only), and with it the view offsets the pans moved it by.
    fn follow_track(&mut self, frame: u32) -> Result<(), String> {
        let p = &self.doc.pmm;
        let a = &p.appearance;
        let parent_selected =
            a.camera_parent_model >= 0 && a.camera_parent_model == i32::from(p.selected_model_slot);
        let camera_view = p.settings.options[0] != 0
            || a.follow_camera != 0 && (self.playing() || parent_selected);
        if camera_view {
            let state = scene::track_camera(&self.doc, frame)?;
            self.camera = view_camera(&self.doc, &self.physics.scene.models, true, state);
        } else if a.follow_camera != 0 {
            self.camera = model_view(&self.doc, &self.physics.scene.models).unwrap_or(self.camera);
        }
        Ok(())
    }

    fn stopped(&self) -> Result<(), String> {
        match self.playing() {
            true => Err("not while playing".into()),
            false => Ok(()),
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
                | ClearBoneMarks
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
        // Asked before the command runs: a paste's clipboard gate reads the document as it was.
        let dirty = self.doc.marks_modified(&cmd);
        let new_scene = cmd == NewScene;
        let bodies = matches!(cmd, SetPhysicsModel { .. });
        let follow = matches!(cmd, ClickFrame(_));
        let (physics_mode, floor) = match cmd {
            SetPhysicsMode(m) => (Some(m), None),
            SetFloorVisible(on) => (None, Some(on)),
            _ => (None, None),
        };
        if let LoadModel { path, data } = &cmd {
            self.loaded.insert(path.clone(), data.clone());
        }
        let wave = match &cmd {
            LoadWave { data, .. } => Some(Wave::from_bytes(data.clone())),
            _ => None,
        };
        let (files, camera) = (Files::of(&self.doc), scene::state_camera(&self.doc));
        let camera_mode = self.doc.pmm.settings.options[0];
        let selection = matches!(cmd, SelectModel(_));
        self.doc.apply(cmd).map_err(|e| e.to_string())?;
        if (self.doc.pmm.settings.options[0] != camera_mode || selection) && !self.playing() {
            // The other view: the camera state, or the model view about its reference point.
            self.camera = model_view(&self.doc, &self.physics.scene.models).unwrap_or_else(|| {
                view_camera(
                    &self.doc,
                    &self.physics.scene.models,
                    true,
                    scene::state_camera(&self.doc),
                )
            });
        }
        if let Some(m) = physics_mode {
            // `ModelKinematicSync` of every model (`command_view_menu.cpp:1048` to `:1110`).
            self.physics.set_physics_mode(m)?;
        }
        if let Some(on) = floor {
            // The ground body's collision flags (`command_view_menu.cpp:1437`).
            self.floor = on;
            self.physics.set_floor_visible(on)?;
        }
        if let Some(w) = wave {
            audio::stop();
            self.wave = None;
            if self.doc.pmm.wave.enabled != 0 {
                self.wave = Some(Arc::new(w.map_err(|e| format!("WAV: {e:?}"))?));
            }
        }
        if new_scene {
            self.rebuild()?;
            self.modified = false;
            return Ok(());
        }
        let now = Files::of(&self.doc);
        if bodies {
            // `CommitPhysicsEdits` puts the edited bodies into the world: it is built again from
            // the edited PMDs.
            for (m, f) in self.doc.pmm.models.iter().zip(&self.doc.models) {
                if let ModelFile::Pmd(pmd) = f {
                    let bytes = pmd.write().map_err(|e| e.to_string())?;
                    self.loaded.insert(m.path.text.clone(), bytes);
                }
            }
        }
        if now.models != files.models || bodies {
            self.models_changed()?;
        }
        if now.accessories != files.accessories {
            self.assets.accessories = Assets::load_accessories(&self.doc, &self.dir);
            self.mme.objects_changed(&self.doc);
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
                self.camera =
                    model_view(&self.doc, &self.physics.scene.models).unwrap_or_else(|| {
                        view_camera(&self.doc, &self.physics.scene.models, true, moved)
                    });
            }
        }
        Ok(())
    }

    /// The world again from the document, after a new scene.
    fn rebuild(&mut self) -> Result<(), String> {
        self.playback = None;
        audio::stop();
        self.wave = wave_of(&self.doc, &self.dir);
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
        let always_on_off = self.physics.always_on_off;
        self.physics = PhysicsScene::open_running(&self.doc.pmm, read)?;
        self.physics_opens += 1;
        self.reapply_physics_menus(always_on_off)?;
        self.sync_physics_pose();
        self.mme.objects_changed(&self.doc);
        Ok(())
    }

    /// The menu state the C++ keeps in its one world onto a new world: the floor (285) and
    /// `playbackAlwaysOnOffMode` (271, `command_view_menu.cpp:1163`, cleared only at start-up,
    /// `app_defaults.cpp:239`).
    fn reapply_physics_menus(&mut self, always_on_off: bool) -> Result<(), String> {
        self.physics.always_on_off = always_on_off;
        match self.floor {
            true => Ok(()),
            false => self.physics.set_floor_visible(false),
        }
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
        audio::frame_moved(self.wave.as_ref(), frame);
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
        audio::frame_moved(self.wave.as_ref(), frame);
        self.follow_track(frame)
    }

    /// The play button 408 (`ApplyPlaybackRangeEdits`, `src/window/command_frame_edit.cpp:622`).
    pub fn toggle_play(&mut self, now_ms: u64) -> Result<(), String> {
        if self.recording.is_some() {
            return Err("not while recording".into());
        }
        if let Some(p) = self.playback.take() {
            return self.stop(&p);
        }
        let t = &self.doc.pmm.timeline;
        let (current, last) = (t.current_frame, t.last_registered_frame);
        let p = Playback::start(&self.options, current, last, now_ms);
        let frame_changed = self.options.from_current || self.options.start_frame == current;
        self.physics.start_playback(p.start, frame_changed);
        self.playback = Some(p);
        audio::play_from(self.wave.as_ref(), p.start);
        self.follow_track(p.frame())
    }

    /// `StopPlayback`: the current frame after the stop, every model at it, and a settle.
    fn stop(&mut self, p: &Playback) -> Result<(), String> {
        self.stop_at(p.cursor)
    }

    /// [`Editor::stop`] with the cursor at `cursor` seconds; the sound stops too.
    fn stop_at(&mut self, cursor: f32) -> Result<(), String> {
        audio::stop();
        let current = self.doc.pmm.timeline.current_frame;
        let frame = playback::stop_frame(&self.options, cursor, current).max(0) as u32;
        self.apply(Command::SetFrame(frame))?;
        if self.keys_stale {
            self.sync_keys()?;
        }
        self.physics.stop_playback(frame);
        self.follow_track(frame)
    }

    /// `LoadVsqFile` of the `.vsq` at `path` onto the selected model (menu 224, a dropped file
    /// when `dropped`; [`Document::lip_sync`]), then the frame the load moved to in the live
    /// models, as a seek. Both callers set `SceneModified` after the load, whatever it did
    /// (`command_file_menu.cpp:1169`, `ui_dropfiles.cpp:261`). The `.txt` it writes beside the VSQ
    /// ([`mds_vsq::txt_path`]) is a text-mode file, with CRLF lines on Windows. The inner `Err` is
    /// a load that stopped, whose message box is the caller's.
    pub fn lip_sync(
        &mut self,
        path: &Path,
        dropped: bool,
    ) -> Result<Result<(), mds_vsq::Stop>, String> {
        self.stopped()?;
        let vsq = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let run = self.doc.lip_sync(&vsq, dropped);
        if run.is_ok() || !dropped {
            self.modified = true;
        }
        // The keys, the frame and the timeline start change even when a key fails to register.
        self.sync_keys()?;
        let frame = self.current_frame();
        self.physics.seek(frame);
        self.follow_track(frame)?;
        let run = run.map_err(|e| e.to_string())?;
        let name = path.to_string_lossy();
        let txt = mds_vsq::txt_path(&name).ok_or("a VSQ path without .vsq")?;
        let mut text = Vec::with_capacity(run.txt.len());
        for &b in &run.txt {
            if cfg!(windows) && b == b'\n' {
                text.push(b'\r');
            }
            text.push(b);
        }
        std::fs::write(&txt, text).map_err(|e| format!("{txt}: {e}"))?;
        Ok(run.outcome.map(|_| ()))
    }

    /// Menu 278, restore texture (`command_view_menu.cpp:1343`): every texture file read again
    /// ([`Assets::reload_textures`]); returns the files found that did not decode.
    pub fn reload_textures(&mut self) -> Vec<(String, String)> {
        self.assets.reload_textures(&self.doc, &self.dir)
    }

    /// The physics reset, menu 268 (`MDS_CMD_RESET_PHYSICS_BODIES`).
    pub fn reset_physics(&mut self) {
        self.physics.reset();
    }

    /// A window message (`MainWndProc` entry): gate A opens for the next pumps.
    pub fn message(&mut self) {
        self.message_seen = 1;
    }

    /// `AdvanceFrameRenderGate` (`src/app/frame_driver.cpp:61`); whether the stopped pump runs
    /// `PhysicsFrame`.
    fn render_gate(&mut self) -> bool {
        if self.playing() || !self.low_power {
            self.message_seen = 1;
        }
        self.message_seen = match self.message_seen {
            1 => 2,
            2 => 3,
            _ => 0,
        };
        self.message_seen != 0
    }

    fn sync_physics_pose(&mut self) {
        for (m, e) in self.doc.pmm.models.iter().zip(&mut self.doc.edit.models) {
            e.physics_pose = self
                .physics
                .scene
                .models
                .iter()
                .find(|p| p.slot == m.slot)
                .map(|p| {
                    p.bones
                        .iter()
                        .map(|b| {
                            let k = b.ik_backup;
                            ([k[3], k[4], k[5], k[6]], [k[0], k[1], k[2]])
                        })
                        .collect()
                });
        }
    }

    /// One window pass at wall-clock `now_ms`; see the module doc.
    pub fn pump(&mut self, now_ms: u64) -> Result<(), String> {
        let result = self.pump_inner(now_ms);
        self.sync_physics_pose();
        result
    }

    fn pump_inner(&mut self, now_ms: u64) -> Result<(), String> {
        let dt = self
            .last_pump_ms
            .map_or(0.0, |t| now_ms.saturating_sub(t) as f32 * 0.001);
        self.last_pump_ms = Some(now_ms);
        let gate = self.render_gate();
        if self.mme.switches.auto_reload && now_ms >= self.last_reload_ms + 100 {
            self.last_reload_ms = now_ms;
            self.mme.reload_changed();
        }
        if let Some(mut r) = self.recording.take() {
            if std::mem::take(&mut r.pending) {
                // The pass of the menu command: a stopped `PhysicsFrame`, then section 10 arms
                // the frame steps.
                let start = r.settings.start_frame;
                self.recording = Some(r);
                self.physics.tick(dt)?;
                let current = self.doc.pmm.timeline.current_frame;
                self.physics
                    .start_playback(playback::frame_to_seconds(start), start == current);
                return Ok(());
            }
            return match self.record_pass(&mut r) {
                Ok(true) => {
                    self.recording = Some(r);
                    Ok(())
                }
                Ok(false) => self.finish_recording(r),
                Err(e) => {
                    let _ = self.finish_recording(r);
                    Err(e)
                }
            };
        }
        let Some(mut p) = self.playback else {
            return match gate {
                true => self.physics.tick(dt),
                false => Ok(()),
            };
        };
        match p.pass(&self.options, now_ms) {
            Pass::Playing => {
                self.playback = Some(p);
                self.physics.catch_up(p.cursor, dt)?;
            }
            Pass::Looped => {
                self.playback = Some(p);
                audio::play_from(self.wave.as_ref(), p.start);
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

    /// Starts a recording to `path` (`RecordStartTail`, see [`record`]): the models at the start
    /// frame now; the next pump is the pass that arms the frame steps (section 10 of
    /// `FrameDriver`), the one after writes the first frame. The current frame stays.
    pub fn start_recording(&mut self, settings: &AviSettings, path: &Path) -> Result<(), String> {
        self.stopped()?;
        let r = Recording::new(settings, path, self.wave.as_ref())?;
        if settings.start_frame != self.doc.pmm.timeline.current_frame {
            self.physics.seek(settings.start_frame.max(0) as u32);
        }
        audio::stop();
        self.recording = Some(r);
        self.follow_track(self.shown_frame())
    }

    /// Esc while recording (`PumpEscStop`): `FinishAviRecord` now.
    pub fn stop_recording(&mut self) -> Result<(), String> {
        match self.recording.take() {
            Some(r) => self.finish_recording(r),
            None => Ok(()),
        }
    }

    /// One pass of a recording: the frame at the cursor written, N counted, then the frame step
    /// to the next target, or `false` past the end frame.
    fn record_pass(&mut self, r: &mut Recording) -> Result<bool, String> {
        let frame = cursor_frame(r.cursor);
        self.follow_track(frame)?;
        let shot = Shot {
            physics: &self.physics,
            frame,
            camera: &self.camera,
            size: r.size(),
            samples: &mds_render::SAMPLES_8X,
            picture_viewport: None,
        };
        let px = match self.mme.active() {
            true => self.mme.render(
                &self.doc,
                &self.physics,
                &self.view_while(frame, r.size(), 1.0 / r.settings.fps, true)?,
            )?,
            false => {
                let light = self.light_while(frame, true)?;
                scene::with_stage_lit(&self.doc, &self.assets, &shot, light, |f, s| {
                    mds_render::render_frame_with(r.gpu(), f, s)
                })??
            }
        };
        r.write(&px)?;
        r.n += 1;
        let s = &r.settings;
        if !record::records(r.n, s.start_frame, s.end_frame, s.fps) {
            return Ok(false);
        }
        r.cursor = record::term(r.n, s.start_frame, s.fps) / 30.0;
        self.physics.catch_up(r.cursor, 1.0 / s.fps)?;
        Ok(true)
    }

    /// `FinishAviRecord`: the file closed, then `StopPlayback` at the cursor.
    fn finish_recording(&mut self, r: Recording) -> Result<(), String> {
        let cursor = r.cursor;
        let closed = r.finish();
        self.stop_at(cursor)?;
        closed
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
        if self.mme.switches.auto_save {
            // `MmeAutoSaveEmmForPmm` saves on its own, after the PMM: a failure is only logged.
            let emm = mme::emm_path(path);
            if let Err(e) = std::fs::write(&emm, self.mme.save_emm(&self.doc)) {
                let line = format!("{}: {e}", emm.display());
                self.mme.log.borrow_mut().push(line);
            }
        }
        self.path = Some(path.to_path_buf());
        self.modified = false;
        Ok(())
    }

    /// The light of `frame` on screen; see the module doc.
    pub fn light(&self, frame: u32) -> Result<Light, String> {
        self.light_while(frame, self.playing())
    }

    /// [`Editor::light`] with `playing` for [`Editor::playing`], which a recording pass, holding
    /// its recording out of the editor, cannot ask.
    fn light_while(&self, frame: u32, playing: bool) -> Result<Light, String> {
        let p = &self.doc.pmm;
        let track = p.settings.options[0] != 0 || p.appearance.follow_camera != 0 && playing;
        if !track {
            let s = p.light_state;
            return Ok(Light {
                color: [s[0], s[1], s[2]],
                direction: [s[3], s[4], s[5]],
            });
        }
        mds_render::scene::light_at(p, frame).ok_or_else(|| format!("light track at frame {frame}"))
    }

    /// The MME view of the frame on screen from the view camera: `frame` at `size`, `elapsed`
    /// seconds after the last.
    pub fn view(&self, frame: u32, size: [u32; 2], elapsed: f32) -> Result<View<'_>, String> {
        self.view_while(frame, size, elapsed, self.playing())
    }

    /// [`Editor::view`] with `playing` as [`Editor::light_while`].
    fn view_while(
        &self,
        frame: u32,
        size: [u32; 2],
        elapsed: f32,
        playing: bool,
    ) -> Result<View<'_>, String> {
        let l = self.light_while(frame, playing)?;
        let ([r, g, b], [x, y, z]) = (l.color, l.direction);
        Ok(View {
            camera: &self.camera,
            light: [r, g, b, x, y, z],
            frame,
            elapsed,
            size,
        })
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
        let light = self.light(shot.frame)?;
        scene::with_stage_lit(&self.doc, &self.assets, &shot, light, draw)
    }
}

/// The stopped model view, including its reference pivot and saved attachment basis.
fn model_view(doc: &Document, models: &[mds_pose::model::Model]) -> Option<Camera> {
    let p = &doc.pmm;
    if p.settings.options[0] != 0 {
        return None;
    }
    let camera_view = p.appearance.follow_camera != 0
        && p.appearance.camera_parent_model >= 0
        && p.appearance.camera_parent_model == i32::from(p.selected_model_slot);
    Some(view_camera(
        doc,
        models,
        camera_view,
        scene::state_camera(doc),
    ))
}

/// `debug_geometry.cpp:476-566`: focus, attachment rotation and fixed-view eye offsets.
fn view_camera(
    doc: &Document,
    models: &[mds_pose::model::Model],
    camera_view: bool,
    mut camera: Camera,
) -> Camera {
    use mds_math::Mat4;
    let p = &doc.pmm;
    let a = &p.appearance;
    let parent = models
        .iter()
        .find(|m| i32::from(m.slot) == a.camera_parent_model)
        .and_then(|m| m.bones.get(a.camera_parent_bone as usize));
    let point = |b: &mds_pose::model::Bone| {
        std::array::from_fn(|c| {
            b.mat_init.0[c] * b.position[0]
                + b.mat_init.0[4 + c] * b.position[1]
                + b.mat_init.0[8 + c] * b.position[2]
                + b.mat_init.0[12 + c]
        })
    };
    let mut offsets = [p.camera_state[3], p.camera_state[4]];
    camera.target = if camera_view {
        if let Some(b) = parent {
            offsets = [camera.target[0], camera.target[1]];
            camera.distance = camera.target[2];
            point(b)
        } else {
            offsets = [0.0; 2];
            camera.target
        }
    } else {
        models
            .iter()
            .find(|m| m.slot == p.selected_model_slot)
            .and_then(|m| match p.timeline.camera_reference_mode {
                1 => m
                    .bones
                    .get(m.center_bone)
                    .map(|b| b.mat_init.0[12..15].try_into().unwrap()),
                2 => p
                    .models
                    .iter()
                    .find(|s| s.slot == m.slot)
                    .and_then(|s| m.bones.get(s.selection.selected_bone as usize))
                    .map(point),
                _ => None,
            })
            .unwrap_or([0.0; 3])
    };
    let mut basis = Mat4::IDENTITY;
    if a.follow_camera != 0 || p.settings.options[0] != 0 {
        if let Some(b) = parent.filter(|_| a.suppress_camera_transform == 0) {
            for row in 0..3 {
                for col in 0..3 {
                    basis.0[row * 4 + col] = b.mat_init.0[col * 4 + row];
                }
            }
        }
    } else {
        basis = Mat4(a.camera_attachment_basis);
    }
    if basis != Mat4::IDENTITY {
        let [pitch, yaw, roll] = camera.rotation;
        let r = Mat4::multiply(&Mat4::rotation_y(yaw), &Mat4::rotation_x(pitch));
        let r = Mat4::multiply(&basis, &Mat4::multiply(&r, &Mat4::rotation_z(roll))).0;
        let cosine = r[2].hypot(r[10]);
        let pitch = r[6].atan2(cosine);
        // At the pole yaw and roll share one axis, so retain their combined angle as yaw.
        camera.rotation = if cosine > 0.000001 {
            [pitch, (-r[2]).atan2(r[10]), (-r[4]).atan2(r[5])]
        } else {
            [pitch, r[8].atan2(r[0]), 0.0]
        };
    }
    pan_view_offset(&mut camera, offsets[0], offsets[1]);
    camera
}

/// The whole frame a cursor at `cursor` seconds shows ([`Playback::frame`]).
fn cursor_frame(cursor: f32) -> u32 {
    mds_scene::playback_frame(cursor).map_or(0, |f| f as u32)
}

/// The document's WAV, read from its path, when it is enabled and loads.
fn wave_of(doc: &Document, dir: &Path) -> Option<Arc<Wave>> {
    let w = &doc.pmm.wave;
    if w.enabled == 0 {
        return None;
    }
    let bytes = std::fs::read(scene::resolve(dir, &w.path.text)).ok()?;
    Wave::from_bytes(bytes).ok().map(Arc::new)
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
