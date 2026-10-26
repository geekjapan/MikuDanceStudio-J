//! Geometry an MME pass draws: a model's or an accessory's vertex and index buffers with its
//! material subsets, and the `Draw=Buffer` quad of `SasDefaultDrawBufferPass` (`pass_planner.cpp`).
//! [`Model::update`] writes a pose: the vertices and materials `mds-skin` computed.
//!
//! The vertex layout is the model FVF of `ModelVertexFormat` (`src/render/model_renderers.cpp`):
//! `XYZ | NORMAL | TEX1` plus up to four float4 additional UVs as `TEXCOORD1..4`. Every buffer
//! here holds all four (zero when the model has fewer), so one layout serves every shader.

use mds_accessory::accessory::TextureSlot;
use mds_accessory::{Accessory, TextureKind};
use mds_formats::pmd::Pmd;
use mds_formats::pmx::Pmx;
use mds_skin::Skin;
use wgpu::util::DeviceExt;

/// Floats per vertex: position 3, normal 3, uv 2, four additional uv4.
pub const VERTEX_FLOATS: usize = 3 + 3 + 2 + 16;
pub const STRIDE: u64 = (VERTEX_FLOATS * 4) as u64;

/// The byte offset and format a vertex-shader input of this D3D usage and index reads, or
/// `None` when the stream has no such element.
pub fn element(usage: &str, index: u32) -> Option<(u64, wgpu::VertexFormat)> {
    use wgpu::VertexFormat as F;
    match (usage, index) {
        ("position", 0) => Some((0, F::Float32x3)),
        ("normal", 0) => Some((12, F::Float32x3)),
        ("texcoord", 0) => Some((24, F::Float32x2)),
        ("texcoord", 1..=4) => Some((32 + 16 * u64::from(index - 1), F::Float32x4)),
        _ => None,
    }
}

/// One material subset: what the parameter binder reads and the index range it draws.
#[derive(Clone, Debug)]
pub struct Material {
    pub diffuse: [f32; 4],
    /// The record's mirror of the diffuse, its `D3DMATERIAL9` ambient (`mds_skin::Material`).
    pub mirror: [f32; 4],
    pub ambient: [f32; 3],
    pub specular: [f32; 3],
    pub power: f32,
    pub edge_color: [f32; 4],
    pub has_texture: bool,
    /// PMX sphere mode: 0 off, 1 multiply, 2 add, 3 sub-texture.
    pub sphere_mode: u8,
    pub toon: bool,
    /// The material draws its edge (the PMX flag 0x10, the PMD edge byte).
    pub edge: bool,
    /// An accessory's `D3DMATERIAL9` (diffuse, ambient, specular, emissive), which
    /// `ExpGetAcsMaterial` returns in place of the fields above.
    pub accessory: Option<[[f32; 4]; 4]>,
    pub start: u32,
    pub count: u32,
}

pub struct Model {
    pub vertices: wgpu::Buffer,
    pub indices: wgpu::Buffer,
    pub materials: Vec<Material>,
}

fn floats(f: &[f32]) -> Vec<u8> {
    f.iter().flat_map(|x| x.to_le_bytes()).collect()
}

