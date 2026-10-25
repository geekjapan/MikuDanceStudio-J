//! The per-frame vertex buffers and material values of a model, computed on
//! the CPU as the C++ x64 app computes them, bit for bit.
//!
//! A port of `src/model/model_skinning.cpp` (`UpdateModelVertexBuffers`: the
//! vertex and UV morph pass, BDEF1, BDEF2, BDEF4, SDEF, the PMX edge and the
//! PMD edge) and of the material part of `src/model/morph_apply.cpp`
//! (`ModelApplyMorphs`), with the tables the loaders build for them
//! (`src/model/pmx_load.cpp` `LoadPMX`, `src/model/pmd_load.cpp`
//! `ModelLoadPMD`). The bone part of `ModelApplyMorphs` is
//! `mds_pose::pose::apply_morphs`.
//!
//! * [`Skin::from_pmx`], [`Skin::from_pmd`]: the load (`load.rs`).
//! * [`Skin::apply_morphs`]: material morphs (`morph.rs`).
//! * [`Skin::update`]: vertex and UV morphs, then skinning (`skinning.rs`).
//!
//! The skinning matrix of a bone is `BoneRecord::matInit`, which
//! `mds_pose::model::Bone::mat_init` holds after the pose pass. The morph
//! weights are `MorphRecord::value`. `tests/skin_check.rs` compares every
//! buffer with the C++ harness `tools/skin_check`.
//!
//! QDEF vertices keep the position and normal of the last frame that wrote
//! them, as in the C++ (its workers have no QDEF branch). Not ported: the
//! `MIKUDANCESTUDIO_DIAG` buffer dump and the PMX shrink edge of vertices
//! without edge data, which the loader never leaves.

mod load;
mod morph;
mod skinning;

pub use mds_math::Mat4;

/// `EdgeVertex`: one record of the edge (outline) vertex buffer.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct EdgeVertex {
    pub position: [f32; 3],
    /// `A8R8G8B8`.
    pub diffuse: u32,
}

/// The fields of `ModelMaterialRecord` that the morphs and the edge read or
/// write. [`Skin::apply_morphs`] writes all of them except `diffuse[0..3]`
/// and `diffuse_mirror[3]`, which keep the file values.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Material {
    pub diffuse: [f32; 4],
    pub diffuse_mirror: [f32; 4],
    pub specular: [f32; 3],
    pub ambient: [f32; 3],
    pub specular_power: f32,
    pub edge_color: [f32; 4],
    pub edge_size: f32,
}

/// `MaterialMorphChannels`: the 28 channels of a material morph.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Channels {
    pub diffuse: [f32; 4],
    pub specular: [f32; 3],
    pub specular_power: f32,
    pub ambient: [f32; 3],
    pub edge_color: [f32; 4],
    pub edge_size: f32,
    pub texture_tint: [f32; 4],
    pub sphere_tint: [f32; 4],
    pub toon_tint: [f32; 4],
}

/// The scene values the edge reads.
#[derive(Clone, Copy, Debug)]
pub struct View {
    /// The frame world matrix of the model.
    pub world: Mat4,
    pub camera_position: [f32; 3],
    pub camera_fov: f32,
    /// `ModelRecord::edgeScale`, the edge thickness of the model (1 by default).
    pub edge_scale: f32,
    /// Self-shadow on: the PMX edge color gets an opaque alpha.
    pub self_shadow: bool,
}

/// `PmxVertex`, the working vertex of a PMX model.
#[derive(Clone, Debug)]
struct PmxVertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
    additional_uv: [[f32; 4]; 4],
    /// 0 BDEF1, 1 BDEF2, 2 BDEF4, 3 SDEF; anything else is not skinned.
    kind: u8,
    bones: [i32; 4],
    weights: [f32; 4],
    /// SDEF C, and R0 and R1 relative to the weighted pivot.
    sdef: [[f32; 3]; 3],
    edge_scale: f32,
    /// The material with the smallest edge size among those using the vertex.
    material: usize,
}

/// `PmdVertex`.
#[derive(Clone, Debug)]
struct PmdVertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
    bones: [i16; 2],
    weight: i8,
    edge_disabled: u8,
}

#[derive(Clone, Debug)]
enum Vertices {
    Pmx(Vec<PmxVertex>),
    Pmd(Vec<PmdVertex>),
}

/// `PmxMaterialMorphEntry`.
#[derive(Clone, Debug)]
struct MaterialOffset {
    /// `None` is every material (index -1).
    material: Option<usize>,
    additive: bool,
    channels: Channels,
}

/// The parts of `MorphRecord` the vertex buffers and materials read.
#[derive(Clone, Debug, Default)]
struct Morph {
    kind: u8,
    /// Kind 1 (PMD: every morph after the base): vertex and offset.
    vertex: Vec<(usize, [f32; 3])>,
    /// Kinds 3 to 7: vertex and offset.
    uv: Vec<(usize, [f32; 4])>,
    /// Kind 0: morph and weight.
    group: Vec<(usize, f32)>,
    /// Kind 8.
    material: Vec<MaterialOffset>,
}

/// One model's vertex buffers, materials and the tables that produce them.
#[derive(Clone, Debug)]
pub struct Skin {
    vertices: Vertices,
    additional_uvs: usize,
    bone_positions: Vec<[f32; 3]>,
    morphs: Vec<Morph>,
    /// The base vertex morph table: vertex and the position it restores.
    base: Vec<(usize, [f32; 3])>,
    /// The UV and additional UV restore tables of the five PMX UV families.
    uv_base: [Vec<(usize, [f32; 4])>; 5],
    pub materials: Vec<Material>,
    /// The load-time material values the material morphs scale and offset.
    material_base: Vec<Channels>,
    /// The additive and multiplicative material morph pools of the last
    /// [`Skin::apply_morphs`]. The tints reach no material field.
    pub material_add: Vec<Channels>,
    pub material_mul: Vec<Channels>,
    /// The main vertex buffer, [`Skin::stride`] floats per vertex: position,
    /// normal, UV, then each additional UV as 4 floats.
    pub main: Vec<f32>,
    /// The edge vertex buffer.
    pub edge: Vec<EdgeVertex>,
}

impl Skin {
    /// Floats per vertex in [`Skin::main`]: `8 + 4 * additional UVs`.
    pub fn stride(&self) -> usize {
        8 + 4 * self.additional_uvs
    }

    pub fn is_pmx(&self) -> bool {
        matches!(self.vertices, Vertices::Pmx(_))
    }

    pub fn vertex_count(&self) -> usize {
        self.edge.len()
    }

    pub fn morph_count(&self) -> usize {
        self.morphs.len()
    }

    pub fn bone_count(&self) -> usize {
        self.bone_positions.len()
    }
}
