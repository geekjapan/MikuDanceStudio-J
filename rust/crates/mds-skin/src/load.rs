//! What `LoadPMX` (`src/model/pmx_load.cpp`) and `ModelLoadPMD`
//! (`src/model/pmd_load.cpp`) leave for the skinning and the morphs: the
//! working vertices, the morph and restore tables, the materials, the
//! material morph base pool and the initial vertex buffers.
//!
//! Indices the C++ would follow out of bounds are errors here.

use crate::{
    Channels, EdgeVertex, Material, MaterialOffset, Morph, PmdVertex, PmxVertex, Skin, Vertices,
};
use mds_formats::pmd::Pmd;
use mds_formats::pmx::{Offsets, Pmx};

fn vertex_index(i: i32, count: usize) -> Result<usize, String> {
    usize::try_from(i)
        .ok()
        .filter(|&i| i < count)
        .ok_or_else(|| format!("vertex index {i} out of range"))
}

/// `InitializePmxEdgeVertices` and the PMD edge fill: the position and an
/// opaque black.
fn initial_edge(position: [f32; 3]) -> EdgeVertex {
    EdgeVertex {
        position,
        diffuse: 0xFF00_0000,
    }
}

/// The 28 floats of a PMX material morph entry, in file order.
fn channels(v: &[f32; 28]) -> Channels {
    let four = |i: usize| [v[i], v[i + 1], v[i + 2], v[i + 3]];
    Channels {
        diffuse: four(0),
        specular: [v[4], v[5], v[6]],
        specular_power: v[7],
        ambient: [v[8], v[9], v[10]],
        edge_color: four(11),
        edge_size: v[15],
        texture_tint: four(16),
        sphere_tint: four(20),
        toon_tint: four(24),
    }
}

/// The material morph base pool: the material values, tints 1.
fn base_channels(m: &Material) -> Channels {
    let [r, g, b, _] = m.diffuse_mirror;
    Channels {
        diffuse: [r, g, b, m.diffuse[3]],
        specular: m.specular,
        specular_power: m.specular_power,
        ambient: m.ambient,
        edge_color: m.edge_color,
        edge_size: m.edge_size,
        texture_tint: [1.0; 4],
        sphere_tint: [1.0; 4],
        toon_tint: [1.0; 4],
    }
}

impl Skin {
    /// `LoadPMX`. A QDEF vertex (PMX 2.1) is read like the others but not
    /// skinned.
    pub fn from_pmx(pmx: &Pmx) -> Result<Skin, String> {
        let additional_uvs = usize::from(pmx.globals[1]);
        if additional_uvs > 4 {
            return Err(format!("{additional_uvs} additional UVs"));
        }
        let mut vertices: Vec<PmxVertex> = pmx
            .vertices
            .iter()
            .map(|v| {
                let mut additional_uv = [[0.0; 4]; 4];
                for (o, uv) in additional_uv.iter_mut().zip(&v.extra_uv) {
                    *o = *uv;
                }
                let mut sdef = v.sdef;
                if v.weight_kind == 3 {
                    // R0 and R1 relative to the pivot of the weighted midpoint.
                    let w = v.weights[0];
                    let mid: [f32; 3] =
                        std::array::from_fn(|c| w * sdef[1][c] + (1.0 - w) * sdef[2][c]);
                    for c in 0..3 {
                        sdef[1][c] -= mid[c];
                        sdef[2][c] -= mid[c];
                    }
                }
                PmxVertex {
                    position: v.position,
                    normal: v.normal,
                    uv: v.uv,
                    additional_uv,
                    kind: v.weight_kind,
                    bones: v.bones,
                    weights: v.weights,
                    sdef,
                    edge_scale: v.edge_scale,
                    material: 0,
                }
            })
            .collect();
        let count = vertices.len();

        let materials: Vec<Material> = pmx
            .materials
            .iter()
            .map(|m| Material {
                diffuse: m.diffuse,
                diffuse_mirror: m.diffuse,
                specular: m.specular,
                ambient: m.ambient,
                specular_power: m.specular_power,
                edge_color: m.edge_color,
                edge_size: m.edge_size,
            })
            .collect();
        // Each vertex takes the first material with the smallest edge size
        // among those whose faces use it.
        // 999.79999f in the C++.
        let mut edge_key = vec![999.8_f32; count];
        let mut faces = pmx.indices.iter();
        for (mi, (m, file)) in materials.iter().zip(&pmx.materials).enumerate() {
            for _ in 0..file.face_vertex_count.max(0) {
                let index = faces.next().ok_or("material faces exceed the indices")?;
                let vi = vertex_index(*index, count)?;
                if m.edge_size < edge_key[vi] {
                    edge_key[vi] = m.edge_size;
                    vertices[vi].material = mi;
                }
            }
        }

        let mut morphs = Vec::with_capacity(pmx.morphs.len());
        let mut morphed = vec![false; count];
        for m in &pmx.morphs {
            let mut morph = Morph {
                kind: m.kind,
                ..Morph::default()
            };
            match (&m.offsets, m.kind) {
                (Offsets::Group(entries), 0) => {
                    for &(target, weight) in entries {
                        let target = usize::try_from(target).unwrap_or(0);
                        if target >= pmx.morphs.len() {
                            return Err(format!("group morph index {target} out of range"));
                        }
                        morph.group.push((target, weight));
                    }
                }
                (Offsets::Vertex(entries), _) => {
                    for &(v, offset) in entries {
                        let v = vertex_index(v, count)?;
                        morphed[v] = true;
                        morph.vertex.push((v, offset));
                    }
                }
                (Offsets::Uv(entries), _) => {
                    for &(v, offset) in entries {
                        morph.uv.push((vertex_index(v, count)?, offset));
                    }
                }
                (Offsets::Material(entries), _) => {
                    for e in entries {
                        let material = match e.material {
                            -1 => None,
                            i => Some(
                                usize::try_from(i)
                                    .ok()
                                    .filter(|&i| i < materials.len())
                                    .ok_or_else(|| format!("material index {i} out of range"))?,
                            ),
                        };
                        morph.material.push(MaterialOffset {
                            material,
                            additive: e.operation != 0,
                            channels: channels(&e.values),
                        });
                    }
                }
                // Bone morphs move bones (mds-pose); kinds 9 and 10 are not read.
                _ => {}
            }
            morphs.push(morph);
        }
        let base = (0..count)
            .filter(|&v| morphed[v])
            .map(|v| (v, vertices[v].position))
            .collect();
        let uv_base = std::array::from_fn(|family| {
            morphs
                .iter()
                .filter(|m| usize::from(m.kind) == family + 3)
                .flat_map(|m| &m.uv)
                .map(|&(v, _)| {
                    let x = &vertices[v];
                    let value = match family {
                        0 => [x.uv[0], x.uv[1], 0.0, 0.0],
                        f => x.additional_uv[f - 1],
                    };
                    (v, value)
                })
                .collect()
        });

        let stride = 8 + 4 * additional_uvs;
        let mut main = Vec::with_capacity(stride * count);
        for v in &vertices {
            main.extend(v.position);
            main.extend(v.normal);
            main.extend(v.uv);
            for uv in &v.additional_uv[..additional_uvs] {
                main.extend(uv);
            }
        }
        let edge = vertices.iter().map(|v| initial_edge(v.position)).collect();
        let material_base: Vec<Channels> = materials.iter().map(base_channels).collect();
        Ok(Skin {
            vertices: Vertices::Pmx(vertices),
            additional_uvs,
            bone_positions: pmx.bones.iter().map(|b| b.position).collect(),
            morphs,
            base,
            uv_base,
            material_add: vec![Channels::default(); materials.len()],
            material_mul: vec![Channels::default(); materials.len()],
            materials,
            material_base,
            main,
            edge,
        })
    }

