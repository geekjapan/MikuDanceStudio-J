//! Offscreen wgpu rendering of a PMX model in bind pose with MMD-style shading.
//!
//! The model is drawn at a fixed size ([`WIDTH`] x [`HEIGHT`]) from a camera that
//! the model's bounding box fixes, with no multisampling and a fixed clear color,
//! so the same model on the same adapter gives the same bytes.
//!
//! Shading follows the public description of MMD's standard pipeline: material
//! diffuse and ambient colors under a fixed light, a toon ramp lookup, a sphere map
//! (multiply or add), a Blinn-Phong specular term, and an inverted-hull edge for
//! materials with the edge flag. Diffuse alpha blends.
//!
//! Not in this crate yet: texture decoding. Every texture slot (texture, sphere,
//! toon) is bound to a default (white, white, a built-in two-tone ramp), so the
//! sphere map path is in the shader but is not used. See [`render`].

mod png;

use mds_formats::pmx::Pmx;

pub const WIDTH: u32 = 512;
pub const HEIGHT: u32 = 512;
/// Color the target is cleared to (RGBA8).
pub const CLEAR: [u8; 4] = [209, 219, 230, 255];

const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;
/// MMD's default view angle.
const FOV_Y: f32 = 30.0 * std::f32::consts::PI / 180.0;
/// MMD's default light color (154 / 255) and direction.
const LIGHT_COLOR: f32 = 154.0 / 255.0;
const LIGHT_DIR: [f32; 3] = [-0.5, -1.0, 0.5];
const FLAG_DOUBLE_SIDED: u8 = 0x01;
const FLAG_EDGE: u8 = 0x10;

/// Encodes RGBA8 pixels (top row first) as a PNG.
pub use png::encode as encode_png;

// ---- matrices: column-major, left-handed, depth 0 to 1 (Direct3D conventions) ----

type Mat = [[f32; 4]; 4];

fn mul(a: &Mat, b: &Mat) -> Mat {
    let mut r = [[0.0; 4]; 4];
    for (c, col) in r.iter_mut().enumerate() {
        for (row, cell) in col.iter_mut().enumerate() {
            *cell = (0..4).map(|k| a[k][row] * b[c][k]).sum();
        }
    }
    r
}

