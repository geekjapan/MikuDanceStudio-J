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
//! when the set of models changes (open, new scene).

use crate::file;
use crate::playback::{Options, Pass, Playback};
use crate::scene::{self, read_model};
use mds_doc::{Command, Document};
use mds_physics::PhysicsScene;
use mds_render::{Camera, Frame, Mesh};
use std::path::{Path, PathBuf};

pub struct Editor {
    pub doc: Document,
    /// `EnvFileName`, where Save writes. New scene keeps it, as `ResetAppState` does.
    pub path: Option<PathBuf>,
    /// `SceneModified`: set by edits, cleared by load, save and new scene.
    pub modified: bool,
    /// The folder model paths resolve against.
    dir: PathBuf,
    /// One per document model, in PMM order.
    meshes: Vec<Mesh>,
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
            meshes: scene::meshes(&doc)?,
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
        })
    }

    pub fn open(path: &Path) -> Result<Editor, String> {
        Editor::new(file::read(path)?, Some(path.to_path_buf()))
    }

    /// The scene the application starts with.
    pub fn empty() -> Editor {
        Editor::new(file::empty(), None).expect("the startup scene opens")
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
        let edit = !matches!(
            cmd,
            SelectModel(_)
                | SelectCameraMode
                | SetFrame(_)
                | SelectBones(_)
                | ClearKeySelection
                | SelectKeys { .. }
                | Copy
        );
        let new_scene = cmd == NewScene;
        self.doc.apply(cmd).map_err(|e| e.to_string())?;
        if new_scene {
            self.rebuild()?;
            self.modified = false;
        } else if edit {
            self.modified = true;
            self.sync_keys()?;
        }
        Ok(())
    }

    /// The world again from the document, after the models changed.
    fn rebuild(&mut self) -> Result<(), String> {
        self.playback = None;
        self.meshes = scene::meshes(&self.doc)?;
        self.physics = PhysicsScene::open(&self.doc.pmm, |p| read_model(&self.dir, p))?;
        self.physics_opens += 1;
        self.options = Options::of(&self.doc.pmm.timeline);
        self.follow_track(self.current_frame())
    }

    /// The edited keys and saved pose into the live models, then a seek to the current frame (an
    /// edit moves the keys in place in the C++; the world stays).
    fn sync_keys(&mut self) -> Result<(), String> {
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
        let frame = self.current_frame();
        self.physics.seek(frame);
        self.follow_track(frame)
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
        scene::with_frame(
            &self.doc,
            &self.meshes,
            &self.physics,
            self.shown_frame(),
            &self.camera,
            size,
            samples,
            draw,
        )
    }
}
