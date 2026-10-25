//! The technique walk of `sas_exec.cpp` (`SasCreateRunState`, `SasRunTechniqueWalk`,
//! `SasApplyCommandImpl`, `SasRunPassCommands`) on wgpu, and the host draws of
//! `pass_planner.cpp` (`SasHostRunPass`: the recorded subset for `Draw=Geometry`,
//! `SasDefaultDrawBufferPass` for `Draw=Buffer`).
//!
//! The device model is the one `mds_mme::run` checks against the oracle: four color targets,
//! a depth stencil, and a viewport, with the same names, so [`Device::bindings`] and the draw
//! lines read like the plan's `runs` section. Each clear and each draw is its own render pass.
//!
//! Where wgpu is stricter than D3D9:
//!
//! - A depth surface of another size than color target 0 is replaced, for that draw, by a
//!   scratch depth surface of the target's size (D3D9 uses the corner of the larger one).
//! - A texture bound as a target is not sampled in the same draw: its sampler reads the
//!   placeholder (D3D9 reads undefined texels).
//! - Blending is turned off on formats wgpu cannot blend (32-bit float).

use std::collections::HashMap;

use mds_mme::run::S_OK;
use mds_mme::sas::*;

use crate::anime::Anime;
use crate::bind::{self, Draw};
use crate::control::Controls;
use crate::gpu::Gpu;
use crate::model::{self, Model};
use crate::resource::{self, Created};
use crate::shader::{self, Shader, Slot, Stage};
use crate::state::{self, PassStates};

const INVALIDCALL: u32 = 0x8876_086C;
/// The runtime's synthetic failure code.
const CODE_1: u32 = 1;

pub const MAIN_COLOR: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm;
pub const MAIN_DEPTH: wgpu::TextureFormat = wgpu::TextureFormat::Depth24PlusStencil8;

/// The device's own back buffer and depth stencil.
pub struct Target {
    pub color: wgpu::Texture,
    pub depth: wgpu::Texture,
}

impl Target {
    pub fn new(gpu: &Gpu, (w, h): (u32, u32)) -> Target {
        let t = |label, format, usage| {
            gpu.device.create_texture(&wgpu::TextureDescriptor {
                label: Some(label),
                size: wgpu::Extent3d {
                    width: w,
                    height: h,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format,
                usage,
                view_formats: &[],
            })
        };
        Target {
            color: t("main", MAIN_COLOR, resource::COLOR_USAGE),
            depth: t(
                "main.depth",
                MAIN_DEPTH,
                wgpu::TextureUsages::RENDER_ATTACHMENT,
            ),
        }
    }
}

impl Target {
    /// The back buffer as RGBA8, top row first.
    pub fn read(&self, gpu: &Gpu) -> Result<Vec<u8>, String> {
        let (w, h) = (self.color.width(), self.color.height());
        let padded = (w * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let buf = gpu.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size: u64::from(padded * h),
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        enc.copy_texture_to_buffer(
            self.color.as_image_copy(),
            wgpu::TexelCopyBufferInfo {
                buffer: &buf,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(padded),
                    rows_per_image: Some(h),
                },
            },
            self.color.size(),
        );
        gpu.queue.submit([enc.finish()]);
        let (tx, rx) = std::sync::mpsc::channel();
        buf.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        gpu.wait()?;
        rx.recv()
            .map_err(|e| e.to_string())?
            .map_err(|e| e.to_string())?;
        let mapped = buf
            .slice(..)
            .get_mapped_range()
            .map_err(|e| e.to_string())?;
        let mut out = Vec::with_capacity((w * h * 4) as usize);
        for row in mapped.chunks(padded as usize).take(h as usize) {
            for px in row[..(w * 4) as usize].chunks(4) {
                out.extend([px[2], px[1], px[0], px[3]]);
            }
        }
        Ok(out)
    }
}

/// The two shaders of a pass and what the pipeline needs from them.
pub struct Program {
    vs: std::sync::Arc<Shader>,
    ps: std::sync::Arc<Shader>,
    vs_module: wgpu::ShaderModule,
    ps_module: wgpu::ShaderModule,
    layouts: [wgpu::BindGroupLayout; 2],
    layout: wgpu::PipelineLayout,
    attributes: Vec<wgpu::VertexAttribute>,
    states: PassStates,
}

/// A loaded effect: the plan of `mds-mme`, the wgpu objects of its resources, the programs of
/// its passes, and the parameter values.
pub struct Effect {
    pub sas: Sas,
    fx: mds_fx::Effect,
    /// By resource index; `None` for resources that create no texture.
    pub created: Vec<Option<Created>>,
    /// By technique record, then pass record.
    pub programs: Vec<Vec<Result<Program, String>>>,
    pub values: Vec<Vec<f32>>,
    row_major: Vec<bool>,
    /// The animated textures (`ANIMATEDTEXTURE`) that decoded.
    pub animes: Vec<AnimeTexture>,
    pipelines: HashMap<PipelineKey, wgpu::RenderPipeline>,
    samplers: HashMap<(usize, bool), wgpu::Sampler>,
    placeholders: HashMap<wgpu::TextureViewDimension, wgpu::TextureView>,
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct PipelineKey {
    tech: usize,
    pass: usize,
    buffer: bool,
    cull: u32,
    colors: [Option<wgpu::TextureFormat>; 4],
    depth: Option<wgpu::TextureFormat>,
}

/// Why an effect did not load.
#[derive(Debug)]
pub enum LoadError {
    /// mds-fx could not parse the file.
    Parse(String),
    /// The SAS parse rejected it (the plan's `load rejected`).
    Rejected(String),
    /// A resource has no wgpu equivalent.
    Resource(String),
}

impl std::fmt::Display for LoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LoadError::Parse(e) => write!(f, "parse: {e}"),
            LoadError::Rejected(e) => write!(f, "rejected: {}", e.lines().next().unwrap_or("")),
            LoadError::Resource(e) => write!(f, "resource: {e}"),
        }
    }
}

type ShaderCache = HashMap<(mds_fx::Entry, Stage), Result<std::sync::Arc<Shader>, String>>;

/// One `ANIMATEDTEXTURE` (`MmeAnimeRegisterParsed`): the decoded file and its texture.
pub struct AnimeTexture {
    pub param: usize,
    /// The `SeekVariable` parameter, or `None` for the host frame clock.
    pub seek: Option<usize>,
    pub offset: f64,
    pub speed: f64,
    pub anime: Anime,
    pub texture: wgpu::Texture,
    /// The frame the texture holds.
    pub shown: Option<usize>,
}

