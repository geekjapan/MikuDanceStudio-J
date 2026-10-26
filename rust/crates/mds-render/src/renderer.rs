//! [`Renderer`]: the pipelines, the default textures and the per-model buffers, kept between frames
//! on a device the caller owns.

use crate::mesh::{
    EdgeView, FLAG_DOUBLE_SIDED, FLAG_EDGE, FLAG_GROUND_SHADOW, FLAG_SHADOW_CAST,
    FLAG_SHADOW_RECEIVE,
};
use crate::Image;
use crate::{
    linear_to_srgb, srgb_to_linear_table, view, Frame, Mesh, Stage, COLOR_FORMAT, DEPTH_FORMAT,
};
use std::collections::HashMap;
use std::sync::Arc;

/// Bytes per vertex of the body buffer (position, normal, uv) and of the edge buffer (position,
/// `A8R8G8B8` color).
const BODY_STRIDE: u64 = 32;
const EDGE_STRIDE: u64 = 16;
/// Bytes of a material's uniform block: diffuse, ambient, specular, a parameter vector, and the
/// emissive color of an accessory.
const MATERIAL_BYTES: u64 = 80;

/// A model of a frame: the mesh and how many models of the same mesh came before it in the frame
/// (one mesh can be drawn twice with two poses).
type Key = (u64, u32);

struct Pipelines {
    body: wgpu::RenderPipeline,
    body_two_sided: wgpu::RenderPipeline,
    edge: wgpu::RenderPipeline,
    ground_shadow: wgpu::RenderPipeline,
    accessory: wgpu::RenderPipeline,
    picture: wgpu::RenderPipeline,
    /// Depth from the light, both sides of every face (golden2 `selfshadow-*.png`: 0.9977 and
    /// 0.9973 within 4, against 0.994 culling back faces and 0.984 culling front faces).
    shadow: wgpu::RenderPipeline,
}

/// Render pipelines in one [`Pipelines`] set.
const PIPELINES_PER_SET: usize = 7;

/// The self-shadow map: its size (the render target of the `shadow` lines of the golden2 probes,
/// the app's default) and its format.
const SHADOW_MAP_SIZE: u32 = 2048;
const SHADOW_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