impl Model {
    /// A PMX model in its bind pose.
    pub fn from_pmx(device: &wgpu::Device, pmx: &Pmx) -> Result<Model, String> {
        let mut data = Vec::with_capacity(pmx.vertices.len() * VERTEX_FLOATS);
        for v in &pmx.vertices {
            data.extend(v.position);
            data.extend(v.normal);
            data.extend(v.uv);
            for k in 0..4 {
                data.extend(v.extra_uv.get(k).copied().unwrap_or([0.0; 4]));
            }
        }
        let n = pmx.vertices.len();
        let mut indices = Vec::with_capacity(pmx.indices.len());
        for &i in &pmx.indices {
            match usize::try_from(i) {
                Ok(i) if i < n => indices.push(i as u32),
                _ => return Err(format!("index {i} is outside the {n} vertices")),
            }
        }
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmx.materials {
            let count = u32::try_from(m.face_vertex_count).map_err(|_| "negative face count")?;
            if (start + count) as usize > indices.len() {
                return Err("a material reaches past the index list".into());
            }
            materials.push(Material {
                diffuse: m.diffuse,
                mirror: m.diffuse,
                ambient: m.ambient,
                specular: m.specular,
                power: m.specular_power,
                edge_color: m.edge_color,
                has_texture: m.texture >= 0,
                sphere_mode: if m.sphere >= 0 { m.sphere_mode } else { 0 },
                toon: m.shared_toon != 0 || m.toon >= 0,
                edge: m.flags & 0x10 != 0,
                accessory: None,
                start,
                count,
            });
            start += count;
        }
        Ok(Model::new(device, &data, &indices, materials))
    }

    /// A PMD model in its bind pose. Its texture name splits as an accessory's does
    /// (`name*map.sph`); every PMD material draws with a toon (the file has no switch).
    pub fn from_pmd(device: &wgpu::Device, pmd: &Pmd) -> Result<Model, String> {
        let mut data = Vec::with_capacity(pmd.vertices.len() * VERTEX_FLOATS);
        for v in &pmd.vertices {
            data.extend(v.position);
            data.extend(v.normal);
            data.extend(v.uv);
            data.extend([0.0; 16]);
        }
        let n = pmd.vertices.len();
        let indices: Vec<u32> = pmd.indices.iter().map(|&i| u32::from(i)).collect();
        if indices.iter().any(|&i| i as usize >= n) {
            return Err(format!("an index is outside the {n} vertices"));
        }
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmd.materials {
            let count = m.face_vertex_count;
            if (start + count) as usize > indices.len() {
                return Err("a material reaches past the index list".into());
            }
            let name = &m.texture.raw;
            let name = &name[..name.iter().position(|&b| b == 0).unwrap_or(name.len())];
            let (has_texture, sphere_mode) = texture_use(&TextureSlot::parse(Some(name)));
            materials.push(Material {
                diffuse: m.diffuse,
                mirror: m.diffuse,
                ambient: m.ambient,
                specular: m.specular,
                power: m.specular_power,
                edge_color: [0.0, 0.0, 0.0, 1.0],
                has_texture,
                sphere_mode,
                toon: true,
                edge: m.edge != 0,
                accessory: None,
                start,
                count,
            });
            start += count;
        }
        Ok(Model::new(device, &data, &indices, materials))
    }

    /// An accessory: one subset per material, its faces in the order `DrawSubset` draws them.
    pub fn from_accessory(device: &wgpu::Device, acc: &Accessory) -> Result<Model, String> {
        let mut data = Vec::with_capacity(acc.vertices.len() * VERTEX_FLOATS);
        for v in &acc.vertices {
            data.extend(v.position);
            data.extend(v.normal);
            data.extend(v.texcoord);
            data.extend([0.0; 16]);
        }
        let n = acc.vertices.len() as u32;
        let mut indices = Vec::with_capacity(acc.indices.len());
        let mut materials = Vec::new();
        for (k, m) in acc.materials.iter().enumerate() {
            let start = indices.len() as u32;
            for f in acc.subset_faces(k) {
                let face = acc
                    .indices
                    .get(3 * f..3 * f + 3)
                    .ok_or("a face past the indices")?;
                if face.iter().any(|&i| i >= n) {
                    return Err(format!("an index is outside the {n} vertices"));
                }
                indices.extend(face);
            }
            let (has_texture, sphere_mode) = texture_use(&m.texture);
            materials.push(Material {
                diffuse: m.diffuse,
                mirror: m.ambient,
                ambient: [m.emissive[0], m.emissive[1], m.emissive[2]],
                specular: [m.specular[0], m.specular[1], m.specular[2]],
                power: m.power,
                edge_color: [0.0; 4],
                has_texture,
                sphere_mode,
                toon: false,
                edge: false,
                accessory: Some([m.diffuse, m.ambient, m.specular, m.emissive]),
                start,
                count: indices.len() as u32 - start,
            });
        }
        Ok(Model::new(device, &data, &indices, materials))
    }