impl Effect {
    /// The `sub_18000F3A0` case 45 constructors: a file that does not decode logs the
    /// constructor's message and binds nothing.
    fn load_animes(&mut self, gpu: &Gpu) {
        for r in &self.sas.resources {
            let (SEM_ANIMATED, Some(file)) = (r.semantic, &r.resource_file) else {
                continue;
            };
            let anime = match Anime::open(file) {
                Ok(a) => a,
                Err(e) => {
                    self.sas.log.push_str(&e);
                    continue;
                }
            };
            let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
                label: Some(&r.name),
                size: wgpu::Extent3d {
                    width: anime.width,
                    height: anime.height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8Unorm,
                usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            });
            self.animes.push(AnimeTexture {
                param: r.param,
                seek: self.sas.fx.param_by_name(&r.seek_variable),
                offset: f64::from(r.offset),
                speed: f64::from(r.speed),
                anime,
                texture,
                shown: None,
            });
        }
    }

    /// `MmeAnimeTick`: each animated texture shows the frame of its `SeekVariable` or of the
    /// host frame clock `frame_time`.
    pub fn tick_animes(&mut self, gpu: &Gpu, frame_time: f32) {
        for a in &mut self.animes {
            let time = a
                .seek
                .and_then(|p| self.values[p].first())
                .copied()
                .unwrap_or(frame_time);
            let frame = a.anime.timeline.frame(f64::from(time), a.offset, a.speed);
            if a.shown == Some(frame) {
                continue;
            }
            a.shown = Some(frame);
            let (w, h) = (a.anime.width, a.anime.height);
            gpu.queue.write_texture(
                a.texture.as_image_copy(),
                a.anime.pixels(frame),
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(w * 4),
                    rows_per_image: Some(h),
                },
                a.texture.size(),
            );
        }
    }
}

impl Effect {
    /// `MmeEngineLoadEffectFile` for `path`, with paths resolved below `root` as
    /// [`mds_mme::plan`] does, then the resources and pass programs on `gpu`. `ViewportRatio`
    /// targets are sized against `backbuffer` (width, height).
    pub fn load(
        gpu: &Gpu,
        vk: &mds_shader::vkd3d::Vkd3d,
        path: &std::path::Path,
        root: &std::path::Path,
        backbuffer: (u32, u32),
    ) -> Result<Effect, LoadError> {
        let rel = path
            .strip_prefix(root)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");
        let dir = rel.rsplit_once('/').map_or("", |(d, _)| d).to_string();
        let fx = mds_fx::Effect::parse_file(path).map_err(|e| LoadError::Parse(e.to_string()))?;
        let loc = Location {
            root,
            dir,
            backbuffer: (backbuffer.0 as i32, backbuffer.1 as i32),
        };
        let sas = parse(mds_mme::fx::Fx::new(&fx), &format!("<root>/{rel}"), &loc)
            .map_err(LoadError::Rejected)?;
        let created = sas
            .resources
            .iter()
            .map(|r| resource::create(gpu, r))
            .collect::<Result<Vec<_>, _>>()
            .map_err(LoadError::Resource)?;
        let values = sas.fx.params.iter().map(bind::initial).collect();
        let row_major = fx
            .ast
            .globals
            .iter()
            .filter(|g| !g.modifiers.iter().any(|m| m == "static"))
            .map(|g| g.modifiers.iter().any(|m| m == "row_major"))
            .collect();
        let mut e = Effect {
            sas,
            fx,
            created,
            programs: Vec::new(),
            values,
            row_major,
            animes: Vec::new(),
            pipelines: HashMap::new(),
            samplers: HashMap::new(),
            placeholders: HashMap::new(),
        };
        e.load_animes(gpu);
        let mut cache = ShaderCache::new();
        for t in 0..e.sas.techniques.len() {
            let passes = (0..e.sas.techniques[t].passes.len())
                .map(|p| e.program(gpu, vk, t, p, &mut cache))
                .collect();
            e.programs.push(passes);
        }
        Ok(e)
    }

    /// The `compile` entry of a pass state (`VertexShader`/`PixelShader`).
    fn entry(&self, tech: usize, pass: usize, state: &str) -> Option<mds_fx::Entry> {
        let t = &self.sas.techniques[tech];
        let ast_pass = &self.fx.ast.techniques[t.fx].passes[t.passes[pass].fx];
        ast_pass.states.iter().rev().find_map(|s| match &s.value {
            mds_fx::ast::StateValue::Compile(c) if s.name.eq_ignore_ascii_case(state) => {
                Some(mds_fx::Entry {
                    profile: c.profile.clone(),
                    function: c.function.clone(),
                    args: c.args.clone(),
                    args_text: c.args_text.clone(),
                })
            }
            _ => None,
        })
    }

