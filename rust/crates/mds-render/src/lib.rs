//! Offscreen wgpu rendering of PMX and PMD models with MMD-style shading.
//!
//! Two entry points:
//!
//! * [`render`] draws one PMX in bind pose from a camera that its bounding box fixes, at
//!   [`WIDTH`] x [`HEIGHT`], with no multisampling. The image-hash test records it.
//! * [`render_frame`] draws a posed scene: any number of [`Mesh`]es with a [`Pose`] each, from the
//!   PMM [`Camera`] and [`Light`] of a frame ([`scene`] reads them from a PMM), averaging
//!   several sub-pixel shifted renders the way an 8x multisample resolve averages its samples, in
//!   linear light (the golden images' resolve is gamma correct).
//!
//! Shading follows MMD's standard pipeline as the golden images show it: the color is
//! `saturate(ambient + diffuse * light)` times the texture, the sphere map (multiply or add) and the
//! toon ramp looked up by the angle to the light, plus a Blinn-Phong highlight
//! `specular * light * (N.H)^power` that uses the eye position (a local viewer, also under the
//! orthographic projection). Materials with the edge flag get an inverted-hull edge. Diffuse alpha
//! blends.
//!
//! Not in this crate yet: texture decoding. Every texture slot (texture, sphere, toon) is bound
//! to a default (white, white, a built-in toon ramp).

mod mesh;
mod png;
pub mod scene;
mod view;

use mds_formats::pmx::Pmx;
pub use mesh::{Mesh, Pose};
use mesh::{FLAG_DOUBLE_SIDED, FLAG_EDGE};
pub use view::{Camera, Light, View};

pub const WIDTH: u32 = 512;
pub const HEIGHT: u32 = 512;
/// Color the bind-pose target is cleared to (RGBA8).
pub const CLEAR: [u8; 4] = [209, 219, 230, 255];

const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

/// Encodes RGBA8 pixels (top row first) as a PNG.
pub use png::encode as encode_png;

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

/// How far the edge pass pushes a back face along its normal per unit of the material's edge size,
/// in the model's own units. Fitted to the golden images: the whole picture of frames 150, 300 and
/// 599 is closest for 0.019 to 0.0205 (the error is flat there), and a width in screen pixels
/// (tried from 0.25 to 3 px) fits worse. The golden scene is orthographic, so how the C++ app
/// scales the edge with distance under a perspective camera is not known.
const EDGE_WORLD: f32 = 0.02;

/// What [`render_frame`] draws.
pub struct Frame<'a> {
    pub width: u32,
    pub height: u32,
    pub view: View,
    pub light: Light,
    /// Color the target is cleared to (RGBA8).
    pub background: [u8; 4],
    /// Whether the toon ramp darkens the faces turned from the light.
    pub toon: bool,
    /// Models in draw order, each with its pose (`None` draws the bind pose).
    pub models: &'a [(&'a Mesh, Option<&'a Pose>)],
    /// One render per entry, the content shifted by the negated offset (in pixels from the pixel
    /// center, y down), then all renders averaged. `[[0.0, 0.0]]` is a single render.
    pub samples: &'a [[f32; 2]],
    /// Shifts the whole picture by this many pixels (x right, y down); [`PIXEL_OFFSET_D3D9`] for
    /// the picture the C++ app writes.
    pub pixel_offset: [f32; 2],
}

/// The golden images sit half a pixel right and down of where the viewport transform of Direct3D 11
/// and wgpu puts a point: the models' edges and the 8 and 12 unit spacing of the model roots fit at
/// this offset to a few hundredths of a pixel (Direct3D 9 puts pixel centers on integer
/// coordinates).
pub const PIXEL_OFFSET_D3D9: [f32; 2] = [0.5, 0.5];

/// The sample positions of Direct3D's standard 8x multisample pattern, in pixels from the pixel
/// center (y down): the grid of 16ths `(1,-3) (-1,3) (5,1) (-3,-5) (-5,5) (-7,-1) (3,7) (7,-7)`.
pub const SAMPLES_8X: [[f32; 2]; 8] = [
    [1.0 / 16.0, -3.0 / 16.0],
    [-1.0 / 16.0, 3.0 / 16.0],
    [5.0 / 16.0, 1.0 / 16.0],
    [-3.0 / 16.0, -5.0 / 16.0],
    [-5.0 / 16.0, 5.0 / 16.0],
    [-7.0 / 16.0, -1.0 / 16.0],
    [3.0 / 16.0, 7.0 / 16.0],
    [7.0 / 16.0, -7.0 / 16.0],
];

fn bind_entry(binding: u32, resource: wgpu::BindingResource) -> wgpu::BindGroupEntry {
    wgpu::BindGroupEntry { binding, resource }
}

/// Renders `pmx` in bind pose and returns `WIDTH * HEIGHT * 4` RGBA8 bytes, top row first.
///
/// Texture slots are not decoded yet: texture and sphere are white, toon is the built-in ramp
/// whatever the material names, and the sphere mode is passed as 0 (off).
pub fn render(gpu: &Gpu, pmx: &Pmx) -> Result<Vec<u8>, String> {
    let mesh = Mesh::from_pmx(pmx)?;
    let (min, max) = mesh.bounds();
    render_frame(
        gpu,
        &Frame {
            width: WIDTH,
            height: HEIGHT,
            view: view::bounding_box_view(min, max, mesh.front(), WIDTH as f32 / HEIGHT as f32),
            light: view::DEFAULT_LIGHT,
            background: CLEAR,
            toon: true,
            models: &[(&mesh, None)],
            samples: &[[0.0, 0.0]],
            pixel_offset: [0.0, 0.0],
        },
    )
}

