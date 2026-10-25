//! Model geometry for drawing: the index list and material ranges of a PMX or a PMD, and the
//! per-frame vertex buffers and material values that `mds-skin` computes for a pose.

use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_skin::{Mat4, Skin};
use std::sync::atomic::{AtomicU64, Ordering};

pub(crate) const FLAG_DOUBLE_SIDED: u8 = 0x01;
pub(crate) const FLAG_GROUND_SHADOW: u8 = 0x02;
pub(crate) const FLAG_EDGE: u8 = 0x10;

/// Where a material's faces sit in the index list, and how they are drawn. The colors come from
/// `Skin::materials` each frame, because material morphs change them.
pub(crate) struct Material {
    pub flags: u8,
    /// First index and index count of the material's faces.
    pub start: u32,
    pub count: u32,
}

/// What a pose changes: the skin matrix of every bone (row-major, row-vector convention, as the
/// D3DX matrices of `mds-pose`) and the morph values (indexed like the model's morph list).
#[derive(Clone, Debug, Default)]
pub struct Pose {
    pub skin: Vec<[f32; 16]>,
    pub morphs: Vec<f32>,
}

pub struct Mesh {
    /// Names the mesh to `Renderer`, which keeps the buffers of a model between frames.
    pub(crate) id: u64,
    /// Position and normal of every vertex in the file, for the bind-pose camera.
    bind: Vec<([f32; 3], [f32; 3])>,
    skin: Skin,
    pub(crate) indices: Vec<u32>,
    pub(crate) materials: Vec<Material>,
    edge_scale: f32,
}

/// The scene values the edge of `mds-skin` reads, except the model's edge scale.
pub(crate) struct EdgeView {
    pub world: [f32; 16],
    pub camera_position: [f32; 3],
    /// The `camera_fov` that `mds_skin::View` takes.
    pub fov: f32,
    pub self_shadow: bool,
}

fn finish(
    bind: Vec<([f32; 3], [f32; 3])>,
    skin: Skin,
    indices: Vec<u32>,
    materials: Vec<Material>,
) -> Result<Mesh, String> {
    if bind.is_empty() {
        return Err("model has no vertices".into());
    }
    if indices.iter().any(|&i| i as usize >= bind.len()) {
        return Err("an index is outside the vertex list".into());
    }
    if materials
        .iter()
        .any(|m| (m.start + m.count) as usize > indices.len())
    {
        return Err("a material reaches past the index list".into());
    }
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    Ok(Mesh {
        id: NEXT_ID.fetch_add(1, Ordering::Relaxed),
        bind,
        skin,
        indices,
        materials,
        edge_scale: 1.0,
    })
}