    fn program(
        &self,
        gpu: &Gpu,
        vk: &mds_shader::vkd3d::Vkd3d,
        tech: usize,
        pass: usize,
        cache: &mut ShaderCache,
    ) -> Result<Program, String> {
        let t = &self.sas.techniques[tech];
        if !t.passes[pass].shader_mix_ok {
            return Err("shader models mixed (the original refuses the pass)".into());
        }
        let mut get = |state: &str, stage: Stage| -> Result<std::sync::Arc<Shader>, String> {
            let entry = self
                .entry(tech, pass, state)
                .ok_or_else(|| format!("no {state} (fixed-function passes are not ported)"))?;
            cache
                .entry((entry.clone(), stage))
                .or_insert_with(|| {
                    shader::compile(vk, &self.fx, &entry, stage)
                        .map(std::sync::Arc::new)
                        .map_err(|e| format!("{} {}: {e}", entry.profile, entry.function))
                })
                .clone()
        };
        let vs = get("VertexShader", Stage::Vertex)?;
        let ps = get("PixelShader", Stage::Fragment)?;
        let provided: Vec<u32> = vs.outputs.iter().map(|l| l.location).collect();
        if let Some(l) = ps.inputs.iter().find(|l| !provided.contains(&l.location)) {
            return Err(format!(
                "the pixel shader reads location {} that the vertex shader does not write",
                l.location
            ));
        }
        let ((vs_module, ps_module), errors) = gpu.scoped(|| {
            let m = |s: &Shader| {
                gpu.device
                    .create_shader_module(wgpu::ShaderModuleDescriptor {
                        label: Some(&s.entry),
                        source: wgpu::ShaderSource::Wgsl(s.wgsl.clone().into()),
                    })
            };
            (m(&vs), m(&ps))
        });
        if let Some(e) = errors.first() {
            return Err(format!("shader module: {e}"));
        }
        let layout_of = |s: &Shader, vis: wgpu::ShaderStages| {
            let entries: Vec<_> = s
                .slots
                .iter()
                .map(|slot| wgpu::BindGroupLayoutEntry {
                    binding: slot.binding(),
                    visibility: vis,
                    ty: match slot {
                        Slot::Uniform { .. } => wgpu::BindingType::Buffer {
                            ty: wgpu::BufferBindingType::Uniform,
                            has_dynamic_offset: false,
                            min_binding_size: None,
                        },
                        Slot::Sampler { comparison, .. } => {
                            wgpu::BindingType::Sampler(if *comparison {
                                wgpu::SamplerBindingType::Comparison
                            } else {
                                wgpu::SamplerBindingType::Filtering
                            })
                        }
                        Slot::Texture { dim, kind, .. } => wgpu::BindingType::Texture {
                            sample_type: match kind {
                                naga::ScalarKind::Sint => wgpu::TextureSampleType::Sint,
                                naga::ScalarKind::Uint => wgpu::TextureSampleType::Uint,
                                _ => wgpu::TextureSampleType::Float { filterable: true },
                            },
                            view_dimension: *dim,
                            multisampled: false,
                        },
                    },
                    count: None,
                })
                .collect();
            gpu.device
                .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                    label: None,
                    entries: &entries,
                })
        };
        let layouts = [
            layout_of(&vs, wgpu::ShaderStages::VERTEX),
            layout_of(&ps, wgpu::ShaderStages::FRAGMENT),
        ];
        let layout = gpu
            .device
            .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: None,
                bind_group_layouts: &[Some(&layouts[0]), Some(&layouts[1])],
                immediate_size: 0,
            });
        let zero_offset = model::STRIDE - 16;
        let attributes = vs
            .inputs
            .iter()
            .map(|l| {
                let (offset, format) = vs
                    .input_semantics
                    .get(&l.location)
                    .and_then(|(u, i)| model::element(u, *i))
                    // Elements the stream lacks read the zero tail of the last additional UV.
                    .unwrap_or((zero_offset, wgpu::VertexFormat::Float32x4));
                wgpu::VertexAttribute {
                    format,
                    offset,
                    shader_location: l.location,
                }
            })
            .collect();
        let t = &self.sas.techniques[tech];
        let ast_pass = &self.fx.ast.techniques[t.fx].passes[t.passes[pass].fx];
        Ok(Program {
            states: PassStates::read(&ast_pass.states),
            vs,
            ps,
            vs_module,
            ps_module,
            layouts,
            layout,
            attributes,
        })
    }

    fn pipeline(&mut self, gpu: &Gpu, key: &PipelineKey) -> Option<&wgpu::RenderPipeline> {
        if !self.pipelines.contains_key(key) {
            let p = self.programs[key.tech][key.pass].as_ref().ok()?;
            let st = &p.states;
            let targets: Vec<Option<wgpu::ColorTargetState>> = key
                .colors
                .iter()
                .enumerate()
                .map(|(i, f)| {
                    f.map(|format| {
                        let written = p.ps.outputs.iter().any(|l| l.location == i as u32);
                        let blendable = format
                            .guaranteed_format_features(gpu.features)
                            .flags
                            .contains(wgpu::TextureFormatFeatureFlags::BLENDABLE);
                        wgpu::ColorTargetState {
                            format,
                            blend: st.blend.filter(|_| blendable),
                            write_mask: if written {
                                st.write_mask[i]
                            } else {
                                wgpu::ColorWrites::empty()
                            },
                        }
                    })
                })
                .collect();
            // Trailing empty slots are not attachments.
            let n = targets
                .iter()
                .rposition(Option::is_some)
                .map_or(0, |i| i + 1);
            let z = st.z_enable && !key.buffer;
            let depth_stencil = key.depth.map(|format| wgpu::DepthStencilState {
                format,
                depth_write_enabled: Some(z && st.z_write),
                depth_compare: Some(if z {
                    st.z_func
                } else {
                    wgpu::CompareFunction::Always
                }),
                stencil: Default::default(),
                bias: Default::default(),
            });
            let buffers = [Some(wgpu::VertexBufferLayout {
                array_stride: model::STRIDE,
                step_mode: wgpu::VertexStepMode::Vertex,
                attributes: &p.attributes,
            })];
            let pipe = gpu
                .device
                .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some(&p.ps.entry),
                    layout: Some(&p.layout),
                    vertex: wgpu::VertexState {
                        module: &p.vs_module,
                        entry_point: Some(&p.vs.entry),
                        compilation_options: Default::default(),
                        buffers: &buffers,
                    },
                    primitive: wgpu::PrimitiveState {
                        front_face: wgpu::FrontFace::Cw,
                        cull_mode: match key.cull {
                            2 => Some(wgpu::Face::Front),
                            3 => Some(wgpu::Face::Back),
                            _ => None,
                        },
                        ..Default::default()
                    },
                    depth_stencil,
                    multisample: Default::default(),
                    fragment: Some(wgpu::FragmentState {
                        module: &p.ps_module,
                        entry_point: Some(&p.ps.entry),
                        compilation_options: Default::default(),
                        targets: &targets[..n],
                    }),
                    multiview_mask: None,
                    cache: None,
                });
            self.pipelines.insert(key.clone(), pipe);
        }
        self.pipelines.get(key)
    }

    fn placeholder(&mut self, gpu: &Gpu, dim: wgpu::TextureViewDimension) -> wgpu::TextureView {
        self.placeholders
            .entry(dim)
            .or_insert_with(|| {
                let (layers, d) = match dim {
                    wgpu::TextureViewDimension::Cube => (6, wgpu::TextureDimension::D2),
                    wgpu::TextureViewDimension::D3 => (1, wgpu::TextureDimension::D3),
                    _ => (1, wgpu::TextureDimension::D2),
                };
                let t = gpu.device.create_texture(&wgpu::TextureDescriptor {
                    label: Some("placeholder"),
                    size: wgpu::Extent3d {
                        width: 1,
                        height: 1,
                        depth_or_array_layers: layers,
                    },
                    mip_level_count: 1,
                    sample_count: 1,
                    dimension: d,
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                    view_formats: &[],
                });
                for z in 0..layers {
                    gpu.queue.write_texture(
                        wgpu::TexelCopyTextureInfo {
                            texture: &t,
                            mip_level: 0,
                            origin: wgpu::Origin3d { x: 0, y: 0, z },
                            aspect: wgpu::TextureAspect::All,
                        },
                        &[0, 0, 0, 255],
                        wgpu::TexelCopyBufferLayout {
                            offset: 0,
                            bytes_per_row: Some(4),
                            rows_per_image: Some(1),
                        },
                        wgpu::Extent3d {
                            width: 1,
                            height: 1,
                            depth_or_array_layers: 1,
                        },
                    );
                }
                t.create_view(&wgpu::TextureViewDescriptor {
                    dimension: Some(dim),
                    ..Default::default()
                })
            })
            .clone()
    }

    /// The sampler parameter on register `reg` of `shader`, and its `sampler_state`.
    fn sampler_param(&self, shader: &Shader, reg: u32) -> Option<usize> {
        let c = shader.constants.iter().find(|c| {
            c.set == mds_shader::ctab::RegisterSet::Sampler
                && (u32::from(c.index)..u32::from(c.index) + u32::from(c.count)).contains(&reg)
        })?;
        self.fx.ast.globals.iter().position(|g| g.name == c.name)
    }

    fn sampler_state(&self, global: usize) -> &[mds_fx::ast::StateAssignment] {
        match &self.fx.ast.globals[global].initializer {
            Some(mds_fx::ast::Initializer::Sampler(s)) => &s.states,
            _ => &[],
        }
    }

    /// The bind group of one stage for a draw.
    fn bind_group(
        &mut self,
        gpu: &Gpu,
        program: (usize, usize),
        stage: Stage,
        attached: &[usize],
    ) -> wgpu::BindGroup {
        enum Res {
            Buffer(wgpu::Buffer),
            View(wgpu::TextureView),
            Sampler(wgpu::Sampler),
        }
        let mut resources = Vec::new();
        let slots = {
            let p = self.programs[program.0][program.1].as_ref().unwrap();
            let s = if stage == Stage::Vertex { &p.vs } else { &p.ps };
            s.slots.clone()
        };
        for slot in &slots {
            let res = match slot {
                Slot::Uniform { cb, rows } => {
                    let p = self.programs[program.0][program.1].as_ref().unwrap();
                    let s = if stage == Stage::Vertex { &p.vs } else { &p.ps };
                    let mut data = vec![[0f32; 4]; *rows as usize];
                    let set = match cb {
                        0 => mds_shader::ctab::RegisterSet::Float4,
                        1 => mds_shader::ctab::RegisterSet::Int4,
                        _ => mds_shader::ctab::RegisterSet::Bool,
                    };
                    for c in s.constants.iter().filter(|c| c.set == set) {
                        let Some(i) = self.sas.fx.param_by_name(&c.name) else {
                            continue;
                        };
                        let regs = bind::registers(
                            &self.sas.fx.params[i].desc,
                            self.row_major.get(i).copied().unwrap_or(false),
                            &self.values[i],
                            c.count as usize,
                        );
                        for (k, r) in regs.into_iter().enumerate() {
                            if let Some(d) = data.get_mut(c.index as usize + k) {
                                *d = r;
                            }
                        }
                    }
                    let bytes: Vec<u8> = data
                        .iter()
                        .flatten()
                        .flat_map(|f| {
                            if *cb == 0 {
                                f.to_le_bytes()
                            } else {
                                (*f as i32).to_le_bytes()
                            }
                        })
                        .collect();
                    Res::Buffer(model::buffer(
                        &gpu.device,
                        wgpu::BufferUsages::UNIFORM,
                        &bytes,
                    ))
                }
                Slot::Sampler { reg, comparison } => {
                    let p = self.programs[program.0][program.1].as_ref().unwrap();
                    let s = if stage == Stage::Vertex { &p.vs } else { &p.ps };
                    let global = self.sampler_param(s, *reg);
                    let key = (global.unwrap_or(usize::MAX), *comparison);
                    if !self.samplers.contains_key(&key) {
                        let states = global.map_or(&[][..], |g| self.sampler_state(g));
                        let border = gpu
                            .features
                            .contains(wgpu::Features::ADDRESS_MODE_CLAMP_TO_BORDER);
                        let (_, desc) = state::sampler(states, border, *comparison);
                        let sampler = gpu.device.create_sampler(&desc);
                        self.samplers.insert(key, sampler);
                    }
                    Res::Sampler(self.samplers[&key].clone())
                }
                Slot::Texture { reg, dim, .. } => {
                    let p = self.programs[program.0][program.1].as_ref().unwrap();
                    let s = if stage == Stage::Vertex { &p.vs } else { &p.ps };
                    let param = self
                        .sampler_param(s, *reg)
                        .and_then(|g| state::sampler(self.sampler_state(g), false, false).0)
                        .and_then(|name| self.sas.fx.param_by_name(&name));
                    let animated = param
                        .and_then(|param| self.animes.iter().find(|a| a.param == param))
                        .filter(|_| *dim == wgpu::TextureViewDimension::D2)
                        .map(|a| a.texture.create_view(&Default::default()));
                    let view = param
                        .and_then(|param| self.sas.bound[param])
                        .filter(|r| !attached.contains(r))
                        .and_then(|r| {
                            let c = self.created[r].as_ref()?;
                            let want = match c.kind {
                                TexKind::Plain => wgpu::TextureViewDimension::D2,
                                TexKind::Cube => wgpu::TextureViewDimension::Cube,
                                TexKind::Volume => wgpu::TextureViewDimension::D3,
                            };
                            let tex = c.texture.as_ref()?;
                            let float_ok = tex.format().sample_type(None, Some(gpu.features))
                                == Some(wgpu::TextureSampleType::Float { filterable: true });
                            (want == *dim && float_ok).then(|| {
                                tex.create_view(&wgpu::TextureViewDescriptor {
                                    dimension: Some(want),
                                    ..Default::default()
                                })
                            })
                        });
                    Res::View(match view.or(animated) {
                        Some(v) => v,
                        None => self.placeholder(gpu, *dim),
                    })
                }
            };
            resources.push((slot.binding(), res));
        }
        let p = self.programs[program.0][program.1].as_ref().unwrap();
        let entries: Vec<_> = resources
            .iter()
            .map(|(b, r)| wgpu::BindGroupEntry {
                binding: *b,
                resource: match r {
                    Res::Buffer(b) => b.as_entire_binding(),
                    Res::View(v) => wgpu::BindingResource::TextureView(v),
                    Res::Sampler(s) => wgpu::BindingResource::Sampler(s),
                },
            })
            .collect();
        gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &p.layouts[stage.group() as usize],
            entries: &entries,
        })
    }
}

