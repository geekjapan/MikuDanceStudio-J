//! [`Renderer`]: the pipelines, the default textures and the per-model buffers, kept between frames
//! on a device the caller owns.

use crate::mesh::{EdgeView, FLAG_DOUBLE_SIDED, FLAG_EDGE};
use crate::{linear_to_srgb, srgb_to_linear_table, view, Frame, Mesh, COLOR_FORMAT, DEPTH_FORMAT};
use std::collections::HashMap;

/// Bytes per vertex of the body buffer (position, normal, uv) and of the edge buffer (position,
/// `A8R8G8B8` color).
const BODY_STRIDE: u64 = 32;
const EDGE_STRIDE: u64 = 16;
/// Bytes of a material's uniform block: diffuse, ambient, specular and a parameter vector.
const MATERIAL_BYTES: u64 = 64;

/// A model of a frame: the mesh and how many models of the same mesh came before it in the frame
/// (one mesh can be drawn twice with two poses).
type Key = (u64, u32);

struct Pipelines {
    body: wgpu::RenderPipeline,
    body_two_sided: wgpu::RenderPipeline,
    edge: wgpu::RenderPipeline,
}

/// The GPU side of one model. The index buffer is written once; the vertex buffers and material
/// uniforms are rewritten for every frame, because the pose and the material morphs change them.
struct Prepared {
    vertices: wgpu::Buffer,
    edge_vertices: wgpu::Buffer,
    indices: wgpu::Buffer,
    /// Per material: its uniform buffer and the bind group over it.
    materials: Vec<(wgpu::Buffer, wgpu::BindGroup)>,
    /// Whether each material draws its edge: the flag, and for PMX a visible edge color.
    edge_drawn: Vec<bool>,
    /// The diffuse alpha of each material after the material morphs.
    alpha: Vec<f32>,
}

/// Depth, and the multisampled color when `samples > 1`, for one target size.
struct Targets {
    size: (u32, u32),
    samples: u32,
    depth: wgpu::TextureView,
    color: Option<wgpu::TextureView>,
}

/// Draws [`Frame`]s on a wgpu device that the caller owns, keeping what does not change between
/// frames: the shader and pipelines (one set per sample count), the default textures, the scene
/// uniform, the depth and multisample targets, and the buffers of every model in the last frame.
///
/// [`render_into`](Renderer::render_into) draws into a color texture of the caller's, so a window
/// shows the picture without a read back; [`render_frame`](Renderer::render_frame) returns pixels.
///
/// A model is identified by its [`Mesh`]; a mesh that a frame does not list loses its buffers.
pub struct Renderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    shader: wgpu::ShaderModule,
    material_layout: wgpu::BindGroupLayout,
    layout: wgpu::PipelineLayout,
    scene_buf: wgpu::Buffer,
    scene_group: wgpu::BindGroup,
    white: wgpu::TextureView,
    toon: wgpu::TextureView,
    sampler: wgpu::Sampler,
    pipelines: HashMap<u32, Pipelines>,
    pipelines_created: usize,
    models: HashMap<Key, Prepared>,
    targets: Option<Targets>,
}