impl Mesh {
    /// A PMX model.
    pub fn from_pmx(pmx: &Pmx) -> Result<Mesh, String> {
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
                flags: m.flags,
                start,
                count,
            });
            start = start.checked_add(count).ok_or("face count overflows")?;
        }
        let bind = pmx
            .vertices
            .iter()
            .map(|v| (v.position, v.normal))
            .collect();
        finish(bind, Skin::from_pmx(pmx)?, indices, materials)
    }

    /// A PMD model. Materials with an alpha below 1 are drawn double sided, and every material
    /// casts the ground shadow.
    pub fn from_pmd(pmd: &Pmd) -> Result<Mesh, String> {
        let indices = pmd.indices.iter().map(|&i| u32::from(i)).collect();
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmd.materials {
            materials.push(Material {
                flags: (if m.diffuse[3] < 1.0 {
                    FLAG_DOUBLE_SIDED
                } else {
                    0
                }) | if m.edge != 0 { FLAG_EDGE } else { 0 }
                    | FLAG_GROUND_SHADOW,
                start,
                count: m.face_vertex_count,
            });
            start = start
                .checked_add(m.face_vertex_count)
                .ok_or("face count overflows")?;
        }
        let bind = pmd
            .vertices
            .iter()
            .map(|v| (v.position, v.normal))
            .collect();
        finish(bind, Skin::from_pmd(pmd)?, indices, materials)
    }

    /// The model's edge thickness, `edge_scale` of its PMM model record (1 when a mesh is made).
    pub fn set_edge_scale(&mut self, scale: f32) {
        self.edge_scale = scale;
    }

    pub(crate) fn vertex_count(&self) -> usize {
        self.bind.len()
    }

    /// Bounding box of the bind pose.
    pub(crate) fn bounds(&self) -> ([f32; 3], [f32; 3]) {
        let (mut min, mut max) = ([f32::MAX; 3], [f32::MIN; 3]);
        for (p, _) in &self.bind {
            for i in 0..3 {
                min[i] = min[i].min(p[i]);
                max[i] = max[i].max(p[i]);
            }
        }
        (min, max)
    }

    /// Side of the Z axis the mean vertex normal points to: +1 or -1.
    pub(crate) fn front(&self) -> f32 {
        let z: f32 = self.bind.iter().map(|(_, n)| n[2]).sum();
        if z > 0.0 {
            1.0
        } else {
            -1.0
        }
    }

    /// The skin after the material morphs and the vertex pass of `pose` (`None`: the bind pose).
    /// A pose that is shorter or longer than the model's bone and morph tables is padded with the
    /// identity and zero weights, or cut.
    pub(crate) fn skinned(&self, pose: Option<&Pose>, view: &EdgeView) -> Skin {
        let mut skin = self.skin.clone();
        let mut weights = vec![0.0; skin.morph_count()];
        let mut bones = vec![Mat4::IDENTITY; skin.bone_count()];
        if let Some(pose) = pose {
            for (w, &v) in weights.iter_mut().zip(&pose.morphs) {
                *w = v;
            }
            for (b, &m) in bones.iter_mut().zip(&pose.skin) {
                *b = Mat4(m);
            }
        }
        skin.apply_morphs(&weights);
        skin.update(
            &weights,
            &bones,
            &mds_skin::View {
                world: Mat4(view.world),
                camera_position: view.camera_position,
                camera_fov: view.fov,
                edge_scale: self.edge_scale,
                self_shadow: view.self_shadow,
            },
        );
        skin
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const VIEW: EdgeView = EdgeView {
        world: Mat4::IDENTITY.0,
        camera_position: [0.0; 3],
        fov: 30.0,
        self_shadow: false,
    };

    fn fixture(name: &str) -> Pmx {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust")
            .join(name);
        Pmx::read(&std::fs::read(path).unwrap()).unwrap()
    }

    #[test]
    fn bind_pose_is_the_file_and_a_vertex_morph_moves_it() {
        let pmx = fixture("morph4.pmx");
        let mesh = Mesh::from_pmx(&pmx).unwrap();
        let bind = mesh.skinned(None, &VIEW);
        let stride = bind.stride();
        for (i, v) in pmx.vertices.iter().enumerate() {
            assert_eq!(bind.main[stride * i..][..3], v.position, "vertex {i}");
        }
        let (k, m) = pmx
            .morphs
            .iter()
            .enumerate()
            .find(|(_, m)| m.kind == 1)
            .expect("a vertex morph");
        let mds_formats::pmx::Offsets::Vertex(offsets) = &m.offsets else {
            panic!("vertex morph without vertex offsets")
        };
        let mut morphs = vec![0.0; pmx.morphs.len()];
        morphs[k] = 1.0;
        let pose = Pose {
            morphs,
            ..Pose::default()
        };
        let moved = mesh.skinned(Some(&pose), &VIEW);
        let (v, d) = offsets[0];
        let v = v as usize;
        let (a, b) = (&bind.main[stride * v..], &moved.main[stride * v..]);
        assert_ne!(d, [0.0; 3]);
        for c in 0..3 {
            assert!((b[c] - a[c] - d[c]).abs() < 1e-5);
        }
    }
}