pub struct Surface {
    pub name: String,
    pub width: u32,
    pub height: u32,
    render_target: bool,
    depth: bool,
    view: wgpu::TextureView,
    format: wgpu::TextureFormat,
    /// The resource whose texture this is, for the sample-while-bound check.
    resource: Option<usize>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Viewport {
    x: u32,
    y: u32,
    width: u32,
    height: u32,
}

const MAIN: usize = 0;
const MAIN_DEPTH_SURFACE: usize = 1;
const SCRATCH: usize = 2;

/// The bound targets and the surfaces they can name.
pub struct Device {
    pub surfaces: Vec<Surface>,
    rt: [Option<usize>; 4],
    ds: Option<usize>,
    vp: Viewport,
    tex_surfaces: Vec<Vec<usize>>,
    depth_of: Vec<Option<usize>>,
    scratch_depth: HashMap<(u32, u32), wgpu::TextureView>,
    pub encoder: wgpu::CommandEncoder,
}

fn single_view(t: &wgpu::Texture, layer: u32) -> wgpu::TextureView {
    t.create_view(&wgpu::TextureViewDescriptor {
        dimension: Some(wgpu::TextureViewDimension::D2),
        base_mip_level: 0,
        mip_level_count: Some(1),
        base_array_layer: layer,
        array_layer_count: Some(1),
        ..Default::default()
    })
}

impl Device {
    /// `main`, `main.depth`, `scratch`, and every surface of the effect's resources, named as
    /// `mds_mme::run::Device` names them.
    pub fn new(gpu: &Gpu, effect: &Effect, target: &Target) -> Device {
        let s = |name: &str, t: &wgpu::Texture, layer, render_target, depth, resource| Surface {
            name: name.to_string(),
            width: t.width(),
            height: t.height(),
            render_target,
            depth,
            view: single_view(t, layer),
            format: t.format(),
            resource,
        };
        let scratch = gpu.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("scratch"),
            size: wgpu::Extent3d {
                width: 16,
                height: 16,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: MAIN_COLOR,
            usage: resource::COLOR_USAGE,
            view_formats: &[],
        });
        let mut surfaces = vec![
            s("main", &target.color, 0, true, false, None),
            s("main.depth", &target.depth, 0, false, true, None),
            s("scratch", &scratch, 0, true, false, None),
        ];
        let mut tex_surfaces = Vec::new();
        let mut depth_of = Vec::new();
        for (i, r) in effect.sas.resources.iter().enumerate() {
            let c = effect.created[i].as_ref();
            let mut depth = None;
            if let (Some(d), SEM_RENDER_DEPTH) = (c.and_then(|c| c.depth.as_ref()), r.semantic) {
                surfaces.push(s(&r.name, d, 0, false, true, None));
                depth = Some(surfaces.len() - 1);
            }
            if let (Some(d), SEM_OFFSCREEN) = (c.and_then(|c| c.depth.as_ref()), r.semantic) {
                surfaces.push(s(&format!("{}.depth", r.name), d, 0, false, true, None));
            }
            let mut mine = Vec::new();
            if let (Some(t), Some(tex)) = (r.texture, c.and_then(|c| c.texture.as_ref())) {
                let rt = t.is_render_target();
                match t.kind {
                    TexKind::Plain => {
                        surfaces.push(s(&r.name, tex, 0, rt, false, Some(i)));
                        mine.push(surfaces.len() - 1);
                    }
                    TexKind::Cube => {
                        for face in 0..6 {
                            surfaces.push(s(
                                &format!("{}[{face}]", r.name),
                                tex,
                                face,
                                rt,
                                false,
                                Some(i),
                            ));
                            mine.push(surfaces.len() - 1);
                        }
                    }
                    TexKind::Volume => {}
                }
            }
            tex_surfaces.push(mine);
            depth_of.push(depth);
        }
        let (w, h) = (target.color.width(), target.color.height());
        Device {
            surfaces,
            rt: [Some(MAIN), None, None, None],
            ds: Some(MAIN_DEPTH_SURFACE),
            vp: Viewport {
                x: 0,
                y: 0,
                width: w,
                height: h,
            },
            tex_surfaces,
            depth_of,
            scratch_depth: HashMap::new(),
            encoder: gpu.device.create_command_encoder(&Default::default()),
        }
    }