impl Renderer {
    /// A renderer on `device` and `queue`. Both are handles to the caller's objects (cloned, not
    /// new devices). `render_into` accepts [`Rgba8Unorm`](wgpu::TextureFormat::Rgba8Unorm) targets.
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Result<Renderer, String> {
        let error_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
        let both = wgpu::ShaderStages::VERTEX_FRAGMENT;
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("mds-render"),
            source: wgpu::ShaderSource::Wgsl(include_str!("shader.wgsl").into()),
        });
        let scene_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[uniform_entry(0, both)],
        });
        let material_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[
                uniform_entry(0, both),
                texture_entry(1),
                texture_entry(2),
                texture_entry(3),
                entry(
                    4,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    wgpu::ShaderStages::FRAGMENT,
                ),
            ],
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[Some(&scene_layout), Some(&material_layout)],
            immediate_size: 0,
        });
        let scene_buf = empty_buffer(device, wgpu::BufferUsages::UNIFORM, SCENE_BYTES);
        let scene_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &scene_layout,
            entries: &[bind_entry(0, scene_buf.as_entire_binding())],
        });
        let renderer = Renderer {
            white: texture(device, queue, 1, 1, &[255; 4]),
            toon: texture(device, queue, 1, 32, &toon_ramp()),
            sampler: device.create_sampler(&wgpu::SamplerDescriptor {
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                ..Default::default()
            }),
            device: device.clone(),
            queue: queue.clone(),
            shader,
            material_layout,
            layout,
            scene_buf,
            scene_group,
            pipelines: HashMap::new(),
            pipelines_created: 0,
            models: HashMap::new(),
            targets: None,
        };
        match pollster::block_on(error_scope.pop()) {
            Some(e) => Err(format!("wgpu: {e}")),
            None => Ok(renderer),
        }
    }

    /// How many render pipelines this renderer has built. A frame at a sample count seen before
    /// builds none.
    pub fn pipelines_created(&self) -> usize {
        self.pipelines_created
    }

    /// Draws `frame` into `target`, a view of a `frame.width` x `frame.height`
    /// [`Rgba8Unorm`](wgpu::TextureView) texture with `RENDER_ATTACHMENT` usage, and submits the
    /// work. The queue orders it before whatever the caller submits next, so the caller can sample
    /// or present the texture right after.
    ///
    /// `sample_count` (1, 2, 4 or 8, as the device supports) is hardware multisampling, resolved
    /// into `target`; `frame.samples` is not used. `frame.background` clears the target and
    /// `frame.pixel_offset` shifts the picture as in [`render_frame`](Renderer::render_frame).
    pub fn render_into(
        &mut self,
        target: &wgpu::TextureView,
        frame: &Frame,
        sample_count: u32,
    ) -> Result<(), String> {
        check(frame)?;
        if !matches!(sample_count, 1 | 2 | 4 | 8) {
            return Err(format!("unsupported sample count {sample_count}"));
        }
        let error_scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        self.upload(frame);
        let encoder = self.encode(target, frame, frame.pixel_offset, sample_count);
        self.queue.submit([encoder.finish()]);
        finish(error_scope)
    }

    /// Draws `frame` and returns `width * height * 4` RGBA8 bytes, top row first: one render per
    /// entry of `frame.samples` (no multisampling), averaged in linear light.
    pub fn render_frame(&mut self, frame: &Frame) -> Result<Vec<u8>, String> {
        check(frame)?;
        if frame.samples.is_empty() {
            return Err("empty frame".into());
        }
        let (width, height) = (frame.width, frame.height);
        let error_scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        self.upload(frame);

        let size = wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        };
        let target = self.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("target"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COLOR_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let row_bytes = width * 4;
        let padded_row = row_bytes.next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let read_buf = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size: u64::from(padded_row * height),
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let target_view = target.create_view(&Default::default());

        let to_linear = srgb_to_linear_table();
        let mut sum = vec![0f32; (width * height * 4) as usize];
        for sample in frame.samples {
            let shift = [
                frame.pixel_offset[0] - sample[0],
                frame.pixel_offset[1] - sample[1],
            ];
            let mut encoder = self.encode(&target_view, frame, shift, 1);
            encoder.copy_texture_to_buffer(
                target.as_image_copy(),
                wgpu::TexelCopyBufferInfo {
                    buffer: &read_buf,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(padded_row),
                        rows_per_image: Some(height),
                    },
                },
                size,
            );
            self.queue.submit([encoder.finish()]);

            let slice = read_buf.slice(..);
            let (tx, rx) = std::sync::mpsc::channel();
            slice.map_async(wgpu::MapMode::Read, move |r| {
                let _ = tx.send(r);
            });
            self.device
                .poll(wgpu::PollType::wait_indefinitely())
                .map_err(|e| format!("poll: {e}"))?;
            rx.recv()
                .map_err(|e| e.to_string())?
                .map_err(|e| format!("map readback buffer: {e}"))?;
            {
                let mapped = slice
                    .get_mapped_range()
                    .map_err(|e| format!("read readback buffer: {e}"))?;
                for (y, row) in mapped
                    .chunks(padded_row as usize)
                    .take(height as usize)
                    .enumerate()
                {
                    let out = &mut sum[y * row_bytes as usize..][..row_bytes as usize];
                    for (k, (s, &p)) in out.iter_mut().zip(row).enumerate() {
                        // Alpha is averaged as it is; the colors in linear light.
                        *s += if k % 4 == 3 {
                            f32::from(p) / 255.0
                        } else {
                            to_linear[usize::from(p)]
                        };
                    }
                }
            }
            read_buf.unmap();
        }
        finish(error_scope)?;
        let n = frame.samples.len() as f32;
        Ok(sum
            .iter()
            .enumerate()
            .map(|(k, &s)| {
                let v = s / n;
                let v = if k % 4 == 3 { v } else { linear_to_srgb(v) };
                (v * 255.0).round().clamp(0.0, 255.0) as u8
            })
            .collect())
    }

    /// The keys of the models of `frame`, in order.
    fn keys(frame: &Frame) -> Vec<Key> {
        let mut seen: HashMap<u64, u32> = HashMap::new();
        frame
            .models
            .iter()
            .map(|(mesh, _)| {
                let n = seen.entry(mesh.id).or_default();
                *n += 1;
                (mesh.id, *n - 1)
            })
            .collect()
    }

    /// Creates the buffers of the models that are new, writes this frame's vertices and material
    /// values into all of them, and drops the models the frame does not list.
    fn upload(&mut self, frame: &Frame) {
        let keys = Self::keys(frame);
        let edge_view = EdgeView {
            camera_position: frame.view.eye,
            fov: frame.view.edge_fov,
            self_shadow: frame.toon,
        };
        for (&(mesh, pose), key) in frame.models.iter().zip(&keys) {
            let skin = mesh.skinned(pose, &edge_view);
            let stride = skin.stride();
            let body: Vec<f32> = skin
                .main
                .chunks(stride)
                .flat_map(|v| v[..8].iter().copied())
                .collect();
            let edge_data: Vec<u8> = skin
                .edge
                .iter()
                .flat_map(|e| {
                    let color = e.diffuse.to_le_bytes();
                    let p = e.position.map(f32::to_ne_bytes);
                    [p[0], p[1], p[2], color].concat()
                })
                .collect();
            // The morphed rgb is in diffuse_mirror, the morphed alpha in diffuse.
            let diffuse = |m: &mds_skin::Material| {
                [
                    m.diffuse_mirror[0],
                    m.diffuse_mirror[1],
                    m.diffuse_mirror[2],
                    m.diffuse[3],
                ]
            };
            if !self.models.contains_key(key) {
                let prepared = self.prepare(mesh, skin.materials.len());
                self.models.insert(*key, prepared);
            }
            let p = self.models.get_mut(key).expect("inserted above");
            self.queue.write_buffer(&p.vertices, 0, &bytes(&body));
            self.queue.write_buffer(&p.edge_vertices, 0, &edge_data);
            for (m, (buf, _)) in skin.materials.iter().zip(&p.materials) {
                let u = [
                    diffuse(m).as_slice(),
                    &[m.ambient[0], m.ambient[1], m.ambient[2], 1.0],
                    &[
                        m.specular[0],
                        m.specular[1],
                        m.specular[2],
                        m.specular_power,
                    ],
                    &[0.0; 4],
                ]
                .concat();
                self.queue.write_buffer(buf, 0, &bytes(&u));
            }
            p.edge_drawn = mesh
                .materials
                .iter()
                .zip(&skin.materials)
                .map(|(m, sm)| {
                    m.flags & FLAG_EDGE != 0 && (!skin.is_pmx() || sm.edge_color[3] > 0.0)
                })
                .collect();
            p.alpha = skin.materials.iter().map(|m| diffuse(m)[3]).collect();
        }
        self.models.retain(|k, _| keys.contains(k));
    }

    /// Buffers for `mesh`, with the sizes its vertex count and material count fix; the contents
    /// come with the first upload.
    fn prepare(&self, mesh: &Mesh, materials: usize) -> Prepared {
        let device = &self.device;
        let index_data: Vec<u8> = mesh.indices.iter().flat_map(|i| i.to_ne_bytes()).collect();
        let indices = empty_buffer(device, wgpu::BufferUsages::INDEX, index_data.len() as u64);
        self.queue.write_buffer(&indices, 0, &index_data);
        let vertices = mesh.vertex_count() as u64;
        Prepared {
            vertices: empty_buffer(device, wgpu::BufferUsages::VERTEX, vertices * BODY_STRIDE),
            edge_vertices: empty_buffer(device, wgpu::BufferUsages::VERTEX, vertices * EDGE_STRIDE),
            indices,
            materials: (0..materials)
                .map(|_| {
                    let buf = empty_buffer(device, wgpu::BufferUsages::UNIFORM, MATERIAL_BYTES);
                    let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: None,
                        layout: &self.material_layout,
                        entries: &[
                            bind_entry(0, buf.as_entire_binding()),
                            bind_entry(1, wgpu::BindingResource::TextureView(&self.white)),
                            bind_entry(2, wgpu::BindingResource::TextureView(&self.white)),
                            bind_entry(3, wgpu::BindingResource::TextureView(&self.toon)),
                            bind_entry(4, wgpu::BindingResource::Sampler(&self.sampler)),
                        ],
                    });
                    (buf, group)
                })
                .collect(),
            edge_drawn: Vec::new(),
            alpha: Vec::new(),
        }
    }

    /// The pipelines for `samples` and the depth and multisample targets for `size`, built if the
    /// last call did not have them.
    fn ensure(&mut self, size: (u32, u32), samples: u32) {
        if !self.pipelines.contains_key(&samples) {
            let pipelines = self.build_pipelines(samples);
            self.pipelines.insert(samples, pipelines);
            self.pipelines_created += 3;
        }
        if self
            .targets
            .as_ref()
            .is_none_or(|t| t.size != size || t.samples != samples)
        {
            let make = |label, format, usage| {
                self.device
                    .create_texture(&wgpu::TextureDescriptor {
                        label: Some(label),
                        size: wgpu::Extent3d {
                            width: size.0,
                            height: size.1,
                            depth_or_array_layers: 1,
                        },
                        mip_level_count: 1,
                        sample_count: samples,
                        dimension: wgpu::TextureDimension::D2,
                        format,
                        usage,
                        view_formats: &[],
                    })
                    .create_view(&Default::default())
            };
            self.targets = Some(Targets {
                size,
                samples,
                depth: make(
                    "depth",
                    DEPTH_FORMAT,
                    wgpu::TextureUsages::RENDER_ATTACHMENT,
                ),
                color: (samples > 1).then(|| {
                    make(
                        "multisample color",
                        COLOR_FORMAT,
                        wgpu::TextureUsages::RENDER_ATTACHMENT,
                    )
                }),
            });
        }
    }

    fn build_pipelines(&self, samples: u32) -> Pipelines {
        let body_attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2];
        let edge_attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Unorm8x4Bgra];
        let pipeline = |vs: &str,
                        fs: &str,
                        (stride, attrs): (u64, &[wgpu::VertexAttribute]),
                        cull: Option<wgpu::Face>,
                        blend: Option<wgpu::BlendState>| {
            self.device
                .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some(vs),
                    layout: Some(&self.layout),
                    vertex: wgpu::VertexState {
                        module: &self.shader,
                        entry_point: Some(vs),
                        compilation_options: Default::default(),
                        buffers: &[Some(wgpu::VertexBufferLayout {
                            array_stride: stride,
                            step_mode: wgpu::VertexStepMode::Vertex,
                            attributes: attrs,
                        })],
                    },
                    // PMX front faces are clockwise.
                    primitive: wgpu::PrimitiveState {
                        front_face: wgpu::FrontFace::Cw,
                        cull_mode: cull,
                        ..Default::default()
                    },
                    depth_stencil: Some(wgpu::DepthStencilState {
                        format: DEPTH_FORMAT,
                        depth_write_enabled: Some(true),
                        depth_compare: Some(wgpu::CompareFunction::LessEqual),
                        stencil: Default::default(),
                        bias: Default::default(),
                    }),
                    multisample: wgpu::MultisampleState {
                        count: samples,
                        ..Default::default()
                    },
                    fragment: Some(wgpu::FragmentState {
                        module: &self.shader,
                        entry_point: Some(fs),
                        compilation_options: Default::default(),
                        targets: &[Some(wgpu::ColorTargetState {
                            format: COLOR_FORMAT,
                            blend,
                            write_mask: wgpu::ColorWrites::ALL,
                        })],
                    }),
                    multiview_mask: None,
                    cache: None,
                })
        };
        let alpha = Some(wgpu::BlendState::ALPHA_BLENDING);
        let body_layout = (BODY_STRIDE, &body_attrs[..]);
        Pipelines {
            body: pipeline(
                "vs_main",
                "fs_main",
                body_layout,
                Some(wgpu::Face::Back),
                alpha,
            ),
            body_two_sided: pipeline("vs_main", "fs_main", body_layout, None, alpha),
            edge: pipeline(
                "vs_edge",
                "fs_edge",
                (EDGE_STRIDE, &edge_attrs[..]),
                Some(wgpu::Face::Front),
                alpha,
            ),
        }
    }

    /// Records one render of the (already uploaded) models into `target`, shifted by `shift`
    /// pixels, and returns the encoder.
    fn encode(
        &mut self,
        target: &wgpu::TextureView,
        frame: &Frame,
        shift: [f32; 2],
        samples: u32,
    ) -> wgpu::CommandEncoder {
        let (width, height) = (frame.width, frame.height);
        self.ensure((width, height), samples);
        self.queue
            .write_buffer(&self.scene_buf, 0, &scene_data(frame, shift));
        let pipelines = &self.pipelines[&samples];
        let targets = self.targets.as_ref().expect("ensured above");
        let [r, g, b, a] = frame.background.map(|c| f64::from(c) / 255.0);
        let (view, resolve_target, store) = match &targets.color {
            Some(color) => (color, Some(target), wgpu::StoreOp::Discard),
            None => (target, None, wgpu::StoreOp::Store),
        };
        let mut encoder = self.device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("mds-render"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view,
                    depth_slice: None,
                    resolve_target,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color { r, g, b, a }),
                        store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &targets.depth,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Discard,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_bind_group(0, &self.scene_group, &[]);
            for (&(mesh, _), key) in frame.models.iter().zip(Self::keys(frame)) {
                let res = &self.models[&key];
                pass.set_index_buffer(res.indices.slice(..), wgpu::IndexFormat::Uint32);
                let drawn = || {
                    mesh.materials
                        .iter()
                        .zip(&res.materials)
                        .zip(res.alpha.iter().zip(&res.edge_drawn))
                        .filter(|((m, _), _)| m.count > 0)
                };
                // Materials in file order, then the edges of the materials that have one.
                pass.set_vertex_buffer(0, res.vertices.slice(..));
                for ((m, (_, group)), (&alpha, _)) in drawn() {
                    if alpha <= 0.0 {
                        continue;
                    }
                    pass.set_pipeline(if m.flags & FLAG_DOUBLE_SIDED != 0 {
                        &pipelines.body_two_sided
                    } else {
                        &pipelines.body
                    });
                    pass.set_bind_group(1, group, &[]);
                    pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                }
                pass.set_pipeline(&pipelines.edge);
                pass.set_vertex_buffer(0, res.edge_vertices.slice(..));
                for ((m, (_, group)), (_, &has_edge)) in drawn() {
                    if has_edge {
                        pass.set_bind_group(1, group, &[]);
                        pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                    }
                }
            }
        }
        encoder
    }
}