fn sub(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn dot(a: [f32; 3], b: [f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
fn normalize(a: [f32; 3]) -> [f32; 3] {
    let l = dot(a, a).sqrt();
    [a[0] / l, a[1] / l, a[2] / l]
}

fn look_at_lh(eye: [f32; 3], target: [f32; 3], up: [f32; 3]) -> Mat {
    let z = normalize(sub(target, eye));
    let x = normalize(cross(up, z));
    let y = cross(z, x);
    [
        [x[0], y[0], z[0], 0.0],
        [x[1], y[1], z[1], 0.0],
        [x[2], y[2], z[2], 0.0],
        [-dot(x, eye), -dot(y, eye), -dot(z, eye), 1.0],
    ]
}

fn perspective_lh(fov_y: f32, aspect: f32, near: f32, far: f32) -> Mat {
    let f = 1.0 / (fov_y / 2.0).tan();
    let q = far / (far - near);
    [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, q, 1.0],
        [0.0, 0.0, -near * q, 0.0],
    ]
}

// ---- mesh ----

struct Draw {
    start: u32,
    count: u32,
    material: usize,
}

struct Mesh {
    /// Per vertex: position 3, normal 3, uv 2, edge scale 1.
    vertices: Vec<f32>,
    indices: Vec<u32>,
    draws: Vec<Draw>,
    min: [f32; 3],
    max: [f32; 3],
    /// Side of the Z axis the camera sits on: +1 when the mean vertex normal points toward +Z,
    /// else -1, which is where MMD models face.
    front: f32,
}

fn mesh(pmx: &Pmx) -> Result<Mesh, String> {
    if pmx.vertices.is_empty() {
        return Err("model has no vertices".into());
    }
    let mut vertices = Vec::with_capacity(pmx.vertices.len() * 9);
    let (mut min, mut max) = ([f32::MAX; 3], [f32::MIN; 3]);
    let mut normal_z = 0.0;
    for v in &pmx.vertices {
        normal_z += v.normal[2];
        for i in 0..3 {
            min[i] = min[i].min(v.position[i]);
            max[i] = max[i].max(v.position[i]);
        }
        vertices.extend(v.position);
        vertices.extend(v.normal);
        vertices.extend(v.uv);
        vertices.push(v.edge_scale);
    }
    let n = pmx.vertices.len();
    let indices = pmx
        .indices
        .iter()
        .map(|&i| u32::try_from(i).ok().filter(|&i| (i as usize) < n))
        .collect::<Option<Vec<u32>>>()
        .ok_or("an index is outside the vertex list")?;
    let mut draws = Vec::new();
    let mut start = 0u32;
    for (material, m) in pmx.materials.iter().enumerate() {
        let count = u32::try_from(m.face_vertex_count).map_err(|_| "negative face count")?;
        let end = start
            .checked_add(count)
            .filter(|&e| e as usize <= indices.len());
        if end.is_none() {
            return Err(format!("material {material} reaches past the index list"));
        }
        draws.push(Draw {
            start,
            count,
            material,
        });
        start += count;
    }
    Ok(Mesh {
        vertices,
        indices,
        draws,
        min,
        max,
        front: if normal_z > 0.0 { 1.0 } else { -1.0 },
    })
}

/// The view matrix, view-projection matrix and eye position the bounding box fixes: MMD's view angle, looking at the box center from
/// the side the model faces (`front`, -Z for an MMD model), a little to the right and above, far enough that the box's bounding
/// sphere fits.
fn camera(min: [f32; 3], max: [f32; 3], front: f32) -> (Mat, Mat, [f32; 3]) {
    let center = [0, 1, 2].map(|i| (min[i] + max[i]) / 2.0);
    let radius = (dot(sub(max, min), sub(max, min)).sqrt() / 2.0).max(1e-3);
    let dist = radius / (FOV_Y / 2.0).sin() * 1.1;
    let dir = normalize([0.25, 0.2, front]);
    let eye = [0, 1, 2].map(|i| center[i] + dir[i] * dist);
    let view = look_at_lh(eye, center, [0.0, 1.0, 0.0]);
    let proj = perspective_lh(
        FOV_Y,
        WIDTH as f32 / HEIGHT as f32,
        (dist - radius * 2.0).max(dist * 0.05),
        dist + radius * 2.0,
    );
    (view, mul(&proj, &view), eye)
}

// ---- gpu ----

/// A wgpu device with no window.
pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    /// `name|backend`, the key the hash regression test records hashes under.
    pub adapter: String,
}

impl Gpu {
    /// `Ok(None)` when the host has no adapter. `WGPU_BACKEND` overrides the backend.
    pub fn new() -> Result<Option<Gpu>, String> {
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
        let Ok(adapter) =
            pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default()))
        else {
            return Ok(None);
        };
        let info = adapter.get_info();
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("mds-render"),
            ..Default::default()
        }))
        .map_err(|e| format!("cannot create a device on {}: {e}", info.name))?;
        Ok(Some(Gpu {
            device,
            queue,
            adapter: format!("{}|{:?}", info.name, info.backend),
        }))
    }
}

fn bytes(f: &[f32]) -> Vec<u8> {
    f.iter().flat_map(|x| x.to_ne_bytes()).collect()
}