    /// `rt0=.. rt1=.. rt2=.. rt3=.. ds=.. viewport=WxH+X+Y`.
    pub fn bindings(&self) -> String {
        let name = |s: Option<usize>| s.map_or("none", |i| self.surfaces[i].name.as_str());
        format!(
            "rt0={} rt1={} rt2={} rt3={} ds={} viewport={}x{}+{}+{}",
            name(self.rt[0]),
            name(self.rt[1]),
            name(self.rt[2]),
            name(self.rt[3]),
            name(self.ds),
            self.vp.width,
            self.vp.height,
            self.vp.x,
            self.vp.y
        )
    }

    fn set_render_target(&mut self, slot: usize, s: Option<usize>) -> u32 {
        if slot >= 4
            || (slot == 0 && s.is_none())
            || s.is_some_and(|i| !self.surfaces[i].render_target)
        {
            return INVALIDCALL;
        }
        self.rt[slot] = s;
        if let (0, Some(i)) = (slot, s) {
            self.vp = self.full(i);
        }
        S_OK
    }

    fn full(&self, i: usize) -> Viewport {
        Viewport {
            x: 0,
            y: 0,
            width: self.surfaces[i].width,
            height: self.surfaces[i].height,
        }
    }

    fn set_depth(&mut self, s: Option<usize>) -> u32 {
        if s.is_some_and(|i| !self.surfaces[i].depth) {
            return INVALIDCALL;
        }
        self.ds = s;
        S_OK
    }

    fn set_viewport(&mut self, vp: Viewport) {
        let rt0 = &self.surfaces[self.rt[0].unwrap_or(MAIN)];
        if vp.x + vp.width <= rt0.width && vp.y + vp.height <= rt0.height {
            self.vp = vp;
        }
    }