fn check(frame: &Frame) -> Result<(), String> {
    if frame.width == 0 || frame.height == 0 {
        return Err("empty frame".into());
    }
    Ok(())
}

fn finish(error_scope: wgpu::ErrorScopeGuard) -> Result<(), String> {
    match pollster::block_on(error_scope.pop()) {
        Some(e) => Err(format!("wgpu: {e}")),
        None => Ok(()),
    }
}

/// Bytes of the scene uniform: two matrices and six vectors.
const SCENE_BYTES: u64 = 2 * 64 + 6 * 16;

fn scene_data(frame: &Frame, shift: [f32; 2]) -> Vec<u8> {
    let view = &frame.view;
    let light = view::normalize(frame.light.direction);
    let mut scene = Vec::new();
    scene.extend(view.view_proj.iter().flatten());
    scene.extend(view.view.iter().flatten());
    scene.extend([view.eye[0], view.eye[1], view.eye[2], 1.0]);
    scene.extend([
        light[0],
        light[1],
        light[2],
        f32::from(u8::from(frame.toon)),
    ]);
    scene.extend([
        frame.light.color[0],
        frame.light.color[1],
        frame.light.color[2],
        1.0,
    ]);
    // The shift in clip space: x right, y up.
    scene.extend([
        frame.width as f32,
        frame.height as f32,
        2.0 * shift[0] / frame.width as f32,
        -2.0 * shift[1] / frame.height as f32,
    ]);
    bytes(&scene)
}

