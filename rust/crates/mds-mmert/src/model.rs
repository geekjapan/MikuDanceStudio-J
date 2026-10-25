//! Geometry an MME pass draws: a model's vertex and index buffers with its material subsets,
//! and the `Draw=Buffer` quad of `SasDefaultDrawBufferPass` (`pass_planner.cpp`).
//!
//! The vertex layout is the model FVF of `ModelVertexFormat` (`src/render/model_renderers.cpp`):
//! `XYZ | NORMAL | TEX1` plus up to four float4 additional UVs as `TEXCOORD1..4`. Every buffer
//! here holds all four (zero when the model has fewer), so one layout serves every shader.

use mds_formats::pmx::Pmx;
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
    pub ambient: [f32; 3],
    pub specular: [f32; 3],
    pub power: f32,
    pub edge_color: [f32; 4],
    pub has_texture: bool,
    /// PMX sphere mode: 0 off, 1 multiply, 2 add, 3 sub-texture.
    pub sphere_mode: u8,
    pub toon: bool,
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
    // ponytail: no skinning or morphs; mds-render keeps its skinning crate-private (see the
    // crate doc), so posed models wait for that hook.
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
                ambient: m.ambient,
                specular: m.specular,
                power: m.specular_power,
                edge_color: m.edge_color,
                has_texture: m.texture >= 0,
                sphere_mode: if m.sphere >= 0 { m.sphere_mode } else { 0 },
                toon: m.shared_toon != 0 || m.toon >= 0,
                start,
                count,
            });
            start += count;
        }
        Ok(Model {
            vertices: buffer(device, wgpu::BufferUsages::VERTEX, &floats(&data)),
            indices: buffer(
                device,
                wgpu::BufferUsages::INDEX,
                &indices
                    .iter()
                    .flat_map(|i| i.to_le_bytes())
                    .collect::<Vec<_>>(),
            ),
            materials,
        })
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
