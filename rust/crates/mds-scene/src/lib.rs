//! A bit-exact Rust port of the portable C++ PMM scene evaluator
//! (`EvaluatePmmSceneFrame` in `src/io/pmm_scene_evaluation.cpp`) and its
//! playback sibling, with the trace writer for trace format 1, level L1.
//!
//! The scene is an [`mds_formats::pmm::Pmm`]. The port keeps the C++
//! operation order and `f32`/`f64` types; Rust does not fuse multiply-adds.
//! Every transcendental goes through [`mds_math`], which evaluates in `f64`
//! and rounds once to `f32`, so traces agree across platforms.
//!
//! * [`curve`]: Bezier easing of bone and camera keys.
//! * [`track`]: key lookup and the camera, light, accessory, self-shadow and
//!   gravity evaluators.
//! * [`frame`]: the scene at an integer frame, and the bone, morph and
//!   selector kernels.
//! * [`playback`]: the cursor evaluator at a fractional frame.
//! * [`trace`]: the L1 trace writer.
//!
//! The evaluator reads the PMM only. The C++ loader also resolves each
//! model file; this port does not, because the layout of a PMM v2 model is
//! in the PMM.

pub mod curve;
pub mod frame;
pub mod mds_math;
pub mod playback;
pub mod trace;
pub mod track;

pub use frame::{evaluate_scene_frame, ScenePose};
pub use playback::{advance_playback, playback_frame, start_playback, PlaybackState};

use mds_formats::pmm::Pmm;

/// Reads a PMM file for evaluation. The C++ loader (`SceneSession::Load`)
/// rejects a negative current frame; so does this.
pub fn load_scene(data: &[u8]) -> Result<Pmm, String> {
    let scene = Pmm::read(data).map_err(|e| e.to_string())?;
    if scene.timeline.current_frame < 0 {
        return Err("negative current frame".into());
    }
    Ok(scene)
}
