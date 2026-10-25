//! The MME runtime of `third_party/mmeffect` on wgpu: it takes an effect that `mds-mme` loaded
//! and planned, compiles its passes through `mds-shader`, creates its resources, and executes
//! its technique scripts with real render passes.
//!
//! Ported from `third_party/mmeffect/src/mmeffect/`: `sas_exec.cpp` (the technique walk and
//! the script commands: `RenderColorTarget0..3`, `RenderDepthStencilTarget`, `ClearSetColor`,
//! `ClearSetDepth`, `Clear`, `ScriptExternal`, `Pass`, `LoopByCount`, `LoopGetIndex`,
//! `LoopEnd`, `Draw=Geometry`, `Draw=Buffer`), `sas_interpreter.cpp`
//! (`SasEnsureResourceTexture`, as `mds-mme` models it), `pass_planner.cpp` (the host draws:
//! `SasHostRunPass`, `SasDefaultDrawBufferPass`), and `material_bind.cpp`
//! (`ClassifySemantic`, `MmeBindSemanticParameters`, `MmeBindMaterialParameter`,
//! `MmeBindBooleanParameter`).
//!
//! # API
//!
//! - [`Gpu`]: a wgpu device whose errors are collected, never raised.
//! - [`Effect::load`]: parse, SAS-parse, create the resources ([`resource`]), and compile every
//!   pass ([`shader`]) of one `.fx`. A pass that cannot compile keeps its error in
//!   [`Effect::programs`]; its draws are recorded and skipped.
//! - [`Target`]: the back buffer and depth stencil (1000x600, the oracle's device).
//! - [`Model`]: the vertex and index buffers and material subsets `Draw=Geometry` draws.
//! - [`Scene`]: the camera, light, clocks, and viewport the parameters bind to.
//! - [`Effect::frame`]: one frame that runs every technique in scan order, as the plan's
//!   `runs` section does, on one device, and returns those lines.
//!
//! # Not ported
//!
//! - EMM and EMD files (`emm_manager.cpp`) and the `DefaultEffect` assignment of offscreen
//!   targets: an offscreen target is created and can be bound, but nothing renders into it
//!   with another effect.
//! - Animated textures (`anime_texture.cpp`), texture shaders (`Function`/`Target`),
//!   `CONTROLOBJECT` lookups (the parameters keep their initial values), the effect cache and
//!   context (`effect_engine.cpp`, `mme_context.cpp`), multisampled targets (`AntiAlias`),
//!   automatic mip generation of `Miplevels=0` targets.
//! - The scene render at `ScriptExternal`: the walk suspends and resumes, and draws nothing
//!   in between.
//! - Skinned and morphed geometry: `Model::from_pmx` is the bind pose. `mds-render` keeps its
//!   GPU device, mesh buffers, and skinning crate-private; this crate builds its own until
//!   `mds-render` exposes them.
//! - Pixel-center alignment: wgpu samples at pixel centers where D3D9 is half a pixel off.

pub mod bind;
pub mod emm;
mod exec;
mod gpu;
pub mod model;
pub mod resource;
pub mod shader;
mod state;

pub use bind::Scene;
pub use exec::{Device, DrawInput, Effect, LoadError, Program, Run, RunState, Target};
pub use gpu::Gpu;
pub use model::Model;

/// The oracle's back buffer: the size `mds-mme` resolves `ViewportRatio` against.
pub const BACKBUFFER: (u32, u32) = (1000, 600);

/// What [`Effect::frame`] did.
pub struct FrameReport {
    /// The `runs` section lines without `log` lines, as the plan writes them.
    pub runs: String,
    pub draws: u32,
    /// Draws that reached the GPU.
    pub drawn: u32,
    /// Why the other draws were skipped.
    pub skipped: Vec<String>,
}

impl Effect {
    /// Runs every non-empty technique in scan order on one device, with `SasCreateRunState`,
    /// the step walk to `ScriptExternal`, and the resumed walk, then submits the frame.
    pub fn frame(&mut self, gpu: &Gpu, target: &Target, input: &DrawInput) -> FrameReport {
        let mut dev = Device::new(gpu, self, target);
        // The host's BeginScene clear of the back buffer and its depth stencil.
        dev.clear_main(input.scene.background);
        let mut report = FrameReport {
            runs: String::from("runs\n"),
            draws: 0,
            drawn: 0,
            skipped: Vec::new(),
        };
        for tech in 0..self.sas.techniques.len() {
            if self.sas.techniques[tech].empty {
                continue;
            }
            self.sas.run_failed = false;
            let name = mds_mme::plan::q(&self.sas.techniques[tech].name);
            report.runs.push_str(&format!("  run {name}\n"));
            let mut st = RunState::new(&dev, input.scene.background);
            report
                .runs
                .push_str(&format!("    start {}\n", dev.bindings()));
            let mut run = Run {
                gpu,
                effect: self,
                dev: &mut dev,
                input,
                tech,
                draws: 0,
                drawn: 0,
                out: String::new(),
                skipped: Vec::new(),
            };
            let (_, suspended) = run.walk(&mut st, true);
            if suspended {
                let b = run.dev.bindings();
                run.out.push_str(&format!("    suspend {b}\n"));
            }
            let hr = if run.effect.sas.run_failed {
                mds_mme::run::E_FAIL
            } else {
                run.walk(&mut st, false).0
            };
            let (draws, drawn) = (run.draws, run.drawn);
            report.runs.push_str(&run.out);
            report.skipped.append(&mut run.skipped);
            report
                .runs
                .push_str(&format!("    end {}\n", dev.bindings()));
            report.runs.push_str(&format!(
                "    result suspended={} draws={draws} hr=0x{hr:08x} runfailed={}\n",
                u8::from(suspended),
                u8::from(self.sas.run_failed)
            ));
            report.draws += draws;
            report.drawn += drawn;
        }
        gpu.queue.submit([dev.encoder.finish()]);
        report
    }
}
