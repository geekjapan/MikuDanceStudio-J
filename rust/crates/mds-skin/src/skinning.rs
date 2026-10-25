//! `UpdateModelVertexBuffers` (`src/model/model_skinning.cpp`): the vertex
//! and UV morph pass, then the PMD worker or the PMX stride worker.
//!
//! Every expression keeps the C++ operand order; float addition does not
//! associate, so the BDEF4 position and normal sums differ on purpose.

use crate::{EdgeVertex, Mat4, Morph, PmdVertex, PmxVertex, Skin, Vertices, View};
use mds_math::Quat;

const ZERO: Mat4 = Mat4([0.0; 16]);
/// `4.5e-05f` and `0.6f` of the edge distance (.rdata `0x383CBE62`, `0x3F19999A`).
const EDGE_PER_DISTANCE: f32 = 4.5e-5;
const EDGE_FOV: f32 = 0.6;
const PMD_SHRINK: f32 = -0.005;

fn transform_position(v: [f32; 3], m: &Mat4) -> [f32; 3] {
    let m = &m.0;
    std::array::from_fn(|c| v[0] * m[c] + v[1] * m[c + 4] + v[2] * m[c + 8] + m[c + 12])
}

fn transform_normal(v: [f32; 3], m: &Mat4) -> [f32; 3] {
    let m = &m.0;
    std::array::from_fn(|c| v[0] * m[c] + v[1] * m[c + 4] + v[2] * m[c + 8])
}

/// `TransformComponent`.
fn component(v: [f32; 3], m: &Mat4, c: usize, position: bool) -> f32 {
    let m = &m.0;
    let mut value = v[0] * m[c];
    value += v[1] * m[c + 4];
    value += v[2] * m[c + 8];
    if position {
        value += m[c + 12];
    }
    value
}

/// `BlendTransformComponent` (x64). The normal adds `0.0`, which turns -0 into +0.
fn blend_component(v: [f32; 3], m0: &Mat4, m1: &Mat4, c: usize, w0: f32, position: bool) -> f32 {
    let w1 = 1.0 - w0;
    let one = |m: &Mat4| {
        let m = &m.0;
        v[0] * m[c] + v[1] * m[c + 4] + v[2] * m[c + 8] + if position { m[c + 12] } else { 0.0 }
    };
    one(m1) * w1 + one(m0) * w0
}

/// `PmxSkinMatrix`: a reference outside the bone table is a zero matrix.
fn matrix(bones: &[Mat4], i: i32) -> &Mat4 {
    usize::try_from(i)
        .ok()
        .and_then(|i| bones.get(i))
        .unwrap_or(&ZERO)
}

/// `BlendSdefQuaternions`: a sign-corrected normalized lerp, not a slerp.
fn blend_quaternions(from: [f32; 4], to: [f32; 4], mut t: f32) -> [f32; 4] {
    let dot = ((to[0] * from[0] + to[3] * from[3]) + to[1] * from[1]) + to[2] * from[2];
    let delta: [f32; 4] = if dot >= 0.0 {
        std::array::from_fn(|i| to[i] - from[i])
    } else {
        t = -t;
        std::array::from_fn(|i| to[i] + from[i])
    };
    let out: [f32; 4] = std::array::from_fn(|i| delta[i] * t + from[i]);
    let length = (((out[0] * out[0] + out[1] * out[1]) + out[2] * out[2]) + out[3] * out[3]).sqrt();
    if length <= 0.0 {
        return [0.0, 0.0, 0.0, 1.0];
    }
    let inverse = 1.0 / length;
    out.map(|x| x * inverse)
}

