//! Port of the per-frame pose of the C++ x64 app: key application, bone
//! morphs, the bone hierarchy, append (grant) transforms, outside parents and
//! CCD IK, as the L2 trace mode (`src/tools/trace_mode.cpp`) runs them.
//!
//! The scene is a PMM plus its model files. [`Scene::new`] does what the
//! PMM load and `ArmFrameStep` leave behind (trace frame 0);
//! [`Scene::step`] runs one frame-step pass (`PlaybackCatchup` then
//! `PhysicsFrame`, timeline time `+1/30 s`). `new` and `step` are the
//! physics-off driver (physics mode 0). The physics modes step a Bullet
//! world between the pose passes; `mds-physics` drives them from
//! [`Scene::load`], [`Scene::arm_frame_step`], [`Scene::ordered_pass`] and
//! [`Scene::advance_keys`].
//!
//! * [`model`]: the bone, IK, selector and morph tables of the loaders.
//! * [`keys`]: `SeekModelFrame`, `InitModelTrackCursors`, `AdvanceModelKeyframes`.
//! * [`pose`]: `ModelApplyMorphs`, `SetPhysicsMode`, `BoneFrameTransform`.
//! * [`trace`]: the `bone`, `bonew` and `morph` lines of trace format 1, L2.

pub mod keys;
pub mod model;
pub mod pose;
pub mod trace;

use mds_formats::pmm::Pmm;
use mds_formats::{pmd::Pmd, pmx::Pmx};
use model::Model;
use pose::Others;

/// `kModelSlotCount` of the x64 build.
const SLOT_COUNT: usize = 255;

pub struct Scene {
    /// Loaded models in slot order.
    pub models: Vec<Model>,
    /// `PlaybackPhysicsMode`: 0 off, 1 always on, 2 on/off by bone key,
    /// 3 the on/off mode with blends out of physics.
    pub physics_mode: i32,
    /// `recordedFrameCount`, the frame-step pass counter.
    pub passes: i32,
    /// `PlaybackCursorSeconds`.
    pub cursor: f32,
}

impl Scene {
    /// Loads the PMM's models through `read` (the model path as stored in
    /// the PMM, to the file bytes) and sets up trace frame 0. Physics mode 0
    /// only.
    pub fn new(
        pmm: &Pmm,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<Scene, String> {
        let mut scene = Scene::load(pmm, read)?;
        if scene.physics_mode != 0 {
            return Err(format!(
                "physics mode {} needs mds-physics",
                scene.physics_mode
            ));
        }
        scene.arm_frame_step();
        Ok(scene)
    }

    /// The PMM load: the models with their key tracks and saved pose, in
    /// slot order.
    pub fn load(
        pmm: &Pmm,
        mut read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<Scene, String> {
        let physics_mode = i32::from(pmm.physics.playback_mode);
        if !(0..=3).contains(&physics_mode) {
            return Err(format!("bad physics mode {physics_mode}"));
        }
        let mut models = Vec::with_capacity(pmm.models.len());
        for source in &pmm.models {
            let path = source.path.text.as_str();
            let data = read(path)?;
            let mut model = if path.to_ascii_lowercase().ends_with(".pmd") {
                Model::from_pmd(
                    source.slot,
                    &Pmd::read(&data).map_err(|e| format!("{path}: {e}"))?,
                )
            } else {
                Model::from_pmx(
                    source.slot,
                    &Pmx::read(&data).map_err(|e| format!("{path}: {e}"))?,
                )
            }
            .map_err(|e| format!("{path}: {e}"))?;
            model.apply_pmm(source)?;
            models.push(model);
        }
        models.sort_by_key(|m| m.slot);
        if models.windows(2).any(|w| w[0].slot == w[1].slot)
            || models.iter().any(|m| usize::from(m.slot) >= SLOT_COUNT)
        {
            return Err("bad model slots".into());
        }
        Ok(Scene {
            models,
            physics_mode,
            passes: 0,
            cursor: 0.0,
        })
    }

    /// `ArmFrameStep` of the trace mode: seek every model to frame 0,
    /// `UpdateBoneFrames` (the track cursors at cursor 0) and one pose pass.
    pub fn arm_frame_step(&mut self) {
        self.cursor = 0.0;
        for model in &mut self.models {
            keys::seek_model_frame(model, 0, self.physics_mode);
        }
        for model in &mut self.models {
            keys::init_track_cursors(model, self.cursor, self.physics_mode);
        }
        self.passes = 0;
        self.ordered_pass(0, self.physics_mode);
    }

    /// The model part of `PlaybackPoseAdvance`: the keys at the cursor.
    pub fn advance_keys(&mut self) {
        for model in &mut self.models {
            keys::advance_model_keyframes(model, self.cursor, self.physics_mode);
        }
    }

    /// The per-model morph and pose pass in calculation order
    /// (`OrderedMorphPhysicsPass`, the two passes of `PhysicsFrame`).
    pub fn ordered_pass(&mut self, after: u8, physics_mode: i32) {
        for order in 0..SLOT_COUNT {
            for i in 0..self.models.len() {
                if usize::from(self.models[i].order) != order {
                    continue;
                }
                let (before, rest) = self.models.split_at_mut(i);
                let (model, after_models) = rest.split_first_mut().unwrap();
                pose::apply_morphs(model);
                let others = Others {
                    models: [before, after_models],
                };
                pose::set_physics_mode(model, after, &others, physics_mode);
            }
        }
    }

    /// The frame-step target of the next pass at 30 fps: the pass count
    /// goes up and the cursor time is returned.
    pub fn next_target(&mut self) -> f32 {
        self.passes += 1;
        let term = (self.passes as f32 * 30.0) / 30.0 + 0.0;
        term / 30.0
    }

    /// One frame-step pass at 30 fps with physics off: `PlaybackCatchup`
    /// (key application at the new cursor) then `PhysicsFrame` (two pose
    /// passes).
    pub fn step(&mut self) {
        self.cursor = self.next_target();
        self.advance_keys();
        self.ordered_pass(0, 0);
        self.ordered_pass(1, 0);
    }
}