    /// The depth view a pass with the current targets uses.
    fn depth_view(&mut self, gpu: &Gpu) -> Option<(wgpu::TextureView, wgpu::TextureFormat)> {
        let ds = self.ds?;
        let rt0 = &self.surfaces[self.rt[0]?];
        let d = &self.surfaces[ds];
        if (d.width, d.height) == (rt0.width, rt0.height) {
            return Some((d.view.clone(), d.format));
        }
        let (w, h, format) = (rt0.width, rt0.height, d.format);
        let view = self
            .scratch_depth
            .entry((w, h))
            .or_insert_with(|| {
                gpu.device
                    .create_texture(&wgpu::TextureDescriptor {
                        label: Some("scratch depth"),
                        size: wgpu::Extent3d {
                            width: w,
                            height: h,
                            depth_or_array_layers: 1,
                        },
                        mip_level_count: 1,
                        sample_count: 1,
                        dimension: wgpu::TextureDimension::D2,
                        format: MAIN_DEPTH,
                        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                        view_formats: &[],
                    })
                    .create_view(&Default::default())
            })
            .clone();
        Some((
            view,
            if format == MAIN_DEPTH {
                format
            } else {
                MAIN_DEPTH
            },
        ))
    }

    /// The color attachments of the bound targets that have color 0's size.
    fn colors(&self) -> [Option<usize>; 4] {
        let Some(rt0) = self.rt[0] else {
            return [None; 4];
        };
        let size = (self.surfaces[rt0].width, self.surfaces[rt0].height);
        self.rt
            .map(|s| s.filter(|&i| (self.surfaces[i].width, self.surfaces[i].height) == size))
    }

    pub fn clear_main(&mut self, color: u32) {
        let (rt, ds) = (self.rt, self.ds);
        self.rt = [Some(MAIN), None, None, None];
        self.ds = Some(MAIN_DEPTH_SURFACE);
        self.clear(7, color, 1.0);
        (self.rt, self.ds) = (rt, ds);
    }

    /// `IDirect3DDevice9::Clear` of the bound targets (`D3DCLEAR_TARGET`) or the depth stencil
    /// (`D3DCLEAR_ZBUFFER | D3DCLEAR_STENCIL`).
    fn clear(&mut self, flags: i32, color: u32, depth: f32) {
        if flags & 1 != 0 {
            let c = |shift: u32| f64::from((color >> shift) & 0xFF) / 255.0;
            let value = wgpu::Color {
                r: c(16),
                g: c(8),
                b: c(0),
                a: c(24),
            };
            for s in self.rt.into_iter().flatten() {
                let view = self.surfaces[s].view.clone();
                self.encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("Clear=Color"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &view,
                        depth_slice: None,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(value),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    depth_stencil_attachment: None,
                    timestamp_writes: None,
                    occlusion_query_set: None,
                    multiview_mask: None,
                });
            }
        }
        if flags & 6 != 0 {
            if let Some(ds) = self.ds {
                let view = self.surfaces[ds].view.clone();
                let stencil = self.surfaces[ds].format.has_stencil_aspect();
                self.encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("Clear=Depth"),
                    color_attachments: &[],
                    depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                        view: &view,
                        depth_ops: Some(wgpu::Operations {
                            load: wgpu::LoadOp::Clear(depth.clamp(0.0, 1.0)),
                            store: wgpu::StoreOp::Store,
                        }),
                        stencil_ops: stencil.then_some(wgpu::Operations {
                            load: wgpu::LoadOp::Clear(0),
                            store: wgpu::StoreOp::Store,
                        }),
                    }),
                    timestamp_writes: None,
                    occlusion_query_set: None,
                    multiview_mask: None,
                });
            }
        }
    }
}

/// `SasRunState`.
pub struct RunState {
    command: usize,
    mask: u32,
    saved_color: [Option<usize>; 4],
    saved_depth: Option<usize>,
    saved_vp: Viewport,
    current_vp: Viewport,
    loops: Vec<(usize, i32, i32)>,
    clear_color: u32,
    clear_depth: f32,
}

impl RunState {
    pub fn new(d: &Device, background: u32) -> RunState {
        RunState {
            command: 0,
            mask: 0,
            saved_color: d.rt,
            saved_depth: d.ds,
            saved_vp: d.vp,
            current_vp: d.vp,
            loops: Vec::new(),
            clear_color: background,
            clear_depth: 1.0,
        }
    }
}

/// What a draw puts on screen.
pub struct DrawInput<'a> {
    pub scene: &'a bind::Scene,
    /// The model and the material subset `Draw=Geometry` draws.
    pub geometry: Option<(&'a Model, usize)>,
    pub draw_type: u8,
    /// The scene's objects for `CONTROLOBJECT`. `None` leaves those parameters as they are, as
    /// the plan oracle does.
    pub controls: Option<&'a Controls>,
    /// The object the effect is assigned to, an index into `controls`.
    pub owner: Option<usize>,
    /// Inside an offscreen turn, the object that carries the offscreen target.
    pub offscreen_owner: Option<usize>,
}

/// One technique run: the effect, the device, and the lines the draws write.
pub struct Run<'a> {
    pub gpu: &'a Gpu,
    pub effect: &'a mut Effect,
    pub dev: &'a mut Device,
    pub input: &'a DrawInput<'a>,
    pub tech: usize,
    pub draws: u32,
    /// Draws that reached the GPU.
    pub drawn: u32,
    pub out: String,
    /// Why draws were left out, by reason.
    pub skipped: Vec<String>,
}