    /// `ModelLoadPMD`. Morph 0 is the base table of the vertex morphs; the
    /// other morphs index it.
    pub fn from_pmd(pmd: &Pmd) -> Result<Skin, String> {
        let vertices: Vec<PmdVertex> = pmd
            .vertices
            .iter()
            .map(|v| PmdVertex {
                position: v.position,
                normal: v.normal,
                uv: v.uv,
                bones: v.bones.map(|b| b as i16),
                weight: v.weight as i8,
                edge_disabled: v.edge_disabled,
            })
            .collect();
        let count = vertices.len();
        let mut base = Vec::new();
        let mut morphs = Vec::with_capacity(pmd.morphs.len());
        if let Some(first) = pmd.morphs.first() {
            for &(v, offset) in &first.offsets {
                base.push((vertex_index(v as i32, count)?, offset));
            }
            for (k, m) in pmd.morphs.iter().enumerate() {
                let mut vertex = Vec::new();
                // The base morph is never applied, only restored.
                if k > 0 {
                    for &(i, offset) in &m.offsets {
                        let &(v, _) = base
                            .get(i as usize)
                            .ok_or_else(|| format!("base morph index {i} out of range"))?;
                        vertex.push((v, offset));
                    }
                }
                morphs.push(Morph {
                    kind: 1,
                    vertex,
                    ..Morph::default()
                });
            }
        }
        let materials: Vec<Material> = pmd
            .materials
            .iter()
            .map(|m| Material {
                diffuse: m.diffuse,
                diffuse_mirror: m.diffuse,
                specular: m.specular,
                ambient: m.ambient,
                specular_power: m.specular_power,
                ..Material::default()
            })
            .collect();
        let mut main = Vec::with_capacity(8 * count);
        for v in &vertices {
            main.extend(v.position);
            main.extend(v.normal);
            main.extend(v.uv);
        }
        let edge = vertices.iter().map(|v| initial_edge(v.position)).collect();
        Ok(Skin {
            vertices: Vertices::Pmd(vertices),
            additional_uvs: 0,
            bone_positions: pmd.bones.iter().map(|b| b.position).collect(),
            morphs,
            base,
            uv_base: Default::default(),
            material_base: materials.iter().map(base_channels).collect(),
            material_add: vec![Channels::default(); materials.len()],
            material_mul: vec![Channels::default(); materials.len()],
            materials,
            main,
            edge,
        })
    }
}
