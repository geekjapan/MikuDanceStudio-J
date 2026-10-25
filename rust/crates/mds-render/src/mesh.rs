//! Model geometry for drawing: vertices with skin weights, vertex morph offsets and materials,
//! from a PMX or a PMD, and the CPU skinning that turns a pose into a vertex buffer.

use mds_formats::{pmd::Pmd, pmx::Offsets, pmx::Pmx};

pub(crate) const FLAG_DOUBLE_SIDED: u8 = 0x01;
pub(crate) const FLAG_EDGE: u8 = 0x10;

struct Vertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
    edge_scale: f32,
    /// Up to four `(bone, weight)` influences; the weights add up to 1, or the list is empty.
    skin: [(usize, f32); 4],
    skin_len: usize,
}

pub(crate) struct Material {
    pub diffuse: [f32; 4],
    pub ambient: [f32; 3],
    pub specular: [f32; 3],
    pub specular_power: f32,
    pub edge_color: [f32; 4],
    pub edge_size: f32,
    pub flags: u8,
    /// First index and index count of the material's faces.
    pub start: u32,
    pub count: u32,
}

/// One vertex morph: the vertices it moves and by how much at weight 1.
struct VertexMorph {
    offsets: Vec<(usize, [f32; 3])>,
}

/// What a pose changes: the skin matrix of every bone (row-major, row-vector convention, as the
/// D3DX matrices of `mds-pose`) and the morph values (indexed like the model's morph list).
#[derive(Clone, Debug, Default)]
pub struct Pose {
    pub skin: Vec<[f32; 16]>,
    pub morphs: Vec<f32>,
}

pub struct Mesh {
    vertices: Vec<Vertex>,
    pub(crate) indices: Vec<u32>,
    pub(crate) materials: Vec<Material>,
    /// By morph index; a morph that is not a vertex morph has no offsets.
    morphs: Vec<VertexMorph>,
    /// Group morphs: `(member morph, weight)` by morph index.
    groups: Vec<Vec<(usize, f32)>>,
}

fn finish(
    vertices: Vec<Vertex>,
    indices: Vec<u32>,
    materials: Vec<Material>,
    morphs: Vec<VertexMorph>,
    groups: Vec<Vec<(usize, f32)>>,
) -> Result<Mesh, String> {
    if vertices.is_empty() {
        return Err("model has no vertices".into());
    }
    if indices.iter().any(|&i| i as usize >= vertices.len()) {
        return Err("an index is outside the vertex list".into());
    }
    if materials
        .iter()
        .any(|m| (m.start + m.count) as usize > indices.len())
    {
        return Err("a material reaches past the index list".into());
    }
    Ok(Mesh {
        vertices,
        indices,
        materials,
        morphs,
        groups,
    })
}

fn skin_of(influences: &[(i64, f32)]) -> ([(usize, f32); 4], usize) {
    let mut skin = [(0, 0.0); 4];
    let mut n = 0;
    for &(bone, w) in influences {
        if let Ok(bone) = usize::try_from(bone) {
            if w > 0.0 {
                skin[n] = (bone, w);
                n += 1;
            }
        }
    }
    (skin, n)
}

