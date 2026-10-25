//! The bone update of the x64 app: `ModelApplyMorphs`
//! (`src/model/morph_apply.cpp`, bone morphs only), `SetPhysicsMode`
//! (`src/physics/physics_create.cpp`) and `BoneFrameTransform` with its five
//! phases (`src/model/bone_transform.cpp`): physics-swept locals, standard
//! locals with the append (grant) transforms, the world pass with outside
//! parents, CCD IK, and the post-IK pass.
//!
//! Every D3DX call goes through `mds_math`, every UCRT float function
//! through `mds_crtmath`. Matrix products keep the C++ operand order.

use crate::model::{flag, kind, Bone, IkChain, Model, Selector};
use mds_crtmath::{acosf, asinf, atan2f, cosf, sinf};
use mds_math::{Mat4, Quat, Vec3};

/// The truncated pi `0x4048F5C3`.
const PI_F: f32 = f32::from_bits(0x4048_f5c3);
const EPS: f32 = 1.192_092_9e-7;
/// `0x3FC90FD8`, pi/2 from the truncated float pi.
const HALF_PI: f32 = f32::from_bits(0x3fc9_0fd8);
const KNEE_CLAMP: f32 = 1.535_889;
/// 左ひざ, 右ひざ in SJIS.
const KNEES: [[u8; 6]; 2] = [
    [0x8d, 0xb6, 0x82, 0xd0, 0x82, 0xb4],
    [0x89, 0x45, 0x82, 0xd0, 0x82, 0xb4],
];

fn mul(a: &Mat4, b: &Mat4) -> Mat4 {
    Mat4::multiply(a, b)
}

fn t(x: f32, y: f32, z: f32) -> Mat4 {
    Mat4::translation(x, y, z)
}

fn rot_quat(q: [f32; 4]) -> Mat4 {
    Mat4::rotation_quaternion(Quat(q))
}

/// `D3DXQuaternionMultiply(out, a, b)`.
fn qmul(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    Quat::multiply(Quat(a), Quat(b)).0
}

fn norm3(v: [f32; 3]) -> [f32; 3] {
    Vec3(v).normalize().0
}

/// The other models of the scene, for outside parents.
pub struct Others<'a> {
    pub models: [&'a [Model]; 2],
}

impl Others<'static> {
    /// No model table (`modelSlots == nullptr` at load time).
    pub const NONE: Others<'static> = Others { models: [&[], &[]] };
}

impl Others<'_> {
    fn bone(&self, slot: i32, bone: i32) -> Option<(Mat4, [f32; 3])> {
        let model = self
            .models
            .iter()
            .flat_map(|m| m.iter())
            .find(|m| i32::from(m.slot) == slot)?;
        let b = &model.bones[bone as usize];
        Some((b.mat_extra, b.position))
    }
}

/// `T(-p) * local * T(offset) * T(p)`, as three products.
fn sandwich(local: Mat4, position: [f32; 3], offset: [f32; 3]) -> Mat4 {
    let cur = mul(&t(-position[0], -position[1], -position[2]), &local);
    let local = mul(&cur, &t(offset[0], offset[1], offset[2]));
    mul(&local, &t(position[0], position[1], position[2]))
}

/// `quat * rate` about its own axis, through axis-angle: the inherit and
/// co-rotate scaling of 0x493B12, 0x493F1F and 0x4968F3. `scale` maps the
/// angle to the scaled angle.
fn rescale(sq: [f32; 4], scale: impl Fn(f32) -> f32) -> [f32; 4] {
    let mut w = sq[3];
    if w <= 1.0 {
        if w < -1.0 {
            w = -1.0;
        }
    } else {
        w = 1.0;
    }
    let mut angle = acosf(w);
    if w < 0.0 {
        angle -= PI_F;
    }
    let len = (sq[0] * sq[0] + sq[1] * sq[1] + sq[2] * sq[2]).sqrt();
    if angle == 0.0 || len < EPS {
        return [0.0, 0.0, 0.0, 1.0];
    }
    let scaled = scale(angle);
    let s = sinf(scaled) / len;
    [s * sq[0], s * sq[1], s * sq[2], cosf(scaled)]
}