    fn new(
        device: &wgpu::Device,
        data: &[f32],
        indices: &[u32],
        materials: Vec<Material>,
    ) -> Model {
        Model {
            vertices: buffer(device, wgpu::BufferUsages::VERTEX, &floats(data)),
            indices: buffer(
                device,
                wgpu::BufferUsages::INDEX,
                &indices
                    .iter()
                    .flat_map(|i| i.to_le_bytes())
                    .collect::<Vec<_>>(),
            ),
            materials,
        }
    }

    /// The pose `skin` holds after `Skin::apply_morphs` and `Skin::update`: its vertex buffer
    /// (position, normal, uv and the additional uvs, padded to four) and its material values.
    pub fn update(&mut self, queue: &wgpu::Queue, skin: &Skin) {
        let stride = skin.stride();
        let mut data = Vec::with_capacity(skin.vertex_count() * VERTEX_FLOATS);
        for v in skin.main.chunks_exact(stride) {
            data.extend(v);
            data.extend(std::iter::repeat_n(0.0, VERTEX_FLOATS - stride));
        }
        queue.write_buffer(&self.vertices, 0, &floats(&data));
        for (m, s) in self.materials.iter_mut().zip(&skin.materials) {
            m.diffuse = s.diffuse;
            m.mirror = s.diffuse_mirror;
            m.ambient = s.ambient;
            m.specular = s.specular;
            m.power = s.specular_power;
            m.edge_color = s.edge_color;
        }
    }
}

/// Whether a texture slot has a main texture, and its sphere mode as PMX numbers it.
fn texture_use(t: &TextureSlot) -> (bool, u8) {
    match t.kind {
        TextureKind::Plain => (!t.primary.raw.is_empty(), 0),
        TextureKind::SphereMultiply => (false, 1),
        TextureKind::SphereAdd => (false, 2),
        TextureKind::Screen => (true, 0),
        TextureKind::SubMultiply => (true, 1),
        TextureKind::SubAdd => (true, 2),
    }
}

pub fn buffer(device: &wgpu::Device, usage: wgpu::BufferUsages, data: &[u8]) -> wgpu::Buffer {
    let mut padded = data.to_vec();
    padded.resize(data.len().next_multiple_of(4).max(4), 0);
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: &padded,
        usage: usage | wgpu::BufferUsages::COPY_DST,
    })
}

/// The quad of `SasDefaultDrawBufferPass` for a `w` x `h` viewport, as a triangle list (the
/// original draws the same four vertices as a fan): one pixel of NDC expansion on the left and
/// top, one texel of under-scan on the matching u and v edges.
pub fn quad(w: u32, h: u32) -> Vec<u8> {
    let (w, h) = (w as f32, h as f32);
    let x_left = -1.0 - (1.0 / w) * 2.0;
    let y_top = (1.0 / h) * 2.0 + 1.0;
    let u_left = -(1.0 / w);
    let v_top = -(1.0 / h);
    let fan = [
        [1.0, -1.0, 1.0, 1.0],
        [x_left, -1.0, u_left, 1.0],
        [x_left, y_top, u_left, v_top],
        [1.0, y_top, 1.0, v_top],
    ];
    let mut out = Vec::new();
    for i in [0, 1, 2, 0, 2, 3] {
        let [x, y, u, v] = fan[i];
        let mut vtx = [0.0f32; VERTEX_FLOATS];
        vtx[0] = x;
        vtx[1] = y;
        vtx[6] = u;
        vtx[7] = v;
        out.extend(floats(&vtx));
    }
    out
}