impl Mesh {
    /// A PMX model. SDEF vertices blend like BDEF2 and QDEF like BDEF4 (the linear blend; the
    /// golden models have no SDEF vertex that differs).
    pub fn from_pmx(pmx: &Pmx) -> Result<Mesh, String> {
        let vertices = pmx
            .vertices
            .iter()
            .map(|v| {
                let b = |i: usize| i64::from(v.bones[i]);
                let infl: Vec<(i64, f32)> = match v.weight_kind {
                    0 => vec![(b(0), 1.0)],
                    1 | 3 => vec![(b(0), v.weights[0]), (b(1), 1.0 - v.weights[0])],
                    _ => (0..4).map(|i| (b(i), v.weights[i])).collect(),
                };
                let (skin, skin_len) = skin_of(&infl);
                Vertex {
                    position: v.position,
                    normal: v.normal,
                    uv: v.uv,
                    edge_scale: v.edge_scale,
                    skin,
                    skin_len,
                }
            })
            .collect();
        let indices = pmx
            .indices
            .iter()
            .map(|&i| u32::try_from(i).map_err(|_| "negative index".to_string()))
            .collect::<Result<Vec<u32>, String>>()?;
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmx.materials {
            let count = u32::try_from(m.face_vertex_count).map_err(|_| "negative face count")?;
            materials.push(Material {
                diffuse: m.diffuse,
                ambient: m.ambient,
                specular: m.specular,
                specular_power: m.specular_power,
                edge_color: m.edge_color,
                edge_size: m.edge_size,
                flags: m.flags,
                start,
                count,
            });
            start = start.checked_add(count).ok_or("face count overflows")?;
        }
        let mut morphs = Vec::new();
        let mut groups = Vec::new();
        for m in &pmx.morphs {
            let mut offsets = Vec::new();
            let mut group = Vec::new();
            match &m.offsets {
                Offsets::Vertex(list) if m.kind == 1 => {
                    for &(v, d) in list {
                        offsets.push((usize::try_from(v).map_err(|_| "negative morph vertex")?, d));
                    }
                }
                Offsets::Group(list) if m.kind == 0 => {
                    for &(i, w) in list {
                        group.push((usize::try_from(i).map_err(|_| "negative group member")?, w));
                    }
                }
                _ => {}
            }
            morphs.push(VertexMorph { offsets });
            groups.push(group);
        }
        let n = pmx.vertices.len();
        if morphs
            .iter()
            .any(|m| m.offsets.iter().any(|&(v, _)| v >= n))
        {
            return Err("a morph moves a vertex outside the vertex list".into());
        }
        if groups.iter().flatten().any(|&(i, _)| i >= morphs.len()) {
            return Err("a group morph names a morph outside the list".into());
        }
        finish(vertices, indices, materials, morphs, groups)
    }

    /// A PMD model. Materials with an alpha below 1 are drawn double sided; vertex morphs are not
    /// read (the face morph list of a PMD is relative to a base morph).
    pub fn from_pmd(pmd: &Pmd) -> Result<Mesh, String> {
        let vertices = pmd
            .vertices
            .iter()
            .map(|v| {
                let w = f32::from(v.weight.min(100)) / 100.0;
                let (skin, skin_len) =
                    skin_of(&[(i64::from(v.bones[0]), w), (i64::from(v.bones[1]), 1.0 - w)]);
                Vertex {
                    position: v.position,
                    normal: v.normal,
                    uv: v.uv,
                    edge_scale: if v.edge_disabled == 0 { 1.0 } else { 0.0 },
                    skin,
                    skin_len,
                }
            })
            .collect();
        let indices = pmd.indices.iter().map(|&i| u32::from(i)).collect();
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmd.materials {
            materials.push(Material {
                diffuse: m.diffuse,
                ambient: m.ambient,
                specular: m.specular,
                specular_power: m.specular_power,
                edge_color: [0.0, 0.0, 0.0, 1.0],
                edge_size: 1.0,
                flags: (if m.diffuse[3] < 1.0 {
                    FLAG_DOUBLE_SIDED
                } else {
                    0
                }) | if m.edge != 0 { FLAG_EDGE } else { 0 },
                start,
                count: m.face_vertex_count,
            });
            start = start
                .checked_add(m.face_vertex_count)
                .ok_or("face count overflows")?;
        }
        finish(vertices, indices, materials, Vec::new(), Vec::new())
    }

    /// Bounding box of the bind pose.
    pub(crate) fn bounds(&self) -> ([f32; 3], [f32; 3]) {
        let (mut min, mut max) = ([f32::MAX; 3], [f32::MIN; 3]);
        for v in &self.vertices {
            for i in 0..3 {
                min[i] = min[i].min(v.position[i]);
                max[i] = max[i].max(v.position[i]);
            }
        }
        (min, max)
    }

