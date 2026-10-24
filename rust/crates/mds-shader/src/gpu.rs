//! `--wgpu-check`: create a shader module and a render pipeline for each WGSL output on a real
//! device (Metal on macOS, DX12 on Windows, Vulkan elsewhere).
//!
//! An MME pass pairs a vertex and a pixel shader, but this check takes each shader alone, so
//! every pipeline gets a generated counterpart:
//!
//! - A vertex shader gets one vertex buffer that holds every `@location` input, and a
//!   fragment shader that reads nothing and writes one `Rgba8Unorm` target.
//! - A fragment shader gets a generated vertex shader that writes every `@location` the
//!   fragment shader reads, with the same type and interpolation, and one color target per
//!   output location (a float format with no more components than the output), plus a depth
//!   target when it writes `frag_depth`.
//!
//! The bind group layout is derived from the shader (`layout: None`).

use std::borrow::Cow;
use std::fmt::Write as _;

use naga::{Binding, BuiltIn, Interpolation, Sampling, ScalarKind, ShaderStage, TypeInner};

use crate::Stage;

const COUNTERPART_FRAGMENT: &str =
    "@fragment fn main() -> @location(0) vec4<f32> { return vec4<f32>(0.0); }\n";

pub struct Gpu {
    device: wgpu::Device,
    pub adapter: String,
}

/// One `@location` binding of an entry point and its type.
struct Loc {
    location: u32,
    interpolation: Option<Interpolation>,
    sampling: Option<Sampling>,
    kind: ScalarKind,
    components: u32,
}

#[derive(Default)]
struct Interface {
    inputs: Vec<Loc>,
    outputs: Vec<Loc>,
    writes_depth: bool,
}

fn numeric(module: &naga::Module, ty: naga::Handle<naga::Type>) -> Option<(ScalarKind, u32, u8)> {
    match module.types[ty].inner {
        TypeInner::Scalar(s) => Some((s.kind, 1, s.width)),
        TypeInner::Vector { size, scalar } => Some((scalar.kind, size as u32, scalar.width)),
        _ => None,
    }
}

/// Flattens an argument or result: a binding on the value, or bindings on struct members.
fn collect(
    module: &naga::Module,
    ty: naga::Handle<naga::Type>,
    binding: Option<&Binding>,
    out: &mut Vec<Loc>,
    depth: &mut bool,
) -> Result<(), String> {
    match binding {
        Some(Binding::Location {
            location,
            interpolation,
            sampling,
            ..
        }) => {
            let (kind, components, width) = numeric(module, ty)
                .ok_or_else(|| format!("location {location} is not a scalar or vector"))?;
            if width != 4 {
                return Err(format!("location {location} has {width}-byte components"));
            }
            out.push(Loc {
                location: *location,
                interpolation: *interpolation,
                sampling: *sampling,
                kind,
                components,
            });
        }
        Some(Binding::BuiltIn(BuiltIn::FragDepth)) => *depth = true,
        Some(Binding::BuiltIn(_)) => {}
        None => {
            if let TypeInner::Struct { members, .. } = &module.types[ty].inner {
                for m in members {
                    collect(module, m.ty, m.binding.as_ref(), out, depth)?;
                }
            }
        }
    }
    Ok(())
}

/// The entry point of a single-entry WGSL module and its interface.
fn interface(module: &naga::Module, stage: ShaderStage) -> Result<(String, Interface), String> {
    let ep = module
        .entry_points
        .iter()
        .find(|e| e.stage == stage)
        .ok_or_else(|| format!("no {stage:?} entry point"))?;
    let mut i = Interface::default();
    let mut unused = false;
    for a in &ep.function.arguments {
        collect(module, a.ty, a.binding.as_ref(), &mut i.inputs, &mut unused)?;
    }
    if let Some(r) = &ep.function.result {
        collect(
            module,
            r.ty,
            r.binding.as_ref(),
            &mut i.outputs,
            &mut i.writes_depth,
        )?;
    }
    Ok((ep.name.clone(), i))
}

fn wgsl_type(l: &Loc) -> String {
    let s = match l.kind {
        ScalarKind::Sint => "i32",
        ScalarKind::Uint => "u32",
        _ => "f32",
    };
    if l.components == 1 {
        s.to_string()
    } else {
        format!("vec{}<{s}>", l.components)
    }
}