/// Position and normal of one PMX vertex, or `None` for QDEF and unknown kinds.
fn skin_pmx(v: &PmxVertex, bones: &[Mat4]) -> Option<([f32; 3], [f32; 3])> {
    let m = |k: usize| matrix(bones, v.bones[k]);
    let w = v.weights;
    match v.kind {
        0 => Some((
            transform_position(v.position, m(0)),
            transform_normal(v.normal, m(0)),
        )),
        1 => Some((
            std::array::from_fn(|c| blend_component(v.position, m(0), m(1), c, w[0], true)),
            std::array::from_fn(|c| blend_component(v.normal, m(0), m(1), c, w[0], false)),
        )),
        2 => {
            let sum = |input: [f32; 3], order: [usize; 4], position: bool, c: usize| {
                let mut s = component(input, m(order[0]), c, position) * w[order[0]];
                for &k in &order[1..] {
                    s += component(input, m(k), c, position) * w[k];
                }
                s
            };
            Some((
                std::array::from_fn(|c| sum(v.position, [1, 0, 2, 3], true, c)),
                std::array::from_fn(|c| sum(v.normal, [0, 1, 2, 3], false, c)),
            ))
        }
        3 => {
            let (m0, m1) = (m(0), m(1));
            let w0 = w[0];
            let w1 = 1.0 - w0;
            let [center, r0, r1] = v.sdef;
            let pivot: [f32; 3] = std::array::from_fn(|c| {
                let blended_center =
                    component(center, m0, c, true) * w0 + component(center, m1, c, true) * w1;
                let blended_arms =
                    component(r0, m0, c, false) * w0 + component(r1, m1, c, false) * w1;
                ((blended_arms + blended_center) + blended_center) * 0.5
            });
            let q = blend_quaternions(Quat::from_matrix(m0).0, Quat::from_matrix(m1).0, w1);
            let rotation = Mat4::rotation_quaternion(Quat(q));
            let delta: [f32; 3] = std::array::from_fn(|c| v.position[c] - center[c]);
            Some((
                std::array::from_fn(|c| component(delta, &rotation, c, false) + pivot[c]),
                std::array::from_fn(|c| component(v.normal, &rotation, c, false)),
            ))
        }
        _ => None,
    }
}

/// `cvttss2si`: out of range and NaN give `i32::MIN`.
fn truncate(x: f32) -> i32 {
    if (-2_147_483_648.0..2_147_483_648.0).contains(&x) {
        x as i32
    } else {
        i32::MIN
    }
}

/// `PackPmxEdgeColor`.
fn pack_edge_color(color: [f32; 4], opaque: bool) -> u32 {
    let channel = |x: f32| u32::from(truncate(x * 255.0) as u8);
    let alpha = if opaque { 0xFF } else { channel(color[3]) };
    alpha << 24 | channel(color[0]) << 16 | channel(color[1]) << 8 | channel(color[2])
}

/// One vertex or UV morph's offsets (`AccumPmxVertexMorph`), the group
/// weight multiplied in after the morph weight.
fn accumulate(vertices: &mut [PmxVertex], morph: &Morph, value: f32, group_w: f32) {
    match morph.kind {
        1 => {
            for &(v, offset) in &morph.vertex {
                for (p, o) in vertices[v].position.iter_mut().zip(offset) {
                    *p += o * value * group_w;
                }
            }
        }
        3 => {
            for &(v, offset) in &morph.uv {
                for (p, o) in vertices[v].uv.iter_mut().zip(offset) {
                    *p += o * value * group_w;
                }
            }
        }
        4..=7 => {
            let uv = usize::from(morph.kind) - 4;
            for &(v, offset) in &morph.uv {
                for (p, o) in vertices[v].additional_uv[uv].iter_mut().zip(offset) {
                    *p += o * value * group_w;
                }
            }
        }
        _ => {}
    }
}

impl Skin {
    /// `UpdateModelVertexBuffers`: applies the vertex and UV morphs to the
    /// working vertices and writes [`Skin::main`] and [`Skin::edge`].
    /// `bones` holds one skinning matrix per bone, `weights` one weight per
    /// morph. Run [`Skin::apply_morphs`] first: the PMX edge reads the
    /// morphed materials.
    pub fn update(&mut self, weights: &[f32], bones: &[Mat4], view: &View) {
        assert_eq!(weights.len(), self.morphs.len(), "one weight per morph");
        assert_eq!(
            bones.len(),
            self.bone_positions.len(),
            "one matrix per bone"
        );
        if self.edge.is_empty() {
            return;
        }
        let distance = self.edge_distance(bones, view);
        match &mut self.vertices {
            Vertices::Pmx(vertices) => {
                apply_pmx_morphs(vertices, &self.base, &self.uv_base, &self.morphs, weights);
                if bones.is_empty() || self.materials.is_empty() {
                    return;
                }
                let stride = 8 + 4 * self.additional_uvs;
                for (i, v) in vertices.iter().enumerate() {
                    let main = &mut self.main[stride * i..stride * (i + 1)];
                    if let Some((position, normal)) = skin_pmx(v, bones) {
                        main[0..3].copy_from_slice(&position);
                        main[3..6].copy_from_slice(&normal);
                    }
                    main[6..8].copy_from_slice(&v.uv);
                    for (k, uv) in v.additional_uv[..self.additional_uvs].iter().enumerate() {
                        main[8 + 4 * k..12 + 4 * k].copy_from_slice(uv);
                    }
                    let material = &self.materials[v.material];
                    let edge = &mut self.edge[i];
                    edge.diffuse = pack_edge_color(material.edge_color, view.self_shadow);
                    for c in 0..3 {
                        let mut amount = distance * main[3 + c];
                        amount *= v.edge_scale;
                        amount *= material.edge_size;
                        edge.position[c] = main[c] + amount;
                    }
                }
            }
            Vertices::Pmd(vertices) => {
                apply_pmd_morphs(vertices, &self.base, &self.morphs, weights);
                for (i, v) in vertices.iter().enumerate() {
                    skin_pmd(
                        v,
                        bones,
                        distance,
                        &mut self.main[8 * i..8 * i + 8],
                        &mut self.edge[i],
                    );
                }
            }
        }
    }