fn bytes(f: &[f32]) -> Vec<u8> {
    f.iter().flat_map(|x| x.to_ne_bytes()).collect()
}

fn texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    w: u32,
    h: u32,
    rgba: &[u8],
) -> wgpu::TextureView {
    let size = wgpu::Extent3d {
        width: w,
        height: h,
        depth_or_array_layers: 1,
    };
    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("default texture"),
        size,
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: COLOR_FORMAT,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    queue.write_texture(
        tex.as_image_copy(),
        rgba,
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(w * 4),
            rows_per_image: Some(h),
        },
        size,
    );
    tex.create_view(&Default::default())
}

fn empty_buffer(device: &wgpu::Device, usage: wgpu::BufferUsages, size: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: size.next_multiple_of(4).max(4),
        usage: usage | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

/// The built-in toon ramp, lit end first (v = 0.5 - 0.5 * N.L), 32 texels: full light for texels 0
/// to 10, a linear fall over 11 to 14, then 0.8 (204) from texel 15 on. With the sampler's linear
/// filter that is a ramp from v = 0.33 to 0.49, which is what the golden images show.
fn toon_ramp() -> Vec<u8> {
    (0..32)
        .flat_map(|y| {
            let b = (255.0 - (y as f32 - 10.0).clamp(0.0, 5.0) * 10.2).round() as u8;
            [b, b, b, 255]
        })
        .collect()
}

fn entry(
    binding: u32,
    ty: wgpu::BindingType,
    visibility: wgpu::ShaderStages,
) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility,
        ty,
        count: None,
    }
}

fn uniform_entry(binding: u32, visibility: wgpu::ShaderStages) -> wgpu::BindGroupLayoutEntry {
    entry(
        binding,
        wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        visibility,
    )
}

fn texture_entry(binding: u32) -> wgpu::BindGroupLayoutEntry {
    entry(
        binding,
        wgpu::BindingType::Texture {
            sample_type: wgpu::TextureSampleType::Float { filterable: true },
            view_dimension: wgpu::TextureViewDimension::D2,
            multisampled: false,
        },
        wgpu::ShaderStages::FRAGMENT,
    )
}

fn bind_entry(binding: u32, resource: wgpu::BindingResource) -> wgpu::BindGroupEntry {
    wgpu::BindGroupEntry { binding, resource }
}