fn interpolate_attr(l: &Loc) -> String {
    let Some(i) = l.interpolation else {
        return String::new();
    };
    let i = match i {
        Interpolation::Perspective => "perspective",
        Interpolation::Linear => "linear",
        Interpolation::Flat => "flat",
        Interpolation::PerVertex => "perspective",
    };
    let s = match l.sampling {
        Some(Sampling::Center) => ", center",
        Some(Sampling::Centroid) => ", centroid",
        Some(Sampling::Sample) => ", sample",
        Some(Sampling::First) => ", first",
        Some(Sampling::Either) => ", either",
        None => "",
    };
    format!("@interpolate({i}{s}) ")
}

/// A vertex shader that feeds every input of a fragment shader.
fn counterpart_vertex(inputs: &[Loc]) -> String {
    let mut s = String::from("struct V {\n  @builtin(position) p: vec4<f32>,\n");
    for l in inputs {
        let _ = writeln!(
            s,
            "  @location({}) {}v{}: {},",
            l.location,
            interpolate_attr(l),
            l.location,
            wgsl_type(l)
        );
    }
    s.push_str("}\n@vertex fn main() -> V {\n  var o: V;\n  return o;\n}\n");
    s
}

fn vertex_format(l: &Loc) -> wgpu::VertexFormat {
    use wgpu::VertexFormat as F;
    match (l.kind, l.components) {
        (ScalarKind::Sint, 1) => F::Sint32,
        (ScalarKind::Sint, 2) => F::Sint32x2,
        (ScalarKind::Sint, 3) => F::Sint32x3,
        (ScalarKind::Sint, _) => F::Sint32x4,
        (ScalarKind::Uint, 1) => F::Uint32,
        (ScalarKind::Uint, 2) => F::Uint32x2,
        (ScalarKind::Uint, 3) => F::Uint32x3,
        (ScalarKind::Uint, _) => F::Uint32x4,
        (_, 1) => F::Float32,
        (_, 2) => F::Float32x2,
        (_, 3) => F::Float32x3,
        _ => F::Float32x4,
    }
}

/// A color format whose components the output covers (wgpu requires format components <=
/// output components).
fn color_format(l: &Loc) -> wgpu::TextureFormat {
    use wgpu::TextureFormat as T;
    match (l.kind, l.components) {
        (ScalarKind::Sint, 1) => T::R32Sint,
        (ScalarKind::Sint, 2 | 3) => T::Rg32Sint,
        (ScalarKind::Sint, _) => T::Rgba32Sint,
        (ScalarKind::Uint, 1) => T::R32Uint,
        (ScalarKind::Uint, 2 | 3) => T::Rg32Uint,
        (ScalarKind::Uint, _) => T::Rgba32Uint,
        (_, 1) => T::R16Float,
        (_, 2 | 3) => T::Rg16Float,
        _ => T::Rgba16Float,
    }
}