/// `InheritRotQuat`: the source bone's local rotation scaled by `rate`,
/// multiplied onto `q`.
fn inherit_rot(q: [f32; 4], bones: &[Bone], src: i32, rate: f32) -> [f32; 4] {
    let sq = Quat::from_matrix(&bones[src as usize].mat_local).0;
    qmul(rescale(sq, |a| a * rate), q)
}

/// world = local * parent world; `mat_world` is the parent's rotation part.
fn world_from_parent(bones: &mut [Bone], i: usize) {
    let parent = bones[bones[i].parent as usize].mat_init;
    let bone = &mut bones[i];
    bone.mat_init = mul(&bone.mat_local, &parent);
    let mut r = parent;
    r.0[12..16].copy_from_slice(&[0.0, 0.0, 0.0, 1.0]);
    bone.mat_world = r;
}

fn world_pos(bone: &Bone) -> [f32; 3] {
    let m = &bone.mat_init.0;
    let r = bone.position;
    [
        m[0] * r[0] + m[4] * r[1] + m[8] * r[2] + m[12],
        m[1] * r[0] + m[5] * r[1] + m[9] * r[2] + m[13],
        m[2] * r[0] + m[6] * r[1] + m[10] * r[2] + m[14],
    ]
}

fn dot3(a: &[f32], b: &[f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

/// axis = transpose(rotation of `mat_world`) * axis, normalized.
fn project_axis(axis: [f32; 3], bone: &Bone) -> [f32; 3] {
    let r = &bone.mat_world.0;
    norm3([
        dot3(&r[0..3], &axis),
        dot3(&r[4..7], &axis),
        dot3(&r[8..11], &axis),
    ])
}

fn clamp_euler(a: &mut f32, lo: f32, hi: f32, twist: bool) {
    if lo > *a {
        let refl = 2.0 * lo - *a;
        *a = if hi < refl || twist { lo } else { refl };
    }
    if hi < *a {
        let refl = 2.0 * hi - *a;
        *a = if lo > refl || twist { hi } else { refl };
    }
}

fn is_knee(bone: &Bone) -> bool {
    KNEES.iter().any(|k| bone.name[..6] == k[..])
}

fn channel(bone: &Bone, after_physics: u8) -> bool {
    let has = bone.flags & flag::AFTER_PHYSICS != 0;
    if after_physics != 0 {
        has
    } else {
        !has
    }
}

/// The `matExtra` copy gate.
fn copy_gate(bone: &Bone, physics_mode: i32) -> bool {
    !((physics_mode == 1 || (physics_mode >= 2 && bone.physics_disabled == 0))
        && bone.has_rigid_body != 0)
}

/// The append (grant) inputs of phases B and E: the inherited
/// translation, applied to `mat_local` after the rotation.
fn append_translation(bones: &mut [Bone], i: usize) -> [f32; 3] {
    let bone = &bones[i];
    if bone.flags & flag::TRANS_INHERIT == 0 {
        return [0.0; 3];
    }
    let src = &bones[bone.tail_idx as usize];
    let r = bone.inherit_ratio;
    let inh = [
        src.physics_offset[0] * r,
        src.physics_offset[1] * r,
        src.physics_offset[2] * r,
    ];
    let local = bones[i].mat_local;
    bones[i].mat_local = mul(&local, &t(inh[0], inh[1], inh[2]));
    inh
}

fn finish_local(bones: &mut [Bone], i: usize, inh: [f32; 3]) {
    let bone = &mut bones[i];
    bone.mat_local = sandwich(bone.mat_local, bone.position, bone.physics_offset);
    if bone.flags & flag::TRANS_INHERIT != 0 {
        for (o, d) in bone.physics_offset.iter_mut().zip(inh) {
            *o += d;
        }
    }
}

/// Phase A (0x493A85): bones under an IK-driven append source.
fn physics_swept_locals(bones: &mut [Bone], after: u8, layer: i32) {
    for i in 0..bones.len() {
        let bone = &bones[i];
        if !channel(bone, after) || bone.layer != layer || bone.has_flag == 0 {
            continue;
        }
        let mut q = bone.physics_quat;
        if bone.flags & flag::ROT_INHERIT != 0 {
            q = inherit_rot(q, bones, bone.tail_idx, bone.inherit_ratio);
        }
        bones[i].mat_local = rot_quat(q);
        if bones[i].flags & flag::TRANS_INHERIT != 0 {
            let src = &bones[bones[i].tail_idx as usize];
            let r = bones[i].inherit_ratio;
            let tr = t(
                src.physics_offset[0] * r,
                src.physics_offset[1] * r,
                src.physics_offset[2] * r,
            );
            bones[i].mat_local = mul(&bones[i].mat_local, &tr);
        }
        let bone = &mut bones[i];
        bone.mat_local = sandwich(bone.mat_local, bone.position, bone.physics_offset);
    }
}

/// Phase B (0x493E71): the local matrix of every other bone, with the
/// co-rotate, rotate-grant and inherit (append) transforms.
fn standard_locals(bones: &mut [Bone], after: u8, layer: i32) {
    for i in 0..bones.len() {
        let bone = &bones[i];
        if !channel(bone, after) || bone.layer != layer || bone.has_flag != 0 {
            continue;
        }
        if bone.kind == kind::UNDER_IK {
            bones[i].rot_quat2 = [0.0, 0.0, 0.0, 1.0];
        }
        if bones[i].kind == kind::CO_ROTATE {
            let sq = bones[bones[i].tail_bone as usize].physics_quat;
            let rate = bones[i].tail_idx as f32;
            bones[i].physics_quat = rescale(sq, |a| (rate * a) / 100.0);
        }
        let bone = &bones[i];
        let mut q = bone.physics_quat;
        if bone.kind == kind::ROTATE_GRANT {
            q = qmul(bones[bone.tail_idx as usize].physics_quat, q);
        }
        if bone.flags & flag::ROT_INHERIT != 0 {
            q = inherit_rot(q, bones, bone.tail_idx, bone.inherit_ratio);
        }
        bones[i].mat_local = rot_quat(q);
        let inh = append_translation(bones, i);
        finish_local(bones, i, inh);
    }
}

/// Phase C (0x49455F): world matrices, with outside parents.
fn world_pass(
    bones: &mut [Bone],
    selectors: &[Selector],
    own_slot: u8,
    others: &Others,
    after: u8,
    layer: i32,
    physics_mode: i32,
) {
    let source = |bones: &[Bone], slot: i32, bone: i32| -> (Mat4, [f32; 3]) {
        if slot == i32::from(own_slot) {
            let b = &bones[bone as usize];
            return (b.mat_extra, b.position);
        }
        others
            .bone(slot, bone)
            .unwrap_or_else(|| panic!("outside parent in empty slot {slot}"))
    };
    for i in 0..bones.len() {
        let bone = &bones[i];
        if !channel(bone, after) || bone.layer != layer {
            continue;
        }
        let parent = bone.parent;
        let ext = bone.slot_index;
        let mut handled = false;
        let mut via_global = false;
        if ext >= 0 {
            let s = selectors[ext as usize];
            if s.linked_model >= 0 {
                let (extra, src_pos) = source(bones, s.linked_model, s.linked_bone);
                let p = bones[i].position;
                let mut e = mul(&t(src_pos[0], src_pos[1], src_pos[2]), &extra);
                e = mul(&t(-p[0], -p[1], -p[2]), &e);
                let bone = &mut bones[i];
                bone.mat_init = mul(&bone.mat_local, &e);
                e.0[12..16].copy_from_slice(&[0.0, 0.0, 0.0, 1.0]);
                bone.mat_world = e;
                handled = true;
            } else if s.linked_model == -1 {
                if parent >= 0 {
                    world_from_parent(bones, i);
                    handled = true;
                } else {
                    via_global = true;
                }
            }
        } else if parent >= 0 {
            world_from_parent(bones, i);
            handled = true;
        } else {
            via_global = true;
        }
        if via_global && selectors[0].linked_model >= 0 {
            let s = selectors[0];
            let (extra, src_pos) = source(bones, s.linked_model, s.linked_bone);
            let mut e = mul(&t(src_pos[0], src_pos[1], src_pos[2]), &extra);
            let bone = &mut bones[i];
            bone.mat_init = mul(&bone.mat_local, &e);
            e.0[12..16].copy_from_slice(&[0.0, 0.0, 0.0, 1.0]);
            bone.mat_world = e;
            handled = true;
        }
        let bone = &mut bones[i];
        if !handled {
            bone.mat_init = bone.mat_local;
            bone.mat_world = Mat4::IDENTITY;
        }
        if copy_gate(bone, physics_mode) {
            bone.mat_extra = bone.mat_init;
        }
    }
}

/// The PMX link axis rules of phase D (twist-limited links, first half of
/// the iterations): hinge, plane, fixed axis, or the projected axis.
/// Returns the axis and the alignment factor.
fn limited_axis(link: &Bone, axis: [f32; 3]) -> ([f32; 3], f32) {
    let r = &link.mat_world.0;
    let [xlo, ylo, zlo] = link.ik_limit_min;
    let [xhi, yhi, zhi] = link.ik_limit_max;
    if ylo != 0.0 || yhi != 0.0 || zlo != 0.0 || zhi != 0.0 {
        if xlo == 0.0 && xhi == 0.0 && zlo == 0.0 && zhi == 0.0 {
            let d = r[4] * axis[0] + r[5] * axis[1] + r[6] * axis[2];
            ([0.0, if d < 0.0 { -1.0 } else { 1.0 }, 0.0], 1.0)
        } else if xlo == 0.0 && xhi == 0.0 && ylo == 0.0 && yhi == 0.0 {
            let d = r[8] * axis[0] + r[9] * axis[1] + r[10] * axis[2];
            ([0.0, 0.0, if d < 0.0 { -1.0 } else { 1.0 }], 1.0)
        } else if link.flags & flag::FIXED_AXIS != 0 {
            fixed_axis(link, axis)
        } else {
            (project_axis(axis, link), 1.0)
        }
    } else {
        let d = r[0] * axis[0] + r[1] * axis[1] + r[2] * axis[2];
        ([if d < 0.0 { -1.0 } else { 1.0 }, 0.0, 0.0], 1.0)
    }
}

fn fixed_axis(link: &Bone, axis: [f32; 3]) -> ([f32; 3], f32) {
    let a = project_axis(axis, link);
    let [fx, fy, fz] = link.axis;
    (link.axis, fy * a[1] + fx * a[0] + fz * a[2])
}

/// The Euler decomposition, limit clamp and rebuild of a twist-limited
/// PMX link (0x495921..0x496429).
fn limit_rotation(link: &Bone, m: &Mat4, twist: bool) -> Mat4 {
    let g = |r: usize, c: usize| m.0[r * 4 + c];
    let clamp = |mut a: f32| {
        let mut c = cosf(a);
        if a.abs() > KNEE_CLAMP {
            a = if a > 0.0 { KNEE_CLAMP } else { -KNEE_CLAMP };
            c = cosf(a);
        }
        (a, c)
    };
    let (lo, hi) = (link.ik_limit_min, link.ik_limit_max);
    let limit = |e: &mut [f32; 3]| {
        for k in 0..3 {
            clamp_euler(&mut e[k], lo[k], hi[k], twist);
        }
    };
    let rx = |e: &[f32; 3]| Mat4::rotation_x(e[0]);
    let ry = |e: &[f32; 3]| Mat4::rotation_y(e[1]);
    let rz = |e: &[f32; 3]| Mat4::rotation_z(e[2]);
    if lo[0] > -HALF_PI && hi[0] < HALF_PI {
        let (a, c) = clamp(asinf(-g(2, 1)));
        let mut e = [
            a,
            atan2f(g(2, 0) / c, g(2, 2) / c),
            atan2f(g(0, 1) / c, g(1, 1) / c),
        ];
        limit(&mut e);
        mul(&mul(&rz(&e), &rx(&e)), &ry(&e))
    } else if lo[1] > -HALF_PI && hi[1] < HALF_PI {
        let (a, c) = clamp(asinf(-g(0, 2)));
        let mut e = [
            atan2f(g(1, 2) / c, g(2, 2) / c),
            a,
            atan2f(g(0, 1) / c, g(0, 0) / c),
        ];
        limit(&mut e);
        mul(&mul(&rx(&e), &ry(&e)), &rz(&e))
    } else {
        let (a, c) = clamp(asinf(-g(1, 0)));
        let mut e = [
            atan2f(g(1, 2) / c, g(1, 1) / c),
            atan2f(g(2, 0) / c, g(0, 0) / c),
            a,
        ];
        limit(&mut e);
        mul(&mul(&ry(&e), &rz(&e)), &rx(&e))
    }
}

/// Phase D (0x494A56): CCD IK.
fn ccd_ik(
    bones: &mut [Bone],
    iks: &[IkChain],
    after: u8,
    layer: i32,
    physics_mode: i32,
    pmx: bool,
) {
    for ik in iks {
        let target = &bones[ik.bone_index as usize];
        if !channel(target, after) || target.layer != layer || ik.enabled == 0 {
            continue;
        }
        let root_i = ik.target_bone as usize;
        let root_parent = &bones[bones[root_i].parent as usize];
        if (physics_mode == 1 || (physics_mode >= 2 && root_parent.physics_disabled == 0))
            && root_parent.has_rigid_body != 0
        {
            continue;
        }
        let eff = world_pos(target);
        {
            let root = &mut bones[root_i];
            root.mat_local = sandwich(
                rot_quat(root.physics_quat),
                root.position,
                root.physics_offset,
            );
        }
        let loops = i32::from(ik.iterations);
        if ik.links.is_empty() {
            continue;
        }
        let twist = loops >> 1;
        let mut iter = 0;
        'iterations: while iter < loops {
            for (li, &link_i) in ik.links.iter().enumerate() {
                let link_i = usize::from(link_i);
                let root_pos = world_pos(&bones[root_i]);
                let link_pos = world_pos(&bones[link_i]);
                let d1 = norm3([
                    link_pos[0] - root_pos[0],
                    link_pos[1] - root_pos[1],
                    link_pos[2] - root_pos[2],
                ]);
                let d2 = norm3([
                    link_pos[0] - eff[0],
                    link_pos[1] - eff[1],
                    link_pos[2] - eff[2],
                ]);
                let (dx, dy, dz) = (d1[0] - d2[0], d1[1] - d2[1], d1[2] - d2[2]);
                if dy * dy + dx * dx + dz * dz < 1e-7 {
                    break 'iterations;
                }
                let mut axis = [
                    d1[1] * d2[2] - d1[2] * d2[1],
                    d1[2] * d2[0] - d1[0] * d2[2],
                    d1[0] * d2[1] - d1[1] * d2[0],
                ];
                let mut align = 1.0f32;
                let link = &bones[link_i];
                if !pmx {
                    if is_knee(link) {
                        let r = &link.mat_world.0;
                        let d = r[0] * axis[0] + r[1] * axis[1] + r[2] * axis[2];
                        axis = [if d >= 0.0 { 1.0 } else { -1.0 }, 0.0, 0.0];
                    } else {
                        axis = project_axis(axis, link);
                    }
                } else if link.twist_enable != 0 && iter < twist {
                    (axis, align) = limited_axis(link, axis);
                } else if link.flags & flag::FIXED_AXIS == 0 {
                    axis = project_axis(axis, link);
                } else {
                    (axis, align) = fixed_axis(link, axis);
                }
                let mut dot = d2[0] * d1[0] + d2[1] * d1[1] + d2[2] * d1[2];
                dot = dot.clamp(-1.0, 1.0);
                let mut half = (acosf(dot) * 0.5) * align;
                let wlim = ((li + 1) as f32 * ik.max_angle) * 2.0;
                if half >= 0.0 {
                    if wlim < half {
                        half = wlim;
                    }
                } else if -wlim > half {
                    half = -wlim;
                }
                let s = sinf(half);
                let rotq = [s * axis[0], s * axis[1], s * axis[2], cosf(half)];
                let link = &mut bones[link_i];
                link.rot_quat2 = qmul(link.rot_quat2, rotq);
                if iter == 0 {
                    link.rot_quat2 = qmul(link.physics_quat, link.rot_quat2);
                }
                let mut rot = rot_quat(link.rot_quat2);
                if pmx && link.twist_enable != 0 {
                    rot = limit_rotation(link, &rot, iter >= twist);
                    link.rot_quat2 = Quat::from_matrix(&rot).0;
                } else if !pmx && is_knee(link) && atan2f(rot.0[9], rot.0[10]) < 0.0 {
                    rot.0[6] = -rot.0[6];
                    rot.0[9] = -rot.0[9];
                    link.rot_quat2[0] = -link.rot_quat2[0];
                }
                link.mat_local = sandwich(rot, link.position, link.physics_offset);
                for &lj in ik.links[..=li].iter().rev() {
                    let lj = usize::from(lj);
                    let b = &bones[lj];
                    if !(b.has_rigid_body != 0 && b.physics_disabled == 0 && physics_mode == 3) {
                        world_from_parent(bones, lj);
                        if copy_gate(&bones[lj], physics_mode) {
                            bones[lj].mat_extra = bones[lj].mat_init;
                        }
                    }
                }
                world_from_parent(bones, root_i);
                if copy_gate(&bones[root_i], physics_mode) {
                    bones[root_i].mat_extra = bones[root_i].mat_init;
                }
            }
            iter += 1;
        }
    }
}

/// Phase E (0x496881): bones of phase A again, after the IK.
fn post_ik(bones: &mut [Bone], after: u8, layer: i32, physics_mode: i32) {
    let source = |b: &Bone| {
        if b.kind == kind::UNDER_IK {
            b.rot_quat2
        } else {
            b.physics_quat
        }
    };
    for i in 0..bones.len() {
        let bone = &bones[i];
        if !channel(bone, after)
            || bone.layer != layer
            || bone.kind == kind::UNDER_IK
            || bone.has_flag == 0
        {
            continue;
        }
        if bone.kind == kind::CO_ROTATE {
            let sq = source(&bones[bone.tail_bone as usize]);
            let rate = bone.tail_idx as f32;
            bones[i].physics_quat = rescale(sq, |a| (rate * a) / 100.0);
        }
        let bone = &bones[i];
        let mut q = bone.physics_quat;
        if bone.kind == kind::ROTATE_GRANT {
            q = qmul(source(&bones[bone.tail_idx as usize]), q);
        }
        if bone.flags & flag::ROT_INHERIT != 0 {
            q = inherit_rot(q, bones, bone.tail_idx, bone.inherit_ratio);
        }
        bones[i].mat_local = rot_quat(q);
        let inh = append_translation(bones, i);
        finish_local(bones, i, inh);
        world_from_parent(bones, i);
        if copy_gate(&bones[i], physics_mode) {
            bones[i].mat_extra = bones[i].mat_init;
        }
    }
}

/// `BoneFrameTransform` for one layer.
fn bone_frame_transform(
    model: &mut Model,
    after: u8,
    layer: i32,
    others: &Others,
    physics_mode: i32,
) {
    let bones = &mut model.bones;
    physics_swept_locals(bones, after, layer);
    standard_locals(bones, after, layer);
    world_pass(
        bones,
        &model.selectors,
        model.slot,
        others,
        after,
        layer,
        physics_mode,
    );
    ccd_ik(bones, &model.iks, after, layer, physics_mode, model.pmx);
    post_ik(bones, after, layer, physics_mode);
}

/// `SetPhysicsMode`: picks each bone's pose source, adds the bone morph
/// offsets (PMX), then runs every transform layer.
pub fn set_physics_mode(model: &mut Model, after: u8, others: &Others, physics_mode: i32) {
    for bone in &mut model.bones {
        let physics = (physics_mode == 1 || (physics_mode >= 2 && bone.physics_disabled == 0))
            && bone.has_rigid_body != 0;
        if physics {
            bone.physics_offset.copy_from_slice(&bone.ik_backup[..3]);
            bone.physics_quat.copy_from_slice(&bone.ik_backup[3..]);
        } else {
            bone.physics_offset = bone.trans;
            bone.physics_quat = bone.rot_quat;
        }
    }
    if model.pmx {
        for record in &model.bone_morph_offsets {
            let bone = &mut model.bones[record.bone_index];
            for (o, d) in bone.physics_offset.iter_mut().zip(record.translation) {
                *o += d;
            }
            bone.physics_quat = qmul(bone.physics_quat, record.rotation);
        }
    }
    for layer in 0..=model.max_layer {
        bone_frame_transform(model, after, layer, others, physics_mode);
    }
}

/// The hand-rolled product of `morph_apply.cpp` (not D3DX):
/// `a * b`, summed left to right.
fn morph_qmul(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    [
        a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
        a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
        a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
        a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
    ]
}

/// `ModelApplyMorphs`, bone morphs only (PMX). Material morphs change only
/// material colours, which the pose does not read.
pub fn apply_morphs(model: &mut Model) {
    if !model.pmx {
        return;
    }
    for r in &mut model.bone_morph_offsets {
        r.translation = [0.0; 3];
        r.rotation = [0.0, 0.0, 0.0, 1.0];
    }
    let Model {
        morphs,
        bone_morph_offsets: work,
        ..
    } = model;
    let mut accumulate = |entries: &[(usize, [f32; 3], [f32; 4])], w: f32, ref_w: f32| {
        for &(slot, translation, rotation) in entries {
            let rec = &mut work[slot];
            let [x, y, z, mut qw] = rotation;
            qw = qw.clamp(-1.0, 1.0); // NaN stays NaN, as with the comiss pair
            let mut angle = acosf(qw);
            if qw < 0.0 {
                angle -= PI_F;
            }
            let len = (x * x + y * y + z * z).sqrt();
            let q = if angle == 0.0 || len < EPS {
                [0.0, 0.0, 0.0, 1.0]
            } else {
                let scaled = (angle * w) * ref_w;
                let s = sinf(scaled) / len;
                [s * x, s * y, s * z, cosf(scaled)]
            };
            rec.rotation = morph_qmul(rec.rotation, q);
            for (o, d) in rec.translation.iter_mut().zip(translation) {
                *o += (d * w) * ref_w;
            }
        }
    };
    for morph in morphs.iter() {
        let w = morph.value;
        if w == 0.0 {
            continue;
        }
        match morph.kind {
            2 => accumulate(&morph.bone_entries, w, 1.0),
            0 => {
                for &(target, ref_w) in &morph.group_entries {
                    let target = &morphs[target];
                    if target.kind == 2 {
                        accumulate(&target.bone_entries, w, ref_w);
                    }
                }
            }
            _ => {}
        }
    }
}
