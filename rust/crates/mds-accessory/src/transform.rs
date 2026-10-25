//! The accessory world transform and the shadow decisions of `accessory.cpp`.

use crate::accessory::{Accessory, AccessoryMaterial, AccessoryState};
use mds_math::Mat4;

/// The bone an accessory follows, from the parent model's current pose: the
/// bone's `position` (its rest position) and `matInit` (its world matrix).
#[derive(Clone, Copy, Debug)]
pub struct ParentBone {
    pub position: [f32; 3],
    pub matrix: Mat4,
}

/// `kModelSlotCount` on x64.
pub const MODEL_SLOTS: i32 = 255;

/// The bone index `AccessoryPlacement` reads: a negative `parentBone` means bone 0.
pub fn parent_bone_index(parent_bone: i32) -> usize {
    parent_bone.max(0) as usize
}

/// The model slot `AccessoryPlacement` follows, or `None` when `parentModel` is
/// outside `0..255` (including `-1`, no parent).
pub fn parent_model_slot(parent_model: i32) -> Option<usize> {
    (0..MODEL_SLOTS)
        .contains(&parent_model)
        .then_some(parent_model as usize)
}

/// `D3DXMatrixScaling`.
fn scaling(s: f32) -> Mat4 {
    let mut m = Mat4::IDENTITY;
    (m.0[0], m.0[5], m.0[10]) = (s, s, s);
    m
}

/// `AccessoryPlacement`: `S(scale * 10) * Rz * Rx * Ry * T(position)`, and with a
/// parent bone also `* T(bone.position) * bone.matrix`. Row vectors, as D3D.
///
/// `parent` is `None` when the accessory has no usable parent: `parentModel` outside
/// the slots (see [`parent_model_slot`]) or an empty model slot.
pub fn world_matrix(state: &AccessoryState, parent: Option<&ParentBone>) -> Mat4 {
    let [rx, ry, rz] = state.rotation;
    let [px, py, pz] = state.position;
    let mut world = scaling(state.scale * 10.0);
    for part in [
        Mat4::rotation_z(rz),
        Mat4::rotation_x(rx),
        Mat4::rotation_y(ry),
        Mat4::translation(px, py, pz),
    ] {
        world = Mat4::multiply(&world, &part);
    }
    if let Some(bone) = parent {
        let [x, y, z] = bone.position;
        world = Mat4::multiply(&world, &Mat4::translation(x, y, z));
        world = Mat4::multiply(&world, &bone.matrix);
    }
    world
}

/// `RenderAccessoriesShadow` (`accessory.cpp:793`): whether the accessory is drawn
/// into the shadow map.
pub fn casts_shadow_map(state: &AccessoryState) -> bool {
    state.visible && state.shadow_enabled && !state.additive_blend
}

/// `RenderAccessoriesShadow`: the subsets drawn into the shadow map skip a material
/// whose diffuse alpha is exactly 0.98 (`0.9800000190734863f`).
pub fn shadow_map_subsets(acc: &Accessory) -> impl Iterator<Item = usize> + '_ {
    acc.materials
        .iter()
        .enumerate()
        .filter(|(_, m)| m.diffuse[3] != 0.98f32)
        .map(|(i, _)| i)
}

/// `RenderAccessoriesProjectedGroundShadowGeometry` (`accessory.cpp:769`) checks the
/// shadow flag; `RenderAccessoryFixedOne` then returns early for an invisible
/// accessory (line 223).
pub fn casts_projected_shadow(state: &AccessoryState) -> bool {
    state.visible && state.shadow_enabled
}

/// The material `RenderAccessoryFixedOne` sets for each subset of a projected ground
/// shadow, as `(diffuse alpha, ambient rgba, specular alpha)`; everything else is zero.
/// `gray` is `ProjectedShadowAmbientIntensity`.
pub fn projected_shadow_material(gray: f32) -> ([f32; 4], [f32; 4], [f32; 4]) {
    ([0.0, 0.0, 0.0, 0.7f32], [gray; 4], [0.0, 0.0, 0.0, 1.0])
}

/// The diffuse alpha `RenderAccessoryFixedOne` sends to the device for one material.
pub fn drawn_alpha(material: &AccessoryMaterial, opacity: f32) -> f32 {
    material.diffuse[3] * opacity
}