impl Run<'_> {
    fn restore(&mut self, st: &mut RunState) {
        if st.mask == 0 {
            return;
        }
        for i in 0..4 {
            if st.mask & (1 << (i + 1)) != 0 && (i != 0 || st.saved_color[0].is_some()) {
                self.dev.set_render_target(i, st.saved_color[i]);
            }
        }
        if st.mask & 1 != 0 {
            self.dev.set_depth(st.saved_depth);
        }
        self.dev.set_viewport(st.saved_vp);
        st.mask = 0;
    }

    fn draw(&mut self, kind: u8, pass: usize) -> u32 {
        self.draws += 1;
        let t = &self.effect.sas.techniques[self.tech];
        let p = &t.passes[pass];
        let line = format!(
            "    draw {} pass={} {} {}\n",
            if kind == 0 { "geometry" } else { "buffer" },
            p.index,
            mds_mme::plan::q(&p.name),
            self.dev.bindings()
        );
        self.out.push_str(&line);
        if let Err(why) = self.gpu_draw(kind == 1, pass) {
            self.skipped.push(why);
        } else {
            self.drawn += 1;
        }
        S_OK
    }

    fn gpu_draw(&mut self, buffer: bool, pass: usize) -> Result<(), String> {
        let tech = self.tech;
        if let Err(e) = &self.effect.programs[tech][pass] {
            return Err(e.clone());
        }
        let geometry = if buffer {
            None
        } else {
            Some(self.input.geometry.ok_or("Draw=Geometry with no model")?)
        };
        let material = geometry.and_then(|(m, s)| m.materials.get(s));
        if geometry.is_some() && material.is_none_or(|m| m.count == 0) {
            return Err("empty subset".into());
        }
        let draw = Draw {
            scene: self.input.scene,
            material,
            draw_type: self.input.draw_type,
        };
        bind::bind_semantics(&self.effect.sas.fx.params, &mut self.effect.values, &draw);

        let colors = self.dev.colors();
        let depth = self.dev.depth_view(self.gpu);
        let program = self.effect.programs[tech][pass].as_ref().unwrap();
        let cull = if buffer { 1 } else { program.states.cull };
        let key = PipelineKey {
            tech,
            pass,
            buffer,
            cull,
            colors: colors.map(|s| s.map(|i| self.dev.surfaces[i].format)),
            depth: depth.as_ref().map(|d| d.1),
        };
        let attached: Vec<usize> = colors
            .iter()
            .flatten()
            .filter_map(|&i| self.dev.surfaces[i].resource)
            .collect();
        let groups = [
            self.effect
                .bind_group(self.gpu, (tech, pass), Stage::Vertex, &attached),
            self.effect
                .bind_group(self.gpu, (tech, pass), Stage::Fragment, &attached),
        ];
        let vp = self.dev.vp;
        let quad;
        let (vertices, indices, range) = match geometry {
            Some((m, s)) => {
                let mat = &m.materials[s];
                (
                    &m.vertices,
                    Some(&m.indices),
                    mat.start..mat.start + mat.count,
                )
            }
            None => {
                quad = model::buffer(
                    &self.gpu.device,
                    wgpu::BufferUsages::VERTEX,
                    &model::quad(vp.width, vp.height),
                );
                (&quad, None, 0..6)
            }
        };
        let views: Vec<Option<wgpu::TextureView>> = colors
            .iter()
            .map(|s| s.map(|i| self.dev.surfaces[i].view.clone()))
            .collect();
        let n = views.iter().rposition(Option::is_some).map_or(0, |i| i + 1);
        let attachments: Vec<_> = views[..n]
            .iter()
            .map(|v| {
                v.as_ref().map(|view| wgpu::RenderPassColorAttachment {
                    view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                })
            })
            .collect();
        let pipeline = self
            .effect
            .pipeline(self.gpu, &key)
            .ok_or("no pipeline")?
            .clone();
        let stencil = depth.as_ref().is_some_and(|d| d.1.has_stencil_aspect());
        let mut rp = self
            .dev
            .encoder
            .begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("pass"),
                color_attachments: &attachments,
                depth_stencil_attachment: depth.as_ref().map(|(view, _)| {
                    wgpu::RenderPassDepthStencilAttachment {
                        view,
                        depth_ops: Some(wgpu::Operations {
                            load: wgpu::LoadOp::Load,
                            store: wgpu::StoreOp::Store,
                        }),
                        stencil_ops: stencil.then_some(wgpu::Operations {
                            load: wgpu::LoadOp::Load,
                            store: wgpu::StoreOp::Store,
                        }),
                    }
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
        rp.set_pipeline(&pipeline);
        rp.set_bind_group(0, &groups[0], &[]);
        rp.set_bind_group(1, &groups[1], &[]);
        rp.set_viewport(
            vp.x as f32,
            vp.y as f32,
            vp.width as f32,
            vp.height as f32,
            0.0,
            1.0,
        );
        rp.set_vertex_buffer(0, vertices.slice(..));
        match indices {
            Some(ib) => {
                rp.set_index_buffer(ib.slice(..), wgpu::IndexFormat::Uint32);
                rp.draw_indexed(range, 0, 0..1);
            }
            None => rp.draw(range, 0..1),
        }
        Ok(())
    }

    fn report_target(&mut self, param: Option<usize>, slot: Option<usize>, hr: u32) {
        let sas = &mut self.effect.sas;
        let pname = param
            .map_or("", |p| sas.fx.params[p].name.as_str())
            .to_string();
        let tname = sas.techniques[self.tech].name.clone();
        let code = if hr == CODE_1 {
            String::new()
        } else {
            format!(" [{hr:08X}]")
        };
        let target = match slot {
            Some(s) => format!("RenderColorTarget{s}"),
            None => "RenderDepthStencilTarget".to_string(),
        };
        let path = sas.path.clone();
        sas.log.push_str(&format!(
            "{path}:\nError: invalid render target: {target}={pname}{code}  (technique: {tname})\n"
        ));
    }

    /// `SasApplyCommandImpl`.
    fn apply(&mut self, cmd: &Cmd, st: &mut RunState, pass: Option<usize>) -> u32 {
        match cmd.id {
            CMD_RT0..=4 => {
                let slot = usize::from(cmd.id - CMD_RT0);
                let bit = 1 << (slot + 1);
                let Some(param) = cmd.param else {
                    if slot != 0 || st.saved_color[0].is_some() {
                        let hr = self.dev.set_render_target(slot, st.saved_color[slot]);
                        if hr != S_OK {
                            self.report_target(None, Some(slot), hr);
                            return hr;
                        }
                        st.mask &= !bit;
                        if slot == 0 {
                            st.current_vp = st.saved_vp;
                        }
                        self.dev.set_viewport(st.current_vp);
                        return hr;
                    }
                    self.report_target(None, Some(slot), CODE_1);
                    return CODE_1;
                };
                let surf = match self.effect.sas.bound[param] {
                    None if slot == 0 => Some(SCRATCH),
                    None => None,
                    Some(r) => {
                        let tex = self.effect.sas.resources[r].texture.map(|t| t.kind);
                        let faces = &self.dev.tex_surfaces[r];
                        let pick = match (cmd.value, tex) {
                            (e, Some(TexKind::Cube)) if e >= 0 => faces.get(e as usize).copied(),
                            (e, Some(TexKind::Plain)) if e < 0 => faces.first().copied(),
                            _ => None,
                        };
                        match pick {
                            Some(s) => Some(s),
                            None => {
                                self.report_target(Some(param), Some(slot), CODE_1);
                                return CODE_1;
                            }
                        }
                    }
                };
                let hr = self.dev.set_render_target(slot, surf);
                if hr != S_OK {
                    self.report_target(Some(param), Some(slot), hr);
                    return hr;
                }
                st.mask |= bit;
                if let (0, Some(s)) = (slot, surf) {
                    st.current_vp = self.dev.full(s);
                }
                self.dev.set_viewport(st.current_vp);
                hr
            }
            CMD_DEPTH => {
                let Some(param) = cmd.param else {
                    let hr = self.dev.set_depth(st.saved_depth);
                    if hr != S_OK {
                        self.report_target(None, None, hr);
                        return hr;
                    }
                    st.mask &= !1;
                    self.dev.set_viewport(st.current_vp);
                    return hr;
                };
                let surf = match self.effect.sas.bound[param] {
                    None => None,
                    Some(r) => match self.dev.depth_of[r] {
                        Some(s) => Some(s),
                        None => {
                            self.report_target(Some(param), None, CODE_1);
                            return CODE_1;
                        }
                    },
                };
                let hr = self.dev.set_depth(surf);
                if hr != S_OK {
                    self.report_target(Some(param), None, hr);
                    return hr;
                }
                st.mask |= 1;
                self.dev.set_viewport(st.current_vp);
                hr
            }
            CMD_CLEAR_SET_COLOR => {
                let mut f = [1.0f32; 4];
                if let Some(p) = cmd.param {
                    for (d, s) in f.iter_mut().zip(&self.effect.values[p]) {
                        *d = *s;
                    }
                }
                let c = f.map(|v| {
                    let v = if v > 0.0 { v.min(1.0) } else { 0.0 };
                    (v * 255.0) as i32 as u32
                });
                st.clear_color = (c[3] << 24) | (c[0] << 16) | (c[1] << 8) | c[2];
                S_OK
            }
            CMD_CLEAR_SET_DEPTH => {
                if let Some(v) = cmd.param.and_then(|p| self.effect.values[p].first()) {
                    st.clear_depth = *v;
                }
                S_OK
            }
            CMD_CLEAR => {
                self.dev.clear(cmd.value, st.clear_color, st.clear_depth);
                S_OK
            }
            CMD_DRAW_GEOMETRY | CMD_DRAW_BUFFER => match pass {
                Some(p) => self.draw(cmd.id - CMD_DRAW_GEOMETRY, p),
                None => S_OK,
            },
            _ => S_OK,
        }
    }

    fn report_error(&mut self, pass: usize, hr: u32) {
        let sas = &mut self.effect.sas;
        let t = &sas.techniques[self.tech];
        let line = format!(
            "technique: {}, pass: {}:\nDirectX Error: Unknown [{hr:08X}]\nFailed to run the effect script:\n",
            t.name, t.passes[pass].name
        );
        sas.log.push_str(&line);
    }

    /// `SasRunPassCommands`.
    fn run_pass(&mut self, pass: usize, st: &mut RunState) -> u32 {
        let p = &self.effect.sas.techniques[self.tech].passes[pass];
        if p.script.is_none() {
            let hr = self.draw(0, pass);
            if hr != S_OK {
                self.report_error(pass, hr);
            }
            return hr;
        }
        let cmds = p.cmds.clone();
        for c in &cmds {
            let hr = self.apply(c, st, Some(pass));
            if hr != S_OK {
                if c.id == CMD_DRAW_GEOMETRY || c.id == CMD_DRAW_BUFFER {
                    self.report_error(pass, hr);
                }
                return hr;
            }
        }
        S_OK
    }

    /// `SasRunTechniqueWalk`: the result, and whether the walk suspended at `ScriptExternal`.
    pub fn walk(&mut self, st: &mut RunState, step: bool) -> (u32, bool) {
        let t = &self.effect.sas.techniques[self.tech];
        if t.script.is_none() {
            if step {
                return (S_OK, false);
            }
            let mut hr = S_OK;
            for p in 0..t.passes.len() {
                hr = self.run_pass(p, st);
                if hr != S_OK {
                    break;
                }
            }
            self.restore(st);
            if hr != S_OK {
                self.effect.sas.run_failed = true;
            }
            return (hr, false);
        }
        let cmds = t.cmds.clone();
        while st.command < cmds.len() {
            let cmd = &cmds[st.command];
            let mut advance = true;
            match cmd.id {
                CMD_PASS => {
                    let pass = self.effect.sas.techniques[self.tech]
                        .passes
                        .iter()
                        .position(|p| p.index == cmd.value);
                    if let Some(p) = pass {
                        let hr = self.run_pass(p, st);
                        if hr != S_OK {
                            self.effect.sas.run_failed = true;
                            self.restore(st);
                            return (hr, false);
                        }
                    }
                }
                CMD_SCRIPT_EXTERNAL if step => return (S_OK, true),
                CMD_LOOP_BY_COUNT => {
                    let count = cmd
                        .param
                        .and_then(|p| self.effect.values[p].first().map(|v| *v as i32))
                        .unwrap_or(0);
                    if count <= 0 {
                        st.command = skip_loop(&cmds, st.command);
                        advance = false;
                    } else {
                        st.loops.push((st.command, 0, count));
                    }
                }
                CMD_LOOP_GET_INDEX => {
                    let i = st.loops.last().map_or(0, |l| l.1);
                    if let Some(v) = cmd.param.and_then(|p| self.effect.values[p].first_mut()) {
                        *v = i as f32;
                    }
                }
                CMD_LOOP_END => {
                    if let Some(top) = st.loops.last_mut() {
                        top.1 += 1;
                        if top.1 >= top.2 {
                            st.loops.pop();
                        } else {
                            st.command = top.0;
                        }
                    }
                }
                CMD_RT0..=9 => {
                    let hr = self.apply(cmd, st, None);
                    if hr != S_OK {
                        self.effect.sas.run_failed = true;
                        self.restore(st);
                        return (hr, false);
                    }
                }
                _ => {}
            }
            if advance {
                st.command += 1;
            }
        }
        self.restore(st);
        (S_OK, false)
    }
}

fn skip_loop(cmds: &[Cmd], at: usize) -> usize {
    let mut depth = 1;
    for (i, c) in cmds.iter().enumerate().skip(at + 1) {
        if c.id == CMD_LOOP_BY_COUNT {
            depth += 1;
        } else if c.id == CMD_LOOP_END {
            depth -= 1;
            if depth == 0 {
                return i + 1;
            }
        }
    }
    cmds.len()
}