    /// `PmdEdgeDistance`, shared by PMD and PMX: the camera distance of the
    /// second bone (the first if there is one) scaled by the field of view
    /// and the edge thickness.
    fn edge_distance(&self, bones: &[Mat4], view: &View) -> f32 {
        let i = usize::from(bones.len() > 1);
        let model_point = match bones.get(i) {
            Some(m) => transform_position(self.bone_positions[i], m),
            None => [0.0; 3],
        };
        let world_point = transform_position(model_point, &view.world);
        let d: [f32; 3] = std::array::from_fn(|c| world_point[c] - view.camera_position[c]);
        let distance = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
        distance * EDGE_PER_DISTANCE * (view.camera_fov * EDGE_FOV + 1.0) * view.edge_scale
    }
}

/// `ApplyPmxVertexMorphs`: restore every morphed component, then add each
/// morph with a nonzero weight, morph 0 included.
fn apply_pmx_morphs(
    vertices: &mut [PmxVertex],
    base: &[(usize, [f32; 3])],
    uv_base: &[Vec<(usize, [f32; 4])>; 5],
    morphs: &[Morph],
    weights: &[f32],
) {
    if morphs.is_empty() {
        return;
    }
    for &(v, position) in base {
        vertices[v].position = position;
    }
    for (family, table) in uv_base.iter().enumerate() {
        for &(v, value) in table {
            match family {
                0 => vertices[v].uv = [value[0], value[1]],
                f => vertices[v].additional_uv[f - 1] = value,
            }
        }
    }
    for (morph, &w) in morphs.iter().zip(weights) {
        if w == 0.0 {
            continue;
        }
        if morph.kind != 0 {
            accumulate(vertices, morph, w, 1.0);
            continue;
        }
        for &(target, group_w) in &morph.group {
            accumulate(vertices, &morphs[target], w, group_w);
        }
    }
}

/// `ApplyPmdVertexMorphs`: restore the base positions, then add every
/// morph after the base with a nonzero weight.
fn apply_pmd_morphs(
    vertices: &mut [PmdVertex],
    base: &[(usize, [f32; 3])],
    morphs: &[Morph],
    weights: &[f32],
) {
    if morphs.is_empty() {
        return;
    }
    for &(v, position) in base {
        vertices[v].position = position;
    }
    for (morph, &w) in morphs.iter().zip(weights).skip(1) {
        if w == 0.0 {
            continue;
        }
        for &(v, offset) in &morph.vertex {
            for (p, o) in vertices[v].position.iter_mut().zip(offset) {
                *p += o * w;
            }
        }
    }
}

/// The PMD worker: BDEF2 by the weight percent, the UV, and the edge pushed
/// out along the normal (or pulled in when the vertex has no edge).
fn skin_pmd(v: &PmdVertex, bones: &[Mat4], distance: f32, main: &mut [f32], edge: &mut EdgeVertex) {
    let w0 = f32::from(v.weight) * 0.01;
    let (m0, m1) = (
        matrix(bones, v.bones[0].into()),
        matrix(bones, v.bones[1].into()),
    );
    for c in 0..3 {
        main[c] = blend_component(v.position, m0, m1, c, w0, true);
        main[3 + c] = blend_component(v.normal, m0, m1, c, w0, false);
    }
    main[6..8].copy_from_slice(&v.uv);
    let amount = if v.edge_disabled != 0 {
        PMD_SHRINK
    } else {
        distance
    };
    for c in 0..3 {
        edge.position[c] = main[c] + main[3 + c] * amount;
    }
}
