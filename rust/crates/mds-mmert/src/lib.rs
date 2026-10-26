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
//! - [`Target`]: the back buffer and depth stencil, of the size the effect was loaded for
//!   ([`BACKBUFFER`], the oracle's 1000x600, by default).
//! - [`Model`]: the vertex and index buffers and material subsets `Draw=Geometry` draws, of a PMX,
//!   a PMD or an accessory; [`Model::update`] writes a pose.
//! - [`Scene`]: the camera, light, clocks, and viewport the parameters bind to.
//! - [`Effect::frame`]: one frame that runs every technique in scan order, as the plan's
//!   `runs` section does, on one device, and returns those lines.
//! - [`emm`]: EMM and EMD files (`emm_manager.cpp`): load, apply to the scene's objects, save.
//! - [`control`]: `CONTROLOBJECT` values from the [`control::Controls`] the application fills.
//! - [`anime`]: animated GIF and APNG textures (`anime_texture.cpp`), ticked by
//!   [`Effect::tick_animes`] at the end of each frame.
//! - [`scene`]: what each object draws in an offscreen turn, from the `DefaultEffect` rows;
//!   [`Effect::begin_offscreen`] binds and clears the turn's target, and [`Effect::draw`]
//!   draws one object's effect into it.
//! - [`host`]: the application's side, shared by `mds-app` and the mmegold test: the objects
//!   posed through `mds-skin`, the camera, the turn and draw order of a frame, and the objects
//!   without an effect in `mds-render`'s standard shading.
//! - [`Gpu::from_device`]: the runtime on a window's device.
//!
//! # Not ported
//!
//! - The walk at `ScriptExternal` suspends and resumes with only [`Effect::frame_with_scene`]'s
//!   callback in between ([`host`] draws the scene there). The post-effect turn snapshot
//!   (`pass_planner.cpp:MmeSnapshotMainTargets`) is not ported.
//! - Texture shaders (`Function`/`Target`; `mds-mme` does not model them), the effect cache and
//!   context (`effect_engine.cpp`, `mme_context.cpp`), multisampled targets (`AntiAlias`),
//!   automatic mip generation of `Miplevels=0` targets.
//! - Pixel-center alignment: wgpu samples at pixel centers where D3D9 is half a pixel off.

pub mod anime;
pub mod bind;
pub mod control;
pub mod emm;
mod exec;
mod gpu;
pub mod host;
pub mod model;
pub mod resource;
pub mod scene;
pub mod shader;
mod state;

pub use bind::Scene;
pub use exec::{Device, DrawInput, Effect, LoadError, Program, Run, RunState, Target};
pub use gpu::Gpu;
pub use model::Model;

/// The oracle's back buffer: the size `mds-mme` resolves `ViewportRatio` against.
pub const BACKBUFFER: (u32, u32) = (1000, 600);

/// The host's scene draw at `ScriptExternal`, into the targets bound there.
pub type SceneDraw<'a> = dyn FnMut(&Gpu, &Target) + 'a;

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
        self.run_frame(gpu, target, input, true, None, None)
    }

    /// [`Effect::frame`] that calls `scene` where a technique suspends at `ScriptExternal`, with
    /// the targets the script bound there, so the host draws the scene into them.
    pub fn frame_with_scene(
        &mut self,
        gpu: &Gpu,
        target: &Target,
        input: &DrawInput,
        scene: &mut SceneDraw,
    ) -> FrameReport {
        self.run_frame(gpu, target, input, true, Some(scene), None)
    }

    /// [`Effect::frame`] without the host's clear: the draw of one object into a target other
    /// effects share, such as an offscreen turn's.
    pub fn draw(&mut self, gpu: &Gpu, target: &Target, input: &DrawInput) -> FrameReport {
        self.run_frame(gpu, target, input, false, None, None)
    }

    /// [`Effect::draw`] of technique `tech` alone: the host's draw of one material subset with
    /// the technique `mds_mme::plan::select` picked for its draw mode (`SasExecuteTechnique`).
    pub fn draw_technique(
        &mut self,
        gpu: &Gpu,
        target: &Target,
        input: &DrawInput,
        tech: usize,
    ) -> FrameReport {
        self.run_frame(gpu, target, input, false, None, Some(tech))
    }

    /// `MmeBindStandardParameters` of a host draw that no technique of the effect takes: the
    /// parameters still take the draw's values, as the C++ binds them from every draw snapshot.
    pub fn bind(&mut self, input: &DrawInput) {
        let draw = bind::Draw {
            scene: input.scene,
            material: input.geometry.and_then(|(m, s)| m.materials.get(s)),
            draw_type: input.draw_type,
            subsets: input.geometry.map_or(0, |(m, _)| m.materials.len()),
        };
        bind::bind_semantics(&self.sas.fx.params, &mut self.values, &draw);
    }

    /// The `OFFSCREENRENDERTARGET` resource `r` and its depth stencil as the target of its
    /// turn, cleared as `pass_planner.cpp:MmeApplyPassRecord` does; `None` for another resource.
    /// Each object then draws into it as [`scene::turn_draw`] says.
    pub fn begin_offscreen(&self, gpu: &Gpu, r: usize) -> Option<Target> {
        let res = self.sas.resources.get(r)?;
        if res.semantic != mds_mme::sas::SEM_OFFSCREEN {
            return None;
        }
        let c = self.created[r].as_ref()?;
        let target = Target {
            color: c.texture.clone()?,
            depth: c.depth.clone()?,
        };
        // Without a ClearDepth the Z clear reads 0, the original's uninitialised field.
        target.clear_turn(
            gpu,
            res.has_clear_color.then_some(res.clear_color),
            res.clear_depth,
            res.has_clear_depth,
        );
        Some(target)
    }

    fn run_frame(
        &mut self,
        gpu: &Gpu,
        target: &Target,
        input: &DrawInput,
        clear: bool,
        mut scene: Option<&mut SceneDraw>,
        only: Option<usize>,
    ) -> FrameReport {
        if let Some(c) = input.controls {
            control::resolve(
                &self.sas,
                &mut self.values,
                c,
                input.owner,
                input.offscreen_owner,
            );
        }
        let mut dev = Device::new(gpu, self, target);
        if clear {
            // The host's BeginScene clear of the back buffer and its depth stencil.
            dev.clear_main(input.scene.background);
        }
        let mut report = FrameReport {
            runs: String::from("runs\n"),
            draws: 0,
            drawn: 0,
            skipped: Vec::new(),
        };
        for tech in 0..self.sas.techniques.len() {
            if self.sas.techniques[tech].empty || only.is_some_and(|t| t != tech) {
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
                if let Some(scene) = scene.as_mut() {
                    match run.dev.external_target(gpu) {
                        Ok(t) => scene(gpu, &t),
                        Err(e) => run.skipped.push(e),
                    }
                }
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
