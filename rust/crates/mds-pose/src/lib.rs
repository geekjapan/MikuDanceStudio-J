//! Port of the per-frame pose of the C++ x64 app: key application, bone
//! morphs, the bone hierarchy, append (grant) transforms, outside parents and
//! CCD IK, as the L2 trace mode (`src/tools/trace_mode.cpp`) runs them.
//!
//! The scene is a PMM plus its model files. [`Scene::new`] does what the
//! PMM load and `ArmFrameStep` leave behind (trace frame 0);
//! [`Scene::step`] runs one frame-step pass (`PlaybackCatchup` then
//! `PhysicsFrame`, timeline time `+1/30 s`). Only physics mode 0 (no
//! calculation) is supported: the rigid bodies belong to `mds-physics`.
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
    physics_mode: i32,
    /// `recordedFrameCount`, the frame-step pass counter.
    passes: i32,
}

impl Scene {
    /// Loads the PMM's models through `read` (the model path as stored in
    /// the PMM, to the file bytes) and sets up trace frame 0.
    pub fn new(
        pmm: &Pmm,
        mut read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<Scene, String> {
        let physics_mode = i32::from(pmm.physics.playback_mode);
        if physics_mode != 0 {
            return Err(format!("physics mode {physics_mode} is not supported"));
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
        let mut scene = Scene {
            models,
            physics_mode,
            passes: 0,
        };
        // ArmFrameStep: seek to frame 0, UpdateBoneFrames, one pose pass.
        for model in &mut scene.models {
            keys::seek_model_frame(model, 0);
        }
        for model in &mut scene.models {
            keys::init_track_cursors(model, 0.0);
        }
        scene.ordered_pass(0);
        Ok(scene)
    }

    /// The per-model morph and pose pass in calculation order
    /// (`OrderedMorphPhysicsPass`, the two passes of `PhysicsFrame`).
    fn ordered_pass(&mut self, after: u8) {
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
                pose::set_physics_mode(model, after, &others, self.physics_mode);
            }
        }
    }

    /// One frame-step pass at 30 fps: `PlaybackCatchup` (key application
    /// at the new cursor) then `PhysicsFrame` (two pose passes).
    pub fn step(&mut self) {
        self.passes += 1;
        let term = (self.passes as f32 * 30.0) / 30.0 + 0.0;
        let cursor = term / 30.0;
        for model in &mut self.models {
            keys::advance_model_keyframes(model, cursor);
        }
        self.ordered_pass(0);
        self.ordered_pass(1);
    }
}