fn depth_state(write: bool, stencil: wgpu::StencilState) -> wgpu::DepthStencilState {
    wgpu::DepthStencilState {
        format: DEPTH_FORMAT,
        depth_write_enabled: Some(write),
        depth_compare: Some(wgpu::CompareFunction::LessEqual),
        stencil,
        bias: Default::default(),
    }
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
    /// Accessories: the first index and index count of each material's faces.
    ranges: Vec<(u32, u32)>,
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
    /// The scene uniform alone, for the pass that draws the shadow map.
    light_layout: wgpu::PipelineLayout,
    light_group: wgpu::BindGroup,
    shadow_map: wgpu::TextureView,
    white: wgpu::TextureView,
    toon: wgpu::TextureView,
    /// Bilinear; the texture slot repeats (Direct3D's default wrap address mode) and blends its
    /// mip levels, the sphere and toon slots clamp and read level 0. The mip blend is chosen by
    /// golden2 `accessory-30.png`, whose cube shows one face edge on: 37 pixels beyond the
    /// tolerance with it, 50 without. Anisotropic filtering (a clamp of 4, 8 or 16 gives the same
    /// image, 2 does not) passes that image. The background picture keeps `picture_sampler`, the
    /// same without anisotropy (`background-0.png`: 0.98805 within 4, 0.98692 with it).
    repeat: wgpu::Sampler,
    picture_sampler: wgpu::Sampler,
    sampler: wgpu::Sampler,
    pipelines: HashMap<u32, Pipelines>,
    pipelines_created: usize,
    models: HashMap<Key, Prepared>,
    /// The last background picture: the image it was made from, its uniform and bind group.
    picture: Option<(Arc<Image>, wgpu::Buffer, wgpu::BindGroup)>,
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
        let light_scene_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: None,
                entries: &[uniform_entry(0, both)],
            });
        let scene_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[
                uniform_entry(0, both),
                entry(
                    1,
                    wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Depth,
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    wgpu::ShaderStages::FRAGMENT,
                ),
            ],
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
                entry(
                    5,
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
        let shadow_map = device
            .create_texture(&wgpu::TextureDescriptor {
                label: Some("self-shadow map"),
                size: wgpu::Extent3d {
                    width: SHADOW_MAP_SIZE,
                    height: SHADOW_MAP_SIZE,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: SHADOW_FORMAT,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            })
            .create_view(&Default::default());
        let scene_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &scene_layout,
            entries: &[
                bind_entry(0, scene_buf.as_entire_binding()),
                bind_entry(1, wgpu::BindingResource::TextureView(&shadow_map)),
            ],
        });
        let light_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &light_scene_layout,
            entries: &[bind_entry(0, scene_buf.as_entire_binding())],
        });
        let light_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[Some(&light_scene_layout)],
            immediate_size: 0,
        });
        let repeat = wgpu::SamplerDescriptor {
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::Repeat,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::MipmapFilterMode::Linear,
            ..Default::default()
        };
        let renderer = Renderer {
            white: texture(device, queue, &[Image::new(1, 1, vec![255; 4])]),
            toon: texture(device, queue, &[Image::new(1, 32, toon_ramp())]),
            sampler: device.create_sampler(&wgpu::SamplerDescriptor {
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                ..Default::default()
            }),
            repeat: device.create_sampler(&wgpu::SamplerDescriptor {
                anisotropy_clamp: 16,
                ..repeat.clone()
            }),
            picture_sampler: device.create_sampler(&repeat),
            device: device.clone(),
            queue: queue.clone(),
            shader,
            material_layout,
            layout,
            scene_buf,
            scene_group,
            light_layout,
            light_group,
            shadow_map,
            pipelines: HashMap::new(),
            pipelines_created: 0,
            models: HashMap::new(),
            picture: None,
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
        self.render_into_with(target, frame, &Stage::legacy(frame), sample_count)
    }

    /// [`render_into`](Renderer::render_into) with the passes of `stage`.
    pub fn render_into_with(
        &mut self,
        target: &wgpu::TextureView,
        frame: &Frame,
        stage: &Stage,
        sample_count: u32,
    ) -> Result<(), String> {
        check(frame)?;
        if !matches!(sample_count, 1 | 2 | 4 | 8) {
            return Err(format!("unsupported sample count {sample_count}"));
        }
        let error_scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        self.upload(frame, stage);
        let encoder = self.encode(target, frame, stage, frame.pixel_offset, sample_count);
        self.queue.submit([encoder.finish()]);
        finish(error_scope)
    }

    /// Draws `frame` and returns `width * height * 4` RGBA8 bytes, top row first: one render per
    /// entry of `frame.samples` (no multisampling), averaged in linear light.
    pub fn render_frame(&mut self, frame: &Frame) -> Result<Vec<u8>, String> {
        self.render_frame_with(frame, &Stage::legacy(frame))
    }

    /// [`render_frame`](Renderer::render_frame) with the passes of `stage`.
    pub fn render_frame_with(&mut self, frame: &Frame, stage: &Stage) -> Result<Vec<u8>, String> {
        check(frame)?;
        if frame.samples.is_empty() {
            return Err("empty frame".into());
        }
        let (width, height) = (frame.width, frame.height);
        let error_scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        self.upload(frame, stage);

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
            let mut encoder = self.encode(&target_view, frame, stage, shift, 1);
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
    fn upload(&mut self, frame: &Frame, stage: &Stage) {
        let keys = Self::keys(frame);
        let edge_view = EdgeView {
            world: frame.view.edge_world.concat().try_into().expect("4 x 4"),
            camera_position: frame.view.edge_origin,
            fov: frame.view.edge_fov,
            self_shadow: stage.self_shadow.is_some_and(|s| s.shades()),
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
                let prepared = self.prepare(mesh);
                self.models.insert(*key, prepared);
            }
            let p = self.models.get_mut(key).expect("inserted above");
            self.queue.write_buffer(&p.vertices, 0, &bytes(&body));
            self.queue.write_buffer(&p.edge_vertices, 0, &edge_data);
            for (k, (m, (buf, _))) in skin.materials.iter().zip(&p.materials).enumerate() {
                let t = &mesh.materials[k].textures;
                let params = [
                    f32::from(u8::from(t.texture.is_some())),
                    t.sphere
                        .as_ref()
                        .map_or(0.0, |(_, mode)| *mode as u8 as f32),
                    f32::from(u8::from(mesh.materials[k].flags & FLAG_SHADOW_RECEIVE != 0)),
                    0.0,
                ];
                let u = [
                    diffuse(m).as_slice(),
                    &[m.ambient[0], m.ambient[1], m.ambient[2], 1.0],
                    &[
                        m.specular[0],
                        m.specular[1],
                        m.specular[2],
                        m.specular_power,
                    ],
                    &params,
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
        if let Some(pic) = &stage.picture {
            if !self
                .picture
                .as_ref()
                .is_some_and(|(img, _, _)| Arc::ptr_eq(img, pic.image))
            {
                let view = self.view_of(&mut HashMap::new(), &Some(pic.image.clone()), &self.white);
                let (buf, group) = self
                    .material_groups(
                        vec![[view, self.white.clone(), self.toon.clone()]],
                        &self.picture_sampler,
                    )
                    .pop()
                    .expect("one group");
                self.picture = Some((pic.image.clone(), buf, group));
            }
            let (_, buf, _) = self.picture.as_ref().expect("set above");
            let mut u = pic.rect.to_vec();
            u.resize((MATERIAL_BYTES / 4) as usize, 0.0);
            self.queue.write_buffer(buf, 0, &bytes(&u));
        }
        let accessory_keys = Self::accessory_keys(stage);
        for (a, key) in stage.accessories.iter().zip(&accessory_keys) {
            if !self.models.contains_key(key) {
                let prepared = self.prepare_accessory(a.mesh);
                self.models.insert(*key, prepared);
            }
            let w = a.world;
            let body: Vec<f32> = a
                .mesh
                .accessory
                .vertices
                .iter()
                .flat_map(|v| {
                    let [x, y, z] = v.position;
                    let p: [f32; 3] =
                        std::array::from_fn(|c| x * w[c] + y * w[4 + c] + z * w[8 + c] + w[12 + c]);
                    let [x, y, z] = v.normal;
                    let n = view::normalize(std::array::from_fn(|c| {
                        x * w[c] + y * w[4 + c] + z * w[8 + c]
                    }));
                    [
                        p[0],
                        p[1],
                        p[2],
                        n[0],
                        n[1],
                        n[2],
                        v.texcoord[0],
                        v.texcoord[1],
                    ]
                })
                .collect();
            let p = self.models.get_mut(key).expect("inserted above");
            self.queue.write_buffer(&p.vertices, 0, &bytes(&body));
            p.alpha.clear();
            for ((m, (buf, _)), t) in a
                .mesh
                .accessory
                .materials
                .iter()
                .zip(&p.materials)
                .zip(&a.mesh.textures)
            {
                let alpha = mds_accessory::transform::drawn_alpha(m, a.state.opacity);
                p.alpha.push(alpha);
                let params = [
                    f32::from(u8::from(t.texture.is_some())),
                    t.sphere
                        .as_ref()
                        .map_or(0.0, |(_, mode)| *mode as u8 as f32),
                    f32::from(u8::from(a.state.shadow_enabled)),
                    stage.ground_shadow.map_or(1.0, |g| g.ambient),
                ];
                let [dr, dg, db, _] = m.diffuse;
                let [sr, sg, sb, _] = m.specular;
                let u = [
                    [dr, dg, db, alpha],
                    m.ambient,
                    [sr, sg, sb, m.power],
                    params,
                    m.emissive,
                ]
                .concat();
                self.queue.write_buffer(buf, 0, &bytes(&u));
            }
        }
        self.models
            .retain(|k, _| keys.contains(k) || accessory_keys.contains(k));
    }

    /// The keys of the accessories of `stage`, in order.
    fn accessory_keys(stage: &Stage) -> Vec<Key> {
        let mut seen: HashMap<u64, u32> = HashMap::new();
        stage
            .accessories
            .iter()
            .map(|a| {
                let n = seen.entry(a.mesh.id).or_default();
                *n += 1;
                (a.mesh.id, *n - 1)
            })
            .collect()
    }

    /// Buffers for an accessory: its faces ordered by material, as `DrawSubset` draws them.
    fn prepare_accessory(&self, mesh: &crate::AccessoryMesh) -> Prepared {
        let device = &self.device;
        let acc = &mesh.accessory;
        let mut indices = Vec::with_capacity(acc.indices.len());
        let ranges = (0..acc.materials.len())
            .map(|k| {
                let start = indices.len() as u32;
                for f in acc.subset_faces(k) {
                    indices.extend_from_slice(&acc.indices[3 * f..3 * f + 3]);
                }
                (start, indices.len() as u32 - start)
            })
            .collect();
        let index_data: Vec<u8> = indices.iter().flat_map(|i| i.to_ne_bytes()).collect();
        let index_buf = empty_buffer(device, wgpu::BufferUsages::INDEX, index_data.len() as u64);
        self.queue.write_buffer(&index_buf, 0, &index_data);
        let mut uploaded = HashMap::new();
        let views = mesh
            .textures
            .iter()
            .map(|t| {
                let sphere = t.sphere.as_ref().map(|(img, _)| img.clone());
                [
                    self.view_of(&mut uploaded, &t.texture, &self.white),
                    self.view_of(&mut uploaded, &sphere, &self.white),
                    self.toon.clone(),
                ]
            })
            .collect();
        Prepared {
            vertices: empty_buffer(
                device,
                wgpu::BufferUsages::VERTEX,
                acc.vertices.len() as u64 * BODY_STRIDE,
            ),
            edge_vertices: empty_buffer(device, wgpu::BufferUsages::VERTEX, 4),
            indices: index_buf,
            materials: self.material_groups(views, &self.repeat),
            edge_drawn: Vec::new(),
            alpha: Vec::new(),
            ranges,
        }
    }

    /// The GPU texture of `img` (made once per image), or `default`.
    fn view_of(
        &self,
        uploaded: &mut HashMap<*const Image, wgpu::TextureView>,
        img: &Option<Arc<Image>>,
        default: &wgpu::TextureView,
    ) -> wgpu::TextureView {
        img.as_ref().map_or(default.clone(), |img| {
            uploaded
                .entry(Arc::as_ptr(img))
                .or_insert_with(|| texture(&self.device, &self.queue, &img.mip_chain()))
                .clone()
        })
    }

    /// A uniform buffer and a bind group per material, over its texture, sphere and toon views.
    fn material_groups(
        &self,
        views: Vec<[wgpu::TextureView; 3]>,
        texture_sampler: &wgpu::Sampler,
    ) -> Vec<(wgpu::Buffer, wgpu::BindGroup)> {
        views
            .iter()
            .map(|[tex, sphere, toon]| {
                let buf = empty_buffer(&self.device, wgpu::BufferUsages::UNIFORM, MATERIAL_BYTES);
                let group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: None,
                    layout: &self.material_layout,
                    entries: &[
                        bind_entry(0, buf.as_entire_binding()),
                        bind_entry(1, wgpu::BindingResource::TextureView(tex)),
                        bind_entry(2, wgpu::BindingResource::TextureView(sphere)),
                        bind_entry(3, wgpu::BindingResource::TextureView(toon)),
                        bind_entry(4, wgpu::BindingResource::Sampler(texture_sampler)),
                        bind_entry(5, wgpu::BindingResource::Sampler(&self.sampler)),
                    ],
                });
                (buf, group)
            })
            .collect()
    }

    /// Buffers for `mesh`, with the sizes its vertex count and material count fix; the contents
    /// come with the first upload.
    fn prepare(&self, mesh: &Mesh) -> Prepared {
        let device = &self.device;
        let index_data: Vec<u8> = mesh.indices.iter().flat_map(|i| i.to_ne_bytes()).collect();
        let indices = empty_buffer(device, wgpu::BufferUsages::INDEX, index_data.len() as u64);
        self.queue.write_buffer(&indices, 0, &index_data);
        let vertices = mesh.vertex_count() as u64;
        let mut uploaded = HashMap::new();
        let views = mesh
            .materials
            .iter()
            .map(|m| {
                let t = &m.textures;
                let sphere = t.sphere.as_ref().map(|(img, _)| img.clone());
                [
                    self.view_of(&mut uploaded, &t.texture, &self.white),
                    self.view_of(&mut uploaded, &sphere, &self.white),
                    self.view_of(&mut uploaded, &t.toon, &self.toon),
                ]
            })
            .collect();
        Prepared {
            vertices: empty_buffer(device, wgpu::BufferUsages::VERTEX, vertices * BODY_STRIDE),
            edge_vertices: empty_buffer(device, wgpu::BufferUsages::VERTEX, vertices * EDGE_STRIDE),
            indices,
            materials: self.material_groups(views, &self.repeat),
            edge_drawn: Vec::new(),
            alpha: Vec::new(),
            ranges: Vec::new(),
        }
    }

    /// The pipelines for `samples` and the depth and multisample targets for `size`, built if the
    /// last call did not have them.
    fn ensure(&mut self, size: (u32, u32), samples: u32) {
        if !self.pipelines.contains_key(&samples) {
            let pipelines = self.build_pipelines(samples);
            self.pipelines.insert(samples, pipelines);
            self.pipelines_created += PIPELINES_PER_SET;
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
                        blend: Option<wgpu::BlendState>,
                        depth: wgpu::DepthStencilState| {
            self.device
                .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some(vs),
                    layout: Some(&self.layout),
                    vertex: wgpu::VertexState {
                        module: &self.shader,
                        entry_point: Some(vs),
                        compilation_options: Default::default(),
                        // A stride of 0: no vertex buffer (the picture quad).
                        buffers: &[(stride > 0).then_some(wgpu::VertexBufferLayout {
                            array_stride: stride,
                            step_mode: wgpu::VertexStepMode::Vertex,
                            attributes: attrs,
                        })][..usize::from(stride > 0)],
                    },
                    // PMX front faces are clockwise.
                    primitive: wgpu::PrimitiveState {
                        front_face: wgpu::FrontFace::Cw,
                        cull_mode: cull,
                        ..Default::default()
                    },
                    depth_stencil: Some(depth),
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
        let opaque = || depth_state(true, Default::default());
        // A ground shadow pixel is blended once however many triangles cover it: the first
        // marks the stencil and the rest fail the test. The shadow writes depth, so the bottom of
        // a model behind its plane is hidden (golden2 `groundshadow-*.png`: the models' last two
        // rows show the shadow over white).
        let once = wgpu::StencilFaceState {
            compare: wgpu::CompareFunction::Equal,
            fail_op: wgpu::StencilOperation::Keep,
            depth_fail_op: wgpu::StencilOperation::Keep,
            pass_op: wgpu::StencilOperation::IncrementClamp,
        };
        let shadow_stencil = wgpu::StencilState {
            front: once,
            back: once,
            read_mask: 0xff,
            write_mask: 0xff,
        };
        let shadow = self
            .device
            .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("vs_shadow"),
                layout: Some(&self.light_layout),
                vertex: wgpu::VertexState {
                    module: &self.shader,
                    entry_point: Some("vs_shadow"),
                    compilation_options: Default::default(),
                    buffers: &[Some(wgpu::VertexBufferLayout {
                        array_stride: BODY_STRIDE,
                        step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: &body_attrs,
                    })],
                },
                primitive: Default::default(),
                depth_stencil: Some(wgpu::DepthStencilState {
                    format: SHADOW_FORMAT,
                    depth_write_enabled: Some(true),
                    depth_compare: Some(wgpu::CompareFunction::LessEqual),
                    stencil: Default::default(),
                    bias: Default::default(),
                }),
                multisample: Default::default(),
                fragment: None,
                multiview_mask: None,
                cache: None,
            });
        Pipelines {
            shadow,
            body: pipeline(
                "vs_main",
                "fs_main",
                body_layout,
                Some(wgpu::Face::Back),
                alpha,
                opaque(),
            ),
            body_two_sided: pipeline("vs_main", "fs_main", body_layout, None, alpha, opaque()),
            edge: pipeline(
                "vs_edge",
                "fs_edge",
                (EDGE_STRIDE, &edge_attrs[..]),
                Some(wgpu::Face::Front),
                alpha,
                opaque(),
            ),
            ground_shadow: pipeline(
                "vs_ground_shadow",
                "fs_ground_shadow",
                body_layout,
                None,
                alpha,
                depth_state(true, shadow_stencil),
            ),
            accessory: pipeline(
                "vs_main",
                "fs_accessory",
                body_layout,
                Some(wgpu::Face::Back),
                alpha,
                opaque(),
            ),
            picture: pipeline(
                "vs_picture",
                "fs_picture",
                (0, &[]),
                None,
                None,
                depth_state(false, Default::default()),
            ),
        }
    }

    /// Records one render of the (already uploaded) models into `target`, shifted by `shift`
    /// pixels, and returns the encoder.
    fn encode(
        &mut self,
        target: &wgpu::TextureView,
        frame: &Frame,
        stage: &Stage,
        shift: [f32; 2],
        samples: u32,
    ) -> wgpu::CommandEncoder {
        let (width, height) = (frame.width, frame.height);
        self.ensure((width, height), samples);
        self.queue
            .write_buffer(&self.scene_buf, 0, &scene_data(frame, stage, shift));
        let pipelines = &self.pipelines[&samples];
        let targets = self.targets.as_ref().expect("ensured above");
        let [r, g, b, a] = frame.background.map(|c| f64::from(c) / 255.0);
        let (view, resolve_target, store) = match &targets.color {
            Some(color) => (color, Some(target), wgpu::StoreOp::Discard),
            None => (target, None, wgpu::StoreOp::Store),
        };
        let mut encoder = self.device.create_command_encoder(&Default::default());
        if self_shadow_map(stage).is_some() {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("self-shadow map"),
                color_attachments: &[],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.shadow_map,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&pipelines.shadow);
            pass.set_bind_group(0, &self.light_group, &[]);
            // Only the models: an accessory in the map (golden2 `selfshadow-*.png`, the floor)
            // widens the models' shadows on it by about a texel each side.
            for (&(mesh, _), key) in frame.models.iter().zip(Self::keys(frame)) {
                let res = &self.models[&key];
                pass.set_index_buffer(res.indices.slice(..), wgpu::IndexFormat::Uint32);
                pass.set_vertex_buffer(0, res.vertices.slice(..));
                for (m, &alpha) in mesh.materials.iter().zip(&res.alpha) {
                    if m.count > 0 && alpha > 0.0 && m.flags & FLAG_SHADOW_CAST != 0 {
                        pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                    }
                }
            }
        }
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
                    stencil_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(0),
                        store: wgpu::StoreOp::Discard,
                    }),
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_bind_group(0, &self.scene_group, &[]);
            if let (Some(_), Some((_, _, group))) = (&stage.picture, &self.picture) {
                pass.set_pipeline(&pipelines.picture);
                pass.set_bind_group(1, group, &[]);
                pass.draw(0..6, 0..1);
            }
            // The ground shadow first: the models then cover it where they stand in front of it.
            if stage.ground_shadow.is_some() && casts_ground_shadow(frame) {
                pass.set_pipeline(&pipelines.ground_shadow);
                pass.set_stencil_reference(0);
                for (&(mesh, _), key) in frame.models.iter().zip(Self::keys(frame)) {
                    let res = &self.models[&key];
                    pass.set_index_buffer(res.indices.slice(..), wgpu::IndexFormat::Uint32);
                    pass.set_vertex_buffer(0, res.vertices.slice(..));
                    for ((m, (_, group)), &alpha) in
                        mesh.materials.iter().zip(&res.materials).zip(&res.alpha)
                    {
                        if m.count > 0 && alpha > 0.0 && m.flags & FLAG_GROUND_SHADOW != 0 {
                            pass.set_bind_group(1, group, &[]);
                            pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                        }
                    }
                }
            }
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
            pass.set_pipeline(&pipelines.accessory);
            for (a, key) in stage.accessories.iter().zip(Self::accessory_keys(stage)) {
                if !a.state.visible {
                    continue;
                }
                let res = &self.models[&key];
                pass.set_index_buffer(res.indices.slice(..), wgpu::IndexFormat::Uint32);
                pass.set_vertex_buffer(0, res.vertices.slice(..));
                for ((&(start, count), (_, group)), &alpha) in
                    res.ranges.iter().zip(&res.materials).zip(&res.alpha)
                {
                    if count > 0 && alpha > 0.0 {
                        pass.set_bind_group(1, group, &[]);
                        pass.draw_indexed(start..start + count, 0, 0..1);
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

/// Bytes of the scene uniform: three matrices and nine vectors.
const SCENE_BYTES: u64 = 3 * 64 + 9 * 16;

/// The self-shadow that draws a map: mode 1 or 2 with the shading on and a distance above 0
/// ([`Stage::legacy`] has distance 0 and draws none).
fn self_shadow_map(stage: &Stage) -> Option<crate::SelfShadow> {
    stage.self_shadow.filter(|s| s.shades() && s.distance > 0.0)
}

/// The depth difference factor of the self-shadow comparison (`SKII1` and `SKII2` of the golden2
/// README) and whether mode 2 scales it by the map's v (`parthf`).
fn shadow_factor(mode: u8) -> (f32, bool) {
    if mode == 2 {
        (8000.0, true)
    } else {
        (1500.0, false)
    }
}

/// The ground shadow projects along the light onto y = 0, so a light that does not go down casts
/// none.
fn casts_ground_shadow(frame: &Frame) -> bool {
    view::normalize(frame.light.direction)[1] < -1e-6
}

/// The ground shadow, from the `ground` lines of golden2 `groundshadow.edge.txt`: the plane matrix
/// flattens a point along the light onto y = 0 and lifts it to [`GROUND_SHADOW_HEIGHT`], and the
/// material is ambient = the shadow ambient with diffuse alpha [`SHADOW_ALPHA`] (both 0.5 there,
/// translucent). The color is `ambient * SHADOW_LIGHT`, the light fitted to that scene's 141 over
/// white; another ambient, or an opaque shadow (taken as alpha 1), is extrapolated.
const SHADOW_LIGHT: f32 = 0.2118;
const GROUND_SHADOW_HEIGHT: f32 = 0.1;
const SHADOW_ALPHA: f32 = 0.5;

fn scene_data(frame: &Frame, stage: &Stage, shift: [f32; 2]) -> Vec<u8> {
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
        match (frame.toon, stage.self_shadow.map(|s| s.shades())) {
            (true, None) => 1.0,
            (true, Some(true)) => 2.0,
            // Self-shadow on with a shadow range of zero or less draws no toon at all.
            (false, _) | (true, Some(false)) => 0.0,
        },
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
    let shadow = stage.ground_shadow.map_or([0.0; 4], |g| {
        let c = g.ambient * SHADOW_LIGHT;
        [c, c, c, if g.translucent { SHADOW_ALPHA } else { 1.0 }]
    });
    scene.extend(shadow);
    // The sample this render stands for, in pixels from the pixel center (y down).
    let sample = [
        frame.pixel_offset[0] - shift[0],
        frame.pixel_offset[1] - shift[1],
    ];
    scene.extend([GROUND_SHADOW_HEIGHT, sample[0], sample[1], 0.0]);
    match self_shadow_map(stage) {
        Some(s) => {
            let m = view.self_shadow_view_proj(&frame.light, s.mode, s.distance);
            scene.extend(m.iter().flatten());
            let (k, by_v) = shadow_factor(s.mode);
            scene.extend([1.0, k, f32::from(u8::from(by_v)), SHADOW_MAP_SIZE as f32]);
        }
        None => {
            scene.extend(view::IDENTITY.iter().flatten());
            scene.extend([0.0, 0.0, 0.0, SHADOW_MAP_SIZE as f32]);
        }
    }
    bytes(&scene)
}

fn bytes(f: &[f32]) -> Vec<u8> {
    f.iter().flat_map(|x| x.to_ne_bytes()).collect()
}

/// A texture of `levels`: the picture, then its mip levels, each half the size of the last.
fn texture(device: &wgpu::Device, queue: &wgpu::Queue, levels: &[Image]) -> wgpu::TextureView {
    let size = |l: &Image| wgpu::Extent3d {
        width: l.width,
        height: l.height,
        depth_or_array_layers: 1,
    };
    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("texture"),
        size: size(&levels[0]),
        mip_level_count: levels.len() as u32,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: COLOR_FORMAT,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    for (k, l) in levels.iter().enumerate() {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                mip_level: k as u32,
                ..tex.as_image_copy()
            },
            &l.rgba,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(l.width * 4),
                rows_per_image: Some(l.height),
            },
            size(l),
        );
    }
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

/// The built-in toon texture, lit end first (v = 0.5 - 0.5 * N.L), 32 texels: full light for texels 0
/// to 15 and 0.8 (204) from texel 16 on, so the step falls where N.L crosses 0. Fitted to the
/// curled model of golden2 `groundshadow-0.png` (self-shadow off); its bottom texel is the shadow
/// color of the self-shadow blend.
fn toon_ramp() -> Vec<u8> {
    (0..32)
        .flat_map(|y| {
            let b = if y < 16 { 255 } else { 204 };
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