impl Gpu {
    pub fn new() -> Result<Gpu, String> {
        let backends = if cfg!(target_os = "macos") {
            wgpu::Backends::METAL
        } else if cfg!(windows) {
            wgpu::Backends::DX12
        } else {
            wgpu::Backends::VULKAN
        };
        let mut desc = wgpu::InstanceDescriptor::new_without_display_handle();
        desc.backends = backends;
        let instance = wgpu::Instance::new(desc.with_env());
        let adapter =
            pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default()))
                .map_err(|e| format!("no {backends:?} adapter: {e}"))?;
        let info = adapter.get_info();
        let (device, _queue) =
            pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
                label: Some("mds-shader --wgpu-check"),
                required_limits: adapter.limits(),
                ..Default::default()
            }))
            .map_err(|e| format!("cannot create a device on {}: {e}", info.name))?;
        Ok(Gpu {
            device,
            adapter: format!("{} ({:?}, {})", info.name, info.backend, info.driver),
        })
    }

    fn scoped<T>(&self, f: impl FnOnce() -> T) -> Result<T, String> {
        // Internal errors carry backend compile failures (for example of the generated MSL).
        let internal = self.device.push_error_scope(wgpu::ErrorFilter::Internal);
        let validation = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let v = f();
        let errors = [
            pollster::block_on(validation.pop()),
            pollster::block_on(internal.pop()),
        ];
        match errors.into_iter().flatten().next() {
            None => Ok(v),
            Some(e) => Err(e.to_string()),
        }
    }

    fn module(&self, label: &str, wgsl: &str) -> Result<wgpu::ShaderModule, String> {
        self.scoped(|| {
            self.device
                .create_shader_module(wgpu::ShaderModuleDescriptor {
                    label: Some(label),
                    source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(wgsl)),
                })
        })
        .map_err(|e| format!("shader module: {e}"))
    }

    /// Creates the module and a pipeline for one WGSL output. `parsed` is the same WGSL read
    /// back by naga, which gives the entry point and its interface.
    pub fn check(
        &self,
        label: &str,
        wgsl: &str,
        parsed: &naga::Module,
        stage: Stage,
    ) -> Result<(), String> {
        let naga_stage = match stage {
            Stage::Vertex => ShaderStage::Vertex,
            Stage::Fragment => ShaderStage::Fragment,
        };
        let (entry, io) = interface(parsed, naga_stage)?;
        let module = self.module(label, wgsl)?;
        let created = match stage {
            Stage::Vertex => {
                let mut offset = 0;
                let attrs: Vec<wgpu::VertexAttribute> = io
                    .inputs
                    .iter()
                    .map(|l| {
                        let a = wgpu::VertexAttribute {
                            format: vertex_format(l),
                            offset,
                            shader_location: l.location,
                        };
                        offset += a.format.size();
                        a
                    })
                    .collect();
                let buffers = [Some(wgpu::VertexBufferLayout {
                    array_stride: offset.max(4),
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &attrs,
                })];
                // A pipeline needs an attachment; a fragment shader that reads no inputs
                // matches any vertex outputs.
                let fs = self.module("counterpart fragment shader", COUNTERPART_FRAGMENT)?;
                let target = [Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })];
                self.scoped(|| {
                    self.device
                        .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                            label: Some(label),
                            layout: None,
                            vertex: wgpu::VertexState {
                                module: &module,
                                entry_point: Some(&entry),
                                compilation_options: Default::default(),
                                buffers: if attrs.is_empty() { &[] } else { &buffers },
                            },
                            primitive: Default::default(),
                            depth_stencil: None,
                            multisample: Default::default(),
                            fragment: Some(wgpu::FragmentState {
                                module: &fs,
                                entry_point: Some("main"),
                                compilation_options: Default::default(),
                                targets: &target,
                            }),
                            multiview_mask: None,
                            cache: None,
                        })
                })
            }
            Stage::Fragment => {
                let vs =
                    self.module("counterpart vertex shader", &counterpart_vertex(&io.inputs))?;
                let n = io.outputs.iter().map(|l| l.location + 1).max().unwrap_or(0) as usize;
                let mut targets = vec![None; n];
                for l in &io.outputs {
                    targets[l.location as usize] = Some(wgpu::ColorTargetState {
                        format: color_format(l),
                        blend: None,
                        write_mask: wgpu::ColorWrites::ALL,
                    });
                }
                let depth = io.writes_depth.then(|| wgpu::DepthStencilState {
                    format: wgpu::TextureFormat::Depth32Float,
                    depth_write_enabled: Some(true),
                    depth_compare: Some(wgpu::CompareFunction::Always),
                    stencil: Default::default(),
                    bias: Default::default(),
                });
                self.scoped(|| {
                    self.device
                        .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                            label: Some(label),
                            layout: None,
                            vertex: wgpu::VertexState {
                                module: &vs,
                                entry_point: Some("main"),
                                compilation_options: Default::default(),
                                buffers: &[],
                            },
                            primitive: Default::default(),
                            depth_stencil: depth,
                            multisample: Default::default(),
                            fragment: Some(wgpu::FragmentState {
                                module: &module,
                                entry_point: Some(&entry),
                                compilation_options: Default::default(),
                                targets: &targets,
                            }),
                            multiview_mask: None,
                            cache: None,
                        })
                })
            }
        };
        created
            .map(|_| ())
            .map_err(|e| format!("render pipeline: {e}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counterpart_matches_the_fragment_inputs() {
        let fs = "struct I { @location(0) a: vec4<f32>, @location(2) @interpolate(flat) b: i32 }\n\
                  @fragment fn f(i: I, @builtin(position) p: vec4<f32>) -> @location(0) vec3<f32> { return i.a.xyz; }";
        let m = naga::front::wgsl::parse_str(fs).unwrap();
        let (name, io) = interface(&m, ShaderStage::Fragment).unwrap();
        assert_eq!(name, "f");
        let vs = counterpart_vertex(&io.inputs);
        assert!(
            vs.contains("@location(2) @interpolate(flat) v2: i32"),
            "{vs}"
        );
        let v = naga::front::wgsl::parse_str(&vs).unwrap();
        naga::valid::Validator::new(Default::default(), naga::valid::Capabilities::all())
            .validate(&v)
            .unwrap();
        assert_eq!(color_format(&io.outputs[0]), wgpu::TextureFormat::Rg16Float);
    }
}