/// Renders a posed scene and returns `width * height * 4` RGBA8 bytes, top row first.
pub fn render_frame(gpu: &Gpu, frame: &Frame) -> Result<Vec<u8>, String> {
    let (width, height) = (frame.width, frame.height);
    if width == 0 || height == 0 || frame.samples.is_empty() {
        return Err("empty frame".into());
    }
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

    let light = view::normalize(frame.light.direction);
    let scene_data = |shift: [f32; 2]| {
        let view = &frame.view;
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
            width as f32,
            height as f32,
            2.0 * shift[0] / width as f32,
            -2.0 * shift[1] / height as f32,
        ]);
        bytes(&scene)
    };
    let scene_buf = buffer(gpu, wgpu::BufferUsages::UNIFORM, &scene_data([0.0; 2]));
    let scene_group = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &scene_layout,
        entries: &[bind_entry(0, scene_buf.as_entire_binding())],
    });

    let white = texture(gpu, 1, 1, &[255; 4]);
    let toon = texture(gpu, 1, 32, &toon_ramp());
    let sampler = gpu.device.create_sampler(&wgpu::SamplerDescriptor {
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });

    struct Resident<'a> {
        mesh: &'a Mesh,
        vertices: wgpu::Buffer,
        indices: wgpu::Buffer,
        /// The material's uniform buffer is kept alive by its bind group.
        groups: Vec<wgpu::BindGroup>,
    }
    let residents: Vec<Resident> = frame
        .models
        .iter()
        .map(|&(mesh, pose)| {
            let index_data: Vec<u8> = mesh.indices.iter().flat_map(|i| i.to_ne_bytes()).collect();
            let groups = mesh
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
                        &[m.edge_size * EDGE_WORLD, 0.0, 0.0, 0.0],
                    ]
                    .concat();
                    let buf = buffer(gpu, wgpu::BufferUsages::UNIFORM, &bytes(&u));
                    gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: None,
                        layout: &material_layout,
                        entries: &[
                            bind_entry(0, buf.as_entire_binding()),
                            bind_entry(1, wgpu::BindingResource::TextureView(&white)),
                            bind_entry(2, wgpu::BindingResource::TextureView(&white)),
                            bind_entry(3, wgpu::BindingResource::TextureView(&toon)),
                            bind_entry(4, wgpu::BindingResource::Sampler(&sampler)),
                        ],
                    })
                })
                .collect();
            Resident {
                mesh,
                vertices: buffer(
                    gpu,
                    wgpu::BufferUsages::VERTEX,
                    &bytes(&mesh.vertex_data(pose)),
                ),
                indices: buffer(gpu, wgpu::BufferUsages::INDEX, &index_data),
                groups,
            }
        })
        .collect();

    let size = wgpu::Extent3d {
        width,
        height,
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
    let row_bytes = width * 4;
    let padded_row = row_bytes.next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
    let read_buf = gpu.device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("readback"),
        size: u64::from(padded_row * height),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let target_view = target.create_view(&Default::default());
    let depth_view = depth.create_view(&Default::default());
    let [r, g, b, a] = frame.background.map(|c| f64::from(c) / 255.0);

    let to_linear = srgb_to_linear_table();
    let mut sum = vec![0f32; (width * height * 4) as usize];
    for sample in frame.samples {
        let shift = [
            frame.pixel_offset[0] - sample[0],
            frame.pixel_offset[1] - sample[1],
        ];
        gpu.queue.write_buffer(&scene_buf, 0, &scene_data(shift));
        let mut encoder = gpu.device.create_command_encoder(&Default::default());
        {
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
            for res in &residents {
                pass.set_vertex_buffer(0, res.vertices.slice(..));
                pass.set_index_buffer(res.indices.slice(..), wgpu::IndexFormat::Uint32);
                let drawn = || {
                    res.mesh
                        .materials
                        .iter()
                        .zip(&res.groups)
                        .filter(|(m, _)| m.count > 0)
                };
                // Materials in file order, then the edges of the materials that have one.
                for (m, group) in drawn() {
                    if m.diffuse[3] <= 0.0 {
                        continue;
                    }
                    pass.set_pipeline(if m.flags & FLAG_DOUBLE_SIDED != 0 {
                        &body_two_sided
                    } else {
                        &body
                    });
                    pass.set_bind_group(1, group, &[]);
                    pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                }
                pass.set_pipeline(&edge);
                for (m, group) in drawn() {
                    if m.flags & FLAG_EDGE == 0 || m.edge_color[3] <= 0.0 {
                        continue;
                    }
                    pass.set_bind_group(1, group, &[]);
                    pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                }
            }
        }
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
    if let Some(e) = pollster::block_on(error_scope.pop()) {
        return Err(format!("wgpu: {e}"));
    }
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

fn srgb_to_linear_table() -> [f32; 256] {
    std::array::from_fn(|i| {
        let c = i as f32 / 255.0;
        if c <= 0.04045 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    })
}

fn linear_to_srgb(l: f32) -> f32 {
    if l <= 0.003_130_8 {
        l * 12.92
    } else {
        1.055 * l.powf(1.0 / 2.4) - 0.055
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn srgb_round_trip_keeps_every_8_bit_value() {
        let table = super::srgb_to_linear_table();
        for (v, &lin) in table.iter().enumerate() {
            assert_eq!((super::linear_to_srgb(lin) * 255.0).round() as usize, v);
        }
    }
}