fn texture(gpu: &Gpu, w: u32, h: u32, rgba: &[u8]) -> wgpu::TextureView {
    let size = wgpu::Extent3d {
        width: w,
        height: h,
        depth_or_array_layers: 1,
    };
    let tex = gpu.device.create_texture(&wgpu::TextureDescriptor {
        label: Some("default texture"),
        size,
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: COLOR_FORMAT,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    gpu.queue.write_texture(
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

fn buffer(gpu: &Gpu, usage: wgpu::BufferUsages, data: &[u8]) -> wgpu::Buffer {
    let b = gpu.device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: (data.len() as u64).next_multiple_of(4).max(4),
        usage: usage | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    gpu.queue.write_buffer(&b, 0, data);
    b
}

/// The default toon ramp, lit end first: full light for the lit half, then a fall to 0.55.
fn toon_ramp() -> Vec<u8> {
    (0..32)
        .flat_map(|y| {
            let v = if y < 16 {
                255
            } else {
                (255.0 - (y - 15) as f32 / 16.0 * 115.0).round() as u8
            };
            [v, v, v, 255]
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

/// Renders `pmx` in bind pose and returns `WIDTH * HEIGHT * 4` RGBA8 bytes, top row first.
///
/// Texture slots are not decoded yet: texture and sphere are white, toon is the built-in ramp
/// whatever the material names, and the sphere mode is passed as 0 (off).
pub fn render(gpu: &Gpu, pmx: &Pmx) -> Result<Vec<u8>, String> {
    let mesh = mesh(pmx)?;
    let (view, view_proj, eye) = camera(mesh.min, mesh.max, mesh.front);
    let both = wgpu::ShaderStages::VERTEX_FRAGMENT;

    let error_scope = gpu.device.push_error_scope(wgpu::ErrorFilter::Validation);

    let shader = gpu
        .device
        .create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("mds-render"),
            source: wgpu::ShaderSource::Wgsl(include_str!("shader.wgsl").into()),
        });
    let scene_layout = gpu
        .device
        .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[uniform_entry(0, both)],
        });
    let material_layout = gpu
        .device
        .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
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
    let layout = gpu
        .device
        .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[Some(&scene_layout), Some(&material_layout)],
            immediate_size: 0,
        });

    let attrs =
        wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32];
    let pipeline =
        |vs: &str, fs: &str, cull: Option<wgpu::Face>, blend: Option<wgpu::BlendState>| {
            gpu.device
                .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some(vs),
                    layout: Some(&layout),
                    vertex: wgpu::VertexState {
                        module: &shader,
                        entry_point: Some(vs),
                        compilation_options: Default::default(),
                        buffers: &[Some(wgpu::VertexBufferLayout {
                            array_stride: 36,
                            step_mode: wgpu::VertexStepMode::Vertex,
                            attributes: &attrs,
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
                    multisample: Default::default(),
                    fragment: Some(wgpu::FragmentState {
                        module: &shader,
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
    let body = pipeline("vs_main", "fs_main", Some(wgpu::Face::Back), alpha);
    let body_two_sided = pipeline("vs_main", "fs_main", None, alpha);
    let edge = pipeline("vs_edge", "fs_edge", Some(wgpu::Face::Front), alpha);

    let light = normalize(LIGHT_DIR);
    let mut scene = Vec::new();
    scene.extend(view_proj.iter().flatten());
    scene.extend(view.iter().flatten());
    scene.extend([eye[0], eye[1], eye[2], 1.0]);
    scene.extend([light[0], light[1], light[2], 0.0]);
    scene.extend([LIGHT_COLOR, LIGHT_COLOR, LIGHT_COLOR, 1.0]);
    scene.extend([WIDTH as f32, HEIGHT as f32, 0.0, 0.0]);
    let scene_buf = buffer(gpu, wgpu::BufferUsages::UNIFORM, &bytes(&scene));
    let scene_group = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &scene_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: scene_buf.as_entire_binding(),
        }],
    });

    let white = texture(gpu, 1, 1, &[255; 4]);
    let toon = texture(gpu, 1, 32, &toon_ramp());
    let sampler = gpu.device.create_sampler(&wgpu::SamplerDescriptor {
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });
    let material_groups: Vec<wgpu::BindGroup> = pmx
        .materials
        .iter()
        .map(|m| {
            let u = [
                m.diffuse.as_slice(),
                &[m.ambient[0], m.ambient[1], m.ambient[2], 1.0],
                &[
                    m.specular[0],
                    m.specular[1],
                    m.specular[2],
                    m.specular_power,
                ],
                m.edge_color.as_slice(),
                &[m.edge_size, 0.0, 0.0, 0.0],
            ]
            .concat();
            let buf = buffer(gpu, wgpu::BufferUsages::UNIFORM, &bytes(&u));
            let group = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &material_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: buf.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&white),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::TextureView(&white),
                    },
                    wgpu::BindGroupEntry {
                        binding: 3,
                        resource: wgpu::BindingResource::TextureView(&toon),
                    },
                    wgpu::BindGroupEntry {
                        binding: 4,
                        resource: wgpu::BindingResource::Sampler(&sampler),
                    },
                ],
            });
            group
        })
        .collect();

    let vertex_buf = buffer(gpu, wgpu::BufferUsages::VERTEX, &bytes(&mesh.vertices));
    let index_data: Vec<u8> = mesh.indices.iter().flat_map(|i| i.to_ne_bytes()).collect();
    let index_buf = buffer(gpu, wgpu::BufferUsages::INDEX, &index_data);

    let size = wgpu::Extent3d {
        width: WIDTH,
        height: HEIGHT,
        depth_or_array_layers: 1,
    };
    let target = gpu.device.create_texture(&wgpu::TextureDescriptor {
        label: Some("target"),
        size,
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: COLOR_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let depth = gpu.device.create_texture(&wgpu::TextureDescriptor {
        label: Some("depth"),
        size,
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: DEPTH_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    // 512 * 4 is a multiple of 256, the row alignment of buffer copies.
    let read_buf = gpu.device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("readback"),
        size: u64::from(WIDTH * HEIGHT * 4),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });

    let mut encoder = gpu.device.create_command_encoder(&Default::default());
    {
        let target_view = target.create_view(&Default::default());
        let depth_view = depth.create_view(&Default::default());
        let [r, g, b, a] = CLEAR.map(|c| f64::from(c) / 255.0);
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("mds-render"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &target_view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color { r, g, b, a }),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &depth_view,
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
        pass.set_bind_group(0, &scene_group, &[]);
        pass.set_vertex_buffer(0, vertex_buf.slice(..));
        pass.set_index_buffer(index_buf.slice(..), wgpu::IndexFormat::Uint32);
        // Materials in file order, then the edges of the materials that have one.
        for d in mesh.draws.iter().filter(|d| d.count > 0) {
            let m = &pmx.materials[d.material];
            if m.diffuse[3] <= 0.0 {
                continue;
            }
            pass.set_pipeline(if m.flags & FLAG_DOUBLE_SIDED != 0 {
                &body_two_sided
            } else {
                &body
            });
            pass.set_bind_group(1, &material_groups[d.material], &[]);
            pass.draw_indexed(d.start..d.start + d.count, 0, 0..1);
        }
        pass.set_pipeline(&edge);
        for d in mesh.draws.iter().filter(|d| d.count > 0) {
            let m = &pmx.materials[d.material];
            if m.flags & FLAG_EDGE == 0 || m.edge_color[3] <= 0.0 {
                continue;
            }
            pass.set_bind_group(1, &material_groups[d.material], &[]);
            pass.draw_indexed(d.start..d.start + d.count, 0, 0..1);
        }
    }
    encoder.copy_texture_to_buffer(
        target.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &read_buf,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(WIDTH * 4),
                rows_per_image: Some(HEIGHT),
            },
        },
        size,
    );
    gpu.queue.submit([encoder.finish()]);

    let slice = read_buf.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| {
        let _ = tx.send(r);
    });
    gpu.device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|e| format!("poll: {e}"))?;
    rx.recv()
        .map_err(|e| e.to_string())?
        .map_err(|e| format!("map readback buffer: {e}"))?;
    let pixels = slice
        .get_mapped_range()
        .map_err(|e| format!("read readback buffer: {e}"))?
        .to_vec();
    read_buf.unmap();

    if let Some(e) = pollster::block_on(error_scope.pop()) {
        return Err(format!("wgpu: {e}"));
    }
    Ok(pixels)
}