    /// Side of the Z axis the mean vertex normal points to: +1 or -1.
    pub(crate) fn front(&self) -> f32 {
        let z: f32 = self.vertices.iter().map(|v| v.normal[2]).sum();
        if z > 0.0 {
            1.0
        } else {
            -1.0
        }
    }

    /// The effective weight of every vertex morph: its own value plus the group morphs that name it.
    fn morph_weights(&self, values: &[f32]) -> Vec<f32> {
        let mut w: Vec<f32> = (0..self.morphs.len())
            .map(|i| values.get(i).copied().unwrap_or(0.0))
            .collect();
        for (g, members) in self.groups.iter().enumerate() {
            let value = values.get(g).copied().unwrap_or(0.0);
            for &(m, ratio) in members {
                w[m] += value * ratio;
            }
        }
        w
    }

    /// The vertex buffer: per vertex position 3, normal 3, uv 2, edge scale 1. With a pose the
    /// positions get the vertex morphs and the linear blend skin; normals get the blended
    /// rotation. The bind pose (`None`) is the file's positions.
    pub(crate) fn vertex_data(&self, pose: Option<&Pose>) -> Vec<f32> {
        let mut positions: Vec<[f32; 3]> = self.vertices.iter().map(|v| v.position).collect();
        if let Some(pose) = pose {
            for (m, w) in self.morph_weights(&pose.morphs).into_iter().enumerate() {
                if w != 0.0 {
                    for &(v, d) in &self.morphs[m].offsets {
                        for k in 0..3 {
                            positions[v][k] += d[k] * w;
                        }
                    }
                }
            }
        }
        let mut out = Vec::with_capacity(self.vertices.len() * 9);
        for (v, p) in self.vertices.iter().zip(&positions) {
            let (mut pos, mut normal) = (*p, v.normal);
            if let Some(pose) = pose {
                if v.skin_len > 0 {
                    (pos, normal) = ([0.0; 3], [0.0; 3]);
                    for &(bone, w) in &v.skin[..v.skin_len] {
                        let m = pose.skin.get(bone).copied().unwrap_or(IDENTITY);
                        for k in 0..3 {
                            pos[k] +=
                                w * (p[0] * m[k] + p[1] * m[4 + k] + p[2] * m[8 + k] + m[12 + k]);
                            normal[k] += w
                                * (v.normal[0] * m[k]
                                    + v.normal[1] * m[4 + k]
                                    + v.normal[2] * m[8 + k]);
                        }
                    }
                }
            }
            out.extend(pos);
            out.extend(normal);
            out.extend(v.uv);
            out.push(v.edge_scale);
        }
        out
    }
}

const IDENTITY: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linear_blend_moves_a_vertex_by_the_weighted_matrices() {
        let (skin, skin_len) = skin_of(&[(0, 0.25), (1, 0.75)]);
        let mesh = Mesh {
            vertices: vec![Vertex {
                position: [1.0, 2.0, 3.0],
                normal: [0.0, 0.0, 1.0],
                uv: [0.0; 2],
                edge_scale: 1.0,
                skin,
                skin_len,
            }],
            indices: vec![],
            materials: vec![],
            morphs: vec![VertexMorph {
                offsets: vec![(0, [0.0, 1.0, 0.0])],
            }],
            groups: vec![vec![]],
        };
        let mut translate_x = IDENTITY;
        translate_x[12] = 4.0;
        let pose = Pose {
            skin: vec![IDENTITY, translate_x],
            morphs: vec![0.5],
        };
        // The morph moves the vertex to y = 2.5 first; 0.75 of the x offset 4 is 3.
        assert_eq!(&mesh.vertex_data(Some(&pose))[..3], &[4.0, 2.5, 3.0]);
        assert_eq!(&mesh.vertex_data(None)[..3], &[1.0, 2.0, 3.0]);
    }
}
